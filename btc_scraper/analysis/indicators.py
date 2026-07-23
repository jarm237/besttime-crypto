import math
import numpy as np
import pandas as pd

def calculate_sma(prices: list[float], period: int) -> list[float]:
    """Tính toán Simple Moving Average (SMA) bằng Pandas."""
    if len(prices) < period:
        return [0.0] * len(prices)
    s = pd.Series(prices)
    sma = s.rolling(window=period, min_periods=period).mean().fillna(0.0)
    return sma.tolist()


def calculate_ema(prices: list[float], period: int) -> list[float]:
    """Tính toán Exponential Moving Average (EMA) bằng Pandas."""
    if len(prices) < period:
        return [0.0] * len(prices)
    s = pd.Series(prices)
    sma = s.iloc[:period].mean()
    
    # Khởi tạo EMA bằng SMA của `period` điểm đầu, rồi smooth
    s2 = pd.concat([pd.Series([sma]), s.iloc[period:]], ignore_index=True)
    res = s2.ewm(span=period, adjust=False).mean()
    final = [0.0] * (period - 1) + res.tolist()
    return final


def calculate_atr(candles: list[dict], period: int = 14) -> list[float]:
    """Tính toán Average True Range (ATR) bằng Pandas."""
    if len(candles) < period + 1:
        return [c["high"] - c["low"] for c in candles]
    
    df = pd.DataFrame(candles)
    high = df['high']
    low = df['low']
    prev_close = df['close'].shift(1)
    
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    sma = tr.iloc[:period].mean()
    s2 = pd.concat([pd.Series([sma]), tr.iloc[period:]], ignore_index=True)
    # Wilder's Smoothing = EMA với alpha = 1/period
    res = s2.ewm(alpha=1/period, adjust=False).mean()
    final = [0.0] * (period - 1) + res.tolist()
    return final


