"""
Binance WebSocket Manager — Real-time OHLCV kline stream.

Thay thế REST polling bằng Binance Combined Stream WebSocket.
Endpoint: wss://stream.binance.com:9443/stream?streams=...

Hỗ trợ:
  - Combined stream (tất cả coins trong 1 connection)
  - Bootstrap từ REST để load 210 nến lịch sử khi khởi động
  - Auto-reconnect với exponential backoff
  - MTF (15m, 1h, 4h, 1d)
  - Callback khi nến đóng cửa (on_candle_close)
"""

import json
import time
import threading
import logging
from typing import Callable, Optional

from btc_scraper.core.candle_store import candle_store as _default_store
from btc_scraper.exchanges.binance import (
    fetch_ohlcv,
    fetch_ohlcv_tf,
    MTF_INTERVALS,
    LIMIT,
    _utc_candle_time,
    create_robust_client_session,
)
import aiohttp

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

WS_BASE_URL = "wss://stream.binance.com:9443/stream"
WS_INTERVALS = ["15m", "1h", "4h", "1d"]
MTF_LIMIT_MAP = {
    "15m": LIMIT,   # 210
    "1h":  50,
    "4h":  50,
    "1d":  30,
}
RECONNECT_BASE = 10    # giây, initial backoff
RECONNECT_MAX  = 120   # giây, max backoff


def _parse_kline_event(msg: dict) -> Optional[dict]:
    """
    Parse Binance kline stream event thành candle dict.
    Returns None nếu không phải kline event.
    """
    data = msg.get("data", msg)
    if data.get("e") != "kline":
        return None

    k = data["k"]
    is_closed = bool(k["x"])
    return {
        "coin":     data["s"].replace("USDT", ""),  # "BTCUSDT" → "BTC"
        "interval": k["i"],
        "is_closed": is_closed,
        "candle": {
            "time":   time.strftime(
                "%Y-%m-%d %H:%M",
                time.localtime(k["t"] / 1000),
            ),
            "time_utc": _utc_candle_time(k["t"]),
            "open_time_utc": _utc_candle_time(k["t"]),
            "close_time_utc": _utc_candle_time(k["T"]) if "T" in k else None,
            "open":   float(k["o"]),
            "high":   float(k["h"]),
            "low":    float(k["l"]),
            "close":  float(k["c"]),
            "volume": float(k["v"]),
            "closed": is_closed,
            "is_closed": is_closed,
        },
    }


