"""
Fetch data for a full year (or selected months).
Usage:
  python scripts/fetch_year.py --year 2024 [--months 1,2,3] [--dry-run]

This reuses `fetch_candles` and `save_csv` from `fetch_historical_range.py`.
Dry-run will only print planned month/coin/interval counts.
"""
import argparse
import calendar
from datetime import datetime, timezone, timedelta
import sys, os

# Ensure repo root is on sys.path so we can import fetch_historical_range
repo_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, repo_root)
from fetch_historical_range import fetch_candles, save_csv, INTERVALS
from btc_scraper.core.config import COINS


def month_start_end(year: int, month: int):
    start = datetime(year, month, 1, 0, 0, tzinfo=timezone.utc)
    last_day = calendar.monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--year', type=int, required=True)
    p.add_argument('--months', type=str, default=None,
                   help='Comma-separated month numbers, e.g. 1,2,3')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()

    months = list(range(1,13))
    if args.months:
        months = [int(m) for m in args.months.split(',') if m.strip()]

    plan = []
    for m in months:
        s,e = month_start_end(args.year, m)
        plan.append({'month': m, 'start': s, 'end': e})

    total_files = 0
    for item in plan:
        month_name = item['start'].strftime('%B').lower()
        for coin in COINS:
            for interval in INTERVALS.keys():
                total_files += 1
    if args.dry_run:
        print(f"Dry-run: will fetch {total_files} files for year {args.year} (coins={len(COINS)}, intervals={len(INTERVALS)})")
        return 0

    for item in plan:
        month_name = item['start'].strftime('%B').lower()
        print(f"Fetching month {month_name} {args.year}...")
        for coin in COINS:
            print(f"  Coin: {coin}")
            for interval, cfg in INTERVALS.items():
                warmup_days = cfg.get('warmup_days', 3)
                start_dt = item['start'] - timedelta(days=warmup_days)
                end_dt = item['end']
                print(f"    {interval} start={start_dt} end={end_dt}")
                candles = fetch_candles(coin, interval, start_dt, end_dt)
                if not candles:
                    print(f"      [WARN] no candles for {coin}/{interval}/{month_name}")
                    continue
                path = save_csv(month_name, coin, interval, candles)
                print(f"      saved {path}")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
