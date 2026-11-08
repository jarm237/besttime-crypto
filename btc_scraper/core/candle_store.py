"""
CandleStore — Thread-safe sliding-window OHLCV candle store.

Dùng chung giữa WebSocket updater và analysis pipeline.
Hỗ trợ nhiều coin × nhiều interval cùng lúc.
"""

import threading
import time
from collections import defaultdict
from copy import deepcopy
from typing import Optional


DEFAULT_STREAM_CAPACITIES: dict[tuple[str, str], int] = {
    ("BTC", "15m"): 500,
    ("ETH", "15m"): 500,
    ("BNB", "15m"): 500,
}


class CandleStore:
    """
    Thread-safe in-memory store cho OHLCV candles.

    Layout:
        _store[coin][interval] = list[dict]
        ví dụ: _store["BTC"]["15m"] = [...210 candles...]

    Sliding window: khi số nến > capacity, tự động bỏ nến cũ nhất.
    """

    def __init__(
        self,
        max_candles: int = 220,
        capacity_overrides: Optional[dict[tuple[str, str], int]] = None,
    ):
        """
        Args:
            max_candles: Số nến tối đa mỗi (coin, interval) giữ lại mặc định.
                         210 cho SMA200 + 10 buffer.
            capacity_overrides: Bản đồ ghi đè capacity riêng cho từng stream (coin, interval).
        """
        self._store: dict[str, dict[str, list[dict]]] = defaultdict(dict)
        self._last_updated: dict[str, dict[str, float]] = defaultdict(dict)
        self._lock = threading.RLock()
        self.max_candles = max_candles
        if capacity_overrides is not None:
            self.capacity_overrides = dict(capacity_overrides)
        elif max_candles == 220:
            self.capacity_overrides = dict(DEFAULT_STREAM_CAPACITIES)
        else:
            self.capacity_overrides = {}

    def get_capacity(self, coin: str, interval: str) -> int:
        """Trả về số nến tối đa được lưu trữ cho cặp (coin, interval)."""
        return self.capacity_overrides.get((coin.upper(), interval), self.max_candles)

    # ── Seeding (from REST bootstrap) ────────────────────────────────────────

    def seed(self, coin: str, interval: str, candles: list[dict], now: Optional[float] = None) -> None:
        """
        Khởi tạo store từ REST API response hoặc historical replay.
        Ghi đè toàn bộ candles cũ nếu có.
        """
        if not candles:
            return
        coin = coin.upper()
        capacity = self.get_capacity(coin, interval)
        with self._lock:
            self._store[coin][interval] = list(candles[-capacity:])
            self._last_updated[coin][interval] = now if now is not None else time.time()

    # ── Updating (from WebSocket) ─────────────────────────────────────────────

    def update(
        self,
        coin: str,
        interval: str,
        candle: dict,
        is_closed: bool | None = None,
        now: Optional[float] = None,
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
        capacity = self.get_capacity(coin, interval)
        with self._lock:
            existing = self._store[coin].setdefault(interval, [])
            if existing and existing[-1]["time"] == candle_entry["time"]:
                # Cập nhật nến hiện tại (live tick)
                existing[-1] = candle_entry
            elif is_closed:
                # Nến mới đã đóng → append
                existing.append(candle_entry)
                # Trim sliding window
                if len(existing) > capacity:
                    self._store[coin][interval] = existing[-capacity:]
            else:
                # Nến đang hình thành, chưa có trong store → thêm tạm
                existing.append(candle_entry)
                if len(existing) > capacity:
                    self._store[coin][interval] = existing[-capacity:]
            self._last_updated[coin][interval] = now if now is not None else time.time()
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

    def is_fresh(
        self,
        coin: str,
        interval: str = "15m",
        max_age_seconds: float = 1800.0,
        max_future_skew_seconds: float = 60.0,
        now: Optional[float] = None,
    ) -> bool:
        """
        Kiểm tra dữ liệu nến trong CandleStore có tươi mới hay không.
        Điều kiện:
        1. Có nến trong store.
        2. Thời điểm cập nhật cuối cùng (_last_updated) nằm trong [ref_time - max_age_seconds, ref_time + max_future_skew_seconds].
        3. Thời điểm của nến cuối cùng (candle_ts) nằm trong [ref_time - max_age_seconds, ref_time + max_future_skew_seconds].
        """
        coin = coin.upper()
        with self._lock:
            candles = self._store.get(coin, {}).get(interval, [])
            if not candles:
                return False

            ref_time = now if now is not None else time.time()

            last_updated = self._last_updated.get(coin, {}).get(interval)
            if last_updated is not None:
                if (ref_time - last_updated) > max_age_seconds:
                    return False
                if (last_updated - ref_time) > max_future_skew_seconds:
                    return False

            last_candle = candles[-1]
            candle_ts = None
            if "time_utc" in last_candle and isinstance(last_candle["time_utc"], str):
                try:
                    import datetime as _dt
                    dt_val = _dt.datetime.fromisoformat(last_candle["time_utc"].replace("Z", "+00:00"))
                    candle_ts = dt_val.timestamp()
                except Exception:
                    pass
            elif "time" in last_candle:
                val = last_candle["time"]
                if isinstance(val, (int, float)):
                    candle_ts = float(val if val < 1e11 else val / 1000.0)
                elif isinstance(val, str):
                    try:
                        import datetime as _dt
                        dt_val = _dt.datetime.strptime(val, "%Y-%m-%d %H:%M").replace(tzinfo=_dt.timezone.utc)
                        candle_ts = dt_val.timestamp()
                    except Exception:
                        pass

            if candle_ts is not None:
                if (ref_time - candle_ts) > max_age_seconds:
                    return False
                if (candle_ts - ref_time) > max_future_skew_seconds:
                    return False

            return True

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
