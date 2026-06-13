"""
Telegram Bot module - Xử lý gửi cảnh báo và báo cáo tín hiệu mua bán qua Telegram Bot.
"""

import os
import requests
import queue
import time
from btc_scraper.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# Command queue for main-thread execution
telegram_command_queue = queue.Queue()


def send_telegram_message(
    text: str,
    parse_mode: str = "HTML",
    reply_to_message_id: int | None = None,
    chat_id: str | int | None = None,
) -> int | None:
    """
    Gửi tin nhắn về Telegram.
    - parse_mode: 'HTML', 'Markdown' hoặc None (plain text).
    - reply_to_message_id: message_id của tin nhắn gốc để gửi dưới dạng reply/thread.
    Trả về message_id (int) nếu thành công, None nếu thất bại.
    """
    if not TELEGRAM_BOT_TOKEN:
        return None

    target_chat_id = chat_id if chat_id is not None else TELEGRAM_CHAT_ID
    if not target_chat_id:
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": target_chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", {}).get("message_id")
    except Exception as e:
        print(f"\n[Warning] Khong the gui tin nhan Telegram: {e}")
        return None



def send_signals_alert(analysis_results: dict[str, dict]) -> int | None:

    """
    [LUỒNG CORE] Phân tích tín hiệu và gửi ngay về Telegram (< 1 giây).
    Trả về message_id của tin nhắn vừa gửi để background worker có thể reply AI sau.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return None

    import html

    # Lọc ra các coin có tín hiệu hành động (BUY/SELL)
    active_signals = []
    neutral_signals = []
    missed_valid_signals = []
    
    from btc_scraper.signal_score import extract_signal_fields
    for key, ana in analysis_results.items():
        coin, exchange = key.split(":")
        sig_fields = extract_signal_fields(ana)
        sig = ana.get("signal", sig_fields.get("raw", ""))
        
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
        sig_score = ana.get("signal_score", {}) or {}
        score_val = sig_score.get("score")
        confidence = sig_score.get("confidence")
        meta_pct = sig_score.get("meta_confidence_pct")  # int 0-100 hoặc None

        score_part = f" <b>[{score_val}% {confidence}]</b>" if score_val is not None else ""

        # Meta Confidence badge (chỉ hiển thị khi model đã train)
        if meta_pct is not None:
            if meta_pct >= 70:
                meta_emoji = "🟢"
            elif meta_pct >= 50:
                meta_emoji = "🟡"
            else:
                meta_emoji = "🔴"
            meta_part = f" | {meta_emoji} <b>Meta: {meta_pct}%</b>"
        else:
            meta_part = ""

        line = f"{emoji} <b>{coin}</b>: <b>{escaped_sig}</b>{score_part}{meta_part} giá <code>{price_str}</code> (RSI: {ana['rsi']:.1f})\n<i>{escaped_reason}</i>"
        
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
            
            if entry_val > 0 and sl_val > 0 and tp1_val > 0:
                tp1_pct = abs(tp1_val - entry_val) / entry_val * 100
                TARGET_USD = 5.0
                FEE_SPOT = 0.20
                FEE_SPOT_BNB = 0.15
                FEE_FUTURES = 0.10
                
                net_spot = tp1_pct - FEE_SPOT
                net_bnb = tp1_pct - FEE_SPOT_BNB
                net_fut = tp1_pct - FEE_FUTURES
                
                def _fmt(net: float) -> str:
                    if net <= 0:
                        return "❌"
                    return f"${TARGET_USD / (net / 100):,.0f}"
                
                line += f"\n  💰 <b>Vốn tối thiểu (lãi ≥$5)</b>: Spot <code>{_fmt(net_spot)}</code> | +BNB <code>{_fmt(net_bnb)}</code> | Fut <code>{_fmt(net_fut)}</code>"
            
        if "BUY" in sig or "SELL" in sig:
            active_signals.append(line)
        else:
            neutral_signals.append(line)
            
        # Kiểm tra tín hiệu bỏ lỡ còn hiệu lực (Running)
        for ms in ana.get("missed_signals", []):
            if "Running" in ms["status"]:
                ms_fields = extract_signal_fields(ms)
                ms_sig = ms.get("signal", ms_fields.get("raw", ""))
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

    message = "\n".join(message_lines)
    message_id = send_telegram_message(message, parse_mode="HTML")
    return message_id


def send_ai_reply(ai_report: str, reply_to_message_id: int | None = None) -> None:
    """
    [LUỒNG AI - BACKGROUND] Gửi nhận định Gemini AI về Telegram.
    - Nếu có reply_to_message_id: gửi dưới dạng reply của tin nhắn signal gốc.
    - Nếu gặp lỗi bất kỳ (429, 503, network): log ra stdout và bỏ qua.
    """
    if not ai_report:
        return
    if ai_report.startswith("[Warning]") or ai_report.startswith("[Loi AI Analyst]") or ai_report.startswith("[Tạm dừng]"):
        print(f"[AI Worker] Bỏ qua gửi Telegram do AI báo lỗi: {ai_report[:80]}...")
        return

    # Giới hạn 4000 ký tự mỗi tin để không vượt giới hạn Telegram
    ai_header = "🤖 NHAN DINH GEMINI AI:\n" + "-" * 30 + "\n"
    first_chunk = True
    remaining = ai_report

    while remaining:
        chunk = remaining[:3900]
        remaining = remaining[3900:]

        # Chỉ reply vào tin nhắn gốc cho phần đầu tiên; các phần tiếp theo gửi thường
        rid = reply_to_message_id if first_chunk else None
        send_telegram_message(ai_header + chunk, parse_mode=None, reply_to_message_id=rid)

        ai_header = "🤖 NHAN DINH GEMINI AI (tiep theo):\n" + "-" * 30 + "\n"
        first_chunk = False


def send_position_recommendations(recommendations: list[dict]) -> None:
    """
    Gửi thông báo cập nhật về các vị thế đang mở qua Telegram.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not recommendations:
        return

    import html
    message_lines = ["🛡️ <b>[CẬP NHẬT VỊ THẾ ĐANG MỞ]</b> 🛡️\n"]

    for rec in recommendations:
        coin = rec["coin"]
        direction = rec["direction"]
        pnl = rec["pnl_pct"]
        urgency = rec["urgency"]
        action = rec["action"] if "action" in rec else rec["recommendation"]
        current_price = rec.get("current_price", 0.0)
        entry_price = rec.get("entry_price", 0.0)
        
        # Biểu tượng mức độ khẩn cấp
        icon = "🟢"
        if urgency == "HIGH":
            icon = "🚨"
        elif urgency == "MEDIUM":
            icon = "⚠️"
        
        # PnL color
        pnl_text = f"lãi +{pnl:.2f}%" if pnl > 0 else f"lỗ {pnl:.2f}%"
        
        val_format = ",.4f" if current_price > 0 and current_price < 10 else ",.2f"
        current_price_str = f"{current_price:{val_format}}" if current_price > 0 else "N/A"
        
        entry_val_format = ",.4f" if entry_price > 0 and entry_price < 10 else ",.2f"
        entry_price_str = f"{entry_price:{entry_val_format}}" if entry_price > 0 else "N/A"
        
        escaped_action = html.escape(action)
        escaped_reason = html.escape(rec["recommendation_reason"])

        meta_part = ""
        live_meta = rec.get("live_meta_confidence")
        if live_meta is not None:
            live_meta_pct = int(round(live_meta * 100))
            if live_meta_pct >= 70:
                meta_emoji = "🟢"
            elif live_meta_pct >= 50:
                meta_emoji = "🟡"
            else:
                meta_emoji = "🔴"
            meta_part = f" | {meta_emoji} <b>XS thắng: {live_meta_pct}%</b>"
        
        dca_opp = rec.get("dca_opportunity")
        if dca_opp:
            icon = "➕"
            dca_size = dca_opp["suggested_dca_size"]
            new_avg_entry = dca_opp["new_avg_entry"]
            sim_meta = int(round(dca_opp["sim_meta_prob"] * 100))
            
            new_entry_format = ",.4f" if new_avg_entry > 0 and new_avg_entry < 10 else ",.2f"
            new_avg_entry_str = f"{new_avg_entry:{new_entry_format}}"
            
            line = (
                f"{icon} <b>[KHUYẾN NGHỊ DCA] {coin} ({direction})</b>: {pnl_text}\n"
                f"  👉 <b>Khuyên dùng DCA thêm ${dca_size:.2f} USDT tại {current_price_str}</b>\n"
                f"  💰 Entry cũ: <code>{entry_price_str}</code> | Entry mới: <code>{new_avg_entry_str}</code>\n"
                f"  🤖 <b>XS thắng DCA: {sim_meta}%</b> (Reversal Prob)\n"
            )
        else:
            line = (
                f"{icon} <b>{coin}</b> ({direction}){meta_part}: {pnl_text}\n"
                f"  👉 <b>{escaped_action}</b>\n"
                f"  💰 Entry: <code>{entry_price_str}</code> | Hiện tại: <code>{current_price_str}</code>\n"
                f"  <i>{escaped_reason}</i>\n"
            )
        message_lines.append(line)

    message = "\n".join(message_lines)
    send_telegram_message(message, parse_mode="HTML")


