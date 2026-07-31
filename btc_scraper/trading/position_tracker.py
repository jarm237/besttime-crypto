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

try:
    import torch
except Exception as exc:  # pragma: no cover - environment dependent
    torch = None
    TORCH_IMPORT_ERROR = exc
else:
    TORCH_IMPORT_ERROR = None

from btc_scraper.analysis import calculate_tp_sl
from btc_scraper.core.db import positions_col, closed_positions_col, closed_trades_col
from btc_scraper.core.paths import build_logs_path, runtime_paper_run_id
from btc_scraper.regime.config import compute_regime_config_sha256, load_runtime_regime_config
from btc_scraper.regime.contract import coerce_regime_snapshot
from btc_scraper.regime.contract import model_regime_bucket

TRADE_ORIGIN_PAPER = "paper_mode"
TRADE_ORIGIN_MANUAL = "manual"
TRADE_ORIGIN_TEST = "test_function"
TRADE_ORIGIN_LIVE = "live"

ORDER_CREATOR_SYSTEM = "system"
ORDER_CREATOR_USER = "user"
ORDER_CREATOR_TEST = "test"

ORDER_CHANNEL_PAPER_RUNNER = "paper_runner"
ORDER_CHANNEL_LIVE_RUNNER = "live_runner"
ORDER_CHANNEL_TELEGRAM = "telegram"
ORDER_CHANNEL_UI = "ui"
ORDER_CHANNEL_CLI = "cli"
ORDER_CHANNEL_MANUAL = "manual"
ORDER_CHANNEL_TEST = "test"
ORDER_CHANNEL_UNKNOWN = "unknown"
_ORDER_CREATORS = {
    ORDER_CREATOR_SYSTEM,
    ORDER_CREATOR_USER,
    ORDER_CREATOR_TEST,
}
_ORDER_CHANNELS = {
    ORDER_CHANNEL_PAPER_RUNNER,
    ORDER_CHANNEL_LIVE_RUNNER,
    ORDER_CHANNEL_TELEGRAM,
    ORDER_CHANNEL_UI,
    ORDER_CHANNEL_CLI,
    ORDER_CHANNEL_MANUAL,
    ORDER_CHANNEL_TEST,
    ORDER_CHANNEL_UNKNOWN,
}

# This answers a separate question from trade_origin: a human can place a
# manual order because the system produced a signal, or independently.
MANUAL_DECISION_SYSTEM_SIGNAL = "system_signal"
MANUAL_DECISION_PERSONAL = "personal_discretion"
MANUAL_DECISION_UNKNOWN = "unknown"
_MANUAL_DECISION_BASES = {
    MANUAL_DECISION_SYSTEM_SIGNAL,
    MANUAL_DECISION_PERSONAL,
    MANUAL_DECISION_UNKNOWN,
}


def _resolve_manual_decision_basis(
    trade_origin: str,
    manual_decision_basis: str | None,
) -> str | None:
    """Normalize why a person created a manual position."""
    if trade_origin != TRADE_ORIGIN_MANUAL:
        return None
    basis = (manual_decision_basis or MANUAL_DECISION_PERSONAL).strip().lower()
    if basis not in _MANUAL_DECISION_BASES:
        allowed = ", ".join(sorted(_MANUAL_DECISION_BASES))
        raise ValueError(f"manual_decision_basis must be one of: {allowed}")
    return basis


def _is_running_under_pytest() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST"))


def _infer_trade_origin(
    note: str = "",
    execution_mode: str | None = None,
    trade_origin: str | None = None,
) -> str:
    """Return stable provenance for manual, paper, live and test-created positions."""
    if trade_origin:
        return str(trade_origin)
    if _is_running_under_pytest():
        return TRADE_ORIGIN_TEST

    mode = (execution_mode or "").strip().lower()
    if mode == "paper":
        return TRADE_ORIGIN_PAPER
    if mode == "test":
        return TRADE_ORIGIN_TEST
    if mode == "live":
        return TRADE_ORIGIN_LIVE

    note_upper = (note or "").upper()
    if "[AUTO-DRY_RUN]" in note_upper or "[PAPER]" in note_upper:
        return TRADE_ORIGIN_PAPER
    if "[AUTO-TEST]" in note_upper or "[TEST]" in note_upper:
        return TRADE_ORIGIN_TEST
    if "[AUTO-TESTNET]" in note_upper or "[AUTO-LIVE]" in note_upper:
        return TRADE_ORIGIN_LIVE
    return TRADE_ORIGIN_MANUAL


