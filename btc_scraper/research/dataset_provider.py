"""
btc_scraper/research/dataset_provider.py
Phase M2-E: Minimal Historical Dataset Provider.

Provides verified, point-in-time compliant historical candle streams for
M1 ExperimentRunner and downstream feature/label engineering pipelines.
Guarantees integrity verification, deduplication of partition overlap,
and strict prevention of look-ahead leakage.
"""
from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from btc_scraper.research.dataset_manifest import (
    CanonicalDatasetManifest,
    PartitionMetadata,
    TIMEFRAME_SECONDS,
)


class DatasetProviderError(Exception):
    """Base exception for dataset provider errors."""
    pass


class SymbolNotListedError(DatasetProviderError):
    """Raised when evaluation is requested before a symbol's official listing date."""
    pass


class PartitionIntegrityError(DatasetProviderError):
    """Raised when a partition on disk fails checksum validation against the manifest."""
    pass


def _sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _parse_to_iso(dt_str: str) -> str:
    """Parses raw CSV timestamp 'YYYY-MM-DD HH:MM' to ISO UTC 'YYYY-MM-DDTHH:MM:SSZ'."""
    s = dt_str.strip()
    if "T" in s:
        # Already ISO
        return s if s.endswith("Z") else s + "Z"
    dt = datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_to_dt(iso_str: str) -> datetime:
    s = iso_str.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


