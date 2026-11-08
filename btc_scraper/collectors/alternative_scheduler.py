"""Production scheduler and orchestration for the alternative-data pipeline.

This module wires up cron-style interval scheduling for the
AlternativeDataCollector so it can be run as a standalone daemon or
embedded inside the main event loop.

Usage (standalone):
    python -m btc_scraper.collectors.alternative_scheduler --interval 300

Usage (embedded):
    from btc_scraper.collectors.alternative_scheduler import AlternativeDataScheduler
    sched = AlternativeDataScheduler(interval_seconds=300)
    sched.start()
    ...
    sched.stop()
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from btc_scraper.collectors.alternative_data import (
    AlternativeDataCollector,
    DEFAULT_FEATURE_SNAPSHOT_PATH,
    DEFAULT_OUTPUT_PATH,
    DEFAULT_RAW_STORE_DIR,
)

logger = logging.getLogger(__name__)

DEFAULT_PARSEBOT_RECENT_CRON = "0 9,11,13,15,17,19 * * 2-6"
DEFAULT_PARSEBOT_ALL_CRON = "30 9 * * 6"
DEFAULT_PARSEBOT_FUND_CRON = "0 10 * * 0"


def resolve_startup_mode(configured: str | None = None) -> str:
    """Resolve alternative-data startup mode: 'cache', 'background', or 'blocking'.

    Defaults to 'cache' in paper/demo or once modes, avoiding network wait on critical startup path.
    """
    if configured:
        val = str(configured).strip().lower()
        if val in ("cache", "background", "blocking"):
            return val
    env_mode = os.getenv("ALTERNATIVE_DATA_STARTUP_MODE")
    if env_mode:
        val = env_mode.strip().lower()
        if val in ("cache", "background", "blocking"):
            return val
    is_paper = os.getenv("BTC_RUNTIME_ENVIRONMENT", "").strip().lower() == "paper"
    is_dry = os.getenv("AUTO_TRADE_DRY_RUN", "").strip().lower() == "true"
    if is_paper or is_dry:
        return "cache"
    return "background"


def _parse_cron_field(raw: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part == "*":
            values.update(range(minimum, maximum + 1))
        elif part.startswith("*/"):
            step = int(part[2:])
            if step <= 0:
                raise ValueError("cron step must be positive")
            values.update(range(minimum, maximum + 1, step))
        elif "-" in part:
            start_raw, end_raw = part.split("-", 1)
            start, end = int(start_raw), int(end_raw)
            if start > end:
                raise ValueError("cron range start must not exceed end")
            values.update(range(start, end + 1))
        else:
            values.add(int(part))
    if not values or min(values) < minimum or max(values) > maximum:
        raise ValueError(f"cron field must be within {minimum}..{maximum}")
    return values


def _latest_due_cron_slot(expression: str, now: datetime) -> str | None:
    """Return the latest configured slot today that is due at ``now``."""
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("cron expression must contain five fields")
    minute_raw, hour_raw, day_raw, month_raw, weekday_raw = fields
    minutes = _parse_cron_field(minute_raw, 0, 59)
    hours = _parse_cron_field(hour_raw, 0, 23)
    days = _parse_cron_field(day_raw, 1, 31)
    months = _parse_cron_field(month_raw, 1, 12)
    weekdays = {value % 7 for value in _parse_cron_field(weekday_raw, 0, 7)}
    cron_weekday = (now.weekday() + 1) % 7  # cron: Sunday=0

    if now.day not in days or now.month not in months or cron_weekday not in weekdays:
        return None

    candidates = [
        now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        for hour in hours
        for minute in minutes
        if (hour, minute) <= (now.hour, now.minute)
    ]
    if not candidates:
        return None
    return max(candidates).isoformat()


class AlternativeDataScheduler:
    """Thread-based production scheduler for alternative-data collection.

    Runs the full collector pipeline at a fixed cadence and calls optional
    callback hooks after each successful or failed collection cycle.
    """

    def __init__(
        self,
        interval_seconds: float = 300.0,
        output_path: Optional[str] = DEFAULT_OUTPUT_PATH,
        raw_store_dir: Optional[str] = DEFAULT_RAW_STORE_DIR,
        feature_snapshot_path: Optional[str] = DEFAULT_FEATURE_SNAPSHOT_PATH,
        on_success: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_failure: Optional[Callable[[Exception], None]] = None,
        retries: int = 2,
        delay_seconds: float = 1.0,
        analysis_symbols: Iterable[str] | None = None,
    ) -> None:
        """
        Args:
            interval_seconds: Seconds between collection runs (default 5 min).
            output_path: Path to persist the normalized payload JSON.
            raw_store_dir: Directory for timestamped raw-store files.
            feature_snapshot_path: Path for the latest feature snapshot export.
            on_success: Optional callback invoked with the payload on success.
            on_failure: Optional callback invoked with the exception on failure.
            retries: Per-collection attempt retries.
            delay_seconds: Delay between retry attempts.
            analysis_symbols: Optional runtime cohort used to scope symbol jobs.
        """
        self.interval_seconds = max(1.0, interval_seconds)
        self.output_path = output_path
        self.raw_store_dir = raw_store_dir
        self.feature_snapshot_path = feature_snapshot_path
        self.on_success = on_success
        self.on_failure = on_failure
        self.retries = retries
        self.delay_seconds = delay_seconds
        self.analysis_symbols = (
            tuple(str(symbol).strip().upper() for symbol in analysis_symbols)
            if analysis_symbols is not None
            else None
        )

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Runtime counters
        self.run_count: int = 0
        self.success_count: int = 0
        self.failure_count: int = 0
        self.last_run_at: Optional[datetime] = None
        self.last_payload: Optional[Dict[str, Any]] = None
        self.last_error: Optional[Exception] = None

        # Parse.bot schedule tracking with slot persistence across restarts
        self._slots_file = self._resolve_slots_file()
        persisted_slots = self._load_persisted_slots()
        self._last_recent_run_slot: Optional[str] = persisted_slots.get("recent")
        self._last_all_run_slot: Optional[str] = persisted_slots.get("all")
        self._last_fund_run_slot: Optional[str] = persisted_slots.get("fund")

    def _resolve_slots_file(self) -> Path:
        from btc_scraper.core.paths import build_data_path
        return build_data_path("parsebot_cron_slots.json")

    def _load_persisted_slots(self) -> dict[str, str]:
        path = self._resolve_slots_file()
        if path.exists():
            try:
                import json
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
            except Exception:
                pass
        return {}

    def _persist_slot(self, state_attr: str, due_slot: str) -> None:
        key_map = {
            "_last_recent_run_slot": "recent",
            "_last_all_run_slot": "all",
            "_last_fund_run_slot": "fund",
        }
        key = key_map.get(state_attr)
        if not key:
            return
        slots = self._load_persisted_slots()
        slots[key] = due_slot
        path = self._resolve_slots_file()
        try:
            import json
            from btc_scraper.core.utils import write_atomic
            path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(str(path), json.dumps(slots, indent=2))
        except Exception as e:
            logger.warning("Could not persist Parse.bot slot %s=%s: %s", key, due_slot, e)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, daemon: bool = True) -> None:
        """Start the background collection thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("AlternativeDataScheduler is already running.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="alternative-data-scheduler",
            daemon=daemon,
        )
        self._thread.start()
        logger.info(
            "AlternativeDataScheduler started (interval=%.0fs).",
            self.interval_seconds,
        )

    def stop(self, timeout: float = 10.0) -> None:
        """Stop the background collection thread gracefully."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        logger.info("AlternativeDataScheduler stopped.")

    def run_startup(self, mode: str | None = None) -> Dict[str, Any]:
        """Execute startup initialization according to the resolved startup mode.

        Modes:
            - 'cache': load cached alternative payload immediately without network wait.
            - 'background': return cached payload immediately and trigger background refresh.
            - 'blocking': execute synchronous network collection (not recommended for startup).
        """
        resolved_mode = resolve_startup_mode(mode)
        logger.info("AlternativeDataScheduler starting with mode: %s", resolved_mode)

        if resolved_mode in ("cache", "background"):
            from btc_scraper.collectors.alternative_data import load_alternative_data
            payload = load_alternative_data(self.output_path)
            self.last_payload = payload
            self.last_run_at = datetime.now(timezone.utc)
            self.success_count += 1

            ts_raw = payload.get("timestamp")
            if ts_raw:
                try:
                    ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    age_sec = (datetime.now(timezone.utc) - ts).total_seconds()
                    logger.info(
                        "Loaded alternative data cache from %s (age=%.1fs, fields=%d)",
                        self.output_path, age_sec, len(payload),
                    )
                except Exception:
                    logger.info("Loaded alternative data cache with unparsed timestamp: %s", ts_raw)
            else:
                logger.info("Alternative data cache missing or empty; using default neutral features.")

            if self.on_success is not None:
                try:
                    self.on_success(payload)
                except Exception:
                    logger.exception("on_success callback raised an exception during startup cache load.")

            if resolved_mode == "background":
                bg_thread = threading.Thread(
                    target=self._collect,
                    kwargs={"force": True, "allow_all_history": False},
                    name="alt-data-startup-bg",
                    daemon=True,
                )
                bg_thread.start()

            return payload
        else:
            return self._collect(force=True, allow_all_history=False)

    def run_once(self, force: bool = True, allow_network: bool = True, allow_all_history: bool = False) -> Dict[str, Any]:
        """Execute a single collection cycle synchronously."""
        if not allow_network:
            return self.run_startup(mode="cache")
        return self._collect(force=force, allow_all_history=allow_all_history)

    def is_running(self) -> bool:
        """Return True if the scheduler thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> Dict[str, Any]:
        """Return a summary of the scheduler's runtime state."""
        return {
            "running": self.is_running(),
            "interval_seconds": self.interval_seconds,
            "run_count": self.run_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_error": str(self.last_error) if self.last_error else None,
        }

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._collect(force=False, allow_all_history=True)
            # Sleep in small increments so stop() is responsive
            elapsed = 0.0
            tick = 1.0
            while elapsed < self.interval_seconds and not self._stop_event.is_set():
                time.sleep(tick)
                elapsed += tick

    def _collect(self, force: bool = False, allow_all_history: bool = True) -> Dict[str, Any]:
        self.run_count += 1
        self.last_run_at = datetime.now(timezone.utc)

        # Trigger scheduled Parse.bot fetch jobs if enabled (Phase D Gap)
        parsebot_enabled = os.getenv("PARSEBOT_ENABLED", "false").strip().lower() == "true"
        if parsebot_enabled:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(os.getenv("ETF_FLOW_TIMEZONE", "Asia/Ho_Chi_Minh"))
                now_tz = datetime.now(tz)
                self._run_scheduled_parsebot_jobs(now_tz, allow_all_history=allow_all_history)

            except Exception as e:
                logger.warning("Error executing scheduled Parse.bot jobs in scheduler loop: %s", e)

        try:
            collector = AlternativeDataCollector(
                output_path=self.output_path,
                retries=self.retries,
                delay_seconds=self.delay_seconds,
                raw_store_dir=self.raw_store_dir,
                feature_snapshot_path=self.feature_snapshot_path,
            )
            payload = collector.collect(force=force)
            self.last_payload = payload
            self.last_error = None
            self.success_count += 1
            logger.info(
                "Alternative data collected successfully (run #%d).",
                self.run_count,
            )
            if self.on_success is not None:
                try:
                    self.on_success(payload)
                except Exception:  # pragma: no cover
                    logger.exception("on_success callback raised an exception.")
            return payload
        except Exception as exc:
            self.last_error = exc
            self.failure_count += 1
            logger.error(
                "Alternative data collection failed (run #%d): %s",
                self.run_count,
                exc,
            )
            if self.on_failure is not None:
                try:
                    self.on_failure(exc)
                except Exception:  # pragma: no cover
                    logger.exception("on_failure callback raised an exception.")
            return {}

    def _run_scheduled_parsebot_jobs(self, now_tz: datetime, allow_all_history: bool = True) -> None:
        """Run the low-frequency Parse.bot jobs due at ``now_tz``.

        With five keys, the default recent schedule runs six times per
        publication day. At the maximum 23 Tue-Sat days in a month, recent,
        weekly all-history, and fund jobs consume at most 429 base requests.
        With one retry for every request, 858 attempts remain below the
        five-key operational guard of 900 attempts.
        """
        from scripts.fetch_parsebot_etf_jobs import (
            fetch_parsebot_etf_all_job,
            fetch_parsebot_etf_recent_job,
            fetch_parsebot_fund_info_job,
        )

        schedules = (
            (
                "recent",
                os.getenv("PARSEBOT_ETF_RECENT_CRON", DEFAULT_PARSEBOT_RECENT_CRON),
                fetch_parsebot_etf_recent_job,
                "_last_recent_run_slot",
            ),
            (
                "all historical",
                os.getenv("PARSEBOT_ETF_ALL_CRON", DEFAULT_PARSEBOT_ALL_CRON),
                fetch_parsebot_etf_all_job,
                "_last_all_run_slot",
            ),
            (
                "fund info",
                os.getenv("PARSEBOT_FUND_INFO_CRON", DEFAULT_PARSEBOT_FUND_CRON),
                fetch_parsebot_fund_info_job,
                "_last_fund_run_slot",
            ),
        )

        for name, expression, job, state_attr in schedules:
            if name == "all historical" and not allow_all_history:
                continue
            try:
                due_slot = _latest_due_cron_slot(expression, now_tz)
            except (TypeError, ValueError) as exc:
                logger.error("Invalid Parse.bot %s cron %r: %s", name, expression, exc)
                continue
            if due_slot is not None and getattr(self, state_attr) != due_slot:
                logger.info(
                    "Scheduler triggering %s Parse.bot job for slot %s",
                    name,
                    due_slot,
                )
                try:
                    if self.analysis_symbols is not None and name != "fund info":
                        supported = (
                            {"BTC", "ETH", "SOL"}
                            if name == "recent"
                            else {"BTC", "ETH"}
                        )
                        job(symbols=tuple(
                            symbol
                            for symbol in self.analysis_symbols
                            if symbol in supported
                        ))
                    else:
                        job()
                    setattr(self, state_attr, due_slot)
                    self._persist_slot(state_attr, due_slot)
                except Exception as job_exc:
                    logger.warning("Parse.bot job %s failed: %s", name, job_exc)


