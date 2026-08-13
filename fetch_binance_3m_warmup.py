#!/usr/bin/env python3
"""Fetch and freeze D5 historical 3-month feature warm-up market data."""

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
REQUEST_LIMIT = 1000
REQUEST_TIMEOUT_SECONDS = 20
REQUEST_DELAY_SECONDS = 0.2
EXPECTED_ROWS_PER_SYMBOL_TIMEFRAME = 220

WINDOWS = {
    "15m": {
        "start": datetime(2026, 5, 9, 2, 0, tzinfo=timezone.utc),
        "last_bar_open": datetime(2026, 5, 11, 8, 45, tzinfo=timezone.utc),
        "delta": timedelta(minutes=15),
    },
    "1h": {
        "start": datetime(2026, 5, 2, 5, 0, tzinfo=timezone.utc),
        "last_bar_open": datetime(2026, 5, 11, 8, 0, tzinfo=timezone.utc),
        "delta": timedelta(hours=1),
    },
    "4h": {
        "start": datetime(2026, 4, 4, 16, 0, tzinfo=timezone.utc),
        "last_bar_open": datetime(2026, 5, 11, 4, 0, tzinfo=timezone.utc),
        "delta": timedelta(hours=4),
    },
    "1d": {
        "start": datetime(2025, 10, 3, 0, 0, tzinfo=timezone.utc),
        "last_bar_open": datetime(2026, 5, 10, 0, 0, tzinfo=timezone.utc),
        "delta": timedelta(days=1),
    },
}

FIELDS = [
    "symbol",
    "interval",
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
    "quality_denominator",
]


def utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_open_time(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
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


def expected_open_times(start: datetime, last_open: datetime, delta: timedelta) -> list[datetime]:
    values = []
    cursor = start
    while cursor <= last_open:
        values.append(cursor)
        cursor += delta
    return values


def row_from_kline(symbol: str, interval: str, item: list[Any]) -> dict[str, Any]:
    opened = datetime.fromtimestamp(item[0] / 1000, tz=timezone.utc)
    close_time = datetime.fromtimestamp(item[6] / 1000, tz=timezone.utc)
    return {
        "symbol": symbol,
        "interval": interval,
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
        "quality_denominator": 0,
    }


def fetch_symbol_interval(symbol: str, interval: str, spec: dict[str, Any]) -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers.update({"User-Agent": "besttime-crypto-d5-shadow-warmup/1.0"})
    start = spec["start"]
    last_open = spec["last_bar_open"]
    delta = spec["delta"]
    start_ms = int(start.timestamp() * 1000)
    end_ms = int((last_open + delta - timedelta(milliseconds=1)).timestamp() * 1000)
    current_ms = start_ms
    rows: list[dict[str, Any]] = []

    while current_ms <= end_ms:
        response = session.get(
            SOURCE,
            params={
                "symbol": symbol,
                "interval": interval,
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
                rows.append(row_from_kline(symbol, interval, item))
        next_ms = int(payload[-1][0]) + int(delta.total_seconds() * 1000)
        if next_ms <= current_ms or len(payload) < REQUEST_LIMIT:
            break
        current_ms = next_ms
        time.sleep(REQUEST_DELAY_SECONDS)

    by_open = {row["open_time"]: row for row in rows}
    return [by_open[key] for key in sorted(by_open)]


def validate_rows(rows: list[dict[str, Any]], interval: str, spec: dict[str, Any]) -> dict[str, Any]:
    expected = {utc_iso(dt) for dt in expected_open_times(spec["start"], spec["last_bar_open"], spec["delta"])}
    open_times = [row["open_time"] for row in rows]
    missing = sorted(expected - set(open_times))
    unexpected = sorted(set(open_times) - expected)
    duplicate_open_count = len(open_times) - len(set(open_times))
    invalid_ohlc = []
    invalid_close_time = []
    invalid_denominator = []
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
        if row.get("quality_denominator") != 0:
            invalid_denominator.append(row["open_time"])
        if high < max(open_, close) or low > min(open_, close):
            invalid_ohlc.append(row["open_time"])
        if close_time != opened + spec["delta"] - timedelta(milliseconds=1):
            invalid_close_time.append(row["open_time"])
        if row.get("interval") != interval:
            invalid_close_time.append(row["open_time"])

    actual_count = len(rows)
    expected_count = EXPECTED_ROWS_PER_SYMBOL_TIMEFRAME
    continuity_pass = (
        actual_count == expected_count
        and len(expected) == expected_count
        and duplicate_open_count == 0
        and not missing
        and not unexpected
        and not invalid_ohlc
        and not invalid_close_time
        and not invalid_denominator
    )
    return {
        "expected_count": expected_count,
        "actual_count": actual_count,
        "duplicate_open_count": duplicate_open_count,
        "missing_bar_count": len(missing),
        "unexpected_bar_count": len(unexpected),
        "invalid_ohlc_count": len(invalid_ohlc),
        "invalid_close_time_count": len(invalid_close_time),
        "invalid_quality_denominator_count": len(invalid_denominator),
        "continuity_pass": continuity_pass,
        "missing_bar_sample": missing[:20],
        "unexpected_bar_sample": unexpected[:20],
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def dataset_id(manifest_without_id: dict[str, Any]) -> str:
    canonical = json.dumps(manifest_without_id, sort_keys=True, separators=(",", ":"))
    return f"d5_shadow_3m_warmup_{sha256_text(canonical)[:16]}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch D5 3M shadow feature warm-up bars.")
    parser.add_argument(
        "--output-dir",
        default=str(
            Path.home()
            / ".local/state/besttime-crypto/release/8c7b119/d5-v5/historical-3m/warmup"
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(manifest_path)
        print(f"Frozen warmup dataset already exists: {manifest.get('DATASET_ID')}")
        return 0 if manifest.get("acceptance", {}).get("continuity_pass") is True else 1

    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    combined_rows: list[dict[str, Any]] = []

    for symbol in SYMBOLS:
        for interval, spec in WINDOWS.items():
            rows = fetch_symbol_interval(symbol, interval, spec)
            raw_path = raw_dir / f"{symbol}_{interval}_warmup.csv"
            write_csv(raw_path, rows)
            validation = validate_rows(rows, interval, spec)
            key = f"{symbol}:{interval}"
            results[key] = {
                "symbol": symbol,
                "interval": interval,
                "path": str(raw_path),
                "row_count": len(rows),
                "sha256": sha256_file(raw_path),
                "warmup_start": utc_iso(spec["start"]),
                "warmup_last_bar_open": utc_iso(spec["last_bar_open"]),
                "quality_denominator_rows": 0,
                "validation": validation,
            }
            combined_rows.extend(rows)

    combined_rows.sort(key=lambda row: (row["open_time"], row["symbol"], row["interval"]))
    combined_path = output_dir / "BTC_ETH_BNB_USDT_warmup_15m_1h_4h_1d.csv"
    write_csv(combined_path, combined_rows)
    all_pass = all(item["validation"]["continuity_pass"] for item in results.values())
    manifest_without_id = {
        "phase": "D5_HISTORICAL_SHADOW_3M_H3B_WARMUP_DATASET",
        "mode": "READ_ONLY_SHADOW_FEATURE_WARMUP_NON_DENOMINATOR",
        "SOURCE": SOURCE,
        "SYMBOLS": list(SYMBOLS),
        "INTERVALS": list(WINDOWS),
        "EXPECTED_ROWS_PER_SYMBOL_TIMEFRAME": EXPECTED_ROWS_PER_SYMBOL_TIMEFRAME,
        "EXPECTED_ROWS_TOTAL": EXPECTED_ROWS_PER_SYMBOL_TIMEFRAME * len(SYMBOLS) * len(WINDOWS),
        "WINDOWS": {
            interval: {
                "start": utc_iso(spec["start"]),
                "last_bar_open": utc_iso(spec["last_bar_open"]),
            }
            for interval, spec in WINDOWS.items()
        },
        "ROW_COUNTS": {key: item["row_count"] for key, item in results.items()},
        "SHA256_PER_SYMBOL_TIMEFRAME": {key: item["sha256"] for key, item in results.items()},
        "SHA256_COMBINED": sha256_file(combined_path),
        "combined_file": str(combined_path),
        "symbol_timeframe_results": results,
        "acceptance": {
            "expected_count_equals_actual_count": all(
                item["validation"]["expected_count"] == item["validation"]["actual_count"]
                for item in results.values()
            ),
            "duplicate_open_count": sum(item["validation"]["duplicate_open_count"] for item in results.values()),
            "missing_bar_count": sum(item["validation"]["missing_bar_count"] for item in results.values()),
            "invalid_ohlc_count": sum(item["validation"]["invalid_ohlc_count"] for item in results.values()),
            "invalid_close_time_count": sum(
                item["validation"]["invalid_close_time_count"] for item in results.values()
            ),
            "invalid_quality_denominator_count": sum(
                item["validation"]["invalid_quality_denominator_count"] for item in results.values()
            ),
            "continuity_pass": all_pass,
        },
        "FEATURE_WARMUP": "SUFFICIENT_AFTER_WARMUP_DATASET",
        "WARMUP_ROWS_IN_QUALITY_DENOMINATOR": 0,
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
