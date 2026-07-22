import html
import math
import queue
import re

from .api import send_telegram_message, get_latest_price
from .formatters import format_status_message, format_positions_message, format_performance_message

# Command queue for main-thread execution
telegram_command_queue = queue.Queue(maxsize=1)

_COIN_PATTERN = re.compile(r"^[A-Z0-9]{2,15}$")
_DECISION_BASIS_MAP = {
    "signal": "system_signal",
    "personal": "personal_discretion",
}


def _reply(text: str, chat_id: str | int, reply_to_id: int | None) -> None:
    send_telegram_message(text, reply_to_message_id=reply_to_id, chat_id=chat_id)


def _normalize_command(token: str) -> str:
    """Support Telegram group commands such as /status@besttime_bot."""
    return token.split("@", 1)[0].lower()


def _normalize_coin(value: str) -> str:
    coin = value.strip().upper().replace("/", "").replace("-", "").replace("_", "")
    if coin.endswith("USDT"):
        coin = coin[:-4]
    if not _COIN_PATTERN.fullmatch(coin):
        raise ValueError("Mã coin chỉ được gồm 2-15 chữ cái hoặc chữ số.")
    return coin


def _positive_number(value: str, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} phải là một số hợp lệ.") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} phải là số dương hữu hạn.")
    return number


def _buy_usage() -> str:
    return (
        "❌ Cú pháp sai. Ví dụ:\n"
        "• Giá thị trường: <code>/buy BTC LONG 50</code>\n"
        "• Giá chỉ định: <code>/buy BTC LONG 50 67100</code>\n"
        "• Theo tín hiệu hệ thống: <code>/buy BTC LONG 50 signal</code>"
    )


def _close_usage() -> str:
    return (
        "❌ Cú pháp sai. Ví dụ:\n"
        "• Đóng toàn bộ: <code>/close BTC</code>\n"
        "• Đóng một phần: <code>/close BTC 50%</code>\n"
        "• Một phần kèm giá: <code>/close BTC 50% 67500</code>\n"
        "• Toàn bộ kèm giá: <code>/close BTC 67500</code>"
    )