def _default_execution_mode_for_origin(origin: str, execution_mode: str | None = None) -> str:
    if execution_mode:
        return str(execution_mode)
    if origin == TRADE_ORIGIN_PAPER:
        return "paper"
    if origin == TRADE_ORIGIN_TEST:
        return "test"
    if origin == TRADE_ORIGIN_LIVE:
        return "live"
    return "manual"


def _infer_order_channel(created_by: str | None) -> str:
    source = (created_by or "").strip().lower()
    if "telegram" in source or source in {"tele", "tg"}:
        return ORDER_CHANNEL_TELEGRAM
    if "ui" in source or "web" in source or "dashboard" in source:
        return ORDER_CHANNEL_UI
    if "cli" in source or "manage_positions" in source:
        return ORDER_CHANNEL_CLI
    if "pytest" in source or "test" in source:
        return ORDER_CHANNEL_TEST
    if source:
        return ORDER_CHANNEL_MANUAL
    return ORDER_CHANNEL_UNKNOWN


def _resolve_order_provenance(
    trade_origin: str,
    execution_mode: str,
    created_by: str | None,
    order_creator: str | None = None,
    order_channel: str | None = None,
) -> tuple[str, str]:
    """Normalize who created an order and through which surface."""
    if order_creator:
        resolved_creator = str(order_creator).strip().lower()
    elif trade_origin in {TRADE_ORIGIN_PAPER, TRADE_ORIGIN_LIVE}:
        resolved_creator = ORDER_CREATOR_SYSTEM
    elif trade_origin == TRADE_ORIGIN_TEST:
        resolved_creator = ORDER_CREATOR_TEST
    else:
        resolved_creator = ORDER_CREATOR_USER
    if resolved_creator not in _ORDER_CREATORS:
        allowed = ", ".join(sorted(_ORDER_CREATORS))
        raise ValueError(f"order_creator must be one of: {allowed}")

    if order_channel:
        resolved_channel = str(order_channel).strip().lower()
    elif trade_origin == TRADE_ORIGIN_PAPER or execution_mode == "paper":
        resolved_channel = ORDER_CHANNEL_PAPER_RUNNER
    elif trade_origin == TRADE_ORIGIN_LIVE or execution_mode == "live":
        resolved_channel = ORDER_CHANNEL_LIVE_RUNNER
    elif trade_origin == TRADE_ORIGIN_TEST:
        resolved_channel = ORDER_CHANNEL_TEST
    else:
        resolved_channel = _infer_order_channel(created_by)
    if resolved_channel not in _ORDER_CHANNELS:
        allowed = ", ".join(sorted(_ORDER_CHANNELS))
        raise ValueError(f"order_channel must be one of: {allowed}")
    return resolved_creator, resolved_channel


def format_order_provenance(position: dict) -> str:
    """Human-readable provenance label for Telegram/CLI surfaces."""
    origin = position.get("trade_origin")
    execution_mode = position.get("execution_mode") or _default_execution_mode_for_origin(origin or TRADE_ORIGIN_MANUAL)
    try:
        creator, channel = _resolve_order_provenance(
            trade_origin=origin or TRADE_ORIGIN_MANUAL,
            execution_mode=str(execution_mode),
            created_by=position.get("created_by"),
            order_creator=position.get("order_creator"),
            order_channel=position.get("order_channel"),
        )
    except ValueError:
        creator = ORDER_CREATOR_USER if origin == TRADE_ORIGIN_MANUAL else None
        channel = _infer_order_channel(position.get("created_by"))
    if position.get("is_system_paper_order") or origin == TRADE_ORIGIN_PAPER:
        return "System paper mode"
    if creator == ORDER_CREATOR_USER:
        if channel == ORDER_CHANNEL_TELEGRAM:
            return "User via Telegram"
        if channel == ORDER_CHANNEL_UI:
            return "User via UI"
        if channel == ORDER_CHANNEL_CLI:
            return "User via CLI"
        return "User manual"
    if origin == TRADE_ORIGIN_LIVE:
        return "System live"
    if origin == TRADE_ORIGIN_TEST:
        return "Test"
    return "Unknown"

