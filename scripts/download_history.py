import os
import sys
import time
import csv
import requests
from datetime import datetime

# Đảm bảo đường dẫn import hoạt động
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from btc_scraper.config import COINS

BASE_URL = "https://api.binance.com"

def download_coin_history(coin: str, interval: str = "15m", days: int = 365):
    symbol = f"{coin}USDT"
    print(f"\n[Scraper] Bắt đầu tải dữ liệu lịch sử cho {symbol} ({interval}, {days} ngày)...")
    
    # Tính toán start time
    end_time_ms = int(time.time() * 1000)
    start_time_ms = end_time_ms - (days * 24 * 3600 * 1000)
    
    csv_dir = "data"
    os.makedirs(csv_dir, exist_ok=True)
    csv_path = os.path.join(csv_dir, f"{coin}_{interval}.csv")
    
    # Mở file CSV để viết
    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "open", "high", "low", "close", "volume"])
        
        current_start = start_time_ms
        candles_downloaded = 0
        
        while current_start < end_time_ms:
            url = f"{BASE_URL}/api/v3/klines"
            params = {
                "symbol": symbol,
                "interval": interval,
                "limit": 1000,
                "startTime": current_start
            }
            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                raw = resp.json()
            except Exception as e:
                print(f"Lỗi khi gọi API: {e}. Thử lại sau 5s...")
                time.sleep(5)
                continue
                
            if not raw:
                break
                
            for k in raw:
                # k[0] = open time, k[1]=open, k[2]=high, k[3]=low, k[4]=close, k[5]=volume
                # Chỉ lấy đến thời điểm hiện tại
                open_time = k[0]
                if open_time >= end_time_ms:
                    break
                
                formatted_time = datetime.fromtimestamp(open_time / 1000).strftime("%Y-%m-%d %H:%M")
                writer.writerow([
                    formatted_time,
                    float(k[1]), # open
                    float(k[2]), # high
                    float(k[3]), # low
                    float(k[4]), # close
                    float(k[5]), # volume
                ])
                candles_downloaded += 1
            
            # Cập nhật start time cho vòng lặp tiếp theo = open time của nến cuối cùng + 1ms
            last_open_time = raw[-1][0]
            if last_open_time <= current_start:
                break # Đề phòng lặp vô hạn
            current_start = last_open_time + 1
            
            print(f"  Downloaded: {candles_downloaded} candles...")
            time.sleep(0.1) # Tránh rate limit
            
    print(f"✅ Hoàn thành! Đã lưu {candles_downloaded} nến vào {csv_path}")

if __name__ == "__main__":
    # Tải dữ liệu cho 3 coin chính đại diện: BTC, ETH, SOL
    target_coins = ["BTC", "ETH", "SOL"]
    for coin in target_coins:
        download_coin_history(coin, interval="15m", days=365)
