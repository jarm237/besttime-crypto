"""
Position Tracker — Theo dõi vị thế thủ công và đưa ra khuyến nghị chốt lời/cắt lỗ.

Luồng sử dụng:
  1. Nhập lệnh:  add_position(coin, entry_price, direction="LONG")
  2. Mỗi lần quét: evaluate_positions(analysis_results) → trả về list khuyến nghị
  3. Đóng lệnh:  close_position(coin, sell_price) → trả về dict chỉ số đánh giá
"""

import os
from datetime import datetime
import uuid
from typing import Literal
import numpy as np
from pathlib import Path

import torch
from btc_scraper.analysis import calculate_tp_sl
from btc_scraper.core.db import positions_col, closed_positions_col, closed_trades_col

# Cache PPO model globally to avoid reloading on every cycle
_PPO_MODEL_CACHE = None
_LAST_MODEL_PATH = None
_LSTM_STATE_CACHE = {}

_LSTM_CACHE_FILE = "logs/rl_lstm_cache.pkl"

def save_lstm_cache():
    """Lưu _LSTM_STATE_CACHE xuống file pickle."""
    try:
        os.makedirs(os.path.dirname(_LSTM_CACHE_FILE), exist_ok=True)
        import pickle
        with open(_LSTM_CACHE_FILE, "wb") as f:
            pickle.dump(_LSTM_STATE_CACHE, f)
    except Exception as e:
        print(f"[RL Exit Agent] Warning: Không thể lưu LSTM cache: {e}")

def load_lstm_cache():
    """Khôi phục _LSTM_STATE_CACHE từ file pickle."""
    global _LSTM_STATE_CACHE
    if os.path.exists(_LSTM_CACHE_FILE):
        try:
            import pickle
            with open(_LSTM_CACHE_FILE, "rb") as f:
                _LSTM_STATE_CACHE = pickle.load(f)
            print(f"[RL Exit Agent] Restored LSTM state cache from {_LSTM_CACHE_FILE} (found {len(_LSTM_STATE_CACHE)} keys)")
        except Exception as e:
            print(f"[RL Exit Agent] Warning: Không thể khôi phục LSTM cache: {e}")
            _LSTM_STATE_CACHE = {}
    else:
        _LSTM_STATE_CACHE = {}

# Khôi phục cache ngay khi load module
load_lstm_cache()


def _get_default_device() -> str:
    try:
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def load_latest_ppo_model() -> str | None:
    """Tìm file zip model PPO mới nhất."""
    rl_dir = Path("logs/rl_models")
    if not rl_dir.exists():
        return None
    matches = sorted(rl_dir.glob("rl_exit_ppo_*.zip"))
    if matches:
        return str(matches[-1])
    matches_simple = sorted(rl_dir.glob("rl_exit_ppo.zip"))
    if matches_simple:
        return str(matches_simple[-1])
    return None

def get_ppo_model(device: str = "auto"):
    """Tải model PPO động và cache."""
    global _PPO_MODEL_CACHE, _LAST_MODEL_PATH
    model_path = load_latest_ppo_model()
    if not model_path:
        return None
    if _PPO_MODEL_CACHE is None or _LAST_MODEL_PATH != model_path:
        try:
            from sb3_contrib import RecurrentPPO
            if device == "auto":
                device = _get_default_device()
            elif device == "cuda" and not torch.cuda.is_available():
                print("[RL Exit Agent] CUDA requested but not available. Falling back to CPU.")
                device = "cpu"
            _PPO_MODEL_CACHE = RecurrentPPO.load(model_path, device=device)
            _LAST_MODEL_PATH = model_path
            print(f"[RL Exit Agent] Loaded RecurrentPPO model: {model_path} on device={device}")
        except Exception as e:
            print(f"[RL Exit Agent] Warning: Lỗi khi load model: {e}")
            return None
    return _PPO_MODEL_CACHE


def _log_rl_shadow_prediction(
    coin: str,
    rl_action: int,
    pos_meta_prob: float | None,
    position_id: str | None = None,
) -> None:
    if os.getenv("RL_EXIT_SHADOW_MODE", "false").lower() != "true":
        return
    try:
        from scripts.shadow_log import log_rl_shadow_prediction

        symbol = f"{coin}USDT"
        log_rl_shadow_prediction(
            symbol=symbol,
            rl_action=rl_action,
            meta_prob=float(pos_meta_prob or 0.0),
            position_id=position_id,
            note="RL Exit shadow recommendation",
        )
    except Exception as e:
        print(f"[RL Exit Shadow] Failed to log RL shadow prediction for {coin}: {e}")


