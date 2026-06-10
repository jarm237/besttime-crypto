"""
Analysis module - Tính toán RSI, EMA và xác định tín hiệu Mua/Bán
Không phụ thuộc vào thư viện pandas hay ta, sử dụng thuật toán thuần tối ưu.
"""

import math
from btc_scraper.sentiment import get_market_sentiment, sentiment_label_vi
from btc_scraper.filters import atr_shock_filter
from btc_scraper.signal_score import score_signal


def calculate_atr(candles: list[dict], period: int = 14) -> list[float]:
    """
    Tính toán Average True Range (ATR) đo độ biến động giá.
    True Range = max(High-Low, |High-PrevClose|, |Low-PrevClose|)
    ATR = Wilder's smoothing của TR trong `period` phiên.
    """
    if len(candles) < period + 1:
        # Không đủ dữ liệu, fallback về High-Low đơn giản
        return [c["high"] - c["low"] for c in candles]

    tr_list: list[float] = [candles[0]["high"] - candles[0]["low"]]
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low  = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_list.append(tr)

    # Khởi tạo ATR bằng SMA của period phiên đầu
    atr_list: list[float] = [0.0] * period
    atr = sum(tr_list[:period]) / period
    atr_list.append(atr)

    # Wilder's Smoothing (EMA với alpha = 1/period)
    for i in range(period + 1, len(tr_list)):
        atr = (atr * (period - 1) + tr_list[i]) / period
        atr_list.append(atr)

    return atr_list


def calculate_sma(values: list[float], period: int) -> list[float]:
    """Return simple moving average for a numeric series."""
    if len(values) < period:
        return [0.0] * len(values)
    result: list[float] = [0.0] * (period - 1)
    window_sum = sum(values[:period])
    result.append(window_sum / period)
    for i in range(period, len(values)):
        window_sum += values[i] - values[i - period]
        result.append(window_sum / period)
    return result


def calculate_adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """Calculate ADX to measure trend strength."""
    n = len(highs)
    if n < period + 1:
        return [0.0] * n

    tr_list: list[float] = [0.0] * n
    plus_dm: list[float] = [0.0] * n
    minus_dm: list[float] = [0.0] * n

    for i in range(1, n):
        high = highs[i]
        low = lows[i]
        prev_high = highs[i - 1]
        prev_low = lows[i - 1]
        prev_close = closes[i - 1]

        tr_list[i] = max(high - low, abs(high - prev_close), abs(low - prev_close))
        up_move = high - prev_high
        down_move = prev_low - low

        plus_dm[i] = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0.0

    atr_values: list[float] = [0.0] * n
    plus_di: list[float] = [0.0] * n
    minus_di: list[float] = [0.0] * n
    dx: list[float] = [0.0] * n
    adx: list[float] = [0.0] * n

    atr = sum(tr_list[1 : period + 1]) / period
    plus_dm_sum = sum(plus_dm[1 : period + 1])
    minus_dm_sum = sum(minus_dm[1 : period + 1])
    atr_values[period] = atr

    if atr > 0:
        plus_di[period] = 100.0 * plus_dm_sum / atr
        minus_di[period] = 100.0 * minus_dm_sum / atr
        denom = plus_di[period] + minus_di[period]
        dx[period] = 100.0 * abs(plus_di[period] - minus_di[period]) / denom if denom > 0 else 0.0

    for i in range(period + 1, n):
        atr = (atr * (period - 1) + tr_list[i]) / period
        plus_dm_sum = (plus_dm_sum * (period - 1) + plus_dm[i]) / period
        minus_dm_sum = (minus_dm_sum * (period - 1) + minus_dm[i]) / period
        atr_values[i] = atr

        if atr > 0:
            plus_di[i] = 100.0 * plus_dm_sum / atr
            minus_di[i] = 100.0 * minus_dm_sum / atr
            denom = plus_di[i] + minus_di[i]
            dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / denom if denom > 0 else 0.0

    adx_val = sum(dx[period : period * 2]) / period if len(dx) > period * 2 else dx[period]
    adx[period * 2 - 1 if len(dx) > period * 2 - 1 else period] = adx_val
    for i in range(period * 2, n):
        adx_val = (adx_val * (period - 1) + dx[i]) / period
        adx[i] = adx_val

    return adx


