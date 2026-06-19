"""
Fetch Historical Range Data (CLI)
=================================
Cào dữ liệu lịch sử theo khoảng thời gian truyền từ CLI.
Hỗ trợ chọn danh sách coin, dùng cho các bài toán backfill (ví dụ năm 2023).

Output:
    data/<prefix>_<COIN>_<khung>.csv

Cách chạy:
    python fetch_historical_range.py --start 2023-01-01 --end 2023-12-31 --coins BTC,ETH,SOL
    python fetch_historical_range.py --start 2023-01-01 --end 2023-12-31 --coins all --prefix y2023
"""

import argparse
import sys, os, time, csv, requests
from datetime import datetime, timedelta, timezone

# Force stdout to UTF-8 to support Vietnamese characters in console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(__file__))
from btc_scraper.core.config import COINS

# Warmup candles cần thiết để SMA200 có giá trị (tránh all-zeros)
WARMUP_CANDLES = 220

# Định nghĩa các khung + warmup tương ứng (tính bằng ngày)
INTERVALS = {
    "15m": {"minutes": 15,   "warmup_days": 3},    # 220×15min ≈ 55h
    "1h":  {"minutes": 60,   "warmup_days": 10},   # 220×1h   ≈ 9.2 ngày
    "4h":  {"minutes": 240,  "warmup_days": 38},   # 220×4h   ≈ 36.7 ngày
    "1d":  {"minutes": 1440, "warmup_days": 222},  # 220×1d   = 220 ngày
}

CANDLES_PER_REQ = 1000
DATA_DIR        = os.path.join(os.path.dirname(__file__), "data")
BINANCE_BASE    = "https://api.binance.com"

os.makedirs(DATA_DIR, exist_ok=True)