def _build_rl_observation(
    ana: dict,
    avg_confidence: float,
    avg_step: int,
    weighted_entry: float,
    current_pnl: float,
    direction: str,
    min_pnl: float,
    average_correlation: float
) -> np.ndarray:
    """Tạo observation vector 20 chiều đồng bộ với TradeExitEnv."""
    obs = np.zeros(20, dtype=np.float32)
    
    # Feature 0: RSI (0-100 -> -1 to 1)
    rsi = float(ana.get("rsi", 50.0))
    obs[0] = (rsi - 50.0) / 50.0
    
    # Feature 1: MACD Hist (tanh normalized)
    macd_hist = float(ana.get("macd_hist", 0.0))
    obs[1] = np.tanh(macd_hist)
    
    # Feature 2: ATR % (0, inf -> 0, 1)
    atr_pct = float(ana.get("atr_pct", 2.0))
    obs[2] = np.tanh(atr_pct / 2.0)
    
    # Feature 3: ADX (0-100 -> 0, 1)
    adx = float(ana.get("adx", 20.0))
    obs[3] = adx / 100.0
    
    # Feature 4: Entry Confidence (0-1)
    obs[4] = float(avg_confidence)
    
    # Features 5-12: Regime one-hot
    regime_names = [
        "STRONG_TREND", "WEAK_TREND", "COMPRESSION",
        "BREAKOUT", "MEAN_REVERSION", "PANIC_SELL",
        "LOW_LIQUIDITY", "PUMP_RISK"
    ]
    raw_regime = str(ana.get("regime", "STRONG_TREND"))
    
    # Map raw regime
    r = raw_regime.upper()
    if "STRONG_TREND" in r:
        mapped = "STRONG_TREND"
    elif "WEAK_TREND" in r:
        mapped = "WEAK_TREND"
    elif "COMPRESSION" in r:
        mapped = "COMPRESSION"
    elif "BREAKOUT" in r:
        mapped = "BREAKOUT"
    elif "MEAN_REVERSION" in r:
        mapped = "MEAN_REVERSION"
    elif "PANIC_SELL" in r:
        mapped = "PANIC_SELL"
    elif "PUMP_RISK" in r:
        mapped = "PUMP_RISK"
    elif "LOW_LIQUIDITY" in r:
        mapped = "LOW_LIQUIDITY"
    elif "RANGING" in r:
        mapped = "MEAN_REVERSION"
    elif "HIGH_VOLATILITY" in r:
        mapped = "PANIC_SELL"
    else:
        mapped = "STRONG_TREND"
        
    regime_idx = regime_names.index(mapped) if mapped in regime_names else 0
    obs[5 + regime_idx] = 1.0
    
    # Feature 13: PnL % (-100, 100 -> -1, 1)
    obs[13] = np.tanh(current_pnl / 5.0)
    
    # Feature 14: Hold time (0, max -> 0, 1) - max_episode_length = 50
    hold_time = min(avg_step, 50)
    obs[14] = hold_time / 50.0
    
    # Feature 15: Fear & Greed (-1 to 1)
    fear_greed = float(ana.get("fear_greed", 50.0))
    obs[15] = (fear_greed - 50.0) / 50.0
    
    # Feature 16: Volume Ratio (0, 10 -> 0, 1)
    vol_ratio = float(ana.get("volume_ratio", 1.0))
    obs[16] = np.tanh(vol_ratio / 5.0)
    
    # Feature 17: BB Width % (0, 10 -> 0, 1)
    bb_width_pct = float(ana.get("bb_width_pct", 2.0))
    obs[17] = np.tanh((bb_width_pct - 2.0) / 2.0)
    
    # Feature 18: Max drawdown since entry (min_pnl)
    obs[18] = np.tanh(min_pnl / 5.0)
    
    # Feature 19: Average market correlation
    obs[19] = average_correlation
    
    return obs



# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def add_position(
    coin: str,
    entry_price: float,
    direction: Literal["LONG", "SHORT"] = "LONG",
    note: str = "",
    invested_usdt: float = 0.0,
    signal_score: dict | None = None,
    confidence: float | None = None,
) -> dict:
    """
    Thêm vị thế mới vào danh sách theo dõi.
    
    Args:
        coin: Tên coin, ví dụ "BTC", "ETH"
        entry_price: Giá vào lệnh
        direction: "LONG" hoặc "SHORT"
        note: Ghi chú tuỳ chọn (lý do vào lệnh)
    
    Returns:
        dict vị thế vừa tạo
    """
    pos = {
        "coin": coin,
        "id": str(uuid.uuid4()),
        "direction": direction.upper(),
        "entry_price": float(entry_price),
        "invested_usdt": float(invested_usdt),
        "entry_signal_score": signal_score or {},
        "entry_confidence": confidence,
        "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "status": "open",
        "note": note,
        "trailing_sl": None,
        "trailing_sl_active": False,
        "last_signal": None,
        "last_price": None,
        "last_checked": None,
    }
    positions_col.insert_one(pos.copy())
    return pos


def get_open_positions() -> list[dict]:
    """Trả về danh sách các vị thế đang mở."""
    try:
        return list(positions_col.find({"status": "open"}, {"_id": 0}))
    except Exception as e:
        print(f"Warning: Lỗi khi lấy danh sách vị thế mở từ MongoDB: {e}")
        return []


