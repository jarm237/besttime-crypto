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
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from btc_scraper.collectors.alternative_data import (
    AlternativeDataCollector,
    DEFAULT_FEATURE_SNAPSHOT_PATH,
    DEFAULT_OUTPUT_PATH,
    DEFAULT_RAW_STORE_DIR,
)

logger = logging.getLogger(__name__)


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
        """
        self.interval_seconds = max(1.0, interval_seconds)
        self.output_path = output_path
        self.raw_store_dir = raw_store_dir
        self.feature_snapshot_path = feature_snapshot_path
        self.on_success = on_success
        self.on_failure = on_failure
        self.retries = retries
        self.delay_seconds = delay_seconds

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Runtime counters
        self.run_count: int = 0
        self.success_count: int = 0
        self.failure_count: int = 0
        self.last_run_at: Optional[datetime] = None
        self.last_payload: Optional[Dict[str, Any]] = None
        self.last_error: Optional[Exception] = None

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

    def run_once(self, force: bool = True) -> Dict[str, Any]:
        """Execute a single collection cycle synchronously."""
        return self._collect(force=force)

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
            self._collect(force=False)
            # Sleep in small increments so stop() is responsive
            elapsed = 0.0
            tick = 1.0
            while elapsed < self.interval_seconds and not self._stop_event.is_set():
                time.sleep(tick)
                elapsed += tick

    def _collect(self, force: bool = False) -> Dict[str, Any]:
        self.run_count += 1
        self.last_run_at = datetime.now(timezone.utc)
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
