"""Helper filters for trading logic: SFP, ATR-based SL, ATR shock filter, sentiment modifier.

Designed to be lightweight and dependency-free: works with Python lists or sequence-like indexable objects.
"""
from typing import Sequence


def moving_average(values: Sequence[float], window: int) -> float:
    if window <= 0:
        raise ValueError("window must be > 0")
    if len(values) < window:
        return sum(values) / max(1, len(values))
    return sum(values[-window:]) / window


def is_bullish_sfp(low: Sequence[float], close: Sequence[float], open_: Sequence[float],
                   volume: Sequence[float], idx: int, prev_swing_low: float,
                   volume_ma: float) -> bool:
    """Simple Swing Failure Pattern (bullish) detector.

    Conditions (as described):
    - current low < prev_swing_low
    - current close > prev_swing_low (reclaim)
    - lower_wick_ratio > 0.45
    - current volume > volume_ma * 1.5

    Works with index `idx` on lists/arrays for the candle to evaluate.
    """
    if idx <= 0 or idx >= len(low):
        return False

    hl_range = max(1e-9, (max(open_[idx], close[idx]) - low[idx]))
    lower_wick = (min(open_[idx], close[idx]) - low[idx])
    lower_wick_ratio = lower_wick / hl_range

    return (
        low[idx] < prev_swing_low
        and close[idx] > prev_swing_low
        and lower_wick_ratio > 0.45
        and volume[idx] > volume_ma * 1.5
    )


def true_range(high: Sequence[float], low: Sequence[float], close: Sequence[float], idx: int) -> float:
    prev_close = close[idx - 1] if idx > 0 else close[idx]
    return max(high[idx] - low[idx], abs(high[idx] - prev_close), abs(low[idx] - prev_close))


def atr(high: Sequence[float], low: Sequence[float], close: Sequence[float], window: int = 14) -> float:
    if len(high) < 1:
        return 0.0
    trs = [true_range(high, low, close, i) for i in range(len(high))]
    if len(trs) < window:
        return sum(trs) / max(1, len(trs))
    return sum(trs[-window:]) / window


def atr_shock_filter(atr_current: float, atr_ma: float, threshold: float = 1.8) -> bool:
    """Return True if ATR is in 'shock' territory and we should avoid immediate updates."""
    if atr_ma <= 0:
        return False
    return atr_current > atr_ma * threshold


def atr_used_for_chandelier(atr_current: float, atr_ma: float, cap_multiplier: float = 1.5) -> float:
    """Apply ATR capped smoothing to avoid shocks affecting Chandelier immediately."""
    if atr_ma is None or atr_ma <= 0:
        return atr_current
    return min(atr_current, atr_ma * cap_multiplier)


def dynamic_sl_long(support: float, atr_current: float, atr_ma: float,
                    multiplier: float = 0.5, cap_multiplier: float = 1.5,
                    min_sl: float | None = None, max_sl: float | None = None) -> float:
    """Compute dynamic SL for long trades using ATR with optional clamping."""
    atr_used = atr_used_for_chandelier(atr_current, atr_ma, cap_multiplier=cap_multiplier)
    sl = support - multiplier * atr_used
    if min_sl is not None:
        sl = max(sl, min_sl)
    if max_sl is not None:
        sl = min(sl, max_sl)
    return sl


def dynamic_sl_short(resistance: float, atr_current: float, atr_ma: float,
                     multiplier: float = 0.5, cap_multiplier: float = 1.5,
                     min_sl: float | None = None, max_sl: float | None = None) -> float:
    atr_used = atr_used_for_chandelier(atr_current, atr_ma, cap_multiplier=cap_multiplier)
    sl = resistance + multiplier * atr_used
    if min_sl is not None:
        sl = max(sl, min_sl)
    if max_sl is not None:
        sl = min(sl, max_sl)
    return sl


def sentiment_modify(confidence: float, trend: str, signal: str, fear_extreme: bool) -> float:
    """Apply sentiment modifier to a confidence score. Returns adjusted confidence."""
    if trend == 'BEAR' and signal == 'SHORT' and fear_extreme:
        confidence -= 0.1
    if trend == 'BULL' and signal == 'LONG' and not fear_extreme:
        confidence += 0.05
    return max(0.0, min(1.0, confidence))


if __name__ == '__main__':
    # Quick smoke test / example usage
    highs = [10, 11, 12, 13, 12]
    lows = [9, 9.5, 10, 11, 10.5]
    opens = [9.5, 10, 11, 12, 11]
    closes = [10, 11, 11.5, 12.5, 11.2]
    volumes = [100, 120, 90, 300, 200]

    vol_ma = moving_average(volumes[:-1], 3)
    prev_swing_low = 10.8
    idx = 4
    print('bullish_sfp?', is_bullish_sfp(lows, closes, opens, volumes, idx, prev_swing_low, vol_ma))
    atr_val = atr(highs, lows, closes, window=3)
    atr_ma_val = atr(highs[:-1], lows[:-1], closes[:-1], window=3)
    print('atr', atr_val, 'atr_ma', atr_ma_val)
    print('atr_shock?', atr_shock_filter(atr_val, atr_ma_val))
    print('dynamic SL long', dynamic_sl_long(10.5, atr_val, atr_ma_val))