def close_position(coin: str, sell_price: float) -> dict:
    """
    Đóng vị thế và tính toán chỉ số hiệu suất.

    Returns dict gồm:
        - pnl_pct: % lãi/lỗ
        - pnl_usd: lãi/lỗ tuyệt đối nếu vốn $1000
        - r_multiplier: bội số R (nếu có SL được set)
        - result: "WIN" | "LOSS" | "BREAKEVEN"
        - hold_hours: thời gian nắm giữ
    """
    coin = coin.upper()
    _LSTM_STATE_CACHE.pop(coin, None)
    save_lstm_cache()

    pos = positions_col.find_one({"coin": coin, "status": "open"}, {"_id": 0})
    if not pos:
        raise ValueError(f"Không tìm thấy vị thế đang mở cho {coin}.")

    entry = pos["entry_price"]
    direction = pos["direction"]

    # Tính P&L
    if direction == "LONG":
        pnl_pct = (sell_price - entry) / entry * 100
    else:  # SHORT
        pnl_pct = (entry - sell_price) / entry * 100

    # Tính R-multiplier nếu có SL đã được set bởi analysis
    r_mult = None
    sl = pos.get("suggested_sl")
    if sl and sl > 0:
        risk_pct = abs(entry - sl) / entry * 100
        if risk_pct > 0:
            r_mult = round(pnl_pct / risk_pct, 2)

    # Tính thời gian nắm giữ
    try:
        entry_dt = datetime.strptime(pos["entry_time"], "%Y-%m-%d %H:%M")
        hold_hours = round((datetime.now() - entry_dt).total_seconds() / 3600, 1)
    except Exception:
        hold_hours = 0.0

    result = "BREAKEVEN"
    if pnl_pct > 0.1:
        result = "WIN"
    elif pnl_pct < -0.1:
        result = "LOSS"

    invested_usdt = pos.get("invested_usdt", 0.0)
    pnl_usd_actual = invested_usdt * (pnl_pct / 100)
    gross_received = invested_usdt + pnl_usd_actual
    fee_usd = (invested_usdt * 0.001) + (gross_received * 0.001)  # Giả sử phí 0.1% mỗi chiều
    received_usdt = gross_received - fee_usd

    closed_data = {
        **pos,
        "sell_price": float(sell_price),
        "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pnl_pct": round(pnl_pct, 4),
        "pnl_usd_per_1000": round(1000 * pnl_pct / 100, 2),
        "pnl_usd_actual": round(pnl_usd_actual, 2),
        "fee_usd": round(fee_usd, 2),
        "received_usdt": round(received_usdt, 2),
        "r_multiplier": r_mult,
        "hold_hours": hold_hours,
        "result": result,
        "status": "closed",
    }

    # Cập nhật trạng thái đóng trong MongoDB
    try:
        positions_col.update_one({"id": pos["id"]}, {"$set": closed_data})
        # Ghi vào log đóng lệnh
        closed_positions_col.insert_one(closed_data.copy())
    except Exception as e:
        print(f"Warning: Lỗi khi lưu trạng thái đóng lệnh vào MongoDB: {e}")

    # Đồng thời lưu một copy giản lược để huấn luyện
    try:
        simple = {
            "coin": closed_data.get("coin"),
            "id": closed_data.get("id"),
            "entry_time": closed_data.get("entry_time"),
            "exit_time": closed_data.get("exit_time"),
            "entry_price": closed_data.get("entry_price"),
            "exit_price": closed_data.get("sell_price"),
            "pnl_pct": closed_data.get("pnl_pct"),
            "result": closed_data.get("result"),
            "hold_hours": closed_data.get("hold_hours"),
            "signal_raw": closed_data.get("last_signal") or closed_data.get("signal"),
            "signal_score": closed_data.get("entry_signal_score") or closed_data.get("signal_score") or {},
            "confidence": closed_data.get("entry_confidence") or closed_data.get("confidence"),
        }
        closed_trades_col.insert_one(simple)
    except Exception:
        pass

    # Ghi log outcomes cho adaptive scoring (không phá lỗi nếu module không có)
    try:
        from btc_scraper.ml_engine.adaptive_scoring import log_trade_outcome
        try:
            log_trade_outcome(closed_data)
        except Exception:
            # Không phá luồng: adaptive logging là bổ sung
            pass
    except Exception:
        pass

    # Sprint 2: Cập nhật actual_result vào shadow log để calibrate Meta Model
    try:
        import sys as _sys
        import os as _os
        _proj_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        if _proj_root not in _sys.path:
            _sys.path.insert(0, _proj_root)
        from scripts.shadow_log import update_outcome as _shadow_update
        _pos_id = closed_data.get("id") or closed_data.get("coin")
        if _pos_id:
            _shadow_update(
                position_id=_pos_id,
                actual_result=closed_data.get("result", "LOSS"),
                actual_pnl_pct=float(closed_data.get("pnl_pct", 0.0)),
            )
    except Exception:
        pass

    return closed_data