def get_latest_price(coin: str) -> float:
    """Fetch latest price from Binance REST API."""
    try:
        symbol = f"{coin.upper()}USDT"
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return float(data["price"])
    except Exception as e:
        print(f"[Telegram Bot] Loi khi lay gia cho {coin}: {e}")
        return 0.0


def format_status_message() -> str:
    from btc_scraper.auto_trader import auto_trader
    from btc_scraper.position_tracker import get_open_positions
    
    at_status = auto_trader.status()
    open_positions = get_open_positions()
    
    cb_status = "🚨 ĐÃ BỊ KÍCH HOẠT" if at_status["circuit_tripped"] else "🟢 Bình thường"
    if at_status["circuit_tripped"] and at_status["circuit_tripped_remaining_h"]:
        cb_status += f" (Mở khoá sau {at_status['circuit_tripped_remaining_h']}h)"
        
    msg = (
        "ℹ️ <b>TRẠNG THÁI HỆ THỐNG</b> ℹ️\n\n"
        f"• <b>Chế độ AutoTrader:</b> <code>{at_status['mode']}</code>\n"
        f"• <b>Lệnh hôm nay:</b> <code>{at_status['trades_today']}/{at_status['max_daily_trades']}</code>\n"
        f"• <b>Chuỗi thua liên tiếp:</b> <code>{at_status['consecutive_losses']}/{at_status['circuit_breaker_n']}</code>\n"
        f"• <b>Circuit Breaker:</b> {cb_status}\n"
        f"• <b>Số vị thế đang mở:</b> <code>{len(open_positions)}</code>\n"
        f"• <b>Ngưỡng Meta:</b> <code>{at_status['meta_threshold']:.0%}</code>\n"
        f"• <b>Ngưỡng Score:</b> <code>{at_status['score_threshold']}</code>\n"
        f"• <b>Allowed Coins:</b> <code>{', '.join(at_status['allowed_coins'][:10])}...</code>\n"
    )
    return msg


