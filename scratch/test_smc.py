import math

def calculate_roc(prices: list[float], period: int) -> list[float]:
    n = len(prices)
    result = [0.0] * n
    for i in range(period, n):
        if prices[i - period] > 0:
            result[i] = (prices[i] / prices[i - period] - 1.0) * 100.0
    return result

def calculate_hv(prices: list[float], period: int, periods_per_year: int = 35040) -> list[float]:
    n = len(prices)
    result = [0.0] * n
    # Tính log returns
    log_returns = [0.0] * n
    for i in range(1, n):
        if prices[i-1] > 0:
            log_returns[i] = math.log(prices[i] / prices[i-1])
    
    annualization_factor = math.sqrt(periods_per_year)
    for i in range(period, n):
        window = log_returns[i - period + 1 : i + 1]
        mean = sum(window) / period
        variance = sum((x - mean)**2 for x in window) / (period - 1) if period > 1 else 0.0
        result[i] = math.sqrt(variance) * annualization_factor * 100.0 # ra %
    return result

def calculate_smc_structure(candles: list[dict], swing_length: int = 5) -> tuple[list[float], list[float], list[float], list[float]]:
    """
    Tính toán BOS và CHOCH chặt chẽ theo Smart Money Concepts.
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
            # Nếu có đỉnh mới, cập nhật
            # Trong một số biến thể SMC, đỉnh mới phải cao hơn đỉnh cũ (trong uptrend)
            # nhưng ta lấy đỉnh gần nhất làm mốc để phá vỡ.
            last_swing_high_idx = check_idx
            
        if is_swing_low:
            last_swing_low_idx = check_idx

        # Bây giờ, tại nến i hiện tại, giá đóng cửa có phá vỡ mốc nào không?
        current_close = closes[i]
        
        if last_swing_high_idx != -1 and current_close > highs[last_swing_high_idx]:
            # Xóa mốc để không bị trigger lại liên tục trong các nến tiếp theo
            # Cho đến khi có swing high mới
            last_swing_high_idx = -1 
            
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

if __name__ == "__main__":
    print("Testing SMC logic with mock data...")
    # Trend up, swing low, trend up (BOS), swing high, trend down (CHOCH)
    mock_candles = [
        {"high": 10, "low": 5, "close": 8},
        {"high": 12, "low": 6, "close": 11},
        {"high": 14, "low": 8, "close": 13},  # Swing High candidate?
        {"high": 13, "low": 7, "close": 9},
        {"high": 11, "low": 6, "close": 7},
        {"high": 12, "low": 4, "close": 8},  # Swing Low candidate?
        {"high": 15, "low": 9, "close": 14}, # Break above Swing High -> Bullish BOS
        {"high": 17, "low": 12, "close": 16}, # New Swing High candidate
        {"high": 16, "low": 10, "close": 11},
        {"high": 14, "low": 9, "close": 10},
        {"high": 13, "low": 8, "close": 9},
        {"high": 12, "low": 7, "close": 8},
        {"high": 11, "low": 3, "close": 4},   # Break below Swing Low -> Bearish CHOCH
    ]
    # For a real test, we need more padding candles because swing_length=5
    # Since n=13, swing_length=2 is better for this tiny mock
    bos_bull, bos_bear, choch_bull, choch_bear = calculate_smc_structure(mock_candles, swing_length=2)
    for i in range(len(mock_candles)):
        print(f"Candle {i}: close={mock_candles[i]['close']} BOS_BULL={bos_bull[i]} BOS_BEAR={bos_bear[i]} CHOCH_BULL={choch_bull[i]} CHOCH_BEAR={choch_bear[i]}")
    print("Test finished.")
