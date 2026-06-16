import os
import certifi
from pymongo import MongoClient
from btc_scraper.core.config import MONGODB_URI

# Nếu không có MONGODB_URI từ .env, fallback về localhost
_db_uri = MONGODB_URI or "mongodb://localhost:27017/"

# Kết nối MongoDB (singleton)
if "mongodb+srv://" in _db_uri:
    client = MongoClient(_db_uri, tlsCAFile=certifi.where())
else:
    client = MongoClient(_db_uri)

# Tạo database 'besttime_crypto'
db = client['besttime_crypto']

# Collections
positions_col = db['positions']
closed_positions_col = db['closed_positions']
closed_trades_col = db['closed_trades']

# Tạo Index để tối ưu (đề phòng trùng lặp ID, tăng tốc độ query)
try:
    positions_col.create_index("id", unique=True)
    positions_col.create_index([("coin", 1), ("status", 1)])
    
    closed_positions_col.create_index("id")
    closed_positions_col.create_index("coin")
    
    closed_trades_col.create_index("id")
except Exception as e:
    print(f"Warning: Không thể tạo index MongoDB. Error: {e}")
