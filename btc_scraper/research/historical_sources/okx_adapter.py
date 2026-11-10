"""
btc_scraper/research/historical_sources/okx_adapter.py
REST API adapter for OKX historical market data (Candles, Funding Rate, Mark Price).

Source: www.okx.com / api.okx.com
Endpoints:
- /api/v5/market/history-candles
- /api/v5/public/funding-rate-history
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from btc_scraper.research.historical_sources.contracts import (
    CandleRecord,
    DatasetType,
    FundingRecord,
    PITClassification,
    SharedMetadataRecord,
    normalize_timestamp_to_iso,
)


OKX_CANDLES_URL = "https://www.okx.com/api/v5/market/history-candles?instId={inst_id}&bar={bar}&limit={limit}"
OKX_FUNDING_URL = "https://www.okx.com/api/v5/public/funding-rate-history?instId={inst_id}&limit={limit}"


def fetch_okx_candles(
    inst_id: str = "BTC-USDT",
    bar: str = "1H",
    limit: int = 100,
    target_cache_dir: Optional[Path] = None,
    timeout: int = 12,
) -> List[CandleRecord]:
    """
    Fetches historical candlestick records from OKX.
    """
    url = OKX_CANDLES_URL.format(inst_id=inst_id, bar=bar, limit=limit)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_bytes = resp.read()

    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if target_cache_dir:
        target_cache_dir = Path(target_cache_dir)
        target_cache_dir.mkdir(parents=True, exist_ok=True)
        (target_cache_dir / f"okx_candles_{inst_id}_{bar}.json").write_bytes(raw_bytes)

    payload = json.loads(raw_bytes.decode("utf-8"))
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records: List[CandleRecord] = []

    for item in payload.get("data", []):
        # Format: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
        ts_raw = int(item[0])
        open_iso = normalize_timestamp_to_iso(ts_raw)
        
        # Estimate close time for 1H
        interval_secs = 3600 if bar.upper() == "1H" else 60
        close_ts = ts_raw + (interval_secs * 1000) - 1
        close_iso = normalize_timestamp_to_iso(close_ts)

        meta = SharedMetadataRecord(
            source_id="okx_rest",
            dataset_type=DatasetType.SPOT_CANDLE.value,
            record_id=f"OKX_{inst_id}_{open_iso}",
            instrument_id=inst_id,
            event_time=open_iso,
            published_at=close_iso,
            available_at=close_iso,
            ingested_at=ingested_at,
            source_version="1.0.0",
            raw_payload_sha256=raw_sha256,
            quality_flags=("OKX_HISTORY_CANDLE",),
            missingness_status="PRESENT",
            availability_quality=PITClassification.VERIFIED_PIT.value,
        )

        rec = CandleRecord(
            open_time=open_iso,
            close_time=close_iso,
            open=float(item[1]),
            high=float(item[2]),
            low=float(item[3]),
            close=float(item[4]),
            volume=float(item[5]),
            quote_volume=float(item[7]) if len(item) > 7 else 0.0,
            trades_count=0,
            taker_buy_volume=0.0,
            taker_buy_quote_volume=0.0,
            is_closed=bool(int(item[8])) if len(item) > 8 else True,
            metadata=meta,
        )
        records.append(rec)

    records.sort(key=lambda r: r.open_time)
    return records


def fetch_okx_funding_history(
    inst_id: str = "BTC-USDT-SWAP",
    limit: int = 100,
    target_cache_dir: Optional[Path] = None,
    timeout: int = 12,
) -> List[FundingRecord]:
    """
    Fetches historical funding rate settlements from OKX.
    """
    url = OKX_FUNDING_URL.format(inst_id=inst_id, limit=limit)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_bytes = resp.read()

    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if target_cache_dir:
        target_cache_dir = Path(target_cache_dir)
        target_cache_dir.mkdir(parents=True, exist_ok=True)
        (target_cache_dir / f"okx_funding_{inst_id}.json").write_bytes(raw_bytes)

    payload = json.loads(raw_bytes.decode("utf-8"))
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records: List[FundingRecord] = []

    for item in payload.get("data", []):
        ts_raw = int(item["fundingTime"])
        iso_ts = normalize_timestamp_to_iso(ts_raw)
        funding_rate = float(item["fundingRate"])
        realized_rate = float(item.get("realizedRate", item["fundingRate"]))

        meta = SharedMetadataRecord(
            source_id="okx_rest",
            dataset_type=DatasetType.FUNDING_RATE.value,
            record_id=f"OKX_{inst_id}_{iso_ts}",
            instrument_id=inst_id,
            event_time=iso_ts,
            published_at=iso_ts,
            available_at=iso_ts,
            ingested_at=ingested_at,
            source_version="1.0.0",
            raw_payload_sha256=raw_sha256,
            quality_flags=("OKX_FUNDING_SETTLEMENT",),
            missingness_status="PRESENT",
            availability_quality=PITClassification.VERIFIED_PIT.value,
        )

        rec = FundingRecord(
            timestamp=iso_ts,
            funding_interval_hours=8,
            funding_rate=funding_rate,
            realized_rate=realized_rate,
            metadata=meta,
        )
        records.append(rec)

    records.sort(key=lambda r: r.timestamp)
    return records