def format_positions_message() -> str:
    from btc_scraper.position_tracker import get_open_positions
    positions = get_open_positions()
    if not positions:
        return "ℹ️ Hiện không có vị thế mở nào đang được theo dõi."
        
    lines = ["🛡️ <b>DANH SÁCH VỊ THẾ ĐANG MỞ</b> 🛡️\n"]
    for p in positions:
        coin = p["coin"]
        direction = p["direction"]
        entry = p["entry_price"]
        current = p.get("last_price") or entry
        pnl = 0.0
        if entry > 0:
            if direction == "LONG":
                pnl = (current - entry) / entry * 100
            else:
                pnl = (entry - current) / entry * 100
                
        pnl_text = f"lãi +{pnl:.2f}%" if pnl > 0 else f"lỗ {pnl:.2f}%"
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        
        val_format = ",.4f" if current < 10 else ",.2f"
        
        lines.append(
            f"• {pnl_emoji} <b>{coin} ({direction})</b>\n"
            f"  👉 Vốn: <code>${p.get('invested_usdt', 0.0):.2f} USDT</code>\n"
            f"  👉 Giá vào: <code>{entry:{val_format}}</code> | Hiện tại: <code>{current:{val_format}}</code>\n"
            f"  👉 Trạng thái: <b>{pnl_text}</b>\n"
            f"  👉 Entry time: <code>{p['entry_time']}</code>\n"
        )
    return "\n".join(lines)


