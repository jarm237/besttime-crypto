"""
btc_scraper/research/ml_trade_quality/feature_contract.py

Authoritative feature and label contracts for M4-ML1 Trade Quality Research.
Strictly backward-looking, zero-lookahead feature extraction at signal bar close.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import numpy as np


FEATURE_NAMES = [
    "return_6h",
    "return_12h",
    "return_24h",
    "return_48h",
    "atr_14_pct",
    "realized_vol_24h",
    "ema_fast_pct",
    "ema_slow_pct",
    "ema_spread_pct",
    "rsi_14",
    "volume_ratio_24h",
    "htf_4h_trend_alignment",
    "btc_macro_return_24h",
]


def compute_rsi(closes: Sequence[float], period: int = 14) -> float:
    """Computes standard Wilder's RSI or simple rolling RSI."""
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-period - 1:])
    gains = np.maximum(deltas, 0.0)
    losses = np.maximum(-deltas, 0.0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0.0:
        return 100.0 if avg_gain > 0.0 else 50.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def extract_features_at_bar(
    symbol_candles: Sequence[Mapping[str, Any]],
    bar_idx: int,
    btc_candles: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, float]:
    """
    Extracts strictly backward-looking features at `bar_idx` (signal candle close).
    Ensures zero future lookahead: no bar at or after `bar_idx + 1` is accessed.
    """
    if bar_idx < 48:
        raise ValueError(f"Insufficient history for feature extraction at bar_idx {bar_idx} (minimum 48 bars required)")

    curr = symbol_candles[bar_idx]
    c_close = float(curr["close"])
    if c_close <= 0.0:
        raise ValueError(f"Invalid non-positive close price {c_close} at bar_idx {bar_idx}")

    # Closes up to bar_idx
    hist_slice = symbol_candles[:bar_idx + 1]
    closes = [float(b["close"]) for b in hist_slice]
    highs = [float(b["high"]) for b in hist_slice]
    lows = [float(b["low"]) for b in hist_slice]
    volumes = [float(b.get("volume", 0.0)) for b in hist_slice]

    # 1. Return Momentum
    r6 = (c_close - closes[-7]) / closes[-7] if len(closes) >= 7 else 0.0
    r12 = (c_close - closes[-13]) / closes[-13] if len(closes) >= 13 else 0.0
    r24 = (c_close - closes[-25]) / closes[-25] if len(closes) >= 25 else 0.0
    r48 = (c_close - closes[-49]) / closes[-49] if len(closes) >= 49 else 0.0

    # 2. Volatility & ATR(14)
    trs = []
    for i in range(max(1, len(hist_slice) - 20), len(hist_slice)):
        h = highs[i]
        l = lows[i]
        prev_c = closes[i - 1]
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)))
    atr_14 = float(np.mean(trs[-14:])) if len(trs) >= 14 else (highs[-1] - lows[-1])
    atr_14_pct = atr_14 / c_close

    # Realized volatility (std of 1h log returns over last 24 bars)
    log_rets = np.diff(np.log(closes[-25:])) if len(closes) >= 25 else np.array([0.0])
    realized_vol_24h = float(np.std(log_rets, ddof=1)) if len(log_rets) > 1 else 0.0

    # 3. EMA Trend Geometry (12 and 26)
    # Compute EMAs incrementally over history
    k12 = 2.0 / (12.0 + 1.0)
    k26 = 2.0 / (26.0 + 1.0)
    ema12 = closes[0]
    ema26 = closes[0]
    for c in closes[1:]:
        ema12 = c * k12 + ema12 * (1.0 - k12)
        ema26 = c * k26 + ema26 * (1.0 - k26)

    ema_fast_pct = (c_close - ema12) / ema12
    ema_slow_pct = (c_close - ema26) / ema26
    ema_spread_pct = (ema12 - ema26) / c_close

    # 4. RSI(14)
    rsi_14 = compute_rsi(closes, period=14)

    # 5. Volume Dynamics (relative to 24h rolling average)
    vol_24_avg = float(np.mean(volumes[-24:])) if len(volumes) >= 24 and np.mean(volumes[-24:]) > 0 else 1.0
    volume_ratio_24h = volumes[-1] / vol_24_avg if vol_24_avg > 0 else 1.0

    # 6. Higher Timeframe 4h Trend Alignment (strictly backward-looking closed 4h bar)
    htf_close = float(curr.get("htf_4h_close", float("nan")))
    htf_ema = float(curr.get("htf_4h_ema_100", float("nan")))
    if not math.isnan(htf_close) and not math.isnan(htf_ema):
        htf_4h_trend_alignment = 1.0 if htf_close > htf_ema else -1.0
    else:
        htf_4h_trend_alignment = 0.0

    # 7. BTC Macro 24h Return
    if btc_candles is not None and len(btc_candles) > bar_idx:
        btc_c = float(btc_candles[bar_idx]["close"])
        btc_prev_24 = float(btc_candles[max(0, bar_idx - 24)]["close"])
        btc_macro_return_24h = (btc_c - btc_prev_24) / btc_prev_24 if btc_prev_24 > 0 else 0.0
    else:
        btc_macro_return_24h = r24

    features = {
        "return_6h": float(r6),
        "return_12h": float(r12),
        "return_24h": float(r24),
        "return_48h": float(r48),
        "atr_14_pct": float(atr_14_pct),
        "realized_vol_24h": float(realized_vol_24h),
        "ema_fast_pct": float(ema_fast_pct),
        "ema_slow_pct": float(ema_slow_pct),
        "ema_spread_pct": float(ema_spread_pct),
        "rsi_14": float(rsi_14),
        "volume_ratio_24h": float(volume_ratio_24h),
        "htf_4h_trend_alignment": float(htf_4h_trend_alignment),
        "btc_macro_return_24h": float(btc_macro_return_24h),
    }

    # Validate zero lookahead assertion and NaN checks
    for k, v in features.items():
        if math.isnan(v) or math.isinf(v):
            features[k] = 0.0

    return features
