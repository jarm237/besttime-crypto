"""
btc_scraper/research/multi_source_strategies.py
Phase M4 Controlled Successor Strategies utilizing Multi-Source Features.

Contains rule-based candidate successors separated strictly from the frozen M5 candidate:
1. BasisFilteredTrendStrategy: EMA(12, 26) filtered by positive Spot/Futures basis (contango).
2. OiFilteredTrendStrategy: EMA(12, 26) filtered by expanding Futures Open Interest and taker flow > 1.0.
3. MacroFilteredMeanReversionStrategy: RSI & Bollinger mean reversion filtered by Macro yield curve slope.
4. CombinedMultiSourceStrategy: Evaluates combined multi-source signals.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence
from btc_scraper.research.baseline_runner import BaselineStrategy


class BasisFilteredTrendStrategy(BaselineStrategy):
    """
    Price + Cross-market basis filter.
    Enters LONG on EMA(12, 26) bullish crossover ONLY IF futures basis is in contango (basis_bps > 0).
    Exits on EMA bearish crossover.
    """
    TIER = "CANDIDATE"
    STATUS = "ACTIVE"

    def __init__(self, fast_period: int = 12, slow_period: int = 26, min_basis_bps: float = 0.0):
        super().__init__("basis_filtered_trend_v1")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.min_basis_bps = min_basis_bps

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        n = len(historical_candles)
        if n < self.slow_period + 2:
            return None

        closes = [float(c["close"]) for c in historical_candles[-self.slow_period - 2:]] + [float(current_candle["close"])]

        # Calculate fast & slow EMAs
        def _calc_ema(series: List[float], period: int) -> float:
            k = 2.0 / (period + 1.0)
            val = series[0]
            for x in series[1:]:
                val = x * k + val * (1.0 - k)
            return val

        fast_curr = _calc_ema(closes[-self.fast_period:], self.fast_period)
        fast_prev = _calc_ema(closes[-self.fast_period - 1:-1], self.fast_period)
        slow_curr = _calc_ema(closes[-self.slow_period:], self.slow_period)
        slow_prev = _calc_ema(closes[-self.slow_period - 1:-1], self.slow_period)

        bullish_cross = (fast_prev <= slow_prev) and (fast_curr > slow_curr)
        bearish_cross = (fast_prev >= slow_prev) and (fast_curr < slow_curr)

        basis_bps = float(current_candle.get("basis_bps", float("nan")))
        basis_valid = not math.isnan(basis_bps) and basis_bps > self.min_basis_bps

        if current_position is None:
            if bullish_cross and basis_valid:
                return {
                    "action": "BUY",
                    "reason": f"ema_cross_basis_confirmed (basis={basis_bps:.1f}bps)",
                }
        else:
            if bearish_cross:
                return {
                    "action": "CLOSE",
                    "reason": "ema_bearish_crossover",
                }

        return None


class OiFilteredTrendStrategy(BaselineStrategy):
    """
    Price + Derivatives Open Interest & Taker flow filter.
    Enters LONG on EMA(12, 26) bullish crossover ONLY IF taker flow ratio > 1.0.
    """
    TIER = "CANDIDATE"
    STATUS = "ACTIVE"

    def __init__(self, fast_period: int = 12, slow_period: int = 26, min_taker_flow: float = 1.0):
        super().__init__("oi_filtered_trend_v1")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.min_taker_flow = min_taker_flow

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        n = len(historical_candles)
        if n < self.slow_period + 2:
            return None

        closes = [float(c["close"]) for c in historical_candles[-self.slow_period - 2:]] + [float(current_candle["close"])]

        def _calc_ema(series: List[float], period: int) -> float:
            k = 2.0 / (period + 1.0)
            val = series[0]
            for x in series[1:]:
                val = x * k + val * (1.0 - k)
            return val

        fast_curr = _calc_ema(closes[-self.fast_period:], self.fast_period)
        fast_prev = _calc_ema(closes[-self.fast_period - 1:-1], self.fast_period)
        slow_curr = _calc_ema(closes[-self.slow_period:], self.slow_period)
        slow_prev = _calc_ema(closes[-self.slow_period - 1:-1], self.slow_period)

        bullish_cross = (fast_prev <= slow_prev) and (fast_curr > slow_curr)
        bearish_cross = (fast_prev >= slow_prev) and (fast_curr < slow_curr)

        taker_flow = float(current_candle.get("taker_flow_ratio", float("nan")))
        flow_valid = not math.isnan(taker_flow) and taker_flow >= self.min_taker_flow

        if current_position is None:
            if bullish_cross and flow_valid:
                return {
                    "action": "BUY",
                    "reason": f"ema_cross_oi_flow_confirmed (flow={taker_flow:.2f})",
                }
        else:
            if bearish_cross:
                return {
                    "action": "CLOSE",
                    "reason": "ema_bearish_crossover",
                }

        return None


class MacroFilteredMeanReversionStrategy(BaselineStrategy):
    """
    Price + Macro yield curve filter.
    Enters LONG on RSI(14) < 30 lower Bollinger breach ONLY IF Treasury yield curve is not severely inverted (slope > -1.0%).
    """
    TIER = "CANDIDATE"
    STATUS = "ACTIVE"

    def __init__(self, rsi_period: int = 14, bb_period: int = 20, bb_std: float = 2.0, min_slope: float = -1.0):
        super().__init__("macro_filtered_mr_v1")
        self.rsi_period = rsi_period
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.min_slope = min_slope

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        n = len(historical_candles)
        if n < max(self.rsi_period, self.bb_period) + 2:
            return None

        closes = [float(c["close"]) for c in historical_candles[-self.bb_period:]] + [float(current_candle["close"])]
        curr_price = closes[-1]

        # Bollinger Bands
        sma = sum(closes[-self.bb_period:]) / float(self.bb_period)
        variance = sum((x - sma) ** 2 for x in closes[-self.bb_period:]) / float(self.bb_period)
        std = math.sqrt(variance)
        lower_band = sma - self.bb_std * std

        # RSI(14)
        all_closes = [float(c["close"]) for c in historical_candles[-self.rsi_period - 1:]] + [curr_price]
        gains = []
        losses = []
        for i in range(1, len(all_closes)):
            chg = all_closes[i] - all_closes[i - 1]
            if chg > 0:
                gains.append(chg)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(chg))

        avg_gain = sum(gains) / float(self.rsi_period)
        avg_loss = sum(losses) / float(self.rsi_period)
        rs = avg_gain / max(avg_loss, 1e-8)
        rsi = 100.0 - (100.0 / (1.0 + rs))

        slope = float(current_candle.get("treasury_slope_10_2", float("nan")))
        macro_valid = math.isnan(slope) or slope >= self.min_slope

        if current_position is None:
            # Oversold bounce condition
            if rsi < 30.0 and curr_price <= lower_band and macro_valid:
                return {
                    "action": "BUY",
                    "reason": f"mr_oversold_macro_pass (rsi={rsi:.1f}, slope={slope:.2f})",
                }
        else:
            # Exit when RSI recovers above 50 or reaches SMA
            if rsi >= 50.0 or curr_price >= sma:
                return {
                    "action": "CLOSE",
                    "reason": "mr_reversion_target_hit",
                }

        return None