def format_performance_message() -> str:
    from btc_scraper.position_tracker import get_performance_summary
    perf = get_performance_summary("ALL")
    if "message" in perf:
        return f"ℹ️ {perf['message']}"
        
    msg = (
        "📈 <b>BÁO CÁO HIỆU SUẤT GIAO DỊCH</b> 📈\n\n"
        f"• <b>Tổng số lệnh đã đóng:</b> <code>{perf['total_trades']}</code>\n"
        f"• <b>Số lệnh thắng:</b> <code>{perf['wins']}</code> (Win Rate: <code>{perf['win_rate_pct']}%</code>)\n"
        f"• <b>Số lệnh thua:</b> <code>{perf['losses']}</code>\n"
        f"• <b>Chuỗi thua liên tiếp tối đa:</b> <code>{perf['max_consecutive_losses']}</code>\n"
        f"• <b>Lãi/lỗ trung bình lệnh thắng:</b> <code>+{perf['avg_win_pct']}%</code>\n"
        f"• <b>Lãi/lỗ trung bình lệnh thua:</b> <code>{perf['avg_loss_pct']}%</code>\n"
        f"• <b>Profit Factor:</b> <code>{perf['profit_factor'] or 'N/A'}</code>\n"
        f"• <b>Average R-Multiplier:</b> <code>{perf['avg_r_multiplier'] or 'N/A'}R</code>\n"
        f"• <b>Tổng PnL (%):</b> <code>{perf['total_pnl_pct']:+.3f}%</code>\n"
        f"• <b>Ước tính PnL ($1000 vốn):</b> <code>{perf['pnl_per_1000_usd']:+.2f} USD</code>\n"
        f"• <b>PnL thực tế tích luỹ:</b> <code>{perf['total_pnl_usd_actual']:+.2f} USDT</code>"
    )
    return msg


