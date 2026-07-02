#!/usr/bin/env python3
"""
Build labeled trade records from a historical CSV prefix (e.g. y2023)
and merge into logs/adaptive_signals_v2.json with deduplication.

Usage:
  .venv/bin/python scripts/merge_historical_records.py --month y2023
"""

import argparse
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from scripts import build_and_train as bt
from btc_scraper.core.config import FRESH_TRAINING_DATA_DIR


def detect_coins(month: str) -> list[str]:
    data_dir = BASE / "data"
    # Prefer fresh training data dir
    if FRESH_TRAINING_DATA_DIR.is_absolute():
        hist_dir = Path(FRESH_TRAINING_DATA_DIR)
    else:
        hist_dir = BASE / FRESH_TRAINING_DATA_DIR

    def _coins_from(dir_path: Path) -> list[str]:
        coins = set()
        for p in dir_path.glob(f"{month}_*_15m.csv"):
            parts = p.stem.split("_")
            if len(parts) >= 3:
                coins.add(parts[-2])
        return sorted(coins)

    coins = _coins_from(data_dir)
    if coins:
        return coins
    return _coins_from(hist_dir)


def to_compact_record(record: dict) -> dict:
    entry = {
        "coin": record.get("coin"),
        "result": record.get("result"),
        "pnl_pct": record.get("pnl_pct"),
        "signal_raw": record.get("signal_raw") or record.get("signal"),
        "entry_time": record.get("entry_time"),
        "exit_time": record.get("exit_time"),
        "htf_trend": record.get("htf_trend", ""),
        "signal_score": record.get("signal_score", {}),
    }

    for k, v in record.items():
        if k in entry:
            continue
        if k in {"signal", "features"}:
            continue
        entry[k] = v

    features = record.get("features")
    if isinstance(features, dict):
        entry.update(features)

    if not entry.get("signal_score"):
        raw = str(entry.get("signal_raw", ""))
        entry["signal_score"] = {
            "score": record.get("score", 50),
            "raw_text": raw,
            "action": "BUY" if "BUY" in raw.upper() else "SELL",
        }

    return entry


def dedup_key(record: dict) -> tuple[str, str, str, str]:
    return (
        str(record.get("coin", "")),
        str(record.get("entry_time", "")),
        str(record.get("exit_time", "")),
        str(record.get("signal_raw", "")),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge historical labeled records into adaptive_signals_v2")
    parser.add_argument("--month", default="y2023", help="CSV month prefix in data/, e.g. y2023")
    parser.add_argument("--coins", default="", help="Optional comma-separated subset coins, e.g. BTC,ETH,SOL")
    parser.add_argument("--summary", default="logs/adaptive_signals_v2_2023_merge_summary.json", help="Summary JSON output path")
    args = parser.parse_args()

    logs_dir = BASE / "logs"
    input_file = logs_dir / "adaptive_signals_v2.json"
    summary_file = BASE / args.summary

    coins = detect_coins(args.month)
    if not coins:
        print(f"No 15m CSV found for prefix '{args.month}' in data/ or data/historical_18m")
        return 1

    if args.coins.strip():
        requested = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
        coins = [c for c in coins if c in requested]
        if not coins:
            print(f"No matching coins for --coins={args.coins}")
            return 1

    print(f"Detected coins for {args.month}: {', '.join(coins)}")

    bt.initialize_runtime_dependencies()
    bt._load_sentiment_history()

    built = bt.build_dataset([args.month], coins)
    new_records = [to_compact_record(r) for r in built]

    if input_file.exists():
        existing = json.loads(input_file.read_text(encoding="utf-8"))
    else:
        existing = []

    seen = {dedup_key(r) for r in existing}
    added = 0
    for record in new_records:
        key = dedup_key(record)
        if key in seen:
            continue
        existing.append(record)
        seen.add(key)
        added += 1

    input_file.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {
        "month": args.month,
        "coins": coins,
        "new_records_built": len(new_records),
        "added_records": added,
        "merged_total": len(existing),
    }
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"New records built: {len(new_records)}")
    print(f"Added records: {added}")
    print(f"Merged total: {len(existing)}")
    print(f"Summary saved: {summary_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