# Cache PPO model globally to avoid reloading on every cycle
_PPO_MODEL_CACHE = None
_LAST_MODEL_PATH = None
_LSTM_STATE_CACHE = {}

_LSTM_CACHE_FILE = str(build_logs_path("rl_lstm_cache.pkl"))

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
            from btc_scraper.ml_engine.governed_artifact_loader import load_trusted_pickle
            _LSTM_STATE_CACHE = load_trusted_pickle(_LSTM_CACHE_FILE)
            print(f"[RL Exit Agent] Restored LSTM state cache from {_LSTM_CACHE_FILE} (found {len(_LSTM_STATE_CACHE)} keys)")
        except Exception as e:
            print(f"[RL Exit Agent] Warning: Không thể khôi phục LSTM cache: {e}")
            _LSTM_STATE_CACHE = {}
    else:
        _LSTM_STATE_CACHE = {}

# Khôi phục cache ngay khi load module
load_lstm_cache()


def _get_default_device() -> str:
    if torch is None:
        return "cpu"
    try:
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _legacy_latest_ppo_model() -> str | None:
    """Tìm file zip model PPO mới nhất."""
    rl_dir = build_logs_path("rl_models")
    if not rl_dir.exists():
        return None
    matches = sorted(rl_dir.glob("rl_exit_ppo_*.zip"))
    if matches:
        return str(matches[-1])
    matches_simple = sorted(rl_dir.glob("rl_exit_ppo.zip"))
    if matches_simple:
        return str(matches_simple[-1])
    return None

def load_latest_ppo_model() -> str | None:
    """Resolve only the configured canonical PPO artifact; never glob by name."""
    try:
        from btc_scraper.ml_engine.artifact_resolver import get_artifact_resolver
        from btc_scraper.ml_engine.model_registry import ModelRegistry
        result = get_artifact_resolver().resolve("rl_exit", require_metadata=True)
        permitted = result.path is not None and ModelRegistry().permits_artifact("rl_exit", result.path, result.sha256, ("production", "shadow"))
        return str(result.path) if result.healthy and permitted and result.status in {"production", "shadow"} else None
    except Exception:
        return None