def handle_telegram_command(text: str, chat_id: str | int, reply_to_id: int | None = None) -> None:
    parts = text.split()
    if not parts:
        return
    cmd = parts[0].lower()
    
    if cmd in ("/start", "/help"):
        help_msg = (
            "🤖 <b>HƯỚNG DẪN SỬ DỤNG BOT TELEGRAM</b> 🤖\n\n"
            "<b>Lệnh hệ thống:</b>\n"
            "• <code>/status</code>: Xem trạng thái hệ thống, WebSocket, và AutoTrader.\n"
            "• <code>/scan</code> hoặc <code>/signals</code>: Quét thị trường và phân tích tín hiệu ngay.\n"
            "• <code>/perf</code> hoặc <code>/summary</code>: Xem báo cáo hiệu suất giao dịch.\n\n"
            "<b>Lệnh quản lý vị thế:</b>\n"
            "• <code>/positions</code>: Xem danh sách vị thế đang mở.\n"
            "• <code>/buy &lt;coin&gt; &lt;LONG/SHORT&gt; [vốn USDT]</code>: Mở vị thế thủ công.\n"
            "  <i>Ví dụ: <code>/buy BTC LONG 50</code></i>\n"
            "• <code>/close &lt;coin&gt;</code>: Đóng vị thế thủ công theo giá hiện tại.\n"
            "  <i>Ví dụ: <code>/close BTC</code></i>"
        )
        send_telegram_message(help_msg, reply_to_message_id=reply_to_id, chat_id=chat_id)
        
    elif cmd == "/status":
        msg = format_status_message()
        send_telegram_message(msg, reply_to_message_id=reply_to_id, chat_id=chat_id)
        
    elif cmd in ("/scan", "/signals"):
        send_telegram_message("⏳ Đang tiến hành quét thị trường và phân tích tín hiệu...", reply_to_message_id=reply_to_id, chat_id=chat_id)
        telegram_command_queue.put("scan")
        
    elif cmd in ("/perf", "/summary"):
        msg = format_performance_message()
        send_telegram_message(msg, reply_to_message_id=reply_to_id, chat_id=chat_id)
        
    elif cmd == "/positions":
        msg = format_positions_message()
        send_telegram_message(msg, reply_to_message_id=reply_to_id, chat_id=chat_id)
        
    elif cmd == "/buy":
        if len(parts) < 3:
            send_telegram_message(
                "❌ Cú pháp sai. Ví dụ: <code>/buy BTC LONG 50</code>",
                reply_to_message_id=reply_to_id,
                chat_id=chat_id
            )
            return
            
        coin = parts[1].upper()
        direction = parts[2].upper()
        if direction not in ("LONG", "SHORT", "BUY", "SELL"):
            send_telegram_message(
                "❌ Chiều giao dịch phải là LONG hoặc SHORT.",
                reply_to_message_id=reply_to_id,
                chat_id=chat_id
            )
            return
            
        if direction == "BUY":
            direction = "LONG"
        elif direction == "SELL":
            direction = "SHORT"
            
        invested_usdt = 50.0
        if len(parts) >= 4:
            try:
                invested_usdt = float(parts[3])
            except ValueError:
                send_telegram_message(
                    "❌ Số vốn USDT phải là một số hợp lệ.",
                    reply_to_message_id=reply_to_id,
                    chat_id=chat_id
                )
                return
                
        price = get_latest_price(coin)
        if price <= 0:
            send_telegram_message(
                f"❌ Không lấy được giá hiện tại cho coin <b>{coin}</b>. Vui lòng kiểm tra lại.",
                reply_to_message_id=reply_to_id,
                chat_id=chat_id
            )
            return
            
        from btc_scraper.position_tracker import add_position
        pos = add_position(
            coin=coin,
            entry_price=price,
            direction=direction,
            note="[MANUAL] Telegram Command",
            invested_usdt=invested_usdt
        )
        
        reply = (
            "✅ <b>ĐÃ MỞ VỊ THẾ THỦ CÔNG:</b>\n"
            f"• Coin: <b>{coin}</b> ({direction})\n"
            f"• Giá vào: <code>{price:,.4f}</code>\n"
            f"• Vốn đầu tư: <code>${invested_usdt:.2f} USDT</code>\n"
            f"• Thời gian: <code>{pos['entry_time']}</code>"
        )
        send_telegram_message(reply, reply_to_message_id=reply_to_id, chat_id=chat_id)
        
    elif cmd == "/close":
        if len(parts) < 2:
            send_telegram_message(
                "❌ Cú pháp sai. Ví dụ: <code>/close BTC</code>",
                reply_to_message_id=reply_to_id,
                chat_id=chat_id
            )
            return
            
        coin = parts[1].upper()
        price = get_latest_price(coin)
        if price <= 0:
            send_telegram_message(
                f"❌ Không lấy được giá thị trường cho <b>{coin}</b> để đóng lệnh.",
                reply_to_message_id=reply_to_id,
                chat_id=chat_id
            )
            return
            
        from btc_scraper.position_tracker import close_position
        try:
            closed_data = close_position(coin, price)
            pnl = closed_data["pnl_pct"]
            pnl_text = f"+{pnl:.2f}%" if pnl > 0 else f"{pnl:.2f}%"
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            
            reply = (
                f"✅ <b>ĐÃ ĐÓNG VỊ THẾ THỦ CÔNG:</b>\n"
                f"• Coin: <b>{coin}</b> ({closed_data['direction']})\n"
                f"• Giá vào: <code>{closed_data['entry_price']:,.4f}</code>\n"
                f"• Giá đóng: <code>{price:,.4f}</code>\n"
                f"• Lãi/lỗ: {pnl_emoji} <b>{pnl_text}</b>\n"
                f"• Lợi nhuận: <code>${closed_data['pnl_usd_actual']:.2f} USDT</code>\n"
                f"• Hold: <code>{closed_data['hold_hours']} giờ</code>"
            )
            send_telegram_message(reply, reply_to_message_id=reply_to_id, chat_id=chat_id)
        except Exception as e:
            send_telegram_message(
                f"❌ Không thể đóng vị thế: {e}",
                reply_to_message_id=reply_to_id,
                chat_id=chat_id
            )


