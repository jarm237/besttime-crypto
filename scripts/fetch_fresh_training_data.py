#!/usr/bin/env python3
"""
Fetch fresh OHLCV data for training from Binance and store it in a dedicated folder.

This script intentionally does not reuse prior CSVs. It creates a fresh output
folder and downloads data from Jan 2023 through Jun 2026 for the configured
coins and intervals. The design includes rate-limit avoidance via pagination,
small delays, and retry/backoff.

Usage examples:
    python scripts/fetch_fresh_training_data.py --dry-run
    python scripts/fetch_fresh_training_data.py --overwrite
    python scripts/fetch_fresh_training_data.py --coins BTC,ETH,SOL --intervals 15m,1h
"""

from __future__ import annotations

import argparse
import calendar
import csv
import json
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from btc_scraper.core.config import COINS  # noqa: E402

BINANCE_BASE = "https://api.binance.com"
DEFAULT_OUTPUT_DIR = BASE_DIR / "data" / "fresh_training_data_2023_2026"
INTERVALS = ["15m", "1h", "4h", "1d"]
WARMUP_DAYS = {"15m": 3, "1h": 10, "4h": 38, "1d": 220}
REQUEST_DELAY_SECONDS = 0.25
REQUEST_RETRIES = 5
REQUEST_TIMEOUT_SECONDS = 20
CANDLES_PER_REQUEST = 1000


def iter_months(start_year: int, start_month: int, end_year: int, end_month: int) -> Iterable[tuple[int, int]]:
    year = start_year
    month = start_month
    while (year, month) <= (end_year, end_month):
        yield year, month
        month += 1
        if month > 12:
            month = 1
            year += 1