def get_ppo_model(device: str = "auto"):
    """Tải model PPO động và cache."""
    global _PPO_MODEL_CACHE, _LAST_MODEL_PATH
    if _PPO_MODEL_CACHE is None:
        try:
            from sb3_contrib import RecurrentPPO
            from btc_scraper.ml_engine.governed_artifact_loader import get_governed_artifact_loader
            from btc_scraper.trading.rl_action_guard import rl_exit_allows_shadow_artifact
            if device == "auto":
                device = _get_default_device()
            elif device == "cuda" and not torch.cuda.is_available():
                print("[RL Exit Agent] CUDA requested but not available. Falling back to CPU.")
                device = "cpu"
            allowed = ("production", "shadow") if rl_exit_allows_shadow_artifact() else ("production",)
            loaded = get_governed_artifact_loader().load_production(
                "rl_exit", "rl-exit-obs-v2", allowed_statuses=allowed,
                model_class=RecurrentPPO, device=device,
            )
            _PPO_MODEL_CACHE = loaded.model
            _LAST_MODEL_PATH = str(loaded.path)
            print(f"[RL Exit Agent] Loaded governed RecurrentPPO model: {loaded.artifact_id} on device={device}")
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
    
    mapped = model_regime_bucket(raw_regime)
        
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
    
    from btc_scraper.ml_engine.schema_validator import RLExitObservationV2
    contract = RLExitObservationV2(tuple(float(v) for v in obs))
    contract.validate()
    return np.asarray(contract.as_list(), dtype=np.float32)



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
    trade_origin: str | None = None,
    execution_mode: str | None = None,
    fill_source: str | None = None,
    paper_run_id: str | None = None,
    cycle_id: str | None = None,
    created_by: str | None = None,
    source_test_name: str | None = None,
    prediction_id: str | None = None,
    signal_id: str | None = None,
    entry_decision_id: str | None = None,
    reservation_id: str | None = None,
    idempotency_key: str | None = None,
    client_order_id: str | None = None,
    exchange_order_id: str | None = None,
    fill_id: str | None = None,
    position_id: str | None = None,
    lifecycle_schema_version: str = "trade-lifecycle-v1",
    model_version: str | None = None,
    artifact_sha256: str | None = None,
    feature_schema_version: str | None = None,
    deployment_id: str | None = None,
    decision_context: str | None = None,
    caller_context: str | None = None,
    manual_decision_basis: str | None = None,
    order_creator: str | None = None,
    order_channel: str | None = None,
    regime_snapshot: dict | None = None,
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
    signal_score = signal_score or {}
    supplied_snapshot = regime_snapshot or (
        signal_score.get("regime_snapshot") if isinstance(signal_score, dict) else None
    )
    regime_config_hash = compute_regime_config_sha256(load_runtime_regime_config())
    entry_snapshot = coerce_regime_snapshot(
        supplied_snapshot,
        fallback_regime=signal_score.get("regime") if isinstance(signal_score, dict) else "UNKNOWN",
        fallback_confidence=(
            signal_score.get("regime_confidence", 0.0) if isinstance(signal_score, dict) else 0.0
        ),
        config_sha256=regime_config_hash,
    ).to_dict()

    if position_id:
        try:
            existing = positions_col.find_one({"id": position_id}, {"_id": 0})
            if existing:
                existing_snapshot = existing.get("entry_regime_snapshot")
                if supplied_snapshot and existing_snapshot and existing_snapshot != entry_snapshot:
                    raise ValueError("CONFLICTING_REGIME_SNAPSHOT_QUARANTINED")
                return existing
        except ValueError:
            raise
        except Exception:
            pass

    resolved_origin = _infer_trade_origin(
        note=note,
        execution_mode=execution_mode,
        trade_origin=trade_origin,
    )
    resolved_execution_mode = _default_execution_mode_for_origin(
        resolved_origin,
        execution_mode=execution_mode,
    )
    resolved_manual_decision_basis = _resolve_manual_decision_basis(
        resolved_origin,
        manual_decision_basis,
    )
    resolved_created_by = created_by or ("pytest" if resolved_origin == TRADE_ORIGIN_TEST else "manual")
    resolved_order_creator, resolved_order_channel = _resolve_order_provenance(
        trade_origin=resolved_origin,
        execution_mode=resolved_execution_mode,
        created_by=resolved_created_by,
        order_creator=order_creator,
        order_channel=order_channel,
    )
    pytest_test_name = os.getenv("PYTEST_CURRENT_TEST") if resolved_origin == TRADE_ORIGIN_TEST else None

    pos = {
        "coin": coin,
        "id": position_id or str(uuid.uuid4()),
        "prediction_id": prediction_id,
        "cycle_id": cycle_id,
        "signal_id": signal_id,
        "entry_decision_id": entry_decision_id,
        "reservation_id": reservation_id,
        "idempotency_key": idempotency_key,
        "client_order_id": client_order_id,
        "exchange_order_id": exchange_order_id,
        "fill_id": fill_id,
        "lifecycle_schema_version": lifecycle_schema_version,
        "model_version": model_version,
        "artifact_sha256": artifact_sha256,
        "model_artifact_sha256": artifact_sha256,
        "feature_schema_version": feature_schema_version,
        "deployment_id": deployment_id,
        "decision_context": decision_context,
        "caller_context": caller_context,
        "direction": direction.upper(),
        "entry_price": float(entry_price),
        "invested_usdt": float(invested_usdt),
        "entry_signal_score": signal_score,
        "entry_confidence": confidence,
        "entry_regime_snapshot": entry_snapshot,
        "entry_regime_family": entry_snapshot["family"],
        "entry_regime_direction": entry_snapshot["direction"],
        "entry_regime_volatility": entry_snapshot["volatility"],
        "entry_regime_confidence": entry_snapshot["confidence"],
        "entry_regime_observed_at": entry_snapshot["observed_at"],
        "entry_regime_detector_version": entry_snapshot["detector_version"],
        "entry_regime_taxonomy_version": entry_snapshot["taxonomy_version"],
        "entry_regime_config_sha256": entry_snapshot["config_sha256"],
        "entry_regime_lineage_status": "NATIVE_RUNTIME" if supplied_snapshot else "EXPLICIT_UNKNOWN",
        "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "status": "open",
        "note": note,
        "trailing_sl": None,
        "trailing_sl_active": False,
        "last_signal": None,
        "last_price": None,
        "last_checked": None,
        "trade_origin": resolved_origin,
        "execution_mode": resolved_execution_mode,
        "fill_source": fill_source or ("real_paper" if resolved_origin == TRADE_ORIGIN_PAPER else None),
        "paper_run_id": paper_run_id or runtime_paper_run_id() or "",
        "created_by": resolved_created_by,
        "order_creator": resolved_order_creator,
        "order_channel": resolved_order_channel,
        "source_test_name": source_test_name or pytest_test_name,
        "is_paper": resolved_origin == TRADE_ORIGIN_PAPER,
        "is_manual": resolved_origin == TRADE_ORIGIN_MANUAL,
        "is_test_record": resolved_origin == TRADE_ORIGIN_TEST,
        "is_system_order": resolved_order_creator == ORDER_CREATOR_SYSTEM,
        "is_user_order": resolved_order_creator == ORDER_CREATOR_USER,
        "is_system_paper_order": (
            resolved_order_creator == ORDER_CREATOR_SYSTEM
            and resolved_order_channel == ORDER_CHANNEL_PAPER_RUNNER
        ),
        "is_user_telegram_order": (
            resolved_order_creator == ORDER_CREATOR_USER
            and resolved_order_channel == ORDER_CHANNEL_TELEGRAM
        ),
        "is_user_ui_order": (
            resolved_order_creator == ORDER_CREATOR_USER
            and resolved_order_channel == ORDER_CHANNEL_UI
        ),
        "manual_decision_basis": resolved_manual_decision_basis,
        "is_system_signal_manual": resolved_manual_decision_basis == MANUAL_DECISION_SYSTEM_SIGNAL,
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


def _build_open_position_query(
    coin: str,
    *,
    trade_origin: str | None = None,
    execution_mode: str | None = None,
    order_creator: str | None = None,
    order_channel: str | None = None,
    created_by: str | None = None,
) -> dict:
    query = {"coin": coin.upper(), "status": "open"}
    if trade_origin is not None:
        query["trade_origin"] = trade_origin
    if execution_mode is not None:
        query["execution_mode"] = execution_mode
    if order_creator is not None:
        query["order_creator"] = order_creator
    if order_channel is not None:
        query["order_channel"] = order_channel
    if created_by is not None:
        query["created_by"] = created_by
    return query


def _find_open_position(
    coin: str,
    *,
    trade_origin: str | None = None,
    execution_mode: str | None = None,
    order_creator: str | None = None,
    order_channel: str | None = None,
    created_by: str | None = None,
) -> dict | None:
    query = _build_open_position_query(
        coin,
        trade_origin=trade_origin,
        execution_mode=execution_mode,
        order_creator=order_creator,
        order_channel=order_channel,
        created_by=created_by,
    )
    return positions_col.find_one(query, {"_id": 0})


def close_position(
    coin: str,
    sell_price: float,
    *,
    trade_origin: str | None = None,
    execution_mode: str | None = None,
    order_creator: str | None = None,
    order_channel: str | None = None,
    created_by: str | None = None,
) -> dict:
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

    pos = _find_open_position(
        coin,
        trade_origin=trade_origin,
        execution_mode=execution_mode,
        order_creator=order_creator,
        order_channel=order_channel,
        created_by=created_by,
    )
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
        "outcome_id": pos.get("outcome_id") or f"out-{uuid.uuid4().hex[:12]}",
        "outcome_revision": int(pos.get("outcome_revision") or 1),
        "closed_at": datetime.now().isoformat(),
        "sell_price": float(sell_price),
        "exit_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pnl_pct": round(pnl_pct, 4),
        "net_pnl_pct": round(pnl_pct, 4),
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
            "prediction_id": closed_data.get("prediction_id"),
            "cycle_id": closed_data.get("cycle_id"),
            "signal_id": closed_data.get("signal_id"),
            "position_id": closed_data.get("id"),
            "outcome_id": closed_data.get("outcome_id"),
            "outcome_revision": closed_data.get("outcome_revision"),
            "net_pnl_pct": closed_data.get("net_pnl_pct"),
            "model_version": closed_data.get("model_version"),
            "artifact_sha256": closed_data.get("artifact_sha256"),
            "model_artifact_sha256": (
                closed_data.get("model_artifact_sha256")
                or closed_data.get("artifact_sha256")
            ),
            "feature_schema_version": closed_data.get("feature_schema_version"),
            "deployment_id": closed_data.get("deployment_id"),
            "decision_context": closed_data.get("decision_context"),
            "caller_context": closed_data.get("caller_context"),
            "trade_origin": closed_data.get("trade_origin"),
            "execution_mode": closed_data.get("execution_mode"),
            "fill_source": closed_data.get("fill_source"),
            "paper_run_id": closed_data.get("paper_run_id"),
            "created_by": closed_data.get("created_by"),
            "order_creator": closed_data.get("order_creator"),
            "order_channel": closed_data.get("order_channel"),
            "source_test_name": closed_data.get("source_test_name"),
            "is_paper": closed_data.get("is_paper"),
            "is_manual": closed_data.get("is_manual"),
            "is_test_record": closed_data.get("is_test_record"),
            "is_system_order": closed_data.get("is_system_order"),
            "is_user_order": closed_data.get("is_user_order"),
            "is_system_paper_order": closed_data.get("is_system_paper_order"),
            "is_user_telegram_order": closed_data.get("is_user_telegram_order"),
            "is_user_ui_order": closed_data.get("is_user_ui_order"),
            "manual_decision_basis": closed_data.get("manual_decision_basis"),
            "is_system_signal_manual": closed_data.get("is_system_signal_manual"),
        }
        closed_trades_col.insert_one(simple)
    except Exception:
        pass

    # Canonical transactional outcome evidence. Only model-linked positions are
    # eligible; manual/legacy positions without a prediction remain excluded.
    if closed_data.get("prediction_id"):
        try:
            from btc_scraper.ml_engine.runtime_evidence_store import get_runtime_evidence_store
            get_runtime_evidence_store().append_outcome_link({
                **closed_data,
                "position_id": closed_data.get("id"),
            })
        except Exception as exc:
            from btc_scraper.ml_engine.operational_health import record_degradation
            record_degradation("prediction_audit", "prediction_audit_write_failure_total", exc)

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

    # Cập nhật outcome cho RL Exit shadow records của position này.
    try:
        import sys as _sys
        import os as _os
        _proj_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        if _proj_root not in _sys.path:
            _sys.path.insert(0, _proj_root)
        from scripts.shadow_log import update_rl_outcome as _rl_shadow_update
        _pos_uuid = closed_data.get("id")
        if _pos_uuid:
            _rl_shadow_update(
                position_id=_pos_uuid,
                actual_result=closed_data.get("result", "LOSS"),
                actual_pnl_pct=float(closed_data.get("pnl_pct", 0.0)),
            )
    except Exception:
        pass

    return closed_data


