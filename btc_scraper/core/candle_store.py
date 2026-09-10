"""
CandleStore — Thread-safe sliding-window OHLCV candle store.

Dùng chung giữa WebSocket updater và analysis pipeline.
Hỗ trợ nhiều coin × nhiều interval cùng lúc.
"""

import threading
from collections import defaultdict
from copy import deepcopy
from typing import Optional


class CandleStore:
    """
    Thread-safe in-memory store cho OHLCV candles.

    Layout:
        _store[coin][interval] = list[dict]
        ví dụ: _store["BTC"]["15m"] = [...210 candles...]

    Sliding window: khi số nến > max_candles, tự động bỏ nến cũ nhất.
    """

    def __init__(self, max_candles: int = 220):
        """
        Args:
            max_candles: Số nến tối đa mỗi (coin, interval) giữ lại.
                         210 cho SMA200 + 10 buffer.
        """
        self._store: dict[str, dict[str, list[dict]]] = defaultdict(dict)
        self._lock = threading.RLock()
        self.max_candles = max_candles

    # ── Seeding (from REST bootstrap) ────────────────────────────────────────

    def seed(self, coin: str, interval: str, candles: list[dict]) -> None:
        """
        Khởi tạo store từ REST API response.
        Ghi đè toàn bộ candles cũ nếu có.
        """
        if not candles:
            return
        coin = coin.upper()
        with self._lock:
            self._store[coin][interval] = list(candles[-self.max_candles:])

    # ── Updating (from WebSocket) ─────────────────────────────────────────────

    def update(
        self,
        coin: str,
        interval: str,
        candle: dict,
        is_closed: bool | None = None,
    ) -> bool:
        """
        Cập nhật nến đang hình thành (live) hoặc thêm nến đã đóng.

        Nếu nến có cùng `time` với nến cuối cùng trong store → cập nhật in-place.
        Nếu là nến mới (time mới) và is_closed=True → thêm vào cuối.

        Returns:
            True nếu đây là nến đã đóng hoàn toàn (is_closed).
        """
        if is_closed is None:
            c_flag = candle.get("closed")
            if c_flag is None:
                c_flag = candle.get("is_closed")
            is_closed = bool(c_flag) if c_flag is not None else False

        coin = coin.upper()
        candle_entry = dict(candle)
        candle_entry["closed"] = bool(is_closed)
        candle_entry["is_closed"] = bool(is_closed)
        with self._lock:
            existing = self._store[coin].setdefault(interval, [])
            if existing and existing[-1]["time"] == candle_entry["time"]:
                # Cập nhật nến hiện tại (live tick)
                existing[-1] = candle_entry
            elif is_closed:
                # Nến mới đã đóng → append
                existing.append(candle_entry)
                # Trim sliding window
                if len(existing) > self.max_candles:
                    self._store[coin][interval] = existing[-self.max_candles:]
            else:
                # Nến đang hình thành, chưa có trong store → thêm tạm
                existing.append(candle_entry)
        return is_closed

    # ── Reading ───────────────────────────────────────────────────────────────

    def get(self, coin: str, interval: str = "15m") -> list[dict]:
        """
        Thread-safe getter. Trả về shallow copy để tránh race condition.

        Returns:
            list[dict] với các trường: time, open, high, low, close, volume
            Trả về list rỗng nếu chưa có dữ liệu.
        """
        coin = coin.upper()
        with self._lock:
            data = self._store.get(coin, {}).get(interval, [])
            return list(data)  # shallow copy là đủ vì dict trong list là immutable ở mức phân tích

    def has_data(self, coin: str, interval: str = "15m") -> bool:
        """Kiểm tra xem có dữ liệu cho coin + interval không."""
        coin = coin.upper()
        with self._lock:
            return bool(self._store.get(coin, {}).get(interval))

    def candle_count(self, coin: str, interval: str = "15m") -> int:
        """Trả về số nến hiện có."""
        coin = coin.upper()
        with self._lock:
            return len(self._store.get(coin, {}).get(interval, []))

    def all_coins(self) -> list[str]:
        """Danh sách tất cả coin đang được lưu."""
        with self._lock:
            return list(self._store.keys())


# Singleton — dùng chung giữa WS manager và main pipeline
candle_store = CandleStore(max_candles=220)
