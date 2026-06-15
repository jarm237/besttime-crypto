import math
from btc_scraper.core.sentiment import get_market_sentiment, sentiment_label_vi
from btc_scraper.core.filters import atr_shock_filter
from btc_scraper.ml_engine.signal_score import score_signal
from btc_scraper.regime.market_regime import regime_from_values
from .indicators import *
from .structure import *

REGIME_MULTIPLIERS_MAP = {
    "STRONG_TREND_BULL": {"tp_scale": 1.2, "sl_scale": 0.8},
    "STRONG_TREND_BEAR": {"tp_scale": 1.2, "sl_scale": 0.8},
    "WEAK_TREND_BULL": {"tp_scale": 1.0, "sl_scale": 1.0},
    "WEAK_TREND_BEAR": {"tp_scale": 1.0, "sl_scale": 1.0},
    "RANGING": {"tp_scale": 0.6, "sl_scale": 1.2},
    "HIGH_VOLATILITY": {"tp_scale": 0.8, "sl_scale": 1.5},
    "COMPRESSION": {"tp_scale": 1.1, "sl_scale": 0.9},
    "BREAKOUT": {"tp_scale": 1.3, "sl_scale": 0.8},
    "MEAN_REVERSION": {"tp_scale": 0.7, "sl_scale": 1.1},
    "PANIC_SELL": {"tp_scale": 1.2, "sl_scale": 1.0},
    "PUMP_RISK": {"tp_scale": 0.8, "sl_scale": 1.2},
}

_OPTIMIZED_PARAMS_CACHE = None

def _calculate_position_size(
    base_confidence: float,
    atr_shock: bool,
    weak_signal: bool,
    trend_following_allowed: bool,
    extreme_fear: bool,
    extreme_greed: bool,
    direction: str,
) -> float:
    size = max(0.25, min(1.0, 0.5 + base_confidence * 0.5))
    if weak_signal:
        size *= 0.75
    if atr_shock:
        size *= 0.75
    if not trend_following_allowed:
        size *= 0.8
    if direction == "LONG" and extreme_greed:
        size *= 0.8
    if direction == "SHORT" and extreme_fear:
        size *= 0.8
    if base_confidence < 0.6:
        size *= 0.8
    return round(max(0.25, min(1.0, size)), 2)


def _load_optimized_params():
    global _OPTIMIZED_PARAMS_CACHE
    if _OPTIMIZED_PARAMS_CACHE is not None:
        return _OPTIMIZED_PARAMS_CACHE
    from pathlib import Path
    import json
    cfg_path = Path(__file__).parent.parent / "logs" / "optimized_trading_params.json"
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                _OPTIMIZED_PARAMS_CACHE = json.load(f)
                return _OPTIMIZED_PARAMS_CACHE
        except Exception:
            pass
    _OPTIMIZED_PARAMS_CACHE = {}
    return _OPTIMIZED_PARAMS_CACHE


def calculate_tp_sl(
    close: float,
    signal: str,
    atr: float,
    support: float,
    resistance: float,
    bb_upper: float,
    bb_middle: float,
    bb_lower: float,
    atr_sl_mult: float = 1.2,
    atr_tp_mult: float = 5.0,
    regime: str = None,
) -> dict:
    """
    Tính mức Entry, Take Profit (TP1, TP2) và Stop Loss (SL) dựa trên:
      - ATR (volatility)   : khoảng cách cản bản cho SL và TP
      - Support/Resistance : các mức chốt lời / cắt lỗ tự nhiên
      - Bollinger Bands    : mục tiêu giá trung gian (BB Middle) và xa hơn

    Tỷ lệ R:R được tính cho TP1 (mục tiêu bảo thủ hơn).

    Trả về dict:
      entry, sl, tp1, tp2, rr1 (Risk:Reward cho TP1), rr2, method
    """
    opt_params = _load_optimized_params()
    atr_tp_mult = opt_params.get("atr_tp_mult", atr_tp_mult)
    atr_sl_mult = opt_params.get("atr_sl_mult", atr_sl_mult)

    tp_scale = 1.0
    sl_scale = 1.0
    
    if regime:
        regime_tp_override = opt_params.get("regime_tp_scale", {}).get(regime)
        regime_sl_override = opt_params.get("regime_sl_scale", {}).get(regime)
        
        if regime_tp_override is not None:
            tp_scale = float(regime_tp_override)
        else:
            tp_scale = REGIME_MULTIPLIERS_MAP.get(regime, {}).get("tp_scale", 1.0)
            
        if regime_sl_override is not None:
            sl_scale = float(regime_sl_override)
        else:
            sl_scale = REGIME_MULTIPLIERS_MAP.get(regime, {}).get("sl_scale", 1.0)

    atr_tp_mult = atr_tp_mult * tp_scale
    atr_sl_mult = atr_sl_mult * sl_scale

    is_buy = "BUY" in signal.upper() or "BULLISH" in signal.upper()
    is_sell = "SELL" in signal.upper() or "BEARISH" in signal.upper()

    if atr <= 0 or close <= 0:
        return {"entry": close, "sl": 0.0, "tp1": 0.0, "tp2": 0.0, "rr1": 0.0, "rr2": 0.0, "method": "N/A"}

    entry = close

    if is_buy:
        atr_used = atr
        if atr > 0:
            atr_used = atr
        sl = support - 0.5 * atr_used if support > 0 else entry - atr_sl_mult * atr_used
        sl = max(sl, entry - 3.0 * atr_used)   # SL không xa hơn 3× ATR
        sl = min(sl, entry - 1.2 * atr_used)
        if sl >= entry:
            sl = entry - atr_sl_mult * atr_used

        tp1_bb  = bb_middle if bb_middle > entry else 0.0
        tp1_atr = entry + atr_tp_mult * atr_used
        tp1 = min(tp1_bb, tp1_atr) if tp1_bb > 0 else tp1_atr
        if tp1 <= entry:
            tp1 = entry + atr_tp_mult * atr_used

        tp2_candidates = [x for x in [resistance * 0.998, bb_upper * 0.998, entry + atr_tp_mult * 2 * atr_used] if x > tp1]
        tp2 = min(tp2_candidates) if tp2_candidates else tp1 * 1.01

        method = "ATR+DynamicSL+Support+BB (Long)"

    elif is_sell:
        atr_used = atr
        if atr > 0:
            atr_used = atr
        sl = resistance + 0.5 * atr_used if resistance > 0 else entry + atr_sl_mult * atr_used
        sl = min(sl, entry + 3.0 * atr_used)   # SL không xa hơn 3× ATR
        sl = max(sl, entry + 1.2 * atr_used)
        if sl <= entry:
            sl = entry + atr_sl_mult * atr_used

        tp1_bb  = bb_middle if 0 < bb_middle < entry else 0.0
        tp1_atr = entry - atr_tp_mult * atr_used
        tp1 = max(tp1_bb, tp1_atr) if tp1_bb > 0 else tp1_atr
        if tp1 >= entry:
            tp1 = entry - atr_tp_mult * atr_used

        tp2_candidates = [x for x in [support * 1.002, bb_lower * 1.002, entry - atr_tp_mult * 2 * atr_used] if x < tp1]
        tp2 = max(tp2_candidates) if tp2_candidates else tp1 * 0.99

        method = "ATR+DynamicSL+Resistance+BB (Short)"

    else:
        # NEUTRAL: chỉ tính mức tham chiếu, không có lệnh
        sl  = entry - atr_sl_mult * atr
        tp1 = entry + atr_tp_mult * atr
        tp2 = resistance if resistance > tp1 else tp1 * 1.01
        method = "ATR (Tham chieu - Chua co lenh)"

    # Tỷ lệ Risk:Reward
    risk = abs(entry - sl)
    rr1  = round(abs(tp1 - entry) / risk, 2) if risk > 0 else 0.0
    rr2  = round(abs(tp2 - entry) / risk, 2) if risk > 0 else 0.0

    return {
        "entry": round(entry, 4),
        "sl":    round(sl,    4),
        "tp1":   round(tp1,   4),
        "tp2":   round(tp2,   4),
        "rr1":   rr1,
        "rr2":   rr2,
        "method": method,
    }


