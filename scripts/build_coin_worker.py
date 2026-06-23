#!/usr/bin/env python3
"""Worker script: build dataset for a single coin using functions from
`scripts/build_and_train.py`. This runs in a separate process to allow
parallel builds.

Usage:
  python scripts/build_coin_worker.py --coin BTC
"""
import argparse
import json
import runpy
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coin", required=True)
    args = parser.parse_args()

    # Load build_and_train into an isolated namespace
    ns = runpy.run_path("scripts/build_and_train.py")

    # Initialize runtime and load sentiment history
    ns.get("initialize_runtime_dependencies", lambda: None)()
    ns.get("_load_sentiment_history", lambda: None)()

    months = ns.get("get_available_months", lambda: [])()
    if not months:
        print("[worker] No months available, aborting.")
        return

    coin = args.coin
    print(f"[worker] Building dataset for {coin} (months={months})")
    trades = ns.get("build_dataset", lambda *_: [])(months, [coin])

    out_dir = Path("logs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"adaptive_signals_v2_{coin}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2, ensure_ascii=False)

    print(f"[worker] Saved {len(trades)} records → {out_file}")


if __name__ == "__main__":
    main()