class SchedulerRegistry:
    """Lightweight registry that tracks multiple named schedulers."""

    def __init__(self) -> None:
        self._schedulers: Dict[str, AlternativeDataScheduler] = {}

    def register(self, name: str, scheduler: AlternativeDataScheduler) -> None:
        self._schedulers[name] = scheduler

    def start_all(self) -> None:
        for name, sched in self._schedulers.items():
            sched.start()
            logger.info("Started scheduler: %s", name)

    def stop_all(self, timeout: float = 10.0) -> None:
        for name, sched in self._schedulers.items():
            sched.stop(timeout=timeout)
            logger.info("Stopped scheduler: %s", name)

    def status_all(self) -> Dict[str, Any]:
        return {name: sched.status() for name, sched in self._schedulers.items()}

    def get(self, name: str) -> Optional[AlternativeDataScheduler]:
        return self._schedulers.get(name)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _run_cli() -> None:  # pragma: no cover
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Alternative data collection scheduler")
    parser.add_argument("--interval", type=float, default=300.0, help="Collection interval in seconds (default: 300)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH, help="Output JSON path")
    parser.add_argument("--raw-store", default=DEFAULT_RAW_STORE_DIR, help="Raw store directory")
    parser.add_argument("--snapshot", default=DEFAULT_FEATURE_SNAPSHOT_PATH, help="Feature snapshot path")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    sched = AlternativeDataScheduler(
        interval_seconds=args.interval,
        output_path=args.output,
        raw_store_dir=args.raw_store,
        feature_snapshot_path=args.snapshot,
    )

    if args.once:
        result = sched.run_once()
        print(f"Collected {len(result)} fields.")
        return

    sched.start(daemon=False)
    try:
        while sched.is_running():
            time.sleep(5)
    except KeyboardInterrupt:
        sched.stop()


if __name__ == "__main__":
    _run_cli()