def analyze_market(candles: list[dict]) -> dict:
    """
    Phân tích dữ liệu nến của một sàn giao dịch.
    Trả về chỉ số hiện tại (RSI, EMA9, EMA21, SMA50, SMA200, MACD, Bollinger Bands,
    Support/Resistance) và Tín hiệu hành động khuyến nghị.

    Chiến lược tín hiệu (6 lớp lọc):
      Lớp 1 — Trend Filter (SMA 200): Chỉ cho phép BUY khi giá > SMA200.
      Lớp 2 — Pullback to SMA50: Khi giá gãy EMA21 nhưng chạm SMA50, bắt đáy pullback.
      Lớp 3 — EMA Crossover Matrix: EMA9/EMA21 crossover có xác nhận xu hướng từ SMA50.
      Lớp 4 — Chandelier Exit: Bảo vệ khỏi downtrend theo ATR.
      Lớp 5 — Volume & SFP: Xác nhận thanh khoản.
      Lớp 6 — Sentiment Filter (Fear & Greed): Hạ cấp tín hiệu khi thị trường cực đoan.
    """
    if not candles or "error" in candles[0]:
        return {
            "rsi": 50.0,
            "ema9": 0.0,
            "ema21": 0.0,
            "sma50": 0.0,
            "sma200": 0.0,
            "macd": 0.0,
            "macd_signal": 0.0,
            "macd_hist": 0.0,
            "bb_upper": 0.0,
            "bb_middle": 0.0,
            "bb_lower": 0.0,
            "atr": 0.0,
            "support": 0.0,
            "resistance": 0.0,
            "tp_sl": {"entry": 0.0, "sl": 0.0, "tp1": 0.0, "tp2": 0.0, "rr1": 0.0, "rr2": 0.0, "method": "N/A"},
            "signal": "ERROR",
            "reason": "Khong co du lieu de phan tich",
            "history": []
        }
        
    close_prices = [c["close"] for c in candles]

    rsi_list = calculate_rsi(close_prices, 14)
    ema9_list = calculate_ema(close_prices, 9)
    ema21_list = calculate_ema(close_prices, 21)
    sma50_list = calculate_sma(close_prices, 50)
    sma200_list = calculate_sma(close_prices, 200)
    macd_list, macd_sig_list, macd_hist_list = calculate_macd(close_prices, 12, 26, 9)
    bb_up_list, bb_mid_list, bb_low_list = calculate_bollinger_bands(close_prices, 20, 2)
    atr_list = calculate_atr(candles, 14)
    atr_ma_list = calculate_sma(atr_list, 14)
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    adx_list = calculate_adx(highs, lows, close_prices, 14)
    choppiness_list = calculate_choppiness_index(highs, lows, close_prices, 14)
    vol_sma_list = calculate_volume_sma(candles, 20)
    obv_list = _calculate_obv(candles)
    cmf_list = _calculate_cmf(highs, lows, close_prices, [c.get("volume", 0.0) for c in candles], period=20)
    mfi_list = _calculate_mfi(highs, lows, close_prices, [c.get("volume", 0.0) for c in candles], period=14)
    chandelier_list = calculate_chandelier_exit(candles, period=22, multiplier=3.0)
    sentiment_data = get_market_sentiment()
    sentiment_score = sentiment_data["score"]
    sentiment_label = sentiment_data["label"]
    sentiment_raw = sentiment_data["raw_value"]

    # Ghi lại chỉ số vào nến để hiển thị
    for i, c in enumerate(candles):
        current_close = close_prices[i]
        c["rsi"] = rsi_list[i]
        c["ema9"] = ema9_list[i]
        c["ema21"] = ema21_list[i]
        c["sma50"] = sma50_list[i]
        c["sma200"] = sma200_list[i]
        c["macd"] = macd_list[i]
        c["macd_signal"] = macd_sig_list[i]
        c["macd_hist"] = macd_hist_list[i]
        c["bb_upper"] = bb_up_list[i]
        c["bb_middle"] = bb_mid_list[i]
        c["bb_lower"] = bb_low_list[i]
        c["atr"] = atr_list[i] if i < len(atr_list) else 0.0
        c["atr_ma"] = atr_ma_list[i] if i < len(atr_ma_list) else 0.0
        c["adx"] = adx_list[i] if i < len(adx_list) else 0.0
        c["choppiness"] = choppiness_list[i] if i < len(choppiness_list) else 0.0
        c["atr_shock"] = (
            c["atr"] > 0
            and c["atr_ma"] > 0
            and c["atr"] > c["atr_ma"] * 1.8
        )
        c["market_regime"] = (
            "TRENDING"
            if is_trend_following_allowed(c["adx"], c["choppiness"])
            else "SIDEWAY"
        )
        atr_pct = (c["atr"] / current_close * 100.0) if current_close and c["atr"] else 0.0
        regime_info = regime_from_values(
            current_close,
            c["sma200"],
            c["ema21"],
            c["sma50"],
            c["adx"],
            atr_pct,
        )
        c["regime"] = regime_info.get("regime")
        c["regime_confidence"] = regime_info.get("confidence")
        c["obv"] = obv_list[i]
        c["cmf"] = cmf_list[i]
        c["mfi"] = mfi_list[i]
        c["return_15m"] = _lookback_return(close_prices, i, 1)
        c["return_1h"] = _lookback_return(close_prices, i, 4)
        c["return_4h"] = _lookback_return(close_prices, i, 16)
        c["return_1d"] = _lookback_return(close_prices, i, 96)
        c["ema9_slope"] = _calculate_slope(ema9_list, i, 4)
        c["ema21_slope"] = _calculate_slope(ema21_list, i, 4)
        c["sma50_slope"] = _calculate_slope(sma50_list, i, 8)
        c["sma200_slope"] = _calculate_slope(sma200_list, i, 16)
        
        current_high = c["high"]
        current_low = c["low"]
        current_sma200 = sma200_list[i]
        c["ema_distance_pct"] = ((ema9_list[i] - ema21_list[i]) / current_close * 100.0) if current_close else 0.0
        window_start = max(0, i - 50)
        ema_diff_window = [((ema9_list[j] - ema21_list[j]) / close_prices[j] * 100.0) for j in range(window_start, i + 1) if close_prices[j] > 0]
        if ema_diff_window:
            mean_diff = sum(ema_diff_window) / len(ema_diff_window)
            std_diff = math.sqrt(sum((x - mean_diff) ** 2 for x in ema_diff_window) / len(ema_diff_window))
            c["ema_distance_zscore"] = ((c["ema_distance_pct"] - mean_diff) / std_diff) if std_diff > 0 else 0.0
        else:
            c["ema_distance_zscore"] = 0.0
        c["realized_vol_20"] = _calculate_realized_volatility(close_prices, i, 20)
        c["realized_vol_50"] = _calculate_realized_volatility(close_prices, i, 50)
        atr_window = [x for x in atr_list[max(0, i - 50) : i + 1] if x > 0]
        c["atr_percentile"] = _percentile_rank(c["atr"], atr_window)
        current_volume = candles[i].get("volume", 0.0)
        current_vol_sma = vol_sma_list[i]
        c["volume_acceleration"] = ((current_volume - current_vol_sma) / current_vol_sma) if current_vol_sma > 0 else 0.0
        vol_window = [candles[j].get("volume", 0.0) for j in range(max(0, i - 100), i + 1)]
        c["volume_percentile"] = _percentile_rank(current_volume, vol_window)
        structure_window = candles[max(0, i - 20) : i]
        support = min(cand["low"] for cand in structure_window) if structure_window else 0.0
        resistance = max(cand["high"] for cand in structure_window) if structure_window else 0.0
        c["distance_support_pct"] = ((current_close - support) / current_close * 100.0) if current_close else 0.0
        c["distance_resistance_pct"] = ((resistance - current_close) / current_close * 100.0) if current_close else 0.0
        c["higher_high"] = 1.0 if current_high > resistance else 0.0
        c["lower_low"] = 1.0 if current_low < support else 0.0
        c["market_structure_break"] = 1.0 if current_close > resistance or current_close < support else 0.0
        c["volatility_regime_compression"] = 1.0 if (c["atr_percentile"] <= 25.0 and c["adx"] < 20.0) else 0.0
        c["volatility_regime_breakout"] = 1.0 if (c["atr_percentile"] >= 75.0 and c["adx"] >= 30.0 and c["market_structure_break"] == 1.0) else 0.0
        c["volatility_regime_mean_reversion"] = 1.0 if (c["atr_percentile"] >= 60.0 and c["adx"] < 25.0) else 0.0
        c["volatility_regime_panic_sell"] = 1.0 if (c["atr_percentile"] >= 80.0 and current_close < current_sma200 and c["adx"] >= 25.0) else 0.0
        c["volatility_regime_low_liquidity"] = 1.0 if c["volume_percentile"] <= 20.0 else 0.0
        c["volatility_regime_pump_risk"] = 1.0 if (c["volume_percentile"] >= 90.0 and c["atr_percentile"] >= 70.0 and c["adx"] >= 25.0) else 0.0
        c["vol_sma20"] = current_vol_sma
        c["chandelier"] = chandelier_list[i]

    def _evaluate_candle_signal(t: int):
        current_rsi = rsi_list[t]
        current_ema9 = ema9_list[t]
        current_ema21 = ema21_list[t]
        current_sma50 = sma50_list[t]
        current_sma200 = sma200_list[t]
        current_macd = macd_list[t]
        current_macd_signal = macd_sig_list[t]
        current_macd_hist = macd_hist_list[t]
        current_bb_upper = bb_up_list[t]
        current_bb_middle = bb_mid_list[t]
        current_bb_lower = bb_low_list[t]
        current_atr = atr_list[t] if t < len(atr_list) and t >= -len(atr_list) else 0.0
        current_atr_ma = atr_ma_list[t] if t < len(atr_ma_list) and t >= -len(atr_ma_list) else 0.0
        current_adx = adx_list[t] if t < len(adx_list) and t >= -len(adx_list) else 0.0
        current_choppiness = choppiness_list[t] if t < len(choppiness_list) and t >= -len(choppiness_list) else 0.0
        current_close = close_prices[t]
        current_open  = candles[t]["open"]
        current_high  = candles[t]["high"]
        current_low   = candles[t]["low"]
        current_volume = candles[t].get("volume", 0.0)
        current_vol_sma = vol_sma_list[t]
        chandelier_state = chandelier_list[t]

        prev_rsi = rsi_list[t-1] if t >= -len(candles) + 1 else current_rsi
        rsi_turning_up   = (prev_rsi <= 30) and (current_rsi > 30)
        rsi_turning_down = (prev_rsi >= 70) and (current_rsi < 70)

        vol_spike = (current_vol_sma > 0) and (current_volume > current_vol_sma * 1.3)

        above_sma200 = (current_sma200 > 0) and (current_close > current_sma200)
        below_sma200 = (current_sma200 > 0) and (current_close < current_sma200)

        sma50_prev5   = sma50_list[t-5] if t >= -len(candles) + 5 else 0.0
        sma50_uptrend   = (current_sma50 > 0) and (current_sma50 > sma50_prev5)
        sma50_downtrend = (current_sma50 > 0) and (current_sma50 < sma50_prev5)
        above_sma50 = (current_sma50 > 0) and (current_close > current_sma50)

        sma50_lower_bound = current_sma50 * 0.99
        in_pullback_zone = (
            current_sma50 > 0
            and current_ema21 > 0
            and sma50_lower_bound <= current_close <= current_ema21
        )
        is_bullish_candle = current_close > current_open

        prev_in_pullback_zone = False
        if t >= -len(candles) + 1:
            prev_close = close_prices[t-1]
            prev_sma50 = sma50_list[t-1]
            prev_ema21 = ema21_list[t-1]
            prev_in_pullback_zone = (
                prev_sma50 > 0
                and prev_ema21 > 0
                and prev_sma50 * 0.99 <= prev_close <= prev_ema21
            )

        # Tính toán support / resistance
        idx = t if t >= 0 else len(candles) + t
        recent_candles = candles[max(0, idx - 50):idx] if idx > 0 else []
        support = min(c["low"] for c in recent_candles) if recent_candles else 0.0
        resistance = max(c["high"] for c in recent_candles) if recent_candles else 0.0

        sfp_bull = is_bullish_sfp(
            current_high,
            current_low,
            current_close,
            current_open,
            support,
            current_volume,
            current_vol_sma,
            current_rsi,
        )
        sfp_bear = is_bearish_sfp(
            current_high,
            current_low,
            current_close,
            current_open,
            resistance,
            current_volume,
            current_vol_sma,
            current_rsi,
        )

        prev_ema9 = ema9_list[t-1] if t >= -len(candles) + 1 else current_ema9
        prev_ema21 = ema21_list[t-1] if t >= -len(candles) + 1 else current_ema21
        ema_golden_cross = (prev_ema9 <= prev_ema21) and (current_ema9 > current_ema21)
        ema_death_cross  = (prev_ema9 >= prev_ema21) and (current_ema9 < current_ema21)
        ema_bearish_active = current_ema9 < current_ema21

        chandelier_blocks_buy = (chandelier_state == "BEAR")
        trend_following_allowed = is_trend_following_allowed(current_adx, current_choppiness)
        current_atr_shock = atr_shock_filter(current_atr, current_atr_ma)
        trend_label = (
            "BULL"
            if above_sma200 and chandelier_state == "BULL"
            else "BEAR"
            if below_sma200 and chandelier_state == "BEAR"
            else "NEUTRAL"
        )

        # Lớp 6 — Sentiment modifier (không chặn tín hiệu mạnh)
        sentiment_note = f" | Sentiment: {sentiment_raw}/100 ({sentiment_label_vi(sentiment_label)})"
        extreme_fear = sentiment_score < -0.6
        extreme_greed = sentiment_score > 0.6
        base_confidence = 0.55
        if above_sma200 and chandelier_state == "BULL":
            base_confidence += 0.15
        if below_sma200 and chandelier_state == "BEAR":
            base_confidence += 0.15
        if current_adx >= 20 and current_choppiness <= 62:
            base_confidence += 0.05
        if current_adx < 20 or current_choppiness > 62:
            base_confidence -= 0.05

        def finalize(sig: str, reason: str):
            tp_sl = calculate_tp_sl(
                close=current_close,
                signal=sig,
                atr=current_atr,
                support=support,
                resistance=resistance,
                bb_upper=current_bb_upper,
                bb_middle=current_bb_middle,
                bb_lower=current_bb_lower,
                regime=candles[t].get("regime") if (t < len(candles) and t >= -len(candles)) else None,
            )
            direction = "SHORT" if "SELL" in sig.upper() or "SHORT" in sig.upper() else ("LONG" if "BUY" in sig.upper() or "BULL" in sig.upper() else None)
            confidence = max(0.0, min(1.0, base_confidence))
            position_size = 1.0

            if direction == "SHORT" and trend_label == "BEAR" and extreme_fear:
                confidence = max(0.0, confidence - 0.1)
                position_size *= 0.8
            elif direction == "LONG" and trend_label == "BULL" and extreme_greed:
                confidence = max(0.0, confidence - 0.1)
                position_size *= 0.8
            elif direction == "LONG" and trend_label == "BULL":
                confidence = min(1.0, confidence + 0.05)
            elif direction == "SHORT" and trend_label == "BEAR":
                confidence = min(1.0, confidence + 0.05)

            if current_atr_shock:
                confidence = max(0.0, confidence - 0.1)
                position_size *= 0.75
                if "STRONG" not in sig and "NEUTRAL" not in sig:
                    if "BUY" in sig and "WEAK" not in sig:
                        sig = sig.replace("BUY", "WEAK BUY")
                    elif "SELL" in sig and "WEAK" not in sig:
                        sig = sig.replace("SELL", "WEAK SELL")
                    reason += " | ATR Shock: bien dong lon, giam quy mo"
                else:
                    reason += " | ATR Shock: bien dong lon, giam quy mo"

            if "WEAK" in sig.upper() or "NEUTRAL" in sig.upper():
                position_size *= 0.75

            if not trend_following_allowed and "CROSSOVER" in sig.upper():
                confidence = max(0.0, confidence - 0.1)
                position_size *= 0.8
                reason += " | Trend-following block: ADX hoac Choppiness khong hop le"

            if not trend_following_allowed and any(x in sig.upper() for x in ["PULLBACK-ZONE", "SFP-LIQUIDITY-SWEEP", "BREAK-SMA50"]):
                confidence = max(0.0, confidence - 0.1)
                position_size *= 0.85
                reason += " | Market regime SIDEWAY: tien hanh can than"

            if confidence < 0.6:
                position_size = max(position_size * 0.8, 0.25)

            position_size = round(max(0.25, min(1.0, position_size)), 2)

            data = {
                "rsi": current_rsi,
                "ema9": current_ema9,
                "ema21": current_ema21,
                "sma50": current_sma50,
                "sma200": current_sma200,
                "macd": current_macd,
                "macd_signal": current_macd_signal,
                "macd_hist": current_macd_hist,
                "bb_upper": current_bb_upper,
                "bb_middle": current_bb_middle,
                "bb_lower": current_bb_lower,
                "atr": current_atr,
                "atr_ma": current_atr_ma,
                "adx": current_adx,
                "choppiness": current_choppiness,
                "atr_shock": current_atr_shock,
                "support": support,
                "resistance": resistance,
                "confidence": round(confidence, 2),
                "position_size": round(position_size, 2),
                "market_regime": "TRENDING" if trend_following_allowed else "SIDEWAY",
                "regime": c.get("regime"),
                "regime_confidence": c.get("regime_confidence"),
                "trend_following_allowed": trend_following_allowed,
                "trend_label": trend_label,
                "volume": current_volume,
                "vol_sma20": current_vol_sma,
                "obv": c["obv"],
                "cmf": c["cmf"],
                "mfi": c["mfi"],
                "return_15m": c["return_15m"],
                "return_1h": c["return_1h"],
                "return_4h": c["return_4h"],
                "return_1d": c["return_1d"],
                "ema9_slope": c["ema9_slope"],
                "ema21_slope": c["ema21_slope"],
                "sma50_slope": c["sma50_slope"],
                "sma200_slope": c["sma200_slope"],
                "ema_distance_pct": c["ema_distance_pct"],
                "ema_distance_zscore": c["ema_distance_zscore"],
                "realized_vol_20": c["realized_vol_20"],
                "realized_vol_50": c["realized_vol_50"],
                "atr_percentile": c["atr_percentile"],
                "volatility_regime_compression": c["volatility_regime_compression"],
                "volatility_regime_breakout": c["volatility_regime_breakout"],
                "volatility_regime_mean_reversion": c["volatility_regime_mean_reversion"],
                "volatility_regime_panic_sell": c["volatility_regime_panic_sell"],
                "volatility_regime_low_liquidity": c["volatility_regime_low_liquidity"],
                "volatility_regime_pump_risk": c["volatility_regime_pump_risk"],
                "distance_support_pct": c["distance_support_pct"],
                "distance_resistance_pct": c["distance_resistance_pct"],
                "higher_high": c["higher_high"],
                "lower_low": c["lower_low"],
                "market_structure_break": c["market_structure_break"],
                "volume_acceleration": c["volume_acceleration"],
                "volume_percentile": c["volume_percentile"],
            }
            context = {
                "chandelier": chandelier_state,
                "above_sma200": above_sma200,
                "below_sma200": below_sma200,
                "sma50_uptrend": sma50_uptrend,
                "sma50_downtrend": sma50_downtrend,
                "above_sma50": above_sma50,
                "in_pullback_zone": in_pullback_zone,
                "vol_spike": vol_spike,
                "sfp_bull": sfp_bull,
                "sfp_bear": sfp_bear,
                "rsi_turning_up": rsi_turning_up,
                "rsi_turning_down": rsi_turning_down,
                "sentiment_score": sentiment_score,
                "sentiment_label": sentiment_label,
                "sentiment_raw": sentiment_raw,
                "market_regime": "TRENDING" if trend_following_allowed else "SIDEWAY",
                "trend_label": trend_label,
                "adx": current_adx,
                "choppiness": current_choppiness,
                "trend_following_allowed": trend_following_allowed,
            }
            return sig, reason, tp_sl, data, context

        if rsi_turning_up:
            vol_note = " + Volume Spike (dong tien lon do day)" if vol_spike else " (volume trung binh - can them xac nhan)"
            if above_sma200 and not chandelier_blocks_buy:
                sig = "STRONG BUY (Confirmed Reversal)"
                reason = f"RSI cat len tren 30 (dao chieu tu Oversold){vol_note} | Tren SMA200"
                if extreme_fear:
                    reason += f" | {sentiment_note}"
                return finalize(sig, reason)
            else:
                # Counter-Trend khi không có xác nhận xu hướng: chuyển thành NEUTRAL
                # (backtest cho thấy win rate <43% và avg PnL âm)
                return finalize("NEUTRAL (CT-Unconfirmed)", f"RSI dao chieu tu Oversold{vol_note} NHUNG thieu xac nhan (Chandelier=BEAR hoac ben duoi SMA200) — bo qua")

        if rsi_turning_down:
            vol_note = " + Volume Spike (xa hang manh)" if vol_spike else " (volume trung binh)"
            sig = "STRONG SELL (Confirmed Reversal)"
            reason = f"RSI cat xuong duoi 70 (dao chieu tu Overbought){vol_note}" + (" | Ben tren SMA200 - co the chi la dieu chinh" if above_sma200 else "")
            if extreme_greed:
                reason += f" | {sentiment_note}"
            return finalize(sig, reason)

        if sfp_bull and not chandelier_blocks_buy:
            return finalize("BUY (SFP-Liquidity-Sweep)", f"Quet thanh khoan day: wick xuyen SL duoi {support:.2f} roi dong cua tren support | RSI={current_rsi:.1f}" + (" | Bull Market (SMA200 xac nhan)" if above_sma200 else " | Bear Market - rui ro cao hon"))

        if sfp_bear:
            return finalize("SELL (SFP-Liquidity-Sweep)", f"Quet thanh khoan dinh: wick vuot {resistance:.2f} roi dong cua duoi resistance | RSI={current_rsi:.1f}" + (" | Bear Market (SMA200 xac nhan)" if below_sma200 else " | Bull Market - co the chi la fakeout"))

        if ema_golden_cross:
            if not trend_following_allowed:
                return finalize(
                    "NEUTRAL (Trend-Blocked)",
                    "EMA9 cat len EMA21 nhung ADX < 20 hoac Choppiness cao, bo qua trend-following"
                )
            if chandelier_blocks_buy:
                return finalize(
                    "WEAK BUY (Crossover-Blocked)",
                    "EMA9 cat len EMA21 NHUNG Chandelier=BEAR — thi truong dang downtrend theo ATR, chu y!"
                )
            if above_sma200:
                sig = "BUY (Crossover)"
                reason = "EMA9 cat len EMA21 + Chandelier=BULL + Gia tren SMA200 (Bull Market confirmed)"
                if extreme_fear:
                    sig = "WEAK BUY (Crossover-Sentiment)"
                    reason += f" | NHUNG{sentiment_note} — Thi truong dang trong vung so hai cuc do!"
                return finalize(sig, reason)
            elif current_sma200 > 0:
                # WEAK BUY below SMA200: xác suất thấp, bỏ qua
                return finalize("NEUTRAL (Crossover-BearMkt)", "EMA9 cat len EMA21 NHUNG gia duoi SMA200 — co the la bull trap, bo qua")
            else:
                return finalize("BUY (Crossover)", "EMA9 cat len EMA21 (Xu huong tang — chua du du lieu SMA200)" + sentiment_note)

        if ema_death_cross:
            if not trend_following_allowed:
                return finalize(
                    "NEUTRAL (Trend-Blocked)",
                    "EMA9 cat xuong EMA21 nhung ADX < 20 hoac Choppiness cao, bo qua trend-following"
                )
            if below_sma200:
                return finalize("SELL (Crossover)", "EMA9 cat xuong EMA21 + Gia duoi SMA200 (Bear Market confirmed)")
            elif current_sma200 > 0:
                return finalize("WEAK SELL (Crossover)", "EMA9 cat xuong EMA21 NHUNG gia tren SMA200 — co the chi la dieu chinh")
            else:
                return finalize("SELL (Crossover)", "EMA9 cat xuong EMA21 (Xu huong giam — chua du du lieu SMA200)")

        if (ema_bearish_active and in_pullback_zone and not prev_in_pullback_zone and is_bullish_candle and sma50_uptrend and above_sma200 and not chandelier_blocks_buy and current_rsi < 55):
            return finalize("BUY (Pullback-Zone)", f"Gia dieu chinh vao vung EMA21({current_ema21:.2f})-SMA50({current_sma50:.2f}), nen xanh xac nhan | SMA50 doc len | SMA200 phia duoi | Chandelier=BULL")

        prev_above_sma50 = (sma50_list[t-1] > 0) and (close_prices[t-1] > sma50_list[t-1]) if t >= -len(candles) + 1 else False
        if (ema_bearish_active and not above_sma50 and prev_above_sma50 and sma50_downtrend and below_sma200 and current_sma50 > 0):
            return finalize("SELL (Break-SMA50)", f"Gia XUYEN THU'NG SMA50 ({current_sma50:.2f}) trong Bear Market (duoi SMA200) — trailing stop kich hoat!")

        chandelier_tag = f" | Chandelier={chandelier_state}"
        if current_ema9 > current_ema21:
            if above_sma200 and sma50_uptrend and not chandelier_blocks_buy:
                return finalize("NEUTRAL (BULLISH)", f"Xu huong tang manh: EMA9>EMA21, tren SMA50+SMA200{chandelier_tag}")
            elif above_sma200:
                return finalize("NEUTRAL (BULLISH)", f"Xu huong tang: EMA9>EMA21, tren SMA200 (SMA50 chua xac nhan){chandelier_tag}")
            else:
                return finalize("NEUTRAL (BULLISH-CAUTION)", f"EMA9>EMA21 nhung duoi SMA200 — thi truong lon van giam{chandelier_tag}")
        else:
            if below_sma200 and sma50_downtrend:
                return finalize("NEUTRAL (BEARISH)", f"Xu huong giam manh: EMA9<EMA21, duoi SMA50+SMA200{chandelier_tag}")
            elif below_sma200:
                return finalize("NEUTRAL (BEARISH)", f"Xu huong giam: EMA9<EMA21, duoi SMA200{chandelier_tag}")
            else:
                return finalize("NEUTRAL (BEARISH-CAUTION)", f"EMA9<EMA21 nhung tren SMA200 — co the chi la dieu chinh ngan han{chandelier_tag}")

    # Đánh giá tín hiệu hiện hành
    current_sig, current_reason, current_tp_sl, current_data, trend_context = _evaluate_candle_signal(-1)

    history = []
    for c in candles[-8:]:
        history.append({
            "time": c["time"], "open": c["open"], "high": c["high"],
            "low": c["low"], "close": c["close"], "volume": c["volume"],
            "rsi": c["rsi"], "ema9": c["ema9"], "ema21": c["ema21"],
            "sma50": c["sma50"], "sma200": c["sma200"], "macd": c["macd"],
            "macd_signal": c["macd_signal"], "macd_hist": c["macd_hist"],
            "bb_upper": c["bb_upper"], "bb_middle": c["bb_middle"], "bb_lower": c["bb_lower"]
        })

    # Quét tín hiệu bỏ lỡ (dùng chung 1 logic hàm chuẩn)
    missed_signals = []
    current_close = close_prices[-1]
    for offset in [-2, -3]:
        if len(candles) < abs(offset) + 50:
            continue
        
        t = offset
        past_sig, past_reason, past_tp_sl, past_data, _ = _evaluate_candle_signal(t)
        
        # Chỉ xét tín hiệu Mua/Bán rõ ràng, loại bỏ NEUTRAL và WEAK
        if ("BUY" in past_sig and "WEAK" not in past_sig) or ("SELL" in past_sig and "WEAK" not in past_sig):
            idx = len(candles) + t
            past_time = candles[idx]["time"]
            age_min = abs(offset) * 15
            past_close = close_prices[idx]
            
            sl_level = past_tp_sl["sl"]
            tp1_level = past_tp_sl["tp1"]
            tp2_level = past_tp_sl["tp2"]
            
            status = "Running (Van con hieu luc)"
            if "BUY" in past_sig:
                if current_close <= sl_level:
                    status = "Hit SL (Da can SL)"
                elif current_close >= tp2_level:
                    status = "Hit TP2 (Da dat TP2)"
                elif current_close >= tp1_level:
                    status = "Hit TP1 (Da dat TP1)"
            elif "SELL" in past_sig:
                if current_close >= sl_level:
                    status = "Hit SL (Da can SL)"
                elif current_close <= tp2_level:
                    status = "Hit TP2 (Da dat TP2)"
                elif current_close <= tp1_level:
                    status = "Hit TP1 (Da dat TP1)"
                    
            missed_signals.append({
                "time": past_time,
                "age_minutes": age_min,
                "signal": past_sig,
                "entry": past_close,
                "tp_sl": past_tp_sl,
                "reason": past_reason,
                "status": status
            })

    res = {
        **current_data,
        "history": history,
        "missed_signals": missed_signals,
        "signal": current_sig,
        "reason": current_reason,
        "tp_sl": current_tp_sl,
        "trend_context": trend_context,
        "sentiment": {
            "score": sentiment_score,
            "label": sentiment_label,
            "raw_value": sentiment_raw,
        },
    }
    # Attach scoring metadata (phase 1-5 basic implementation). Keep backward compatibility.
    try:
        htf_trend = res.get("htf_trend") or trend_context.get("trend_label") or ""
        res["signal_score"] = score_signal(current_sig, res, trend_context, htf_trend=htf_trend)
    except Exception:
        res["signal_score"] = {"action": current_sig, "score": 50, "confidence": "LOW", "position_size": 0.5}

    return res


