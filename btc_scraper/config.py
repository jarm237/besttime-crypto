# BTC/Multi-coin OHLCV Scraper - Cấu hình

import os
from dotenv import load_dotenv

# Tải cấu hình từ file .env nếu có
load_dotenv()

# Danh sách các coin cần theo dõi (tự động ghép cặp USDT/USDT-spot)
COINS = [
    "BTC", 
    "ETH", 
    "BNB", 
    "SOL", 
    "ZEC", 
    "XRP", 
    "DOGE", 
    "WLD", 
    "XLM", 
    "NEAR", 
    "AVAX", 
    "TAO", 
    "TRB", 
    "AEVO", 
    "ENA", 
    "AR", 
    "IOTA", 
    "XPL", 
    "NAORIS", 
    "SOPH", 
    "TSLAB", 
    "XAUT", 
    "TRX",
    "TRUMP"
]

INTERVAL = "15m"            # Khung nến 15 phút
LIMIT = 210                  # Số nến lấy mỗi lần — cần tối thiểu 200 để tính SMA200 (+ 10 buffer)
FETCH_INTERVAL_MINUTES = 15   # Tần suất cập nhật (phút)

# Telegram credentials
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Gemini API Keys (round-robin, tối đa 5 key)
# Ưu tiên dùng GEMINI_API_KEY_1..5, fallback về GEMINI_API_KEY nếu có
_raw_keys = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3"),
    os.getenv("GEMINI_API_KEY_4"),
    os.getenv("GEMINI_API_KEY_5"),
    os.getenv("GEMINI_API_KEY"),  # fallback key đơn cũ
]
GEMINI_API_KEYS: list[str] = [k for k in _raw_keys if k]  # Lọc bỏ None/rỗng
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else None  # tương thích ngược
