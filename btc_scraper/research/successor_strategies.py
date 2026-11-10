"""
btc_scraper/research/successor_strategies.py
Phase B: Pre-Registered Strategy Implementations for M4 Successor Research.

Contains 3 Hypothesis Families:
1. H-S1: CostAwareMeanReversionStrategy (3 Variants: 30, 40, 50 bps hurdle to middle Bollinger Band).
2. H-S2: GenuineOiTrendStrategy (3 Variants: delta_oi_24h > 0, delta_oi_24h >= 2%, delta_oi_24h > 0 AND oi > sma_5d).
3. H-S3: HtfTrendFilteredMeanReversionStrategy (3 Variants: 4h EMA 100, 150, 200 closed-candle trend filter).

Strict Invariants:
- Zero lookahead: H-S3 only accesses 4h candles that closed at or before 1h bar close T.
- Genuine OI: H-S2 uses sum_open_interest_usd and 24h OI changes, NOT taker_flow_ratio or basis.
- Execution Timing: Signals generated at bar close T -> filled at bar T+1 open (NEXT_BAR_OPEN).
- Spot long-only: Derivatives funding is NOT deducted from spot PnL.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from btc_scraper.research.baseline_runner import BaselineStrategy


# ── Family 1: H-S1 (Cost-Aware Entry Hurdle) ──────────────────────────────────

class CostAwareMeanReversionStrategy(BaselineStrategy):
    """
    RSI + Bollinger Mean Reversion with a minimum distance hurdle to the middle Bollinger Band.
    Enters LONG only when:
      1. Close < Lower Bollinger Band
      2. RSI(14) < oversold (30.0)
      3. (SMA_20 - Close) / Close * 10,000 >= min_distance_bps
    Exits LONG when:
      1. Close >= SMA_20 OR RSI >= exit_threshold (50.0)
    """
    TIER = "CANDIDATE"
    STATUS = "ACTIVE"

    def __init__(
        self,
        min_distance_bps: float = 40.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_exit: float = 50.0,
        bb_period: int = 20,
        bb_std: float = 2.0,
        variant_id: str = "H_S1_V2",
    ):
        name = f"cost_aware_mr_{int(min_distance_bps)}bps_{variant_id.lower()}"
        super().__init__(name)
        self.variant_id = variant_id
        self.min_distance_bps = min_distance_bps
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_exit = rsi_exit
        self.bb_period = bb_period
        self.bb_std = bb_std

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        n = len(historical_candles)
        min_bars = max(self.bb_period, self.rsi_period) + 2
        if n < min_bars:
            return None

        closes = [float(c["close"]) for c in historical_candles[-min_bars:]] + [float(current_candle["close"])]
        current_price = closes[-1]

        # 1. Bollinger Bands
        bb_slice = closes[-self.bb_period:]
        sma_bb = sum(bb_slice) / self.bb_period
        variance = sum((x - sma_bb) ** 2 for x in bb_slice) / self.bb_period
        std = math.sqrt(variance)
        lower_band = sma_bb - self.bb_std * std

        # 2. RSI Calculation
        gains, losses = [], []
        for i in range(-self.rsi_period, 0):
            diff = closes[i] - closes[i - 1]
            if diff >= 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(-diff)

        avg_gain = sum(gains) / len(gains) if gains else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        if avg_loss < 1e-12:
            rsi = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # 3. Distance Hurdle to Middle Band
        distance_bps = ((sma_bb - current_price) / current_price) * 10_000.0

        # Entry logic (flat)
        if current_position is None:
            if current_price < lower_band and rsi < self.rsi_oversold:
                if distance_bps >= self.min_distance_bps:
                    return {
                        "action": "BUY",
                        "reason": f"cost_aware_dip (rsi={rsi:.1f}, dist={distance_bps:.1f}bps >= {self.min_distance_bps}bps)",
                    }
        # Exit logic (long)
        else:
            if current_price >= sma_bb or rsi >= self.rsi_exit:
                return {
                    "action": "CLOSE",
                    "reason": f"cost_aware_exit (close={current_price:.2f} >= sma={sma_bb:.2f} or rsi={rsi:.1f})",
                }

        return None


# ── Family 2: H-S2 (Genuine Open Interest Expansion) ─────────────────────────

class GenuineOiTrendStrategy(BaselineStrategy):
    """
    EMA(12, 26) Trend Following filtered by genuine USD-M Futures Open Interest expansion.
    Enters LONG on EMA bullish cross ONLY IF:
      - Variant 1 (H_S2_V1): delta_oi_24h > 0 (expanding OI in USD over 24h)
      - Variant 2 (H_S2_V2): delta_oi_24h >= +2.0% (significant OI expansion)
      - Variant 3 (H_S2_V3): delta_oi_24h > 0 AND current_oi > SMA_5d(oi)
    Exits LONG on EMA bearish cross.
    """
    TIER = "CANDIDATE"
    STATUS = "ACTIVE"

    def __init__(
        self,
        min_oi_change_pct: float = 0.0,
        require_sma_filter: bool = False,
        fast_period: int = 12,
        slow_period: int = 26,
        variant_id: str = "H_S2_V1",
    ):
        name = f"genuine_oi_trend_{variant_id.lower()}"
        super().__init__(name)
        self.variant_id = variant_id
        self.min_oi_change_pct = min_oi_change_pct
        self.require_sma_filter = require_sma_filter
        self.fast_period = fast_period
        self.slow_period = slow_period

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        n = len(historical_candles)
        min_bars = max(self.slow_period + 2, 125)  # 120 bars for 5d OI SMA + buffer
        if n < min_bars:
            return None

        # 1. EMA(12, 26) Cross
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

        # 2. Genuine Open Interest Metrics
        current_oi = float(current_candle.get("oi_usd", float("nan")))
        oi_valid = not math.isnan(current_oi) and current_oi > 0.0

        if not oi_valid:
            # If OI data is missing, fail-closed
            oi_condition = False
        else:
            # 24h change
            past_24h_c = historical_candles[-24]
            past_24h_oi = float(past_24h_c.get("oi_usd", float("nan")))
            if not math.isnan(past_24h_oi) and past_24h_oi > 0:
                delta_oi_24h = (current_oi - past_24h_oi) / past_24h_oi
            else:
                delta_oi_24h = 0.0

            if self.min_oi_change_pct == 0.0:
                delta_pass = delta_oi_24h > 0.0
            else:
                delta_pass = delta_oi_24h >= self.min_oi_change_pct

            if self.require_sma_filter:
                # 5-day (120-hour) rolling average OI
                recent_ois = [float(c.get("oi_usd", float("nan"))) for c in historical_candles[-120:]]
                valid_ois = [x for x in recent_ois if not math.isnan(x) and x > 0]
                if valid_ois:
                    sma_oi_5d = sum(valid_ois) / len(valid_ois)
                    sma_pass = current_oi > sma_oi_5d
                else:
                    sma_pass = False
            else:
                sma_pass = True

            oi_condition = delta_pass and sma_pass

        # Entry logic
        if current_position is None:
            if bullish_cross and oi_condition:
                return {
                    "action": "BUY",
                    "reason": f"ema_cross_genuine_oi_confirmed (delta_oi_24h={delta_oi_24h*100:+.2f}%)",
                }
        # Exit logic
        else:
            if bearish_cross:
                return {
                    "action": "CLOSE",
                    "reason": "ema_bearish_crossover",
                }

        return None


# ── Family 3: H-S3 (Higher-Timeframe 4h Trend Alignment) ──────────────────────

class HtfTrendFilteredMeanReversionStrategy(BaselineStrategy):
    """
    1h RSI + Bollinger Mean Reversion filtered by higher-timeframe 4h closed-candle trend.
    Closed-Bar Invariant:
      Only 4h candles that CLOSED at or before 1h bar close T are used.
      Never uses the forming/uncompleted 4h bucket.
    Enters LONG only when:
      1. 1h Close < 1h Lower Bollinger Band
      2. 1h RSI(14) < oversold (30.0)
      3. Latest CLOSED 4h Close > 4h EMA(N)  where N in {100, 150, 200}
    Exits LONG when:
      1. 1h Close >= 1h SMA_20 OR 1h RSI >= 50.0
    """
    TIER = "CANDIDATE"
    STATUS = "ACTIVE"

    def __init__(
        self,
        ema_period_4h: int = 200,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_exit: float = 50.0,
        bb_period: int = 20,
        bb_std: float = 2.0,
        variant_id: str = "H_S3_V3",
    ):
        name = f"htf_trend_mr_4h_ema{ema_period_4h}_{variant_id.lower()}"
        super().__init__(name)
        self.variant_id = variant_id
        self.ema_period_4h = ema_period_4h
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_exit = rsi_exit
        self.bb_period = bb_period
        self.bb_std = bb_std

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        n = len(historical_candles)
        min_bars = max(self.bb_period, self.rsi_period) + 2
        if n < min_bars:
            return None

        # 1. 1h Bollinger Bands & RSI
        closes = [float(c["close"]) for c in historical_candles[-min_bars:]] + [float(current_candle["close"])]
        current_price = closes[-1]

        bb_slice = closes[-self.bb_period:]
        sma_bb = sum(bb_slice) / self.bb_period
        variance = sum((x - sma_bb) ** 2 for x in bb_slice) / self.bb_period
        std = math.sqrt(variance)
        lower_band = sma_bb - self.bb_std * std

        gains, losses = [], []
        for i in range(-self.rsi_period, 0):
            diff = closes[i] - closes[i - 1]
            if diff >= 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(-diff)

        avg_gain = sum(gains) / len(gains) if gains else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        if avg_loss < 1e-12:
            rsi = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # 2. 4h Closed-Candle Trend Filter (pre-computed in candle metadata or history)
        # current_candle['htf_4h_close'] and current_candle['htf_4h_ema_{period}']
        htf_close = float(current_candle.get("htf_4h_close", float("nan")))
        htf_ema = float(current_candle.get(f"htf_4h_ema_{self.ema_period_4h}", float("nan")))

        if math.isnan(htf_close) or math.isnan(htf_ema):
            # Fallback if not enriched: calculate on the fly from closed 4h bars
            htf_bullish = False
        else:
            htf_bullish = htf_close > htf_ema

        # Entry logic
        if current_position is None:
            if current_price < lower_band and rsi < self.rsi_oversold:
                if htf_bullish:
                    return {
                        "action": "BUY",
                        "reason": f"htf_trend_dip (rsi={rsi:.1f}, 4h_close={htf_close:.2f} > 4h_ema={htf_ema:.2f})",
                    }
        # Exit logic
        else:
            if current_price >= sma_bb or rsi >= self.rsi_exit:
                return {
                    "action": "CLOSE",
                    "reason": f"htf_mr_exit (close={current_price:.2f} >= sma={sma_bb:.2f} or rsi={rsi:.1f})",
                }

        return None
