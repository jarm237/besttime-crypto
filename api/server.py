import os
import sys
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Literal

# Thêm đường dẫn project vào sys.path để import btc_scraper
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from btc_scraper.trading import position_tracker
from btc_scraper.core.config import COINS
from btc_scraper.core.operational_resilience import service_health

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


def _get_queue_size() -> int:
    try:
        import main as main_module
        q = getattr(main_module, "ai_queue", None)
        if q is not None and hasattr(q, "qsize"):
            return q.qsize()
    except Exception:
        pass
    return 0


def _get_ws_health() -> int:
    try:
        import main as main_module
        ws_manager = getattr(main_module, "_ws_manager", None)
        if ws_manager is not None and hasattr(ws_manager, "is_healthy"):
            return 1 if ws_manager.is_healthy() else 0
    except Exception:
        pass
    return 0


def _get_db_conn_ok() -> int:
    try:
        from btc_scraper.core.db import client as mongodb_client
        mongodb_client.admin.command("ping")
        return 1
    except Exception:
        return 0


def _get_model_ok() -> bool:
    try:
        from btc_scraper.ml_engine.meta_model import MODEL_OUT
        return bool(MODEL_OUT.exists())
    except Exception:
        return False


def _health_payload() -> dict:
    # WS is the exchange market-data dependency. It is explicitly included in
    # readiness rather than allowing a process to report ready while blind.
    return service_health(db_ok=bool(_get_db_conn_ok()), exchange_ok=bool(_get_ws_health()), model_ok=_get_model_ok(), data_path=DATA_DIR)


def _get_causal_alpha() -> float:
    try:
        from btc_scraper.ml_engine.causal_context_bridge import _get_causal_alpha as _alpha_fn
        return float(_alpha_fn())
    except Exception:
        try:
            return float(os.environ.get("CAUSAL_ALPHA", "0.0"))
        except Exception:
            return 0.0


def _get_rl_model_version() -> str:
    try:
        from btc_scraper.trading.position_tracker import load_latest_ppo_model
        model_path = load_latest_ppo_model()
        if not model_path:
            return "none"
        return os.path.basename(model_path)
    except Exception:
        return "none"


def _escape_label_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")


def _get_open_positions_count() -> int:
    try:
        return len(position_tracker.get_open_positions())
    except Exception:
        return 0

def _get_total_realized_pnl() -> float:
    try:
        perf = position_tracker.get_performance_summary("ALL")
        if isinstance(perf, dict):
            return float(perf.get("total_net_profit", 0.0))
        return 0.0
    except Exception:
        return 0.0