def fetch_candles(coin: str, interval: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    symbol   = f"{coin}USDT"
    url      = f"{BINANCE_BASE}/api/v3/klines"
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int(end_dt.timestamp() * 1000)

    all_candles = []
    current_start = start_ms

    while current_start < end_ms:
        params = {
            "symbol":    symbol,
            "interval":  interval,
            "startTime": current_start,
            "endTime":   end_ms,
            "limit":     CANDLES_PER_REQ,
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            print(f"    [Lỗi] {coin}/{interval}: {e}")
            break

        if not raw:
            break

        for k in raw:
            all_candles.append({
                "time":      datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
                             .strftime("%Y-%m-%d %H:%M"),
                "open":      float(k[1]),
                "high":      float(k[2]),
                "low":       float(k[3]),
                "close":     float(k[4]),
                "volume":    float(k[5]),
                "is_warmup": 0,
            })

        last_ts = raw[-1][0]
        if last_ts >= end_ms or len(raw) < CANDLES_PER_REQ:
            break
        current_start = last_ts + 1
        time.sleep(0.12)

    # Dedup + sort
    seen   = set()
    unique = []
    for c in all_candles:
        if c["time"] not in seen:
            seen.add(c["time"])
            unique.append(c)
    unique.sort(key=lambda x: x["time"])

    return unique


def save_csv(prefix: str, coin: str, interval: str, candles: list[dict]) -> str:
    path = os.path.join(DATA_DIR, f"{prefix}_{coin}_{interval}.csv")
    if not candles:
        return path
    fieldnames = list(candles[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(candles)
    return path


def print_summary(interval: str, candles: list[dict], target_start_str: str):
    warmup = sum(1 for c in candles if c["is_warmup"])
    actual = len(candles) - warmup
    if candles:
        first = candles[0]["time"]
        last  = candles[-1]["time"]
        print(f"    {interval:>3}: {len(candles):>5} nến (warmup={warmup}, target={actual}) | {first} → {last}")
    else:
        print(f"    {interval:>3}: [Không có dữ liệu]")


def parse_datetime_utc(value: str, *, is_end: bool = False) -> datetime:
    fmts = ["%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"]
    for fmt in fmts:
        try:
            dt = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            if fmt == "%Y-%m-%d" and is_end:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"Invalid datetime '{value}'. Use YYYY-MM-DD or YYYY-MM-DD HH:MM"
    )


def parse_coins(value: str) -> list[str]:
    if value.strip().lower() == "all":
        return list(COINS)

    items = [c.strip().upper() for c in value.split(",") if c.strip()]
    if not items:
        raise argparse.ArgumentTypeError("--coins cannot be empty")

    invalid = [c for c in items if c not in COINS]
    if invalid:
        raise argparse.ArgumentTypeError(
            f"Unknown coin(s): {', '.join(invalid)}. Allowed: {', '.join(COINS)}"
        )
    return items


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch historical OHLCV data from Binance")
    parser.add_argument(
        "--start",
        required=True,
        help="UTC start datetime (YYYY-MM-DD or YYYY-MM-DD HH:MM)",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="UTC end datetime (YYYY-MM-DD or YYYY-MM-DD HH:MM)",
    )
    parser.add_argument(
        "--coins",
        default="all",
        help="Comma-separated coins (e.g., BTC,ETH,SOL) or 'all'",
    )
    parser.add_argument(
        "--prefix",
        default="",
        help="Output filename prefix. Default: range_<start>_<end>",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore existing CSV cache and refetch",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    target_start = parse_datetime_utc(args.start)
    target_end = parse_datetime_utc(args.end, is_end=True)
    if target_start >= target_end:
        parser.error("--start must be earlier than --end")

    selected_coins = parse_coins(args.coins)
    prefix = args.prefix.strip() or f"range_{target_start:%Y%m%d}_{target_end:%Y%m%d}"
    target_start_str = target_start.strftime("%Y-%m-%d %H:%M")

    print("=" * 70)
    print("  FETCH HISTORICAL RANGE DATA (CLI)")
    print(f"  Range (UTC): {target_start.strftime('%Y-%m-%d %H:%M')} -> {target_end.strftime('%Y-%m-%d %H:%M')}")
    print(f"  Coins: {', '.join(selected_coins)}")
    print(f"  Prefix: {prefix}")
    print(f"  Thư mục lưu: {DATA_DIR}")
    print("=" * 70)

    total_files = 0
    skipped_coins = set()

    print(
        f"\n⚡ BẮT ĐẦU CÀO RANGE: {target_start_str} -> {target_end.strftime('%Y-%m-%d %H:%M')}"
    )

    for coin in selected_coins:
        # Bỏ qua các coin đã xác định thiếu dữ liệu từ trước để tiết kiệm thời gian
        if coin in ["XAUT"]:
            skipped_coins.add(coin)
            continue

        print(f"  [{coin}]")
        coin_ok = True

        for interval, cfg in INTERVALS.items():
            warmup_days = cfg["warmup_days"]
            start_dt = target_start - timedelta(days=warmup_days)

            csv_path = os.path.join(DATA_DIR, f"{prefix}_{coin}_{interval}.csv")

            # Check cache
            if (not args.no_cache) and os.path.exists(csv_path) and os.path.getsize(csv_path) > 100:
                print(f"    {interval:>3}: cache — bỏ qua")
                total_files += 1
                continue

            # Fetch from Binance
            candles = fetch_candles(coin, interval, start_dt, target_end)

            if not candles:
                print(f"    {interval:>3}: [Không lấy được dữ liệu — bỏ qua {coin}]")
                coin_ok = False
                break

            # Đánh dấu nến warmup
            for c in candles:
                c["is_warmup"] = 1 if c["time"] < target_start_str else 0

            save_csv(prefix, coin, interval, candles)
            print_summary(interval, candles, target_start_str)
            total_files += 1

            time.sleep(0.05)

        if not coin_ok:
            skipped_coins.add(coin)

    print("\n" + "=" * 70)
    print(f"  Hoàn thành: {total_files} file CSV")
    print(f"  Bỏ qua hoặc lỗi các đồng coin: {', '.join(sorted(skipped_coins)) if skipped_coins else 'Không có'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
