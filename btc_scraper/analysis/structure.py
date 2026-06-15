import math

def _percentile_rank(value: float, values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return 100.0 if values[0] <= value else 0.0
    count = sum(1 for x in values if x <= value)
    return float(count) / len(values) * 100.0


def _calculate_slope(values: list[float], idx: int, lookback: int = 4) -> float:
    if idx < lookback or values[idx - lookback] == 0.0:
        return 0.0
    prev = values[idx - lookback]
    return (values[idx] - prev) / abs(prev) * 100.0


def _calculate_realized_volatility(prices: list[float], idx: int, lookback: int) -> float:
    if idx < lookback or lookback < 2:
        return 0.0
    returns = []
    for j in range(idx - lookback + 1, idx + 1):
        prev = prices[j - 1]
        if prev > 0:
            returns.append(math.log(prices[j] / prev))
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((x - mean) ** 2 for x in returns) / len(returns)
    return math.sqrt(variance) * math.sqrt(lookback)


def _calculate_obv(candles: list[dict]) -> list[float]:
    obv = []
    current = 0.0
    for i, c in enumerate(candles):
        if i == 0:
            obv.append(0.0)
            continue
        prev_close = candles[i - 1]["close"]
        volume = c.get("volume", 0.0)
        if c["close"] > prev_close:
            current += volume
        elif c["close"] < prev_close:
            current -= volume
        obv.append(current)
    return obv


def _calculate_cmf(highs: list[float], lows: list[float], closes: list[float], volumes: list[float], period: int = 20) -> list[float]:
    n = len(closes)
    result = [0.0] * n
    if n < period:
        return result
    money_flow = [0.0] * n
    for i in range(n):
        high = highs[i]
        low = lows[i]
        close = closes[i]
        volume = volumes[i]
        denom = max(high - low, 1e-9)
        money_flow_multiplier = ((close - low) - (high - close)) / denom
        money_flow[i] = money_flow_multiplier * volume
    for i in range(period - 1, n):
        window = money_flow[i - period + 1 : i + 1]
        positive = sum(x for x in window if x > 0)
        negative = sum(-x for x in window if x < 0)
        denom = positive + negative
        result[i] = positive / denom if denom > 0 else 0.0
    return result


def _calculate_mfi(highs: list[float], lows: list[float], closes: list[float], volumes: list[float], period: int = 14) -> list[float]:
    n = len(closes)
    result = [0.0] * n
    if n < period + 1:
        return result
    typical_prices = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]
    money_flows = [typical_prices[i] * volumes[i] for i in range(n)]
    for i in range(period, n):
        positive = 0.0
        negative = 0.0
        for j in range(i - period + 1, i + 1):
            if typical_prices[j] > typical_prices[j - 1]:
                positive += money_flows[j]
            elif typical_prices[j] < typical_prices[j - 1]:
                negative += money_flows[j]
        if negative <= 0.0:
            result[i] = 100.0
        else:
            money_ratio = positive / negative if negative else 0.0
            result[i] = 100.0 - (100.0 / (1.0 + money_ratio))
    return result


def _structure_flags(candles: list[dict], idx: int, lookback: int = 20) -> tuple[float, float, float, float, float]:
    if idx <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    start = max(0, idx - lookback)
    highs = [c["high"] for c in candles[start:idx]]
    lows = [c["low"] for c in candles[start:idx]]
    if not highs or not lows:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    prev_high = max(highs)
    prev_low = min(lows)
    current = candles[idx]
    current_close = current["close"]
    current_high = current["high"]
    current_low = current["low"]
    distance_support_pct = ((current_close - prev_low) / current_close * 100.0) if current_close else 0.0
    distance_resistance_pct = ((prev_high - current_close) / current_close * 100.0) if current_close else 0.0
    higher_high = 1.0 if current_high > prev_high else 0.0
    lower_low = 1.0 if current_low < prev_low else 0.0
    market_structure_break = 1.0 if current_close > prev_high or current_close < prev_low else 0.0
    return distance_support_pct, distance_resistance_pct, higher_high, lower_low, market_structure_break


def _make_window(values: list[float], idx: int, window: int) -> list[float]:
    if idx < 0:
        idx = len(values) + idx
    start = max(0, idx - window + 1)
    return values[start : idx + 1]


def _lookback_return(prices: list[float], idx: int, bars: int) -> float:
    if idx < bars or prices[idx - bars] == 0.0:
        return 0.0
    return (prices[idx] / prices[idx - bars] - 1.0) * 100.0


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


def wick_ratios(open_price: float, high: float, low: float, close_price: float) -> tuple[float, float]:
    body_top = max(open_price, close_price)
    body_bottom = min(open_price, close_price)
    full_range = max(high - low, 1e-9)
    lower_wick = max(body_bottom - low, 0.0)
    upper_wick = max(high - body_top, 0.0)
    return lower_wick / full_range, upper_wick / full_range


def calculate_smc_structure(candles: list[dict], swing_length: int = 5) -> tuple[list[float], list[float], list[float], list[float]]:
    """
    Tính toán BOS và CHOCH chặt chẽ theo Smart Money Concepts (Strict SMC).
    Trả về 4 list: bos_bull, bos_bear, choch_bull, choch_bear (0.0 hoac 1.0)
    """
    n = len(candles)
    bos_bull = [0.0] * n
    bos_bear = [0.0] * n
    choch_bull = [0.0] * n
    choch_bear = [0.0] * n

    if n < swing_length * 2 + 1:
        return bos_bull, bos_bear, choch_bull, choch_bear

    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]

    # Lưu trữ index của Swing gần nhất
    last_swing_high_idx = -1
    last_swing_low_idx = -1
    
    # Trend: 1 (Bullish), -1 (Bearish), 0 (Neutral)
    current_trend = 0

    for i in range(swing_length * 2, n):
        # Kiểm tra xem nến ở i - swing_length có phải là Swing High không
        # Nó phải cao hơn swing_length nến trước và swing_length nến sau
        check_idx = i - swing_length
        is_swing_high = True
        is_swing_low = True
        
        check_high = highs[check_idx]
        check_low = lows[check_idx]
        
        for j in range(check_idx - swing_length, check_idx + swing_length + 1):
            if j == check_idx: continue
            if highs[j] >= check_high:
                is_swing_high = False
            if lows[j] <= check_low:
                is_swing_low = False
                
        if is_swing_high:
            last_swing_high_idx = check_idx
            
        if is_swing_low:
            last_swing_low_idx = check_idx

        # Tại nến i hiện tại, giá đóng cửa có phá vỡ mốc nào không?
        current_close = closes[i]
        
        if last_swing_high_idx != -1 and current_close > highs[last_swing_high_idx]:
            last_swing_high_idx = -1 # Đã phá vỡ, reset mốc
            if current_trend == 1 or current_trend == 0:
                bos_bull[i] = 1.0
                current_trend = 1
            elif current_trend == -1:
                choch_bull[i] = 1.0
                current_trend = 1
                
        if last_swing_low_idx != -1 and current_close < lows[last_swing_low_idx]:
            last_swing_low_idx = -1
            if current_trend == -1 or current_trend == 0:
                bos_bear[i] = 1.0
                current_trend = -1
            elif current_trend == 1:
                choch_bear[i] = 1.0
                current_trend = -1

    return bos_bull, bos_bear, choch_bull, choch_bear