def close_partial_position(coin: str, sell_price: float, percentage: float) -> dict:
    """
    Đóng một phần vị thế (theo phần trăm) và tính toán chỉ số hiệu suất cho phần đó.
    Vị thế gốc sẽ được giảm invested_usdt tương ứng.
    """
    coin = coin.upper()
    if percentage <= 0 or percentage >= 100:
        raise ValueError(f"Phần trăm chốt lời phải nằm trong khoảng (0, 100). Giá trị: {percentage}")

    pos = positions_col.find_one({"coin": coin, "status": "open"}, {"_id": 0})
    if not pos:
        raise ValueError(f"Không tìm thấy vị thế đang mở cho {coin}.")

    entry = pos["entry_price"]
    direction = pos["direction"]
    invested_usdt = pos.get("invested_usdt", 0.0)

    if invested_usdt <= 0:
        raise ValueError(f"Vị thế {coin} không có vốn đầu tư (invested_usdt = 0), không thể chốt 1 phần.")

    # Tính P&L phần trăm
    if direction == "LONG":
        pnl_pct = (sell_price - entry) / entry * 100
    else:  # SHORT
        pnl_pct = (entry - sell_price) / entry * 100

    # Lượng vốn đóng
    closed_amount_usdt = invested_usdt * (percentage / 100)
    
    # Tính R-multiplier
    r_mult = None
    sl = pos.get("suggested_sl")
    if sl and sl > 0:
        risk_pct = abs(entry - sl) / entry * 100
        if risk_pct > 0:
            r_mult = round(pnl_pct / risk_pct, 2)

    # Tính thời gian nắm giữ
    try:
        entry_dt = datetime.strptime(pos["entry_time"], "%Y-%m-%d %H:%M")
        hold_hours = round((datetime.now() - entry_dt).total_seconds() / 3600, 1)
    except Exception:
        hold_hours = 0.0

    result = "BREAKEVEN"
    if pnl_pct > 0.1:
        result = "WIN"
    elif pnl_pct < -0.1:
        result = "LOSS"

    pnl_usd_actual = closed_amount_usdt * (pnl_pct / 100)
    gross_received = closed_amount_usdt + pnl_usd_actual
    fee_usd = (closed_amount_usdt * 0.001) + (gross_received * 0.001)
    received_usdt = gross_received - fee_usd

    closed_data = {
        **pos,
        "id": f"{pos['id']}-partial-{int(datetime.now().timestamp())}",
        "parent_id": pos["id"],
        "is_partial": True,
        "sell_price": float(sell_price),
        "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "invested_usdt": round(closed_amount_usdt, 2),
        "closed_percentage": percentage,
        "pnl_pct": round(pnl_pct, 4),
        "pnl_usd_per_1000": round(1000 * pnl_pct / 100, 2),
        "pnl_usd_actual": round(pnl_usd_actual, 2),
        "fee_usd": round(fee_usd, 2),
        "received_usdt": round(received_usdt, 2),
        "r_multiplier": r_mult,
        "hold_hours": hold_hours,
        "result": result,
        "status": "closed",
    }

    # Cập nhật vị thế gốc (giảm vốn)
    remaining_usdt = invested_usdt - closed_amount_usdt
    partial_record = {
        "time": closed_data["exit_time"],
        "percentage": percentage,
        "amount_usdt": round(closed_amount_usdt, 2),
        "sell_price": float(sell_price),
        "pnl_pct": round(pnl_pct, 4),
        "pnl_usd": round(pnl_usd_actual, 2)
    }

    try:
        positions_col.update_one(
            {"id": pos["id"]},
            {
                "$set": {"invested_usdt": remaining_usdt},
                "$push": {"partial_closes": partial_record}
            }
        )
        # Lưu bản ghi đóng lệnh 1 phần vào collections
        closed_positions_col.insert_one(closed_data.copy())
        
        simple = {
            "coin": closed_data.get("coin"),
            "id": closed_data.get("id"),
            "parent_id": pos["id"],
            "is_partial": True,
            "entry_time": closed_data.get("entry_time"),
            "exit_time": closed_data.get("exit_time"),
            "entry_price": closed_data.get("entry_price"),
            "exit_price": closed_data.get("sell_price"),
            "pnl_pct": closed_data.get("pnl_pct"),
            "result": closed_data.get("result"),
            "hold_hours": closed_data.get("hold_hours"),
            "signal_raw": closed_data.get("last_signal") or closed_data.get("signal"),
            "signal_score": closed_data.get("entry_signal_score") or closed_data.get("signal_score") or {},
            "confidence": closed_data.get("entry_confidence") or closed_data.get("confidence"),
        }
        closed_trades_col.insert_one(simple)
    except Exception as e:
        print(f"Warning: Lỗi khi lưu trạng thái đóng 1 phần vào MongoDB: {e}")

    return closed_data


