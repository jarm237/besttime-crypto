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

import os
import socket

class SyncResolver(aiohttp.ThreadedResolver):
    """Custom resolver alias for ThreadedResolver.
    Fixes Windows Python async DNS resolution failures ([Could not contact DNS servers])
    when aiodns/pycares is installed.
    """
    pass


def create_robust_client_session(**kwargs) -> aiohttp.ClientSession:
    """Tạo aiohttp ClientSession với ThreadedResolver chống lỗi DNS trên Windows."""
    if "connector" not in kwargs:
        connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver(), family=socket.AF_INET)
        kwargs["connector"] = connector
    return aiohttp.ClientSession(**kwargs)


BASE_URL = os.getenv("BINANCE_BASE_URL", "https://api.binance.com").rstrip("/")
_ALT_DOMAINS = [
    BASE_URL,
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
    "https://api.binance.gapi.tech",
]
_seen_domains = set()
BINANCE_DOMAINS = [d for d in _ALT_DOMAINS if not (d in _seen_domains or _seen_domains.add(d))]


def _utc_candle_time(timestamp_ms: int | float) -> str:
    """Serialize a Binance millisecond epoch as an aware UTC timestamp."""
    return (
        datetime.fromtimestamp(float(timestamp_ms) / 1000, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


BYBIT_TF_MAP = {
    "15m": "15",
    "1h": "60",
    "4h": "240",
    "1d": "D",
}

OKX_TF_MAP = {
    "15m": "15m",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
}


INTERVAL_MS_MAP = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


async def _fetch_from_bybit(symbol: str, interval: str, limit: int, sess: aiohttp.ClientSession) -> list[dict]:
    url = "https://api.bybit.com/v5/market/kline"
    params = {
        "category": "spot",
        "symbol": symbol,
        "interval": BYBIT_TF_MAP.get(interval, "15"),
        "limit": limit,
    }
    async with sess.get(url, params=params, timeout=8) as resp:
        resp.raise_for_status()
        data = await resp.json()
        if data.get("retCode") == 0 and data.get("result", {}).get("list"):
            raw = data["result"]["list"]
            import time
            now_ms = time.time() * 1000
            interval_ms = INTERVAL_MS_MAP.get(interval, 900_000)
            candles = []
            for k in raw:
                ts = int(k[0])
                close_ts = ts + interval_ms - 1
                is_closed = bool(close_ts <= now_ms)
                candles.append({
                    "time": datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M"),
                    "time_utc": _utc_candle_time(ts),
                    "open_time_utc": _utc_candle_time(ts),
                    "close_time_utc": _utc_candle_time(close_ts),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "closed": is_closed,
                    "is_closed": is_closed,
                })
            return list(reversed(candles))
    raise RuntimeError("Bybit kline data empty or error")


async def _fetch_from_okx(coin: str, interval: str, limit: int, sess: aiohttp.ClientSession) -> list[dict]:
    symbol = f"{coin}-USDT"
    url = "https://www.okx.com/api/v5/market/candles"
    params = {
        "instId": symbol,
        "bar": OKX_TF_MAP.get(interval, "15m"),
        "limit": limit,
    }
    async with sess.get(url, params=params, timeout=8) as resp:
        resp.raise_for_status()
        data = await resp.json()
        if data.get("code") == "0" and data.get("data"):
            raw = data["data"]
            import time
            now_ms = time.time() * 1000
            interval_ms = INTERVAL_MS_MAP.get(interval, 900_000)
            candles = []
            for k in raw:
                ts = int(k[0])
                close_ts = ts + interval_ms - 1
                is_closed = bool(close_ts <= now_ms)
                candles.append({
                    "time": datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d %H:%M"),
                    "time_utc": _utc_candle_time(ts),
                    "open_time_utc": _utc_candle_time(ts),
                    "close_time_utc": _utc_candle_time(close_ts),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "closed": is_closed,
                    "is_closed": is_closed,
                })
            return list(reversed(candles))
    raise RuntimeError("OKX kline data empty or error")


async def _fetch_from_domains(symbol: str, interval: str, limit: int, sess: aiohttp.ClientSession) -> list[dict]:
    """Thử lấy klines từ lần lượt các Binance domain, nếu lỗi DNS/mạng chuyển sang Bybit & OKX fallback."""
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }
    last_err = None
    for domain in BINANCE_DOMAINS:
        url = f"{domain}/api/v3/klines"
        try:
            async with sess.get(url, params=params, timeout=5) as resp:
                resp.raise_for_status()
                raw = await resp.json()
                import time
                now_ms = time.time() * 1000
                candles = []
                for k in raw:
                    close_ms = k[6] if len(k) > 6 else k[0]
                    is_closed = bool(close_ms <= now_ms)
                    candles.append({
                        "time":   datetime.fromtimestamp(k[0] / 1000).strftime("%Y-%m-%d %H:%M"),
                        "time_utc": _utc_candle_time(k[0]),
                        "open_time_utc": _utc_candle_time(k[0]),
                        "close_time_utc": _utc_candle_time(k[6]) if len(k) > 6 else None,
                        "open":   float(k[1]),
                        "high":   float(k[2]),
                        "low":    float(k[3]),
                        "close":  float(k[4]),
                        "volume": float(k[5]),
                        "closed": is_closed,
                        "is_closed": is_closed,
                    })
                return candles
        except Exception as e:
            last_err = e
            continue

    # Fallback sang Bybit
    try:
        return await _fetch_from_bybit(symbol, interval, limit, sess)
    except Exception as bybit_exc:
        last_err = bybit_exc

    # Fallback sang OKX
    coin_name = symbol.replace("USDT", "")
    try:
        return await _fetch_from_okx(coin_name, interval, limit, sess)
    except Exception as okx_exc:
        last_err = okx_exc

    raise last_err or RuntimeError("All exchange REST endpoints unreachable")


async def fetch_ohlcv(coin: str, session: aiohttp.ClientSession = None) -> list[dict]:
    """
    Lấy dữ liệu nến OHLCV từ Binance cho một coin cụ thể.
    Trả về danh sách dict với các trường: time, open, high, low, close, volume.
    """
    symbol = f"{coin}USDT"
    try:
        if session is None:
            async with create_robust_client_session() as sess:
                return await _fetch_from_domains(symbol, INTERVAL, LIMIT, sess)
        return await _fetch_from_domains(symbol, INTERVAL, LIMIT, session)
    except Exception as e:
        return [{"error": str(e)}]


async def fetch_ohlcv_tf(coin: str, interval: str, limit: int, session: aiohttp.ClientSession = None) -> list[dict]:
    """
    Lấy dữ liệu nến OHLCV từ Binance cho một coin và một khung thời gian cụ thể.
    """
    symbol = f"{coin}USDT"
    try:
        if session is None:
            async with create_robust_client_session() as sess:
                return await _fetch_from_domains(symbol, interval, limit, sess)
        return await _fetch_from_domains(symbol, interval, limit, session)
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
            async with create_robust_client_session() as sess:
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
