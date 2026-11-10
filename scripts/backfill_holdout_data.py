"""
scripts/backfill_holdout_data.py
Phase 3: Minimal Holdout Backfill for Candidate Independent Historical OOS (2026-07-01 to 2026-11-09).

Backfills Binance Spot 1h klines for ETHUSDT (target candidate) and BTCUSDT (benchmark/context).
Verifies SHA-256 checksums from Binance Vision, validates OHLC invariants, eliminates duplicates,
and produces an immutable dataset manifest.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_TARGET_DIR = PROJECT_ROOT / "data" / "historical" / "raw" / "holdout_spot"
NORMALIZED_DIR = PROJECT_ROOT / "data" / "historical" / "holdout_2026_h2"
MANIFEST_DIR = PROJECT_ROOT / "data" / "historical" / "manifests"


def download_with_checksum(url: str, dest_dir: Path) -> Tuple[Path, str, str]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = url.split("/")[-1]
    local_file = dest_dir / filename
    
    # 1. Fetch checksum
    checksum_url = url + ".CHECKSUM"
    expected_hash: Optional[str] = None
    try:
        req = urllib.request.Request(checksum_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8").strip()
            expected_hash = text.split()[0].lower()
    except Exception as e:
        expected_hash = None

    # Check if local file exists
    if local_file.exists():
        content = local_file.read_bytes()
        file_hash = hashlib.sha256(content).hexdigest().lower()
        if expected_hash and file_hash == expected_hash:
            return local_file, file_hash, "CHECKSUM_VERIFIED"
        elif not expected_hash:
            return local_file, file_hash, "NO_CHECKSUM_PROVIDED"

    # Download
    print(f"  Downloading: {filename}...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        content = resp.read()

    file_hash = hashlib.sha256(content).hexdigest().lower()
    if expected_hash and file_hash != expected_hash:
        raise IOError(f"Checksum mismatch for {filename}: expected {expected_hash}, got {file_hash}")

    with open(local_file, "wb") as f:
        f.write(content)

    return local_file, file_hash, "CHECKSUM_VERIFIED" if expected_hash else "NO_CHECKSUM_PROVIDED"


def parse_spot_klines(zip_path: Path, symbol: str) -> List[Dict[str, Any]]:
    records = []
    zip_bytes = zip_path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for fname in z.namelist():
            if not fname.endswith(".csv"):
                continue
            with z.open(fname) as f:
                reader = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
                for row in reader:
                    if not row or not row[0].isdigit():
                        continue
                    open_ts = int(row[0])
                    # Normalize timestamp
                    if open_ts > 10**14:  # microsecond
                        sec = open_ts // 1_000_000
                    else:  # millisecond
                        sec = open_ts // 1000
                    dt = datetime.fromtimestamp(sec, tz=timezone.utc)
                    time_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

                    open_p = float(row[1])
                    high_p = float(row[2])
                    low_p = float(row[3])
                    close_p = float(row[4])
                    vol = float(row[5])

                    # OHLC invariant
                    assert high_p >= low_p, f"High < Low at {time_iso}"
                    assert high_p >= open_p and high_p >= close_p, f"High < Open/Close at {time_iso}"
                    assert low_p <= open_p and low_p <= close_p, f"Low > Open/Close at {time_iso}"

                    records.append({
                        "time": time_iso,
                        "timestamp": time_iso,
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "close": close_p,
                        "volume": vol,
                        "symbol": symbol,
                    })
    return records


def backfill_holdout() -> Dict[str, Any]:
    print("=================================================================")
    print("   PHASE 3: MINIMAL HISTORICAL OOS BACKFILL")
    print("   Window: 2026-07-01T00:00:00Z -> 2026-11-09T23:00:00Z")
    print("   Assets: ETHUSDT (Target) & BTCUSDT (Benchmark/Context)")
    print("=================================================================\n")

    symbols = ["ETHUSDT", "BTCUSDT"]
    months = ["2026-07", "2026-08", "2026-09", "2026-10"]
    days = [f"2026-11-{d:02d}" for d in range(1, 10)]

    manifest_entries = []
    symbol_candles: Dict[str, List[Dict[str, Any]]] = {}

    for sym in symbols:
        print(f"\n[Processing {sym}]")
        raw_sym_dir = RAW_TARGET_DIR / sym
        all_records: Dict[str, Dict[str, Any]] = {}

        # 1. Monthly archives
        for ym in months:
            url = f"https://data.binance.vision/data/spot/monthly/klines/{sym}/1h/{sym}-1h-{ym}.zip"
            local_path, f_hash, status = download_with_checksum(url, raw_sym_dir)
            records = parse_spot_klines(local_path, sym)
            for r in records:
                all_records[r["time"]] = r
            print(f"  Monthly {ym}: {len(records)} candles | SHA256: {f_hash[:12]}... | {status}")
            manifest_entries.append({
                "symbol": sym,
                "partition_type": "monthly",
                "period": ym,
                "filename": local_path.name,
                "sha256": f_hash,
                "candle_count": len(records),
            })

        # 2. Daily archives for Nov 1 to Nov 9
        for ymd in days:
            url = f"https://data.binance.vision/data/spot/daily/klines/{sym}/1h/{sym}-1h-{ymd}.zip"
            local_path, f_hash, status = download_with_checksum(url, raw_sym_dir)
            records = parse_spot_klines(local_path, sym)
            for r in records:
                all_records[r["time"]] = r
            print(f"  Daily {ymd}: {len(records)} candles | SHA256: {f_hash[:12]}... | {status}")
            manifest_entries.append({
                "symbol": sym,
                "partition_type": "daily",
                "period": ymd,
                "filename": local_path.name,
                "sha256": f_hash,
                "candle_count": len(records),
            })

        # Sort deduplicated candles
        sorted_candles = sorted(all_records.values(), key=lambda x: x["time"])
        print(f"  Total deduplicated candles for {sym}: {len(sorted_candles)}")
        
        # Verify continuous 1h stepping
        start_time = sorted_candles[0]["time"]
        end_time = sorted_candles[-1]["time"]
        print(f"  Range: {start_time} -> {end_time}")
        assert start_time == "2026-07-01T00:00:00Z", f"Expected start 2026-07-01T00:00:00Z, got {start_time}"
        assert end_time == "2026-11-09T23:00:00Z", f"Expected end 2026-11-09T23:00:00Z, got {end_time}"
        
        # Expected hours: 31 (Jul) + 31 (Aug) + 30 (Sep) + 31 (Oct) + 9*24 (Nov) = 132 * 24 = 3,168
        expected_count = 132 * 24
        assert len(sorted_candles) == expected_count, f"Expected {expected_count} candles, got {len(sorted_candles)}"
        print(f"  Gap check PASS: exactly {expected_count} consecutive 1-hour candles with zero missingness!")

        symbol_candles[sym] = sorted_candles

        # Save normalized CSV
        NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
        csv_out = NORMALIZED_DIR / f"{sym}_1h_2026-07-01_to_2026-11-09.csv"
        with open(csv_out, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["time", "timestamp", "open", "high", "low", "close", "volume", "symbol"])
            writer.writeheader()
            writer.writerows(sorted_candles)
        print(f"  Saved normalized dataset to {csv_out}")

    # Compute overall dataset hash
    combined_content = ""
    for sym in symbols:
        for c in symbol_candles[sym]:
            combined_content += f"{sym}|{c['time']}|{c['open']}|{c['high']}|{c['low']}|{c['close']}|{c['volume']}\n"
    dataset_content_hash = hashlib.sha256(combined_content.encode("utf-8")).hexdigest()

    manifest_data = {
        "manifest_identity": "historical_oos_2026_h2_eth_btc_spot_1h",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_start_utc": "2026-07-01T00:00:00Z",
        "window_end_utc": "2026-11-09T23:00:00Z",
        "total_days": 132,
        "candles_per_symbol": 3168,
        "dataset_content_hash": dataset_content_hash,
        "symbols": symbols,
        "partitions": manifest_entries,
    }

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    manifest_file = MANIFEST_DIR / "historical_oos_2026_h2_manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    print(f"\n[Manifest Created]: {manifest_file}")
    print(f"  Dataset Content Hash: {dataset_content_hash}")
    return manifest_data


if __name__ == "__main__":
    backfill_holdout()