def parse_coin_list(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return list(COINS)
    items = [coin.strip().upper() for coin in raw.split(",") if coin.strip()]
    invalid = [coin for coin in items if coin not in COINS]
    if invalid:
        raise SystemExit(f"Unknown coin(s): {', '.join(invalid)}")
    return items


def parse_interval_list(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return INTERVALS.copy()
    items = [interval.strip() for interval in raw.split(",") if interval.strip()]
    invalid = [interval for interval in items if interval not in INTERVALS]
    if invalid:
        raise SystemExit(f"Unsupported interval(s): {', '.join(invalid)}")
    return items


def month_start_end(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, 0, 0, 0, tzinfo=timezone.utc)
    last_day = calendar.monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


def prepare_output_dir(path: Path, overwrite: bool) -> Path:
    if path.exists():
        if overwrite:
            shutil.rmtree(path)
        else:
            raise FileExistsError(
                f"Output directory already exists: {path}. Use --overwrite to replace it."
            )
    path.mkdir(parents=True, exist_ok=True)
    return path


def fetch_json_with_retry(session: requests.Session, url: str, params: dict, *, retries: int = REQUEST_RETRIES) -> list[list]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 429:
                raise requests.HTTPError("Rate limited")
            if response.status_code >= 500:
                raise requests.HTTPError(f"Server error {response.status_code}")
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise ValueError(f"Unexpected Binance response type: {type(data).__name__}")
            return data
        except requests.RequestException as exc:  # noqa: BLE001
            last_error = exc
            if attempt == retries - 1:
                break
            wait_seconds = REQUEST_DELAY_SECONDS * (attempt + 1)
            if exc.response is not None and exc.response.headers.get("Retry-After"):
                try:
                    wait_seconds = max(float(exc.response.headers["Retry-After"]), wait_seconds)
                except ValueError:
                    pass
            print(f"    [retry {attempt + 1}/{retries}] waiting {wait_seconds:.2f}s: {exc}")
            time.sleep(wait_seconds)
    if last_error is not None:
        raise RuntimeError(f"Failed to fetch Binance data: {last_error}") from last_error
    raise RuntimeError("Failed to fetch Binance data")


def fetch_candles(session: requests.Session, coin: str, interval: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    symbol = f"{coin}USDT"
    url = f"{BINANCE_BASE}/api/v3/klines"
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    candles: list[dict] = []
    current_start = start_ms
    while current_start < end_ms:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "endTime": end_ms,
            "limit": CANDLES_PER_REQUEST,
        }
        raw = fetch_json_with_retry(session, url, params)
        if not raw:
            break

        for row in raw:
            candles.append(
                {
                    "time": datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "is_warmup": 0,
                }
            )

        last_ts = raw[-1][0]
        if last_ts >= end_ms or len(raw) < CANDLES_PER_REQUEST:
            break
        current_start = last_ts + 1
        time.sleep(REQUEST_DELAY_SECONDS)

    if not candles:
        return []

    seen: set[str] = set()
    deduped: list[dict] = []
    for candle in candles:
        if candle["time"] in seen:
            continue
        seen.add(candle["time"])
        deduped.append(candle)
    deduped.sort(key=lambda item: item["time"])
    return deduped


def save_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_manifest(output_dir: Path, ranges: list[tuple[int, int]], coins: list[str], intervals: list[str], file_summary: dict) -> dict:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "binance_klines",
        "range": {
            "start": f"{ranges[0][0]}-{ranges[0][1]:02d}",
            "end": f"{ranges[-1][0]}-{ranges[-1][1]:02d}",
        },
        "coins": coins,
        "intervals": intervals,
        "output_dir": str(output_dir),
        "files": file_summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch fresh OHLCV history for training")
    parser.add_argument("--start-year", type=int, default=2023)
    parser.add_argument("--start-month", type=int, default=1)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--end-month", type=int, default=6)
    parser.add_argument("--coins", type=str, default=",".join(COINS))
    parser.add_argument("--intervals", type=str, default=",".join(INTERVALS))
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--overwrite", action="store_true", help="Delete the existing output directory before fetching")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned work without downloading data")
    args = parser.parse_args()

    if not 1 <= args.start_month <= 12 or not 1 <= args.end_month <= 12:
        raise SystemExit("Month values must be between 1 and 12")
    if (args.start_year, args.start_month) > (args.end_year, args.end_month):
        raise SystemExit("Start date must be earlier than or equal to end date")

    coins = parse_coin_list(args.coins)
    intervals = parse_interval_list(args.intervals)
    output_dir = Path(args.output_dir).resolve()

    months = list(iter_months(args.start_year, args.start_month, args.end_year, args.end_month))
    print("=" * 78)
    print("  FRESH TRAINING DATA FETCHER")
    print(f"  Range: {args.start_year:04d}-{args.start_month:02d} -> {args.end_year:04d}-{args.end_month:02d}")
    print(f"  Coins: {', '.join(coins)}")
    print(f"  Intervals: {', '.join(intervals)}")
    print(f"  Output dir: {output_dir}")
    print("=" * 78)

    if args.dry_run:
        print(f"Dry run: would create {len(months) * len(coins) * len(intervals)} monthly fetch jobs")
        return 0

    output_dir = prepare_output_dir(output_dir, args.overwrite)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; fresh-data-fetcher/1.0)"})

    file_summary: dict[str, dict] = {}
    total_rows = 0

    for coin in coins:
        coin_dir = output_dir / coin
        coin_dir.mkdir(parents=True, exist_ok=True)
        for interval in intervals:
            interval_dir = coin_dir / interval
            interval_dir.mkdir(parents=True, exist_ok=True)
            print(f"[{coin}/{interval}]")
            for year, month in months:
                month_start, month_end = month_start_end(year, month)
                warmup_start = month_start - timedelta(days=WARMUP_DAYS[interval])
                print(f"  {year:04d}-{month:02d}: fetching ...")
                candles = fetch_candles(session, coin, interval, warmup_start, month_end)
                if not candles:
                    print("    [warn] no candles returned")
                    continue
                for candle in candles:
                    candle["is_warmup"] = 1 if candle["time"] < month_start.strftime("%Y-%m-%d %H:%M") else 0
                candles = sorted(candles, key=lambda item: item["time"])
                seen: set[str] = set()
                deduped_rows: list[dict] = []
                for candle in candles:
                    if candle["time"] in seen:
                        continue
                    seen.add(candle["time"])
                    deduped_rows.append(candle)

                target_path = interval_dir / f"{coin}_{interval}_{year:04d}-{month:02d}.csv"
                try:
                    save_csv(target_path, deduped_rows)
                except Exception as exc:  # noqa: BLE001
                    print(f"    [error] failed to save {target_path}: {exc}")
                    continue
                total_rows += len(deduped_rows)
                file_summary[target_path.relative_to(output_dir).as_posix()] = {
                    "rows": len(deduped_rows),
                    "start": deduped_rows[0]["time"] if deduped_rows else None,
                    "end": deduped_rows[-1]["time"] if deduped_rows else None,
                }
                print(f"    saved {target_path} ({len(deduped_rows)} rows)")
                time.sleep(REQUEST_DELAY_SECONDS)

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(build_manifest(output_dir, months, coins, intervals, file_summary), indent=2, ensure_ascii=False), encoding="utf-8")
    print("=" * 78)
    print(f"Completed: {total_rows} rows written to {output_dir}")
    print(f"Manifest: {manifest_path}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
