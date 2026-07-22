import os
import time
import requests
from btc_scraper.core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from .api import send_telegram_message
from .commands import handle_telegram_command

BOT_COMMANDS = [
    {"command": "start", "description": "Mở hướng dẫn sử dụng"},
    {"command": "help", "description": "Xem danh sách lệnh"},
    {"command": "status", "description": "Xem trạng thái hệ thống"},
    {"command": "scan", "description": "Quét thị trường ngay"},
    {"command": "perf", "description": "Xem hiệu suất giao dịch"},
    {"command": "positions", "description": "Xem các vị thế đang mở"},
    {"command": "buy", "description": "Mở vị thế thủ công"},
    {"command": "close", "description": "Đóng toàn bộ hoặc một phần"},
]


def _allowed_chat_ids() -> set[str]:
    configured = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "")
    chat_ids = {value.strip() for value in configured.split(",") if value.strip()}
    if TELEGRAM_CHAT_ID:
        chat_ids.add(str(TELEGRAM_CHAT_ID).strip())
    return chat_ids


def _register_bot_commands() -> None:
    """Keep Telegram's command menu synchronized with supported commands."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands"
    try:
        response = requests.post(url, json={"commands": BOT_COMMANDS}, timeout=10)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            print(f"[Telegram Bot] Khong the cap nhat menu lenh: {payload}")
    except Exception as exc:
        print(f"[Telegram Bot] Loi khi cap nhat menu lenh: {exc}")


def start_telegram_listener() -> None:
    """Background listener to poll for Telegram commands."""
    if not TELEGRAM_BOT_TOKEN or not _allowed_chat_ids():
        print("[Telegram Bot] TELEGRAM_BOT_TOKEN hoac danh sach chat duoc phep chua duoc cau hinh. Bo qua khoi dong listener.")
        return

    print("[Telegram Bot] Dang khoi dong Telegram Command Listener...")
    _register_bot_commands()
    
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
            allowed_list = _allowed_chat_ids()

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