def _get_causal_risk_level() -> int:
    try:
        if not os.path.exists(LATEST_SIGNALS_FILE):
            return 0
        with open(LATEST_SIGNALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            signals = data.get("analysis", data)
            max_level = 0
            risk_map = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
            for _, ana in signals.items():
                if isinstance(ana, dict):
                    level = risk_map.get(str(ana.get("causal_context_risk", "")).upper(), 0)
                    if level > max_level:
                        max_level = level
            return max_level
    except Exception:
        return 0

def _metrics_response() -> Response:
    queue_size = _get_queue_size()
    ws_health = _get_ws_health()
    db_conn_ok = _get_db_conn_ok()
    causal_alpha = _get_causal_alpha()
    rl_model_version = _get_rl_model_version()
    
    open_positions = _get_open_positions_count()
    total_pnl = _get_total_realized_pnl()
    causal_risk = _get_causal_risk_level()
    pipeline_status = 1 if ws_health and db_conn_ok else 0

    lines = [
        "# HELP besttime_queue_size Size of AI analysis queue",
        "# TYPE besttime_queue_size gauge",
        f"besttime_queue_size {queue_size}",
        "# HELP besttime_ws_healthy Binance websocket health state (1 healthy, 0 unhealthy)",
        "# TYPE besttime_ws_healthy gauge",
        f"besttime_ws_healthy {ws_health}",
        "# HELP besttime_db_conn_ok MongoDB connection health (1 ok, 0 fail)",
        "# TYPE besttime_db_conn_ok gauge",
        f"besttime_db_conn_ok {db_conn_ok}",
        "# HELP besttime_causal_alpha Current CAUSAL_ALPHA blending factor",
        "# TYPE besttime_causal_alpha gauge",
        f"besttime_causal_alpha {causal_alpha}",
        "# HELP besttime_rl_model_info Latest RL model version info label",
        "# TYPE besttime_rl_model_info gauge",
        f"besttime_rl_model_info{{version=\"{_escape_label_value(rl_model_version)}\"}} 1",
        "# HELP besttime_open_positions_count Number of open positions",
        "# TYPE besttime_open_positions_count gauge",
        f"besttime_open_positions_count {open_positions}",
        "# HELP besttime_total_realized_pnl Total realized PnL",
        "# TYPE besttime_total_realized_pnl gauge",
        f"besttime_total_realized_pnl {total_pnl}",
        "# HELP besttime_causal_risk_level Max causal risk level across signals (0=LOW, 1=MEDIUM, 2=HIGH, 3=CRITICAL)",
        "# TYPE besttime_causal_risk_level gauge",
        f"besttime_causal_risk_level {causal_risk}",
        "# HELP besttime_pipeline_status Overall pipeline status",
        "# TYPE besttime_pipeline_status gauge",
        f"besttime_pipeline_status {pipeline_status}",
    ]
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.get("/live")
def live():
    """Liveness only: the process can answer requests."""
    return {"live": True}


@app.get("/dependencies")
def dependencies():
    return _health_payload()["dependencies"]


@app.get("/ready")
def ready(response: Response):
    payload = _health_payload()
    if not payload["ready"]:
        response.status_code = 503
    return payload


def _read_prediction_logs(logs_dir: str, days: int = 7) -> list:
    """Đọc nhiều file predictions_YYYY-MM-DD.log trong khoảng `days` ngày gần nhất.
    
    - days=0: đọc tất cả các file có pattern predictions_YYYY-MM-DD.log
    - days>0: chỉ đọc các file trong `days` ngày gần nhất (UTC)
    - Backward-compatible: nếu có file predictions.log cũ cũng đọc kèm.
    """
    import glob
    from datetime import datetime, timezone, timedelta

    preds = []

    # Tính ngưỡng ngày tối thiểu (UTC)
    if days > 0:
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).date()
    else:
        cutoff_date = None

    # Đọc các file theo ngày: predictions_YYYY-MM-DD.log
    pattern = os.path.join(logs_dir, "predictions_????-??-??.log")
    daily_files = sorted(glob.glob(pattern))
    for fpath in daily_files:
        # Lọc theo ngày từ tên file
        fname = os.path.basename(fpath)  # predictions_YYYY-MM-DD.log
        try:
            file_date_str = fname[len("predictions_"):-len(".log")]  # YYYY-MM-DD
            from datetime import date
            file_date = date.fromisoformat(file_date_str)
        except Exception:
            file_date = None

        if cutoff_date and file_date and file_date < cutoff_date:
            continue  # bỏ qua các file quá cũ

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        preds.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            continue

    # Backward-compatible: đọc file predictions.log cũ nếu còn tồn tại
    legacy_path = os.path.join(logs_dir, "predictions.log")
    if os.path.exists(legacy_path):
        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        # Lọc theo ngày nếu cần
                        if cutoff_date:
                            ts = obj.get("timestamp", "")
                            day_str = ts[:10]
                            try:
                                from datetime import date
                                obj_date = date.fromisoformat(day_str)
                                if obj_date < cutoff_date:
                                    continue
                            except Exception:
                                pass
                        preds.append(obj)
                    except Exception:
                        continue
        except Exception:
            pass

    # Sắp xếp theo timestamp tăng dần
    preds.sort(key=lambda x: x.get("timestamp", ""))
    return preds


