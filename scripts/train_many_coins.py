#!/usr/bin/env python3
"""
Launch multi-coin training in parallel using subprocess workers.
This is intended for the dataset-building step and can optionally invoke
training once each worker has produced its per-coin signal file.

Usage:
  python scripts/train_many_coins.py --coins BTC,ETH,SOL --jobs 3 --months april_2025,june_2025
  python scripts/train_many_coins.py --coins BTC,ETH,SOL --jobs 3 --train
  python scripts/train_many_coins.py --coins BTC,ETH,SOL --jobs 3 --gpu --device-id 0
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from btc_scraper.core.config import COINS as DEFAULT_COINS


def _discover_default_months() -> list[str]:
    candidates = [BASE / "data" / "historical_18m", BASE / "data"]
    months = set()
    for root in candidates:
        if not root.exists():
            continue
        for path in root.glob("*_15m.csv"):
            stem = path.stem
            parts = stem.split("_")
            if len(parts) >= 3:
                months.add(f"{parts[0]}_{parts[1]}")
    return sorted(months)


def parse_args():
    parser = argparse.ArgumentParser(description="Run multi-coin training in parallel")
    parser.add_argument("--coins", default=None, help="Comma-separated coin list (defaults to all configured coins)")
    parser.add_argument("--jobs", type=int, default=3, help="Number of parallel workers")
    parser.add_argument("--months", default=None, help="Comma-separated months (defaults to all available training months)")
    parser.add_argument("--train", action="store_true", help="Run model training after per-coin artifacts are built")
    parser.add_argument("--gpu", action="store_true", help="Pass GPU flags to training")
    parser.add_argument("--device-id", type=int, default=0, help="GPU device id for GPU training")
    return parser.parse_args()


def main():
    args = parse_args()
    coins = [c.strip().upper() for c in (args.coins or ",".join(DEFAULT_COINS)).split(",") if c.strip()]
    months = [m.strip() for m in (args.months or ",".join(_discover_default_months())).split(",") if m.strip()]

    if not coins:
        raise SystemExit("No coins supplied")

    print(f"Launching parallel training for {len(coins)} coins with {args.jobs} workers")
    print(f"Months: {months}")

    procs = []
    idx = 0
    total = len(coins)
    running = 0

    while idx < total or procs:
        while running < args.jobs and idx < total:
            coin = coins[idx]
            cmd = [sys.executable, str(BASE / "scripts" / "build_coin_worker.py"), "--coin", coin]
            env = os.environ.copy()
            env["TRAIN_MONTHS"] = ",".join(months)
            env["TRAIN_COINS"] = ",".join(coins)
            if args.gpu:
                env["USE_GPU"] = "1"
                env["GPU_DEVICE_ID"] = str(args.device_id)
            print(f"Starting worker for {coin}: {' '.join(cmd)}")
            proc = subprocess.Popen(cmd, cwd=str(BASE), env=env)
            procs.append((coin, proc))
            running += 1
            idx += 1

        for coin, proc in list(procs):
            ret = proc.poll()
            if ret is not None:
                procs.remove((coin, proc))
                running -= 1
                print(f"Finished {coin}: exit={ret}")

        if procs:
            import time
            time.sleep(1)

    if args.train or args.gpu:
        train_cmd = [sys.executable, str(BASE / "scripts" / "build_and_train.py"), "--skip-build"]
        if args.gpu:
            train_cmd.extend(["--use-gpu", "--device-id", str(args.device_id)])
        print(f"Training meta model with {'GPU' if args.gpu else 'CPU'} backend")
        subprocess.run(train_cmd, cwd=str(BASE), check=False)


if __name__ == "__main__":
    main()