def calculate_choppiness_index(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """Calculate Choppiness Index to detect trending vs choppy market."""
    n = len(highs)
    result = [0.0] * n
    if n < period:
        return result

    tr_list: list[float] = [0.0] * n
    for i in range(1, n):
        tr_list[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))

    for i in range(period - 1, n):
        window_high = max(highs[i - period + 1 : i + 1])
        window_low = min(lows[i - period + 1 : i + 1])
        tr_total = sum(tr_list[i - period + 1 : i + 1])
        dist = window_high - window_low
        if dist <= 0:
            result[i] = 0.0
        else:
            result[i] = 100.0 * math.log10(tr_total / dist) / math.log10(period)
    return result


def is_trend_following_allowed(adx: float, choppiness: float, adx_threshold: float = 20.0, choppy_threshold: float = 62.0) -> bool:
    return adx >= adx_threshold and choppiness <= choppy_threshold


def is_bullish_sfp(
    high: float,
    low: float,
    close_price: float,
    open_price: float,
    support: float,
    volume: float,
    volume_ma: float,
    rsi: float,
    wick_threshold: float = 0.45,
    volume_multiplier: float = 1.5,
) -> bool:
    if support <= 0 or volume_ma <= 0:
        return False
    lower_wick = max(min(open_price, close_price) - low, 0.0)
    full_range = max(high - low, 1e-9)
    lower_wick_ratio = lower_wick / full_range
    return (
        low < support
        and close_price > support
        and rsi < 55
        and volume > volume_ma * volume_multiplier
        and lower_wick_ratio > wick_threshold
    )


def is_bearish_sfp(
    high: float,
    low: float,
    close_price: float,
    open_price: float,
    resistance: float,
    volume: float,
    volume_ma: float,
    rsi: float,
    wick_threshold: float = 0.45,
    volume_multiplier: float = 1.5,
) -> bool:
    if resistance <= 0 or volume_ma <= 0:
        return False
    upper_wick = max(high - max(open_price, close_price), 0.0)
    full_range = max(high - low, 1e-9)
    upper_wick_ratio = upper_wick / full_range
    return (
        high > resistance
        and close_price < resistance
        and rsi > 55
        and volume > volume_ma * volume_multiplier
        and upper_wick_ratio > wick_threshold
    )


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


def wick_ratios(open_price: float, high: float, low: float, close_price: float) -> tuple[float, float]:
    body_top = max(open_price, close_price)
    body_bottom = min(open_price, close_price)
    full_range = max(high - low, 1e-9)
    lower_wick = max(body_bottom - low, 0.0)
    upper_wick = max(high - body_top, 0.0)
    return lower_wick / full_range, upper_wick / full_range


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
    atr_tp_mult: float = 3.5,
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
        sl = max(sl, entry - 6.0 * atr_used)
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
        sl = min(sl, entry + 6.0 * atr_used)
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

def calculate_macd(prices: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list[float], list[float], list[float]]:
    """Tính toán MACD Line, Signal Line và Histogram"""
    ema_fast = calculate_ema(prices, fast)
    ema_slow = calculate_ema(prices, slow)
    
    macd_line = []
    for f, s in zip(ema_fast, ema_slow):
        if f == 0.0 or s == 0.0:
            macd_line.append(0.0)
        else:
            macd_line.append(f - s)
            
    first_valid_idx = slow - 1
    if len(macd_line) <= first_valid_idx + signal:
        return [0.0] * len(prices), [0.0] * len(prices), [0.0] * len(prices)
        
    macd_valid_part = macd_line[first_valid_idx:]
    signal_valid_part = calculate_ema(macd_valid_part, signal)
    
    signal_line = [0.0] * first_valid_idx + signal_valid_part
    
    hist = []
    for m, sig in zip(macd_line, signal_line):
        if m == 0.0 or sig == 0.0:
            hist.append(0.0)
        else:
            hist.append(m - sig)
            
    return macd_line, signal_line, hist