def handle_telegram_command(text: str, chat_id: str | int, reply_to_id: int | None = None) -> None:
    parts = text.split()
    if not parts:
        return
    cmd = _normalize_command(parts[0])
    
    if cmd in ("/start", "/help"):
        help_msg = (
            "🤖 <b>HƯỚNG DẪN SỬ DỤNG BOT TELEGRAM</b> 🤖\n\n"
            "<b>Lệnh hệ thống:</b>\n"
            "• <code>/status</code>: Xem trạng thái hệ thống, WebSocket, và AutoTrader.\n"
            "• <code>/scan</code> hoặc <code>/signals</code>: Quét thị trường và phân tích tín hiệu ngay.\n"
            "• <code>/perf</code> hoặc <code>/summary</code>: Xem báo cáo hiệu suất giao dịch.\n\n"
            "<b>Lệnh quản lý vị thế:</b>\n"
            "• <code>/positions</code>: Xem danh sách vị thế đang mở.\n"
            "• <code>/buy &lt;coin&gt; &lt;LONG/SHORT&gt; [vốn USDT] [giá vào] [signal/personal]</code>: Mở vị thế thủ công.\n"
            "  <i>Ví dụ: <code>/buy BTC LONG 50 67100</code></i>\n"
            "• <code>/close &lt;coin&gt; [phần trăm] [giá đóng]</code>: Đóng toàn bộ hoặc một phần vị thế.\n"
            "  <i>Ví dụ: <code>/close BTC 50%</code> hoặc <code>/close BTC 67500</code></i>"
        )
        _reply(help_msg, chat_id, reply_to_id)
        
    elif cmd == "/status":
        msg = format_status_message()
        send_telegram_message(msg, reply_to_message_id=reply_to_id, chat_id=chat_id)
        
    elif cmd in ("/scan", "/signals"):
        try:
            telegram_command_queue.put_nowait({
                "command": "scan",
                "chat_id": chat_id,
                "reply_to_id": reply_to_id,
            })
        except queue.Full:
            _reply("⏳ Yêu cầu quét trước đó đang chờ xử lý.", chat_id, reply_to_id)
        else:
            _reply("⏳ Đang tiến hành quét thị trường và phân tích tín hiệu...", chat_id, reply_to_id)
        
    elif cmd in ("/perf", "/summary"):
        msg = format_performance_message()
        send_telegram_message(msg, reply_to_message_id=reply_to_id, chat_id=chat_id)
        
    elif cmd == "/positions":
        msg = format_positions_message()
        send_telegram_message(msg, reply_to_message_id=reply_to_id, chat_id=chat_id)
        
    elif cmd == "/buy":
        if len(parts) < 3 or len(parts) > 6:
            _reply(_buy_usage(), chat_id, reply_to_id)
            return

        try:
            coin = _normalize_coin(parts[1])
        except ValueError as exc:
            _reply(f"❌ {exc}", chat_id, reply_to_id)
            return

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
                invested_usdt = _positive_number(parts[3], "Số vốn USDT")
            except ValueError as exc:
                _reply(f"❌ {exc}", chat_id, reply_to_id)
                return

        price = 0.0
        manual_decision_basis = "personal_discretion"
        if len(parts) >= 5:
            basis = _DECISION_BASIS_MAP.get(parts[4].lower())
            if basis is not None and len(parts) == 5:
                manual_decision_basis = basis
            else:
                try:
                    price = _positive_number(parts[4], "Giá vào lệnh")
                except ValueError as exc:
                    _reply(f"❌ {exc}", chat_id, reply_to_id)
                    return

        if len(parts) == 6:
            manual_decision_basis = _DECISION_BASIS_MAP.get(parts[5].lower(), "")
            if not manual_decision_basis:
                _reply("❌ Nguồn quyết định phải là <code>signal</code> hoặc <code>personal</code>.", chat_id, reply_to_id)
                return

        if price == 0:
            price = get_latest_price(coin)

        if not math.isfinite(price) or price <= 0:
            send_telegram_message(
                f"❌ Không lấy được giá vào lệnh cho coin <b>{coin}</b>. Vui lòng nhập giá thủ công.",
                reply_to_message_id=reply_to_id,
                chat_id=chat_id
            )
            return
            
        from btc_scraper.trading.position_tracker import add_position, get_open_positions
        duplicate = next(
            (
                position for position in get_open_positions()
                if str(position.get("coin", "")).upper() == coin
                and (
                    position.get("order_channel") == "telegram"
                    or position.get("created_by") == "telegram_command"
                )
            ),
            None,
        )
        if duplicate:
            _reply(
                f"⚠️ Đã có vị thế Telegram đang mở cho <b>{coin}</b>. "
                "Hãy đóng vị thế hiện tại trước khi mở lệnh mới.",
                chat_id,
                reply_to_id,
            )
            return

        try:
            pos = add_position(
                coin=coin,
                entry_price=price,
                direction=direction,
                note="[MANUAL] Telegram Command",
                invested_usdt=invested_usdt,
                trade_origin="manual",
                execution_mode="manual",
                created_by="telegram_command",
                order_creator="user",
                order_channel="telegram",
                manual_decision_basis=manual_decision_basis,
            )
        except Exception as exc:
            _reply(f"❌ Không thể mở vị thế: {html.escape(str(exc))}", chat_id, reply_to_id)
            return
        
        reply = (
            "✅ <b>ĐÃ MỞ VỊ THẾ THỦ CÔNG:</b>\n"
            f"• Coin: <b>{coin}</b> ({direction})\n"
            f"• Giá vào: <code>{price:,.4f}</code>\n"
            f"• Vốn đầu tư: <code>${invested_usdt:.2f} USDT</code>\n"
            f"• Thời gian: <code>{pos['entry_time']}</code>"
        )
        send_telegram_message(reply, reply_to_message_id=reply_to_id, chat_id=chat_id)
        
    elif cmd == "/close":
        if len(parts) < 2 or len(parts) > 4:
            _reply(_close_usage(), chat_id, reply_to_id)
            return

        try:
            coin = _normalize_coin(parts[1])
        except ValueError as exc:
            _reply(f"❌ {exc}", chat_id, reply_to_id)
            return

        percentage = 100.0
        price = 0.0
        
        if len(parts) == 3:
            # Could be percentage (50%) or price (67500)
            if parts[2].endswith('%'):
                try:
                    percentage = _positive_number(parts[2][:-1], "Phần trăm đóng lệnh")
                except ValueError as exc:
                    _reply(f"❌ {exc}", chat_id, reply_to_id)
                    return
            else:
                try:
                    price = _positive_number(parts[2], "Giá đóng lệnh")
                except ValueError as exc:
                    _reply(f"❌ {exc}", chat_id, reply_to_id)
                    return
        elif len(parts) == 4:
            try:
                percentage = _positive_number(parts[2].removesuffix('%'), "Phần trăm đóng lệnh")
                price = _positive_number(parts[3], "Giá đóng lệnh")
            except ValueError as exc:
                _reply(f"❌ {exc}", chat_id, reply_to_id)
                return

        if percentage > 100:
            _reply("❌ Phần trăm đóng lệnh không được vượt quá 100%.", chat_id, reply_to_id)
            return

        if not math.isfinite(price) or price <= 0:
            price = get_latest_price(coin)
            
        if not math.isfinite(price) or price <= 0:
            send_telegram_message(
                f"❌ Không lấy được giá thị trường cho <b>{coin}</b> để đóng lệnh. Vui lòng nhập giá thủ công.",
                reply_to_message_id=reply_to_id,
                chat_id=chat_id
            )
            return
            
        from btc_scraper.trading.position_tracker import close_position, close_partial_position
        try:
            close_filters = {
                "trade_origin": "manual",
                "execution_mode": "manual",
                "order_creator": "user",
                "order_channel": "telegram",
            }
            if percentage >= 100:
                closed_data = close_position(coin, price, **close_filters)
                is_partial = False
            else:
                closed_data = close_partial_position(coin, price, percentage, **close_filters)
                is_partial = True
                
            pnl = closed_data["pnl_pct"]
            pnl_text = f"+{pnl:.2f}%" if pnl > 0 else f"{pnl:.2f}%"
            pnl_emoji = "🟢" if pnl >= 0 else "🔴"
            
            partial_text = f" (Chốt {percentage}%)" if is_partial else ""
            
            reply = (
                f"✅ <b>ĐÃ ĐÓNG VỊ THẾ THỦ CÔNG{partial_text}:</b>\n"
                f"• Coin: <b>{coin}</b> ({closed_data['direction']})\n"
                f"• Giá vào: <code>{closed_data['entry_price']:,.4f}</code>\n"
                f"• Giá đóng: <code>{price:,.4f}</code>\n"
                f"• Lãi/lỗ phần chốt: {pnl_emoji} <b>{pnl_text}</b>\n"
                f"• Lợi nhuận: <code>${closed_data['pnl_usd_actual']:.2f} USDT</code>\n"
                f"• Vốn chốt: <code>${closed_data['invested_usdt']:.2f} USDT</code>\n"
                f"• Hold: <code>{closed_data['hold_hours']} giờ</code>"
            )
            send_telegram_message(reply, reply_to_message_id=reply_to_id, chat_id=chat_id)
        except Exception as e:
            _reply(f"❌ Không thể đóng vị thế: {html.escape(str(e))}", chat_id, reply_to_id)

    else:
        _reply(f"❓ Lệnh <code>{html.escape(cmd)}</code> không được hỗ trợ. Dùng /help để xem danh sách lệnh.", chat_id, reply_to_id)
