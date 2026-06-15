import asyncio
import aiohttp
import json
import os
import time
from datetime import datetime, timedelta
import sys

# Ensure btc_scraper is in PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from btc_scraper.analysis.core import analyze_market
from btc_scraper.ml_engine.feature_extractor import build_meta_features_v2

BASE_URL = "https://api.binance.com"
LIMIT = 200

async def fetch_ohlcv_end_time(coin: str, end_time_ms: int, session: aiohttp.ClientSession) -> list[dict]:
    symbol = f"{coin}USDT"
    url = f"{BASE_URL}/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": "15m",
        "limit": LIMIT,
        "endTime": end_time_ms
    }
    
    # Thêm retry delay để chống rate limit
    for attempt in range(3):
        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status == 429:
                    print(f"Rate limited for {symbol}, sleeping...")
                    await asyncio.sleep(5)
                    continue
                resp.raise_for_status()
                raw = await resp.json()
                candles = []
                for k in raw:
                    candles.append({
                        "time":   datetime.fromtimestamp(k[0] / 1000).strftime("%Y-%m-%d %H:%M"),
                        "open":   float(k[1]),
                        "high":   float(k[2]),
                        "low":    float(k[3]),
                        "close":  float(k[4]),
                        "volume": float(k[5]),
                    })
                return candles
        except Exception as e:
            if attempt == 2:
                print(f"Failed to fetch {symbol}: {e}")
                return [{"error": str(e)}]
            await asyncio.sleep(2)
    return []

async def process_record(record, session, semaphore, progress):
    async with semaphore:
        coin = record.get("coin")
        exit_time_str = record.get("exit_time")
        hold_hours = float(record.get("hold_hours", 0))
        
        # Thêm 200ms delay giữa mỗi request để đảm bảo an toàn cho Binance API rate limit
        await asyncio.sleep(0.2)
        
        if not coin or not exit_time_str:
            progress["failed"] += 1
            return None
            
        try:
            exit_time = datetime.strptime(exit_time_str, "%Y-%m-%d %H:%M")
            entry_time = exit_time - timedelta(hours=hold_hours)
            end_time_ms = int(entry_time.timestamp() * 1000)
            
            candles = await fetch_ohlcv_end_time(coin, end_time_ms, session)
            
            if not candles or "error" in candles[0] or len(candles) < 50:
                print(f"[!] Lỗi fetch nến cho {coin} tại {entry_time}")
                progress["failed"] += 1
                return None
                
            # Phân tích nến bằng Pandas Engine mới nhất
            analysis = analyze_market(candles)
            analysis["close"] = candles[-1]["close"]
            
            # Trích xuất 40+ Features (V2 Schema)
            new_features = build_meta_features_v2(analysis)
            
            # Merge vào record cũ
            enriched_record = record.copy()
            enriched_record.update(new_features)
            
            progress["success"] += 1
            if (progress["success"] + progress["failed"]) % 50 == 0:
                print(f"Tiến độ: {progress['success'] + progress['failed']} / {progress['total']}")
                
            return enriched_record
        except Exception as e:
            print(f"Lỗi khi xử lý {coin}: {e}")
            progress["failed"] += 1
            return None

async def main():
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    input_file = os.path.join(logs_dir, "adaptive_signals.json")
    output_file = os.path.join(logs_dir, "adaptive_signals_v2.json")
    
    if not os.path.exists(input_file):
        print(f"File not found: {input_file}")
        return
        
    with open(input_file, "r", encoding="utf-8") as f:
        records = json.load(f)
        
    print(f"Đã tải {len(records)} lệnh cũ từ {input_file}")
    
    # Chỉ chạy 5 requests đồng thời để an toàn
    semaphore = asyncio.Semaphore(5)
    enriched_records = []
    
    progress = {"total": len(records), "success": 0, "failed": 0}
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for record in records:
            tasks.append(process_record(record, session, semaphore, progress))
            
        print("Bắt đầu migration & cào dữ liệu từ Binance. Vui lòng đợi...")
        
        results = await asyncio.gather(*tasks)
        
        for res in results:
            if res is not None:
                enriched_records.append(res)
                
    print(f"\nThành công: {len(enriched_records)}/{len(records)} records.")
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(enriched_records, f, indent=2, ensure_ascii=False)
        
    print(f"Đã lưu dataset mới vào {output_file}")

if __name__ == "__main__":
    asyncio.run(main())
