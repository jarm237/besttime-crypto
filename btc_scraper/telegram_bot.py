"""
Telegram Bot module - Xử lý gửi cảnh báo và báo cáo tín hiệu mua bán qua Telegram Bot.
"""

import requests
from btc_scraper.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_telegram_message(text: str, parse_mode: str = "HTML") -> bool:
    """
    Gửi tin nhắn về Telegram. parse_mode có thể là 'HTML', 'Markdown' hoặc None (plain text).
    Trả về True nếu gửi thành công, False nếu thất bại.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"\n[Warning] Khong the gui tin nhan Telegram: {e}")
        return False



def _build_min_capital_section(analysis_results: dict[str, dict]) -> str:
    """
    Tạo section HTML tóm tắt vốn tối thiểu nên giao dịch cho từng coin.
    Dựa trên TP1% thực tế và phí Binance Spot (0.2% round-trip).
    """
    FEE_SPOT     = 0.20   # % round-trip Spot standard
    FEE_SPOT_BNB = 0.15   # % round-trip Spot có BNB
    FEE_FUTURES  = 0.10   # % round-trip Futures taker
    TARGET_USD   = 5.0    # lợi nhuận ròng mục tiêu ($)

    rows = []
    for key, ana in analysis_results.items():
        coin, _ = key.split(":")
        tp_sl = ana.get("tp_sl", {})
        entry = tp_sl.get("entry", 0.0)
        sl    = tp_sl.get("sl", 0.0)
        tp1   = tp_sl.get("tp1", 0.0)

        if entry <= 0 or sl <= 0 or tp1 <= 0:
            continue

        sl_pct  = abs(entry - sl)  / entry * 100
        tp1_pct = abs(tp1 - entry) / entry * 100
        net_spot = tp1_pct - FEE_SPOT
        net_bnb  = tp1_pct - FEE_SPOT_BNB
        net_fut  = tp1_pct - FEE_FUTURES

        def _fmt(net: float) -> str:
            if net <= 0:
                return "❌ Kém"
            val = TARGET_USD / (net / 100)
            return f"${val:,.0f}"

        fee_ratio = FEE_SPOT / tp1_pct * 100 if tp1_pct > 0 else 999
        if fee_ratio < 15:
            icon = "✅"
        elif fee_ratio < 30:
            icon = "⚠️"
        else:
            icon = "❌"

        rows.append(
            f"{icon} <b>{coin}</b>: SL={sl_pct:.2f}% TP1={tp1_pct:.2f}%  "
            f"| Spot: <code>{_fmt(net_spot)}</code> "
            f"| +BNB: <code>{_fmt(net_bnb)}</code> "
            f"| Fut: <code>{_fmt(net_fut)}</code>"
        )

    if not rows:
        return ""

    header = "\n\n💰 <b>VỐN TỐI THIỂU KHUYẾN NGHỊ (lãi ≥ $5 sau phí):</b>"
    note   = "<i>Spot 0.1%/lệnh | +BNB 0.075% | Futures 0.05%</i>"
    return header + "\n" + "\n".join(rows) + "\n" + note


def send_signals_alert(analysis_results: dict[str, dict], ai_report: str = None):

    """
    Phân tích các tín hiệu và tạo tin nhắn gửi về Telegram kèm theo nhận định từ AI.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    import html

    # Lọc ra các coin có tín hiệu hành động (BUY/SELL)
    active_signals = []
    neutral_signals = []
    missed_valid_signals = []
    
    for key, ana in analysis_results.items():
        coin, exchange = key.split(":")
        sig = ana["signal"]
        
        # Định dạng dòng tin nhắn
        close_val = ana.get('close', 0.0)
        val_format = ",.4f" if close_val < 10 else ",.2f"
        price_str = f"{close_val:{val_format}}"
        
        emoji = "⚪"
        if "STRONG BUY" in sig:
            emoji = "🟢🟢"
        elif "BUY" in sig:
            emoji = "🟢"
        elif "STRONG SELL" in sig:
            emoji = "🔴🔴"
        elif "SELL" in sig:
            emoji = "🔴"
            
        escaped_sig = html.escape(sig)
        escaped_reason = html.escape(ana.get("reason", ""))
        line = f"{emoji} <b>{coin}</b>: <b>{escaped_sig}</b> giá <code>{price_str}</code> (RSI: {ana['rsi']:.1f})\n<i>{escaped_reason}</i>"
        
        tp_sl = ana.get("tp_sl", {})
        if ("BUY" in sig or "SELL" in sig) and tp_sl:
            entry_val = tp_sl.get("entry", 0.0)
            sl_val = tp_sl.get("sl", 0.0)
            tp1_val = tp_sl.get("tp1", 0.0)
            tp2_val = tp_sl.get("tp2", 0.0)
            rr1_val = tp_sl.get("rr1", 0.0)
            rr2_val = tp_sl.get("rr2", 0.0)
            
            entry_str = f"{entry_val:{val_format}}" if entry_val > 0 else "N/A"
            sl_str = f"{sl_val:{val_format}}" if sl_val > 0 else "N/A"
            tp1_str = f"{tp1_val:{val_format}}" if tp1_val > 0 else "N/A"
            tp2_str = f"{tp2_val:{val_format}}" if tp2_val > 0 else "N/A"
            
            line += (
                f"\n  👉 <b>Entry</b>: <code>{entry_str}</code> | <b>SL</b>: <code>{sl_str}</code>\n"
                f"  👉 <b>TP1</b>: <code>{tp1_str}</code> (R:R {rr1_val}) | <b>TP2</b>: <code>{tp2_str}</code> (R:R {rr2_val})"
            )
            
        if "BUY" in sig or "SELL" in sig:
            active_signals.append(line)
        else:
            neutral_signals.append(line)
            
        # Kiểm tra tín hiệu bỏ lỡ còn hiệu lực (Running)
        for ms in ana.get("missed_signals", []):
            if "Running" in ms["status"]:
                ms_sig = ms["signal"]
                ms_emoji = "⏳ 🟢" if "BUY" in ms_sig else "⏳ 🔴"
                ms_val_format = ",.4f" if ms["entry"] < 10 else ",.2f"
                ms_entry_str = f"{ms['entry']:{ms_val_format}}"
                
                ms_tp_sl = ms["tp_sl"]
                ms_sl_str = f"{ms_tp_sl.get('sl', 0.0):{ms_val_format}}"
                ms_tp1_str = f"{ms_tp_sl.get('tp1', 0.0):{ms_val_format}}"
                ms_tp2_str = f"{ms_tp_sl.get('tp2', 0.0):{ms_val_format}}"
                
                escaped_ms_sig = html.escape(ms_sig)
                ms_line = (
                    f"{ms_emoji} <b>{coin}</b> (Bỏ lỡ {ms['age_minutes']}p trước): <b>{escaped_ms_sig}</b>\n"
                    f"  Entry cũ: <code>{ms_entry_str}</code> | Giá hiện tại: <code>{price_str}</code>\n"
                    f"  SL: <code>{ms_sl_str}</code> | TP1: <code>{ms_tp1_str}</code> (R:R {ms_tp_sl.get('rr1', 0.0)}) | TP2: <code>{ms_tp2_str}</code> (R:R {ms_tp_sl.get('rr2', 0.0)})"
                )
                missed_valid_signals.append(ms_line)
            
    # Tạo tiêu đề tin nhắn
    message_lines = [
        "🔔 <b>[BÁO CÁO THỊ TRƯỜNG CRYPTO]</b> 🔔\n",
        f"Khung nến: <b>15m</b>"
    ]
    
    # Ưu tiên in các tín hiệu hành động trước
    if active_signals:
        message_lines.append("\n🔥 <b>TÍN HIỆU ĐÁNG CHÚ Ý:</b>")
        message_lines.extend(active_signals)
        
    if missed_valid_signals:
        message_lines.append("\n⏳ <b>TÍN HIỆU BỎ LỠ VẪN CÒN HIỆU LỰC:</b>")
        message_lines.extend(missed_valid_signals)
        
    if neutral_signals:
        message_lines.append("\n📈 <b>Trạng thái thị trường:</b>")
        message_lines.extend(neutral_signals)

    # Thêm section vốn tối thiểu
    min_cap_lines = _build_min_capital_section(analysis_results)
    if min_cap_lines:
        message_lines.append(min_cap_lines)

    message = "\n".join(message_lines)
    send_telegram_message(message, parse_mode="HTML")


    # Gửi báo cáo AI riêng dưới dạng plain text (tránh xung đột Markdown vs HTML)
    if ai_report and not ai_report.startswith("[Warning]") and not ai_report.startswith("[Loi AI Analyst]"):
        # Giới hạn 4000 ký tự để không vượt giới hạn Telegram
        ai_header = "🤖 NHAN DINH GEMINI AI:\n" + "-" * 30 + "\n"
        remainText = len(ai_report)
        while (remainText > 0): 
            if (remainText > 3900):
                send_telegram_message(ai_header + ai_report[:3900], parse_mode=None)
                ai_header = "🤖 NHAN DINH GEMINI AI (tiep theo):\n" + "-" * 30 + "\n"
                ai_report = ai_report[3900:]
                remainText = len(ai_report)
            else:
                send_telegram_message(ai_header + ai_report, parse_mode=None)
                remainText = 0