def evaluate_positions(analysis_results: dict[str, dict]) -> list[dict]:
    """
    Kiểm tra tất cả vị thế đang mở so với kết quả phân tích hiện tại.
    Trả về list các dict khuyến nghị để gửi lên Telegram.
    
    Args:
        analysis_results: dict dạng {"BTC:Binance": {analysis...}, ...}
    
    Returns:
        list[dict] mỗi phần tử gồm:
            coin, direction, entry_price, current_price,
            pnl_pct, signal, recommendation, sl, tp1, tp2, status_icon
    """
    positions = get_open_positions()
    if not positions:
        return []

    # Build lookup: coin → analysis data (lấy từ Binance)
    coin_analysis: dict[str, dict] = {}
    for key, ana in analysis_results.items():
        coin, _ = key.split(":")
        coin_analysis[coin.upper()] = ana

    recommendations = []

    # Group positions by coin to support multiple entries per same coin
    by_coin: dict[str, list[dict]] = {}
    for p in positions:
        by_coin.setdefault(p["coin"], []).append(p)

    for coin, pos_list in by_coin.items():
        ana = coin_analysis.get(coin)
        if not ana:
            continue

        current_price = ana.get("close", 0.0)
        if current_price <= 0:
            continue

        # Aggregate invested and compute weighted average entry if possible
        total_invested = sum(float(p.get("invested_usdt", 0.0)) for p in pos_list)
        if total_invested > 0:
            weighted_entry = sum(float(p.get("entry_price", 0.0)) * float(p.get("invested_usdt", 0.0)) for p in pos_list) / total_invested
        else:
            weighted_entry = sum(float(p.get("entry_price", 0.0)) for p in pos_list) / len(pos_list)

        # Assume direction is the same for grouped positions (LONG/SHORT)
        direction = pos_list[0].get("direction", "LONG")
        from btc_scraper.ml_engine.signal_score import extract_signal_fields
        sig_fields = extract_signal_fields(ana)
        signal = ana.get("signal", sig_fields.get("raw", "NEUTRAL"))

        # Recalculate SL/TP based on weighted entry
        force_signal = "BUY" if direction == "LONG" else "SELL"
        pos_tp_sl = calculate_tp_sl(
            close=weighted_entry,
            signal=force_signal,
            atr=ana.get("atr", 0.0),
            support=ana.get("support", 0.0),
            resistance=ana.get("resistance", 0.0),
            bb_upper=ana.get("bb_upper", 0.0),
            bb_middle=ana.get("bb_middle", 0.0),
            bb_lower=ana.get("bb_lower", 0.0),
        )

        sl = pos_tp_sl.get("sl", 0.0)
        tp1 = pos_tp_sl.get("tp1", 0.0)
        tp2 = pos_tp_sl.get("tp2", 0.0)
        rr1 = pos_tp_sl.get("rr1", 0.0)

        # Compute aggregated P&L using weighted_entry
        if direction == "LONG":
            pnl_pct = (current_price - weighted_entry) / weighted_entry * 100
        else:
            pnl_pct = (weighted_entry - current_price) / weighted_entry * 100

        # Calculate average parameters for RL observation
        conf_list = [p.get("entry_confidence") or p.get("entry_signal_score", {}).get("meta_confidence") or 0.5 for p in pos_list]
        avg_confidence = float(sum(float(c) for c in conf_list) / len(conf_list))
        
        steps_list = []
        for p in pos_list:
            try:
                entry_dt = datetime.strptime(p["entry_time"], "%Y-%m-%d %H:%M")
                elapsed_minutes = (datetime.now() - entry_dt).total_seconds() / 60
                steps_list.append(int(elapsed_minutes / 15))
            except Exception:
                steps_list.append(0)
        avg_step = int(sum(steps_list) / len(steps_list))

        # Track and update min_pnl for each position
        min_pnl_list = []
        for p in pos_list:
            p_entry = float(p.get("entry_price", 0.0))
            if p_entry > 0:
                p_pnl = ((current_price - p_entry) / p_entry * 100) if direction == "LONG" else ((p_entry - current_price) / p_entry * 100)
            else:
                p_pnl = 0.0
            p_min_pnl = p.get("min_pnl")
            if p_min_pnl is None:
                p_min_pnl = p_pnl
            else:
                p_min_pnl = min(float(p_min_pnl), p_pnl)
            
            # Update min_pnl in database
            positions_col.update_one({"id": p["id"]}, {"$set": {"min_pnl": p_min_pnl}})
            p["min_pnl"] = p_min_pnl
            min_pnl_list.append(p_min_pnl)
            
        avg_min_pnl = sum(min_pnl_list) / len(min_pnl_list) if min_pnl_list else 0.0

        # Compute average correlation with the rest of whitelist assets
        from btc_scraper.analysis.correlation import correlation_engine, SECTOR_MAP
        target = coin.upper()
        corrs = []
        for other_coin in SECTOR_MAP.keys():
            if other_coin != target:
                corr_val = correlation_engine.get_correlation(target, other_coin)
                corrs.append(corr_val)
        avg_correlation = float(np.mean(corrs)) if corrs else 0.5

        # Predict success probability of the position using Meta Model
        pos_meta_prob = None
        try:
            from btc_scraper.ml_engine.meta_model import predict_meta_confidence
            eval_info = dict(ana)
            if direction == "LONG":
                eval_info["signal"] = "BUY"
                eval_info["signal_score"] = {
                    "action": "BUY",
                    "score": 70,
                    "confidence": "MEDIUM"
                }
            else:
                eval_info["signal"] = "SELL"
                eval_info["signal_score"] = {
                    "action": "SELL",
                    "score": 30,
                    "confidence": "MEDIUM"
                }
            res = predict_meta_confidence(eval_info)
            if res and res.get("probability") is not None:
                pos_meta_prob = float(res["probability"])
        except Exception:
            pos_meta_prob = None

        # Fetch PPO model and predict
        rl_action = None
        model = get_ppo_model()
        if model is not None:
            try:
                obs = _build_rl_observation(ana, avg_confidence, avg_step, weighted_entry, pnl_pct, direction, avg_min_pnl, avg_correlation)
                
                # Retrieve cached LSTM states for this coin
                lstm_cache_key = coin.upper()
                if lstm_cache_key not in _LSTM_STATE_CACHE:
                    lstm_states = None
                    episode_start = np.ones((1,), dtype=bool)
                else:
                    lstm_states, episode_start = _LSTM_STATE_CACHE[lstm_cache_key]

                rl_action_pred, next_lstm_states = model.predict(
                    obs,
                    state=lstm_states,
                    episode_start=episode_start,
                    deterministic=True
                )
                rl_action = int(rl_action_pred)
                
                # Confidence Gate: only execute PARTIAL_CLOSE (1), TAKE_PROFIT (3), or EXIT (4) if pos_meta_prob is None or < 0.45.
                # Otherwise, override to HOLD (0).
                if rl_action in [1, 3, 4] and pos_meta_prob is not None and pos_meta_prob >= 0.45:
                    print(f"[Confidence Gate] Override RL Action {rl_action} to 0 (HOLD) for {coin} because meta confidence {pos_meta_prob:.4f} >= 0.45")
                    rl_action = 0

                # Cache the updated LSTM hidden state
                _LSTM_STATE_CACHE[lstm_cache_key] = (next_lstm_states, np.zeros((1,), dtype=bool))
                save_lstm_cache()
                print(f"[RL Exit Agent] Coin {coin}: Predicted Action {rl_action}")
            except Exception as ex:
                print(f"[RL Exit Agent] Warning: Error predicting action for {coin}: {ex}")

        # Update trailing SL for each position individually
        atr = float(ana.get("atr", 0.0))
        is_any_trailing_active = any(p.get("trailing_sl_active", False) for p in pos_list) or (rl_action == 5)
        for p in pos_list:
            pos_id = p["id"]
            p_tp_sl = calculate_tp_sl(
                close=p["entry_price"],
                signal=force_signal,
                atr=atr,
                support=ana.get("support", 0.0),
                resistance=ana.get("resistance", 0.0),
                bb_upper=ana.get("bb_upper", 0.0),
                bb_middle=ana.get("bb_middle", 0.0),
                bb_lower=ana.get("bb_lower", 0.0),
            )
            initial_sl = p_tp_sl.get("sl", p["entry_price"] * 0.98 if direction == "LONG" else p["entry_price"] * 1.02)
            
            curr_trailing_sl = p.get("trailing_sl")
            
            if rl_action == 2:
                # Move to breakeven
                curr_trailing_sl = p["entry_price"]
            elif is_any_trailing_active and atr > 0:
                if curr_trailing_sl is None:
                    curr_trailing_sl = initial_sl
                if direction == "LONG":
                    candidate_sl = current_price - 1.5 * atr
                    curr_trailing_sl = max(curr_trailing_sl, candidate_sl)
                else:
                    candidate_sl = current_price + 1.5 * atr
                    curr_trailing_sl = min(curr_trailing_sl, candidate_sl)
            
            try:
                positions_col.update_one(
                    {"id": pos_id, "status": "open"},
                    {"$set": {
                        "trailing_sl": curr_trailing_sl,
                        "trailing_sl_active": is_any_trailing_active
                    }}
                )
            except Exception as e:
                print(f"Warning: Lỗi khi cập nhật trailing_sl cho position {pos_id} trên MongoDB: {e}")
            p["trailing_sl"] = curr_trailing_sl
            p["trailing_sl_active"] = is_any_trailing_active
            
        # Calculate weighted average trailing SL
        grouped_trailing_sls = [p.get("trailing_sl") for p in pos_list if p.get("trailing_sl") is not None]
        if grouped_trailing_sls:
            if total_invested > 0:
                avg_trailing_sl = sum(float(p.get("trailing_sl", 0.0)) * float(p.get("invested_usdt", 0.0)) for p in pos_list) / total_invested
            else:
                avg_trailing_sl = sum(float(p.get("trailing_sl", 0.0)) for p in pos_list) / len(pos_list)
        else:
            avg_trailing_sl = sl

        # Aggregate invested_usdt and expected received
        invested_usdt = total_invested
        pnl_usd_actual = invested_usdt * (pnl_pct / 100)
        gross_received = invested_usdt + pnl_usd_actual
        fee_usd = (invested_usdt * 0.001) + (gross_received * 0.001) if invested_usdt > 0 else 0.0
        expected_received_usdt = gross_received - fee_usd if invested_usdt > 0 else 0.0

        # Read shadow mode from env variable
        shadow_mode = os.getenv("RL_EXIT_SHADOW_MODE", "false").lower() == "true"

        if shadow_mode and rl_action is not None:
            _log_rl_shadow_prediction(
                coin,
                rl_action,
                pos_meta_prob,
                position_id=pos_list[0].get("id"),
            )

        # Xác định khuyến nghị dựa trên entry trung bình và trailing SL
        rec = _generate_recommendation(
            direction=direction,
            entry=weighted_entry,
            current_price=current_price,
            pnl_pct=pnl_pct,
            signal=signal,
            sl=avg_trailing_sl,
            tp1=tp1,
            tp2=tp2,
            rl_action=rl_action,
            shadow_mode=shadow_mode,
        )

        dca_opp = _evaluate_dca_opportunity(pos_list, ana, current_price, pos_meta_prob, rl_action=rl_action)

        # Cập nhật last_signal và last_price cho mọi vị thế của coin
        try:
            positions_col.update_many(
                {"coin": coin, "status": "open"},
                {"$set": {
                    "last_signal": signal,
                    "last_price": current_price,
                    "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "last_signal_score": ana.get("signal_score", {}),
                    "suggested_sl": avg_trailing_sl,
                    "suggested_tp1": tp1,
                    "suggested_tp2": tp2,
                    "live_meta_confidence": pos_meta_prob,
                    "dca_opportunity": dca_opp,
                }}
            )
        except Exception as e:
            print(f"Warning: Lỗi khi cập nhật vị thế cho {coin} trên MongoDB: {e}")

        recommendations.append({
            "coin": coin,
            "direction": direction,
            "positions_count": len(pos_list),
            "avg_entry_price": round(weighted_entry, 6),
            "entry_price": round(weighted_entry, 6),
            "current_price": current_price,
            "pnl_pct": round(pnl_pct, 3),
            "invested_usdt": invested_usdt,
            "expected_received_usdt": round(expected_received_usdt, 2),
            "fee_usd": round(fee_usd, 2),
            "signal": signal,
            "suggested_position_size": ana.get("signal_score", {}).get("position_size") or ana.get("position_size"),
            "recommendation": rec["action"],
            "recommendation_reason": rec["reason"],
            "urgency": rec["urgency"],
            "sl": avg_trailing_sl,
            "tp1": tp1,
            "tp2": tp2,
            "rr1": rr1,
            "live_meta_confidence": pos_meta_prob,
            "shadow_mode": shadow_mode,
            "dca_opportunity": dca_opp,
        })

    return recommendations