def analyze_all_market(candles: list[dict], sentiment_map: dict = None) -> list[dict]:
    """
    Phân tích toàn bộ dữ liệu lịch sử nến và tạo danh sách kết quả phân tích cho từng nến.
    Dùng cho backtesting hiệu năng cao (O(N) thay vì O(N^2)).
    """
    if not candles or "error" in candles[0]:
        return []

    close_prices = [c["close"] for c in candles]
    n = len(candles)
    if n < 200:
        return []

    # Tính toán toàn bộ chỉ báo một lần duy nhất
    rsi_list = calculate_rsi(close_prices, 14)
    ema9_list = calculate_ema(close_prices, 9)
    ema21_list = calculate_ema(close_prices, 21)
    sma50_list = calculate_sma(close_prices, 50)
    sma200_list = calculate_sma(close_prices, 200)
    macd_list, macd_sig_list, macd_hist_list = calculate_macd(close_prices, 12, 26, 9)
    bb_up_list, bb_mid_list, bb_low_list = calculate_bollinger_bands(close_prices, 20, 2)
    atr_list = calculate_atr(candles, 14)
    atr_ma_list = calculate_sma(atr_list, 14)
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    adx_list = calculate_adx(highs, lows, close_prices, 14)
    choppiness_list = calculate_choppiness_index(highs, lows, close_prices, 14)
    vol_sma_list = calculate_volume_sma(candles, 20)
    obv_list = _calculate_obv(candles)
    cmf_list = _calculate_cmf(highs, lows, close_prices, [c.get("volume", 0.0) for c in candles], period=20)
    mfi_list = _calculate_mfi(highs, lows, close_prices, [c.get("volume", 0.0) for c in candles], period=14)
    chandelier_list = calculate_chandelier_exit(candles, period=22, multiplier=3.0)
    # Global market sentiment (reused for all coins / candles in this historical run)
    sentiment_data = get_market_sentiment()
    sentiment_score = sentiment_data.get("score")
    sentiment_label = sentiment_data.get("label")
    sentiment_raw = sentiment_data.get("raw_value")

    # Đưa các chỉ báo vào nến
    for i in range(n):
        candles[i]["rsi"] = rsi_list[i]
        candles[i]["ema9"] = ema9_list[i]
        candles[i]["ema21"] = ema21_list[i]
        candles[i]["sma50"] = sma50_list[i]
        candles[i]["sma200"] = sma200_list[i]
        candles[i]["macd"] = macd_list[i]
        candles[i]["macd_signal"] = macd_sig_list[i]
        candles[i]["macd_hist"] = macd_hist_list[i]
        candles[i]["bb_upper"] = bb_up_list[i]
        candles[i]["bb_middle"] = bb_mid_list[i]
        candles[i]["bb_lower"] = bb_low_list[i]
        candles[i]["atr"] = atr_list[i] if i < len(atr_list) else 0.0
        candles[i]["atr_ma"] = atr_ma_list[i] if i < len(atr_ma_list) else 0.0
        candles[i]["adx"] = adx_list[i] if i < len(adx_list) else 0.0
        candles[i]["choppiness"] = choppiness_list[i] if i < len(choppiness_list) else 0.0
        candles[i]["atr_shock"] = candles[i]["atr"] > 0 and candles[i]["atr_ma"] > 0 and candles[i]["atr"] > candles[i]["atr_ma"] * 1.8
        candles[i]["market_regime"] = (
            "TRENDING"
            if is_trend_following_allowed(candles[i]["adx"], candles[i]["choppiness"])
            else "SIDEWAY"
        )
        candles[i]["vol_sma20"] = vol_sma_list[i]
        candles[i]["chandelier"] = chandelier_list[i]
        candles[i]["obv"] = obv_list[i]
        candles[i]["cmf"] = cmf_list[i]
        candles[i]["mfi"] = mfi_list[i]
        candles[i]["return_15m"] = _lookback_return(close_prices, i, 1)
        candles[i]["return_1h"] = _lookback_return(close_prices, i, 4)
        candles[i]["return_4h"] = _lookback_return(close_prices, i, 16)
        candles[i]["return_1d"] = _lookback_return(close_prices, i, 96)
        candles[i]["ema9_slope"] = _calculate_slope(ema9_list, i, 4)
        candles[i]["ema21_slope"] = _calculate_slope(ema21_list, i, 4)
        candles[i]["sma50_slope"] = _calculate_slope(sma50_list, i, 8)
        candles[i]["sma200_slope"] = _calculate_slope(sma200_list, i, 16)
        current_close = close_prices[i]
        current_high = candles[i]["high"]
        current_low = candles[i]["low"]
        candles[i]["ema_distance_pct"] = ((ema9_list[i] - ema21_list[i]) / current_close * 100.0) if current_close else 0.0
        window_start = max(0, i - 50)
        ema_diff_window = [((ema9_list[j] - ema21_list[j]) / close_prices[j] * 100.0) for j in range(window_start, i + 1) if close_prices[j] > 0]
        if ema_diff_window:
            mean_diff = sum(ema_diff_window) / len(ema_diff_window)
            std_diff = math.sqrt(sum((x - mean_diff) ** 2 for x in ema_diff_window) / len(ema_diff_window))
            candles[i]["ema_distance_zscore"] = ((candles[i]["ema_distance_pct"] - mean_diff) / std_diff) if std_diff > 0 else 0.0
        else:
            candles[i]["ema_distance_zscore"] = 0.0
        candles[i]["realized_vol_20"] = _calculate_realized_volatility(close_prices, i, 20)
        candles[i]["realized_vol_50"] = _calculate_realized_volatility(close_prices, i, 50)
        atr_window = [x for x in atr_list[max(0, i - 50) : i + 1] if x > 0]
        candles[i]["atr_percentile"] = _percentile_rank(candles[i]["atr"], atr_window)
        current_volume = candles[i].get("volume", 0.0)
        current_vol_sma = vol_sma_list[i]
        candles[i]["volume_acceleration"] = ((current_volume - current_vol_sma) / current_vol_sma) if current_vol_sma > 0 else 0.0
        vol_window = [candles[j].get("volume", 0.0) for j in range(max(0, i - 100), i + 1)]
        candles[i]["volume_percentile"] = _percentile_rank(current_volume, vol_window)
        structure_window = candles[max(0, i - 20) : i]
        support = min(cand["low"] for cand in structure_window) if structure_window else 0.0
        resistance = max(cand["high"] for cand in structure_window) if structure_window else 0.0
        candles[i]["distance_support_pct"] = ((current_close - support) / current_close * 100.0) if current_close else 0.0
        candles[i]["distance_resistance_pct"] = ((resistance - current_close) / current_close * 100.0) if current_close else 0.0
        candles[i]["higher_high"] = 1.0 if current_high > resistance else 0.0
        candles[i]["lower_low"] = 1.0 if current_low < support else 0.0
        candles[i]["market_structure_break"] = 1.0 if current_close > resistance or current_close < support else 0.0
        candles[i]["volatility_regime_compression"] = 1.0 if (candles[i]["atr_percentile"] <= 25.0 and candles[i]["adx"] < 20.0) else 0.0
        candles[i]["volatility_regime_breakout"] = 1.0 if (candles[i]["atr_percentile"] >= 75.0 and candles[i]["adx"] >= 30.0 and candles[i]["market_structure_break"] == 1.0) else 0.0
        candles[i]["volatility_regime_mean_reversion"] = 1.0 if (candles[i]["atr_percentile"] >= 60.0 and candles[i]["adx"] < 25.0) else 0.0
        candles[i]["volatility_regime_panic_sell"] = 1.0 if (candles[i]["atr_percentile"] >= 80.0 and current_close < candles[i]["sma200"] and candles[i]["adx"] >= 25.0) else 0.0
        candles[i]["volatility_regime_low_liquidity"] = 1.0 if candles[i]["volume_percentile"] <= 20.0 else 0.0
        candles[i]["volatility_regime_pump_risk"] = 1.0 if (candles[i]["volume_percentile"] >= 90.0 and candles[i]["atr_percentile"] >= 70.0 and candles[i]["adx"] >= 25.0) else 0.0
        candles[i]["regime"] = regime_from_values(current_close, candles[i]["sma200"], candles[i]["ema21"], candles[i]["sma50"], candles[i]["adx"], candles[i]["atr_percentile"]).get("regime")
        candles[i]["regime_confidence"] = regime_from_values(current_close, candles[i]["sma200"], candles[i]["ema21"], candles[i]["sma50"], candles[i]["adx"], candles[i]["atr_percentile"]).get("confidence")

    results = []

    # Chạy từ 200 nến để đủ dữ liệu SMA200
    for i in range(200, n):
        current_rsi = rsi_list[i]
        current_ema9 = ema9_list[i]
        current_ema21 = ema21_list[i]
        current_sma50 = sma50_list[i]
        current_sma200 = sma200_list[i]
        current_macd = macd_list[i]
        current_macd_signal = macd_sig_list[i]
        current_macd_hist = macd_hist_list[i]
        current_bb_upper = bb_up_list[i]
        current_bb_middle = bb_mid_list[i]
        current_bb_lower = bb_low_list[i]
        current_atr = atr_list[i]
        current_atr_ma = atr_ma_list[i]
        current_adx = adx_list[i] if i < len(adx_list) else 0.0
        current_choppiness = choppiness_list[i] if i < len(choppiness_list) else 0.0
        current_close = close_prices[i]
        current_open  = candles[i]["open"]
        current_high  = candles[i]["high"]
        current_low   = candles[i]["low"]
        current_volume = candles[i].get("volume", 0.0)
        current_vol_sma = vol_sma_list[i]
        chandelier_state = chandelier_list[i]
        trend_following_allowed = is_trend_following_allowed(current_adx, current_choppiness)
        current_atr_shock = atr_shock_filter(current_atr, current_atr_ma)

        prev_rsi = rsi_list[i - 1]
        # Determine sentiment dynamically if sentiment_map is provided
        c_sentiment_score = sentiment_score
        c_sentiment_label = sentiment_label
        c_sentiment_raw = sentiment_raw
        if sentiment_map:
            date_str = candles[i]["time"][:10]
            c_sentiment = sentiment_map.get(date_str)
            if c_sentiment:
                c_sentiment_score = c_sentiment["score"]
                c_sentiment_label = c_sentiment["label"]
                c_sentiment_raw = c_sentiment["raw_value"]

        extreme_fear = c_sentiment_score < -0.6
        extreme_greed = c_sentiment_score > 0.6
        sentiment_note = f" | Sentiment: {c_sentiment_raw}/100 ({sentiment_label_vi(c_sentiment_label)})"

        rsi_turning_up   = (prev_rsi <= 30) and (current_rsi > 30)
        rsi_turning_down = (prev_rsi >= 70) and (current_rsi < 70)

        vol_spike = (current_vol_sma > 0) and (current_volume > current_vol_sma * 1.3)

        above_sma200 = (current_sma200 > 0) and (current_close > current_sma200)
        below_sma200 = (current_sma200 > 0) and (current_close < current_sma200)

        sma50_prev5   = sma50_list[i - 6] if i >= 6 else 0.0
        sma50_uptrend   = (current_sma50 > 0) and (current_sma50 > sma50_prev5)
        sma50_downtrend = (current_sma50 > 0) and (current_sma50 < sma50_prev5)
        above_sma50 = (current_sma50 > 0) and (current_close > current_sma50)

        sma50_lower_bound = current_sma50 * 0.99
        in_pullback_zone = (
            current_sma50 > 0
            and current_ema21 > 0
            and sma50_lower_bound <= current_close <= current_ema21
        )
        is_bullish_candle = current_close > current_open

        # Chặn spam Pullback-Zone: chỉ kích hoạt khi mới bước vào zone
        prev_close_val = close_prices[i - 1]
        prev_sma50_val = sma50_list[i - 1]
        prev_ema21_val_pb = ema21_list[i - 1]
        prev_in_pullback_zone = (
            prev_sma50_val > 0
            and prev_ema21_val_pb > 0
            and prev_sma50_val * 0.99 <= prev_close_val <= prev_ema21_val_pb
        )

        # Support / Resistance: dùng 50 nến LỊCH SỬ (loại nến hiện tại) để SFP chính xác
        window_50 = candles[i - 50 : i]   # [i-50, i-1] — không bao gồm nến i
        support = min(c["low"] for c in window_50)
        resistance = max(c["high"] for c in window_50)

        sfp_bull = is_bullish_sfp(
            current_high,
            current_low,
            current_close,
            current_open,
            support,
            current_volume,
            current_vol_sma,
            current_rsi,
        )
        sfp_bear = is_bearish_sfp(
            current_high,
            current_low,
            current_close,
            current_open,
            resistance,
            current_volume,
            current_vol_sma,
            current_rsi,
        )

        # Chặn spam Break-SMA50: chỉ kích hoạt ngay lúc giá vừa xuyên xuống dưới SMA50
        prev_close_val_sma50 = close_prices[i - 1]
        prev_sma50_val_break = sma50_list[i - 1]
        prev_above_sma50 = (
            prev_sma50_val_break > 0
            and prev_close_val_sma50 > prev_sma50_val_break
        )

        prev_ema9 = ema9_list[i - 1]
        prev_ema21 = ema21_list[i - 1]
        ema_golden_cross = (prev_ema9 <= prev_ema21) and (current_ema9 > current_ema21)
        ema_death_cross  = (prev_ema9 >= prev_ema21) and (current_ema9 < current_ema21)
        ema_bearish_active = current_ema9 < current_ema21
        chandelier_blocks_buy = (chandelier_state == "BEAR")
        current_adx = adx_list[i] if i < len(adx_list) else 0.0
        current_choppiness = choppiness_list[i] if i < len(choppiness_list) else 0.0
        trend_following_allowed = is_trend_following_allowed(current_adx, current_choppiness)

        sig = "NEUTRAL"
        reason = ""

        # Áp dụng logic quyết định tín hiệu (y hệt analyze_market)
        if rsi_turning_up:
            vol_note = " + Volume Spike (dong tien lon do day)" if vol_spike else " (volume trung binh - can them xac nhan)"
            if above_sma200 and not chandelier_blocks_buy:
                sig = "STRONG BUY (Confirmed Reversal)"
                reason = f"RSI cat len tren 30 (dao chieu tu Oversold){vol_note} | Tren SMA200"
                if extreme_fear:
                    reason += f" | {sentiment_note}"
            else:
                sig = "NEUTRAL (CT-Unconfirmed)"
                reason = f"RSI dao chieu tu Oversold{vol_note} NHUNG thieu xac nhan — bo qua"
        elif rsi_turning_down:
            vol_note = " + Volume Spike (xa hang manh)" if vol_spike else " (volume trung binh)"
            sig = "STRONG SELL (Confirmed Reversal)"
            reason = f"RSI cat xuong duoi 70 (dao chieu tu Overbought){vol_note}" + (" | Ben tren SMA200 - co the chi la dieu chinh" if above_sma200 else "")
            if extreme_greed:
                reason += f" | {sentiment_note}"
        elif sfp_bull and not chandelier_blocks_buy:
            sig = "BUY (SFP-Liquidity-Sweep)"
            reason = f"Quet thanh khoan day: wick xuyen SL duoi {support:.2f} roi dong cua tren support | RSI={current_rsi:.1f}" + (" | Bull Market (SMA200 xac nhan)" if above_sma200 else " | Bear Market - rui ro cao hon")
        elif sfp_bear:
            sig = "SELL (SFP-Liquidity-Sweep)"
            reason = f"Quet thanh khoan dinh: wick vuot {resistance:.2f} roi dong cua duoi resistance | RSI={current_rsi:.1f}" + (" | Bear Market (SMA200 xac nhan)" if below_sma200 else " | Bull Market - co the chi la fakeout")
        elif ema_golden_cross:
            if not trend_following_allowed:
                sig = "NEUTRAL (Trend-Blocked)"
                reason = "EMA9 cat len EMA21 nhung ADX < 20 hoac Choppiness cao, bo qua trend-following"
            elif chandelier_blocks_buy:
                sig = "WEAK BUY (Crossover-Blocked)"
                reason = "EMA9 cat len EMA21 NHUNG Chandelier=BEAR — thi truong dang downtrend theo ATR, chu y!"
            elif above_sma200:
                sig = "BUY (Crossover)"
                reason = "EMA9 cat len EMA21 + Chandelier=BULL + Gia tren SMA200 (Bull Market confirmed)"
                if extreme_fear:
                    sig = "WEAK BUY (Crossover-Sentiment)"
                    reason += f" | NHUNG{sentiment_note} — Thi truong dang trong vung so hai cuc do!"
            elif current_sma200 > 0:
                sig = "NEUTRAL (Crossover-BearMkt)"
                reason = "EMA9 cat len EMA21 NHUNG gia duoi SMA200 — co the la bull trap, bo qua"
            else:
                sig = "BUY (Crossover)"
                reason = "EMA9 cat len EMA21 (Xu huong tang — chua du du lieu SMA200)" + sentiment_note
        elif ema_death_cross:
            if not trend_following_allowed:
                sig = "NEUTRAL (Trend-Blocked)"
                reason = "EMA9 cat xuong EMA21 nhung ADX < 20 hoac Choppiness cao, bo qua trend-following"
            elif below_sma200:
                sig = "SELL (Crossover)"
                reason = "EMA9 cat xuong EMA21 + Gia duoi SMA200 (Bear Market confirmed)"
            elif current_sma200 > 0:
                sig = "WEAK SELL (Crossover)"
                reason = "EMA9 cat xuong EMA21 NHUNG gia tren SMA200 — co the chi la dieu chinh"
            else:
                sig = "SELL (Crossover)"
                reason = "EMA9 cat xuong EMA21 (Xu huong giam — chua du du lieu SMA200)"
        elif (
            ema_bearish_active
            and in_pullback_zone
            and not prev_in_pullback_zone   # Mới bước vào zone — tránh spam liên tiếp
            and is_bullish_candle
            and sma50_uptrend
            and above_sma200
            and not chandelier_blocks_buy
            and current_rsi < 55
        ):
            sig = "BUY (Pullback-Zone)"
            reason = f"Gia dieu chinh vao vung EMA21({current_ema21:.2f})-SMA50({current_sma50:.2f}), nen xanh xac nhan | SMA50 doc len | SMA200 phia duoi | Chandelier=BULL"
        elif (
            ema_bearish_active
            and not above_sma50
            and prev_above_sma50       # Vừa xuyên xuống dưới SMA50 (chỉ 1 lần)
            and sma50_downtrend
            and below_sma200           # Chỉ SELL khi đang trong bear market thực sự
            and current_sma50 > 0
        ):
            sig = "SELL (Break-SMA50)"
            reason = f"Gia XUYEN THU'NG SMA50 ({current_sma50:.2f}) trong Bear Market (duoi SMA200) — trailing stop kich hoat!"
        else:
            # Neutral states
            chandelier_tag = f" | Chandelier={chandelier_state}"
            if current_ema9 > current_ema21:
                if above_sma200 and sma50_uptrend and not chandelier_blocks_buy:
                    sig = "NEUTRAL (BULLISH)"
                    reason = f"Xu huong tang manh: EMA9>EMA21, tren SMA50+SMA200{chandelier_tag}"
                elif above_sma200:
                    sig = "NEUTRAL (BULLISH)"
                    reason = f"Xu huong tang: EMA9>EMA21, tren SMA200 (SMA50 chua xac nhan){chandelier_tag}"
                else:
                    sig = "NEUTRAL (BULLISH-CAUTION)"
                    reason = f"EMA9>EMA21 nhung duoi SMA200 — thi truong lon van giam{chandelier_tag}"
            else:
                if below_sma200 and sma50_downtrend:
                    sig = "NEUTRAL (BEARISH)"
                    reason = f"Xu huong giam manh: EMA9<EMA21, duoi SMA50+SMA200{chandelier_tag}"
                elif below_sma200:
                    sig = "NEUTRAL (BEARISH)"
                    reason = f"Xu huong giam: EMA9<EMA21, duoi SMA200{chandelier_tag}"
                else:
                    sig = "NEUTRAL (BEARISH-CAUTION)"
                    reason = f"EMA9<EMA21 nhung tren SMA200 — co the chi la dieu chinh ngan han{chandelier_tag}"

        # Determine regime using current indicators (TRENDING_BULL, TRENDING_BEAR, RANGING, HIGH_VOLATILITY)
        atr_pct_val = (current_atr / current_close * 100) if current_close and current_atr else 0.0
        regime_info = regime_from_values(current_close, current_sma200, current_ema21, current_sma50, current_adx, atr_pct_val)

        tp_sl_dict = calculate_tp_sl(
            close       = current_close,
            signal      = sig,
            atr         = current_atr,
            support     = support,
            resistance  = resistance,
            bb_upper    = current_bb_upper,
            bb_middle   = current_bb_middle,
            bb_lower    = current_bb_lower,
            regime      = regime_info.get("regime"),
        )

        # Prepare lightweight data/context for scoring (keeps backward compatibility)
        score_data = {
            "rsi": current_rsi,
            "rsi_delta": current_rsi - rsi_list[i-3] if i >= 3 else 0.0,
            "ema9": current_ema9,
            "ema21": current_ema21,
            "sma50": current_sma50,
            "sma200": current_sma200,
            "macd": current_macd,
            "macd_signal": current_macd_signal,
            "macd_hist": current_macd_hist,
            "bb_upper": current_bb_upper,
            "bb_middle": current_bb_middle,
            "bb_lower": current_bb_lower,
            "atr": current_atr,
            "atr_ma": current_atr_ma,
            "adx": current_adx,
            "choppiness": current_choppiness,
            "atr_shock": current_atr_shock,
            "support": support,
            "resistance": resistance,
            "confidence": round(0.5, 2),
            "position_size": 1.0,
            "market_regime": "TRENDING" if trend_following_allowed else "SIDEWAY",
            "regime": regime_info.get("regime"),
            "regime_confidence": regime_info.get("confidence"),
            "trend_following_allowed": trend_following_allowed,
            "vol_spike": vol_spike,
            "chandelier": chandelier_state,
            "sentiment": {
                "score": c_sentiment_score,
                "label": c_sentiment_label,
                "raw_value": c_sentiment_raw,
            },
            "volume": current_volume,
            "vol_sma20": current_vol_sma,
        }

        # Compute a basic signal_score for this candle (keeps consistency with analyze_market)
        try:
            sig_score_obj = score_signal(
                sig,
                score_data,
                {
                    "chandelier": chandelier_state,
                    "above_sma200": above_sma200,
                    "below_sma200": below_sma200,
                    "vol_spike": vol_spike,
                    "sentiment_score": c_sentiment_score,
                    "regime": regime_info.get("regime"),
                    "disable_ml": True,
                },
            )
        except Exception:
            sig_score_obj = {"action": sig, "score": 50, "confidence": "LOW", "position_size": 0.5, "regime": regime_info.get("regime")}

        results.append({
            "time": candles[i]["time"],
            "close": current_close,
            "open": current_open,
            "high": current_high,
            "low": current_low,
            "rsi": current_rsi,
            "ema9": current_ema9,
            "ema21": current_ema21,
            "sma50": current_sma50,
            "sma200": current_sma200,
            "macd_hist": current_macd_hist,
            "bb_upper": current_bb_upper,
            "bb_middle": current_bb_middle,
            "bb_lower": current_bb_lower,
            "atr": current_atr,
            "atr_ma": current_atr_ma,
            "adx": current_adx,
            "choppiness": current_choppiness,
            "atr_shock": current_atr_shock,
            "market_regime": "TRENDING" if trend_following_allowed else "SIDEWAY",
            "regime": regime_info.get("regime"),
            "regime_confidence": regime_info.get("confidence"),
            "trend_following_allowed": trend_following_allowed,
            "confidence": 0.50,
            "position_size": 1.0,
            "support": support,
            "resistance": resistance,
            "signal": sig,
            "reason": reason,
            "tp_sl": tp_sl_dict,
            "chandelier": chandelier_state,
            "vol_spike": vol_spike,
            "sentiment": {
                "score": c_sentiment_score,
                "label": c_sentiment_label,
                "raw_value": c_sentiment_raw,
            },
            "volume": current_volume,
            "vol_sma20": current_vol_sma,
            "obv": candles[i]["obv"],
            "cmf": candles[i]["cmf"],
            "mfi": candles[i]["mfi"],
            "return_15m": candles[i]["return_15m"],
            "return_1h": candles[i]["return_1h"],
            "return_4h": candles[i]["return_4h"],
            "return_1d": candles[i]["return_1d"],
            "ema9_slope": candles[i]["ema9_slope"],
            "ema21_slope": candles[i]["ema21_slope"],
            "sma50_slope": candles[i]["sma50_slope"],
            "sma200_slope": candles[i]["sma200_slope"],
            "ema_distance_pct": candles[i]["ema_distance_pct"],
            "ema_distance_zscore": candles[i]["ema_distance_zscore"],
            "realized_vol_20": candles[i]["realized_vol_20"],
            "realized_vol_50": candles[i]["realized_vol_50"],
            "atr_percentile": candles[i]["atr_percentile"],
            "volatility_regime_compression": candles[i]["volatility_regime_compression"],
            "volatility_regime_breakout": candles[i]["volatility_regime_breakout"],
            "volatility_regime_mean_reversion": candles[i]["volatility_regime_mean_reversion"],
            "volatility_regime_panic_sell": candles[i]["volatility_regime_panic_sell"],
            "volatility_regime_low_liquidity": candles[i]["volatility_regime_low_liquidity"],
            "volatility_regime_pump_risk": candles[i]["volatility_regime_pump_risk"],
            "distance_support_pct": candles[i]["distance_support_pct"],
            "distance_resistance_pct": candles[i]["distance_resistance_pct"],
            "higher_high": candles[i]["higher_high"],
            "lower_low": candles[i]["lower_low"],
            "market_structure_break": candles[i]["market_structure_break"],
            "volume_acceleration": candles[i]["volume_acceleration"],
            "volume_percentile": candles[i]["volume_percentile"],
            "signal_score": sig_score_obj,
        })

    return results