def start_telegram_listener() -> None:
    """Background listener to poll for Telegram commands."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram Bot] TELEGRAM_BOT_TOKEN hoac TELEGRAM_CHAT_ID chua duoc cau hinh. Bo qua khoi dong listener.")
        return

    print("[Telegram Bot] Dang khoi dong Telegram Command Listener...")
    
    # Avoid executing old commands before startup
    offset = 0
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        resp = requests.get(url, params={"limit": 1, "offset": -1}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok") and data.get("result"):
                offset = data["result"][0]["update_id"] + 1
    except Exception as e:
        print(f"[Telegram Bot] Loi khi lay update_id ban dau: {e}")

    print(f"[Telegram Bot] Dang lang nghe lenh voi offset = {offset}...")

    while True:
        try:
            # Dynamic check of allowed chat IDs from environment
            allowed_chat_ids = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")
            allowed_list = [x.strip() for x in allowed_chat_ids.split(",") if x.strip()] if allowed_chat_ids else ([str(TELEGRAM_CHAT_ID)] if TELEGRAM_CHAT_ID else [])

            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {"offset": offset, "timeout": 20}
            resp = requests.get(url, params=params, timeout=25)
            
            if resp.status_code != 200:
                time.sleep(5)
                continue
                
            data = resp.json()
            if not data.get("ok"):
                time.sleep(5)
                continue
                
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                
                message = update.get("message")
                if not message:
                    continue
                    
                chat = message.get("chat")
                if not chat:
                    continue
                    
                chat_id = chat.get("id")
                text = message.get("text", "").strip()
                
                if not text:
                    continue
                
                # Only handle commands starting with /
                if not text.startswith("/"):
                    continue
                    
                # Security: Only accept commands from configured chat IDs
                if str(chat_id) not in allowed_list:
                    print(f"[Telegram Bot] Bo qua lenh tu chat_id la: {chat_id}")
                    continue
                    
                try:
                    handle_telegram_command(text, chat_id, message.get("message_id"))
                except Exception as cmd_err:
                    send_telegram_message(f"❌ Lỗi thực thi lệnh: {cmd_err}", chat_id=chat_id)
                    print(f"[Telegram Bot] Loi thuc thi lenh '{text}': {cmd_err}")
                    
        except Exception as e:
            print(f"[Telegram Bot] Loi trong vong lap polling: {e}")
            time.sleep(5)
