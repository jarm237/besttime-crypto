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

