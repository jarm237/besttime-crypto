"""
Bybit Public API - Lấy dữ liệu nến OHLCV đa coin
Endpoint: GET /v5/market/kline
"""

import requests
from datetime import datetime
from btc_scraper.config import LIMIT

BASE_URL = "https://api.bybit.com"

# Bybit dùng số phút, không phải chuỗi như Binance
BYBIT_INTERVAL = "15"  # 15 phút


def fetch_ohlcv(coin: str) -> list[dict]:
    """
    Lấy dữ liệu nến OHLCV từ Bybit cho một coin cụ thể.
    Trả về danh sách dict với các trường: time, open, high, low, close, volume.
    """
    symbol = f"{coin}USDT"
    url = f"{BASE_URL}/v5/market/kline"
    params = {
        "category": "spot",
        "symbol": symbol,
        "interval": BYBIT_INTERVAL,
        "limit": LIMIT,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("retCode") != 0:
            return [{"error": data.get("retMsg", "Unknown error")}]
        raw = data["result"]["list"]
        candles = []
        for k in raw:
            # Bybit trả về theo thứ tự: [startTime, open, high, low, close, volume, turnover]
            candles.append({
                "time":   datetime.fromtimestamp(int(k[0]) / 1000).strftime("%Y-%m-%d %H:%M"),
                "open":   float(k[1]),
                "high":   float(k[2]),
                "low":    float(k[3]),
                "close":  float(k[4]),
                "volume": float(k[5]),
            })
        # Bybit trả về mới nhất trước, đảo ngược để theo thứ tự thời gian
        return list(reversed(candles))
    except Exception as e:
        return [{"error": str(e)}]
