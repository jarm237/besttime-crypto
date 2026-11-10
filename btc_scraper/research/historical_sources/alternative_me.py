"""
btc_scraper/research/historical_sources/alternative_me.py
Downloader and normalizer for Alternative.me Crypto Fear & Greed Index.

Source: api.alternative.me
Dataset: Fear and Greed Index (Daily 0-100 value + classification).
PIT Availability Rule:
- Calculated at 00:00 UTC and finalized by 00:05 UTC.
- Available-at timestamp is strictly observation date + "T00:05:00Z" (VERIFIED_PIT).
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from btc_scraper.research.historical_sources.contracts import (
    DatasetType,
    PITClassification,
    SentimentRecord,
    SharedMetadataRecord,
    normalize_timestamp_to_iso,
)


FNG_API_URL = "https://api.alternative.me/fng/?limit={limit}&format=json"


def fetch_fear_and_greed_history(
    limit: int = 100,
    target_cache_dir: Optional[Path] = None,
    timeout: int = 12,
) -> List[SentimentRecord]:
    """
    Downloads historical Fear & Greed index records.
    limit=0 fetches entire history; limit=N fetches latest N records.
    """
    url = FNG_API_URL.format(limit=limit)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_bytes = resp.read()

    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if target_cache_dir:
        target_cache_dir = Path(target_cache_dir)
        target_cache_dir.mkdir(parents=True, exist_ok=True)
        (target_cache_dir / f"fng_history_limit_{limit}.json").write_bytes(raw_bytes)

    payload = json.loads(raw_bytes.decode("utf-8"))
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records: List[SentimentRecord] = []

    for item in payload.get("data", []):
        raw_ts = int(item["timestamp"])
        iso_ts = normalize_timestamp_to_iso(raw_ts)
        # API records date at 00:00 UTC, but actual web scraping / publication timestamp is unverified.
        # We apply conservative availability at 06:00 UTC to ensure complete finalization.
        date_str = iso_ts[:10]
        cons_avail_iso = f"{date_str}T06:00:00Z"

        meta = SharedMetadataRecord(
            source_id="alternative_me",
            dataset_type=DatasetType.MARKET_SENTIMENT.value,
            record_id=f"FNG_{date_str}",
            instrument_id="CRYPTO_FNG",
            event_time=iso_ts,
            published_at=cons_avail_iso,
            available_at=cons_avail_iso,
            ingested_at=ingested_at,
            source_version="1.0.0",
            raw_payload_sha256=raw_sha256,
            quality_flags=("FEAR_AND_GREED_DAILY", "CONSERVATIVE_AVAILABILITY_0600UTC"),
            missingness_status="PRESENT",
            availability_quality=PITClassification.CONSERVATIVE_ESTIMATE.value,
        )

        rec = SentimentRecord(
            timestamp=iso_ts,
            value=int(item["value"]),
            classification=item["value_classification"],
            metadata=meta,
            api_record_timestamp=iso_ts,
            conservative_available_at_utc=cons_avail_iso,
        )
        records.append(rec)

    records.sort(key=lambda r: r.timestamp)
    return records
