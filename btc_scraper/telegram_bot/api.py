import re
import requests
from btc_scraper.core.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

def sanitize_telegram_error(msg: str | Exception, token: str | None = None) -> str:
    """Sanitize Telegram bot token from error messages and URL outputs."""
    text = str(msg)
    active_token = token or TELEGRAM_BOT_TOKEN
    if active_token:
        text = text.replace(active_token, "***REDACTED***")
    return re.sub(r"bot[0-9]+:[A-Za-z0-9_-]+", "bot***REDACTED***", text)

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
    import os
    if os.getenv("TELEGRAM_NOTIFICATIONS_ENABLED", "true").lower() in ("false", "0", "off", "no"):
        return None

    active_token = (os.getenv("TELEGRAM_BOT_TOKEN") if os.getenv("TELEGRAM_BOT_TOKEN") is not None else TELEGRAM_BOT_TOKEN).strip()
    if not active_token:
        return None

    target_chat_id = chat_id if chat_id is not None else (os.getenv("TELEGRAM_CHAT_ID") or TELEGRAM_CHAT_ID)
    if not target_chat_id:
        return None

    url = f"https://api.telegram.org/bot{active_token}/sendMessage"
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
        if resp.status_code == 400 and parse_mode:
            print(f"\n[Warning] Telegram HTML parse error: {resp.text}")
            print("[Telegram Bot] Thu gui lai duoi dang Plain Text (fallback)...")
            payload_fallback = payload.copy()
            payload_fallback.pop("parse_mode", None)
            resp = requests.post(url, json=payload_fallback, timeout=10)
            
        resp.raise_for_status()
        data = resp.json()
        return data.get("result", {}).get("message_id")
    except Exception as e:
        safe_err = sanitize_telegram_error(e, TELEGRAM_BOT_TOKEN)
        print(f"\n[Warning] Khong the gui tin nhan Telegram: {safe_err}")
        if 'resp' in locals() and resp is not None:
            print(f"[Telegram Response Body] {resp.text}")
        return None


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

