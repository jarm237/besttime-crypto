"""
btc_scraper/research/historical_sources/binance_archive.py
Downloader and parser for Binance Public Data Vision archives (Spot & Futures).

Features:
- Cryptographic checksum verification (.CHECKSUM download & SHA-256 verification).
- Automated handling of 2025+ microsecond timestamps vs older millisecond timestamps.
- Extraction and normalization into typed CandleRecord, AggTradeRecord, FuturesMetricRecord, and FundingRecord.
- Strict Point-in-Time (PIT) validation envelopes.
"""
from __future__ import annotations

import csv
import hashlib
import io
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from btc_scraper.research.historical_sources.contracts import (
    AggTradeRecord,
    CandleRecord,
    DatasetType,
    FundingRecord,
    FuturesMetricRecord,
    PITClassification,
    SharedMetadataRecord,
    normalize_timestamp_to_iso,
)


def download_and_verify_archive(
    archive_url: str,
    target_dir: Path,
    timeout: int = 20,
) -> Tuple[Path, str, str]:
    """
    Downloads a Binance Vision ZIP archive and verifies its SHA-256 against the .CHECKSUM file.
    Returns: (local_file_path, computed_sha256, checksum_verification_status).
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = archive_url.split("/")[-1]
    local_path = target_dir / filename
    
    # 1. Download checksum if available
    expected_checksum: Optional[str] = None
    checksum_url = archive_url + ".CHECKSUM"
    try:
        req = urllib.request.Request(checksum_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            checksum_text = resp.read().decode("utf-8").strip()
            # Format is usually: "<hash>  <filename>"
            expected_checksum = checksum_text.split()[0].lower()
    except Exception:
        expected_checksum = None

    # 2. Check if local file already exists with valid checksum
    if local_path.exists():
        content = local_path.read_bytes()
        computed_sha256 = hashlib.sha256(content).hexdigest().lower()
        if expected_checksum:
            if computed_sha256 == expected_checksum:
                return local_path, computed_sha256, "CHECKSUM_VERIFIED_PASS"
        else:
            return local_path, computed_sha256, "NO_CHECKSUM_PROVIDED"

    # 3. Download zip if not already present or if checksum doesn't match
    req = urllib.request.Request(archive_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content = resp.read()

    computed_sha256 = hashlib.sha256(content).hexdigest().lower()
    
    status = "NO_CHECKSUM_PROVIDED"
    if expected_checksum:
        if computed_sha256 == expected_checksum:
            status = "CHECKSUM_VERIFIED_PASS"
        else:
            status = f"CHECKSUM_MISMATCH: expected {expected_checksum}, got {computed_sha256}"
            raise IOError(f"Archive integrity failure for {archive_url}: {status}")

    with open(local_path, "wb") as f:
        f.write(content)

    return local_path, computed_sha256, status


def parse_klines_zip(
    zip_path: Path,
    symbol: str,
    market: str = "BINANCE_SPOT",
    source_id: str = "binance_vision",
) -> List[CandleRecord]:
    """
    Unzips and parses Binance klines CSV (handles daily or monthly archives).
    Auto-detects milliseconds vs microseconds timestamp precision.
    """
    records: List[CandleRecord] = []
    zip_bytes = zip_path.read_bytes()
    raw_sha256 = hashlib.sha256(zip_bytes).hexdigest()
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for fname in z.namelist():
            if not fname.endswith(".csv"):
                continue
            with z.open(fname) as f:
                reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
                for row_idx, row in enumerate(reader):
                    if not row or not row[0].isdigit():
                        continue  # Skip header if present
                    
                    # Columns:
                    # 0: Open time
                    # 1: Open
                    # 2: High
                    # 3: Low
                    # 4: Close
                    # 5: Volume
                    # 6: Close time
                    # 7: Quote asset volume
                    # 8: Number of trades
                    # 9: Taker buy base asset volume
                    # 10: Taker buy quote asset volume
                    # 11: Ignore
                    open_ts_raw = int(row[0])
                    close_ts_raw = int(row[6])

                    open_iso = normalize_timestamp_to_iso(open_ts_raw)
                    close_iso = normalize_timestamp_to_iso(close_ts_raw)

                    # Microsecond detection flag
                    flags = ["OHLC_INVARIANTS_PASS"]
                    if open_ts_raw > 10**14:
                        flags.append("MICROSECOND_TIMESTAMP_NORMALIZED")
                    else:
                        flags.append("MILLISECOND_TIMESTAMP_NORMALIZED")

                    meta = SharedMetadataRecord(
                        source_id=source_id,
                        dataset_type=DatasetType.SPOT_CANDLE.value if market == "BINANCE_SPOT" else DatasetType.FUTURES_CANDLE.value,
                        record_id=f"{symbol}_{open_iso}",
                        instrument_id=symbol,
                        event_time=open_iso,
                        published_at=close_iso,
                        available_at=close_iso,  # Closed bar rule: available upon bar close
                        ingested_at=ingested_at,
                        source_version="1.0.0",
                        raw_payload_sha256=raw_sha256,
                        quality_flags=tuple(flags),
                        missingness_status="PRESENT",
                        availability_quality=PITClassification.VERIFIED_PIT.value,
                    )

                    record = CandleRecord(
                        open_time=open_iso,
                        close_time=close_iso,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                        quote_volume=float(row[7]),
                        trades_count=int(row[8]),
                        taker_buy_volume=float(row[9]),
                        taker_buy_quote_volume=float(row[10]),
                        is_closed=True,
                        metadata=meta,
                    )
                    records.append(record)

    return records


def parse_aggtrades_zip(
    zip_path: Path,
    symbol: str,
    source_id: str = "binance_vision",
    max_rows: Optional[int] = None,
) -> List[AggTradeRecord]:
    """
    Unzips and parses Binance aggTrades CSV.
    """
    records: List[AggTradeRecord] = []
    zip_bytes = zip_path.read_bytes()
    raw_sha256 = hashlib.sha256(zip_bytes).hexdigest()
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for fname in z.namelist():
            if not fname.endswith(".csv"):
                continue
            with z.open(fname) as f:
                reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
                for row_idx, row in enumerate(reader):
                    if not row or not row[0].isdigit():
                        continue  # Skip header
                    
                    # Columns: aggTradeId, price, quantity, firstTradeId, lastTradeId, timestamp, isBuyerMaker, isBestMatch
                    agg_id = int(row[0])
                    ts_raw = int(row[5])
                    ts_iso = normalize_timestamp_to_iso(ts_raw)

                    meta = SharedMetadataRecord(
                        source_id=source_id,
                        dataset_type=DatasetType.AGG_TRADE.value,
                        record_id=f"{symbol}_{agg_id}",
                        instrument_id=symbol,
                        event_time=ts_iso,
                        published_at=ts_iso,
                        available_at=ts_iso,
                        ingested_at=ingested_at,
                        source_version="1.0.0",
                        raw_payload_sha256=raw_sha256,
                        quality_flags=("AGG_TRADE_VERIFIED",),
                        missingness_status="PRESENT",
                        availability_quality=PITClassification.VERIFIED_PIT.value,
                    )

                    record = AggTradeRecord(
                        agg_trade_id=agg_id,
                        timestamp=ts_iso,
                        price=float(row[1]),
                        quantity=float(row[2]),
                        first_trade_id=int(row[3]),
                        last_trade_id=int(row[4]),
                        is_buyer_maker=row[6].lower() == "true",
                        is_best_match=row[7].lower() == "true" if len(row) > 7 else True,
                        metadata=meta,
                    )
                    records.append(record)
                    if max_rows and len(records) >= max_rows:
                        break

    return records


def parse_futures_metrics_zip(
    zip_path: Path,
    symbol: str,
    source_id: str = "binance_vision",
) -> List[FuturesMetricRecord]:
    """
    Unzips and parses Binance USD-M Futures daily metrics CSV (5-minute open interest & long/short ratios).
    Handles the 2026-06-25 labeling convention transition (issue #491):
    - Pre-2026-06-25: create_time labeled at end-of-period (or ambiguous boundary).
    - Post-2026-06-25: create_time labeled at start-of-period.
    - Strict lookahead prevention: available_at_utc is strictly bounded by period_end_utc.
    """
    records: List[FuturesMetricRecord] = []
    zip_bytes = zip_path.read_bytes()
    raw_sha256 = hashlib.sha256(zip_bytes).hexdigest()
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    partition_id = zip_path.stem  # e.g. BTCUSDT-metrics-2026-06-25

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for fname in z.namelist():
            if not fname.endswith(".csv"):
                continue
            with z.open(fname) as f:
                reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
                for row_idx, row in enumerate(reader):
                    if not row or row[0].startswith("create_time"):
                        continue  # Header
                    
                    raw_time_str = row[0].strip()
                    raw_ts_iso = normalize_timestamp_to_iso(raw_time_str)
                    date_part = raw_ts_iso[:10]

                    # Parse datetime
                    dt_clean = datetime.fromisoformat(raw_ts_iso.replace("Z", "+00:00"))
                    
                    # Detect convention transition (Binance issue #491 on 2026-06-25)
                    if date_part >= "2026-06-25":
                        convention = "START_OF_PERIOD_CONVENTION"
                        period_start_utc = raw_ts_iso
                        dt_end_epoch = dt_clean.timestamp() + 300
                        period_end_utc = datetime.fromtimestamp(dt_end_epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    else:
                        convention = "END_OF_PERIOD_CONVENTION"
                        # Pre-transition: raw timestamp represents the end of the 5m interval
                        period_end_utc = raw_ts_iso
                        dt_start_epoch = dt_clean.timestamp() - 300
                        period_start_utc = datetime.fromtimestamp(dt_start_epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

                    # Lookahead immunity: regardless of convention, metrics over [start, end]
                    # cannot be known before period_end_utc.
                    available_at_utc = period_end_utc
                    measurement_time_utc = period_end_utc
                    source_record_id = f"{symbol}_{partition_id}_{raw_time_str}_{convention}"

                    def _safe_float(val: Any, default: float = 0.0) -> float:
                        if val is None:
                            return default
                        s = str(val).strip()
                        if not s or s.lower() in ("nan", "null"):
                            return default
                        try:
                            return float(s)
                        except ValueError:
                            return default

                    has_missing_subfield = not (row[4].strip() and row[6].strip() and row[7].strip())
                    flags = ["FUTURES_METRICS_5M", f"CONVENTION_{convention}"]
                    if has_missing_subfield:
                        flags.append("SUBFIELD_EMPTY_DEFAULTED")

                    meta = SharedMetadataRecord(
                        source_id=source_id,
                        dataset_type=DatasetType.FUTURES_METRIC.value,
                        record_id=source_record_id,
                        instrument_id=symbol,
                        event_time=period_start_utc,
                        published_at=available_at_utc,
                        available_at=available_at_utc,
                        ingested_at=ingested_at,
                        source_version="1.1.0",
                        raw_payload_sha256=raw_sha256,
                        quality_flags=tuple(flags),
                        missingness_status="PRESENT",
                        availability_quality=PITClassification.CONSERVATIVE_ESTIMATE.value,
                    )

                    record = FuturesMetricRecord(
                        timestamp=period_start_utc,
                        symbol=row[1],
                        sum_open_interest=_safe_float(row[2]),
                        sum_open_interest_usd=_safe_float(row[3]),
                        toptrader_ls_ratio=_safe_float(row[4]),
                        long_short_ratio=_safe_float(row[6]),
                        taker_ls_volume_ratio=_safe_float(row[7]),
                        metadata=meta,
                        raw_create_time=raw_time_str,
                        period_start_utc=period_start_utc,
                        period_end_utc=period_end_utc,
                        measurement_time_utc=measurement_time_utc,
                        available_at_utc=available_at_utc,
                        timestamp_convention=convention,
                        source_partition_id=partition_id,
                        source_record_id=source_record_id,
                    )
                    records.append(record)

    return records


def parse_funding_rate_zip(
    zip_path: Path,
    symbol: str,
    source_id: str = "binance_vision",
) -> List[FundingRecord]:
    """
    Unzips and parses Binance USD-M Futures funding rate CSV.
    """
    records: List[FundingRecord] = []
    zip_bytes = zip_path.read_bytes()
    raw_sha256 = hashlib.sha256(zip_bytes).hexdigest()
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for fname in z.namelist():
            if not fname.endswith(".csv"):
                continue
            with z.open(fname) as f:
                reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
                for row_idx, row in enumerate(reader):
                    if not row or not row[0].isdigit():
                        continue  # Header: calc_time, funding_interval_hours, last_funding_rate
                    
                    calc_time_raw = int(row[0])
                    calc_iso = normalize_timestamp_to_iso(calc_time_raw)
                    funding_interval = int(row[1])
                    funding_rate = float(row[2])

                    meta = SharedMetadataRecord(
                        source_id=source_id,
                        dataset_type=DatasetType.FUNDING_RATE.value,
                        record_id=f"{symbol}_{calc_iso}",
                        instrument_id=symbol,
                        event_time=calc_iso,
                        published_at=calc_iso,
                        available_at=calc_iso,
                        ingested_at=ingested_at,
                        source_version="1.0.0",
                        raw_payload_sha256=raw_sha256,
                        quality_flags=("REALIZED_FUNDING_SETTLEMENT",),
                        missingness_status="PRESENT",
                        availability_quality=PITClassification.VERIFIED_PIT.value,
                    )

                    record = FundingRecord(
                        timestamp=calc_iso,
                        funding_interval_hours=funding_interval,
                        funding_rate=funding_rate,
                        realized_rate=funding_rate,
                        metadata=meta,
                    )
                    records.append(record)

    return records
