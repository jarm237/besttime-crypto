"""
btc_scraper/research/candle_aggregator.py
Phase G7 & Phase G8 (P0-5) / Phase C2: Deterministic 15m -> 1h Closed Candle Aggregator.

Provides:
1. ClosedCandleAggregator: Stateful streaming aggregator producing canonical 1h closed candles
   from four consecutive, validated 15m closed candles.
2. Invariants:
   - Zero lookahead: Forming or unclosed 15m bars are strictly rejected.
   - Exact hour bucket alignment (minutes 00, 15, 30, 45).
   - Strict completeness: A 1h candle is emitted ONLY when all 4 consecutive 15m candles are closed.
   - Gap detection: If any 15m bar is missing or timestamps jump, bucket is invalidated (fail-closed).
   - Duplicate detection: Duplicate 15m bars are cleanly ignored without mutating buffer state.
   - Late data handling: Late-arriving bars for already finalized hours are rejected.
   - Deterministic candle hash: Synthesized 1h bars include cryptographic SHA-256 digest.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


class ClosedCandleAggregator:
    """
    Stateful aggregator converting validated 15m closed candles into canonical 1h closed candles.
    """

    EXPECTED_15M_MINUTES: Tuple[int, ...] = (0, 15, 30, 45)

    def __init__(self, symbol: str = "ETHUSDT"):
        self.symbol = symbol
        self._current_hour_key: Optional[str] = None
        self._last_emitted_hour_key: Optional[str] = None
        self._bucket_15m_bars: List[Dict[str, Any]] = []

    def reset(self) -> None:
        """Resets the internal aggregation buffer."""
        self._current_hour_key = None
        self._last_emitted_hour_key = None
        self._bucket_15m_bars.clear()

    @property
    def buffered_bars_count(self) -> int:
        return len(self._bucket_15m_bars)

    def add_15m_candle(self, candle: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Ingests a single 15m candle.
        Returns the aggregated 1h closed candle when the 4th constituent bar (minute 45) closes.
        Returns None while the hour is accumulating or if bar validation fails.
        """
        # 1. Verify closed candle invariant
        is_closed = candle.get("is_closed", candle.get("closed", True))
        if not is_closed:
            raise ValueError(f"Unclosed or forming 15m candle rejected at {candle.get('time')}")

        bar_time_str = str(candle.get("time", candle.get("open_time_utc", "")))
        if not bar_time_str:
            raise ValueError("15m candle missing timestamp ('time' or 'open_time_utc')")

        # Parse timestamp to UTC datetime
        dt = self._parse_iso_timestamp(bar_time_str)
        if dt.minute not in self.EXPECTED_15M_MINUTES:
            raise ValueError(f"15m candle timestamp {bar_time_str} is not aligned to 0, 15, 30, or 45 minutes.")

        hour_key = dt.strftime("%Y-%m-%dT%H:00:00Z")

        # 2. Late data handling: if bar is for an already emitted hour, reject
        if self._last_emitted_hour_key is not None and hour_key <= self._last_emitted_hour_key:
            return None

        # 3. Duplicate detection in current in-flight bucket
        for existing in self._bucket_15m_bars:
            existing_time = str(existing.get("time", existing.get("open_time_utc", "")))
            if existing_time == bar_time_str:
                # Duplicate bar: ignore without corrupting buffer
                return None

        # 4. Check for hour bucket change or gap
        if self._current_hour_key is not None and hour_key != self._current_hour_key:
            # Timestamp moved to a new hour before completing current bucket
            if len(self._bucket_15m_bars) < 4:
                # Incomplete previous hour: discard to fail-closed against gaps
                self._bucket_15m_bars.clear()
            self._current_hour_key = hour_key

        if self._current_hour_key is None:
            self._current_hour_key = hour_key

        # 5. Verify sequence alignment within current hour
        expected_index = len(self._bucket_15m_bars)
        expected_minute = self.EXPECTED_15M_MINUTES[expected_index]
        if dt.minute != expected_minute:
            # Gap detected: reset bucket fail-closed
            self._bucket_15m_bars.clear()
            if dt.minute == 0:
                self._bucket_15m_bars.append(dict(candle))
            return None

        self._bucket_15m_bars.append(dict(candle))

        # 6. If all 4 bars (00, 15, 30, 45) are present, form and emit the 1h bar
        if len(self._bucket_15m_bars) == 4:
            aggregated_1h = self._synthesize_1h_bar(self._current_hour_key, self._bucket_15m_bars)
            self._last_emitted_hour_key = self._current_hour_key
            self._bucket_15m_bars.clear()
            self._current_hour_key = None
            return aggregated_1h

        return None

    def aggregate_batch(self, candles_15m: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        """
        Aggregates an ordered sequence of 15m candles into completed 1h candles.
        """
        self.reset()
        results: List[Dict[str, Any]] = []
        for c in candles_15m:
            out = self.add_15m_candle(c)
            if out is not None:
                results.append(out)
        return results

    def _synthesize_1h_bar(
        self,
        hour_key: str,
        bars_15m: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """Synthesizes high, low, open, close, volume and deterministic hash across four 15m bars."""
        first_bar = bars_15m[0]
        last_bar = bars_15m[-1]

        open_price = float(first_bar["open"])
        close_price = float(last_bar["close"])
        high_price = max(float(b["high"]) for b in bars_15m)
        low_price = min(float(b["low"]) for b in bars_15m)
        volume = sum(float(b.get("volume", 0.0)) for b in bars_15m)

        candle_hash = hashlib.sha256(
            f"{self.symbol}_{hour_key}_{open_price:.6f}_{high_price:.6f}_{low_price:.6f}_{close_price:.6f}_{volume:.6f}".encode("utf-8")
        ).hexdigest()

        return {
            "symbol": str(first_bar.get("symbol", self.symbol)),
            "time": hour_key,
            "open_time_utc": hour_key,
            "timeframe": "1h",
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": round(volume, 6),
            "is_closed": True,
            "constituent_bars_count": 4,
            "candle_hash": candle_hash,
            "aggregation_source": "15m_closed_bars",
        }

    @staticmethod
    def _parse_iso_timestamp(ts_str: str) -> datetime:
        """Parses UTC ISO 8601 string to datetime."""
        clean_ts = ts_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
