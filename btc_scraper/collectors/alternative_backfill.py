"""Historical backfill and replay support for the alternative-data pipeline.

This module provides:
- ``AlternativeDataBackfiller``: generates synthetic or replays existing
  raw-store snapshots across a date range to bootstrap historical coverage.
- ``AlternativeDataReplayer``: iterates over stored raw-store files and
  injects each timestamped payload back into a WorldState for backtesting.

Design notes
------------
The raw-store directory (``data/raw_alternative/``) contains one JSON file
per collection run named ``alternative_<ISO-timestamp>.json``.  The backfiller
and replayer operate on this directory so they stay consistent with the
existing persistence layer.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Generator, Iterator, List, Optional

from btc_scraper.collectors.alternative_data import (
    DEFAULT_RAW_STORE_DIR,
    _default_payload,
    normalize_alternative_payload,
)
from btc_scraper.core.paths import build_data_path

logger = logging.getLogger(__name__)

DEFAULT_BACKFILL_DIR = str(build_data_path("raw_alternative"))


# ---------------------------------------------------------------------------
# File-based helpers
# ---------------------------------------------------------------------------

def _timestamp_from_filename(path: Path) -> Optional[datetime]:
    """Parse an ISO timestamp embedded in a raw-store filename."""
    stem = path.stem  # e.g. "alternative_2026-07-01T12_00_00+00_00"
    prefix = "alternative_"
    if not stem.startswith(prefix):
        return None
    ts_str = stem[len(prefix):].replace("_", ":")
    # Restore date separator that was turned into underscore by store logic
    # Format from normalize_alternative_payload: timestamp.replace(':', '_')
    # So "2026-07-01T12_00_00+00_00" → "2026-07-01T12:00:00+00:00"
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return None


def list_raw_store_files(
    raw_store_dir: str | os.PathLike[str] = DEFAULT_BACKFILL_DIR,
) -> List[Path]:
    """Return all raw-store files sorted chronologically."""
    target_dir = Path(raw_store_dir)
    if not target_dir.exists():
        return []
    files = sorted(
        target_dir.glob("alternative_*.json"),
        key=lambda p: _timestamp_from_filename(p) or datetime.min.replace(tzinfo=timezone.utc),
    )
    return files


# ---------------------------------------------------------------------------
# Backfiller
# ---------------------------------------------------------------------------

class AlternativeDataBackfiller:
    """Generate and persist synthetic backfill snapshots for a date range.

    When no historical raw data exists the backfiller produces placeholder
    entries using the default payload so downstream replay / backtest code
    always has a continuous series to iterate over.

    If real raw files already cover a time slot the backfiller skips it
    (no double-writing) unless ``overwrite=True``.
    """

    def __init__(
        self,
        raw_store_dir: str | os.PathLike[str] = DEFAULT_BACKFILL_DIR,
        interval_minutes: int = 60,
    ) -> None:
        self.raw_store_dir = Path(raw_store_dir)
        self.interval_minutes = max(1, interval_minutes)

    # ------------------------------------------------------------------

    def backfill(
        self,
        start: datetime,
        end: datetime,
        source_payload: Optional[Dict[str, Any]] = None,
        overwrite: bool = False,
    ) -> List[Path]:
        """Create synthetic snapshots between *start* and *end*.

        Args:
            start: Start of the backfill window (timezone-aware recommended).
            end: End of the backfill window.
            source_payload: Base payload to clone for each slot. Defaults to
                ``_default_payload()``.
            overwrite: When *True* existing files are overwritten.

        Returns:
            List of paths that were written.
        """
        self.raw_store_dir.mkdir(parents=True, exist_ok=True)
        base = source_payload or _default_payload()
        written: List[Path] = []

        current = start
        previous: Optional[Dict[str, Any]] = None
        while current <= end:
            ts_str = current.isoformat()
            payload = dict(base)
            payload["timestamp"] = ts_str
            normalized = normalize_alternative_payload(
                payload,
                previous_payload=previous,
                raw_store_dir=None,  # We handle the write ourselves
            )
            normalized["timestamp"] = ts_str

            filename = f"alternative_{ts_str.replace(':', '_')}.json"
            target = self.raw_store_dir / filename

            if target.exists() and not overwrite:
                logger.debug("Skipping existing file: %s", target)
            else:
                with open(target, "w", encoding="utf-8") as fh:
                    json.dump(normalized, fh, indent=2, ensure_ascii=False)
                written.append(target)
                logger.debug("Backfilled slot: %s → %s", ts_str, target.name)

            previous = normalized
            current += timedelta(minutes=self.interval_minutes)

        logger.info(
            "Backfill complete: %d files written in %s.",
            len(written),
            self.raw_store_dir,
        )
        return written

    def backfill_days(
        self,
        days: int,
        interval_minutes: int = 60,
        overwrite: bool = False,
    ) -> List[Path]:
        """Convenience wrapper: backfill the last *days* days."""
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        return self.backfill(start, end, overwrite=overwrite)


# ---------------------------------------------------------------------------
# Replayer
# ---------------------------------------------------------------------------

class AlternativeDataReplayer:
    """Replay historical raw-store snapshots in chronological order.

    Iterates over all files in the raw-store directory and emits each
    payload one at a time, optionally filtering by date range.  An optional
    ``on_payload`` callback can be used to inject the payload into a
    WorldState during replay.
    """

    def __init__(
        self,
        raw_store_dir: str | os.PathLike[str] = DEFAULT_BACKFILL_DIR,
    ) -> None:
        self.raw_store_dir = Path(raw_store_dir)

    # ------------------------------------------------------------------

    def iter_payloads(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Yield stored alternative-data payloads in chronological order.

        Args:
            start: Only yield payloads at or after this timestamp.
            end: Only yield payloads at or before this timestamp.

        Yields:
            Deserialized payload dicts.
        """
        files = list_raw_store_files(self.raw_store_dir)
        for path in files:
            ts = _timestamp_from_filename(path)
            if ts is not None:
                # Ensure tzinfo for comparison
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if start is not None:
                    cmp_start = start if start.tzinfo is not None else start.replace(tzinfo=timezone.utc)
                    if ts < cmp_start:
                        continue
                if end is not None:
                    cmp_end = end if end.tzinfo is not None else end.replace(tzinfo=timezone.utc)
                    if ts > cmp_end:
                        continue
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                if isinstance(payload, dict):
                    yield payload
            except Exception as exc:
                logger.warning("Could not load %s: %s", path, exc)

    def replay(
        self,
        on_payload: Callable[[Dict[str, Any]], None],
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> int:
        """Replay all payloads and invoke *on_payload* for each.

        Args:
            on_payload: Callback called with each payload dict.
            start: Optional start filter.
            end: Optional end filter.

        Returns:
            Number of payloads replayed.
        """
        count = 0
        for payload in self.iter_payloads(start=start, end=end):
            try:
                on_payload(payload)
                count += 1
            except Exception as exc:
                logger.warning("on_payload raised for ts=%s: %s", payload.get("timestamp"), exc)
        logger.info("Replay complete: %d payloads processed.", count)
        return count

    def replay_into_world_state(
        self,
        on_world_state: Callable[["Any"], None],  # WorldState
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> int:
        """Replay payloads and inject each into a WorldState.

        The WorldState's ``alternative`` layer is populated from each
        stored payload before *on_world_state* is called.

        Args:
            on_world_state: Callback called with each populated WorldState.
            start: Optional start filter.
            end: Optional end filter.

        Returns:
            Number of world states emitted.
        """
        from btc_scraper.core.world_state import AlternativeLayer, WorldState

        count = 0
        for payload in self.iter_payloads(start=start, end=end):
            ts_raw = payload.get("timestamp")
            try:
                ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.now(timezone.utc)
            except ValueError:
                ts = datetime.now(timezone.utc)

            state = WorldState(timestamp=ts, source="replay", is_snapshot=True)
            alt = state.alternative
            for field_name in AlternativeLayer.__dataclass_fields__:
                if field_name == "updated_at":
                    continue
                val = payload.get(field_name)
                if val is not None:
                    try:
                        setattr(alt, field_name, float(val))
                    except (TypeError, ValueError):
                        pass
            alt.updated_at = ts

            try:
                on_world_state(state)
                count += 1
            except Exception as exc:
                logger.warning("on_world_state raised for ts=%s: %s", ts_raw, exc)

        logger.info("WorldState replay complete: %d states emitted.", count)
        return count

    def list_available_range(self) -> Dict[str, Optional[str]]:
        """Return the earliest and latest timestamps available in the store."""
        files = list_raw_store_files(self.raw_store_dir)
        timestamps = [_timestamp_from_filename(p) for p in files]
        timestamps = [t for t in timestamps if t is not None]
        if not timestamps:
            return {"earliest": None, "latest": None, "count": 0}
        return {
            "earliest": min(timestamps).isoformat(),
            "latest": max(timestamps).isoformat(),
            "count": len(timestamps),
        }