def _evaluate_dca_opportunity(
    pos_list: list[dict],
    ana: dict,
    current_price: float,
    sim_meta_prob: float | None,
    rl_action: int | None = None,
) -> dict | None:
    """
    Evaluate DCA opportunity for a grouped coin position.

    rl_action:
        0=HOLD, 1=PARTIAL_CLOSE_50, 2=MOVE_SL_TO_BE,
        3=TAKE_PROFIT, 4=EXIT, 5=TRAILING_SL_ATR
    DCA is blocked when rl_action is 1 (PARTIAL_CLOSE), 3 (TAKE_PROFIT), or 4 (EXIT).
    DCA size is scaled by Meta Model confidence:
        - sim_meta_prob >= 0.75 -> 1.5x initial_invested
        - 0.65 <= sim_meta_prob < 0.75 -> 1.0x initial_invested
    """
    if not pos_list or not ana or current_price <= 0:
        return None

    # Block DCA unless RL recommends TRAILING_SL_ATR (5) or is not loaded (None).
    # If RL agent recommends HOLD (0), PARTIAL CLOSE (1), MOVE TO BE (2), TAKE PROFIT (3), or EXIT (4), do not DCA.
    if rl_action is not None and rl_action != 5:
        return None

    direction = pos_list[0].get("direction", "LONG").upper()
    
    # Rule 1: Limit max DCA actions (total entries < 3)
    if len(pos_list) >= 3:
        return None

    # Calculate weighted entry
    total_invested = sum(float(p.get("invested_usdt", 0.0)) for p in pos_list)
    if total_invested > 0:
        weighted_entry = sum(float(p.get("entry_price", 0.0)) * float(p.get("invested_usdt", 0.0)) for p in pos_list) / total_invested
    else:
        weighted_entry = sum(float(p.get("entry_price", 0.0)) for p in pos_list) / len(pos_list)

    # Rule 2: Volatility / Price Distance check
    atr = float(ana.get("atr", 0.0))
    price_diff_pct = abs(current_price - weighted_entry) / weighted_entry * 100
    
    # Volatility distance threshold = 1.5 * ATR% or minimum 1.5%
    atr_pct = (atr / current_price * 100) if current_price > 0 else 0.0
    min_distance = max(1.5, atr_pct * 1.5)
    
    # LONG: current price must be below entry; SHORT: current price must be above entry
    is_in_loss = (direction == "LONG" and current_price < weighted_entry) or (direction == "SHORT" and current_price > weighted_entry)
    
    if not is_in_loss or price_diff_pct < min_distance:
        return None

    # Rule 3: Model confidence check (sim_meta_prob >= 65%)
    if sim_meta_prob is None or sim_meta_prob < 0.65:
        return None

    # Rule 4: S/R Zone check (within 1% of S/R boundary)
    # Skip S/R zone check if S/R value is missing or <= 0
    if direction == "LONG":
        support = float(ana.get("support", 0.0))
        if support > 0:
            is_near_support = (current_price >= support * 0.99) and (current_price <= support * 1.01)
            if not is_near_support:
                return None
    else:
        resistance = float(ana.get("resistance", 0.0))
        if resistance > 0:
            is_near_resistance = (current_price >= resistance * 0.99) and (current_price <= resistance * 1.01)
            if not is_near_resistance:
                return None

    # Dynamic DCA sizing based on Meta Model confidence
    initial_invested = float(pos_list[0].get("invested_usdt", 0.0))
    base_size = initial_invested if initial_invested > 0 else 100.0

    if sim_meta_prob >= 0.75:
        # High confidence: scale up DCA by 1.5x
        suggested_dca_size = base_size * 1.5
        confidence_label = "HIGH"
    else:
        # Medium confidence (0.65–0.75): standard DCA size
        suggested_dca_size = base_size * 1.0
        confidence_label = "MEDIUM"

    # Calculate new average entry price after DCA
    new_avg_entry = (total_invested * weighted_entry + suggested_dca_size * current_price) / (total_invested + suggested_dca_size)

    return {
        "suggested_dca_size": round(suggested_dca_size, 2),
        "new_avg_entry": round(new_avg_entry, 6),
        "sim_meta_prob": round(sim_meta_prob, 4),
        "confidence_label": confidence_label,
        "rl_action_at_eval": rl_action,
    }