def calculate_bollinger_bands(prices: list[float], period: int = 20, num_std: int = 2) -> tuple[list[float], list[float], list[float]]:
    """Tính toán Bollinger Bands (Upper, Middle, Lower)"""
    if len(prices) < period:
        return [0.0] * len(prices), [0.0] * len(prices), [0.0] * len(prices)
        
    middle_band = []
    upper_band = []
    lower_band = []
    
    for _ in range(period - 1):
        middle_band.append(0.0)
        upper_band.append(0.0)
        lower_band.append(0.0)
        
    for i in range(period - 1, len(prices)):
        window = prices[i - period + 1 : i + 1]
        sma = sum(window) / period
        
        variance = sum((x - sma) ** 2 for x in window) / period
        std_dev = math.sqrt(variance)
        
        middle_band.append(sma)
        upper_band.append(sma + num_std * std_dev)
        lower_band.append(sma - num_std * std_dev)
        
    return upper_band, middle_band, lower_band


def calculate_ema(prices: list[float], period: int) -> list[float]:
    """Tính toán Exponential Moving Average (EMA)"""
    if len(prices) < period:
        return [0.0] * len(prices)
    
    ema = []
    # Điểm đầu tiên lấy bằng SMA để khởi tạo
    sma = sum(prices[:period]) / period
    for _ in range(period - 1):
        ema.append(0.0)
    ema.append(sma)
    
    multiplier = 2 / (period + 1)
    for price in prices[period:]:
        next_ema = (price - ema[-1]) * multiplier + ema[-1]
        ema.append(next_ema)
        
    return ema


def calculate_sma(prices: list[float], period: int) -> list[float]:
    """
    Tính toán Simple Moving Average (SMA) — O(n), không phụ thuộc thư viện ngoài.
    Các phần tử chưa đủ `period` điểm sẽ trả về 0.0.
    """
    if len(prices) < period:
        return [0.0] * len(prices)

    result: list[float] = [0.0] * (period - 1)
    window_sum = sum(prices[:period])
    result.append(window_sum / period)

    for i in range(period, len(prices)):
        window_sum += prices[i] - prices[i - period]
        result.append(window_sum / period)

    return result


def calculate_volume_sma(candles: list[dict], period: int = 20) -> list[float]:
    """
    Tính SMA của Volume trong `period` phiên.
    Dùng để xác định Volume Spike: volume hiện tại vượt X lần trung bình.
    Trả về danh sách cùng độ dài với candles, phần tử chưa đủ dữ liệu = 0.0.
    """
    volumes = [c.get("volume", 0.0) for c in candles]
    return calculate_sma(volumes, period)


def calculate_chandelier_exit(candles: list[dict], period: int = 22, multiplier: float = 3.0) -> list[str]:
    """
    Chandelier Exit — chỉ báo xu hướng dựa trên ATR, bảo vệ bot khỏi các pha sideway/sập nhanh
    mà đường MA phản ứng chậm hơn.

    Long Exit (Tín hiệu SELL):  Giá < Highest_High(period) - multiplier * ATR
    Short Exit (Tín hiệu BUY):  Giá > Lowest_Low(period) + multiplier * ATR

    Trả về list[str]: 'BULL' | 'BEAR' | 'UNKNOWN' cho mỗi nến.
    - 'BULL': Chandelier cho phép BUY (đang trong uptrend theo ATR).
    - 'BEAR': Chandelier CẤM BUY — đang trong downtrend hoặc sideway sập.
    - 'UNKNOWN': Chưa đủ dữ liệu.
    """
    n = len(candles)
    if n < period + 1:
        return ["UNKNOWN"] * n

    atr_list = calculate_atr(candles, period)
    atr_ma_list = calculate_sma(atr_list, period)
    result = ["UNKNOWN"] * n

    for i in range(period - 1, n):
        if atr_list[i] == 0.0:
            continue
        window = candles[max(0, i - period + 1): i + 1]
        highest_high = max(c["high"] for c in window)
        lowest_low   = min(c["low"]  for c in window)
        atr_val      = atr_list[i]
        atr_ma       = atr_ma_list[i]
        atr_used     = min(atr_val, atr_ma * 1.5) if atr_ma > 0 else atr_val
        atr_shock    = atr_ma > 0 and atr_val > atr_ma * 1.8
        close        = candles[i]["close"]

        long_stop  = highest_high - multiplier * atr_used   # Nếu giá < mức này → BEAR
        short_stop = lowest_low  + multiplier * atr_used    # Nếu giá > mức này → BULL

        if atr_shock:
            result[i] = result[i - 1] if result[i - 1] != "UNKNOWN" else "UNKNOWN"
        elif close > short_stop:
            result[i] = "BULL"
        elif close < long_stop:
            result[i] = "BEAR"
        else:
            result[i] = result[i - 1] if result[i - 1] != "UNKNOWN" else "UNKNOWN"

    return result


