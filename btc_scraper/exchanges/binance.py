import aiohttp
import asyncio
from datetime import datetime, timezone
from btc_scraper.core.config import INTERVAL, LIMIT

__all__ = ["fetch_ohlcv", "fetch_ohlcv_tf", "fetch_ohlcv_multi_tf", "get_ws_stream_names", "LIMIT", "MTF_INTERVALS"]

# Cấu hình số nến cho từng khung thời gian cao hơn
MTF_INTERVALS = {
    "1h":  50,   # 50 nến 1h (~2 ngày)
    "4h":  50,   # 50 nến 4h (~8 ngày)
    "1d":  30,   # 30 nến 1d (~1 tháng)
}

BASE_URL = "https://api.binance.com"


def _utc_candle_time(timestamp_ms: int | float) -> str:
    """Serialize a Binance millisecond epoch as an aware UTC timestamp."""
    return (
        datetime.fromtimestamp(float(timestamp_ms) / 1000, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


async def fetch_ohlcv(coin: str, session: aiohttp.ClientSession = None) -> list[dict]:
    """
    Lấy dữ liệu nến OHLCV từ Binance cho một coin cụ thể.
    Trả về danh sách dict với các trường: time, open, high, low, close, volume.
    """
    symbol = f"{coin}USDT"
    url = f"{BASE_URL}/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "limit": LIMIT,
    }
    
    async def _fetch(sess):
        async with sess.get(url, params=params, timeout=10) as resp:
            resp.raise_for_status()
            raw = await resp.json()
            candles = []
            for k in raw:
                candles.append({
                    "time":   datetime.fromtimestamp(k[0] / 1000).strftime("%Y-%m-%d %H:%M"),
                    "time_utc": _utc_candle_time(k[0]),
                    "open":   float(k[1]),
                    "high":   float(k[2]),
                    "low":    float(k[3]),
                    "close":  float(k[4]),
                    "volume": float(k[5]),
                })
            return candles

    try:
        if session is None:
            async with aiohttp.ClientSession() as sess:
                return await _fetch(sess)
        return await _fetch(session)
    except Exception as e:
        return [{"error": str(e)}]


async def fetch_ohlcv_tf(coin: str, interval: str, limit: int, session: aiohttp.ClientSession = None) -> list[dict]:
    """
    Lấy dữ liệu nến OHLCV từ Binance cho một coin và một khung thời gian cụ thể.
    """
    symbol = f"{coin}USDT"
    url = f"{BASE_URL}/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }
    
    async def _fetch(sess):
        async with sess.get(url, params=params, timeout=10) as resp:
            resp.raise_for_status()
            raw = await resp.json()
            candles = []
            for k in raw:
                candles.append({
                    "time":   datetime.fromtimestamp(k[0] / 1000).strftime("%Y-%m-%d %H:%M"),
                    "time_utc": _utc_candle_time(k[0]),
                    "open":   float(k[1]),
                    "high":   float(k[2]),
                    "low":    float(k[3]),
                    "close":  float(k[4]),
                    "volume": float(k[5]),
                })
            return candles

    try:
        if session is None:
            async with aiohttp.ClientSession() as sess:
                return await _fetch(sess)
        return await _fetch(session)
    except Exception as e:
        return [{"error": str(e)}]


async def fetch_ohlcv_multi_tf(coin: str, session: aiohttp.ClientSession = None) -> dict[str, list[dict]]:
    """
    Lấy dữ liệu nến OHLCV từ Binance cho nhiều khung thời gian: 1h, 4h, 1d song song.
    Trả về dict với key là interval, value là danh sách nến.
    """
    async def _fetch(sess):
        tasks = []
        for interval, limit in MTF_INTERVALS.items():
            tasks.append(fetch_ohlcv_tf(coin, interval, limit, sess))
        
        results = await asyncio.gather(*tasks)
        return dict(zip(MTF_INTERVALS.keys(), results))
        
    try:
        if session is None:
            async with aiohttp.ClientSession() as sess:
                return await _fetch(sess)
        return await _fetch(session)
    except Exception as e:
        # Trong trường hợp lỗi, trả về list chứa lỗi cho mỗi TF (như logic cũ)
        return {tf: [{"error": str(e)}] for tf in MTF_INTERVALS.keys()}


def get_ws_stream_names(coins: list[str], intervals: list[str] | None = None) -> list[str]:
    """
    Tạo danh sách tên stream cho Binance Combined WebSocket.

    Args:
        coins: Danh sách coin không có USDT — ví dụ ["BTC", "ETH"]
        intervals: Danh sách interval — mặc định ["15m", "1h", "4h", "1d"]

    Returns:
        ["btcusdt@kline_15m", "btcusdt@kline_1h", ..., "ethusdt@kline_15m", ...]
    """
    if intervals is None:
        intervals = ["15m", "1h", "4h", "1d"]
    return [
        f"{coin.lower()}usdt@kline_{interval}"
        for coin in coins
        for interval in intervals
    ]