class HistoricalDatasetProvider:
    """
    Standardized provider that streams verified, point-in-time compliant candle series.
    Enforces manifest SHA-256 verification, deduplication of partition overlaps,
    and prevents future leakage.
    """
    def __init__(
        self,
        manifest: CanonicalDatasetManifest,
        base_dir: Path | str,
        verify_checksums: bool = True,
    ):
        self.manifest = manifest
        self.base_dir = Path(base_dir)
        self.verify_checksums = verify_checksums
        self._checked_hashes: Dict[str, bool] = {}

    def _verify_partition(self, part: PartitionMetadata, full_path: Path) -> None:
        if not full_path.exists():
            raise FileNotFoundError(f"Partition file missing: {full_path}")
        if not self.verify_checksums:
            return
        if self._checked_hashes.get(part.partition_key, False):
            return

        computed = _sha256_file(full_path)
        if computed != part.sha256:
            raise PartitionIntegrityError(
                f"Partition {part.partition_key} checksum mismatch: "
                f"expected {part.sha256}, got {computed}"
            )
        self._checked_hashes[part.partition_key] = True

    def load_candles(
        self,
        symbol: str,
        timeframe: str,
        start_time: str,
        end_time: str,
        include_warmup: bool = False,
        strict_listing: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Loads and verifies a chronological stream of normalized candles.
        
        Args:
            symbol: Ticker symbol (e.g. 'BTC' or 'BTCUSDT').
            timeframe: Candle interval ('15m', '1h', '4h', '1d').
            start_time: ISO UTC start string.
            end_time: ISO UTC end string.
            include_warmup: If True, returns designated warmup bars prior to start_time.
            strict_listing: If True, raises SymbolNotListedError if start_time is before listing.
        """
        clean_sym = symbol.replace("USDT", "")
        if clean_sym not in self.manifest.symbols:
            raise ValueError(f"Symbol '{symbol}' not found in dataset manifest symbols.")
        if timeframe not in self.manifest.timeframes:
            raise ValueError(f"Timeframe '{timeframe}' not supported in dataset manifest.")

        # Check listing metadata
        listing_info = self.manifest.symbol_listing_metadata.get(clean_sym, {})
        first_trading_date = listing_info.get("first_observed_trading_date")
        if first_trading_date and start_time < first_trading_date:
            if strict_listing:
                raise SymbolNotListedError(
                    f"Symbol '{clean_sym}' was not listed at requested start_time {start_time} "
                    f"(First observed trading date: {first_trading_date})."
                )

        tf_seconds = TIMEFRAME_SECONDS.get(timeframe, 60 * 15)

        # 1. Identify partitions intersecting [start_time, end_time]
        matching_parts: List[PartitionMetadata] = []
        for part in self.manifest.partitions.values():
            if part.symbol == clean_sym and part.timeframe == timeframe:
                # Check partition overlap: part.start_time <= end_time and part.end_time >= start_time
                if part.start_time <= end_time and part.end_time >= (
                    start_time if not include_warmup else "2020-01-01T00:00:00Z"
                ):
                    matching_parts.append(part)

        matching_parts.sort(key=lambda p: p.start_time)
        if not matching_parts:
            return []

        # 2. Read and deduplicate records by timestamp across monthly boundaries
        records_by_time: Dict[str, Dict[str, Any]] = {}

        for part in matching_parts:
            full_path = self.base_dir / part.file_path
            self._verify_partition(part, full_path)

            with open(full_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    raw_time = row["time"]
                    iso_open = _parse_to_iso(raw_time)
                    dt_open = _iso_to_dt(iso_open)
                    dt_close = datetime.fromtimestamp(dt_open.timestamp() + tf_seconds, tz=timezone.utc)
                    iso_close = dt_close.strftime("%Y-%m-%dT%H:%M:%SZ")

                    is_warmup_row = row.get("is_warmup") in ("1", 1, True, "True")

                    # If duplicate across monthly warmup boundary: keep the active (non-warmup) record
                    if iso_open in records_by_time:
                        if records_by_time[iso_open]["is_warmup"] and not is_warmup_row:
                            records_by_time[iso_open]["is_warmup"] = False
                        continue

                    # Validate basic OHLC invariants
                    o = float(row["open"])
                    h = float(row["high"])
                    l = float(row["low"])
                    c = float(row["close"])
                    v = float(row["volume"])

                    if h < max(o, c) or l > min(o, c) or v < 0:
                        raise ValueError(f"Corrupt candle record in {part.file_path} at {iso_open}: {row}")

                    records_by_time[iso_open] = {
                        "symbol": f"{clean_sym}USDT",
                        "time": iso_open,            # Canonical open time
                        "open_time": iso_open,       # Point-in-time open
                        "close_time": iso_close,     # Point-in-time close
                        "available_at": iso_close,   # Earliest eligible evaluation timestamp
                        "open": o,
                        "high": h,
                        "low": l,
                        "close": c,
                        "volume": v,
                        "is_warmup": is_warmup_row,
                    }

        # 3. Sort chronologically and apply window bounds
        sorted_times = sorted(records_by_time.keys())
        filtered_candles: List[Dict[str, Any]] = []

        for t in sorted_times:
            candle = records_by_time[t]
            # If warmup included: include warmup rows prior to start_time
            if t < start_time:
                if include_warmup:
                    candle["is_warmup"] = True
                    filtered_candles.append(candle)
            elif t <= end_time:
                filtered_candles.append(candle)

        return filtered_candles

    def get_mtf_context(
        self,
        symbol: str,
        current_timestamp: str,
        higher_timeframes: Sequence[str] = ("1h", "4h", "1d"),
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Retrieves the latest fully closed higher-timeframe candles point-in-time.
        A higher-timeframe candle is only available if candle['close_time'] <= current_timestamp.
        Guarantees zero partial candle / future lookahead leakage.
        """
        context = {}
        for htf in higher_timeframes:
            # Lookback up to 5 days before current_timestamp
            curr_dt = _iso_to_dt(current_timestamp)
            lookback_start = datetime.fromtimestamp(curr_dt.timestamp() - 5 * 86400, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            candles = self.load_candles(
                symbol=symbol,
                timeframe=htf,
                start_time=lookback_start,
                end_time=current_timestamp,
                include_warmup=False,
            )
            # Find the latest candle whose close_time <= current_timestamp
            eligible = [c for c in candles if c["close_time"] <= current_timestamp]
            context[htf] = eligible[-1] if eligible else None

        return context