def calculate_rsi(prices: list[float], period: int = 14) -> list[float]:
    """Tính toán Relative Strength Index (RSI)"""
    if len(prices) <= period:
        return [50.0] * len(prices)
        
    rsi_vals = [50.0] * (period + 1)
    
    # Tính gains và losses đầu tiên
    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))
            
    # Tính SMA đầu tiên cho gain và loss
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    if avg_loss == 0:
        rsi_vals.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi_vals.append(100.0 - (100.0 / (1.0 + rs)))
        
    # Tính các điểm tiếp theo bằng Wilder's Smoothing
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        if avg_loss == 0:
            rsi_vals.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_vals.append(100.0 - (100.0 / (1.0 + rs)))
            
    # Đảm bảo độ dài khớp với danh sách prices đầu vào
    while len(rsi_vals) < len(prices):
        rsi_vals.insert(0, 50.0)
    return rsi_vals[-len(prices):]


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
    chandelier_list = calculate_chandelier_exit(candles, period=22, multiplier=3.0)
    sentiment_data = get_market_sentiment()
    sentiment_score = sentiment_data["score"]
    sentiment_label = sentiment_data["label"]
    sentiment_raw = sentiment_data["raw_value"]

    # Ghi lại chỉ số vào nến để hiển thị
    for i, c in enumerate(candles):
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
        c["vol_sma20"] = vol_sma_list[i]
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
                "trend_following_allowed": trend_following_allowed,
                "trend_label": trend_label,
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
                return finalize("BUY (Counter-Trend Reversal - High Risk)", f"RSI cat len tren 30 (dao chieu tu Oversold){vol_note}" + (" | Chandelier=BEAR: rui ro cao!" if chandelier_blocks_buy else "") + (" | Ben duoi SMA200 - CAUTION" if not above_sma200 else "") + (sentiment_note if extreme_fear else ""))

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
                return finalize("WEAK BUY (Crossover)", "EMA9 cat len EMA21 NHUNG gia duoi SMA200 — co the la bull trap!" + sentiment_note)
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
        res["signal_score"] = score_signal(current_sig, res, trend_context)
    except Exception:
        res["signal_score"] = {"action": current_sig, "score": 50, "confidence": "LOW", "position_size": 0.5}

    return res



def analyze_all_market(candles: list[dict]) -> list[dict]:
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
    chandelier_list = calculate_chandelier_exit(candles, period=22, multiplier=3.0)

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
            else:
                sig = "BUY (Counter-Trend Reversal - High Risk)"
                reason = f"RSI cat len tren 30 (dao chieu tu Oversold){vol_note}" + (" | Chandelier=BEAR: rui ro cao!" if chandelier_blocks_buy else "") + (" | Ben duoi SMA200 - CAUTION" if not above_sma200 else "")
        elif rsi_turning_down:
            vol_note = " + Volume Spike (xa hang manh)" if vol_spike else " (volume trung binh)"
            sig = "STRONG SELL (Confirmed Reversal)"
            reason = f"RSI cat xuong duoi 70 (dao chieu tu Overbought){vol_note}" + (" | Ben tren SMA200 - co the chi la dieu chinh" if above_sma200 else "")
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
            elif current_sma200 > 0:
                sig = "WEAK BUY (Crossover)"
                reason = "EMA9 cat len EMA21 NHUNG gia duoi SMA200 — co the la bull trap!"
            else:
                sig = "BUY (Crossover)"
                reason = "EMA9 cat len EMA21 (Xu huong tang — chua du du lieu SMA200)"
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

        tp_sl_dict = calculate_tp_sl(
            close       = current_close,
            signal      = sig,
            atr         = current_atr,
            support     = support,
            resistance  = resistance,
            bb_upper    = current_bb_upper,
            bb_middle   = current_bb_middle,
            bb_lower    = current_bb_lower,
        )

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
        })

    return results
