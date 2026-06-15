import queue
from .api import send_telegram_message, get_latest_price
from .formatters import format_status_message, format_positions_message, format_performance_message

# Command queue for main-thread execution
telegram_command_queue = queue.Queue()

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
            "• <code>/buy &lt;coin&gt; &lt;LONG/SHORT&gt; [vốn USDT] [giá vào]</code>: Mở vị thế thủ công.\n"
            "  <i>Ví dụ: <code>/buy BTC LONG 50 67100</code></i>\n"
            "• <code>/close &lt;coin&gt; [giá đóng]</code>: Đóng vị thế thủ công.\n"
            "  <i>Ví dụ: <code>/close BTC 67500</code></i>"
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
                "❌ Cú pháp sai. Ví dụ:\n"
                "• Theo giá thị trường: <code>/buy BTC LONG 50</code>\n"
                "• Theo giá chỉ định: <code>/buy BTC LONG 50 67100</code>",
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
                
        price = 0.0
        if len(parts) >= 5:
            try:
                price = float(parts[4])
            except ValueError:
                send_telegram_message(
                    "❌ Giá vào lệnh phải là một số hợp lệ.",
                    reply_to_message_id=reply_to_id,
                    chat_id=chat_id
                )
                return
        else:
            price = get_latest_price(coin)
            
        if price <= 0:
            send_telegram_message(
                f"❌ Không lấy được giá vào lệnh cho coin <b>{coin}</b>. Vui lòng nhập giá thủ công.",
                reply_to_message_id=reply_to_id,
                chat_id=chat_id
            )
            return
            
        from btc_scraper.trading.position_tracker import add_position
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
                "❌ Cú pháp sai. Ví dụ:\n"
                "• Theo giá thị trường: <code>/close BTC</code>\n"
                "• Theo giá chỉ định: <code>/close BTC 67500</code>",
                reply_to_message_id=reply_to_id,
                chat_id=chat_id
            )
            return
            
        coin = parts[1].upper()
        
        price = 0.0
        if len(parts) >= 3:
            try:
                price = float(parts[2])
            except ValueError:
                send_telegram_message(
                    "❌ Giá đóng lệnh phải là một số hợp lệ.",
                    reply_to_message_id=reply_to_id,
                    chat_id=chat_id
                )
                return
        else:
            price = get_latest_price(coin)
            
        if price <= 0:
            send_telegram_message(
                f"❌ Không lấy được giá thị trường cho <b>{coin}</b> để đóng lệnh. Vui lòng nhập giá thủ công.",
                reply_to_message_id=reply_to_id,
                chat_id=chat_id
            )
            return
            
        from btc_scraper.trading.position_tracker import close_position
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

