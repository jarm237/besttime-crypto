"""
btc_scraper/research/historical_sources/treasury_macro.py
Downloader and normalizer for official U.S. Department of the Treasury daily yield curve rates.

Source: home.treasury.gov
Dataset: Daily Treasury Par Yield Curve Rates (1 Mo, 2 Mo, 3 Mo, 4 Mo, 6 Mo, 1 Yr, 2 Yr, 3 Yr, 5 Yr, 7 Yr, 10 Yr, 20 Yr, 30 Yr).
PIT Availability Rule:
- Yields are calculated and released at market close ~16:00 ET (21:00 UTC).
- Available-at timestamp is strictly date + "T21:00:00Z" (VERIFIED_PIT).
- Zero lookahead: Cannot be joined into daytime trading observations before 21:00 UTC.
"""
from __future__ import annotations

import csv
import hashlib
import io
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from btc_scraper.research.historical_sources.contracts import (
    DatasetType,
    MacroYieldRecord,
    PITClassification,
    SharedMetadataRecord,
)

NY_TZ = ZoneInfo("America/New_York")


TREASURY_URL_TEMPLATE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
    "{year}/all?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
)


def fetch_and_parse_treasury_yields(
    year: int,
    target_cache_dir: Optional[Path] = None,
    timeout: int = 15,
) -> List[MacroYieldRecord]:
    """
    Downloads and parses U.S. Treasury daily yield rates for a given year.
    Caches raw CSV to target_cache_dir if provided.
    """
    url = TREASURY_URL_TEMPLATE.format(year=year)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        csv_bytes = resp.read()

    raw_sha256 = hashlib.sha256(csv_bytes).hexdigest()
    if target_cache_dir:
        target_cache_dir = Path(target_cache_dir)
        target_cache_dir.mkdir(parents=True, exist_ok=True)
        (target_cache_dir / f"treasury_yields_{year}.csv").write_bytes(csv_bytes)

    ingested_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records: List[MacroYieldRecord] = []

    text_stream = io.StringIO(csv_bytes.decode("utf-8", errors="replace"))
    reader = csv.reader(text_stream)
    header = next(reader, None)
    if not header:
        return records

    # Column mapping lookup
    col_map: Dict[str, int] = {name.strip(): idx for idx, name in enumerate(header)}

    def _get_float(row: List[str], col_name: str) -> Optional[float]:
        idx = col_map.get(col_name)
        if idx is not None and idx < len(row):
            val = row[idx].strip()
            if val and val != "N/A":
                try:
                    return float(val)
                except ValueError:
                    return None
        return None

    for row in reader:
        if not row or not row[0].strip():
            continue
        # Date is formatted MM/DD/YYYY
        raw_date = row[0].strip()
        try:
            dt_raw = datetime.strptime(raw_date, "%m/%d/%Y")
            iso_date = dt_raw.strftime("%Y-%m-%d")
        except ValueError:
            continue

        # Timezone-aware America/New_York conversion for EST/EDT release semantics
        # 1. Market quotation observation: 15:30 ET
        dt_quote_ny = datetime(dt_raw.year, dt_raw.month, dt_raw.day, 15, 30, tzinfo=NY_TZ)
        quote_utc = dt_quote_ny.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 2. Official publication timing: 16:00 ET (20:00Z in EDT, 21:00Z in EST)
        dt_pub_ny = datetime(dt_raw.year, dt_raw.month, dt_raw.day, 16, 0, tzinfo=NY_TZ)
        pub_utc = dt_pub_ny.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # 3. Conservative availability estimate: 17:00 ET (21:00Z in EDT, 22:00Z in EST)
        dt_cons_ny = datetime(dt_raw.year, dt_raw.month, dt_raw.day, 17, 0, tzinfo=NY_TZ)
        cons_avail_utc = dt_cons_ny.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        meta = SharedMetadataRecord(
            source_id="us_treasury",
            dataset_type=DatasetType.MACRO_YIELD.value,
            record_id=f"US_TREASURY_PAR_{iso_date}",
            instrument_id="US_YIELD_CURVE",
            event_time=quote_utc,
            published_at=pub_utc,
            available_at=cons_avail_utc,
            ingested_at=ingested_at,
            source_version="1.0.0",
            raw_payload_sha256=raw_sha256,
            quality_flags=("OFFICIAL_GOV_CURVE", "DST_AWARE_NY_TIMEZONE"),
            missingness_status="PRESENT",
            availability_quality=PITClassification.CONSERVATIVE_ESTIMATE.value,
        )

        rec = MacroYieldRecord(
            date=iso_date,
            yield_1m=_get_float(row, "1 Mo"),
            yield_3m=_get_float(row, "3 Mo"),
            yield_6m=_get_float(row, "6 Mo"),
            yield_1y=_get_float(row, "1 Yr"),
            yield_2y=_get_float(row, "2 Yr"),
            yield_5y=_get_float(row, "5 Yr"),
            yield_10y=_get_float(row, "10 Yr"),
            yield_30y=_get_float(row, "30 Yr"),
            metadata=meta,
            market_quotation_time_utc=quote_utc,
            actual_publication_time_utc=pub_utc,
            conservative_available_at_utc=cons_avail_utc,
            timezone_convention="America/New_York (EST/EDT aware)",
        )
        records.append(rec)

    # Sort chronologically (Treasury CSV lists newest to oldest)
    records.sort(key=lambda r: r.date)
    return records
