"""Historical Data Acquisition and Validation Pipeline for Unified Neural Discovery.

Provides offline-cached, point-in-time validated historical OHLCV data
for multi-asset crypto universes (default: Canonical 8-asset Universe).

Guarantees:
  - CAUSAL INTEGRITY: Closed bars only. Timestamp is bar open_time; bar is closed at open_time + interval.
  - ZERO OVERWRITE: Stores data exclusively in `data/historical_unified_replay/`.
    Never touches `data/historical/` or legacy `data/neural_n1_*` directories.
  - VALIDATION: Checks for missing hours, gaps, non-positive values, and timestamp alignment across universe.
  - OFFLINE RESUMABLE CACHE: Caches per-coin hourly data in parquet/csv format to allow fast deterministic offline replay.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from btc_scraper.research.carm_market_data import CANONICAL_UNIVERSE

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORAGE_DIR = REPO_ROOT / "data" / "historical_unified_replay"
BINANCE_SPOT_BASE_URL = "https://api.binance.com"


@dataclass
class DatasetQualityReport:
    """Audit report for historical dataset integrity."""
    symbol: str
    start_time_utc: str
    end_time_utc: str
    total_bars: int
    expected_bars: int
    missing_bars: int
    gap_count: int
    max_gap_hours: float
    duplicate_count: int
    zero_or_negative_prices: int
    is_continuous: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class HistoricalDataLoader:
    """Manages acquisition, local caching, and point-in-time validation of historical market data."""

    def __init__(
        self,
        storage_dir: Optional[Path] = None,
        universe: Optional[Sequence[str]] = None,
        base_url: str = BINANCE_SPOT_BASE_URL,
        request_delay_seconds: float = 0.05,
    ) -> None:
        self.storage_dir = Path(storage_dir or DEFAULT_STORAGE_DIR)
        self.universe = list(universe or CANONICAL_UNIVERSE)
        self.base_url = base_url.rstrip("/")
        self.request_delay_seconds = request_delay_seconds
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def fetch_historical_symbol_klines(
        self,
        symbol: str,
        start_dt: datetime,
        end_dt: datetime,
        interval: str = "1h",
        force_download: bool = False,
    ) -> pd.DataFrame:
        """Fetch complete hourly klines for a symbol, with disk caching in storage_dir."""
        cache_filename = f"{symbol}_{interval}_{start_dt.strftime('%Y%m%d')}_{end_dt.strftime('%Y%m%d')}.parquet"
        cache_path = self.storage_dir / cache_filename

        if cache_path.exists() and not force_download:
            logger.info("Loading cached %s data from %s", symbol, cache_path.name)
            df = pd.read_parquet(cache_path)
            return df

        logger.info("Downloading authentic %s %s klines from %s to %s via Binance Spot API...",
                    symbol, interval, start_dt.isoformat(), end_dt.isoformat())

        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)
        current_start = start_ms

        records: List[Dict[str, Any]] = []

        while current_start < end_ms:
            endpoint = (
                f"{self.base_url}/api/v3/klines?"
                f"symbol={symbol}&interval={interval}&startTime={current_start}&endTime={end_ms}&limit=1000"
            )
            req = urllib.request.Request(
                endpoint,
                headers={
                    "User-Agent": "Besttime-Research-Replay/1.0",
                    "Accept": "application/json",
                },
            )

            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP {resp.status} fetching {symbol}")
                    raw_data = json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                logger.warning("Error fetching %s at %d: %s. Retrying in 1s...", symbol, current_start, e)
                time.sleep(1.0)
                continue

            if not raw_data:
                break

            for row in raw_data:
                # Binance Kline format:
                # 0: Open time, 1: Open, 2: High, 3: Low, 4: Close, 5: Volume, 6: Close time, ...
                open_ts = int(row[0])
                close_ts = int(row[6])
                records.append({
                    "open_time_ms": open_ts,
                    "close_time_ms": close_ts,
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                })

            last_open = int(raw_data[-1][0])
            if last_open <= current_start:
                break
            current_start = int(raw_data[-1][6]) + 1
            if self.request_delay_seconds > 0:
                time.sleep(self.request_delay_seconds)

        if not records:
            raise ValueError(f"No records fetched for {symbol} between {start_dt} and {end_dt}")

        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["open_time_ms"], unit="ms", utc=True)
        df["close_timestamp"] = pd.to_datetime(df["close_time_ms"], unit="ms", utc=True)
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

        # Cache to disk
        df.to_parquet(cache_path, index=False)
        logger.info("Saved %d bars for %s to %s", len(df), symbol, cache_path.name)
        return df

    def audit_dataset_integrity(self, df: pd.DataFrame, symbol: str) -> DatasetQualityReport:
        """Audit continuity, timestamps, and validity of the dataset."""
        if df.empty:
            return DatasetQualityReport(
                symbol=symbol,
                start_time_utc="",
                end_time_utc="",
                total_bars=0,
                expected_bars=0,
                missing_bars=0,
                gap_count=0,
                max_gap_hours=0.0,
                duplicate_count=0,
                zero_or_negative_prices=0,
                is_continuous=False,
            )

        ts = df["timestamp"].sort_values().reset_index(drop=True)
        start_ts = ts.iloc[0]
        end_ts = ts.iloc[-1]

        total_hours = int((end_ts - start_ts).total_seconds() / 3600.0) + 1
        actual_bars = len(df)
        missing_bars = max(0, total_hours - actual_bars)

        # Check gaps
        diffs = ts.diff().dropna()
        gaps = diffs[diffs > timedelta(hours=1)]
        gap_count = len(gaps)
        max_gap = gaps.max().total_seconds() / 3600.0 if not gaps.empty else 1.0

        dup_count = df.duplicated(subset=["timestamp"]).sum()
        non_positive = ((df["open"] <= 0) | (df["high"] <= 0) | (df["low"] <= 0) | (df["close"] <= 0)).sum()

        is_continuous = bool((gap_count == 0) and (dup_count == 0) and (non_positive == 0))

        return DatasetQualityReport(
            symbol=symbol,
            start_time_utc=start_ts.isoformat(),
            end_time_utc=end_ts.isoformat(),
            total_bars=actual_bars,
            expected_bars=total_hours,
            missing_bars=missing_bars,
            gap_count=gap_count,
            max_gap_hours=float(max_gap),
            duplicate_count=int(dup_count),
            zero_or_negative_prices=int(non_positive),
            is_continuous=is_continuous,
        )

    def load_aligned_universe(
        self,
        start_dt: datetime,
        end_dt: datetime,
        interval: str = "1h",
        force_download: bool = False,
    ) -> Tuple[pd.DataFrame, Dict[str, DatasetQualityReport]]:
        """Load and align OHLCV closes across the full universe on common timestamps.

        Returns:
            pivoted_close: DataFrame indexed by timestamp (UTC) with columns = symbols
            reports: Dict of DatasetQualityReport per symbol
        """
        symbol_dfs: Dict[str, pd.DataFrame] = {}
        reports: Dict[str, DatasetQualityReport] = {}

        for sym in self.universe:
            df = self.fetch_historical_symbol_klines(sym, start_dt, end_dt, interval=interval, force_download=force_download)
            report = self.audit_dataset_integrity(df, sym)
            reports[sym] = report
            symbol_dfs[sym] = df.set_index("timestamp")[["open", "high", "low", "close", "volume"]]

        # Intersect timestamps present across all symbols
        common_indices = None
        for sym, df in symbol_dfs.items():
            if common_indices is None:
                common_indices = set(df.index)
            else:
                common_indices &= set(df.index)

        sorted_timestamps = sorted(list(common_indices or []))
        logger.info("Aligned universe across %d common %s timestamps (from %s to %s)",
                    len(sorted_timestamps), interval, sorted_timestamps[0], sorted_timestamps[-1])

        # Build pivot table of close prices
        piv_close = pd.DataFrame(index=sorted_timestamps)
        for sym in self.universe:
            piv_close[sym] = symbol_dfs[sym].loc[sorted_timestamps, "close"]

        # Save manifest
        manifest = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "start_time_utc": sorted_timestamps[0].isoformat(),
            "end_time_utc": sorted_timestamps[-1].isoformat(),
            "interval": interval,
            "total_aligned_bars": len(sorted_timestamps),
            "universe": self.universe,
            "quality_reports": {k: v.to_dict() for k, v in reports.items()},
        }
        manifest_path = self.storage_dir / "dataset_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        return piv_close, reports
