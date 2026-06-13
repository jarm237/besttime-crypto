"""
Fetch Historical Range Data (June 2025 - December 2025)
======================================================
Cào dữ liệu lịch sử cho các tháng từ tháng 6 đến tháng 12 năm 2025.
Dành cho tất cả COINS và 4 khung nến (15m, 1h, 4h, 1d), kèm warmup SMA200.

Output:
  data/<tên_tháng>_2025_<COIN>_<khung>.csv

Cách chạy:
  python fetch_historical_range.py
"""

import sys, os, time, csv, requests
from datetime import datetime, timedelta, timezone

# Force stdout to UTF-8 to support Vietnamese characters in console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(__file__))
from btc_scraper.config import COINS

# Định nghĩa danh sách các tháng cần cào dữ liệu
MONTHS = [
    {
        "name": "june_2025",
        "start": datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
        "end": datetime(2025, 6, 30, 23, 59, 59, tzinfo=timezone.utc),
    },
    {
        "name": "july_2025",
        "start": datetime(2025, 7, 1, 0, 0, 0, tzinfo=timezone.utc),
        "end": datetime(2025, 7, 31, 23, 59, 59, tzinfo=timezone.utc),
    },
    {
        "name": "august_2025",
        "start": datetime(2025, 8, 1, 0, 0, 0, tzinfo=timezone.utc),
        "end": datetime(2025, 8, 31, 23, 59, 59, tzinfo=timezone.utc),
    },
    {
        "name": "september_2025",
        "start": datetime(2025, 9, 1, 0, 0, 0, tzinfo=timezone.utc),
        "end": datetime(2025, 9, 30, 23, 59, 59, tzinfo=timezone.utc),
    },
    {
        "name": "october_2025",
        "start": datetime(2025, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
        "end": datetime(2025, 10, 31, 23, 59, 59, tzinfo=timezone.utc),
    },
    {
        "name": "november_2025",
        "start": datetime(2025, 11, 1, 0, 0, 0, tzinfo=timezone.utc),
        "end": datetime(2025, 11, 30, 23, 59, 59, tzinfo=timezone.utc),
    },
    {
        "name": "december_2025",
        "start": datetime(2025, 12, 1, 0, 0, 0, tzinfo=timezone.utc),
        "end": datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
    },
]

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

    # Đánh dấu warmup candles (những nến trước đầu tháng mục tiêu)
    month_start_str = start_dt.strftime("%Y-%m-%d %H:%M") # Thử lấy mốc target month
    # Nhưng ta sẽ lấy chính xác thời điểm target month thực sự để gán warmup
    return unique


def save_csv(month_name: str, coin: str, interval: str, candles: list[dict]) -> str:
    path = os.path.join(DATA_DIR, f"{month_name}_{coin}_{interval}.csv")
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


def main():
    print("=" * 70)
    print("  FETCH HISTORICAL RANGE DATA (June 2025 - December 2025)")
    print(f"  Coins: {', '.join(COINS)}")
    print(f"  Thư mục lưu: {DATA_DIR}")
    print("=" * 70)

    total_files = 0
    skipped_coins = set()

    for month_cfg in MONTHS:
        month_name = month_cfg["name"]
        target_start = month_cfg["start"]
        target_end = month_cfg["end"]
        target_start_str = target_start.strftime("%Y-%m-%d %H:%M")

        print(f"\n⚡ BẮT ĐẦU CÀO THÁNG: {month_name.upper()} ({target_start_str} -> {target_end.strftime('%Y-%m-%d %H:%M')})")

        for coin in COINS:
            # Bỏ qua các coin đã xác định thiếu dữ liệu từ trước để tiết kiệm thời gian
            if coin in ["NAORIS", "TSLAB", "XAUT"]:
                skipped_coins.add(coin)
                continue

            print(f"  [{coin}]")
            coin_ok = True

            for interval, cfg in INTERVALS.items():
                warmup_days = cfg["warmup_days"]
                start_dt = target_start - timedelta(days=warmup_days)

                csv_path = os.path.join(DATA_DIR, f"{month_name}_{coin}_{interval}.csv")
                
                # Check cache
                if os.path.exists(csv_path) and os.path.getsize(csv_path) > 100:
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

                save_csv(month_name, coin, interval, candles)
                print_summary(interval, candles, target_start_str)
                total_files += 1

                time.sleep(0.05)

            if not coin_ok:
                skipped_coins.add(coin)

    print("\n" + "=" * 70)
    print(f"  Hoàn thành: {total_files} file CSV")
    print(f"  Bỏ qua hoặc lỗi các đồng coin: {', '.join(skipped_coins)}")
    print("=" * 70)


if __name__ == "__main__":
    main()
