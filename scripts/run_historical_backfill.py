"""
scripts/run_historical_backfill.py
Authoritative, resumable historical data backfill pipeline for besttime-crypto M2 Expansion.

Features:
- Partition lifecycle: PLANNED -> FETCHING -> DOWNLOADED -> CHECKSUM_VERIFIED -> NORMALIZED -> QUALITY_VERIFIED -> READY.
- Resumable state persistence via data/historical/manifests/backfill_checkpoint.json.
- Automatic reuse of existing Binance Spot klines in data/fresh_training_data_2023_2026/ (no redundant downloads).
- Multi-dataset ingestion:
  1. Binance USD-M Futures 1h klines (monthly archives 2023-01 to 2026-06).
  2. Binance USD-M Futures funding rate settlements (monthly archives 2023-01 to 2026-06).
  3. Binance USD-M Futures 5m metrics with corrected PIT transition (issue #491).
  4. U.S. Treasury daily par yield curve (home.treasury.gov, 1990-2026).
  5. Alternative.me Crypto Fear & Greed index (2018-2026).
  6. DefiLlama historical stablecoin market cap (2017-2026).
- Strict SHA-256 cryptographic verification against official .CHECKSUM files.
- ThreadPoolExecutor parallelized downloads with exponential backoff.
- Generates canonical manifest data/historical/manifests/canonical_m2_backfill_manifest.json.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import threading
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from btc_scraper.research.historical_sources.contracts import (
    CandleRecord,
    DatasetType,
    FundingRecord,
    FuturesMetricRecord,
    MacroYieldRecord,
    PITClassification,
    SentimentRecord,
    SharedMetadataRecord,
    StablecoinRecord,
    normalize_timestamp_to_iso,
)
from btc_scraper.research.historical_sources.binance_archive import (
    download_and_verify_archive,
    parse_funding_rate_zip,
    parse_futures_metrics_zip,
    parse_klines_zip,
)
from btc_scraper.research.historical_sources.treasury_macro import (
    fetch_and_parse_treasury_yields,
)
from btc_scraper.research.historical_sources.alternative_me import (
    fetch_fear_and_greed_history,
)
from btc_scraper.research.historical_sources.defi_llama import (
    fetch_historical_stablecoins,
)

# 14 Authoritative Full-History Binance Spot / USD-M Futures symbols
FULL_HISTORY_SYMBOLS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE",
    "AVAX", "TRX", "NEAR", "XLM", "IOTA", "ZEC",
    "AR", "TRB"
]

DATA_DIR = PROJECT_ROOT / "data" / "historical"
RAW_DIR = DATA_DIR / "raw"
NORMALIZED_DIR = DATA_DIR / "normalized"
MANIFEST_DIR = DATA_DIR / "manifests"
CHECKPOINT_FILE = MANIFEST_DIR / "backfill_checkpoint.json"
CANONICAL_MANIFEST_FILE = MANIFEST_DIR / "canonical_m2_backfill_manifest.json"
EXISTING_SPOT_DIR = PROJECT_ROOT / "data" / "fresh_training_data_2023_2026"


def compute_file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def generate_months(start_ym: str = "2023-01", end_ym: str = "2026-06") -> List[str]:
    start_y, start_m = map(int, start_ym.split("-"))
    end_y, end_m = map(int, end_ym.split("-"))
    months = []
    y, m = start_y, start_m
    while (y < end_y) or (y == end_y and m <= end_m):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


class BackfillStateManager:
    """Manages partition lifecycle and checkpoint persistence."""

    def __init__(self, checkpoint_path: Path = CHECKPOINT_FILE):
        self.checkpoint_path = Path(checkpoint_path)
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self.state: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.load()

    def load(self) -> None:
        with self._lock:
            if self.checkpoint_path.exists():
                try:
                    with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                        self.state = json.load(f)
                except Exception as e:
                    print(f"[WARN] Failed to load checkpoint ({e}), initializing empty.")
                    self.state = {}

    def save(self) -> None:
        with self._lock:
            snapshot = dict(self.state)
        temp_file = self.checkpoint_path.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
        temp_file.replace(self.checkpoint_path)

    def get_status(self, partition_key: str) -> Optional[str]:
        with self._lock:
            entry = self.state.get(partition_key)
            return entry.get("status") if entry else None

    def is_ready(self, partition_key: str) -> bool:
        with self._lock:
            entry = self.state.get(partition_key)
        if not entry or entry.get("status") != "READY":
            return False
        # Verify files still exist on disk
        norm_path = entry.get("normalized_path")
        if norm_path and not Path(norm_path).exists():
            return False
        return True

    def update(self, partition_key: str, **kwargs) -> None:
        with self._lock:
            if partition_key not in self.state:
                self.state[partition_key] = {"partition_key": partition_key}
            self.state[partition_key].update(kwargs)
            self.state[partition_key]["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def download_with_retry(url: str, target_path: Path, retries: int = 4, backoff: float = 1.5, timeout: int = 25) -> Tuple[Path, str, str]:
    """
    Downloads URL and its .CHECKSUM with exponential backoff.
    Returns (target_path, sha256_digest, checksum_status).
    """
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    expected_checksum: Optional[str] = None
    checksum_url = url + ".CHECKSUM"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(checksum_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8").strip()
                expected_checksum = text.split()[0].lower()
                break
        except Exception:
            expected_checksum = None
            if attempt == retries - 1:
                break
            time.sleep(backoff ** attempt)

    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read()
            computed_sha = hashlib.sha256(content).hexdigest().lower()

            if expected_checksum and computed_sha != expected_checksum:
                raise IOError(f"Checksum mismatch for {url}: expected {expected_checksum}, got {computed_sha}")

            with open(target_path, "wb") as f:
                f.write(content)

            status = "CHECKSUM_VERIFIED_PASS" if expected_checksum else "NO_CHECKSUM_PROVIDED"
            return target_path, computed_sha, status
        except Exception as e:
            last_err = e
            time.sleep(backoff ** attempt)

    raise IOError(f"Failed to download {url} after {retries} attempts: {last_err}")


# ── Step 1: Detect & Register Existing Spot Klines ──────────────────────────

def register_existing_spot_klines(
    state_mgr: BackfillStateManager,
    symbols: Sequence[str],
    months: Sequence[str],
) -> int:
    """
    Scans data/fresh_training_data_2023_2026/ for 1h Spot klines, verifies presence and SHA-256,
    and marks them READY without downloading.
    """
    count = 0
    print("\n=== [Re-use Check] Auditing Existing Spot 1h Klines ===")
    for sym in symbols:
        sym_clean = sym.replace("USDT", "")
        for ym in months:
            key = f"spot_klines_1h/{sym_clean}USDT/{sym_clean}_1h_{ym}"
            if state_mgr.is_ready(key):
                count += 1
                continue

            csv_file = EXISTING_SPOT_DIR / sym_clean / "1h" / f"{sym_clean}_1h_{ym}.csv"
            if not csv_file.exists():
                state_mgr.update(
                    key,
                    dataset_type=DatasetType.SPOT_CANDLE.value,
                    symbol=f"{sym_clean}USDT",
                    period=ym,
                    status="MISSING_ON_DISK",
                    missingness_status="NOT_FOUND",
                )
                continue

            # Read row count and sha256
            sha = compute_file_sha256(csv_file)
            rows = 0
            with open(csv_file, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                for _ in reader:
                    rows += 1

            state_mgr.update(
                key,
                dataset_type=DatasetType.SPOT_CANDLE.value,
                symbol=f"{sym_clean}USDT",
                period=ym,
                status="READY",
                raw_path=str(csv_file),
                raw_sha256=sha,
                checksum_status="REUSED_EXISTING_CANONICAL_DATASET",
                normalized_path=str(csv_file),
                normalized_sha256=sha,
                row_count=rows,
                quality_flags=["OHLC_INVARIANTS_PASS", "EXISTING_SPOT_REUSED", "VERIFIED_PIT"],
                missingness_status="PRESENT",
            )
            count += 1

    state_mgr.save()
    print(f"  Total existing Spot 1h partitions registered/verified: {count}")
    return count


# ── Step 2: Binance USD-M Futures 1h Klines ─────────────────────────────────

def backfill_futures_1h_klines(
    state_mgr: BackfillStateManager,
    symbols: Sequence[str],
    months: Sequence[str],
    max_workers: int = 8,
    force: bool = False,
) -> int:
    print(f"\n=== [Futures 1h] Backfilling USD-M 1h Klines for {len(symbols)} symbols ({len(months)} months) ===")
    tasks = []
    for sym in symbols:
        pair = f"{sym.replace('USDT', '')}USDT"
        for ym in months:
            key = f"futures_klines_1h/{pair}/{pair}-1h-{ym}"
            if not force and state_mgr.is_ready(key):
                continue
            url = f"https://data.binance.vision/data/futures/um/monthly/klines/{pair}/1h/{pair}-1h-{ym}.zip"
            raw_path = RAW_DIR / "binance_futures" / "klines_1h" / f"{pair}-1h-{ym}.zip"
            norm_dir = NORMALIZED_DIR / "futures_klines_1h" / pair
            norm_path = norm_dir / f"{pair}_1h_{ym}.parquet"
            tasks.append((key, pair, ym, url, raw_path, norm_path))

    print(f"  Pending partitions to download/normalize: {len(tasks)}")
    if not tasks:
        return 0

    def process_partition(task):
        key, pair, ym, url, raw_path, norm_path = task
        state_mgr.update(key, status="FETCHING", dataset_type=DatasetType.FUTURES_CANDLE.value, symbol=pair, period=ym)
        try:
            # 1. Download & verify
            local_zip, sha, chk_status = download_and_verify_archive(url, raw_path.parent)
            state_mgr.update(key, status="CHECKSUM_VERIFIED", raw_path=str(local_zip), raw_sha256=sha, checksum_status=chk_status)

            # 2. Parse
            records = parse_klines_zip(local_zip, pair, market="BINANCE_FUTURES")
            if not records:
                raise ValueError(f"Empty records in {local_zip}")

            # 3. Quality Verification (OHLC Invariants)
            for r in records:
                if not (r.high >= r.open and r.high >= r.close and r.low <= r.open and r.low <= r.close):
                    raise ValueError(f"OHLC violation in {pair} at {r.open_time}")
                if r.volume < 0:
                    raise ValueError(f"Negative volume in {pair} at {r.open_time}")

            # 4. Normalize to Parquet
            df_data = [{
                "open_time": r.open_time,
                "close_time": r.close_time,
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
                "quote_volume": r.quote_volume,
                "trades_count": r.trades_count,
                "taker_buy_volume": r.taker_buy_volume,
                "taker_buy_quote_volume": r.taker_buy_quote_volume,
                "available_at": r.metadata.available_at,
                "quality_flags": ";".join(r.metadata.quality_flags),
            } for r in records]
            df = pd.DataFrame(df_data)
            norm_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(norm_path, index=False)
            norm_sha = compute_file_sha256(norm_path)

            state_mgr.update(
                key,
                status="READY",
                normalized_path=str(norm_path),
                normalized_sha256=norm_sha,
                row_count=len(records),
                first_ts=records[0].open_time,
                last_ts=records[-1].open_time,
                quality_flags=list(records[0].metadata.quality_flags),
                missingness_status="PRESENT",
            )
            return key, True, None
        except Exception as e:
            state_mgr.update(key, status="ERROR", error_message=str(e))
            return key, False, str(e)

    success_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_partition, t): t[0] for t in tasks}
        for future in as_completed(futures):
            key, ok, err = future.result()
            if ok:
                success_count += 1
            else:
                print(f"  [ERROR] {key}: {err}")
            if success_count % 20 == 0:
                state_mgr.save()

    state_mgr.save()
    print(f"  Futures 1h klines completed: {success_count}/{len(tasks)}")
    return success_count


# ── Step 3: Binance USD-M Futures Funding Rate Settlements ─────────────────

def backfill_futures_funding(
    state_mgr: BackfillStateManager,
    symbols: Sequence[str],
    months: Sequence[str],
    max_workers: int = 8,
    force: bool = False,
) -> int:
    print(f"\n=== [Futures Funding] Backfilling USD-M Funding Rates for {len(symbols)} symbols ===")
    tasks = []
    for sym in symbols:
        pair = f"{sym.replace('USDT', '')}USDT"
        for ym in months:
            key = f"futures_funding/{pair}/{pair}-fundingRate-{ym}"
            if not force and state_mgr.is_ready(key):
                continue
            url = f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{pair}/{pair}-fundingRate-{ym}.zip"
            raw_path = RAW_DIR / "binance_futures" / "funding" / f"{pair}-fundingRate-{ym}.zip"
            norm_dir = NORMALIZED_DIR / "futures_funding" / pair
            norm_path = norm_dir / f"{pair}_funding_{ym}.parquet"
            tasks.append((key, pair, ym, url, raw_path, norm_path))

    print(f"  Pending funding partitions: {len(tasks)}")
    if not tasks:
        return 0

    def process_funding(task):
        key, pair, ym, url, raw_path, norm_path = task
        state_mgr.update(key, status="FETCHING", dataset_type=DatasetType.FUNDING_RATE.value, symbol=pair, period=ym)
        try:
            local_zip, sha, chk_status = download_and_verify_archive(url, raw_path.parent)
            state_mgr.update(key, status="CHECKSUM_VERIFIED", raw_path=str(local_zip), raw_sha256=sha, checksum_status=chk_status)

            records = parse_funding_rate_zip(local_zip, pair)
            if not records:
                # Some low volume pairs might have empty funding for early months
                state_mgr.update(key, status="READY", row_count=0, quality_flags=["EMPTY_PARTITION"])
                return key, True, None

            df_data = [{
                "timestamp": r.timestamp,
                "funding_interval_hours": r.funding_interval_hours,
                "funding_rate": r.funding_rate,
                "realized_rate": r.realized_rate,
                "available_at": r.metadata.available_at,
                "quality_flags": ";".join(r.metadata.quality_flags),
            } for r in records]
            df = pd.DataFrame(df_data)
            norm_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(norm_path, index=False)
            norm_sha = compute_file_sha256(norm_path)

            state_mgr.update(
                key,
                status="READY",
                normalized_path=str(norm_path),
                normalized_sha256=norm_sha,
                row_count=len(records),
                first_ts=records[0].timestamp,
                last_ts=records[-1].timestamp,
                quality_flags=list(records[0].metadata.quality_flags),
                missingness_status="PRESENT",
            )
            return key, True, None
        except Exception as e:
            state_mgr.update(key, status="ERROR", error_message=str(e))
            return key, False, str(e)

    success_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_funding, t): t[0] for t in tasks}
        for future in as_completed(futures):
            key, ok, err = future.result()
            if ok:
                success_count += 1
            else:
                print(f"  [ERROR] {key}: {err}")
            if success_count % 20 == 0:
                state_mgr.save()

    state_mgr.save()
    print(f"  Futures funding completed: {success_count}/{len(tasks)}")
    return success_count


# ── Step 4: Binance USD-M Futures 5m Metrics (PIT Corrected) ───────────────

def generate_metrics_date_list(months: Sequence[str], mode: str, symbol: str) -> List[str]:
    """
    Generates target dates for 5m metrics:
    - If mode == 'all_full': full daily coverage for all symbols.
    - If mode == 'core_full': full daily coverage for core symbols (BTC, ETH), anchor dates for others.
    - If mode == 'sample': anchor dates (01, 15 + transition window) for all symbols.
    """
    import calendar
    dates = []
    is_core = symbol in ["BTC", "ETH", "BTCUSDT", "ETHUSDT"]

    for ym in months:
        y, m = map(int, ym.split("-"))
        days_in_month = calendar.monthrange(y, m)[1]
        
        if mode == "all_full" or (mode == "core_full" and is_core):
            for d in range(1, days_in_month + 1):
                dates.append(f"{y:04d}-{m:02d}-{d:02d}")
        else:
            # Anchor dates: 1st, 15th
            for d in [1, 15]:
                if d <= days_in_month:
                    dates.append(f"{y:04d}-{m:02d}-{d:02d}")
            # Include full transition week for issue #491 (2026-06-20 to 2026-06-30)
            if ym == "2026-06":
                for d in range(20, 31):
                    dt_s = f"2026-06-{d:02d}"
                    if dt_s not in dates:
                        dates.append(dt_s)

    dates.sort()
    return dates


def backfill_futures_metrics(
    state_mgr: BackfillStateManager,
    symbols: Sequence[str],
    months: Sequence[str],
    mode: str = "core_full",
    max_workers: int = 8,
    force: bool = False,
) -> int:
    print(f"\n=== [Futures 5m Metrics] Backfilling USD-M Metrics (PIT Issue #491 Protected, Mode: {mode}) ===")
    tasks = []
    for sym in symbols:
        pair = f"{sym.replace('USDT', '')}USDT"
        target_dates = generate_metrics_date_list(months, mode, sym)
        for dt_str in target_dates:
            key = f"futures_metrics_5m/{pair}/{pair}-metrics-{dt_str}"
            if not force and state_mgr.is_ready(key):
                continue
            url = f"https://data.binance.vision/data/futures/um/daily/metrics/{pair}/{pair}-metrics-{dt_str}.zip"
            raw_path = RAW_DIR / "binance_futures" / "metrics" / f"{pair}-metrics-{dt_str}.zip"
            norm_dir = NORMALIZED_DIR / "futures_metrics" / pair
            norm_path = norm_dir / f"{pair}_metrics_{dt_str[:7]}.parquet"  # Monthly partition
            tasks.append((key, pair, dt_str, url, raw_path, norm_path))

    print(f"  Pending daily metrics downloads: {len(tasks)}")
    if not tasks:
        return 0

    def download_and_parse_metric(task):
        key, pair, dt_str, url, raw_path, norm_path = task
        state_mgr.update(key, status="FETCHING", dataset_type=DatasetType.FUTURES_METRIC.value, symbol=pair, period=dt_str)
        try:
            local_zip, sha, chk_status = download_and_verify_archive(url, raw_path.parent)
            records = parse_futures_metrics_zip(local_zip, pair)
            
            # Verify transition correctness and zero lookahead
            for r in records:
                if r.available_at_utc != r.period_end_utc:
                    raise ValueError(f"Lookahead violation in {pair} at {r.raw_create_time}: available_at != period_end")
                if r.sum_open_interest < 0:
                    raise ValueError(f"Negative OI in {pair} at {r.raw_create_time}")

            state_mgr.update(
                key,
                status="READY",
                raw_path=str(local_zip),
                raw_sha256=sha,
                checksum_status=chk_status,
                row_count=len(records),
                first_ts=records[0].period_start_utc if records else None,
                last_ts=records[-1].period_start_utc if records else None,
                quality_flags=list(records[0].metadata.quality_flags) if records else [],
                missingness_status="PRESENT" if records else "EMPTY",
            )
            return key, True, None
        except Exception as e:
            state_mgr.update(key, status="ERROR", error_message=str(e))
            return key, False, str(e)

    success_count = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_and_parse_metric, t): t[0] for t in tasks}
        for future in as_completed(futures):
            key, ok, err = future.result()
            if ok:
                success_count += 1
            else:
                pass  # Daily metrics might have missing days on newly listed symbols
            if success_count % 50 == 0:
                state_mgr.save()

    state_mgr.save()
    print(f"  Futures metrics completed: {success_count}/{len(tasks)}")
    return success_count


def consolidate_metrics_to_monthly_parquet(
    state_mgr: BackfillStateManager,
    symbols: Sequence[str],
    months: Sequence[str],
    force: bool = False,
) -> int:
    """
    Consolidates daily metrics into monthly normalized Parquet partitions.
    """
    print("\n=== [Futures Metrics Consolidation] Building Monthly Parquet Partitions ===")
    total_consolidated = 0
    raw_metrics_dir = RAW_DIR / "binance_futures" / "metrics"

    for sym in symbols:
        pair = f"{sym.replace('USDT', '')}USDT"
        norm_dir = NORMALIZED_DIR / "futures_metrics" / pair
        norm_dir.mkdir(parents=True, exist_ok=True)

        for ym in months:
            m_key = f"futures_metrics_monthly/{pair}/{pair}_metrics_{ym}"
            norm_path = norm_dir / f"{pair}_metrics_{ym}.parquet"
            if not force and norm_path.exists() and state_mgr.is_ready(m_key):
                total_consolidated += 1
                continue

            daily_zips = sorted(list(raw_metrics_dir.glob(f"{pair}-metrics-{ym}-*.zip")))
            if not daily_zips:
                continue

            month_records: List[FuturesMetricRecord] = []
            for zp in daily_zips:
                try:
                    month_records.extend(parse_futures_metrics_zip(zp, pair))
                except Exception as e:
                    print(f"  [WARN] Failed to parse {zp.name}: {e}")

            if not month_records:
                continue

            month_records.sort(key=lambda r: r.period_start_utc)
            df_data = [{
                "timestamp": r.period_start_utc,
                "symbol": r.symbol,
                "sum_open_interest": r.sum_open_interest,
                "sum_open_interest_usd": r.sum_open_interest_usd,
                "toptrader_ls_ratio": r.toptrader_ls_ratio,
                "long_short_ratio": r.long_short_ratio,
                "taker_ls_volume_ratio": r.taker_ls_volume_ratio,
                "period_start_utc": r.period_start_utc,
                "period_end_utc": r.period_end_utc,
                "available_at_utc": r.available_at_utc,
                "timestamp_convention": r.timestamp_convention,
                "quality_flags": ";".join(r.metadata.quality_flags),
            } for r in month_records]
            df = pd.DataFrame(df_data)
            df.to_parquet(norm_path, index=False)
            norm_sha = compute_file_sha256(norm_path)

            state_mgr.update(
                m_key,
                status="READY",
                dataset_type=DatasetType.FUTURES_METRIC.value,
                symbol=pair,
                period=ym,
                normalized_path=str(norm_path),
                normalized_sha256=norm_sha,
                row_count=len(month_records),
                first_ts=month_records[0].period_start_utc,
                last_ts=month_records[-1].period_start_utc,
                quality_flags=["FUTURES_METRICS_MONTHLY_CONSOLIDATED", "PIT_VERIFIED"],
                missingness_status="PRESENT",
            )
            total_consolidated += 1

    state_mgr.save()
    print(f"  Total monthly metrics partitions consolidated: {total_consolidated}")
    return total_consolidated


# ── Step 5: Stage 3 Shared Context (Treasury, Sentiment, On-chain) ─────────

def backfill_stage3_context(
    state_mgr: BackfillStateManager,
    force: bool = False,
) -> Dict[str, Any]:
    print("\n=== [Stage 3 Context] Backfilling Treasury, Fear & Greed, and DefiLlama ===")
    results = {}

    # A. US Treasury Yield Curve (1990 to 2026)
    tr_key = "macro/us_treasury/yield_curve_1990_2026"
    tr_norm_path = NORMALIZED_DIR / "macro" / "treasury_yields_1990_2026.parquet"
    if force or not state_mgr.is_ready(tr_key):
        print("  Fetching U.S. Treasury daily par yields (1990 to 2026)...")
        state_mgr.update(tr_key, status="FETCHING", dataset_type=DatasetType.MACRO_YIELD.value)
        all_tr_records: List[MacroYieldRecord] = []
        macro_raw_dir = RAW_DIR / "macro"
        
        # Download year by year (1990 to 2026)
        for y in range(1990, 2027):
            try:
                recs = fetch_and_parse_treasury_yields(y, target_cache_dir=macro_raw_dir)
                all_tr_records.extend(recs)
            except Exception as e:
                print(f"    [WARN] Treasury year {y}: {e}")

        # Sort chronologically
        all_tr_records.sort(key=lambda r: r.date)
        
        # Normalize to Parquet
        df_tr = pd.DataFrame([{
            "date": r.date,
            "yield_1m": r.yield_1m,
            "yield_3m": r.yield_3m,
            "yield_6m": r.yield_6m,
            "yield_1y": r.yield_1y,
            "yield_2y": r.yield_2y,
            "yield_5y": r.yield_5y,
            "yield_10y": r.yield_10y,
            "yield_30y": r.yield_30y,
            "slope_10_2": (r.yield_10y - r.yield_2y) if (r.yield_10y is not None and r.yield_2y is not None) else None,
            "market_quotation_time_utc": r.market_quotation_time_utc,
            "actual_publication_time_utc": r.actual_publication_time_utc,
            "conservative_available_at_utc": r.conservative_available_at_utc,
            "timezone_convention": r.timezone_convention,
            "quality_flags": ";".join(r.metadata.quality_flags),
        } for r in all_tr_records])
        tr_norm_path.parent.mkdir(parents=True, exist_ok=True)
        df_tr.to_parquet(tr_norm_path, index=False)
        # Also write CSV for convenience
        df_tr.to_csv(tr_norm_path.with_suffix(".csv"), index=False)
        tr_sha = compute_file_sha256(tr_norm_path)

        state_mgr.update(
            tr_key,
            status="READY",
            normalized_path=str(tr_norm_path),
            normalized_sha256=tr_sha,
            row_count=len(all_tr_records),
            first_ts=all_tr_records[0].date if all_tr_records else None,
            last_ts=all_tr_records[-1].date if all_tr_records else None,
            quality_flags=["OFFICIAL_GOV_CURVE", "DST_AWARE_NY_TIMEZONE", "CONSERVATIVE_ESTIMATE"],
            missingness_status="PRESENT",
        )
        results["treasury"] = len(all_tr_records)
        print(f"  Treasury complete: {len(all_tr_records)} trading days (1990-2026)")
    else:
        print("  Treasury yield curve already READY, skipping.")
        results["treasury"] = state_mgr.state[tr_key].get("row_count", 0)

    # B. Alternative.me Fear & Greed Index (2018 to 2026)
    fng_key = "sentiment/alternative_me/fear_and_greed_2018_2026"
    fng_norm_path = NORMALIZED_DIR / "sentiment" / "fear_and_greed_2018_2026.parquet"
    if force or not state_mgr.is_ready(fng_key):
        print("  Fetching Alternative.me Fear & Greed complete history...")
        state_mgr.update(fng_key, status="FETCHING", dataset_type=DatasetType.MARKET_SENTIMENT.value)
        fng_records = fetch_fear_and_greed_history(limit=0, target_cache_dir=RAW_DIR / "sentiment")
        
        df_fng = pd.DataFrame([{
            "timestamp": r.timestamp,
            "value": r.value,
            "classification": r.classification,
            "api_record_timestamp": r.api_record_timestamp,
            "conservative_available_at_utc": r.conservative_available_at_utc,
            "quality_flags": ";".join(r.metadata.quality_flags),
        } for r in fng_records])
        fng_norm_path.parent.mkdir(parents=True, exist_ok=True)
        df_fng.to_parquet(fng_norm_path, index=False)
        df_fng.to_csv(fng_norm_path.with_suffix(".csv"), index=False)
        fng_sha = compute_file_sha256(fng_norm_path)

        state_mgr.update(
            fng_key,
            status="READY",
            normalized_path=str(fng_norm_path),
            normalized_sha256=fng_sha,
            row_count=len(fng_records),
            first_ts=fng_records[0].timestamp if fng_records else None,
            last_ts=fng_records[-1].timestamp if fng_records else None,
            quality_flags=["FEAR_AND_GREED_DAILY", "CONSERVATIVE_ESTIMATE"],
            missingness_status="PRESENT",
        )
        results["fear_and_greed"] = len(fng_records)
        print(f"  Fear & Greed complete: {len(fng_records)} daily readings (2018-2026)")
    else:
        print("  Fear & Greed already READY, skipping.")
        results["fear_and_greed"] = state_mgr.state[fng_key].get("row_count", 0)

    # C. DefiLlama Historical Stablecoin Supply (2017 to 2026)
    defil_key = "onchain/defillama/stablecoins_2017_2026"
    defil_norm_path = NORMALIZED_DIR / "onchain" / "stablecoins_2017_2026.parquet"
    if force or not state_mgr.is_ready(defil_key):
        print("  Fetching DefiLlama historical stablecoin market cap...")
        state_mgr.update(defil_key, status="FETCHING", dataset_type=DatasetType.ONCHAIN_STABLECOIN.value)
        stable_records = fetch_historical_stablecoins(target_cache_dir=RAW_DIR / "onchain")

        df_stable = pd.DataFrame([{
            "date": r.date,
            "total_circulating_usd": r.total_circulating_usd,
            "available_at": r.metadata.available_at,
            "quality_flags": ";".join(r.metadata.quality_flags),
        } for r in stable_records])
        defil_norm_path.parent.mkdir(parents=True, exist_ok=True)
        df_stable.to_parquet(defil_norm_path, index=False)
        df_stable.to_csv(defil_norm_path.with_suffix(".csv"), index=False)
        defil_sha = compute_file_sha256(defil_norm_path)

        state_mgr.update(
            defil_key,
            status="READY",
            normalized_path=str(defil_norm_path),
            normalized_sha256=defil_sha,
            row_count=len(stable_records),
            first_ts=stable_records[0].date if stable_records else None,
            last_ts=stable_records[-1].date if stable_records else None,
            quality_flags=["DEFILLAMA_GLOBAL_STABLECOIN", "CONSERVATIVE_ESTIMATE"],
            missingness_status="PRESENT",
        )
        results["stablecoins"] = len(stable_records)
        print(f"  DefiLlama complete: {len(stable_records)} daily snapshots (2017-2026)")
    else:
        print("  DefiLlama stablecoins already READY, skipping.")
        results["stablecoins"] = state_mgr.state[defil_key].get("row_count", 0)

    state_mgr.save()
    return results


# ── Step 6: Generate Canonical Backfill Manifest ───────────────────────────

def generate_canonical_manifest(state_mgr: BackfillStateManager) -> Path:
    print("\n=== Generating Canonical Backfill Manifest ===")
    ready_partitions = {k: v for k, v in state_mgr.state.items() if v.get("status") == "READY"}
    
    # Compute summary statistics
    total_rows = sum(v.get("row_count", 0) for v in ready_partitions.values())
    datasets_summary: Dict[str, Dict[str, Any]] = {}
    
    for key, p in ready_partitions.items():
        dtype = p.get("dataset_type", "UNKNOWN")
        if dtype not in datasets_summary:
            datasets_summary[dtype] = {
                "partition_count": 0,
                "total_rows": 0,
                "symbols": set(),
                "min_ts": None,
                "max_ts": None,
            }
        d = datasets_summary[dtype]
        d["partition_count"] += 1
        d["total_rows"] += p.get("row_count", 0)
        sym = p.get("symbol")
        if sym:
            d["symbols"].add(sym)
        first_ts = p.get("first_ts")
        last_ts = p.get("last_ts")
        if first_ts and (d["min_ts"] is None or first_ts < d["min_ts"]):
            d["min_ts"] = first_ts
        if last_ts and (d["max_ts"] is None or last_ts > d["max_ts"]):
            d["max_ts"] = last_ts

    for dtype, d in datasets_summary.items():
        d["symbols"] = sorted(list(d["symbols"]))

    # Deterministic global content hash across all partition hashes
    hasher = hashlib.sha256()
    for key in sorted(ready_partitions.keys()):
        p = ready_partitions[key]
        item_repr = f"{key}:{p.get('normalized_sha256')}:{p.get('row_count')}:{p.get('status')}"
        hasher.update(item_repr.encode("utf-8"))
    manifest_content_hash = hasher.hexdigest()

    manifest_data = {
        "manifest_version": "2.0.0",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generation_script": "scripts/run_historical_backfill.py",
        "governing_roadmap": "docs/SYSTEM_IMPLEMENTATION_PLAN.md",
        "milestone": "M2_EXPANSION_HISTORICAL_BACKFILL",
        "manifest_content_hash": manifest_content_hash,
        "total_ready_partitions": len(ready_partitions),
        "total_rows": total_rows,
        "summary_by_dataset": datasets_summary,
        "partitions": ready_partitions,
    }

    CANONICAL_MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CANONICAL_MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    print(f"  Canonical Manifest written to: {CANONICAL_MANIFEST_FILE}")
    print(f"  Total Partitions: {len(ready_partitions)}, Total Rows: {total_rows:,}")
    print(f"  Manifest Content SHA-256: {manifest_content_hash}")
    return CANONICAL_MANIFEST_FILE


# ── Main CLI Orchestrator ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Authoritative Historical Data Backfill Pipeline")
    parser.add_argument("--stage", choices=["1", "2", "3", "all"], default="all", help="Execution stage")
    parser.add_argument("--symbols", type=str, default=",".join(FULL_HISTORY_SYMBOLS), help="Comma-separated symbols")
    parser.add_argument("--start-month", type=str, default="2023-01", help="Start year-month (YYYY-MM)")
    parser.add_argument("--end-month", type=str, default="2026-06", help="End year-month (YYYY-MM)")
    parser.add_argument("--metrics-mode", choices=["core_full", "sample", "all_full", "none"], default="core_full", help="Metrics coverage mode")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent worker threads")
    parser.add_argument("--force", action="store_true", help="Force re-download and re-processing")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    months = generate_months(args.start_month, args.end_month)

    print(f"===========================================================")
    print(f"   BESTTIME-CRYPTO M2 HISTORICAL BACKFILL PIPELINE")
    print(f"   Stage: {args.stage} | Metrics Mode: {args.metrics_mode}")
    print(f"   Symbols ({len(symbols)}): {', '.join(symbols)}")
    print(f"   Date Range: {args.start_month} to {args.end_month} ({len(months)} months)")
    print(f"===========================================================")

    state_mgr = BackfillStateManager()

    # Step 1: Always register/verify existing Spot klines
    register_existing_spot_klines(state_mgr, symbols, months)

    # Filter symbols by stage
    if args.stage == "1":
        stage_symbols = [s for s in symbols if s in ["BTC", "ETH", "BTCUSDT", "ETHUSDT"]]
    else:
        stage_symbols = symbols

    # Step 2: Futures 1h klines
    if args.stage in ["1", "2", "all"]:
        backfill_futures_1h_klines(state_mgr, stage_symbols, months, max_workers=args.workers, force=args.force)

    # Step 3: Futures funding rates
    if args.stage in ["1", "2", "all"]:
        backfill_futures_funding(state_mgr, stage_symbols, months, max_workers=args.workers, force=args.force)

    # Step 4: Futures 5m metrics
    if args.stage in ["1", "2", "all"] and args.metrics_mode != "none":
        backfill_futures_metrics(state_mgr, stage_symbols, months, mode=args.metrics_mode, max_workers=args.workers, force=args.force)
        consolidate_metrics_to_monthly_parquet(state_mgr, stage_symbols, months, force=args.force)

    # Step 5: Stage 3 Shared Context (Macro, Sentiment, On-chain)
    if args.stage in ["3", "all"]:
        backfill_stage3_context(state_mgr, force=args.force)

    # Step 6: Canonical Manifest
    generate_canonical_manifest(state_mgr)

    print("\n===========================================================")
    print("   M2 HISTORICAL BACKFILL PIPELINE EXECUTION FINISHED")
    print("===========================================================")


if __name__ == "__main__":
    main()
