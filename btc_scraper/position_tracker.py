"""
Position Tracker — Theo dõi vị thế thủ công và đưa ra khuyến nghị chốt lời/cắt lỗ.

Luồng sử dụng:
  1. Nhập lệnh:  add_position(coin, entry_price, direction="LONG")
  2. Mỗi lần quét: evaluate_positions(analysis_results) → trả về list khuyến nghị
  3. Đóng lệnh:  close_position(coin, sell_price) → trả về dict chỉ số đánh giá
"""

import json
import os
from datetime import datetime
import uuid
from typing import Literal

from btc_scraper.analysis import calculate_tp_sl

POSITIONS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "positions.json")
CLOSED_LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "logs", "closed_positions.json")


def _load_positions() -> list[dict]:
    """Tải danh sách vị thế đang mở từ file JSON."""
    os.makedirs(os.path.dirname(POSITIONS_FILE), exist_ok=True)
    if not os.path.exists(POSITIONS_FILE):
        return []
    try:
        with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_positions(positions: list[dict]) -> None:
    """Lưu danh sách vị thế đang mở vào file JSON."""
    os.makedirs(os.path.dirname(POSITIONS_FILE), exist_ok=True)
    with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)


def _load_closed_log() -> list[dict]:
    """Tải nhật ký vị thế đã đóng."""
    os.makedirs(os.path.dirname(CLOSED_LOG_FILE), exist_ok=True)
    if not os.path.exists(CLOSED_LOG_FILE):
        return []
    try:
        with open(CLOSED_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_closed_log(log: list[dict]) -> None:
    os.makedirs(os.path.dirname(CLOSED_LOG_FILE), exist_ok=True)
    with open(CLOSED_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def add_position(
    coin: str,
    entry_price: float,
    direction: Literal["LONG", "SHORT"] = "LONG",
    note: str = "",
    invested_usdt: float = 0.0,
    signal_score: dict | None = None,
    confidence: float | None = None,
) -> dict:
    """
    Thêm vị thế mới vào danh sách theo dõi.
    
    Args:
        coin: Tên coin, ví dụ "BTC", "ETH"
        entry_price: Giá vào lệnh
        direction: "LONG" hoặc "SHORT"
        note: Ghi chú tuỳ chọn (lý do vào lệnh)
    
    Returns:
        dict vị thế vừa tạo
    """
    positions = _load_positions()
    coin = coin.upper()

    # Không chặn nhiều vị thế cùng mã — cho phép pyramiding/multiple entries.
    pos = {
        "coin": coin,
        "id": str(uuid.uuid4()),
        "direction": direction.upper(),
        "entry_price": float(entry_price),
        "invested_usdt": float(invested_usdt),
        "entry_signal_score": signal_score or {},
        "entry_confidence": confidence,
        "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "status": "open",
        "note": note,
        # Sẽ được cập nhật từ analysis mỗi lần quét
        "last_signal": None,
        "last_price": None,
        "last_checked": None,
    }
    positions.append(pos)
    _save_positions(positions)
    return pos


def get_open_positions() -> list[dict]:
    """Trả về danh sách các vị thế đang mở."""
    return [p for p in _load_positions() if p["status"] == "open"]


def close_position(coin: str, sell_price: float) -> dict:
    """
    Đóng vị thế và tính toán chỉ số hiệu suất.

    Returns dict gồm:
        - pnl_pct: % lãi/lỗ
        - pnl_usd: lãi/lỗ tuyệt đối nếu vốn $1000
        - r_multiplier: bội số R (nếu có SL được set)
        - result: "WIN" | "LOSS" | "BREAKEVEN"
        - hold_hours: thời gian nắm giữ
    """
    positions = _load_positions()
    coin = coin.upper()

    pos_idx = next(
        (i for i, p in enumerate(positions) if p["coin"] == coin and p["status"] == "open"),
        None
    )
    if pos_idx is None:
        raise ValueError(f"Không tìm thấy vị thế đang mở cho {coin}.")

    pos = positions[pos_idx]
    entry = pos["entry_price"]
    direction = pos["direction"]

    # Tính P&L
    if direction == "LONG":
        pnl_pct = (sell_price - entry) / entry * 100
    else:  # SHORT
        pnl_pct = (entry - sell_price) / entry * 100

    # Tính R-multiplier nếu có SL đã được set bởi analysis
    r_mult = None
    sl = pos.get("suggested_sl")
    if sl and sl > 0:
        risk_pct = abs(entry - sl) / entry * 100
        if risk_pct > 0:
            r_mult = round(pnl_pct / risk_pct, 2)

    # Tính thời gian nắm giữ
    try:
        entry_dt = datetime.strptime(pos["entry_time"], "%Y-%m-%d %H:%M")
        hold_hours = round((datetime.now() - entry_dt).total_seconds() / 3600, 1)
    except Exception:
        hold_hours = 0.0

    result = "BREAKEVEN"
    if pnl_pct > 0.1:
        result = "WIN"
    elif pnl_pct < -0.1:
        result = "LOSS"

    invested_usdt = pos.get("invested_usdt", 0.0)
    pnl_usd_actual = invested_usdt * (pnl_pct / 100)
    gross_received = invested_usdt + pnl_usd_actual
    fee_usd = (invested_usdt * 0.001) + (gross_received * 0.001)  # Giả sử phí 0.1% mỗi chiều
    received_usdt = gross_received - fee_usd

    closed_data = {
        **pos,
        "sell_price": float(sell_price),
        "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pnl_pct": round(pnl_pct, 4),
        "pnl_usd_per_1000": round(1000 * pnl_pct / 100, 2),
        "pnl_usd_actual": round(pnl_usd_actual, 2),
        "fee_usd": round(fee_usd, 2),
        "received_usdt": round(received_usdt, 2),
        "r_multiplier": r_mult,
        "hold_hours": hold_hours,
        "result": result,
        "status": "closed",
    }

    # Cập nhật positions list
    positions[pos_idx] = closed_data
    _save_positions(positions)

    # Ghi vào log đóng lệnh
    closed_log = _load_closed_log()
    closed_log.append(closed_data)
    _save_closed_log(closed_log)

    # Đồng thời lưu một copy giản lược vào data/closed_trades.json để huấn luyện
    try:
        base = os.path.dirname(os.path.dirname(__file__))
        data_path = os.path.join(base, "data", "closed_trades.json")
        os.makedirs(os.path.dirname(data_path), exist_ok=True)
        simple = {
            "coin": closed_data.get("coin"),
            "id": closed_data.get("id"),
            "entry_time": closed_data.get("entry_time"),
            "exit_time": closed_data.get("exit_time"),
            "entry_price": closed_data.get("entry_price"),
            "exit_price": closed_data.get("sell_price"),
            "pnl_pct": closed_data.get("pnl_pct"),
            "result": closed_data.get("result"),
            "hold_hours": closed_data.get("hold_hours"),
            "signal_raw": closed_data.get("last_signal") or closed_data.get("signal"),
            "signal_score": closed_data.get("entry_signal_score") or closed_data.get("signal_score") or {},
            "confidence": closed_data.get("entry_confidence") or closed_data.get("confidence"),
        }
        # Append to JSON array
        if os.path.exists(data_path):
            try:
                with open(data_path, "r", encoding="utf-8") as f:
                    arr = json.load(f)
            except Exception:
                arr = []
        else:
            arr = []
        arr.append(simple)
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(arr, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # Ghi log outcomes cho adaptive scoring (không phá lỗi nếu module không có)
    try:
        from btc_scraper.adaptive_scoring import log_trade_outcome
        try:
            log_trade_outcome(closed_data)
        except Exception:
            # Không phá luồng: adaptive logging là bổ sung
            pass
    except Exception:
        pass

    # Sprint 2: Cập nhật actual_result vào shadow log để calibrate Meta Model
    try:
        import sys as _sys
        import os as _os
        _proj_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        if _proj_root not in _sys.path:
            _sys.path.insert(0, _proj_root)
        from scripts.shadow_log import update_outcome as _shadow_update
        _pos_id = closed_data.get("id") or closed_data.get("coin")
        if _pos_id:
            _shadow_update(
                position_id=_pos_id,
                actual_result=closed_data.get("result", "LOSS"),
                actual_pnl_pct=float(closed_data.get("pnl_pct", 0.0)),
            )
    except Exception:
        pass

    return closed_data


def evaluate_positions(analysis_results: dict[str, dict]) -> list[dict]:
    """
    Kiểm tra tất cả vị thế đang mở so với kết quả phân tích hiện tại.
    Trả về list các dict khuyến nghị để gửi lên Telegram.
    
    Args:
        analysis_results: dict dạng {"BTC:Binance": {analysis...}, ...}
    
    Returns:
        list[dict] mỗi phần tử gồm:
            coin, direction, entry_price, current_price,
            pnl_pct, signal, recommendation, sl, tp1, tp2, status_icon
    """
    positions = get_open_positions()
    if not positions:
        return []

    # Build lookup: coin → analysis data (lấy từ Binance)
    coin_analysis: dict[str, dict] = {}
    for key, ana in analysis_results.items():
        coin, _ = key.split(":")
        coin_analysis[coin.upper()] = ana

    recommendations = []
    all_positions = _load_positions()

    # Group positions by coin to support multiple entries per same coin
    by_coin: dict[str, list[dict]] = {}
    for p in positions:
        by_coin.setdefault(p["coin"], []).append(p)

    for coin, pos_list in by_coin.items():
        ana = coin_analysis.get(coin)
        if not ana:
            continue

        current_price = ana.get("close", 0.0)
        if current_price <= 0:
            continue

        # Aggregate invested and compute weighted average entry if possible
        total_invested = sum(float(p.get("invested_usdt", 0.0)) for p in pos_list)
        if total_invested > 0:
            weighted_entry = sum(float(p.get("entry_price", 0.0)) * float(p.get("invested_usdt", 0.0)) for p in pos_list) / total_invested
        else:
            weighted_entry = sum(float(p.get("entry_price", 0.0)) for p in pos_list) / len(pos_list)

        # Assume direction is the same for grouped positions (LONG/SHORT)
        direction = pos_list[0].get("direction", "LONG")
        from btc_scraper.signal_score import extract_signal_fields
        sig_fields = extract_signal_fields(ana)
        signal = ana.get("signal", sig_fields.get("raw", "NEUTRAL"))

        # Recalculate SL/TP based on weighted entry
        force_signal = "BUY" if direction == "LONG" else "SELL"
        pos_tp_sl = calculate_tp_sl(
            close=weighted_entry,
            signal=force_signal,
            atr=ana.get("atr", 0.0),
            support=ana.get("support", 0.0),
            resistance=ana.get("resistance", 0.0),
            bb_upper=ana.get("bb_upper", 0.0),
            bb_middle=ana.get("bb_middle", 0.0),
            bb_lower=ana.get("bb_lower", 0.0),
        )

        sl = pos_tp_sl.get("sl", 0.0)
        tp1 = pos_tp_sl.get("tp1", 0.0)
        tp2 = pos_tp_sl.get("tp2", 0.0)
        rr1 = pos_tp_sl.get("rr1", 0.0)

        # Compute aggregated P&L using weighted_entry
        if direction == "LONG":
            pnl_pct = (current_price - weighted_entry) / weighted_entry * 100
        else:
            pnl_pct = (weighted_entry - current_price) / weighted_entry * 100

        # Aggregate invested_usdt and expected received
        invested_usdt = total_invested
        pnl_usd_actual = invested_usdt * (pnl_pct / 100)
        gross_received = invested_usdt + pnl_usd_actual
        fee_usd = (invested_usdt * 0.001) + (gross_received * 0.001) if invested_usdt > 0 else 0.0
        expected_received_usdt = gross_received - fee_usd if invested_usdt > 0 else 0.0

        # Predict success probability of the position using Meta Model
        pos_meta_prob = None
        try:
            from btc_scraper.meta_model import predict_meta_confidence
            eval_info = dict(ana)
            if direction == "LONG":
                eval_info["signal"] = "BUY"
                eval_info["signal_score"] = {
                    "action": "BUY",
                    "score": 70,
                    "confidence": "MEDIUM"
                }
            else:
                eval_info["signal"] = "SELL"
                eval_info["signal_score"] = {
                    "action": "SELL",
                    "score": 30,
                    "confidence": "MEDIUM"
                }
            res = predict_meta_confidence(eval_info)
            if res and res.get("probability") is not None:
                pos_meta_prob = float(res["probability"])
        except Exception:
            pos_meta_prob = None

        # Xác định khuyến nghị dựa trên entry trung bình
        rec = _generate_recommendation(
            direction=direction,
            entry=weighted_entry,
            current_price=current_price,
            pnl_pct=pnl_pct,
            signal=signal,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
        )

        dca_opp = _evaluate_dca_opportunity(pos_list, ana, current_price, pos_meta_prob)

        # Cập nhật last_signal và last_price cho mọi vị thế của coin
        for p in all_positions:
            if p["coin"] == coin and p["status"] == "open":
                p["last_signal"] = signal
                p["last_price"] = current_price
                p["last_checked"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                p["last_signal_score"] = ana.get("signal_score", {})
                p["suggested_sl"] = sl
                p["suggested_tp1"] = tp1
                p["suggested_tp2"] = tp2
                p["live_meta_confidence"] = pos_meta_prob
                p["dca_opportunity"] = dca_opp
        _save_positions(all_positions)

        recommendations.append({
            "coin": coin,
            "direction": direction,
            "positions_count": len(pos_list),
            "avg_entry_price": round(weighted_entry, 6),
            "entry_price": round(weighted_entry, 6),
            "current_price": current_price,
            "pnl_pct": round(pnl_pct, 3),
            "invested_usdt": invested_usdt,
            "expected_received_usdt": round(expected_received_usdt, 2),
            "fee_usd": round(fee_usd, 2),
            "signal": signal,
            "suggested_position_size": ana.get("signal_score", {}).get("position_size") or ana.get("position_size"),
            "recommendation": rec["action"],
            "recommendation_reason": rec["reason"],
            "urgency": rec["urgency"],
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "rr1": rr1,
            "live_meta_confidence": pos_meta_prob,
            "dca_opportunity": dca_opp,
        })

    return recommendations


def _evaluate_dca_opportunity(
    pos_list: list[dict],
    ana: dict,
    current_price: float,
    sim_meta_prob: float | None
) -> dict | None:
    """
    Evaluate DCA opportunity for a grouped coin position.
    """
    if not pos_list or not ana or current_price <= 0:
        return None

    direction = pos_list[0].get("direction", "LONG").upper()
    
    # Rule 1: Limit max DCA actions (total entries < 3)
    if len(pos_list) >= 3:
        return None

    # Calculate weighted entry
    total_invested = sum(float(p.get("invested_usdt", 0.0)) for p in pos_list)
    if total_invested > 0:
        weighted_entry = sum(float(p.get("entry_price", 0.0)) * float(p.get("invested_usdt", 0.0)) for p in pos_list) / total_invested
    else:
        weighted_entry = sum(float(p.get("entry_price", 0.0)) for p in pos_list) / len(pos_list)

    # Rule 2: Volatility / Price Distance check
    atr = float(ana.get("atr", 0.0))
    price_diff_pct = abs(current_price - weighted_entry) / weighted_entry * 100
    
    # Volatility distance threshold = 1.5 * ATR% or minimum 1.5%
    atr_pct = (atr / current_price * 100) if current_price > 0 else 0.0
    min_distance = max(1.5, atr_pct * 1.5)
    
    # LONG: current price must be below entry; SHORT: current price must be above entry
    is_in_loss = (direction == "LONG" and current_price < weighted_entry) or (direction == "SHORT" and current_price > weighted_entry)
    
    if not is_in_loss or price_diff_pct < min_distance:
        return None

    # Rule 3: Model confidence check (sim_meta_prob >= 65%)
    if sim_meta_prob is None or sim_meta_prob < 0.65:
        return None

    # Rule 4: S/R Zone check (within 1% of S/R boundary)
    # Skip S/R zone check if S/R value is missing or <= 0
    if direction == "LONG":
        support = float(ana.get("support", 0.0))
        if support > 0:
            is_near_support = (current_price >= support * 0.99) and (current_price <= support * 1.01)
            if not is_near_support:
                return None
    else:
        resistance = float(ana.get("resistance", 0.0))
        if resistance > 0:
            is_near_resistance = (current_price >= resistance * 0.99) and (current_price <= resistance * 1.01)
            if not is_near_resistance:
                return None

    # Calculate DCA suggestion (default to 100% of the initial position size)
    initial_invested = float(pos_list[0].get("invested_usdt", 0.0))
    suggested_dca_size = initial_invested if initial_invested > 0 else 100.0
    
    # Calculate new average entry price
    new_avg_entry = (total_invested * weighted_entry + suggested_dca_size * current_price) / (total_invested + suggested_dca_size)
    
    return {
        "suggested_dca_size": round(suggested_dca_size, 2),
        "new_avg_entry": round(new_avg_entry, 6),
        "sim_meta_prob": round(sim_meta_prob, 4),
    }


def _generate_recommendation(
    direction: str,
    entry: float,
    current_price: float,
    pnl_pct: float,
    signal: str,
    sl: float,
    tp1: float,
    tp2: float,
) -> dict:
    """
    Logic nội bộ tạo khuyến nghị dựa trên vị thế và tín hiệu thị trường.
    """
    # SL bị chạm
    if direction == "LONG" and sl > 0 and current_price <= sl:
        return {"action": "🚨 CẮT LỖ NGAY", "reason": f"Giá đã chạm/xuyên SL {sl}", "urgency": "HIGH"}
    if direction == "SHORT" and sl > 0 and current_price >= sl:
        return {"action": "🚨 CẮT LỖ NGAY", "reason": f"Giá đã chạm/xuyên SL {sl}", "urgency": "HIGH"}

    # TP đã chạm
    if direction == "LONG":
        if tp2 > 0 and current_price >= tp2:
            return {"action": "🎯 CHỐT LỜI TP2", "reason": f"Giá đạt TP2 {tp2} — đã đủ lãi!", "urgency": "HIGH"}
        if tp1 > 0 and current_price >= tp1:
            return {"action": "✅ Xem xét CHỐT TP1", "reason": f"Giá chạm TP1 {tp1} (lãi {pnl_pct:+.2f}%) — cân nhắc chốt 50%", "urgency": "MEDIUM"}
    if direction == "SHORT":
        if tp2 > 0 and current_price <= tp2:
            return {"action": "🎯 CHỐT LỜI TP2", "reason": f"Giá đạt TP2 {tp2} — đã đủ lãi!", "urgency": "HIGH"}
        if tp1 > 0 and current_price <= tp1:
            return {"action": "✅ Xem xét CHỐT TP1", "reason": f"Giá chạm TP1 {tp1} (lãi {pnl_pct:+.2f}%) — cân nhắc chốt 50%", "urgency": "MEDIUM"}

    # Tín hiệu đảo chiều mạnh ngược chiều vị thế
    if direction == "LONG" and any(x in signal for x in ["STRONG SELL", "SELL (Crossover)", "SELL (Break-SMA50)", "SELL (SFP"]):
        action = "⚠️ XEM XÉT ĐÓNG LỆNH" if pnl_pct > 0 else "⚠️ CÂN NHẮC CẮT LỖ"
        return {"action": action, "reason": f"Xuất hiện tín hiệu đảo chiều: {signal}", "urgency": "MEDIUM"}
    if direction == "SHORT" and any(x in signal for x in ["STRONG BUY", "BUY (Crossover)", "BUY (SFP"]):
        action = "⚠️ XEM XÉT ĐÓNG LỆNH" if pnl_pct > 0 else "⚠️ CÂN NHẮC CẮT LỖ"
        return {"action": action, "reason": f"Xuất hiện tín hiệu đảo chiều: {signal}", "urgency": "MEDIUM"}

    # Đang lỗ nặng (> 3%)
    if pnl_pct < -3.0:
        return {"action": "⚠️ CẢNH BÁO LỖ", "reason": f"Đang lỗ {pnl_pct:.2f}% — xem xét lại kế hoạch", "urgency": "MEDIUM"}

    # Bình thường — giữ lệnh
    trend_note = ""
    if direction == "LONG" and "BULLISH" in signal:
        trend_note = " — xu hướng đang hỗ trợ vị thế"
    elif direction == "SHORT" and "BEARISH" in signal:
        trend_note = " — xu hướng đang hỗ trợ vị thế"

    return {
        "action": f"💤 GIỮ LỆNH ({pnl_pct:+.2f}%)",
        "reason": f"Chưa chạm TP/SL{trend_note}. Tín hiệu: {signal}",
        "urgency": "LOW",
    }


def get_performance_summary(trade_type: str = "ALL") -> dict:
    """
    Tổng hợp hiệu suất từ các lệnh đã đóng.
    trade_type: "ALL" | "AUTO" | "MANUAL"
    """
    closed = _load_closed_log()
    if not closed:
        return {"message": "Chưa có lệnh nào được đóng."}

    if trade_type == "AUTO":
        closed = [t for t in closed if "[AUTO-" in t.get("note", "")]
    elif trade_type == "MANUAL":
        closed = [t for t in closed if "[AUTO-" not in t.get("note", "")]

    if not closed:
        return {"message": f"Chưa có lệnh {trade_type} nào được đóng."}

    total = len(closed)
    wins = [t for t in closed if t.get("result") == "WIN"]
    losses = [t for t in closed if t.get("result") == "LOSS"]

    win_rate = len(wins) / total * 100 if total > 0 else 0
    avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    total_pnl = sum(t["pnl_pct"] for t in closed)

    profit_factor = (
        abs(sum(t["pnl_pct"] for t in wins)) / abs(sum(t["pnl_pct"] for t in losses))
        if losses and sum(t["pnl_pct"] for t in losses) != 0
        else None
    )

    r_values = [t["r_multiplier"] for t in closed if t.get("r_multiplier") is not None]
    avg_r = sum(r_values) / len(r_values) if r_values else None
    
    total_pnl_usd_actual = sum(t.get("pnl_usd_actual", 0.0) for t in closed)

    # Tính max consecutive losses
    consec = max_consec = 0
    for t in closed:
        if t.get("result") == "LOSS":
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    return {
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 2),
        "avg_win_pct": round(avg_win, 3),
        "avg_loss_pct": round(avg_loss, 3),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "avg_r_multiplier": round(avg_r, 2) if avg_r is not None else None,
        "total_pnl_pct": round(total_pnl, 3),
        "pnl_per_1000_usd": round(total_pnl * 10, 2),
        "total_pnl_usd_actual": round(total_pnl_usd_actual, 2),
        "max_consecutive_losses": max_consec,
    }
