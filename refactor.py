import sys

with open("btc_scraper/analysis.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

new_logic = """    def _evaluate_candle_signal(t: int):
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
        recent_candles = candles[max(0, idx-50):idx] if idx > 0 else []
        support = min(c["low"] for c in recent_candles) if recent_candles else 0.0
        resistance = max(c["high"] for c in recent_candles) if recent_candles else 0.0

        sfp_bull = (
            support > 0
            and current_low < support
            and current_close > support
            and current_rsi < 45
        )
        sfp_bear = (
            resistance > 0
            and current_high > resistance
            and current_close < resistance
            and current_rsi > 55
            and below_sma200
        )

        prev_ema9 = ema9_list[t-1] if t >= -len(candles) + 1 else current_ema9
        prev_ema21 = ema21_list[t-1] if t >= -len(candles) + 1 else current_ema21
        ema_golden_cross = (prev_ema9 <= prev_ema21) and (current_ema9 > current_ema21)
        ema_death_cross  = (prev_ema9 >= prev_ema21) and (current_ema9 < current_ema21)
        ema_bearish_active = current_ema9 < current_ema21

        chandelier_blocks_buy = (chandelier_state == "BEAR")

        def finalize(sig: str, reason: str):
            tp_sl = calculate_tp_sl(
                close=current_close, signal=sig, atr=current_atr,
                support=support, resistance=resistance,
                bb_upper=current_bb_upper, bb_middle=current_bb_middle, bb_lower=current_bb_lower
            )
            data = {
                "rsi": current_rsi, "ema9": current_ema9, "ema21": current_ema21,
                "sma50": current_sma50, "sma200": current_sma200, "macd": current_macd,
                "macd_signal": current_macd_signal, "macd_hist": current_macd_hist,
                "bb_upper": current_bb_upper, "bb_middle": current_bb_middle, "bb_lower": current_bb_lower,
                "atr": current_atr, "support": support, "resistance": resistance,
            }
            context = {
                "chandelier": chandelier_state,
                "above_sma200": above_sma200, "below_sma200": below_sma200,
                "sma50_uptrend": sma50_uptrend, "sma50_downtrend": sma50_downtrend,
                "above_sma50": above_sma50, "in_pullback_zone": in_pullback_zone,
                "vol_spike": vol_spike, "sfp_bull": sfp_bull, "sfp_bear": sfp_bear,
                "rsi_turning_up": rsi_turning_up, "rsi_turning_down": rsi_turning_down,
            }
            return sig, reason, tp_sl, data, context

        if rsi_turning_up:
            vol_note = " + Volume Spike (dong tien lon do day)" if vol_spike else " (volume trung binh - can them xac nhan)"
            if above_sma200 and not chandelier_blocks_buy:
                return finalize("STRONG BUY (Confirmed Reversal)", f"RSI cat len tren 30 (dao chieu tu Oversold){vol_note} | Tren SMA200")
            else:
                return finalize("BUY (Counter-Trend Reversal - High Risk)", f"RSI cat len tren 30 (dao chieu tu Oversold){vol_note}" + (" | Chandelier=BEAR: rui ro cao!" if chandelier_blocks_buy else "") + (" | Ben duoi SMA200 - CAUTION" if not above_sma200 else ""))

        if rsi_turning_down:
            vol_note = " + Volume Spike (xa hang manh)" if vol_spike else " (volume trung binh)"
            return finalize("STRONG SELL (Confirmed Reversal)", f"RSI cat xuong duoi 70 (dao chieu tu Overbought){vol_note}" + (" | Ben tren SMA200 - co the chi la dieu chinh" if above_sma200 else ""))

        if sfp_bull and not chandelier_blocks_buy:
            return finalize("BUY (SFP-Liquidity-Sweep)", f"Quet thanh khoan day: wick xuyen SL duoi {support:.2f} roi dong cua tren support | RSI={current_rsi:.1f}" + (" | Bull Market (SMA200 xac nhan)" if above_sma200 else " | Bear Market - rui ro cao hon"))

        if sfp_bear:
            return finalize("SELL (SFP-Liquidity-Sweep)", f"Quet thanh khoan dinh: wick vuot {resistance:.2f} roi dong cua duoi resistance | RSI={current_rsi:.1f}" + (" | Bear Market (SMA200 xac nhan)" if below_sma200 else " | Bull Market - co the chi la fakeout"))

        if ema_golden_cross:
            if chandelier_blocks_buy:
                return finalize("WEAK BUY (Crossover-Blocked)", "EMA9 cat len EMA21 NHUNG Chandelier=BEAR — thi truong dang downtrend theo ATR, chu y!")
            if above_sma200:
                return finalize("BUY (Crossover)", "EMA9 cat len EMA21 + Chandelier=BULL + Gia tren SMA200 (Bull Market confirmed)")
            elif current_sma200 > 0:
                return finalize("WEAK BUY (Crossover)", "EMA9 cat len EMA21 NHUNG gia duoi SMA200 — co the la bull trap!")
            else:
                return finalize("BUY (Crossover)", "EMA9 cat len EMA21 (Xu huong tang — chua du du lieu SMA200)")

        if ema_death_cross:
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
        "trend_context": trend_context
    }
    return res
"""

# Replace lines 394 to 799
new_lines = lines[:394] + [new_logic + "\n"] + lines[800:]

with open("btc_scraper/analysis.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)
