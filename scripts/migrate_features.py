import json
import os
import csv
from datetime import datetime, timedelta
import sys
from pathlib import Path

# Ensure btc_scraper is in PYTHONPATH
BASE_DIR = Path(__file__).parent.parent
sys.path.append(str(BASE_DIR))

from btc_scraper.analysis.core import analyze_market
from btc_scraper.ml_engine.feature_extractor import build_meta_features_v2
from btc_scraper.core.config import COINS

DATA_DIR = BASE_DIR / "data" / "historical_18m"

def get_available_months() -> list[str]:
    months = set()
    if DATA_DIR.exists():
        for f in DATA_DIR.glob("*_15m.csv"):
            parts = f.name.split("_")
            if len(parts) >= 3:
                months.add(f"{parts[0]}_{parts[1]}")
    return sorted(list(months))

def load_candles_raw(coin: str, interval: str, month: str) -> list[dict]:
    path = DATA_DIR / f"{month}_{coin}_{interval}.csv"
    if not path.exists():
        return []
    candles = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = datetime.strptime(row["time"], "%Y-%m-%d %H:%M")
            candles.append({
                "time": row["time"],
                "time_dt": dt,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"])
            })
    return candles

def load_all_candles(coin: str, months: list[str]) -> list[dict]:
    combined = []
    for m in months:
        combined.extend(load_candles_raw(coin, "15m", m))
    seen = set()
    dedup = []
    for c in combined:
        if c["time"] not in seen:
            seen.add(c["time"])
            dedup.append(c)
    dedup.sort(key=lambda x: x["time_dt"])
    return dedup

def main():
    logs_dir = BASE_DIR / "logs"
    input_file = logs_dir / "adaptive_signals.json"
    output_file = logs_dir / "adaptive_signals_v2.json"

    if not input_file.exists():
        print(f"File not found: {input_file}")
        return

    with open(input_file, "r", encoding="utf-8") as f:
        records = json.load(f)

    print(f"Đã tải {len(records)} lệnh cũ từ {input_file}")
    
    months = get_available_months()
    print(f"Sử dụng dữ liệu local từ {len(months)} tháng trong thư mục data/historical_18m.")

    # Tải dữ liệu vào memory
    print("Đang tải dữ liệu nến 15m vào bộ nhớ...")
    candles_by_coin = {}
    for coin in COINS:
        cands = load_all_candles(coin, months)
        if cands:
            candles_by_coin[coin] = cands
    
    print("Đã tải xong dữ liệu nến. Bắt đầu xử lý migration local...")

    enriched_records = []
    success = 0
    failed = 0

    for idx, record in enumerate(records):
        coin = record.get("coin")
        exit_time_str = record.get("exit_time")
        hold_hours = float(record.get("hold_hours", 0))

        if not coin or not exit_time_str or coin not in candles_by_coin:
            failed += 1
            continue

        try:
            exit_time = datetime.strptime(exit_time_str, "%Y-%m-%d %H:%M")
            entry_time = exit_time - timedelta(hours=hold_hours)
            
            coin_candles = candles_by_coin[coin]
            
            # Lấy 200 nến tính đến entry_time (bao gồm cả entry_time)
            # Tối ưu: Tìm index của entry_time thay vì list comprehension qua toàn bộ list (rất chậm với 50k nến)
            # Binary search:
            import bisect
            # Tạo list datetime để search
            dates = [c["time_dt"] for c in coin_candles]
            idx_cutoff = bisect.bisect_right(dates, entry_time)
            
            cutoff_candles = coin_candles[:idx_cutoff]
            
            if len(cutoff_candles) < 50:
                failed += 1
                continue
                
            candles = cutoff_candles[-200:]
            
            analysis = analyze_market(candles)
            analysis["close"] = candles[-1]["close"]
            
            new_features = build_meta_features_v2(analysis)
            
            enriched = record.copy()
            enriched.update(new_features)
            enriched_records.append(enriched)
            success += 1
        except Exception as e:
            failed += 1

        if (idx + 1) % 10 == 0:
            print(f"Tiến độ: {idx + 1} / {len(records)} (Thành công: {success}, Lỗi: {failed})")

    print(f"\nThành công: {success}/{len(records)} records. Lỗi/Thiếu dữ liệu: {failed}")
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(enriched_records, f, indent=2, ensure_ascii=False)
        
    print(f"Đã lưu dataset mới vào {output_file}")

if __name__ == "__main__":
    main()