def calculate_macd(prices: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[list[float], list[float], list[float]]:
    """Tính toán MACD Line, Signal Line và Histogram."""
    ema_fast = np.array(calculate_ema(prices, fast))
    ema_slow = np.array(calculate_ema(prices, slow))
    
    macd_line = np.where((ema_fast == 0.0) | (ema_slow == 0.0), 0.0, ema_fast - ema_slow)
    
    first_valid_idx = slow - 1
    if len(prices) <= first_valid_idx + signal:
        return [0.0]*len(prices), [0.0]*len(prices), [0.0]*len(prices)
        
    macd_valid_part = macd_line[first_valid_idx:].tolist()
    signal_valid_part = calculate_ema(macd_valid_part, signal)
    
    signal_line = np.array([0.0] * first_valid_idx + signal_valid_part)
    hist = np.where((macd_line == 0.0) | (signal_line == 0.0), 0.0, macd_line - signal_line)
    
    return macd_line.tolist(), signal_line.tolist(), hist.tolist()


def calculate_bollinger_bands(prices: list[float], period: int = 20, num_std: int = 2) -> tuple[list[float], list[float], list[float]]:
    """Tính toán Bollinger Bands (Upper, Middle, Lower)."""
    if len(prices) < period:
        return [0.0]*len(prices), [0.0]*len(prices), [0.0]*len(prices)
    
    s = pd.Series(prices)
    sma = s.rolling(window=period, min_periods=period).mean().fillna(0.0)
    std_dev = s.rolling(window=period, min_periods=period).std(ddof=0).fillna(0.0)
    
    sma_np = sma.to_numpy()
    std_dev_np = std_dev.to_numpy()
    
    upper = np.where(sma_np == 0.0, 0.0, sma_np + num_std * std_dev_np)
    lower = np.where(sma_np == 0.0, 0.0, sma_np - num_std * std_dev_np)
    
    return upper.tolist(), sma_np.tolist(), lower.tolist()


def calculate_volume_sma(candles: list[dict], period: int = 20) -> list[float]:
    """Tính SMA của Volume trong `period` phiên."""
    volumes = [c.get("volume", 0.0) for c in candles]
    return calculate_sma(volumes, period)


def calculate_chandelier_exit(candles: list[dict], period: int = 22, multiplier: float = 3.0) -> list[str]:
    """Chandelier Exit."""
    n = len(candles)
    if n < period + 1:
        return ["UNKNOWN"] * n

    df = pd.DataFrame(candles)
    atr_list = calculate_atr(candles, period)
    atr_s = pd.Series(atr_list)
    atr_ma = atr_s.rolling(window=period, min_periods=period).mean().fillna(0.0)
    
    highest_high = df['high'].rolling(window=period, min_periods=period).max().fillna(0.0)
    lowest_low = df['low'].rolling(window=period, min_periods=period).min().fillna(0.0)
    
    atr_used = np.where(atr_ma > 0, np.minimum(atr_s, atr_ma * 1.5), atr_s)
    atr_shock = (atr_ma > 0) & (atr_s > atr_ma * 1.8)
    
    long_stop = highest_high - multiplier * atr_used
    short_stop = lowest_low + multiplier * atr_used
    close = df['close']
    
    result = ["UNKNOWN"] * n
    for i in range(period - 1, n):
        if atr_s.iloc[i] == 0.0:
            continue
        if atr_shock.iloc[i]:
            result[i] = result[i-1] if result[i-1] != "UNKNOWN" else "UNKNOWN"
        elif close.iloc[i] > short_stop.iloc[i]:
            result[i] = "BULL"
        elif close.iloc[i] < long_stop.iloc[i]:
            result[i] = "BEAR"
        else:
            result[i] = result[i-1] if result[i-1] != "UNKNOWN" else "UNKNOWN"
            
    return result


def calculate_rsi(prices: list[float], period: int = 14) -> list[float]:
    """Tính toán Relative Strength Index (RSI)."""
    if len(prices) <= period:
        return [50.0] * len(prices)
        
    s = pd.Series(prices)
    delta = s.diff()
    gain = np.maximum(delta, 0.0)
    loss = np.maximum(-delta, 0.0)
    
    avg_gain = gain.iloc[1:period+1].mean()
    avg_loss = loss.iloc[1:period+1].mean()
    
    rs_list = [50.0] * period
    
    s2_gain = pd.concat([pd.Series([avg_gain]), gain.iloc[period+1:]], ignore_index=True)
    s2_loss = pd.concat([pd.Series([avg_loss]), loss.iloc[period+1:]], ignore_index=True)
    
    ewm_gain = s2_gain.ewm(alpha=1/period, adjust=False).mean()
    ewm_loss = s2_loss.ewm(alpha=1/period, adjust=False).mean()
    
    rs = ewm_gain / ewm_loss
    rsi_vals = 100.0 - (100.0 / (1.0 + rs))
    both_zero = (ewm_gain == 0) & (ewm_loss == 0)
    only_loss_zero = (ewm_gain > 0) & (ewm_loss == 0)
    only_gain_zero = (ewm_gain == 0) & (ewm_loss > 0)
    rsi_vals = np.select(
        [both_zero, only_loss_zero, only_gain_zero],
        [50.0, 100.0, 0.0],
        default=rsi_vals,
    )
    
    final = rs_list + rsi_vals.tolist()
    return final[:len(prices)]


def calculate_adx(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """Calculate ADX to measure trend strength using Pandas."""
    n = len(highs)
    if n < period + 1:
        return [0.0] * n

    df = pd.DataFrame({"high": highs, "low": lows, "close": closes})
    prev_high = df["high"].shift(1)
    prev_low = df["low"].shift(1)
    prev_close = df["close"].shift(1)

    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move = df["high"] - prev_high
    down_move = prev_low - df["low"]

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_s = pd.Series(tr)
    plus_dm_s = pd.Series(plus_dm)
    minus_dm_s = pd.Series(minus_dm)

    atr_init = tr_s.iloc[1:period+1].mean()
    plus_dm_init = plus_dm_s.iloc[1:period+1].sum()
    minus_dm_init = minus_dm_s.iloc[1:period+1].sum()

    atr_smooth = pd.concat([pd.Series([atr_init]), tr_s.iloc[period+1:]], ignore_index=True).ewm(alpha=1/period, adjust=False).mean()
    plus_dm_smooth = pd.concat([pd.Series([plus_dm_init]), plus_dm_s.iloc[period+1:]], ignore_index=True).ewm(alpha=1/period, adjust=False).mean()
    minus_dm_smooth = pd.concat([pd.Series([minus_dm_init]), minus_dm_s.iloc[period+1:]], ignore_index=True).ewm(alpha=1/period, adjust=False).mean()

    # To calculate di correctly, we need to match the indices. The smoothed series start at `period`.
    plus_di = np.where(atr_smooth > 0, 100.0 * plus_dm_smooth / atr_smooth, 0.0)
    minus_di = np.where(atr_smooth > 0, 100.0 * minus_dm_smooth / atr_smooth, 0.0)

    denom = plus_di + minus_di
    dx = np.where(denom > 0, 100.0 * np.abs(plus_di - minus_di) / denom, 0.0)
    dx_s = pd.Series(dx)

    adx_init_val = dx_s.iloc[:period].mean() # This corresponds to dx[period : period*2]
    # Actually, the original ADX initializes with SMA of the first `period` DX values.
    # We have `n - period` values in dx_s.
    if len(dx_s) > period:
        adx_smooth = pd.concat([pd.Series([adx_init_val]), dx_s.iloc[period:]], ignore_index=True).ewm(alpha=1/period, adjust=False).mean()
        adx_res = adx_smooth.to_list()
    else:
        adx_res = dx_s.to_list()

    # The original implementation puts the first ADX value at `period*2 - 1` (or `period`).
    # We pad with 0.0 up to the correct alignment.
    padding = n - len(adx_res)
    final = [0.0] * padding + adx_res
    return final[:n]


def calculate_choppiness_index(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """Calculate Choppiness Index to detect trending vs choppy market."""
    n = len(highs)
    if n < period:
        return [0.0] * n
    df = pd.DataFrame({"high": highs, "low": lows, "close": closes})
    prev_close = df["close"].shift(1)
    
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    tr_sum = tr.rolling(window=period, min_periods=period).sum()
    window_high = df["high"].rolling(window=period, min_periods=period).max()
    window_low = df["low"].rolling(window=period, min_periods=period).min()
    
    dist = window_high - window_low
    safe_dist = np.where(dist <= 0, 1.0, dist)
    safe_tr_sum = np.where(tr_sum <= 0, 1.0, tr_sum)
    
    chop = 100.0 * np.log10(safe_tr_sum / safe_dist) / math.log10(period)
    chop = np.where(dist <= 0, 0.0, chop)
    return np.nan_to_num(chop, nan=0.0).tolist()


def calculate_roc(prices: list[float], period: int) -> list[float]:
    """Calculate Rate of Change (Momentum)."""
    n = len(prices)
    if n < period:
        return [0.0] * n
    s = pd.Series(prices)
    shift_s = s.shift(period)
    roc = np.where(shift_s > 0, (s / shift_s - 1.0) * 100.0, 0.0)
    return np.nan_to_num(roc, nan=0.0).tolist()


def calculate_hv(prices: list[float], period: int, periods_per_year: int = 35040) -> list[float]:
    """Calculate Annualized Historical Volatility."""
    n = len(prices)
    if n < period:
        return [0.0] * n
    s = pd.Series(prices)
    prev_s = s.shift(1)
    log_returns = np.where(prev_s > 0, np.log(s / prev_s), 0.0)
    
    lr_s = pd.Series(log_returns)
    variance = lr_s.rolling(window=period, min_periods=period).var(ddof=1).fillna(0.0)
    
    hv = np.sqrt(variance) * math.sqrt(periods_per_year) * 100.0
    return np.nan_to_num(hv, nan=0.0).tolist()
