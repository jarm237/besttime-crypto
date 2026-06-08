"""
Analysis module - Tính toán RSI, EMA và xác định tín hiệu Mua/Bán
Không phụ thuộc vào thư viện pandas hay ta, sử dụng thuật toán thuần tối ưu.
"""

import math


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


def calculate_tp_sl(
    close: float,
    signal: str,
    atr: float,
    support: float,
    resistance: float,
    bb_upper: float,
    bb_middle: float,
    bb_lower: float,
    atr_sl_mult: float = 1.5,
    atr_tp_mult: float = 2.5,
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
        # SL: mức support hoặc ATR*mult (lấy mức nào cao hơn = bảo vệ tốt hơn)
        sl_atr  = entry - atr_sl_mult * atr
        sl_sup  = support * 0.998 if support > 0 else sl_atr  # buffer 0.2% dưới support
        sl = max(sl_atr, sl_sup)  # chọn mức cao hơn (gần giá hơn = thắt chặt hơn)
        if sl >= entry:
            sl = entry - atr_sl_mult * atr  # fallback ATR nếu support quá cao

        # TP1: BB Middle hoặc ATR*mult (lấy mức nhỏ hơn = bảo thủ)
        tp1_bb  = bb_middle if bb_middle > entry else 0.0
        tp1_atr = entry + atr_tp_mult * atr
        tp1 = min(tp1_bb, tp1_atr) if tp1_bb > 0 else tp1_atr
        if tp1 <= entry:
            tp1 = entry + atr_tp_mult * atr

        # TP2: Resistance hoặc BB Upper hoặc 2×ATR*mult
        tp2_candidates = [x for x in [resistance * 0.998, bb_upper * 0.998, entry + atr_tp_mult * 2 * atr] if x > tp1]
        tp2 = min(tp2_candidates) if tp2_candidates else tp1 * 1.01

        method = "ATR+Support+BB (Long)"

    elif is_sell:
        # SL: resistance hoặc ATR*mult (lấy mức thấp hơn = gần giá hơn)
        sl_atr  = entry + atr_sl_mult * atr
        sl_res  = resistance * 1.002 if resistance > 0 else sl_atr
        sl = min(sl_atr, sl_res)
        if sl <= entry:
            sl = entry + atr_sl_mult * atr

        # TP1: BB Middle hoặc ATR*mult
        tp1_bb  = bb_middle if 0 < bb_middle < entry else 0.0
        tp1_atr = entry - atr_tp_mult * atr
        tp1 = max(tp1_bb, tp1_atr) if tp1_bb > 0 else tp1_atr
        if tp1 >= entry:
            tp1 = entry - atr_tp_mult * atr

        # TP2: Support hoặc BB Lower
        tp2_candidates = [x for x in [support * 1.002, bb_lower * 1.002, entry - atr_tp_mult * 2 * atr] if x < tp1]
        tp2 = max(tp2_candidates) if tp2_candidates else tp1 * 0.99

        method = "ATR+Resistance+BB (Short)"

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
    result = ["UNKNOWN"] * n

    for i in range(period - 1, n):
        if atr_list[i] == 0.0:
            continue
        window = candles[max(0, i - period + 1): i + 1]
        highest_high = max(c["high"] for c in window)
        lowest_low   = min(c["low"]  for c in window)
        atr_val      = atr_list[i]
        close        = candles[i]["close"]

        long_stop  = highest_high - multiplier * atr_val   # Nếu giá < mức này → BEAR
        short_stop = lowest_low  + multiplier * atr_val    # Nếu giá > mức này → BULL

        if close > short_stop:
            result[i] = "BULL"
        elif close < long_stop:
            result[i] = "BEAR"
        else:
            # Trong vùng trung gian: giữ nguyên trạng thái trước đó
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

    Chiến lược tín hiệu (3 lớp lọc):
      Lớp 1 — Trend Filter (SMA 200): Chỉ cho phép BUY khi giá > SMA200.
      Lớp 2 — Pullback to SMA50: Khi giá gãy EMA21 nhưng chạm SMA50, bắt đáy pullback.
      Lớp 3 — EMA Crossover Matrix: EMA9/EMA21 crossover có xác nhận xu hướng từ SMA50.
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
    vol_sma_list = calculate_volume_sma(candles, 20)
    chandelier_list = calculate_chandelier_exit(candles, period=22, multiplier=3.0)

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
        c["vol_sma20"] = vol_sma_list[i]
        c["chandelier"] = chandelier_list[i]

    current_rsi = rsi_list[-1]
    current_ema9 = ema9_list[-1]
    current_ema21 = ema21_list[-1]
    current_sma50 = sma50_list[-1]
    current_sma200 = sma200_list[-1]
    current_macd = macd_list[-1]
    current_macd_signal = macd_sig_list[-1]
    current_macd_hist = macd_hist_list[-1]
    current_bb_upper = bb_up_list[-1]
    current_bb_middle = bb_mid_list[-1]
    current_bb_lower = bb_low_list[-1]
    current_atr = atr_list[-1] if atr_list else 0.0
    current_close = close_prices[-1]
    current_open  = candles[-1]["open"]
    current_high  = candles[-1]["high"]
    current_low   = candles[-1]["low"]
    current_volume = candles[-1].get("volume", 0.0)
    current_vol_sma = vol_sma_list[-1]
    chandelier_state = chandelier_list[-1]   # 'BULL' | 'BEAR' | 'UNKNOWN'

    # ── Lớp 0: RSI flip (đảo chiều qua ngưỡng, không phải chỉ so với ngưỡng) ──
    prev_rsi = rsi_list[-2] if len(rsi_list) >= 2 else current_rsi
    rsi_turning_up   = (prev_rsi <= 30) and (current_rsi > 30)   # RSI vừa cắt lên trên 30
    rsi_turning_down = (prev_rsi >= 70) and (current_rsi < 70)   # RSI vừa cắt xuống dưới 70

    # Volume Spike: volume hiện tại vượt 1.3× trung bình 20 phiên
    vol_spike = (current_vol_sma > 0) and (current_volume > current_vol_sma * 1.3)

    # ── Trạng thái xu hướng SMA (dùng chung cho cả 3 lớp lọc bên dưới) ──────
    above_sma200 = (current_sma200 > 0) and (current_close > current_sma200)
    below_sma200 = (current_sma200 > 0) and (current_close < current_sma200)

    sma50_prev5   = sma50_list[-6] if len(sma50_list) >= 6 else 0.0
    sma50_uptrend   = (current_sma50 > 0) and (current_sma50 > sma50_prev5)
    sma50_downtrend = (current_sma50 > 0) and (current_sma50 < sma50_prev5)
    above_sma50 = (current_sma50 > 0) and (current_close > current_sma50)

    # ── Lớp 2 nâng cấp: Pullback Zone = giữa EMA21 và SMA50 (±1%) ────────────
    # Rộng hơn 0.5% cũ, bắt được cả các cú quét thanh khoản (wick) qua SMA50 1-2%
    sma50_lower_bound = current_sma50 * 0.99   # chấp nhận thủng SMA50 tối đa 1%
    in_pullback_zone = (
        current_sma50 > 0
        and current_ema21 > 0
        and sma50_lower_bound <= current_close <= current_ema21
    )
    is_bullish_candle = current_close > current_open   # Nến xanh — xác nhận lực mua

    # ── SFP (Swing Failure Pattern): Quét thanh khoản đỉnh/đáy 50 phiên ──────
    # Bull SFP (bắt đáy): nến hiện tại xuyên râu xuống dưới support rồi đóng cửa trên support
    sfp_bull = (
        support > 0
        and current_low < support          # râu nến quét qua đáy support
        and current_close > support        # nhưng đóng cửa quay lại trên support
        and current_rsi < 45              # xác nhận vùng giá thấp
    )
    # Bear SFP (bắt đỉnh): nến xuyên râu lên trên resistance rồi đóng cửa dưới resistance
    sfp_bear = (
        resistance > 0
        and current_high > resistance      # râu nến quét qua đỉnh resistance
        and current_close < resistance     # nhưng đóng cửa quay lại dưới resistance
        and current_rsi > 55              # xác nhận vùng giá cao
    )
    
    # Xác định Hỗ trợ / Kháng cự từ mức thấp/cao nhất trong 50 nến gần đây
    recent_candles_50 = candles[-50:] if len(candles) >= 50 else candles
    support = min(c["low"] for c in recent_candles_50) if recent_candles_50 else 0.0
    resistance = max(c["high"] for c in recent_candles_50) if recent_candles_50 else 0.0
    
    # Đóng gói lịch sử 8 nến gần nhất để gửi cho AI
    history = []
    for c in candles[-8:]:
        history.append({
            "time": c["time"],
            "open": c["open"],
            "high": c["high"],
            "low": c["low"],
            "close": c["close"],
            "volume": c["volume"],
            "rsi": c["rsi"],
            "ema9": c["ema9"],
            "ema21": c["ema21"],
            "sma50": c["sma50"],
            "sma200": c["sma200"],
            "macd": c["macd"],
            "macd_signal": c["macd_signal"],
            "macd_hist": c["macd_hist"],
            "bb_upper": c["bb_upper"],
            "bb_middle": c["bb_middle"],
            "bb_lower": c["bb_lower"]
        })
        
    # Quét qua các nến trước đó (nến -2 và -3 tương ứng 15p và 30p trước)
    # để tìm các tín hiệu Mua/Bán đã kích hoạt nhưng có thể đã bị bỏ qua.
    missed_signals = []
    for offset in [-2, -3]:
        if len(candles) < abs(offset) + 2:
            continue
            
        t = len(candles) + offset
        
        rsi_val = rsi_list[t]
        ema9_val = ema9_list[t]
        ema21_val = ema21_list[t]
        prev_ema9_val = ema9_list[t - 1]
        prev_ema21_val = ema21_list[t - 1]
        
        past_sig = None
        past_reason = ""
        
        if rsi_val < 30:
            past_sig = "STRONG BUY"
            past_reason = f"RSI dat {rsi_val:.1f} (Qua ban)"
        elif rsi_val > 70:
            past_sig = "STRONG SELL"
            past_reason = f"RSI dat {rsi_val:.1f} (Qua mua)"
        elif prev_ema9_val <= prev_ema21_val and ema9_val > ema21_val:
            past_sig = "BUY (Crossover)"
            past_reason = "EMA9 cat len tren EMA21"
        elif prev_ema9_val >= prev_ema21_val and ema9_val < ema21_val:
            past_sig = "SELL (Crossover)"
            past_reason = "EMA9 cat xuong duoi EMA21"
            
        if past_sig:
            past_close = close_prices[t]
            past_time = candles[t]["time"]
            age_min = abs(offset) * 15
            
            # Tính Hỗ trợ / Kháng cự tại thời điểm đó
            recent_t = candles[max(0, t - 50):t + 1]
            past_support = min(c["low"] for c in recent_t) if recent_t else 0.0
            past_resistance = max(c["high"] for c in recent_t) if recent_t else 0.0
            
            past_tp_sl = calculate_tp_sl(
                close=past_close,
                signal=past_sig,
                atr=atr_list[t],
                support=past_support,
                resistance=past_resistance,
                bb_upper=bb_up_list[t],
                bb_middle=bb_mid_list[t],
                bb_lower=bb_low_list[t]
            )
            
            # Đánh giá trạng thái lệnh hiện tại so với giá Close hiện tại
            current_close = close_prices[-1]
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

    # Tạo cấu trúc cơ bản cho kết quả trả về
    res = {
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
        "support": support,
        "resistance": resistance,
        "history": history,
        "missed_signals": missed_signals,
        # Trạng thái xu hướng cho AI analyst
        "trend_context": {
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
        }
    }

    def _finalize(sig: str, reason: str) -> dict:
        """Gán signal, tính TP/SL và trả về kết quả cuối."""
        res["signal"] = sig
        res["reason"] = reason
        res["tp_sl"] = calculate_tp_sl(
            close       = close_prices[-1],
            signal      = sig,
            atr         = current_atr,
            support     = support,
            resistance  = resistance,
            bb_upper    = current_bb_upper,
            bb_middle   = current_bb_middle,
            bb_lower    = current_bb_lower,
        )
        return res

    # ══════════════════════════════════════════════════════════════════════
    # QUYẾT ĐỊNH TÍN HIỆU — 5 LỚP LỌC (ưu tiên từ cao xuống thấp)
    # ══════════════════════════════════════════════════════════════════════

    prev_ema9 = ema9_list[-2]
    prev_ema21 = ema21_list[-2]
    ema_golden_cross = (prev_ema9 <= prev_ema21) and (current_ema9 > current_ema21)
    ema_death_cross  = (prev_ema9 >= prev_ema21) and (current_ema9 < current_ema21)
    ema_bearish_active = current_ema9 < current_ema21

    # ─── LỚP -1: CHANDELIER EXIT — Màng lọc tối cao trước mọi lớp khác ───────
    # Khi Chandelier = BEAR, CẤM tất cả lệnh BUY (trừ SFP bắt đáy khẩn cấp).
    # Bảo vệ bot khỏi các pha sideway gập ghềnh làm bẻ gãy MA.
    chandelier_blocks_buy = (chandelier_state == "BEAR")

    # ─── LỚP 0: RSI ĐẢO CHIỀU có xác nhận Volume ──────────────────────────────
    # Không vào lệnh khi RSI vừa chạm vùng cực đoan mà phải đợi RSI CẮT QUA ngưỡng
    # kết hợp Volume Spike để xác nhận có dòng tiền thực sự đỡ giá/bán ra.
    if rsi_turning_up:
        vol_note = " + Volume Spike (dong tien lon do day)" if vol_spike else " (volume trung binh - can them xac nhan)"
        if above_sma200 and not chandelier_blocks_buy:
            return _finalize(
                "STRONG BUY (Confirmed Reversal)",
                f"RSI cat len tren 30 (dao chieu tu Oversold){vol_note} | Tren SMA200"
            )
        else:
            return _finalize(
                "BUY (Counter-Trend Reversal - High Risk)",
                f"RSI cat len tren 30 (dao chieu tu Oversold){vol_note}"
                + (" | Chandelier=BEAR: rui ro cao!" if chandelier_blocks_buy else "")
                + (" | Ben duoi SMA200 - CAUTION" if not above_sma200 else "")
            )

    if rsi_turning_down:
        vol_note = " + Volume Spike (xa hang manh)" if vol_spike else " (volume trung binh)"
        return _finalize(
            "STRONG SELL (Confirmed Reversal)",
            f"RSI cat xuong duoi 70 (dao chieu tu Overbought){vol_note}"
            + (" | Ben tren SMA200 - co the chi la dieu chinh" if above_sma200 else "")
        )

    # ─── LỚP 0.5: SFP — Swing Failure Pattern (Smart Money / Quét thanh khoản) ─
    # Chiến lược Smart Money: cá mập quét SL nhỏ lẻ rồi kéo ngược → tỷ lệ thắng cao
    if sfp_bull and not chandelier_blocks_buy:
        return _finalize(
            "BUY (SFP-Liquidity-Sweep)",
            f"Quet thanh khoan day: wick xuyen SL duoi {support:.2f} roi dong cua tren support | RSI={current_rsi:.1f}"
            + (" | Bull Market (SMA200 xac nhan)" if above_sma200 else " | Bear Market - rui ro cao hon")
        )

    if sfp_bear:
        return _finalize(
            "SELL (SFP-Liquidity-Sweep)",
            f"Quet thanh khoan dinh: wick vuot {resistance:.2f} roi dong cua duoi resistance | RSI={current_rsi:.1f}"
            + (" | Bear Market (SMA200 xac nhan)" if below_sma200 else " | Bull Market - co the chi la fakeout")
        )

    # ─── LỚP 1: EMA CROSSOVER + CHANDELIER + SMA200 FILTER ───────────────────
    if ema_golden_cross:
        if chandelier_blocks_buy:
            # Chandelier đang BEAR → BUY bị chặn dù EMA cross
            return _finalize(
                "WEAK BUY (Crossover-Blocked)",
                "EMA9 cat len EMA21 NHUNG Chandelier=BEAR — thi truong dang downtrend theo ATR, chu y!"
            )
        if above_sma200:
            return _finalize(
                "BUY (Crossover)",
                "EMA9 cat len EMA21 + Chandelier=BULL + Gia tren SMA200 (Bull Market confirmed)"
            )
        elif current_sma200 > 0:
            return _finalize(
                "WEAK BUY (Crossover)",
                "EMA9 cat len EMA21 NHUNG gia duoi SMA200 — co the la bull trap!"
            )
        else:
            return _finalize(
                "BUY (Crossover)",
                "EMA9 cat len EMA21 (Xu huong tang — chua du du lieu SMA200)"
            )

    if ema_death_cross:
        if below_sma200:
            return _finalize(
                "SELL (Crossover)",
                "EMA9 cat xuong EMA21 + Gia duoi SMA200 (Bear Market confirmed)"
            )
        elif current_sma200 > 0:
            return _finalize(
                "WEAK SELL (Crossover)",
                "EMA9 cat xuong EMA21 NHUNG gia tren SMA200 — co the chi la dieu chinh"
            )
        else:
            return _finalize(
                "SELL (Crossover)",
                "EMA9 cat xuong EMA21 (Xu huong giam — chua du du lieu SMA200)"
            )

    # ─── LỚP 2: PULLBACK ZONE (EMA21 ↔ SMA50) + Nến xanh xác nhận ───────────
    # Thay thế near_sma50 0.5% cũ bằng vùng giá rộng hơn EMA21↔SMA50(±1%)
    # Bắt điểm pullback đúng chuẩn, không bỏ lỡ các pha quét thanh khoản
    if (
        ema_bearish_active
        and in_pullback_zone
        and is_bullish_candle          # Nến xanh xác nhận lực mua tại vùng hỗ trợ
        and sma50_uptrend
        and above_sma200
        and not chandelier_blocks_buy
        and current_rsi < 55
    ):
        return _finalize(
            "BUY (Pullback-Zone)",
            f"Gia dieu chinh vao vung EMA21({current_ema21:.2f})-SMA50({current_sma50:.2f}), "
            f"nen xanh xac nhan | SMA50 doc len | SMA200 phia duoi | Chandelier=BULL"
        )

    # Trailing Stop: đóng cửa thủng SMA50 khi SMA50 đang dốc xuống
    if (
        ema_bearish_active
        and not above_sma50
        and sma50_downtrend
        and current_sma50 > 0
    ):
        return _finalize(
            "SELL (Break-SMA50)",
            f"Gia dong cua xuyen thung SMA50 ({current_sma50:.2f}) — trailing stop kich hoat!"
        )

    # ─── LỚP 3: TRẠNG THÁI XU HƯỚNG (Trend-following với đầy đủ context) ─────
    chandelier_tag = f" | Chandelier={chandelier_state}"
    if current_ema9 > current_ema21:
        if above_sma200 and sma50_uptrend and not chandelier_blocks_buy:
            return _finalize(
                "NEUTRAL (BULLISH)",
                f"Xu huong tang manh: EMA9>EMA21, tren SMA50+SMA200{chandelier_tag}"
            )
        elif above_sma200:
            return _finalize(
                "NEUTRAL (BULLISH)",
                f"Xu huong tang: EMA9>EMA21, tren SMA200 (SMA50 chua xac nhan){chandelier_tag}"
            )
        else:
            return _finalize(
                "NEUTRAL (BULLISH-CAUTION)",
                f"EMA9>EMA21 nhung duoi SMA200 — thi truong lon van giam{chandelier_tag}"
            )
    else:
        if below_sma200 and sma50_downtrend:
            return _finalize(
                "NEUTRAL (BEARISH)",
                f"Xu huong giam manh: EMA9<EMA21, duoi SMA50+SMA200{chandelier_tag}"
            )
        elif below_sma200:
            return _finalize(
                "NEUTRAL (BEARISH)",
                f"Xu huong giam: EMA9<EMA21, duoi SMA200{chandelier_tag}"
            )
        else:
            return _finalize(
                "NEUTRAL (BEARISH-CAUTION)",
                f"EMA9<EMA21 nhung tren SMA200 — co the chi la dieu chinh ngan han{chandelier_tag}"
            )