def _normalize_signal_item(item: dict) -> dict:
    """Ensure signal item has a stable signal_score shape for the frontend."""
    if not isinstance(item, dict):
        return {}

    out = dict(item)
    signal_score = out.get("signal_score")
    if not isinstance(signal_score, dict):
        signal_score = {}

    meta_prob = signal_score.get("meta_confidence")
    meta_pct = signal_score.get("meta_confidence_pct")

    if meta_pct is None and meta_prob is not None:
        try:
            meta_pct = int(round(float(meta_prob) * 100))
        except Exception:
            meta_pct = None
    if meta_prob is None and meta_pct is not None:
        try:
            meta_prob = float(meta_pct) / 100.0
        except Exception:
            meta_prob = None

    signal_score.setdefault("action", "NEUTRAL")
    signal_score.setdefault("score", None)
    signal_score.setdefault("display_score", 0)
    signal_score.setdefault("display_label", "NEUTRAL")
    signal_score.setdefault("confidence", None)
    signal_score.setdefault("position_size", None)
    signal_score.setdefault("meta_error", None)
    signal_score["meta_confidence"] = meta_prob
    signal_score["meta_confidence_pct"] = meta_pct

    out["signal_score"] = signal_score
    return out

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
                    import asyncio
                    from btc_scraper.trading.auto_trader import auto_trader as _at
                    asyncio.get_event_loop().run_until_complete(
                        _at.close_position_on_exchange(
                            coin=coin,
                            direction=open_pos.get("direction", ""),
                            invested_usdt=open_pos.get("invested_usdt", 0.0),
                            entry_price=open_pos.get("entry_price", 0.0),
                            current_price=data.sell_price,
                        )
                    )
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
                    import asyncio
                    from btc_scraper.trading.auto_trader import auto_trader as _at
                    invested_usdt = open_pos.get("invested_usdt", 0.0)
                    partial_invested = invested_usdt * (data.percentage / 100)
                    asyncio.get_event_loop().run_until_complete(
                        _at.close_position_on_exchange(
                            coin=coin,
                            direction=open_pos.get("direction", ""),
                            invested_usdt=partial_invested,
                            entry_price=open_pos.get("entry_price", 0.0),
                            current_price=data.sell_price,
                        )
                    )
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
def get_meta_model_metrics(days: int = 7):
    """Trả về metrics của meta-model và sample dự đoán gần nhất từ logs/predictions_YYYY-MM-DD.log.
    
    - days: số ngày gần nhất cần lấy (mặc định 7). Truyền 0 để lấy tất cả.
    """
    try:
        from btc_scraper.ml_engine.meta_model import get_model_metrics
        model_metrics = get_model_metrics()
    except Exception:
        model_metrics = {}

    logs_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
    preds = _read_prediction_logs(logs_dir, days=days)

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

            # Hỗ trợ cả 2 định dạng file:
            # 1) {"analysis": {...}, "mtf_analysis": {...}}
            # 2) {...signals map...}
            if isinstance(data, dict) and isinstance(data.get("analysis"), dict):
                signals = data.get("analysis") or {}
            elif isinstance(data, dict):
                signals = data
            else:
                signals = {}

            normalized = {}
            for key, item in signals.items():
                normalized[key] = _normalize_signal_item(item)

            return {"signals": normalized}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không thể đọc tín hiệu: {str(e)}")

import threading
from typing import List, Dict, Any

# Global status tracking for backtests
active_backtest_task = {
    "status": "idle",
    "progress": 0,
    "run_id": None,
    "error": None
}

class BacktestRunRequest(BaseModel):
    initial_capital: float = 10000.0
    timeframe: str = "15m"
    coins: List[str] = ["BTC", "ETH", "SOL"]
    latency_ms: int = 250
    fee_bps: float = 5.0
    slippage_bps: float = 1.0

def _run_backtest_in_background(payload: Dict[str, Any]):
    global active_backtest_task
    active_backtest_task["status"] = "running"
    active_backtest_task["progress"] = 10
    active_backtest_task["error"] = None
    
    try:
        from scripts.run_backtest_v2 import run_backtest_pipeline
        active_backtest_task["progress"] = 30
        
        # Build override config
        override_config = {
            "initial_capital": payload["initial_capital"],
            "timeframe": payload["timeframe"],
            "coins": payload["coins"],
            "fee_model": {
                "spot_taker_bps": payload["fee_bps"] * 2.0,
                "spot_maker_bps": payload["fee_bps"] * 2.0,
                "futures_taker_bps": payload["fee_bps"],
                "futures_maker_bps": max(2.0, payload["fee_bps"] / 2.5),
                "is_futures": True
            },
            "slippage_model": {
                "enabled": True,
                "mode": "rule_v1",
                "base_slippage_bps": payload["slippage_bps"]
            },
            "latency_model": {
                "enabled": True,
                "latency_ms": payload["latency_ms"]
            }
        }
        
        active_backtest_task["progress"] = 50
        result = run_backtest_pipeline(config_data=override_config)
        active_backtest_task["progress"] = 90
        
        # Generate markdown report
        from subprocess import run as sub_run
        sub_run([sys.executable, "scripts/generate_backtest_report.py"])
        
        active_backtest_task["progress"] = 100
        active_backtest_task["status"] = "completed"
        active_backtest_task["run_id"] = result.get("run_id")
    except Exception as e:
        active_backtest_task["status"] = "error"
        active_backtest_task["error"] = str(e)
        active_backtest_task["progress"] = 0

