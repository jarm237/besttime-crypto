import os
import sys
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Literal

# Thêm đường dẫn project vào sys.path để import btc_scraper
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from btc_scraper import position_tracker
from btc_scraper.config import COINS

app = FastAPI(title="BestTime Crypto API")

# Cấu hình CORS để Frontend (Vite) có thể gọi API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Trong thực tế nên giới hạn origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
LATEST_SIGNALS_FILE = os.path.join(DATA_DIR, "latest_signals.json")

class PositionCreate(BaseModel):
    coin: str
    entry_price: float
    direction: Literal["LONG", "SHORT"] = "LONG"
    note: str = ""
    invested_usdt: float = 0.0

class PositionClose(BaseModel):
    sell_price: float

@app.get("/api/ai-analysis")
def get_ai_analysis():
    try:
        with open("data/latest_ai_analysis.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"timestamp": 0, "report": "Chưa có dữ liệu phân tích từ Gemini AI. Vui lòng chờ..."}

@app.get("/api/positions")
def get_positions():
    """Lấy danh sách các vị thế đang mở."""
    positions = position_tracker.get_open_positions()
    return {"positions": positions}

@app.post("/api/positions")
def add_position(pos: PositionCreate):
    """Thêm một vị thế mới."""
    try:
        new_pos = position_tracker.add_position(
            coin=pos.coin,
            entry_price=pos.entry_price,
            direction=pos.direction,
            note=pos.note,
            invested_usdt=pos.invested_usdt
        )
        return {"status": "success", "position": new_pos}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/positions/{coin}/close")
def close_position(coin: str, data: PositionClose):
    """Đóng một vị thế đang mở."""
    try:
        closed_data = position_tracker.close_position(
            coin=coin,
            sell_price=data.sell_price
        )
        return {"status": "success", "data": closed_data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/performance")
def get_performance():
    """Lấy báo cáo hiệu suất chiến lược giao dịch."""
    perf = position_tracker.get_performance_summary()
    return {"performance": perf}

@app.get("/api/market-signals")
def get_market_signals():
    """Lấy dữ liệu phân tích thị trường mới nhất (RSI, Trend, Signals)."""
    if not os.path.exists(LATEST_SIGNALS_FILE):
        return {"signals": {}}
    try:
        with open(LATEST_SIGNALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {"signals": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể đọc tín hiệu: {str(e)}")

@app.get("/api/config")
def get_config():
    """Lấy danh sách cấu hình, bao gồm danh sách COINS."""
    return {"coins": COINS}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True)
