import os
import csv
import math
import json
from datetime import datetime
from btc_scraper.analysis import analyze_all_market

def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0

def pearson_correlation(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 2 or len(y) != n:
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    
    num = 0.0
    den_x = 0.0
    den_y = 0.0
    for i in range(n):
        dx = x[i] - mean_x
        dy = y[i] - mean_y
        num += dx * dy
        den_x += dx * dx
        den_y += dy * dy
    if den_x == 0.0 or den_y == 0.0:
        return 0.0
    return num / math.sqrt(den_x * den_y)

def load_csv_data(filepath: str) -> list[dict]:
    candles = []
    with open(filepath, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append({
                "time": row["time"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
    return candles

from btc_scraper.config import COINS

def run_backtest(initial_balance: float = 10000.0, sentiment_penalty: float | None = None):
    data_dir = "data"
    # Lọc danh sách coin có sẵn file dữ liệu lịch sử
    coins = [c for c in COINS if os.path.exists(os.path.join(data_dir, f"{c}_15m.csv"))]
    if not coins:
        coins = [f.split("_")[0] for f in os.listdir(data_dir) if f.endswith("_15m.csv") and not f.startswith("april_")]
    
    # 1. Load data & run analysis for each coin
    candles_dict = {}
    analysis_dict = {}
    
    print(f"[Backtest] Đang tải dữ liệu và tính toán chỉ báo cho {len(coins)} coin: {', '.join(coins)}...")
    for coin in coins:
        csv_path = os.path.join(data_dir, f"{coin}_15m.csv")
        if not os.path.exists(csv_path):
            print(f"❌ Thiếu file dữ liệu: {csv_path}. Vui lòng chạy scraper trước.")
            return
        
        candles = load_csv_data(csv_path)
        # Sắp xếp theo thời gian tăng dần
        candles.sort(key=lambda x: x["time"])
        candles_dict[coin] = candles
        
        # Phân tích toàn bộ dữ liệu lịch sử
        analysis_dict[coin] = analyze_all_market(candles)
        print(f"  ↳ {coin}: Đã phân tích {len(analysis_dict[coin])} nến.")

    # 2. Khởi tạo trạng thái danh mục đầu tư
    balance = initial_balance
    cash = initial_balance
    open_positions = {} # coin: position_dict
    trade_log = []
    
    # Cấu hình tham số quản trị rủi ro chuyên nghiệp
    MAX_CONCURRENT_POSITIONS = 3
    RISK_PER_TRADE = 0.01  # Rủi ro 1% tài khoản trên mỗi trade
    FEE_RATE = 0.001       # Phí giao dịch 0.1%
    MIN_HOLD_CANDLES = 4   # Tối thiểu 4 nến (1 giờ) trước khi cho phép EXIT_SIGNAL
    MIN_RR = 1.5           # Chỉ vào lệnh khi RR ≥ 1.5
    
    # Danh sách tất cả các mốc thời gian (sắp xếp tăng dần)
    all_times = sorted(list(set(
        item["time"] for coin in coins for item in analysis_dict[coin]
    )))
    
    # Bản đồ tra cứu nhanh: time -> coin -> data
    lookup = {t: {} for t in all_times}
    for coin in coins:
        for item in analysis_dict[coin]:
            lookup[item["time"]][coin] = item

    # Bản đồ tra cứu index nhanh cho từng coin: coin -> time -> index
    time_to_idx = {
        coin: {c["time"]: i for i, c in enumerate(candles_dict[coin])}
        for coin in coins
    }

    print(f"\n[Backtest] Khởi chạy mô phỏng trên {len(all_times)} bước thời gian...")
    
    # Mảng lưu lịch sử tài sản để tính Max Drawdown
    equity_history = []
    
    for current_time in all_times:
        # 2.1 Cập nhật các lệnh đang mở (Exits)
        closed_coins = []
        
        # Tính toán Equity hiện tại
        current_equity = cash
        for coin, pos in open_positions.items():
            if coin in lookup[current_time]:
                current_price = lookup[current_time][coin]["close"]
                # Ước lượng giá trị hiện tại của vị thế
                if pos["type"] == "LONG":
                    current_equity += pos["units"] * current_price
                else: # SHORT
                    current_equity += pos["units"] * (2 * pos["entry"] - current_price)
        
        equity_history.append((current_time, current_equity))
        balance = current_equity
        
        for coin, pos in open_positions.items():
            if coin not in lookup[current_time]:
                continue
                
            coin_data = lookup[current_time][coin]
            high = coin_data["high"]
            low = coin_data["low"]
            close = coin_data["close"]
            
            # Kiểm tra thoát lệnh cho LONG
            if pos["type"] == "LONG":
                # Check Stop Loss (SL)
                if low <= pos["sl"]:
                    # Exit với mức SL
                    exit_price = pos["sl"]
                    pnl_raw = pos["units"] * (exit_price - pos["entry"])
                    fee = (pos["units"] * pos["entry"] + pos["units"] * exit_price) * FEE_RATE
                    pnl_net = pnl_raw - fee
                    cash += (pos["units"] * exit_price) - fee
                    
                    trade_log.append({
                        "coin": coin,
                        "type": "LONG",
                        "entry_time": pos["entry_time"],
                        "exit_time": current_time,
                        "entry_price": pos["entry"],
                        "exit_price": exit_price,
                        "pnl": pnl_net,
                        "result": "SL",
                        "r_multiplier": pnl_net / (pos["entry_risk"] if pos["entry_risk"] > 0 else 1.0),
                        "signal_score": pos.get("entry_signal_score"),
                        "confidence": pos.get("entry_confidence"),
                    })
                    closed_coins.append(coin)
                    continue
                
                # Check Take Profit 1 (TP1) - Đóng 50% vị thế
                if not pos["tp1_hit"] and high >= pos["tp1"]:
                    pos["tp1_hit"] = True
                    half_units = pos["units"] / 2
                    exit_price = pos["tp1"]
                    pnl_raw = half_units * (exit_price - pos["entry"])
                    fee = (half_units * pos["entry"] + half_units * exit_price) * FEE_RATE
                    pnl_net = pnl_raw - fee
                    cash += (half_units * exit_price) - fee
                    
                    # Ghi nhận một phần trade
                    pos["units"] -= half_units
                    pos["partial_pnl"] += pnl_net
                    pos["partial_exits"].append(("TP1", current_time, exit_price, pnl_net))
                
                # Check Take Profit 2 (TP2) - Đóng phần còn lại
                if high >= pos["tp2"]:
                    exit_price = pos["tp2"]
                    pnl_raw = pos["units"] * (exit_price - pos["entry"])
                    fee = (pos["units"] * pos["entry"] + pos["units"] * exit_price) * FEE_RATE
                    pnl_net = pnl_raw - fee
                    cash += (pos["units"] * exit_price) - fee
                    
                    total_pnl = pos["partial_pnl"] + pnl_net
                    trade_log.append({
                        "coin": coin,
                        "type": "LONG",
                        "entry_time": pos["entry_time"],
                        "exit_time": current_time,
                        "entry_price": pos["entry"],
                        "exit_price": exit_price,
                        "pnl": total_pnl,
                        "result": "TP2",
                        "r_multiplier": total_pnl / (pos["entry_risk"] if pos["entry_risk"] > 0 else 1.0),
                        "signal_score": pos.get("entry_signal_score"),
                        "confidence": pos.get("entry_confidence"),
                    })
                    closed_coins.append(coin)
                    continue
                
                # Check EXIT_SIGNAL: chỉ thoát sau MIN_HOLD_CANDLES và chỉ khi gặp tín hiệu đảo chiều mạnh
                from btc_scraper.signal_score import extract_signal_fields
                sig_fields = extract_signal_fields(coin_data)
                signal = coin_data.get("signal", sig_fields.get("raw", ""))
                candles_held = pos.get("candles_held", 0) + 1
                pos["candles_held"] = candles_held
                strong_exit_long = any(x in signal for x in [
                    "SELL (Crossover)",
                    "STRONG SELL (Confirmed Reversal)",
                    "SELL (Break-SMA50)",
                    "SELL (SFP-Liquidity-Sweep)"
                ])
                if candles_held >= MIN_HOLD_CANDLES and strong_exit_long:
                    exit_price = close
                    pnl_raw = pos["units"] * (exit_price - pos["entry"])
                    fee = (pos["units"] * pos["entry"] + pos["units"] * exit_price) * FEE_RATE
                    pnl_net = pnl_raw - fee
                    cash += (pos["units"] * exit_price) - fee
                    
                    total_pnl = pos["partial_pnl"] + pnl_net
                    trade_log.append({
                        "coin": coin,
                        "type": "LONG",
                        "entry_time": pos["entry_time"],
                        "exit_time": current_time,
                        "entry_price": pos["entry"],
                        "exit_price": exit_price,
                        "pnl": total_pnl,
                        "result": "EXIT_SIGNAL",
                        "r_multiplier": total_pnl / (pos["entry_risk"] if pos["entry_risk"] > 0 else 1.0),
                        "signal_score": pos.get("entry_signal_score"),
                        "confidence": pos.get("entry_confidence"),
                    })
                    closed_coins.append(coin)
                    continue

            # Kiểm tra thoát lệnh cho SHORT
            elif pos["type"] == "SHORT":
                # Check Stop Loss (SL)
                if high >= pos["sl"]:
                    exit_price = pos["sl"]
                    pnl_raw = pos["units"] * (pos["entry"] - exit_price)
                    fee = (pos["units"] * pos["entry"] + pos["units"] * exit_price) * FEE_RATE
                    pnl_net = pnl_raw - fee
                    cash += (pos["units"] * (2 * pos["entry"] - exit_price)) - fee
                    
                    trade_log.append({
                        "coin": coin,
                        "type": "SHORT",
                        "entry_time": pos["entry_time"],
                        "exit_time": current_time,
                        "entry_price": pos["entry"],
                        "exit_price": exit_price,
                        "pnl": pnl_net,
                        "result": "SL",
                        "r_multiplier": pnl_net / (pos["entry_risk"] if pos["entry_risk"] > 0 else 1.0),
                        "signal_score": pos.get("entry_signal_score"),
                        "confidence": pos.get("entry_confidence"),
                    })
                    closed_coins.append(coin)
                    continue
                
                # Check Take Profit 1 (TP1) - Đóng 50%
                if not pos["tp1_hit"] and low <= pos["tp1"]:
                    pos["tp1_hit"] = True
                    half_units = pos["units"] / 2
                    exit_price = pos["tp1"]
                    pnl_raw = half_units * (pos["entry"] - exit_price)
                    fee = (half_units * pos["entry"] + half_units * exit_price) * FEE_RATE
                    pnl_net = pnl_raw - fee
                    cash += (half_units * (2 * pos["entry"] - exit_price)) - fee
                    
                    pos["units"] -= half_units
                    pos["partial_pnl"] += pnl_net
                    pos["partial_exits"].append(("TP1", current_time, exit_price, pnl_net))
                
                # Check Take Profit 2 (TP2) - Đóng phần còn lại
                if low <= pos["tp2"]:
                    exit_price = pos["tp2"]
                    pnl_raw = pos["units"] * (pos["entry"] - exit_price)
                    fee = (pos["units"] * pos["entry"] + pos["units"] * exit_price) * FEE_RATE
                    pnl_net = pnl_raw - fee
                    cash += (pos["units"] * (2 * pos["entry"] - exit_price)) - fee
                    
                    total_pnl = pos["partial_pnl"] + pnl_net
                    trade_log.append({
                        "coin": coin,
                        "type": "SHORT",
                        "entry_time": pos["entry_time"],
                        "exit_time": current_time,
                        "entry_price": pos["entry"],
                        "exit_price": exit_price,
                        "pnl": total_pnl,
                        "result": "TP2",
                        "r_multiplier": total_pnl / (pos["entry_risk"] if pos["entry_risk"] > 0 else 1.0),
                        "signal_score": pos.get("entry_signal_score"),
                        "confidence": pos.get("entry_confidence"),
                    })
                    closed_coins.append(coin)
                    continue
                
                # Check EXIT_SIGNAL: chỉ thoát sau MIN_HOLD_CANDLES và chỉ khi gặp tín hiệu đảo chiều mạnh
                from btc_scraper.signal_score import extract_signal_fields
                sig_fields = extract_signal_fields(coin_data)
                signal = coin_data.get("signal", sig_fields.get("raw", ""))
                candles_held = pos.get("candles_held", 0) + 1
                pos["candles_held"] = candles_held
                strong_exit_short = any(x in signal for x in [
                    "BUY (Crossover)",
                    "STRONG BUY (Confirmed Reversal)",
                    "BUY (SFP-Liquidity-Sweep)"
                ])
                if candles_held >= MIN_HOLD_CANDLES and strong_exit_short:
                    exit_price = close
                    pnl_raw = pos["units"] * (pos["entry"] - exit_price)
                    fee = (pos["units"] * pos["entry"] + pos["units"] * exit_price) * FEE_RATE
                    pnl_net = pnl_raw - fee
                    cash += (pos["units"] * (2 * pos["entry"] - exit_price)) - fee
                    
                    total_pnl = pos["partial_pnl"] + pnl_net
                    trade_log.append({
                        "coin": coin,
                        "type": "SHORT",
                        "entry_time": pos["entry_time"],
                        "exit_time": current_time,
                        "entry_price": pos["entry"],
                        "exit_price": exit_price,
                        "pnl": total_pnl,
                        "result": "EXIT_SIGNAL",
                        "r_multiplier": total_pnl / (pos["entry_risk"] if pos["entry_risk"] > 0 else 1.0),
                        "signal_score": pos.get("entry_signal_score"),
                        "confidence": pos.get("entry_confidence"),
                    })
                    closed_coins.append(coin)
                    continue
                    
        # Xóa các vị thế đã đóng khỏi open_positions
        for coin in closed_coins:
            del open_positions[coin]
            
        # 2.2 Quét tín hiệu mở lệnh (Entries)
        for coin in coins:
            # Bỏ qua nếu đã có lệnh đang mở cho coin này
            if coin in open_positions:
                continue
                
            # Bỏ qua nếu danh mục đã đầy
            if len(open_positions) >= MAX_CONCURRENT_POSITIONS:
                break
                
            if coin not in lookup[current_time]:
                continue
                
            coin_data = lookup[current_time][coin]
            from btc_scraper.signal_score import extract_signal_fields
            sig_fields = extract_signal_fields(coin_data)
            sig_text = coin_data.get("signal", sig_fields.get("raw", ""))
            
            # Chỉ vào lệnh với tín hiệu rõ ràng, loại WEAK và NEUTRAL
            is_buy_signal = (
                any(x in sig_text for x in ["BUY", "STRONG BUY"])
                and "WEAK" not in sig_text
                and "Blocked" not in sig_text
                and "NEUTRAL" not in sig_text
            )
            is_sell_signal = (
                any(x in sig_text for x in ["SELL", "STRONG SELL"])
                and "WEAK" not in sig_text
                and "NEUTRAL" not in sig_text
            )
            
            if not is_buy_signal and not is_sell_signal:
                continue

            tp_sl = coin_data["tp_sl"]
            # Lấy thông số Entry, SL, TP
            entry = tp_sl["entry"]
            sl = tp_sl["sl"]
            tp1 = tp_sl["tp1"]
            tp2 = tp_sl["tp2"]
            
            if entry <= 0 or sl <= 0 or tp1 <= 0 or tp2 <= 0:
                continue

            # Bộ lọc Risk:Reward tối thiểu: chỉ vào lệnh khi RR1 ≥ MIN_RR
            rr1 = tp_sl.get("rr1", 0.0)
            if rr1 < MIN_RR:
                continue

            # Bộ lọc Chandelier: chỉ vào đúng chiều xu hướng ATR chứng nhận
            chandelier = coin_data.get("chandelier", "")
            if is_buy_signal and chandelier == "BEAR":
                continue   # Không LONG trong Chandelier Bear
            if is_sell_signal and chandelier == "BULL":
                continue   # Không SHORT trong Chandelier Bull
                
            # Bộ lọc Volume Spike: chỉ vào lệnh khi có xác nhận dòng tiền (vol > 1.3x SMA20)
            vol_spike = coin_data.get("vol_spike", False)
            if not vol_spike:
                continue   # Bỏ qua tín hiệu không có xác nhận volume

            # Sau khi qua toàn bộ các bộ lọc cơ bản, mới gọi model ML đắt đỏ để chấm điểm & quyết định quy mô vị thế
            from btc_scraper.signal_score import score_signal
            score_obj = score_signal(sig_text, coin_data, {"sentiment_penalty": sentiment_penalty} if sentiment_penalty is not None else {})
            
            # Additionally require model-derived action (if available) to match
            action_ok = False
            try:
                action_ok = score_obj.get("action") == "BUY" if is_buy_signal else (score_obj.get("action") == "SELL" if is_sell_signal else False)
            except Exception:
                action_ok = False

            if not action_ok:
                # Skip if score-based action disagrees with text-based filter
                continue
                
            signal = sig_text
            risk_pct = RISK_PER_TRADE * float(score_obj.get("position_size", 1.0))
            
            # --- 2.2.1 BỘ LỌC TƯƠNG QUAN (Pearson Correlation Filter) ---
            # Tính Pearson correlation với các coin hiện đang có lệnh
            max_corr = 0.0
            for open_coin in open_positions.keys():
                # Lấy 50 nến gần nhất tính đến thời điểm hiện tại
                candles_c1 = candles_dict[coin]
                candles_c2 = candles_dict[open_coin]
                
                # Tìm index hiện tại bằng cách tra cứu từ map O(1)
                idx1 = time_to_idx[coin].get(current_time, -1)
                idx2 = time_to_idx[open_coin].get(current_time, -1)
                
                if idx1 >= 50 and idx2 >= 50:
                    ret1 = [(candles_c1[j]["close"] - candles_c1[j-1]["close"])/candles_c1[j-1]["close"] for j in range(idx1 - 49, idx1 + 1)]
                    ret2 = [(candles_c2[j]["close"] - candles_c2[j-1]["close"])/candles_c2[j-1]["close"] for j in range(idx2 - 49, idx2 + 1)]
                    corr = pearson_correlation(ret1, ret2)
                    max_corr = max(max_corr, abs(corr))
            
            # Nếu tương quan lớn hơn 0.75: Giảm 50% Position Risk để giảm rủi ro tập trung
            if max_corr > 0.75:
                risk_pct = risk_pct * 0.5
                correlation_note = f" (Giảm 50% Vol do tương quan cao r={max_corr:.2f} với vị thế mở)"
            else:
                correlation_note = ""
                
            # --- 2.2.2 VOLATILITY POSITION SIZING ---
            risk_amount = balance * risk_pct
            
            if is_buy_signal:
                risk_per_unit = abs(entry - sl)
                if risk_per_unit <= 0:
                    continue
                units = risk_amount / risk_per_unit
                position_value = units * entry
                
                # Giới hạn tối đa 1/N tài khoản cho mỗi coin (Spot cash limit)
                max_allocation = balance / MAX_CONCURRENT_POSITIONS
                if position_value > max_allocation:
                    position_value = max_allocation
                    units = position_value / entry
                    
                # Thực hiện trừ tiền mặt
                fee = position_value * FEE_RATE
                if cash >= position_value + fee:
                    cash -= (position_value + fee)
                    open_positions[coin] = {
                        "type": "LONG",
                        "entry_time": current_time,
                        "entry": entry,
                        "sl": sl,
                        "tp1": tp1,
                        "tp2": tp2,
                        "units": units,
                        "tp1_hit": False,
                        "entry_risk": risk_amount,
                        "partial_pnl": 0.0,
                        "partial_exits": [],
                        "entry_signal_score": score_obj,
                        "entry_confidence": score_obj.get("confidence"),
                        "candles_held": 0,
                    }
                    # print(f"🟢 [LONG] {coin} tại {entry:.2f} | Risk: {risk_pct*100}%{correlation_note}")
                    
            elif is_sell_signal:
                risk_per_unit = abs(sl - entry)
                if risk_per_unit <= 0:
                    continue
                units = risk_amount / risk_per_unit
                position_value = units * entry
                
                # Giới hạn tối đa 1/N
                max_allocation = balance / MAX_CONCURRENT_POSITIONS
                if position_value > max_allocation:
                    position_value = max_allocation
                    units = position_value / entry
                    
                # Thực hiện trừ tiền mặt (ký quỹ)
                fee = position_value * FEE_RATE
                if cash >= position_value + fee:
                    cash -= (position_value + fee)
                    open_positions[coin] = {
                        "type": "SHORT",
                        "entry_time": current_time,
                        "entry": entry,
                        "sl": sl,
                        "tp1": tp1,
                        "tp2": tp2,
                        "units": units,
                        "tp1_hit": False,
                        "entry_risk": risk_amount,
                        "partial_pnl": 0.0,
                        "partial_exits": [],
                        "entry_signal_score": score_obj,
                        "entry_confidence": score_obj.get("confidence"),
                        "candles_held": 0,
                    }
                    # print(f"🔴 [SHORT] {coin} tại {entry:.2f} | Risk: {risk_pct*100}%{correlation_note}")

    print("\n✅ Backtest hoàn thành. Đang tổng hợp chỉ số hiệu suất...")
    
    # 3. Tính toán các chỉ số KPI
    total_trades = len(trade_log)
    if total_trades == 0:
        print("Không có lệnh nào được khớp trong thời gian này.")
        return
        
    wins = [t for t in trade_log if t["pnl"] > 0]
    losses = [t for t in trade_log if t["pnl"] <= 0]
    
    win_rate = len(wins) / total_trades if total_trades > 0 else 0.0
    
    total_profit = sum(t["pnl"] for t in wins)
    total_loss = abs(sum(t["pnl"] for t in losses))
    profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
    
    # Expectancy (R)
    r_multipliers = [t["r_multiplier"] for t in trade_log]
    expectancy = mean(r_multipliers) if r_multipliers else 0.0
    
    # Max Drawdown
    max_equity = initial_balance
    max_dd = 0.0
    for time_str, eq in equity_history:
        if eq > max_equity:
            max_equity = eq
        dd = (max_equity - eq) / max_equity
        if dd > max_dd:
            max_dd = dd
            
    # Sharpe & Sortino Ratio (mỗi bước 15m, quy đổi ra năm)
    # Tỷ suất sinh lợi theo phiên (15m returns)
    returns = []
    for i in range(1, len(equity_history)):
        ret = (equity_history[i][1] - equity_history[i-1][1]) / equity_history[i-1][1]
        returns.append(ret)
        
    avg_ret = mean(returns)
    variance = sum((r - avg_ret) ** 2 for r in returns) / len(returns) if returns else 0.0
    std_dev = math.sqrt(variance) if variance > 0 else 0.0
    
    # Sharpe Ratio hàng năm (35040 phiên 15m / năm)
    # Lãi suất phi rủi ro = 0%
    sharpe = (avg_ret / std_dev * math.sqrt(35040)) if std_dev > 0 else 0.0
    
    # Sortino Ratio (chỉ tính độ lệch chuẩn cho phiên giảm)
    downside_returns = [r for r in returns if r < 0]
    downside_variance = sum(r ** 2 for r in downside_returns) / len(returns) if returns else 0.0
    downside_std_dev = math.sqrt(downside_variance) if downside_variance > 0 else 0.0
    sortino = (avg_ret / downside_std_dev * math.sqrt(35040)) if downside_std_dev > 0 else 0.0
    
    # Max Consecutive Losses
    consec_losses = 0
    max_consec_losses = 0
    for t in trade_log:
        if t["pnl"] <= 0:
            consec_losses += 1
            if consec_losses > max_consec_losses:
                max_consec_losses = consec_losses
        else:
            consec_losses = 0
            
    final_equity = equity_history[-1][1]
    net_profit = final_equity - initial_balance
    net_profit_pct = (net_profit / initial_balance) * 100
    
    print(f"\n==================================================")
    print(f"📈 KẾT QUẢ BACKTEST HỆ THỐNG TRADING (1 NĂM - 15m)")
    print(f"==================================================")
    print(f"• Số dư ban đầu       : ${initial_balance:,.2f}")
    print(f"• Số dư cuối cùng     : ${final_equity:,.2f}")
    print(f"• Lợi nhuận ròng      : ${net_profit:,.2f} ({net_profit_pct:+.2f}%)")
    print(f"• Tổng số lệnh đã vào  : {total_trades}")
    print(f"• Số lệnh Thắng / Thua: {len(wins)} / {len(losses)}")
    print(f"• Win Rate            : {win_rate*100:.2f}%")
    print(f"• Profit Factor       : {profit_factor:.2f}")
    print(f"• Expectancy (R)      : {expectancy:.2f}R")
    print(f"• Max Drawdown        : {max_dd*100:.2f}%")
    print(f"• Sharpe Ratio        : {sharpe:.2f}")
    print(f"• Sortino Ratio       : {sortino:.2f}")
    print(f"• Chuỗi thua liên tiếp: {max_consec_losses} lệnh")
    print(f"==================================================")
    
    # Lưu Trade Log vào CSV để chạy Monte Carlo
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "backtest_trades.csv")
    with open(log_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["coin", "type", "entry_time", "exit_time", "entry_price", "exit_price", "pnl", "result", "r_multiplier", "signal_score", "confidence"])
        for t in trade_log:
            # Serialize signal_score as JSON string if present
            ss = t.get("signal_score")
            try:
                ss_ser = json.dumps(ss, ensure_ascii=False) if ss is not None else ""
            except Exception:
                ss_ser = str(ss)
            conf = t.get("confidence") if t.get("confidence") is not None else ""
            writer.writerow([
                t["coin"], t["type"], t["entry_time"], t["exit_time"],
                t["entry_price"], t["exit_price"], t["pnl"], t["result"], t["r_multiplier"], ss_ser, conf
            ])
    print(f"📝 Đã lưu nhật ký giao dịch vào {log_path} để stress-test Monte Carlo.")

    # Đồng thời lưu bản giản lược vào data/closed_trades.json để huấn luyện
    try:
        data_path = os.path.join("data", "closed_trades.json")
        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        existing = []
        if os.path.exists(data_path):
            try:
                with open(data_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        for t in trade_log:
            rec = {
                "coin": t.get("coin"),
                "entry_time": t.get("entry_time"),
                "exit_time": t.get("exit_time"),
                "entry_price": t.get("entry_price"),
                "exit_price": t.get("exit_price"),
                "pnl": t.get("pnl"),
                "result": t.get("result"),
                "signal_score": t.get("signal_score"),
                "confidence": t.get("confidence"),
            }
            existing.append(rec)

        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        print(f"📝 Đã lưu bản tóm tắt closed trades vào {data_path}.")
    except Exception:
        pass

    return net_profit

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--sweep", action="store_true", help="Run sentiment penalty sweep")
    p.add_argument("--start", type=int, default=-5, help="Sweep start (negative penalty)")
    p.add_argument("--end", type=int, default=-30, help="Sweep end (negative penalty)")
    p.add_argument("--step", type=int, default=-5, help="Sweep step (negative)")
    args = p.parse_args()

    if args.sweep:
        weights = list(range(args.start, args.end - 1, args.step)) if args.step < 0 else list(range(args.start, args.end + 1, args.step))
        results = []
        for w in weights:
            print(f"\n--- Running backtest with sentiment_penalty={w} ---")
            try:
                # Re-run and capture printed output; return net profit via function
                net = run_backtest(initial_balance=10000.0, sentiment_penalty=w)
                # If run_backtest returns None (no trades), approximate net as 0
                results.append((w, net if isinstance(net, (int, float)) else 0.0))
            except Exception as e:
                print(f"Error running weight {w}: {e}")
                results.append((w, float("-inf")))

        # Find best
        best = max(results, key=lambda x: x[1]) if results else (None, None)
        print("\nSweep results (weight -> net profit):")
        for w, net in results:
            print(f"  {w} -> {net}")
        print(f"\nBest weight: {best[0]} -> {best[1]}")
    else:
        run_backtest()