@app.post("/api/backtests/run")
def run_backtest(req: BacktestRunRequest):
    global active_backtest_task
    if active_backtest_task["status"] == "running":
        raise HTTPException(status_code=400, detail="Một tác vụ backtest khác đang được thực thi.")
        
    payload = {
        "initial_capital": req.initial_capital,
        "timeframe": req.timeframe,
        "coins": req.coins,
        "latency_ms": req.latency_ms,
        "fee_bps": req.fee_bps,
        "slippage_bps": req.slippage_bps
    }
    
    thread = threading.Thread(target=_run_backtest_in_background, args=(payload,))
    thread.daemon = True
    thread.start()
    
    return {"status": "started"}

@app.get("/api/backtests/active-task")
def get_active_backtest_task():
    global active_backtest_task
    return active_backtest_task

@app.get("/api/backtests/history")
def get_backtest_history():
    runs_dir = os.path.join(DATA_DIR, "backtests", "runs")
    if not os.path.exists(runs_dir):
        return []
        
    history = []
    for filename in os.listdir(runs_dir):
        if filename.startswith("run_") and filename.endswith(".json"):
            filepath = os.path.join(runs_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                history.append({
                    "run_id": data.get("run_id"),
                    "timestamp": data.get("timestamp"),
                    "coins": data.get("config", {}).get("coins", []),
                    "total_return": data.get("metrics", {}).get("total_return", 0.0),
                    "sharpe": data.get("metrics", {}).get("sharpe", 0.0),
                    "max_drawdown": data.get("metrics", {}).get("max_drawdown", 0.0),
                    "n_trades": data.get("metrics", {}).get("n_trades", 0),
                    "passed": data.get("approval_status", {}).get("passed", False)
                })
            except Exception:
                continue
                
    # Sort chronological
    history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return history

@app.get("/api/backtests/report/{run_id}")
def get_backtest_report(run_id: str):
    filepath = os.path.join(DATA_DIR, "backtests", "runs", f"run_{run_id}.json")
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Không tìm thấy báo cáo backtest.")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi đọc file: {e}")

@app.get("/api/config")
def get_config():
    """Lấy danh sách cấu hình, bao gồm danh sách COINS."""
    return {"coins": COINS}

@app.get("/metrics")
def get_metrics():
    """Expose Prometheus metrics for Grafana / Prometheus scraping."""
    return _metrics_response()


# ── Phase 10: Execution Intelligence Endpoints ────────────────────────────────

from pathlib import Path as _Path

# Lazy singleton execution engine (initialised on first request)
_exec_engine = None

def _get_exec_engine():
    global _exec_engine
    if _exec_engine is None:
        try:
            from btc_scraper.execution import ExecutionEngine, ExecutionConfig
            cfg_path = _Path(__file__).resolve().parents[1] / "execution_config.json"
            cfg = ExecutionConfig.from_json(str(cfg_path))
            _exec_engine = ExecutionEngine(config=cfg)
        except Exception:
            from btc_scraper.execution import ExecutionEngine
            _exec_engine = ExecutionEngine()
    return _exec_engine


@app.get("/api/execution/config")
def get_execution_config():
    """Return the current execution intelligence configuration."""
    try:
        engine = _get_exec_engine()
        return engine.config.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class PaperOrderRequest(BaseModel):
    coin: str = "BTC"
    signal_raw: str = "BUY (Crossover)"
    close_price: float = 50000.0
    high_price: float = 51000.0
    low_price: float = 49000.0
    volume: float = 100.0
    urgency: str = "NORMAL"


@app.post("/api/execution/submit")
def submit_paper_order(req: PaperOrderRequest):
    """Submit a paper/simulated order through the execution engine."""
    try:
        engine = _get_exec_engine()
        signal = {
            "coin": req.coin,
            "signal_raw": req.signal_raw,
        }
        candle = {
            "close": req.close_price,
            "high": req.high_price,
            "low": req.low_price,
            "volume": req.volume,
        }
        record = engine.submit_paper(signal, candle, urgency=req.urgency)
        return record.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/execution/fills")
def get_execution_fills(limit: int = 50):
    """Return recent filled executions with quality metrics."""
    try:
        engine = _get_exec_engine()
        fills = engine.get_recent_fills(limit=limit)
        return {"fills": fills, "count": len(fills)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/execution/stats")
def get_execution_stats():
    """Aggregate execution stats: avg slippage, reject rate, liquidity scores, by-coin breakdown."""
    try:
        engine = _get_exec_engine()
        return engine.get_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/execution/quality-report")
def get_execution_quality_report():
    """Generate and return the latest post-trade execution quality report."""
    try:
        engine = _get_exec_engine()
        report = engine.analyze_quality(limit=500)
        if not report:
            return {"message": "No filled executions to analyze yet."}
        return report
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=True)