def _generate_recommendation(
    direction: str,
    entry: float,
    current_price: float,
    pnl_pct: float,
    signal: str,
    sl: float,
    tp1: float,
    tp2: float,
    rl_action: int | None = None,
    shadow_mode: bool = False,
) -> dict:
    """
    Logic nội bộ tạo khuyến nghị dựa trên vị thế và tín hiệu thị trường.

    rl_action (optional):
        0=HOLD, 1=PARTIAL_CLOSE_50, 2=MOVE_SL_TO_BREAKEVEN,
        3=TAKE_PROFIT, 4=EXIT, 5=TRAILING_SL_ATR
    RL actions take priority over rule-based signals EXCEPT hard SL/TP hits.
    """
    # --- Hard price-based rules always take priority ---
    # SL bị chạm
    if direction == "LONG" and sl > 0 and current_price <= sl:
        return {"action": "[!] CAT LO NGAY", "reason": f"Gia da cham/xuyen SL {sl}", "urgency": "HIGH"}
    if direction == "SHORT" and sl > 0 and current_price >= sl:
        return {"action": "[!] CAT LO NGAY", "reason": f"Gia da cham/xuyen SL {sl}", "urgency": "HIGH"}

    # TP đã chạm
    if direction == "LONG":
        if tp2 > 0 and current_price >= tp2:
            return {"action": "[TP2] CHOT LOI TP2", "reason": f"Gia dat TP2 {tp2} -- da du lai!", "urgency": "HIGH"}
        if tp1 > 0 and current_price >= tp1:
            return {"action": "[TP1] Xem xet CHOT TP1", "reason": f"Gia cham TP1 {tp1} (lai {pnl_pct:+.2f}%) -- can nhac chot 50%", "urgency": "MEDIUM"}
    if direction == "SHORT":
        if tp2 > 0 and current_price <= tp2:
            return {"action": "[TP2] CHOT LOI TP2", "reason": f"Gia dat TP2 {tp2} -- da du lai!", "urgency": "HIGH"}
        if tp1 > 0 and current_price <= tp1:
            return {"action": "[TP1] Xem xet CHOT TP1", "reason": f"Gia cham TP1 {tp1} (lai {pnl_pct:+.2f}%) -- can nhac chot 50%", "urgency": "MEDIUM"}

    # --- RL Agent recommendations (after price rules) ---
    RL_ACTION_LABELS = {
        0: None,   # HOLD -> fall through to rule-based
        1: ("[RL] CHOT LOI 50% (RL Partial Close)", "RL agent khuyen chot 50% vi the", "MEDIUM"),
        2: ("[RL] DOI SL VE ENTRY (RL Move-to-BE)", "RL agent khuyen doi SL ve entry (breakeven)", "MEDIUM"),
        3: ("[RL] CHOT LOI FULL (RL Take Profit)", "RL agent khuyen chot loi toan bo", "HIGH"),
        4: ("[RL] DONG VI THE (RL Exit)", "RL agent khuyen dong vi the de bao toan von", "HIGH"),
        5: ("[RL] TRAILING SL ATR (RL Trailing SL)", "RL agent kich hoat trailing SL theo ATR", "LOW"),
    }
    if rl_action is not None and rl_action in RL_ACTION_LABELS:
        rl_label = RL_ACTION_LABELS[rl_action]
        if rl_label is not None:  # action 0 (HOLD) falls through
            action_name = rl_label[0]
            if shadow_mode:
                action_name = action_name.replace("[RL]", "[SHADOW-RL]")
            return {"action": action_name, "reason": rl_label[1], "urgency": rl_label[2]}

    # --- Tín hiệu đảo chiều mạnh ngược chiều vị thế ---
    if direction == "LONG" and any(x in signal for x in ["STRONG SELL", "SELL (Crossover)", "SELL (Break-SMA50)", "SELL (SFP"]):
        action = "[!] XEM XET DONG LENH" if pnl_pct > 0 else "[!] CAN NHAC CAT LO"
        return {"action": action, "reason": f"Xuat hien tin hieu dao chieu: {signal}", "urgency": "MEDIUM"}
    if direction == "SHORT" and any(x in signal for x in ["STRONG BUY", "BUY (Crossover)", "BUY (SFP"]):
        action = "[!] XEM XET DONG LENH" if pnl_pct > 0 else "[!] CAN NHAC CAT LO"
        return {"action": action, "reason": f"Xuat hien tin hieu dao chieu: {signal}", "urgency": "MEDIUM"}

    # Đang lỗ nặng (> 3%)
    if pnl_pct < -3.0:
        return {"action": "[WARN] CANH BAO LO", "reason": f"Dang lo {pnl_pct:.2f}% -- xem xet lai ke hoach", "urgency": "MEDIUM"}

    # Bình thường — giữ lệnh
    trend_note = ""
    if direction == "LONG" and "BULLISH" in signal:
        trend_note = " -- xu huong dang ho tro vi the"
    elif direction == "SHORT" and "BEARISH" in signal:
        trend_note = " -- xu huong dang ho tro vi the"

    return {
        "action": f"[HOLD] GIU LENH ({pnl_pct:+.2f}%)",
        "reason": f"Chua cham TP/SL{trend_note}. Tin hieu: {signal}",
        "urgency": "LOW",
    }


