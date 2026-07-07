import os
import certifi
from pymongo import MongoClient
from btc_scraper.core.config import MONGODB_URI

# Nếu không có MONGODB_URI từ .env, fallback về localhost
_db_uri = MONGODB_URI or "mongodb://localhost:27017/"

# Kết nối MongoDB (singleton)
if "mongodb+srv://" in _db_uri or "mongodb.net" in _db_uri:
    client = MongoClient(_db_uri, tls=True, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=2000)
else:
    client = MongoClient(_db_uri, serverSelectionTimeoutMS=2000)

# Tạo database 'besttime_crypto'
db = client['besttime_crypto']

import sqlite3
import json
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

class CircuitBreakerCollection:
    def __init__(self, collection, db_name, col_name):
        self.collection = collection
        self.db_name = db_name
        self.col_name = col_name
        self.sqlite_db = os.path.join(os.path.dirname(__file__), "..", "data", "fallback_buffer.db")
        self._init_sqlite()

    def _init_sqlite(self):
        os.makedirs(os.path.dirname(self.sqlite_db), exist_ok=True)
        with sqlite3.connect(self.sqlite_db) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS fallback_buffer (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                db_name TEXT,
                col_name TEXT,
                operation TEXT,
                data TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )''')
            
    def _buffer_operation(self, operation: str, data: list):
        with sqlite3.connect(self.sqlite_db) as conn:
            for doc in data:
                if '_id' in doc:
                    doc['_id'] = str(doc['_id'])
                conn.execute(
                    'INSERT INTO fallback_buffer (db_name, col_name, operation, data) VALUES (?, ?, ?, ?)',
                    (self.db_name, self.col_name, operation, json.dumps(doc, default=str))
                )

    def insert_one(self, document, *args, **kwargs):
        try:
            return self.collection.insert_one(document, *args, **kwargs)
        except (ConnectionFailure, ServerSelectionTimeoutError):
            print(f"MongoDB down, buffering insert_one to {self.col_name}")
            self._buffer_operation("insert_one", [document])
            class FakeResult:
                inserted_id = None
            return FakeResult()

    def insert_many(self, documents, *args, **kwargs):
        try:
            return self.collection.insert_many(documents, *args, **kwargs)
        except (ConnectionFailure, ServerSelectionTimeoutError):
            print(f"MongoDB down, buffering insert_many to {self.col_name}")
            self._buffer_operation("insert_many", documents)
            class FakeResult:
                inserted_ids = []
            return FakeResult()
            
    def update_one(self, filter, update, *args, **kwargs):
        try:
            return self.collection.update_one(filter, update, *args, **kwargs)
        except (ConnectionFailure, ServerSelectionTimeoutError):
            print(f"MongoDB down, buffering update_one to {self.col_name}")
            self._buffer_operation("update_one", [{"filter": filter, "update": update}])
            class FakeResult:
                modified_count = 0
            return FakeResult()
            
    def __getattr__(self, name):
        return getattr(self.collection, name)

# Collections
positions_col = CircuitBreakerCollection(db['positions'], 'besttime_crypto', 'positions')
closed_positions_col = CircuitBreakerCollection(db['closed_positions'], 'besttime_crypto', 'closed_positions')
closed_trades_col = CircuitBreakerCollection(db['closed_trades'], 'besttime_crypto', 'closed_trades')
alternative_data_etf_flows_col = CircuitBreakerCollection(db['alternative_data_etf_flows'], 'besttime_crypto', 'alternative_data_etf_flows')
alternative_data_fetch_logs_col = CircuitBreakerCollection(db['alternative_data_fetch_logs'], 'besttime_crypto', 'alternative_data_fetch_logs')

# Tạo Index để tối ưu (đề phòng trùng lặp ID, tăng tốc độ query)
try:
    db['positions'].create_index("id", unique=True)
    db['positions'].create_index([("coin", 1), ("status", 1)])
    
    db['closed_positions'].create_index("id")
    db['closed_positions'].create_index("coin")
    
    db['closed_trades'].create_index("id")
    
    # Alternative data indexes
    db['alternative_data_etf_flows'].create_index([("source", 1), ("symbol", 1), ("flow_date", -1)], unique=True)
    db['alternative_data_etf_flows'].create_index([("symbol", 1), ("status", 1), ("fetched_at", -1)])
    db['alternative_data_fetch_logs'].create_index([("source", 1), ("endpoint", 1), ("fetched_at", -1)])
except Exception as e:
    print(f"Warning: Không thể tạo index MongoDB. Error: {e}")