def close_partial_position(
    coin: str,
    sell_price: float,
    percentage: float,
    *,
    trade_origin: str | None = None,
    execution_mode: str | None = None,
    order_creator: str | None = None,
    order_channel: str | None = None,
    created_by: str | None = None,
) -> dict:
    """
    Đóng một phần vị thế (theo phần trăm) và tính toán chỉ số hiệu suất cho phần đó.
    Vị thế gốc sẽ được giảm invested_usdt tương ứng.
    """
    coin = coin.upper()
    if percentage <= 0 or percentage >= 100:
        raise ValueError(f"Phần trăm chốt lời phải nằm trong khoảng (0, 100). Giá trị: {percentage}")

    pos = _find_open_position(
        coin,
        trade_origin=trade_origin,
        execution_mode=execution_mode,
        order_creator=order_creator,
        order_channel=order_channel,
        created_by=created_by,
    )
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
            "cycle_id": closed_data.get("cycle_id"),
            "trade_origin": closed_data.get("trade_origin"),
            "execution_mode": closed_data.get("execution_mode"),
            "fill_source": closed_data.get("fill_source"),
            "paper_run_id": closed_data.get("paper_run_id"),
            "created_by": closed_data.get("created_by"),
            "order_creator": closed_data.get("order_creator"),
            "order_channel": closed_data.get("order_channel"),
            "source_test_name": closed_data.get("source_test_name"),
            "is_paper": closed_data.get("is_paper"),
            "is_manual": closed_data.get("is_manual"),
            "is_test_record": closed_data.get("is_test_record"),
            "is_system_order": closed_data.get("is_system_order"),
            "is_user_order": closed_data.get("is_user_order"),
            "is_system_paper_order": closed_data.get("is_system_paper_order"),
            "is_user_telegram_order": closed_data.get("is_user_telegram_order"),
            "is_user_ui_order": closed_data.get("is_user_ui_order"),
            "manual_decision_basis": closed_data.get("manual_decision_basis"),
            "is_system_signal_manual": closed_data.get("is_system_signal_manual"),
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
            eval_info["signal_id"] = (
                f"exit-recheck:{p.get('id')}:{ana.get('time') or ana.get('timestamp') or avg_step}"
            )
            eval_info["decision_context"] = "exit_recheck"
            eval_info["caller_context"] = "position_tracker"
            eval_info["coin"] = coin
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
        raw_rl_action = None
        model = get_ppo_model()
        from btc_scraper.ml_engine.inference_circuit_breaker import RL_INFERENCE_BREAKER
        if model is not None and RL_INFERENCE_BREAKER.allowed():
            try:
                obs = _build_rl_observation(ana, avg_confidence, avg_step, weighted_entry, pnl_pct, direction, avg_min_pnl, avg_correlation)
                
                # Retrieve cached LSTM states for this coin
                lstm_cache_key = coin.upper()
                if lstm_cache_key not in _LSTM_STATE_CACHE:
                    lstm_states = None
                    episode_start = np.ones((1,), dtype=bool)
                else:
                    lstm_states, episode_start = _LSTM_STATE_CACHE[lstm_cache_key]

                from btc_scraper.ml_engine.rl_inference import guarded_rl_predict
                raw_rl_action, next_lstm_states = guarded_rl_predict(model, obs, state=lstm_states, episode_start=episode_start)
                from btc_scraper.trading.rl_action_guard import guard_rl_action
                guarded = guard_rl_action(raw_rl_action, meta_probability=pos_meta_prob)
                rl_action = guarded.action
                
                # Confidence Gate: only execute PARTIAL_CLOSE (1), TAKE_PROFIT (3), or EXIT (4) if pos_meta_prob is None or < 0.45.
                # Otherwise, override to HOLD (0).
                # Cache the updated LSTM hidden state
                _LSTM_STATE_CACHE[lstm_cache_key] = (next_lstm_states, np.zeros((1,), dtype=bool))
                save_lstm_cache()
                print(f"[RL Exit Agent] Coin {coin}: raw={raw_rl_action}, effective={rl_action}, guard={guarded.decision}")
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
        from btc_scraper.trading.rl_action_guard import rl_exit_mode
        shadow_mode = rl_exit_mode() == "shadow"

        if shadow_mode and raw_rl_action is not None:
            _log_rl_shadow_prediction(
                coin,
                raw_rl_action,
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
