"""
Ensure that the CSV candle files required for training are present in data/.

By default it checks the same training scope used by train_model_v2.py:
- all coins from btc_scraper.core.config.COINS
- months: january_2025 .. june_2025 plus january .. june
- intervals: 15m, 1h, 4h, 1d

Usage:
    python scripts/ensure_training_data.py --check-only
    python scripts/ensure_training_data.py --fetch
    python scripts/ensure_training_data.py --fetch --coins BTC,ETH,SOL --months april_2025 --intervals 15m,1h
    python scripts/ensure_training_data.py --fetch --train
"""
import argparse
import json
import os
import sys
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
LOGS_DIR = BASE / "logs"
REPORT_PATH = LOGS_DIR / "data_check_report.json"

sys.path.insert(0, str(BASE))

try:
    from btc_scraper.core.config import COINS
except Exception:  # pragma: no cover
    COINS = []

try:
    from fetch_historical_range import fetch_candles, save_csv, INTERVALS as FETCH_INTERVALS
except Exception as exc:  # pragma: no cover
    raise RuntimeError(f"Unable to import fetch_historical_range.py: {exc}") from exc

DEFAULT_MONTHS = [
    "january_2025", "february_2025", "march_2025", "april_2025", "may_2025", "june_2025",
    "july_2025", "august_2025", "september_2025", "october_2025", "november_2025", "december_2025",
    "january", "february", "march", "april", "may", "june",
]
DEFAULT_INTERVALS = ["15m", "1h", "4h", "1d"]
MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check and optionally fetch training data")
    parser.add_argument("--check-only", action="store_true", help="Only report missing files")
    parser.add_argument("--fetch", action="store_true", help="Fetch missing files from Binance")
    parser.add_argument("--coins", default=",".join(COINS), help="Comma-separated coins, e.g. BTC,ETH,SOL")
    parser.add_argument("--months", default=",".join(DEFAULT_MONTHS), help="Comma-separated months")
    parser.add_argument("--intervals", default=",".join(DEFAULT_INTERVALS), help="Comma-separated intervals")
    parser.add_argument("--train", action="store_true", help="Run train_model_v2.py after preparing data")
    parser.add_argument("--n", type=int, default=200, help="Number of trees for train_model_v2.py")
    parser.add_argument("--no-calibrate", action="store_true", help="Disable calibration in train_model_v2.py")
    return parser.parse_args()


def normalize_list(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def month_window(month_name: str) -> tuple[datetime, datetime]:
    normalized = month_name.strip().lower()
    year = 2025
    if "_" in normalized:
        base, maybe_year = normalized.rsplit("_", 1)
        if maybe_year.isdigit():
            year = int(maybe_year)
            normalized = base
    month_num = MONTH_NAMES.get(normalized)
    if month_num is None:
        raise ValueError(f"Unsupported month '{month_name}'.")

    start_dt = datetime(year, month_num, 1, tzinfo=timezone.utc)
    if month_num == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month_num + 1
    end_dt = datetime(next_year, next_month, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
    return start_dt, end_dt


def expected_path(month_name: str, coin: str, interval: str) -> Path:
    return DATA_DIR / f"{month_name}_{coin}_{interval}.csv"


def scan_required_files(coins: list[str], months: list[str], intervals: list[str]) -> tuple[list[dict], list[dict]]:
    existing = []
    missing = []
    for coin in coins:
        for month in months:
            for interval in intervals:
                path = expected_path(month, coin, interval)
                if path.exists() and path.stat().st_size > 100:
                    existing.append({"coin": coin, "month": month, "interval": interval, "path": str(path)})
                else:
                    missing.append({"coin": coin, "month": month, "interval": interval, "path": str(path)})
    return existing, missing


def fetch_missing_files(missing: list[dict], *, quiet: bool = False) -> list[dict]:
    created = []
    for item in missing:
        coin = item["coin"]
        month = item["month"]
        interval = item["interval"]
        path = Path(item["path"])
        start_dt, end_dt = month_window(month)
        target_start_str = start_dt.strftime("%Y-%m-%d %H:%M")
        cfg = FETCH_INTERVALS[interval]
        fetch_start_dt = start_dt - timedelta(days=cfg["warmup_days"])
        if not quiet:
            print(f"Fetching {coin}/{interval} for {month} -> {path.name}")
        candles = fetch_candles(coin, interval, fetch_start_dt, end_dt)
        if not candles:
            if not quiet:
                print(f"  -> no data returned for {coin}/{interval}/{month}")
            continue
        for candle in candles:
            candle["is_warmup"] = 1 if candle["time"] < target_start_str else 0
        save_csv(month, coin, interval, candles)
        created.append({"coin": coin, "month": month, "interval": interval, "path": str(path)})
        if not quiet:
            print(f"  -> saved {len(candles)} candles")
        time.sleep(0.05)
    return created


def write_report(existing: list[dict], missing: list[dict], created: list[dict]) -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "coins": sorted({item["coin"] for item in existing + missing}),
        "months": sorted({item["month"] for item in existing + missing}),
        "intervals": sorted({item["interval"] for item in existing + missing}),
        "existing_count": len(existing),
        "missing_count": len(missing),
        "created_count": len(created),
        "existing": existing[:20],
        "missing": missing[:20],
        "created": created[:20],
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)


def run_training() -> None:
    cmd = [sys.executable, str(BASE / "train_model_v2.py"), "--train"]
    if args.n is not None:
        cmd.extend(["--n", str(args.n)])
    if args.no_calibrate:
        cmd.append("--no-calibrate")
    print("Running training command:", " ".join(cmd))
    subprocess.run(cmd, cwd=str(BASE), check=False)


def main() -> int:
    args = parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    coins = normalize_list(args.coins) or list(COINS)
    months = normalize_list(args.months) or DEFAULT_MONTHS
    intervals = normalize_list(args.intervals) or DEFAULT_INTERVALS

    if not coins:
        print("No coins configured. Aborting.")
        return 2

    existing, missing = scan_required_files(coins, months, intervals)

    print("=" * 72)
    print("TRAINING DATA CHECK")
    print(f"Coins: {', '.join(coins)}")
    print(f"Months: {', '.join(months)}")
    print(f"Intervals: {', '.join(intervals)}")
    print(f"Existing files: {len(existing)}")
    print(f"Missing files: {len(missing)}")
    print("=" * 72)

    if missing:
        print("First missing samples:")
        for item in missing[:20]:
            print(" -", item["path"])
    if args.check_only:
        write_report(existing, missing, [])
        return 0

    if args.fetch and missing:
        created = fetch_missing_files(missing)
        write_report(existing, missing, created)
        remaining = scan_required_files(coins, months, intervals)[1]
        print(f"Created files: {len(created)}")
        print(f"Remaining missing after fetch: {len(remaining)}")
        if args.train and not remaining:
            run_training()
        return 0

    if args.fetch and not missing:
        print("No missing files; nothing to fetch.")
        write_report(existing, missing, [])
        if args.train:
            run_training()
        return 0

    write_report(existing, missing, [])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
