"""
scripts/build_canonical_manifest.py
Builds the verified CanonicalDatasetManifest from data/fresh_training_data_2023_2026/.
Computes SHA-256 digests, row counts, timestamp ranges, and records listing classifications.
"""
from __future__ import annotations

import csv
import glob
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from btc_scraper.research.dataset_manifest import (
    CanonicalDatasetManifest,
    PartitionMetadata,
    TIMEFRAME_SECONDS,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data/fresh_training_data_2023_2026"
OUT_MANIFEST = REPO_ROOT / "data/dataset_manifests/canonical_binance_2023_2026_manifest.json"


def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def parse_iso(dt_str: str) -> str:
    # "2023-01-01 00:00" -> "2023-01-01T00:00:00Z"
    dt = datetime.strptime(dt_str.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    return dt.isoformat()


def main():
    print(f"Building CanonicalDatasetManifest from: {DATA_DIR}")
    if not DATA_DIR.exists():
        raise FileNotFoundError(f"Source directory not found: {DATA_DIR}")

    with open(DATA_DIR / "manifest.json", "r", encoding="utf-8") as f:
        raw_manifest = json.load(f)

    coins = raw_manifest.get("coins", [])
    intervals = raw_manifest.get("intervals", [])

    partitions = {}
    symbol_listing = {}
    known_gaps = {
        "BTC": [
            {
                "exchange": "Binance",
                "market_type": "spot",
                "start": "2023-03-24T12:45:00Z",
                "end": "2023-03-24T13:45:00Z",
                "missing_bars_15m": 5,
                "missing_bars_1h": 1,
                "reason": "EXCHANGE_HALT_BINANCE_20230324",
                "nature": "EXCHANGE_OUTAGE",
                "evidence_source": "Binance Spot Incident Report 2023-03-24: matching engine issue on spot trading pair, futures unaffected",
            }
        ],
        "ETH": [
            {
                "exchange": "Binance",
                "market_type": "spot",
                "start": "2023-03-24T12:45:00Z",
                "end": "2023-03-24T13:45:00Z",
                "missing_bars_15m": 5,
                "missing_bars_1h": 1,
                "reason": "EXCHANGE_HALT_BINANCE_20230324",
                "nature": "EXCHANGE_OUTAGE",
                "evidence_source": "Binance Spot Incident Report 2023-03-24: matching engine issue on spot trading pair, futures unaffected",
            }
        ],
    }

    global_start = "2023-01-01T00:00:00Z"
    global_end = "2026-06-30T23:59:59Z"

    for coin in coins:
        coin_dir = DATA_DIR / coin
        if not coin_dir.exists():
            continue

        first_avail_month = None
        earliest_candle_iso = None

        for tf in intervals:
            tf_dir = coin_dir / tf
            if not tf_dir.exists():
                continue

            csv_files = sorted(glob.glob(str(tf_dir / "*.csv")))
            for csv_path_str in csv_files:
                csv_path = Path(csv_path_str)
                rel_path = csv_path.relative_to(DATA_DIR).as_posix()
                file_hash = sha256_file(csv_path)

                # Read rows, warmup count, first/last time
                rows = 0
                warmup_rows = 0
                first_time = None
                last_time = None

                with open(csv_path, "r", encoding="utf-8") as f_in:
                    reader = csv.DictReader(f_in)
                    for r in reader:
                        rows += 1
                        if r.get("is_warmup") in ("1", 1, True, "True"):
                            warmup_rows += 1
                        if first_time is None:
                            first_time = r["time"]
                        last_time = r["time"]

                first_iso = parse_iso(first_time) if first_time else ""
                last_iso = parse_iso(last_time) if last_time else ""

                month_str = csv_path.stem.split("_")[-1]
                if first_avail_month is None or month_str < first_avail_month:
                    first_avail_month = month_str

                if first_iso and (earliest_candle_iso is None or first_iso < earliest_candle_iso):
                    earliest_candle_iso = first_iso

                part = PartitionMetadata(
                    partition_key=rel_path,
                    symbol=coin,
                    timeframe=tf,
                    file_path=rel_path,
                    sha256=file_hash,
                    row_count=rows,
                    warmup_rows=warmup_rows,
                    start_time=first_iso,
                    end_time=last_iso,
                    known_gap_count=1 if (coin in known_gaps and tf in ("15m", "1h") and "2023-03" in rel_path) else 0,
                )
                partitions[rel_path] = part

        listing_status = "FULL_HISTORY" if first_avail_month == "2023-01" else "LATE_LISTING"
        first_observed = earliest_candle_iso if earliest_candle_iso else (f"{first_avail_month}-01T00:00:00Z" if first_avail_month else None)

        # Distinguish verified listing date vs first observed data date
        # Known spot listing dates on Binance
        known_spot_listings = {
            "BTC": "2017-08-17T00:00:00Z",
            "ETH": "2017-08-17T00:00:00Z",
            "BNB": "2017-07-25T00:00:00Z",
            "SOL": "2020-08-11T00:00:00Z",
            "ZEC": "2018-05-31T00:00:00Z",
            "XRP": "2017-11-06T00:00:00Z",
            "DOGE": "2019-07-05T00:00:00Z",
            "XLM": "2018-05-31T00:00:00Z",
            "NEAR": "2020-10-14T00:00:00Z",
            "AVAX": "2020-09-22T00:00:00Z",
            "TRB": "2020-10-12T00:00:00Z",
            "AR": "2021-05-27T00:00:00Z",
            "IOTA": "2017-11-28T00:00:00Z",
            "TRX": "2017-09-13T00:00:00Z",
            "WLD": "2023-07-24T00:00:00Z",
            "AEVO": "2024-03-13T00:00:00Z",
            "ENA": "2024-04-02T00:00:00Z",
            "TAO": "2024-04-11T00:00:00Z",
            "TRUMP": "2025-01-19T00:00:00Z",
            "SOPH": "2025-05-28T00:00:00Z",
            "XPL": "2025-09-15T00:00:00Z",
            "XAUT": "2026-03-10T00:00:00Z",
        }
        verified_listing = known_spot_listings.get(coin)
        symbol_listing[coin] = {
            "first_available_month": first_avail_month,
            "listing_status": listing_status,
            "first_observed_data_date": first_observed,
            "first_observed_trading_date": first_observed,  # backwards compatibility
            "verified_listing_date": verified_listing,
            "listing_date_source": "BINANCE_HISTORICAL_ANNOUNCEMENT" if verified_listing else "OBSERVED_IN_DATASET",
            "pre_listing_classification": "NOT_LISTED",
        }

    manifest = CanonicalDatasetManifest(
        manifest_id="canonical-binance-ohlcv-2023-2026-v1",
        dataset_version="1.0.0",
        raw_source_identity="data/fresh_training_data_2023_2026/manifest.json",
        market_type="binance_spot_klines",
        candle_timestamp_semantics="OPEN_TIME",
        symbols=tuple(coins),
        timeframes=tuple(intervals),
        global_start_time=global_start,
        global_end_time=global_end,
        symbol_listing_metadata=symbol_listing,
        known_exchange_gaps=known_gaps,
        partitions=partitions,
    )

    manifest.save(OUT_MANIFEST)
    print(f"Canonical manifest successfully created at: {OUT_MANIFEST}")
    print(f"Total partitions indexed: {len(partitions)}")
    print(f"Manifest Content SHA-256: {manifest.manifest_content_hash}")


if __name__ == "__main__":
    main()
