#!/usr/bin/env python3
"""Launcher to build datasets per-coin in parallel by spawning
multiple `build_coin_worker.py` processes.

Usage:
  python scripts/build_coins_parallel.py --jobs 4 --coins BTC,ETH
  python scripts/build_coins_parallel.py --jobs 8        # all coins from config
"""
import argparse
import subprocess
import os
from pathlib import Path


def load_all_coins():
    try:
        # Import project config to get default coin list
        from btc_scraper.core.config import COINS
        return list(COINS)
    except Exception:
        # Fallback: auto-detect coins from CSV files in `data/` directory.
        coins = set()
        data_dir = Path("data")
        if data_dir.exists():
            for p in data_dir.iterdir():
                if not p.is_file():
                    continue
                name = p.stem  # filename without extension
                parts = name.split("_")
                # Heuristic: token that is uppercase alnum and length 2-6
                for tok in parts:
                    if tok.isupper() and tok.isalnum() and 2 <= len(tok) <= 6 and not tok.isdigit():
                        coins.add(tok)
                        break
        return sorted(coins)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--coins", default="", help="Comma-separated coins or empty=all")
    parser.add_argument("--python", default="python", help="Python executable")
    args = parser.parse_args()

    if args.coins:
        coins = [c.strip() for c in args.coins.split(",") if c.strip()]
    else:
        coins = load_all_coins()

    if not coins:
        print("No coins found. Provide --coins or ensure btc_scraper.core.config.COINS is available.")
        return

    print(f"Building {len(coins)} coins with {args.jobs} parallel jobs")

    work_dir = Path.cwd()
    procs = []
    running = 0
    idx = 0
    total = len(coins)

    while idx < total or procs:
        # Start new processes if slots available
        while running < args.jobs and idx < total:
            coin = coins[idx]
            cmd = [args.python, "scripts/build_coin_worker.py", "--coin", coin]
            print(f"Starting: {cmd}")
            p = subprocess.Popen(cmd, cwd=str(work_dir))
            procs.append((coin, p))
            running += 1
            idx += 1

        # Check processes
        for coin, p in list(procs):
            ret = p.poll()
            if ret is not None:
                procs.remove((coin, p))
                running -= 1
                status = 'OK' if ret == 0 else f'EXIT={ret}'
                print(f"Finished {coin}: {status}")

    print("All workers finished")


if __name__ == "__main__":
    main()
