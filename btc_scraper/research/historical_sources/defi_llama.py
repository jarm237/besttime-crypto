"""
btc_scraper/research/historical_sources/defi_llama.py
Downloader and normalizer for DefiLlama historical stablecoin circulation and TVL data.

Source: stablecoins.llama.fi / api.llama.fi
Dataset: Global pegged stablecoin circulating volume and chain TVL.
PIT Availability Rule:
- Aggregated daily snapshots; available end-of-day UTC (CONSERVATIVE_ESTIMATE).
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
    SharedMetadataRecord,
    StablecoinRecord,
    normalize_timestamp_to_iso,
)


STABLECOIN_URL = "https://stablecoins.llama.fi/stablecoincharts/all"


def fetch_historical_stablecoins(
    target_cache_dir: Optional[Path] = None,
    timeout: int = 15,
) -> List[StablecoinRecord]:
    """
    Downloads historical circulating volume of pegged stablecoins.
    """
    req = urllib.request.Request(STABLECOIN_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw_bytes = resp.read()

    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if target_cache_dir:
        target_cache_dir = Path(target_cache_dir)
        target_cache_dir.mkdir(parents=True, exist_ok=True)
        (target_cache_dir / "defillama_stablecoins_all.json").write_bytes(raw_bytes)

    payload = json.loads(raw_bytes.decode("utf-8"))
    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records: List[StablecoinRecord] = []

    for item in payload:
        raw_ts = int(item["date"])
        iso_ts = normalize_timestamp_to_iso(raw_ts)
        date_str = iso_ts[:10]
        # Daily snapshot available next day 00:00 UTC
        avail_iso = f"{date_str}T23:59:59Z"

        circ_usd = item.get("totalCirculatingUSD", {})
        pegged_usd = float(circ_usd.get("peggedUSD", 0.0))
        total_usd = sum(float(v) for v in circ_usd.values())

        meta = SharedMetadataRecord(
            source_id="defi_llama",
            dataset_type=DatasetType.ONCHAIN_STABLECOIN.value,
            record_id=f"STABLECOIN_CIRC_{date_str}",
            instrument_id="GLOBAL_STABLECOINS",
            event_time=iso_ts,
            published_at=avail_iso,
            available_at=avail_iso,
            ingested_at=ingested_at,
            source_version="1.0.0",
            raw_payload_sha256=raw_sha256,
            quality_flags=("DEFILLAMA_GLOBAL_PEGGED",),
            missingness_status="PRESENT",
            availability_quality=PITClassification.CONSERVATIVE_ESTIMATE.value,
        )

        rec = StablecoinRecord(
            date=date_str,
            total_circulating_usd=total_usd,
            pegged_usd_volume=pegged_usd,
            metadata=meta,
        )
        records.append(rec)

    records.sort(key=lambda r: r.date)
    return records