class BinanceWebSocketManager:
    """
    Quản lý WebSocket connection tới Binance Combined Stream.

    Workflow:
        1. bootstrap_rest() — load 210 nến lịch sử qua REST
        2. connect()        — kết nối WS, bắt đầu nhận realtime
        3. on_candle_close  — callback được gọi mỗi khi nến đóng

    Fallback:
        Khi WS bị ngắt, auto-reconnect. Caller có thể gọi
        `check_health()` từ scheduler để trigger REST fallback
        nếu WS không kết nối lại được trong `health_timeout` giây.
    """

    def __init__(
        self,
        coins: list[str],
        on_candle_close: Optional[Callable[[str, str], None]] = None,
        store=None,
        intervals: Optional[list[str]] = None,
        health_timeout: int = 120,
    ):
        """
        Args:
            coins: Danh sách coin (không có USDT) — ví dụ ["BTC", "ETH"]
            on_candle_close: Callback(coin, interval) khi nến đóng
            store: CandleStore instance (mặc định: singleton)
            intervals: Danh sách interval subscribe (mặc định: WS_INTERVALS)
            health_timeout: Giây không nhận được message trước khi coi là unhealthy
        """
        self.coins = [c.upper() for c in coins]
        self.on_candle_close = on_candle_close
        self.store = store or _default_store
        self.intervals = intervals or WS_INTERVALS
        self.health_timeout = health_timeout

        self._ws = None
        self._ws_thread: Optional[threading.Thread] = None
        self._running = False
        self._reconnect_count = 0
        self._last_message_time: float = 0.0
        self._bootstrapped = False

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    async def bootstrap_rest(self) -> None:
        """
        Load lịch sử OHLCV qua REST API trước khi WS kết nối (song song).
        Đảm bảo CandleStore có đủ 210 nến để tính SMA200.
        """
        import asyncio
        import aiohttp
        
        print(f"  [WS] Bootstrap REST: {len(self.coins)} coins × {len(self.intervals)} intervals...", flush=True)
        
        async def fetch_for_coin_interval(coin, interval, session):
            limit = MTF_LIMIT_MAP.get(interval, 50)
            try:
                if interval == "15m":
                    c_limit = self.store.get_capacity(coin, "15m") if hasattr(self.store, "get_capacity") else None
                    candles = await fetch_ohlcv(coin, session, limit=c_limit)
                else:
                    candles = await fetch_ohlcv_tf(coin, interval, limit, session)

                if candles and "error" not in candles[0]:
                    self.store.seed(coin, interval, candles)
                    print(f"    ✓ {coin}/{interval}: {len(candles)} nến loaded", flush=True)
                else:
                    err = candles[0].get("error", "unknown") if candles else "no data"
                    print(f"    ✗ {coin}/{interval}: REST error — {err}", flush=True)
            except Exception as e:
                print(f"    ✗ {coin}/{interval}: Exception — {e}", flush=True)

        async with create_robust_client_session() as session:
            tasks = []
            for coin in self.coins:
                for interval in self.intervals:
                    tasks.append(fetch_for_coin_interval(coin, interval, session))
            await asyncio.gather(*tasks)

        self._bootstrapped = True
        print("  [WS] Bootstrap hoàn tất.\n", flush=True)

    # ── Stream management ─────────────────────────────────────────────────────

    def _build_stream_url(self) -> str:
        """Tạo Combined Stream URL cho tất cả coins × intervals."""
        streams = [
            f"{coin.lower()}usdt@kline_{interval}"
            for coin in self.coins
            for interval in self.intervals
        ]
        return f"{WS_BASE_URL}?streams=" + "/".join(streams)

    def connect(self) -> None:
        """
        Kết nối WebSocket và chạy trong background thread.
        Gọi hàm này sau bootstrap_rest().
        """
        if not self._bootstrapped:
            self.bootstrap_rest()
        self._running = True
        self._ws_thread = threading.Thread(
            target=self._run_forever,
            name="binance-ws",
            daemon=True,
        )
        self._ws_thread.start()
        print(f"  [WS] Connected thread started ({len(self.coins)} coins × {len(self.intervals)} intervals)", flush=True)

    def disconnect(self) -> None:
        """Dừng WebSocket gracefully."""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    # ── Internal WS loop ─────────────────────────────────────────────────────

    def _run_forever(self) -> None:
        """
        Vòng lặp reconnect: khi WS đóng, tự động kết nối lại.
        Exponential backoff: 10s → 20s → 40s → ... → 120s.
        """
        while self._running:
            try:
                self._reconnect_count += 1
                url = self._build_stream_url()
                print(f"  [WS] Connecting (attempt #{self._reconnect_count})...", flush=True)
                self._run_websocket(url)
            except Exception as e:
                print(f"  [WS] Connection error: {e}", flush=True)

            if not self._running:
                break

            backoff = min(RECONNECT_BASE * (2 ** (self._reconnect_count - 1)), RECONNECT_MAX)
            print(f"  [WS] Reconnect sau {backoff}s...", flush=True)
            time.sleep(backoff)

    def _run_websocket(self, url: str) -> None:
        """Chạy một WebSocket session đến khi bị đóng."""
        try:
            import websocket as ws_lib
        except ImportError:
            raise ImportError(
                "websocket-client chưa được cài. Chạy: pip install websocket-client>=1.8.0"
            )

        def on_message(ws, message):
            self._last_message_time = time.time()
            try:
                msg = json.loads(message)
                parsed = _parse_kline_event(msg)
                if parsed is None:
                    return

                coin = parsed["coin"]
                interval = parsed["interval"]
                candle = parsed["candle"]
                is_closed = parsed["is_closed"]

                closed = self.store.update(coin, interval, candle, is_closed)

                if closed and self.on_candle_close:
                    try:
                        self.on_candle_close(coin, interval)
                    except Exception as cb_err:
                        print(f"  [WS] Callback error ({coin}/{interval}): {cb_err}", flush=True)
            except Exception as e:
                print(f"  [WS] on_message error: {e}", flush=True)

        def on_open(ws):
            self._reconnect_count = 0  # reset on successful connect
            self._last_message_time = time.time()
            print(f"  [WS] ✅ Connected to Binance stream", flush=True)

        def on_close(ws, close_status_code, close_msg):
            print(f"  [WS] ⚠️  Disconnected ({close_status_code}: {close_msg})", flush=True)

        def on_error(ws, error):
            print(f"  [WS] ❌ Error: {error}", flush=True)

        self._ws = ws_lib.WebSocketApp(
            url,
            on_message=on_message,
            on_open=on_open,
            on_close=on_close,
            on_error=on_error,
        )
        # run_forever blocks until connection closes
        self._ws.run_forever(ping_interval=20, ping_timeout=10)

    # ── Health check (for scheduler fallback) ────────────────────────────────

    def is_healthy(self) -> bool:
        """
        Trả về True nếu WS đang hoạt động bình thường.
        Dùng trong watchdog schedule job.
        """
        if not self._running or self._last_message_time == 0:
            return False
        return (time.time() - self._last_message_time) < self.health_timeout

    def check_health(self) -> bool:
        """
        Watchdog được gọi bởi scheduler mỗi 20 phút.
        Nếu unhealthy, log cảnh báo để caller biết dùng REST fallback.
        Returns: True nếu healthy, False nếu cần fallback.
        """
        healthy = self.is_healthy()
        if not healthy:
            elapsed = time.time() - self._last_message_time if self._last_message_time else -1
            print(
                f"  [WS] ⚠️  Unhealthy! Không nhận message trong {elapsed:.0f}s. "
                f"REST fallback sẽ được dùng.",
                flush=True,
            )
        return healthy

    # ── Convenience getter ────────────────────────────────────────────────────

    def get_candles(self, coin: str, interval: str = "15m") -> list[dict]:
        """Thread-safe getter, forward tới CandleStore."""
        return self.store.get(coin, interval)
