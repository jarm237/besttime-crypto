"""
OKX Public API - Lấy dữ liệu nến OHLCV đa coin
Endpoint: GET /api/v5/market/candles
"""

import requests
from datetime import datetime
from btc_scraper.core.config import LIMIT

BASE_URL = "https://www.okx.com"

OKX_INTERVAL = "15m"


def fetch_ohlcv(coin: str) -> list[dict]:
    """
    Lấy dữ liệu nến OHLCV từ OKX cho một coin cụ thể.
    Trả về danh sách dict với các trường: time, open, high, low, close, volume.
    """
    # OKX dùng định dạng COIN-USDT ví dụ BTC-USDT
    symbol = f"{coin}-USDT"
    url = f"{BASE_URL}/api/v5/market/candles"
    params = {
        "instId": symbol,
        "bar": OKX_INTERVAL,
        "limit": LIMIT,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != "0":
            return [{"error": data.get("msg", "Unknown error")}]
        raw = data["data"]
        candles = []
        for k in raw:
            # OKX: [ts, open, high, low, close, vol, volCcy, volCcyQuote, confirm]
            candles.append({
                "time":   datetime.fromtimestamp(int(k[0]) / 1000).strftime("%Y-%m-%d %H:%M"),
                "open":   float(k[1]),
                "high":   float(k[2]),
                "low":    float(k[3]),
                "close":  float(k[4]),
                "volume": float(k[5]),
            })
        # OKX trả về mới nhất trước, đảo ngược
        return list(reversed(candles))
    except Exception as e:
        return [{"error": str(e)}]
