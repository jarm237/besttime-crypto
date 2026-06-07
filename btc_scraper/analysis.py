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
    Trả về chỉ số hiện tại (RSI, EMA9, EMA21, MACD, Bollinger Bands, Support/Resistance) và Tín hiệu hành động khuyến nghị.
    """
    if not candles or "error" in candles[0]:
        return {
            "rsi": 50.0,
            "ema9": 0.0,
            "ema21": 0.0,
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
    macd_list, macd_sig_list, macd_hist_list = calculate_macd(close_prices, 12, 26, 9)
    bb_up_list, bb_mid_list, bb_low_list = calculate_bollinger_bands(close_prices, 20, 2)
    atr_list = calculate_atr(candles, 14)
    
    # Ghi lại chỉ số vào nến để hiển thị
    for i, c in enumerate(candles):
        c["rsi"] = rsi_list[i]
        c["ema9"] = ema9_list[i]
        c["ema21"] = ema21_list[i]
        c["macd"] = macd_list[i]
        c["macd_signal"] = macd_sig_list[i]
        c["macd_hist"] = macd_hist_list[i]
        c["bb_upper"] = bb_up_list[i]
        c["bb_middle"] = bb_mid_list[i]
        c["bb_lower"] = bb_low_list[i]
        c["atr"] = atr_list[i] if i < len(atr_list) else 0.0
        
    current_rsi = rsi_list[-1]
    current_ema9 = ema9_list[-1]
    current_ema21 = ema21_list[-1]
    current_macd = macd_list[-1]
    current_macd_signal = macd_sig_list[-1]
    current_macd_hist = macd_hist_list[-1]
    current_bb_upper = bb_up_list[-1]
    current_bb_middle = bb_mid_list[-1]
    current_bb_lower = bb_low_list[-1]
    current_atr = atr_list[-1] if atr_list else 0.0
    
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
        "missed_signals": missed_signals
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

    # Quyết định tín hiệu (Quy tắc đơn giản nhưng hiệu quả)
    # 1. RSI Quá mua / Quá bán
    if current_rsi < 30:
        return _finalize("STRONG BUY", f"RSI dat {current_rsi:.1f} (Qua ban / Oversold)")
    elif current_rsi > 70:
        return _finalize("STRONG SELL", f"RSI dat {current_rsi:.1f} (Qua mua / Overbought)")
        
    # 2. Xu hướng giao cắt EMA
    prev_ema9 = ema9_list[-2]
    prev_ema21 = ema21_list[-2]
    
    if prev_ema9 <= prev_ema21 and current_ema9 > current_ema21:
        return _finalize("BUY (Crossover)", "EMA9 cat len tren EMA21 (Xu huong tang)")
    elif prev_ema9 >= prev_ema21 and current_ema9 < current_ema21:
        return _finalize("SELL (Crossover)", "EMA9 cat xuong duoi EMA21 (Xu huong giam)")
        
    # 3. Trạng thái giữ nguyên (Trend-following)
    if current_ema9 > current_ema21:
        return _finalize("NEUTRAL (BULLISH)", "Gia dang nam trong xu huong tang")
    else:
        return _finalize("NEUTRAL (BEARISH)", "Gia dang nam trong xu huong giam")
