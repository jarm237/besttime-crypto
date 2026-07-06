"""
Fetch May 2026 Data — Tất cả khung thời gian mà chiến lược sử dụng
=====================================================================
Cào dữ liệu tháng 5/2026 cho tất cả COINS, trên 4 khung nến:
  - 15m : tín hiệu chính (analyze_market)
  - 1h  : MTF confirmation
  - 4h  : MTF confirmation
  - 1d  : MTF confirmation (SMA200 trend)

Mỗi khung cào thêm "warmup" đủ để tính SMA200 chính xác:
  - 15m : +3 ngày warmup (220 × 15min ≈ 55h)
  - 1h  : +10 ngày warmup (220 × 1h ≈ 9.2 ngày)
  - 4h  : +38 ngày warmup (220 × 4h ≈ 36.7 ngày)
  - 1d  : +220 ngày warmup (SMA200 cần 200 nến 1d)

Output:
  data/may_<COIN>_15m.csv
  data/may_<COIN>_1h.csv
  data/may_<COIN>_4h.csv
  data/may_<COIN>_1d.csv

Cách chạy:
  python fetch_may_data.py
"""

import sys, os, time, csv, requests
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from btc_scraper.core.config import COINS

# ─── Config ──────────────────────────────────────────────────────────────────
TARGET_MONTH_START = datetime(2026, 5, 1,  0, 0, 0, tzinfo=timezone.utc)
TARGET_MONTH_END   = datetime(2026, 5, 31, 23, 59, 59, tzinfo=timezone.utc)

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
# ─────────────────────────────────────────────────────────────────────────────


def fetch_candles(coin: str, interval: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
    """
    Cào nến OHLCV từ Binance trong khoảng [start_dt, end_dt] với pagination.
    """
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
                "is_warmup": 0,   # Sẽ đánh dấu sau
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

    # Đánh dấu warmup candles (những nến trước ngày 1/5)
    may_start_str = TARGET_MONTH_START.strftime("%Y-%m-%d %H:%M")
    for c in unique:
        c["is_warmup"] = 1 if c["time"] < may_start_str else 0

    return unique


def save_csv(coin: str, interval: str, candles: list[dict]) -> str:
    path = os.path.join(DATA_DIR, f"may_{coin}_{interval}.csv")
    if not candles:
        return path
    fieldnames = list(candles[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(candles)
    return path


def print_summary(coin: str, interval: str, candles: list[dict]):
    warmup = sum(1 for c in candles if c["is_warmup"])
    actual = len(candles) - warmup
    if candles:
        first = candles[0]["time"]
        last  = candles[-1]["time"]
        print(f"    {interval:>3}: {len(candles):>5} nến "
              f"(warmup={warmup}, may={actual}) "
              f"| {first} → {last}")
    else:
        print(f"    {interval:>3}: [Không có dữ liệu]")


def main():
    print("=" * 62)
    print("  FETCH MAY 2026 DATA — Tất cả khung thời gian chiến lược")
    print(f"  Coins: {', '.join(COINS)}")
    print(f"  Tháng mục tiêu: {TARGET_MONTH_START.strftime('%Y-%m-%d')} → "
          f"{TARGET_MONTH_END.strftime('%Y-%m-%d')}")
    print(f"  Khung: {', '.join(INTERVALS.keys())} | Warmup SMA200: bật")
    print("=" * 62)

    total_files  = 0
    skipped_coins = []

    for coin in COINS:
        print(f"\n[{coin}]")
        coin_ok = True

        for interval, cfg in INTERVALS.items():
            warmup_days  = cfg["warmup_days"]
            start_dt     = TARGET_MONTH_START - timedelta(days=warmup_days)

            # Kiểm tra cache
            csv_path = os.path.join(DATA_DIR, f"may_{coin}_{interval}.csv")
            if os.path.exists(csv_path):
                age_h = (time.time() - os.path.getmtime(csv_path)) / 3600
                if age_h < 24:
                    candles = []
                    with open(csv_path, "r", encoding="utf-8") as f:
                        for row in csv.DictReader(f):
                            candles.append(row)
                    print(f"    {interval:>3}: cache ({age_h:.1f}h) — {len(candles)} nến")
                    total_files += 1
                    continue

            # Cào từ Binance
            candles = fetch_candles(coin, interval, start_dt, TARGET_MONTH_END)

            if not candles:
                print(f"    {interval:>3}: [Không lấy được dữ liệu — bỏ qua {coin}]")
                coin_ok = False
                break

            save_csv(coin, interval, candles)
            print_summary(coin, interval, candles)
            total_files += 1

            time.sleep(0.05)  # Nhẹ nhàng giữa intervals

        if not coin_ok:
            skipped_coins.append(coin)

    print("\n" + "=" * 62)
    print(f"  Hoàn thành: {total_files} file CSV")
    print(f"  Thư mục   : {DATA_DIR}")
    if skipped_coins:
        print(f"  Bỏ qua    : {', '.join(skipped_coins)}")
    print("=" * 62)


if __name__ == "__main__":
    main()
