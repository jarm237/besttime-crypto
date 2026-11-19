#!/usr/bin/env python3
"""Targeted Backfill Script for 2026 H2 Binance Spot 1h Archives.

Backfills strictly missing archives from official Binance Public Vision:
- SOLUSDT: 2026-07 to 2026-10 (monthly), 2026-11-01 to 2026-11-18 (daily)
- BNBUSDT: 2026-07 to 2026-10 (monthly), 2026-11-01 to 2026-11-18 (daily)
- BTCUSDT: 2026-11-10 to 2026-11-18 (daily)
- ETHUSDT: 2026-11-10 to 2026-11-18 (daily)

Validates SHA-256 against official Binance .CHECKSUM sidecar immediately.
"""
from __future__ import annotations

import hashlib
import os
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOLDOUT_ROOT = REPO_ROOT / "data/historical/raw/holdout_spot"

BASE_MONTHLY = "https://data.binance.vision/data/spot/monthly/klines/{sym}/1h/{sym}-1h-{p}.zip"
BASE_DAILY = "https://data.binance.vision/data/spot/daily/klines/{sym}/1h/{sym}-1h-{p}.zip"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def download_and_verify(url: str, dest_dir: Path, filename: str) -> dict[str, object]:
    dest_file = dest_dir / filename
    sidecar_file = dest_dir / f"{filename}.sha256"

    # Check if already exists and valid
    if dest_file.exists() and sidecar_file.exists():
        existing_hash = sha256_file(dest_file)
        sidecar_hash = sidecar_file.read_text(encoding="utf-8").strip().split()[0].lower()
        if existing_hash == sidecar_hash:
            return {"file": filename, "status": "ALREADY_EXISTS_VALID", "sha256": existing_hash}

    checksum_url = f"{url}.CHECKSUM"
    req_chk = urllib.request.Request(checksum_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req_chk, timeout=10) as resp:
        expected_hash = resp.read().decode("utf-8").strip().split()[0].lower()

    req_data = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req_data, timeout=30) as resp:
        content = resp.read()

    actual_hash = hashlib.sha256(content).hexdigest()
    if actual_hash != expected_hash:
        raise RuntimeError(f"SHA256 mismatch for {filename}: expected {expected_hash}, got {actual_hash}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    with open(dest_file, "wb") as f:
        f.write(content)

    sidecar_file.write_text(f"{actual_hash}  {filename}\n", encoding="utf-8")
    return {"file": filename, "status": "DOWNLOADED_AND_VERIFIED", "sha256": actual_hash}


def main():
    print("=== STARTING TARGETED DATA BACKFILL (BINANCE SPOT 1H) ===")
    targets = []

    # SOL & BNB: 2026-07 to 2026-10 monthly
    for sym in ["SOLUSDT", "BNBUSDT"]:
        for m in ["2026-07", "2026-08", "2026-09", "2026-10"]:
            targets.append((sym, BASE_MONTHLY.format(sym=sym, p=m), f"{sym}-1h-{m}.zip"))

    # SOL & BNB: 2026-11-01 to 2026-11-18 daily
    for sym in ["SOLUSDT", "BNBUSDT"]:
        for d in range(1, 19):
            p = f"2026-11-{d:02d}"
            targets.append((sym, BASE_DAILY.format(sym=sym, p=p), f"{sym}-1h-{p}.zip"))

    # BTC & ETH: 2026-11-10 to 2026-11-18 daily (2026-07 to 2026-11-09 already present)
    for sym in ["BTCUSDT", "ETHUSDT"]:
        for d in range(10, 19):
            p = f"2026-11-{d:02d}"
            targets.append((sym, BASE_DAILY.format(sym=sym, p=p), f"{sym}-1h-{p}.zip"))

    print(f"Total backfill targets to process: {len(targets)}")
    results = []
    for idx, (sym, url, fn) in enumerate(targets, 1):
        dest_dir = HOLDOUT_ROOT / sym
        res = download_and_verify(url, dest_dir, fn)
        results.append(res)
        print(f"[{idx}/{len(targets)}] {sym} {fn}: {res['status']} ({res['sha256'][:16]}...)")

    print("\nBackfill complete. All downloaded files verified against Binance Vision official .CHECKSUM sidecars.")


if __name__ == "__main__":
    main()
