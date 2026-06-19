import os
import sys
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Literal

# Thêm đường dẫn project vào sys.path để import btc_scraper
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from btc_scraper.trading import position_tracker
from btc_scraper.core.config import COINS

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

class PositionClosePartial(BaseModel):
    sell_price: float
    percentage: float

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
    for p in positions:
        p["is_auto"] = "[AUTO-" in p.get("note", "")
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
        open_pos = next((p for p in position_tracker.get_open_positions() if p["coin"].upper() == coin.upper()), None)
        
        closed_data = position_tracker.close_position(
            coin=coin,
            sell_price=data.sell_price
        )
        
        if open_pos and "[AUTO-" in open_pos.get("note", ""):
            note = open_pos.get("note", "")
            mode = "TESTNET" if "TESTNET" in note else ("LIVE" if "LIVE" in note else "DRY_RUN")
            
            try:
                from btc_scraper.trading.auto_trader import auto_trader
                pnl_pct = closed_data.get("pnl_pct", 0.0)
                result_type = "WIN" if pnl_pct > 0 else "LOSS"
                auto_trader._record_trade_result(result_type)
            except Exception as e:
                print(f"Lỗi cập nhật circuit breaker: {e}")
                
            if mode in ("TESTNET", "LIVE"):
                try:
                    from btc_scraper.core.ccxt_client import CCXTClient
                    client = CCXTClient.from_env()
                    client.dry_run = False
                    
                    symbol = f"{coin.upper()}/USDT"
                    direction = open_pos.get("direction")
                    invested_usdt = open_pos.get("invested_usdt", 0.0)
                    entry_price = open_pos.get("entry_price", 0.0)
                    current_price = data.sell_price
                    
                    if entry_price > 0:
                        current_val = invested_usdt * (current_price / entry_price)
                        if direction == "LONG":
                            client.create_market_sell(symbol, current_val)
                        else:
                            client.create_market_buy(symbol, current_val)
                except Exception as exchange_err:
                    print(f"Lỗi đóng lệnh trên exchange: {exchange_err}")
                    
        return {"status": "success", "data": closed_data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/positions/{coin}/close-partial")
def close_partial_position(coin: str, data: PositionClosePartial):
    """Đóng một phần vị thế đang mở."""
    try:
        open_pos = next((p for p in position_tracker.get_open_positions() if p["coin"].upper() == coin.upper()), None)
        
        closed_data = position_tracker.close_partial_position(
            coin=coin,
            sell_price=data.sell_price,
            percentage=data.percentage
        )
        
        if open_pos and "[AUTO-" in open_pos.get("note", ""):
            note = open_pos.get("note", "")
            mode = "TESTNET" if "TESTNET" in note else ("LIVE" if "LIVE" in note else "DRY_RUN")
            
            # Note: We do not record circuit breaker results for partial closes 
            # to avoid messing up the win/loss streak logic until the final close.
                
            if mode in ("TESTNET", "LIVE"):
                try:
                    from btc_scraper.core.ccxt_client import CCXTClient
                    client = CCXTClient.from_env()
                    client.dry_run = False
                    
                    symbol = f"{coin.upper()}/USDT"
                    direction = open_pos.get("direction")
                    invested_usdt = open_pos.get("invested_usdt", 0.0)
                    entry_price = open_pos.get("entry_price", 0.0)
                    current_price = data.sell_price
                    
                    if entry_price > 0:
                        # Partial close amount based on original invested USDT and percentage
                        closed_usdt = invested_usdt * (data.percentage / 100)
                        current_val = closed_usdt * (current_price / entry_price)
                        if direction == "LONG":
                            client.create_market_sell(symbol, current_val)
                        else:
                            client.create_market_buy(symbol, current_val)
                except Exception as exchange_err:
                    print(f"Lỗi đóng lệnh một phần trên exchange: {exchange_err}")
                    
        return {"status": "success", "data": closed_data}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/auto-trade/status")
def get_auto_trade_status():
    """Lấy trạng thái cấu hình và circuit breaker của AutoTrader."""
    try:
        from btc_scraper.trading.auto_trader import auto_trader
        return auto_trader.status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi lấy trạng thái auto-trade: {str(e)}")

@app.get("/api/auto-trade/logs")
def get_auto_trade_logs():
    """Lấy lịch sử giao dịch tự động từ auto_trade_log.json."""
    try:
        from btc_scraper.trading.auto_trader import AUTO_TRADE_LOG
        if not AUTO_TRADE_LOG.exists():
            return []
        with open(AUTO_TRADE_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi đọc log auto-trade: {str(e)}")

@app.get("/api/meta-model")
def get_meta_model_info():
    """Lấy thông tin metrics và feature importance của Meta Model."""
    metrics_path = os.path.join(os.path.dirname(__file__), "..", "logs", "meta_model.json")
    importance_path = os.path.join(os.path.dirname(__file__), "..", "logs", "meta_feature_importance.json")
    
    out = {
        "model_exists": os.path.exists(os.path.join(os.path.dirname(__file__), "..", "logs", "meta_model.joblib")),
        "metrics": None,
        "feature_importance": None
    }
    
    if os.path.exists(metrics_path):
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                out["metrics"] = json.load(f)
        except Exception as e:
            out["metrics_error"] = str(e)
            
    if os.path.exists(importance_path):
        try:
            with open(importance_path, "r", encoding="utf-8") as f:
                out["feature_importance"] = json.load(f)
        except Exception as e:
            out["importance_error"] = str(e)
            
    return out


@app.get("/api/meta-model/metrics")
def get_meta_model_metrics():
    """Trả về metrics của meta-model và sample dự đoán gần nhất từ logs/predictions.log"""
    try:
        from btc_scraper.ml_engine.meta_model import get_model_metrics
        model_metrics = get_model_metrics()
    except Exception:
        model_metrics = {}

    preds_path = os.path.join(os.path.dirname(__file__), "..", "logs", "predictions.log")
    preds = []
    if os.path.exists(preds_path):
        try:
            with open(preds_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        preds.append(json.loads(line))
                    except Exception:
                        # skip malformed lines
                        continue
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Không thể đọc predictions.log: {e}")

    summary = {"total_predictions": len(preds)}
    if preds:
        avg_prob = sum(p.get("probability", 0.0) for p in preds) / len(preds)
        summary["avg_probability"] = avg_prob
        coins = {}
        for p in preds:
            c = p.get("coin") or "UNKNOWN"
            coins[c] = coins.get(c, 0) + 1
        summary["by_coin"] = coins

    return {
        "model_metrics": model_metrics,
        "predictions_count": len(preds),
        "predictions_sample": preds[-100:],
        "summary": summary,
    }

@app.get("/api/performance")
def get_performance():
    """Lấy báo cáo hiệu suất chiến lược giao dịch."""
    perf_all = position_tracker.get_performance_summary("ALL")
    perf_auto = position_tracker.get_performance_summary("AUTO")
    perf_manual = position_tracker.get_performance_summary("MANUAL")
    return {
        "performance": perf_all,
        "performance_auto": perf_auto,
        "performance_manual": perf_manual
    }

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
