#!/usr/bin/env python3
"""Fetch and freeze D5 historical 3-month 15m shadow market data.

This script is intentionally read-only with respect to governed runtime state:
it writes only raw shadow market-data files plus an identity manifest under the
requested output directory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


SOURCE = "https://data-api.binance.vision/api/v3/klines"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT")
INTERVAL = "15m"
BAR_DELTA = timedelta(minutes=15)
REQUEST_LIMIT = 1000
REQUEST_TIMEOUT_SECONDS = 20
REQUEST_DELAY_SECONDS = 0.2

ANALYSIS_WINDOW_START = datetime(2026, 5, 11, 9, 0, tzinfo=timezone.utc)
ANALYSIS_WINDOW_LAST_BAR_OPEN = datetime(2026, 8, 11, 8, 30, tzinfo=timezone.utc)
ANALYSIS_WINDOW_LAST_BAR_CLOSE = datetime(
    2026, 8, 11, 8, 44, 59, 999000, tzinfo=timezone.utc
)
EXPECTED_ROWS_PER_SYMBOL = 8831

FIELDS = [
    "symbol",
    "open_time",
    "open_time_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "close_time_ms",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_asset_volume",
    "taker_buy_quote_asset_volume",
]


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_open_time(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def expected_open_times(start: datetime, last_open: datetime) -> list[datetime]:
    values = []
    cursor = start
    while cursor <= last_open:
        values.append(cursor)
        cursor += BAR_DELTA
    return values


def row_from_kline(symbol: str, item: list[Any]) -> dict[str, Any]:
    opened = datetime.fromtimestamp(item[0] / 1000, tz=timezone.utc)
    close_time = datetime.fromtimestamp(item[6] / 1000, tz=timezone.utc)
    return {
        "symbol": symbol,
        "open_time": utc_iso(opened),
        "open_time_ms": int(item[0]),
        "open": item[1],
        "high": item[2],
        "low": item[3],
        "close": item[4],
        "volume": item[5],
        "close_time": utc_iso(close_time),
        "close_time_ms": int(item[6]),
        "quote_asset_volume": item[7],
        "number_of_trades": int(item[8]),
        "taker_buy_base_asset_volume": item[9],
        "taker_buy_quote_asset_volume": item[10],
    }


def fetch_symbol(symbol: str, start: datetime, last_open: datetime) -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers.update({"User-Agent": "besttime-crypto-d5-shadow-3m/1.0"})
    start_ms = int(start.timestamp() * 1000)
    end_ms = int((last_open + BAR_DELTA - timedelta(milliseconds=1)).timestamp() * 1000)
    current_ms = start_ms
    rows: list[dict[str, Any]] = []

    while current_ms <= end_ms:
        response = session.get(
            SOURCE,
            params={
                "symbol": symbol,
                "interval": INTERVAL,
                "startTime": current_ms,
                "endTime": end_ms,
                "limit": REQUEST_LIMIT,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload:
            break
        for item in payload:
            opened = datetime.fromtimestamp(item[0] / 1000, tz=timezone.utc)
            if start <= opened <= last_open:
                rows.append(row_from_kline(symbol, item))
        next_ms = int(payload[-1][0]) + int(BAR_DELTA.total_seconds() * 1000)
        if next_ms <= current_ms or len(payload) < REQUEST_LIMIT:
            break
        current_ms = next_ms
        time.sleep(REQUEST_DELAY_SECONDS)

    by_open = {row["open_time"]: row for row in rows}
    return [by_open[key] for key in sorted(by_open)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def validate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected = expected_open_times(ANALYSIS_WINDOW_START, ANALYSIS_WINDOW_LAST_BAR_OPEN)
    expected_set = {utc_iso(dt) for dt in expected}
    open_times = [row["open_time"] for row in rows]
    duplicate_open_count = len(open_times) - len(set(open_times))
    missing = sorted(expected_set - set(open_times))
    unexpected = sorted(set(open_times) - expected_set)
    invalid_ohlc = []
    invalid_close_time = []
    invalid_symbol = []

    for row in rows:
        try:
            opened = parse_open_time(row["open_time"])
            close_time = parse_open_time(row["close_time"])
            open_ = float(row["open"])
            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])
        except Exception:
            invalid_ohlc.append(row.get("open_time"))
            continue
        if high < max(open_, close) or low > min(open_, close):
            invalid_ohlc.append(row["open_time"])
        if close_time != opened + BAR_DELTA - timedelta(milliseconds=1):
            invalid_close_time.append(row["open_time"])
        if row["symbol"] not in SYMBOLS:
            invalid_symbol.append(row["open_time"])

    actual_count = len(rows)
    expected_count = len(expected)
    continuity_pass = (
        actual_count == expected_count
        and duplicate_open_count == 0
        and not missing
        and not unexpected
        and not invalid_ohlc
        and not invalid_close_time
    )
    return {
        "expected_count": expected_count,
        "actual_count": actual_count,
        "duplicate_open_count": duplicate_open_count,
        "missing_bar_count": len(missing),
        "unexpected_bar_count": len(unexpected),
        "invalid_ohlc_count": len(invalid_ohlc),
        "invalid_close_time_count": len(invalid_close_time),
        "invalid_symbol_count": len(invalid_symbol),
        "missing_bar_sample": missing[:20],
        "unexpected_bar_sample": unexpected[:20],
        "invalid_ohlc_sample": invalid_ohlc[:20],
        "invalid_close_time_sample": invalid_close_time[:20],
        "continuity_pass": continuity_pass,
    }


def dataset_id(manifest_without_id: dict[str, Any]) -> str:
    canonical = json.dumps(manifest_without_id, sort_keys=True, separators=(",", ":"))
    return f"d5_shadow_3m_15m_{sha256_text(canonical)[:16]}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch BTC/ETH/BNB Binance Spot 15m bars for D5 3-month shadow replay."
    )
    parser.add_argument(
        "--output-dir",
        default=str(
            Path.home()
            / ".local/state/besttime-crypto/release/8c7b119/d5-v5/historical-3m"
        ),
        help="Directory where raw CSVs, combined CSV, and manifest.json are written.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    raw_dir = output_dir / "raw"
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(manifest_path)
        print(f"Frozen dataset already exists: {manifest.get('DATASET_ID')}")
        return 0 if manifest.get("acceptance", {}).get("continuity_pass") is True else 1

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    symbol_reports: dict[str, Any] = {}
    combined_rows: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        rows = fetch_symbol(symbol, ANALYSIS_WINDOW_START, ANALYSIS_WINDOW_LAST_BAR_OPEN)
        raw_path = raw_dir / f"{symbol}_{INTERVAL}.csv"
        write_csv(raw_path, rows)
        validation = validate_rows(rows)
        symbol_reports[symbol] = {
            "path": str(raw_path),
            "row_count": len(rows),
            "sha256": sha256_file(raw_path),
            "validation": validation,
        }
        combined_rows.extend(rows)

    combined_rows.sort(key=lambda row: (row["open_time"], row["symbol"]))
    combined_path = output_dir / "BTC_ETH_BNB_USDT_15m_3m.csv"
    write_csv(combined_path, combined_rows)

    all_pass = all(report["validation"]["continuity_pass"] for report in symbol_reports.values())
    manifest_without_id = {
        "phase": "D5_HISTORICAL_SHADOW_3M",
        "mode": "READ_ONLY_SHADOW_NON_EVIDENCE",
        "SOURCE": SOURCE,
        "SYMBOLS": list(SYMBOLS),
        "INTERVAL": INTERVAL,
        "START": utc_iso(ANALYSIS_WINDOW_START),
        "END": utc_iso(ANALYSIS_WINDOW_LAST_BAR_CLOSE),
        "LAST_BAR_OPEN": utc_iso(ANALYSIS_WINDOW_LAST_BAR_OPEN),
        "expected_rows_per_symbol": EXPECTED_ROWS_PER_SYMBOL,
        "expected_rows_total": EXPECTED_ROWS_PER_SYMBOL * len(SYMBOLS),
        "ROW_COUNTS": {symbol: report["row_count"] for symbol, report in symbol_reports.items()},
        "SHA256_PER_SYMBOL": {symbol: report["sha256"] for symbol, report in symbol_reports.items()},
        "SHA256_COMBINED": sha256_file(combined_path),
        "raw_files": {symbol: report["path"] for symbol, report in symbol_reports.items()},
        "combined_file": str(combined_path),
        "symbol_results": symbol_reports,
        "acceptance": {
            "expected_count_equals_actual_count": all(
                report["validation"]["expected_count"] == report["validation"]["actual_count"]
                for report in symbol_reports.values()
            ),
            "duplicate_open_count": sum(
                report["validation"]["duplicate_open_count"] for report in symbol_reports.values()
            ),
            "missing_bar_count": sum(
                report["validation"]["missing_bar_count"] for report in symbol_reports.values()
            ),
            "invalid_ohlc_count": sum(
                report["validation"]["invalid_ohlc_count"] for report in symbol_reports.values()
            ),
            "invalid_close_time_count": sum(
                report["validation"]["invalid_close_time_count"]
                for report in symbol_reports.values()
            ),
            "continuity_pass": all_pass,
        },
        "CURRENT_CANARY_120": "IMMUTABLE_REFERENCE_COHORT",
        "HISTORICAL_SHADOW_3M": "READ_ONLY_SHADOW_NON_EVIDENCE",
        "ACTIVE_CANARY_MUTATED": "NO",
        "GOVERNED_EVIDENCE_WRITES": 0,
        "RUNTIME_CONTROL_ACTIONS": 0,
        "ORIGINAL_CANARY_TIMESTAMP_MUTATED": "NO",
        "MARKET_REPLAY_PARITY_CONTRACT_MUTATED": "NO",
    }
    manifest = {"DATASET_ID": dataset_id(manifest_without_id), **manifest_without_id}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(manifest_path)
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