def get_performance_summary(trade_type: str = "ALL") -> dict:
    """
    Tổng hợp hiệu suất từ các lệnh đã đóng.
    trade_type: "ALL" | "AUTO" | "MANUAL"
    """
    closed = list(closed_positions_col.find({}, {"_id": 0}))
    if not closed:
        return {"message": "Chưa có lệnh nào được đóng."}

    if trade_type == "AUTO":
        closed = [t for t in closed if "[AUTO-" in t.get("note", "")]
    elif trade_type == "MANUAL":
        closed = [t for t in closed if "[AUTO-" not in t.get("note", "")]

    if not closed:
        return {"message": f"Chưa có lệnh {trade_type} nào được đóng."}

    total = len(closed)
    wins = [t for t in closed if t.get("result") == "WIN"]
    losses = [t for t in closed if t.get("result") == "LOSS"]

    win_rate = len(wins) / total * 100 if total > 0 else 0
    avg_win = sum(t.get("pnl_pct", 0.0) for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.get("pnl_pct", 0.0) for t in losses) / len(losses) if losses else 0
    total_pnl = sum(t.get("pnl_pct", 0.0) for t in closed)

    profit_factor = (
        abs(sum(t.get("pnl_pct", 0.0) for t in wins)) / abs(sum(t.get("pnl_pct", 0.0) for t in losses))
        if losses and sum(t.get("pnl_pct", 0.0) for t in losses) != 0
        else None
    )

    r_values = [t["r_multiplier"] for t in closed if t.get("r_multiplier") is not None]
    avg_r = sum(r_values) / len(r_values) if r_values else None
    
    total_pnl_usd_actual = sum(t.get("pnl_usd_actual", 0.0) for t in closed)

    # Tính max consecutive losses
    consec = max_consec = 0
    for t in closed:
        if t.get("result") == "LOSS":
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    return {
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 2),
        "avg_win_pct": round(avg_win, 3),
        "avg_loss_pct": round(avg_loss, 3),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "avg_r_multiplier": round(avg_r, 2) if avg_r is not None else None,
        "total_pnl_pct": round(total_pnl, 3),
        "pnl_per_1000_usd": round(total_pnl * 10, 2),
        "total_pnl_usd_actual": round(total_pnl_usd_actual, 2),
        "max_consecutive_losses": max_consec,
    }
