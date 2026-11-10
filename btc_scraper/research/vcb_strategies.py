"""
btc_scraper/research/vcb_strategies.py
Pre-Registered VCB-v2 Strategy Implementations for M4 Lineage Testing.

Components:
1. VcbV2Strategy (VCB_V2_BASELINE):
   - Volatility Compression: ATR(14) in bottom 25th percentile of rolling 72-hour window (strictly backward-looking).
   - Breakout: 1h Close > rolling 24-hour Donchian High.
   - Higher-Timeframe Trend Filter: 4h Closed Candle > 4h EMA(100).
   - Protective Stop: Entry price - 2.0 * ATR(14).
   - Trend Exit: 1h Close < 1h EMA(20) OR timeout (48h max hold).
   - Execution: NEXT_BAR_OPEN.

Ablations:
2. VCB_V2_ABL_NO_COMPRESSION: Disables volatility compression filter (Breakout + HTF only).
3. VCB_V2_ABL_NO_HTF: Disables HTF trend filter (Compression + Breakout only).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import numpy as np

from btc_scraper.research.baseline_runner import BaselineStrategy


class VcbV2Strategy(BaselineStrategy):
    """
    Regime-Adaptive Volatility Compression Breakout (VCB-v2).
    Evaluates strictly on closed 1h candles with backward-looking rolling statistics.
    """
    TIER = "CANDIDATE"
    STATUS = "ACTIVE"

    def __init__(
        self,
        atr_period: int = 14,
        compression_lookback_bars: int = 72,
        compression_percentile: float = 25.0,
        donchian_breakout_bars: int = 24,
        require_htf_trend: bool = True,
        require_compression: bool = True,
        atr_stop_multiplier: float = 2.0,
        max_holding_bars: int = 48,
        exit_ema_period: int = 20,
        variant_id: str = "VCB_V2_BASELINE",
    ):
        name = f"vcb_v2_{variant_id.lower()}"
        super().__init__(name)
        self.variant_id = variant_id
        self.atr_period = atr_period
        self.compression_lookback_bars = compression_lookback_bars
        self.compression_percentile = compression_percentile
        self.donchian_breakout_bars = donchian_breakout_bars
        self.require_htf_trend = require_htf_trend
        self.require_compression = require_compression
        self.atr_stop_multiplier = atr_stop_multiplier
        self.max_holding_bars = max_holding_bars
        self.exit_ema_period = exit_ema_period
        self._entry_bars: Dict[str, int] = {}

    def reset(self) -> None:
        self._entry_bars.clear()

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        n = len(historical_candles)
        min_required = max(
            self.compression_lookback_bars + self.atr_period + 10,
            self.donchian_breakout_bars + 10,
            self.exit_ema_period + 10,
        )
        if n < min_required:
            return None

        # Build contiguous bar series: historical + current (avoiding duplicate current bar)
        if historical_candles and (
            historical_candles[-1].get("timestamp") == current_candle.get("timestamp")
            or historical_candles[-1] is current_candle
        ):
            all_bars = list(historical_candles[-min_required:])
        else:
            all_bars = list(historical_candles[-min_required:]) + [dict(current_candle)]

        current_close = float(current_candle["close"])
        curr_idx = len(historical_candles)

        # ── In-Position Exit Logic ─────────────────────────────────────────────
        if current_position is not None:
            entry_bar = self._entry_bars.get(symbol, int(current_position.get("entry_idx", curr_idx - 1)))
            hold_duration = curr_idx - entry_bar

            # 1. Timeout exit
            if hold_duration >= self.max_holding_bars:
                self._entry_bars.pop(symbol, None)
                return {
                    "action": "CLOSE",
                    "reason": f"max_hold_timeout ({hold_duration} >= {self.max_holding_bars} bars)",
                }

            # 2. Exit EMA(20) breakdown
            closes = [float(b["close"]) for b in all_bars[-self.exit_ema_period:]]
            k = 2.0 / (self.exit_ema_period + 1.0)
            ema20 = closes[0]
            for c in closes[1:]:
                ema20 = c * k + ema20 * (1.0 - k)

            if current_close < ema20:
                self._entry_bars.pop(symbol, None)
                return {
                    "action": "CLOSE",
                    "reason": f"ema20_breakdown (close={current_close:.2f} < ema20={ema20:.2f})",
                }

            return None

        # ── Flat Entry Logic ──────────────────────────────────────────────────
        # 1. Rolling ATR(14) calculation over the last (compression_lookback_bars + 1) bars
        trs = []
        for i in range(1, len(all_bars)):
            h = float(all_bars[i]["high"])
            l = float(all_bars[i]["low"])
            prev_c = float(all_bars[i - 1]["close"])
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)

        if len(trs) < self.compression_lookback_bars + self.atr_period:
            return None

        # Calculate rolling ATR(14) series using simple rolling window
        rolling_atrs = []
        for i in range(self.atr_period, len(trs) + 1):
            atr_slice = trs[i - self.atr_period:i]
            rolling_atrs.append(sum(atr_slice) / self.atr_period)

        if len(rolling_atrs) < self.compression_lookback_bars:
            return None

        current_atr = rolling_atrs[-1]
        historical_atr_window = rolling_atrs[-self.compression_lookback_bars:]
        compression_cutoff = float(np.percentile(historical_atr_window, self.compression_percentile))

        # Check compression
        if self.require_compression:
            is_compressed = current_atr <= compression_cutoff
        else:
            is_compressed = True

        if not is_compressed:
            return None

        # 2. Donchian Breakout: Close > max High over previous 24 hours (excluding current bar)
        hist_donchian_bars = all_bars[-self.donchian_breakout_bars - 1:-1]
        donchian_high = max(float(b["high"]) for b in hist_donchian_bars)
        is_breakout = current_close > donchian_high

        if not is_breakout:
            return None

        # 3. Higher-Timeframe 4h Closed-Candle Trend Filter
        if self.require_htf_trend:
            htf_close = float(current_candle.get("htf_4h_close", float("nan")))
            htf_ema = float(current_candle.get("htf_4h_ema_100", float("nan")))
            if math.isnan(htf_close) or math.isnan(htf_ema):
                htf_bullish = False
            else:
                htf_bullish = htf_close > htf_ema
        else:
            htf_bullish = True

        if not htf_bullish:
            return None

        # All entry conditions met -> emit BUY signal
        protective_sl = current_close - self.atr_stop_multiplier * current_atr
        self._entry_bars[symbol] = curr_idx

        return {
            "action": "BUY",
            "stop_loss": protective_sl,
            "reason": (
                f"vcb_v2_breakout (atr={current_atr:.2f} <= {compression_cutoff:.2f}, "
                f"close={current_close:.2f} > donch={donchian_high:.2f})"
            ),
        }
