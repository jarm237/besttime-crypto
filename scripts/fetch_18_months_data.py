"""
Script cào dữ liệu liên tục 18 tháng gần nhất.
Tối ưu hóa số lượng API calls (tải theo block 1000 nến, ít tốn tài nguyên hơn rất nhiều so với migrate từng lệnh trade rải rác).
"""

import sys, os, time, csv
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
import requests

# Thêm path để import từ core
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from btc_scraper.core.config import COINS, FRESH_TRAINING_DATA_DIR
from pathlib import Path

# Resolve DATA_DIR to fresh training data dir (create if missing)
base = Path(os.path.dirname(os.path.dirname(__file__)))
if FRESH_TRAINING_DATA_DIR.is_absolute():
    DATA_DIR = Path(FRESH_TRAINING_DATA_DIR)
else:
    DATA_DIR = base / FRESH_TRAINING_DATA_DIR
os.makedirs(DATA_DIR, exist_ok=True)

BINANCE_BASE = "https://api.binance.com"
CANDLES_PER_REQ = 1000

# Khung thời gian và khoảng thời gian warmup cần thiết cho đường SMA200
INTERVALS = {
    "15m": {"minutes": 15,   "warmup_days": 3},    
    "1h":  {"minutes": 60,   "warmup_days": 10},   
    "4h":  {"minutes": 240,  "warmup_days": 38},   
    "1d":  {"minutes": 1440, "warmup_days": 222},  
}

def get_last_18_months():
    """Tạo danh sách 18 tháng tính từ tháng hiện tại lùi về trước."""
    months = []
    # Lấy ngày mùng 1 của tháng hiện tại
    now = datetime.now(timezone.utc)
    current_month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    
    for i in range(18):
        start = current_month_start - relativedelta(months=i)
        end = start + relativedelta(months=1) - timedelta(seconds=1)
        months.append({
            "name": start.strftime("%Y_%m"),
            "start": start,
            "end": end
        })
    # Đảo ngược để tải từ quá khứ đến hiện tại
    return months[::-1]

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
            # Binance limits: 6000 weight per minute
            if resp.status_code == 429:
                print("    [Rate Limit] Sleeping 10s...")
                time.sleep(10)
                continue
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            print(f"    [Lỗi API] {coin}/{interval}: {e}")
            break

        if not raw:
            break

        for k in raw:
            all_candles.append({
                "time":      datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"),
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
        time.sleep(0.1) # Chống rate limit

    # Loại bỏ nến trùng lặp (nếu có)
    seen = set()
    unique = []
    for c in all_candles:
        if c["time"] not in seen:
            seen.add(c["time"])
            unique.append(c)
    unique.sort(key=lambda x: x["time"])
    return unique

def save_csv(month_name: str, coin: str, interval: str, candles: list[dict]):
    path = os.path.join(DATA_DIR, f"{month_name}_{coin}_{interval}.csv")
    if not candles:
        return
    fieldnames = list(candles[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(candles)

def main():
    months = get_last_18_months()
    print("=" * 70)
    print("  KÍCH HOẠT TẢI DỮ LIỆU LIÊN TỤC 18 THÁNG GẦN NHẤT")
    print(f"  Thời gian: {months[0]['start'].strftime('%Y-%m')} tới {months[-1]['start'].strftime('%Y-%m')}")
    print(f"  Thư mục: {DATA_DIR}")
    print("=" * 70)

    for month_cfg in months:
        month_name = month_cfg["name"]
        target_start = month_cfg["start"]
        target_end = month_cfg["end"]
        target_start_str = target_start.strftime("%Y-%m-%d %H:%M")

        print(f"\n⚡ ĐANG TẢI THÁNG: {month_name} ({target_start_str} -> {target_end.strftime('%Y-%m-%d %H:%M')})")

        for coin in COINS:
            # Bỏ qua các coin delist/chưa list
            if coin in ["NAORIS", "TSLAB", "XAUT"]:
                continue

            print(f"  [{coin}]", end=" ", flush=True)

            for interval, cfg in INTERVALS.items():
                warmup_days = cfg["warmup_days"]
                start_dt = target_start - timedelta(days=warmup_days)

                csv_path = os.path.join(DATA_DIR, f"{month_name}_{coin}_{interval}.csv")
                
                # Bỏ qua nếu đã tải rồi
                if os.path.exists(csv_path) and os.path.getsize(csv_path) > 100:
                    print(f"({interval}: cache)", end=" ", flush=True)
                    continue

                candles = fetch_candles(coin, interval, start_dt, target_end)

                if candles:
                    # Đánh dấu nến warmup
                    for c in candles:
                        c["is_warmup"] = 1 if c["time"] < target_start_str else 0
                    save_csv(month_name, coin, interval, candles)
                    print(f"({interval}: {len(candles)} nến)", end=" ", flush=True)
                else:
                    print(f"({interval}: lỗi)", end=" ", flush=True)

            print() # Xuống dòng cho coin tiếp theo

    print("\n[HOÀN TẤT] Dữ liệu 18 tháng đã được tải về.")

if __name__ == "__main__":
    main()
