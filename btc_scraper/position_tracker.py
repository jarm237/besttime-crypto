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
from typing import Literal

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

    # Kiểm tra nếu đã có vị thế đang mở cho coin này
    existing = next((p for p in positions if p["coin"] == coin and p["status"] == "open"), None)
    if existing:
        raise ValueError(f"Đã có vị thế ĐANG MỞ cho {coin} (entry={existing['entry_price']}). Đóng vị thế cũ trước.")

    pos = {
        "coin": coin,
        "direction": direction.upper(),
        "entry_price": float(entry_price),
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

    closed_data = {
        **pos,
        "sell_price": float(sell_price),
        "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pnl_pct": round(pnl_pct, 4),
        "pnl_usd_per_1000": round(1000 * pnl_pct / 100, 2),
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

    for pos in positions:
        coin = pos["coin"]
        ana = coin_analysis.get(coin)
        if not ana:
            continue

        current_price = ana.get("close", 0.0)
        if current_price <= 0:
            continue

        entry = pos["entry_price"]
        direction = pos["direction"]
        signal = ana.get("signal", "NEUTRAL")
        tp_sl = ana.get("tp_sl", {})
        sl = tp_sl.get("sl", 0.0)
        tp1 = tp_sl.get("tp1", 0.0)
        tp2 = tp_sl.get("tp2", 0.0)
        rr1 = tp_sl.get("rr1", 0.0)

        # Tính P&L hiện tại
        if direction == "LONG":
            pnl_pct = (current_price - entry) / entry * 100
        else:  # SHORT
            pnl_pct = (entry - current_price) / entry * 100

        # Xác định khuyến nghị
        rec = _generate_recommendation(
            direction=direction,
            entry=entry,
            current_price=current_price,
            pnl_pct=pnl_pct,
            signal=signal,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
        )

        # Cập nhật last_signal và last_price trong file
        for p in all_positions:
            if p["coin"] == coin and p["status"] == "open":
                p["last_signal"] = signal
                p["last_price"] = current_price
                p["last_checked"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                p["suggested_sl"] = sl
                p["suggested_tp1"] = tp1
                p["suggested_tp2"] = tp2
        _save_positions(all_positions)

        recommendations.append({
            "coin": coin,
            "direction": direction,
            "entry_price": entry,
            "current_price": current_price,
            "pnl_pct": round(pnl_pct, 3),
            "signal": signal,
            "recommendation": rec["action"],
            "recommendation_reason": rec["reason"],
            "urgency": rec["urgency"],
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "rr1": rr1,
        })

    return recommendations


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
        return {"action": "🚨 CẮT LỖ NGAY", "reason": f"Giá đã chạm/xuyên SL {sl:.4g}", "urgency": "HIGH"}
    if direction == "SHORT" and sl > 0 and current_price >= sl:
        return {"action": "🚨 CẮT LỖ NGAY", "reason": f"Giá đã chạm/xuyên SL {sl:.4g}", "urgency": "HIGH"}

    # TP đã chạm
    if direction == "LONG":
        if tp2 > 0 and current_price >= tp2:
            return {"action": "🎯 CHỐT LỜI TP2", "reason": f"Giá đạt TP2 {tp2:.4g} — đã đủ lãi!", "urgency": "HIGH"}
        if tp1 > 0 and current_price >= tp1:
            return {"action": "✅ Xem xét CHỐT TP1", "reason": f"Giá chạm TP1 {tp1:.4g} (lãi {pnl_pct:+.2f}%) — cân nhắc chốt 50%", "urgency": "MEDIUM"}
    if direction == "SHORT":
        if tp2 > 0 and current_price <= tp2:
            return {"action": "🎯 CHỐT LỜI TP2", "reason": f"Giá đạt TP2 {tp2:.4g} — đã đủ lãi!", "urgency": "HIGH"}
        if tp1 > 0 and current_price <= tp1:
            return {"action": "✅ Xem xét CHỐT TP1", "reason": f"Giá chạm TP1 {tp1:.4g} (lãi {pnl_pct:+.2f}%) — cân nhắc chốt 50%", "urgency": "MEDIUM"}

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


def get_performance_summary() -> dict:
    """
    Tổng hợp hiệu suất từ tất cả các lệnh đã đóng.
    Dùng để đánh giá chiến lược giao dịch cá nhân.
    """
    closed = _load_closed_log()
    if not closed:
        return {"message": "Chưa có lệnh nào được đóng."}

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
        else float("inf")
    )

    r_values = [t["r_multiplier"] for t in closed if t.get("r_multiplier") is not None]
    avg_r = sum(r_values) / len(r_values) if r_values else None

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
        "profit_factor": round(profit_factor, 2),
        "avg_r_multiplier": round(avg_r, 2) if avg_r is not None else None,
        "total_pnl_pct": round(total_pnl, 3),
        "pnl_per_1000_usd": round(total_pnl * 10, 2),
        "max_consecutive_losses": max_consec,
    }
