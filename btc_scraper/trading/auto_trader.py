"""
Auto Trader — Decision engine tự động đặt lệnh Market trên Binance Testnet.

Luồng (sau Phase 1 remediation):
    analysis dict (từ analyze_market)
        ↓
    AutoTrader.evaluate_and_trade(analysis)
        ↓
    should_trade() — kiểm tra ngưỡng meta_confidence + score + filters
        ↓ YES
    compute_position_size() — 2% risk dựa trên SL distance
        ↓
    ExecutionEngine.submit_live()  ←── DUY NHẤT entry point viết lệnh
        ↓ (tích hợp: Liquidity → Slippage → Risk Guard → OrderType → Fill)
    log_order() — ghi vào logs/auto_trade_log.json
        ↓
    notify_telegram() — gửi alert
        ↓
    position_tracker.add_position() — sync với hệ thống tracking

Circuit Breaker:
    - 5 lệnh thua liên tiếp → pause 24h
    - Reset tự động sau 24h hoặc khi user restart bot

Phase 1 Rule: Tất cả lệnh write lên sàn được route qua ExecutionEngine.
              Cấm gọi CCXTClient.create_market_buy/sell trực tiếp.

Config (từ .env):
    AUTO_TRADE_DRY_RUN=true               # Bắt buộc false để live
    AUTO_TRADE_BINANCE_API_KEY=...
    AUTO_TRADE_BINANCE_API_SECRET=...
    AUTO_TRADE_BINANCE_TESTNET=true       # false = mainnet (không khuyến nghị)
    AUTO_TRADE_META_THRESHOLD=0.85
    AUTO_TRADE_SCORE_THRESHOLD=75
    AUTO_TRADE_ACCOUNT_USDT=500           # Kích thước tài khoản ước tính
    AUTO_TRADE_RISK_PCT=2.0               # % risk per trade
    AUTO_TRADE_MAX_TRADE_USDT=100         # Cap tối đa mỗi lệnh
    AUTO_TRADE_MIN_TRADE_USDT=10          # Minimum (Binance min notional)
    AUTO_TRADE_MAX_DAILY=5                # Số lệnh tối đa/ngày
    AUTO_TRADE_CIRCUIT_BREAKER_N=5        # Dừng sau N lệnh thua liên tiếp
    AUTO_TRADE_COINS=                     # Để trống = analysis universe
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal
from typing import Dict, List, Optional, Any

from btc_scraper.analysis.correlation import correlation_engine, SECTOR_MAP
from btc_scraper.trading.exposure_manager import exposure_manager
from btc_scraper.ml_engine.signal_score import (
    signal_strength_from_score,
    _primary_signal_action,
    normalize_directional_score,
)
from btc_scraper.trading.decision_types import (
    TradeAction,
    EntryRejectionReason,
    AuthorizationReason,
    FinalDecisionStatus,
    DecisionStage,
    DecisionBreakdown,
    SizingDecision,
    EntryDecision,
    EventRiskLevel,
    EntryPermission,
    PositionAction,
    OrderIntent,
    EventRiskDecision,
    RiskEvaluationResult,
    RiskPolicyEvaluator,
)
from btc_scraper.core.paths import (
    build_logs_path,
    runtime_deployment_id,
    runtime_evidence_eligible,
    runtime_paper_run_id,
)
from btc_scraper.trading.prospective_shadow_logger import get_prospective_shadow_logger

AUTO_TRADE_LOG = build_logs_path("auto_trade_log.json")
CIRCUIT_BREAKER_STATE = build_logs_path("auto_trade_circuit.json")


def _auto_trade_log_path() -> Path:
    return build_logs_path("auto_trade_log.json")


def _circuit_breaker_state_path() -> Path:
    return build_logs_path("auto_trade_circuit.json")

# ─── Config Loader ─────────────────────────────────────────────────────────────

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except Exception:
        return default

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except Exception:
        return default

def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key, str(default)).lower()
    return v not in ("false", "0", "no", "off")

def _env_list(key: str, default: List[str]) -> List[str]:
    v = os.getenv(key, "").strip()
    return [x.strip().upper() for x in v.split(",") if x.strip()] if v else default


# ─── Audit Log ─────────────────────────────────────────────────────────────────

def _load_log() -> List[Dict]:
    path = _auto_trade_log_path()
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_log(data: List[Dict]) -> None:
    path = _auto_trade_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _append_log(entry: Dict) -> None:
    """
    Append a trade log entry to the auto-trade log JSON file.

    CONCURRENCY CONTRACT: Single-Writer within the runtime process lifecycle.
    This implementation avoids full JSON file re-parsing by seeking to the tail
    and splicing before the closing bracket in bounded latency. It is designed
    for single-writer execution on the main event loop and does not employ cross-process
    file locks.
    """
    path = _auto_trade_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry_json = json.dumps(entry, ensure_ascii=False, indent=2)
    indented_entry = "\n".join("  " + line for line in entry_json.splitlines())

    if not path.exists() or path.stat().st_size == 0:
        with open(path, "w", encoding="utf-8") as f:
            f.write("[\n" + indented_entry + "\n]\n")
        return

    try:
        with open(path, "r+b") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            scan_size = min(size, 1024)
            f.seek(size - scan_size)
            tail = f.read(scan_size)
            bracket_pos = tail.rfind(b"]")
            if bracket_pos == -1:
                # Fallback to full load/dump if file structure is unexpected
                data = _load_log()
                data.append(entry)
                _save_log(data)
                return

            abs_bracket_pos = (size - scan_size) + bracket_pos
            before_bracket = tail[:bracket_pos].strip()
            is_empty_array = (before_bracket == b"[") or (size <= 5 and before_bracket.endswith(b"["))

            f.seek(abs_bracket_pos)
            if is_empty_array:
                f.write(("  " + indented_entry.lstrip() + "\n]\n").encode("utf-8"))
            else:
                f.write((",\n" + indented_entry + "\n]\n").encode("utf-8"))
            f.truncate()
    except Exception:
        data = _load_log()
        data.append(entry)
        _save_log(data)


def _append_logs_batch(entries: List[Dict]) -> None:
    """Append multiple trade log entries in a single file open and fsync operation.

    Designed for NO_TRADE_SHADOW paper batching across universe symbols to avoid
    per-symbol disk open overhead.
    """
    if not entries:
        return
    if len(entries) == 1:
        _append_log(entries[0])
        return

    path = _auto_trade_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    formatted_entries = []
    for entry in entries:
        entry_json = json.dumps(entry, ensure_ascii=False, indent=2)
        formatted_entries.append("\n".join("  " + line for line in entry_json.splitlines()))
    combined_body = ",\n".join(formatted_entries)

    if not path.exists() or path.stat().st_size == 0:
        with open(path, "w", encoding="utf-8") as f:
            f.write("[\n" + combined_body + "\n]\n")
            f.flush()
            os.fsync(f.fileno())
        return

    try:
        with open(path, "r+b") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            scan_size = min(size, 1024)
            f.seek(size - scan_size)
            tail = f.read(scan_size)
            bracket_pos = tail.rfind(b"]")
            if bracket_pos == -1:
                data = _load_log()
                data.extend(entries)
                _save_log(data)
                return

            abs_bracket_pos = (size - scan_size) + bracket_pos
            before_bracket = tail[:bracket_pos].strip()
            is_empty_array = (before_bracket == b"[") or (size <= 5 and before_bracket.endswith(b"["))

            f.seek(abs_bracket_pos)
            if is_empty_array:
                f.write(("  " + combined_body.lstrip() + "\n]\n").encode("utf-8"))
            else:
                f.write((",\n" + combined_body + "\n]\n").encode("utf-8"))
            f.truncate()
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        data = _load_log()
        data.extend(entries)
        _save_log(data)


# ─── Circuit Breaker State ──────────────────────────────────────────────────────

def _load_circuit() -> Dict:
    path = _circuit_breaker_state_path()
    if not path.exists():
        return {"consecutive_losses": 0, "tripped_at": None, "total_trades_today": 0, "date": ""}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"consecutive_losses": 0, "tripped_at": None, "total_trades_today": 0, "date": ""}

def _save_circuit(state: Dict) -> None:
    path = _circuit_breaker_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ─── Main AutoTrader Class ──────────────────────────────────────────────────────

class AutoTrader:
    """
    Singleton-like auto-trading engine.
    Sử dụng: auto_trader.evaluate_and_trade(analysis_dict)

    Phase 1: Tất cả write lệnh được route qua ExecutionEngine.submit_live().
    Không có call trực tiếp tới CCXTClient nữa.
    """

    def __init__(self, activation_manifest_path: str | Path | None = None):
        self._execution_engine = None  # Lazy init ExecutionEngine with WriteAdapter
        self._last_exit_timestamps: dict[str, datetime] = {}
        self._current_cycle_shadow_summaries: dict[str, Any] = {}
        if activation_manifest_path is not None:
            self._activation_manifest_path = Path(activation_manifest_path)
        else:
            env_path = os.environ.get("PROSPECTIVE_ACTIVATION_MANIFEST_PATH")
            self._activation_manifest_path = Path(env_path) if env_path else None

    def activate_prospective_evidence(self, manifest: Any):
        """Explicit activation path for prospective evidence in paper runtime with verified manifest."""
        from btc_scraper.trading.prospective_shadow_logger import (
            EvidenceActivationManifest,
            load_activation_manifest,
            get_prospective_shadow_logger,
            LOCKED_VCB_V1_SPEC,
        )
        if isinstance(manifest, (str, Path)):
            manifest_obj = load_activation_manifest(manifest)
            self._activation_manifest_path = Path(manifest)
        elif isinstance(manifest, EvidenceActivationManifest):
            manifest_obj = manifest
            if hasattr(manifest, "state_path") and manifest.state_path:
                self._activation_manifest_path = Path(manifest.state_path).parent / "activation_manifest.json"
        else:
            raise TypeError(f"Expected EvidenceActivationManifest or Path/str, got {type(manifest)}")

        manifest_obj.verify_integrity()
        if manifest_obj.paper_policy != "NO_TRADE_SHADOW":
            raise ValueError(f"Paper policy must be NO_TRADE_SHADOW, got {manifest_obj.paper_policy!r}")
        if manifest_obj.strategy_spec_sha256 != LOCKED_VCB_V1_SPEC.strategy_spec_sha256:
            raise ValueError(
                f"Manifest strategy_spec_sha256 mismatch: {manifest_obj.strategy_spec_sha256} vs {LOCKED_VCB_V1_SPEC.strategy_spec_sha256}"
            )

        logger = get_prospective_shadow_logger(
            activation_manifest=manifest_obj,
            manifest_path=self._activation_manifest_path,
            reset_singleton=True,
        )
        return logger

    def _get_shadow_logger(self):
        return get_prospective_shadow_logger(manifest_path=self._activation_manifest_path)

    def get_last_exit_timestamps(self) -> dict[str, datetime]:
        """Returns the most recent exit timestamp per coin, queried from DB and memory."""
        res: dict[str, datetime] = dict(self._last_exit_timestamps)
        try:
            from btc_scraper.core.db import closed_positions_col
            if closed_positions_col is not None:
                recent_closed = closed_positions_col.find(
                    {}, {"coin": 1, "closed_at": 1, "exit_time": 1, "timestamp": 1, "_id": 0}
                )
                for doc in recent_closed:
                    c = str(doc.get("coin") or "").upper().removesuffix("USDT")
                    t_val = doc.get("closed_at") or doc.get("exit_time") or doc.get("timestamp")
                    if c and t_val:
                        try:
                            if isinstance(t_val, str):
                                dt = datetime.fromisoformat(t_val.replace("Z", "+00:00"))
                            elif isinstance(t_val, datetime):
                                dt = t_val if t_val.tzinfo is not None else t_val.replace(tzinfo=timezone.utc)
                            else:
                                continue
                            if c not in res or dt > res[c]:
                                res[c] = dt
                        except Exception:
                            pass
        except Exception:
            pass
        return res

    @property
    def dry_run(self) -> bool:
        return _env_bool("AUTO_TRADE_DRY_RUN", True)

    @property
    def meta_threshold(self) -> float:
        return _env_float("AUTO_TRADE_META_THRESHOLD", 0.50)

    @property
    def score_threshold(self) -> int:
        return _env_int("AUTO_TRADE_SCORE_THRESHOLD", 75)

    @property
    def account_usdt(self) -> float:
        return _env_float("AUTO_TRADE_ACCOUNT_USDT", 500.0)

    @property
    def risk_pct(self) -> float:
        """% tài khoản risk mỗi lệnh (mặc định 2%)."""
        return _env_float("AUTO_TRADE_RISK_PCT", 2.0)

    @property
    def max_trade_usdt(self) -> float:
        return _env_float("AUTO_TRADE_MAX_TRADE_USDT", 100.0)

    @property
    def min_trade_usdt(self) -> float:
        return _env_float("AUTO_TRADE_MIN_TRADE_USDT", 10.0)

    @property
    def max_daily_trades(self) -> int:
        return _env_int("AUTO_TRADE_MAX_DAILY", 5)

    @property
    def circuit_breaker_n(self) -> int:
        return _env_int("AUTO_TRADE_CIRCUIT_BREAKER_N", 5)

    @property
    def allowed_coins(self) -> List[str]:
        """Execution universe; it must remain inside the analysis universe."""
        from btc_scraper.core.config import get_runtime_universe
        return list(get_runtime_universe().execution_symbols)

    @property
    def use_kelly(self) -> bool:
        return _env_bool("AUTO_TRADE_USE_KELLY", True)

    @property
    def kelly_fraction(self) -> float:
        return _env_float("AUTO_TRADE_KELLY_FRACTION", 0.5)

    @property
    def min_rr(self) -> float:
        """Minimum reward-to-risk ratio for entry.  Default 1.0."""
        return _env_float("AUTO_TRADE_MIN_RR", 1.0)

    @property
    def min_expected_edge(self) -> float:
        """Minimum net expected value for entry.  Default 0.0."""
        return _env_float("AUTO_TRADE_MIN_EXPECTED_EDGE", 0.0)

    @property
    def estimated_fee_ratio(self) -> float:
        """Estimated round-trip fee ratio (taker).  Default 0.001 (10 bps)."""
        return _env_float("AUTO_TRADE_ESTIMATED_FEE_RATIO", 0.001)

    @property
    def estimated_slippage_ratio(self) -> float:
        """Estimated slippage ratio.  Default 0.0005 (5 bps)."""
        return _env_float("AUTO_TRADE_ESTIMATED_SLIPPAGE_RATIO", 0.0005)

    @property
    def estimated_funding_cost(self) -> float:
        """Estimated funding cost ratio per trade.  Default 0.0."""
        return _env_float("AUTO_TRADE_ESTIMATED_FUNDING_COST", 0.0)

    def _get_execution_engine(self):
        """Lazy-init ExecutionEngine with WriteExchangeAdapter.
        
        ExecutionEngine is the ONLY component allowed to write to the exchange.
        """
        if self._execution_engine is None:
            from btc_scraper.execution.execution_engine import ExecutionEngine
            from btc_scraper.execution.exchange_adapter import make_write_adapter_from_env
            adapter = make_write_adapter_from_env() if not self.dry_run else None
            self._execution_engine = ExecutionEngine(exchange_adapter=adapter)
        return self._execution_engine

    # ─── Circuit Breaker ────────────────────────────────────────────────────────

    def _check_circuit_breaker(self) -> tuple[bool, str]:
        """
        Kiểm tra circuit breaker.
        Returns: (is_ok, reason_if_blocked)
        """
        state = _load_circuit()
        today = datetime.now().strftime("%Y-%m-%d")

        # Reset daily counter nếu sang ngày mới
        if state.get("date") != today:
            state["total_trades_today"] = 0
            state["date"] = today
            # Không reset consecutive_losses — vẫn nhớ chuỗi thua qua ngày

        # Kiểm tra circuit breaker tripped
        if state.get("tripped_at"):
            tripped_at = state["tripped_at"]
            try:
                tripped_dt = datetime.fromisoformat(tripped_at)
                elapsed = (datetime.now() - tripped_dt).total_seconds()
                if elapsed < 86400:  # 24 giờ
                    remaining_h = (86400 - elapsed) / 3600
                    return False, f"Circuit breaker: {self.circuit_breaker_n} thua lien tiep. Reset sau {remaining_h:.1f}h"
                else:
                    # Auto-reset sau 24h
                    state["tripped_at"] = None
                    state["consecutive_losses"] = 0
                    _save_circuit(state)
            except Exception:
                state["tripped_at"] = None
                _save_circuit(state)

        # Kiểm tra daily limit
        if state.get("total_trades_today", 0) >= self.max_daily_trades:
            return False, f"Da dat gioi han {self.max_daily_trades} lenh/ngay"

        return True, ""

    def _trip_circuit_breaker(self) -> None:
        """Kích hoạt circuit breaker."""
        state = _load_circuit()
        state["tripped_at"] = datetime.now().isoformat()
        _save_circuit(state)

    def _record_trade_result(self, result: str) -> None:
        """
        Cập nhật circuit breaker state sau mỗi lệnh.
        result: 'WIN' | 'LOSS' | 'OPEN' (chưa biết)
        """
        state = _load_circuit()
        today = datetime.now().strftime("%Y-%m-%d")
        if state.get("date") != today:
            state["total_trades_today"] = 0
            state["date"] = today

        if result == "OPEN":
            state["total_trades_today"] = state.get("total_trades_today", 0) + 1
        elif result == "LOSS":
            state["consecutive_losses"] = state.get("consecutive_losses", 0) + 1
            if state["consecutive_losses"] >= self.circuit_breaker_n:
                state["tripped_at"] = datetime.now().isoformat()
        elif result == "WIN":
            state["consecutive_losses"] = 0
        # OPEN: không thay đổi consecutive_losses

        _save_circuit(state)

    # ─── Position Size ──────────────────────────────────────────────────────────

    def compute_position_size(
        self,
        entry_price: float,
        sl_price: float,
        current_balance: Optional[float] = None,
        multiplier: float = 1.0,
        win_prob: Optional[float] = None,
        rr_ratio: Optional[float] = None,
        var_cap: Optional[float] = None,
        exposure_cap: Optional[float] = None,
        max_trade_cap: Optional[float] = None,
        min_trade_cap: Optional[float] = None,
        portfolio_weight: Optional[float] = None,
    ) -> SizingDecision:
        """Tính position size dựa trên fixed fractional risk (2% mặc định)
        nhân với setup multiplier (Kelly/Regime) và áp dụng các cap rủi ro.

        Returns:
            SizingDecision object.
        """
        # 1. Validate prices
        if entry_price <= 0.0 or sl_price <= 0.0:
            return SizingDecision(
                entry_price=entry_price,
                sl_price=sl_price,
                stop_distance_pct=0.0,
                risk_pct=0.0,
                risk_notional=0.0,
                raw_notional=0.0,
                portfolio_weight=portfolio_weight,
                risk_multiplier=multiplier,
                rejected=True,
                rejection_reason=EntryRejectionReason.INVALID_SIZING_INPUT,
            )

        # 2. Stop distance calculation
        sl_distance_pct = abs(entry_price - sl_price) / entry_price
        if sl_distance_pct < 0.001:
            return SizingDecision(
                entry_price=entry_price,
                sl_price=sl_price,
                stop_distance_pct=sl_distance_pct,
                risk_pct=0.0,
                risk_notional=0.0,
                raw_notional=0.0,
                portfolio_weight=portfolio_weight,
                risk_multiplier=multiplier,
                rejected=True,
                rejection_reason=EntryRejectionReason.INVALID_SIZING_INPUT,
            )

        balance = current_balance if current_balance and current_balance > 0 else self.account_usdt

        # Check explicit zero or negative risk multiplier
        if multiplier <= 0.0:
            return SizingDecision(
                entry_price=entry_price,
                sl_price=sl_price,
                stop_distance_pct=sl_distance_pct,
                risk_pct=0.0,
                risk_notional=0.0,
                raw_notional=0.0,
                portfolio_weight=portfolio_weight,
                risk_multiplier=0.0,
                rejected=True,
                rejection_reason=EntryRejectionReason.RISK_MANAGER_BLOCKED,
            )

        # 3. Risk-based sizing
        risk_pct = self.risk_pct * max(0.01, min(1.0, multiplier))
        risk_notional = balance * risk_pct / 100.0
        raw_notional = risk_notional / sl_distance_pct

        # Start sequential caps enforcement
        notional = raw_notional

        # 4. Kelly adjustment
        kelly_adjusted = None
        kelly_f = None
        if self.use_kelly and win_prob is not None and rr_ratio is not None and rr_ratio > 0:
            kelly_f = win_prob - (1.0 - win_prob) / rr_ratio
            if kelly_f <= 0:
                return SizingDecision(
                    entry_price=entry_price,
                    sl_price=sl_price,
                    stop_distance_pct=sl_distance_pct,
                    risk_pct=risk_pct,
                    risk_notional=risk_notional,
                    raw_notional=raw_notional,
                    portfolio_weight=portfolio_weight,
                    risk_multiplier=multiplier,
                    rejected=True,
                    rejection_reason=EntryRejectionReason.NON_POSITIVE_KELLY,
                )
            kelly_risk_pct = kelly_f * self.kelly_fraction * 100.0
            kelly_risk_notional = balance * kelly_risk_pct / 100.0
            kelly_adjusted = kelly_risk_notional / sl_distance_pct
            notional = min(notional, kelly_adjusted)

        # 5. Portfolio Allocation Cap (P0-A)
        portfolio_capped = None
        if portfolio_weight is not None:
            if portfolio_weight <= 0.0:
                return SizingDecision(
                    entry_price=entry_price,
                    sl_price=sl_price,
                    stop_distance_pct=sl_distance_pct,
                    risk_pct=risk_pct,
                    risk_notional=risk_notional,
                    raw_notional=raw_notional,
                    portfolio_weight=0.0,
                    risk_multiplier=multiplier,
                    rejected=True,
                    rejection_reason=EntryRejectionReason.PORTFOLIO_WEIGHT_ZERO,
                )
            portfolio_capped = round(balance * portfolio_weight, 2)
            notional = min(notional, portfolio_capped)

        # 6. VaR Cap
        var_capped = None
        if var_cap is not None:
            var_capped = var_cap
            notional = min(notional, var_capped)

        # 7. Exposure Cap
        exposure_capped = None
        if exposure_cap is not None:
            exposure_capped = exposure_cap
            notional = min(notional, exposure_capped)

        # 8. Hard Max Cap
        max_trade_capped = None
        max_limit = max_trade_cap if max_trade_cap is not None else self.max_trade_usdt
        if notional > max_limit:
            max_trade_capped = max_limit
            notional = min(notional, max_limit)

        risk_adjusted_notional = max(0.0, notional)

        # 9. Min Notional Validation
        min_limit = min_trade_cap if min_trade_cap is not None else self.min_trade_usdt
        allowed_risk = risk_notional
        if kelly_f is not None:
            kelly_risk_pct = kelly_f * self.kelly_fraction * 100.0
            allowed_risk = min(allowed_risk, balance * kelly_risk_pct / 100.0)

        if notional < min_limit:
            # A floor cannot override a risk cap or portfolio allocation cap
            if (
                (portfolio_capped is not None and portfolio_capped < min_limit)
                or (var_capped is not None and var_capped < min_limit)
                or (exposure_capped is not None and exposure_capped < min_limit)
            ):
                return SizingDecision(
                    entry_price=entry_price,
                    sl_price=sl_price,
                    stop_distance_pct=sl_distance_pct,
                    risk_pct=risk_pct,
                    risk_notional=risk_notional,
                    raw_notional=raw_notional,
                    kelly_adjusted=kelly_adjusted,
                    portfolio_weight=portfolio_weight,
                    portfolio_capped=portfolio_capped,
                    var_capped=var_capped,
                    exposure_capped=exposure_capped,
                    max_trade_capped=max_trade_capped,
                    risk_adjusted_notional=risk_adjusted_notional,
                    final_notional=0.0,
                    risk_multiplier=multiplier,
                    rejected=True,
                    rejection_reason=EntryRejectionReason.CAPITAL_CAPACITY_EXCEEDED,
                )

            # Reject if min notional exceeds allowed risk
            min_notional_risk = min_limit * sl_distance_pct
            if min_notional_risk > allowed_risk:
                return SizingDecision(
                    entry_price=entry_price,
                    sl_price=sl_price,
                    stop_distance_pct=sl_distance_pct,
                    risk_pct=risk_pct,
                    risk_notional=risk_notional,
                    raw_notional=raw_notional,
                    kelly_adjusted=kelly_adjusted,
                    portfolio_weight=portfolio_weight,
                    portfolio_capped=portfolio_capped,
                    var_capped=var_capped,
                    exposure_capped=exposure_capped,
                    max_trade_capped=max_trade_capped,
                    risk_adjusted_notional=risk_adjusted_notional,
                    final_notional=0.0,
                    risk_multiplier=multiplier,
                    rejected=True,
                    rejection_reason=EntryRejectionReason.INVALID_SIZING_INPUT,
                )
            else:
                notional = min_limit

        return SizingDecision(
            entry_price=entry_price,
            sl_price=sl_price,
            stop_distance_pct=sl_distance_pct,
            risk_pct=risk_pct,
            risk_notional=risk_notional,
            raw_notional=raw_notional,
            kelly_adjusted=kelly_adjusted,
            portfolio_weight=portfolio_weight,
            portfolio_capped=portfolio_capped,
            var_capped=var_capped,
            exposure_capped=exposure_capped,
            max_trade_capped=max_trade_capped,
            risk_adjusted_notional=risk_adjusted_notional,
            final_notional=round(notional, 2),
            risk_multiplier=multiplier,
            rejected=False,
        )

    # ─── Trade Decision ─────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_meta_probability(sig_score_obj: Dict[str, Any]) -> Optional[float]:
        """Resolve meta_probability from signal_score, supporting the
        meta_confidence → meta_probability migration.

        Reads ``meta_probability`` first; falls back to ``meta_confidence``.
        Logs a deprecation note when the old key is used.
        """
        val = sig_score_obj.get("meta_probability")
        if val is None:
            val = sig_score_obj.get("meta_confidence")
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def build_entry_decision(
        self,
        analysis: Dict[str, Any],
        coin: str,
        risk_decision: Optional[Dict[str, Any]] = None,
        portfolio_decision: Optional[Dict[str, Any]] = None,
        current_balance: Optional[float] = None,
        var_cap: Optional[float] = None,
        exposure_cap: Optional[float] = None,
        event_risk: Optional[EventRiskDecision] = None,
        evaluation_time: Optional[datetime] = None,
    ) -> EntryDecision:
        """Canonical entry decision pipeline.

        This is the single source of truth for whether a trade should be
        entered.  All policy checks live here — ``should_trade()`` is a
        backward-compatible wrapper.

        Pipeline stages (in precedence order):
            1. NORMALIZATION — validate action / direction encoding
            2. ELIGIBILITY  — meta_probability, RR, Kelly, EV, strength
            3. EDGE         — net expected value gate
            4. SIZING       — position size computation

        Returns:
            EntryDecision with full DecisionBreakdown.
        """
        sig_score = analysis.get("signal_score") or {}
        raw_signal = str(analysis.get("signal", ""))
        raw_signal_upper = raw_signal.upper()
        tp_sl = analysis.get("tp_sl") or {}
        presented_final_decision = analysis.get("causal_decision") or {}
        prediction_id = analysis.get("prediction_id") or sig_score.get("prediction_id")
        persisted_final_decision: Dict[str, Any] | None = None
        if runtime_evidence_eligible() and prediction_id:
            try:
                from btc_scraper.ml_engine.runtime_evidence_store import (
                    get_runtime_evidence_store,
                )

                store = get_runtime_evidence_store()
                getter = getattr(store, "get_committed_final_decision", None)
                persisted_final_decision = (
                    getter(str(prediction_id))
                    if getter is not None
                    else store.get_final_decision_for_prediction(str(prediction_id))
                )
            except Exception:
                persisted_final_decision = None
        causal_decision = (
            persisted_final_decision
            if runtime_evidence_eligible()
            else presented_final_decision
        ) or {}
        if persisted_final_decision is not None:
            analysis["causal_decision"] = persisted_final_decision
        lineage = {
            "decision_id": (
                causal_decision.get("decision_id")
                or analysis.get("entry_decision_id")
                or f"ed-{uuid.uuid4().hex[:12]}"
            ),
            "signal_id": analysis.get("signal_id") or sig_score.get("signal_id"),
            "prediction_id": analysis.get("prediction_id") or sig_score.get("prediction_id"),
            "model_version": analysis.get("model_version") or sig_score.get("model_version"),
            "artifact_hash": (
                analysis.get("artifact_sha256")
                or sig_score.get("artifact_sha256")
                or sig_score.get("model_artifact_sha256")
            ),
            "feature_schema_version": (
                analysis.get("feature_schema_version")
                or sig_score.get("feature_schema_version")
            ),
            "deployment_id": analysis.get("deployment_id") or sig_score.get("deployment_id"),
            "paper_run_id": analysis.get("paper_run_id") or sig_score.get("paper_run_id"),
            "cycle_id": analysis.get("cycle_id") or sig_score.get("cycle_id"),
            "decision_sha256": causal_decision.get("decision_sha256"),
            "decision_context": analysis.get("decision_context") or sig_score.get("decision_context"),
            "caller_context": analysis.get("caller_context") or sig_score.get("caller_context"),
        }

        score = sig_score.get("score", 50)
        try:
            score = int(score)
        except (TypeError, ValueError):
            score = 50

        # ── Stage: NORMALIZATION ──────────────────────────────────────────
        normalized = normalize_directional_score(
            score, action_threshold=self.score_threshold,
        )

        # Determine action from signal_score object (upstream).
        upstream_action_str = str(
            sig_score.get("action") or _primary_signal_action(raw_signal)
        ).upper()
        try:
            upstream_action = TradeAction(upstream_action_str)
        except ValueError:
            upstream_action = TradeAction.NEUTRAL

        # Event Risk Policy Overlay Resolution (P0-B)
        overlay_present = False
        malformed_event_risk = False
        resolved_event_risk: Optional[EventRiskDecision] = None

        candidate_er = event_risk if event_risk is not None else analysis.get("event_risk")
        if candidate_er is not None or "event_risk" in analysis:
            overlay_present = True
            if isinstance(candidate_er, EventRiskDecision):
                resolved_event_risk = candidate_er
            elif isinstance(candidate_er, dict):
                try:
                    resolved_event_risk = EventRiskDecision.from_dict(candidate_er)
                except Exception:
                    malformed_event_risk = True
            else:
                malformed_event_risk = True

        # Decision boundary evaluation timestamp (strictly deterministic)
        raw_eval_time = evaluation_time or analysis.get("evaluation_time") or analysis.get("timestamp")
        eval_time: Optional[datetime] = None
        if overlay_present:
            # When overlay is present, evaluation_time is mandatory and must be a timezone-aware datetime.
            # Never fallback to datetime.now() and never attach UTC silently to naive datetimes.
            if raw_eval_time is not None:
                if isinstance(raw_eval_time, str):
                    try:
                        parsed_dt = datetime.fromisoformat(raw_eval_time)
                        if parsed_dt.tzinfo is not None and parsed_dt.tzinfo.utcoffset(parsed_dt) is not None:
                            eval_time = parsed_dt
                    except Exception:
                        eval_time = None
                elif isinstance(raw_eval_time, datetime):
                    if raw_eval_time.tzinfo is not None and raw_eval_time.tzinfo.utcoffset(raw_eval_time) is not None:
                        eval_time = raw_eval_time
        else:
            # Baseline P0-A behavior when overlay is absent
            if raw_eval_time is not None:
                if isinstance(raw_eval_time, str):
                    try:
                        eval_time = datetime.fromisoformat(raw_eval_time)
                    except Exception:
                        eval_time = None
                elif isinstance(raw_eval_time, datetime):
                    eval_time = raw_eval_time

        # Separate the three identities: prediction_id, causal_final_decision_id, entry_decision_id
        causal_final_id = causal_decision.get("decision_id")
        cand_entry_id = analysis.get("entry_decision_id")
        if cand_entry_id and str(cand_entry_id) != str(causal_final_id):
            entry_evidence_id = str(cand_entry_id)
        else:
            pred_id_part = lineage.get("prediction_id") or "pred"
            entry_evidence_id = f"eed_{pred_id_part}"

        ev_result: Optional[RiskEvaluationResult] = None

        # Helper to build rejection quickly
        def _reject(
            reason: EntryRejectionReason,
            stage: DecisionStage = DecisionStage.NORMALIZATION,
            rejected_action: Optional[TradeAction] = None,
            event_risk_snapshot: Optional[EventRiskDecision] = None,
            event_risk_res: Optional[RiskEvaluationResult] = None,
            **extra_breakdown,
        ) -> EntryDecision:
            act = rejected_action or upstream_action
            if "approved_action" not in extra_breakdown:
                extra_breakdown["approved_action"] = act
            eff_event_risk = event_risk_snapshot if event_risk_snapshot is not None else resolved_event_risk
            eff_event_res = event_risk_res if event_risk_res is not None else ev_result
            bd = DecisionBreakdown(
                decision_stage=stage,
                technical_score=score,
                directional_score=normalized.directional_score,
                signal_strength=normalized.strength,
                signal_action=upstream_action,
                rejection_reason=reason,
                event_risk=eff_event_risk,
                event_risk_result=eff_event_res,
                **extra_breakdown,
            )
            dec = EntryDecision(
                eligible=False,
                action=act,
                rejection_reason=reason,
                final_status=FinalDecisionStatus.REJECTED,
                breakdown=bd,
                sizing=None,
                signal_eligible=False,
                eligibility_reason=reason,
                event_risk=eff_event_risk,
                event_risk_result=eff_event_res,
                **lineage,
            )
            # Only persist canonical entry evidence if snapshot and evaluation result are valid
            if (
                runtime_evidence_eligible()
                and lineage.get("prediction_id")
                and overlay_present
                and eff_event_risk is not None
                and eff_event_res is not None
                and eval_time is not None
            ):
                self._persist_entry_evidence(entry_evidence_id, dec, eff_event_risk, eff_event_res, eval_time, causal_decision)
            elif runtime_evidence_eligible() and lineage.get("prediction_id") and overlay_present and (eff_event_risk is None or eval_time is None):
                # For malformed snapshot or invalid timestamp, record audit event only, never canonical entry evidence
                from btc_scraper.ml_engine.runtime_evidence_store import get_runtime_evidence_store
                store = get_runtime_evidence_store()
                raw_str = json.dumps(candidate_er, default=str) if isinstance(candidate_er, dict) else str(candidate_er)
                raw_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
                store.append_audit_event({
                    "event_type": "INVALID_EVENT_RISK_SNAPSHOT_REJECTED",
                    "prediction_id": str(lineage.get("prediction_id")),
                    "raw_payload_hash": raw_hash,
                    "rejection_reason": reason.value if hasattr(reason, "value") else str(reason),
                })
            return dec

        # Check timestamp when overlay is present: fail-closed if missing, naive, or invalid
        if overlay_present and eval_time is None:
            return _reject(
                EntryRejectionReason.INVALID_EVENT_RISK_SNAPSHOT,
                stage=DecisionStage.ELIGIBILITY,
                rejected_action=TradeAction.NEUTRAL,
                approved_action=TradeAction.NEUTRAL,
                event_risk_snapshot=None,
                event_risk_res=None,
            )

        # Check malformed overlay immediately fail-closed (P0-B)
        if overlay_present and (malformed_event_risk or resolved_event_risk is None):
            return _reject(
                EntryRejectionReason.INVALID_EVENT_RISK_SNAPSHOT,
                stage=DecisionStage.ELIGIBILITY,
                rejected_action=TradeAction.NEUTRAL,
                approved_action=TradeAction.NEUTRAL,
                event_risk_snapshot=None,
                event_risk_res=None,
            )

        # Authoritative Risk & Portfolio Governance (P0-A)
        def _to_clean_dict(val: Any) -> Dict[str, Any]:
            if val is None:
                return {}
            if isinstance(val, dict):
                return val
            if hasattr(val, "to_dict") and callable(val.to_dict):
                return val.to_dict()
            if hasattr(val, "__dict__"):
                return {k: v for k, v in val.__dict__.items() if not k.startswith("_")}
            return {}

        resolved_risk = _to_clean_dict(risk_decision or analysis.get("risk_decision"))
        resolved_portfolio = _to_clean_dict(portfolio_decision or analysis.get("portfolio_decision"))
        # Only fallback to weight in risk object when portfolio_weight is None, preserving explicit 0.0
        if resolved_portfolio.get("portfolio_weight") is None and resolved_risk.get("portfolio_weight") is not None:
            resolved_portfolio["portfolio_weight"] = resolved_risk["portfolio_weight"]

        # 0a. Check authoritative risk result (blocks stale raw analysis from bypassing)
        if resolved_risk:
            is_risk_blocked = bool(resolved_risk.get("risk_blocked", False)) or str(resolved_risk.get("risk_status", "")).upper() in ("UNAVAILABLE", "BLOCKED", "CRITICAL")
            risk_approved = str(resolved_risk.get("approved_action") or "").upper()
            if risk_approved and risk_approved not in ("NEUTRAL", upstream_action.value):
                # Flipping BUY <-> SELL is forbidden; fail-closed to block
                is_risk_blocked = True

            # Raw NEUTRAL/HOLD is non-trade signal, NOT risk manager failure.
            # RISK_MANAGER_BLOCKED is triggered if risk state is explicitly blocked,
            # or if an active trade signal (BUY/SELL) was demoted by risk manager to NEUTRAL/HOLD/BLOCK.
            if is_risk_blocked or (upstream_action in (TradeAction.BUY, TradeAction.SELL) and risk_approved in ("NEUTRAL", "HOLD", "BLOCK")):
                return _reject(
                    EntryRejectionReason.RISK_MANAGER_BLOCKED,
                    stage=DecisionStage.ELIGIBILITY,
                    rejected_action=TradeAction.NEUTRAL,
                    approved_action=TradeAction.NEUTRAL,
                    risk_blocked=True,
                    risk_status=str(resolved_risk.get("risk_status") or "UNAVAILABLE"),
                    risk_multiplier=0.0,
                    portfolio_weight=float(resolved_portfolio.get("portfolio_weight")) if (resolved_portfolio and resolved_portfolio.get("portfolio_weight") is not None) else None,
                )

        # 0b. Check portfolio weight (explicit 0.0 rejects with PORTFOLIO_WEIGHT_ZERO)
        if resolved_portfolio:
            port_w = resolved_portfolio.get("portfolio_weight")
            if port_w is not None and float(port_w) <= 0.0:
                return _reject(
                    EntryRejectionReason.PORTFOLIO_WEIGHT_ZERO,
                    stage=DecisionStage.ELIGIBILITY,
                    rejected_action=TradeAction.NEUTRAL,
                    approved_action=TradeAction.NEUTRAL,
                    portfolio_weight=0.0,
                    portfolio_cap=0.0,
                )

        # 0c. Check Event Risk Policy overlay (P0-B)
        if resolved_event_risk is not None:
            evaluator = RiskPolicyEvaluator()
            ev_result = evaluator.evaluate(
                snapshot=resolved_event_risk,
                intent=OrderIntent.ENTRY,
                requested_multiplier=Decimal("1.0"),
                evaluation_timestamp=eval_time,
            )
            if not ev_result.allowed:
                return _reject(
                    EntryRejectionReason.EVENT_RISK_BLOCKED,
                    stage=DecisionStage.ELIGIBILITY,
                    rejected_action=TradeAction.NEUTRAL,
                    approved_action=TradeAction.NEUTRAL,
                    event_risk_snapshot=resolved_event_risk,
                    event_risk_res=ev_result,
                )

        # Eligible production evidence must be authorized by the one persisted
        # terminal decision, never reconstructed from the technical signal.
        if runtime_evidence_eligible():
            if persisted_final_decision is None:
                return _reject(EntryRejectionReason.MISSING_FINAL_DECISION)
            if presented_final_decision and any(
                str(presented_final_decision.get(field) or "")
                != str(persisted_final_decision.get(field) or "")
                for field in ("decision_id", "prediction_id", "action", "cycle_id")
            ):
                return _reject(
                    EntryRejectionReason.FINAL_DECISION_LINEAGE_MISMATCH
                )
            final_action = str(causal_decision.get("action") or "").upper()
            if bool(causal_decision.get("superseded")):
                return _reject(EntryRejectionReason.FINAL_DECISION_SUPERSEDED)
            if (
                final_action not in {"BUY", "SELL"}
                or str(causal_decision.get("terminal_status") or "").upper() != "TRADE"
                or not bool(causal_decision.get("eligible"))
            ):
                return _reject(EntryRejectionReason.NON_EXECUTABLE_FINAL_DECISION)
            if not causal_decision.get("decision_sha256"):
                return _reject(EntryRejectionReason.FINAL_DECISION_LINEAGE_MISMATCH)
            # The committed final decision is the only executable action.
            # Display labels and pre-final technical signals remain explanatory
            # metadata and may not reconstruct or override this action.
            upstream_action = TradeAction(final_action)
            expected_lineage = {
                "prediction_id": lineage["prediction_id"],
                "cycle_id": lineage["cycle_id"],
                "deployment_id": runtime_deployment_id(),
                "paper_run_id": runtime_paper_run_id(),
            }
            if (
                not expected_lineage["cycle_id"]
                or not expected_lineage["paper_run_id"]
                or expected_lineage["paper_run_id"] != expected_lineage["deployment_id"]
                or any(
                    str(causal_decision.get(field) or "") != str(value or "")
                    for field, value in expected_lineage.items()
                )
            ):
                return _reject(EntryRejectionReason.FINAL_DECISION_LINEAGE_MISMATCH)

        # 0. Economic policy check from causal / final decision
        if (
            causal_decision.get("economic_rejection_reason") == "NO_VIABLE_ECONOMIC_CANDIDATE"
            or causal_decision.get("rejection_reason") == "NO_VIABLE_ECONOMIC_CANDIDATE"
        ):
            return _reject(
                EntryRejectionReason.NO_VIABLE_ECONOMIC_CANDIDATE,
                stage=DecisionStage.EDGE,
            )

        # 1. Coin whitelist
        if coin.upper() not in [c.upper() for c in self.allowed_coins]:
            return _reject(EntryRejectionReason.COIN_NOT_ALLOWED)

        # 2. Action must be BUY or SELL
        if upstream_action not in (TradeAction.BUY, TradeAction.SELL):
            return _reject(EntryRejectionReason.ACTION_DISAGREEMENT)

        # 3. WEAK signal
        if "WEAK" in raw_signal_upper:
            return _reject(EntryRejectionReason.WEAK_SIGNAL)

        # 4. Direction encoding consistency check
        # When the normalized action has enough strength to be non-NEUTRAL,
        # it must agree with the upstream action.
        if (
            normalized.action != TradeAction.NEUTRAL
            and normalized.action != upstream_action
        ):
            return _reject(EntryRejectionReason.DIRECTION_ENCODING_INCONSISTENT)

        # ── Stage: ELIGIBILITY ────────────────────────────────────────────
        meta_prob = self._resolve_meta_probability(sig_score)
        if runtime_evidence_eligible() and persisted_final_decision is not None:
            try:
                meta_prob = float(
                    persisted_final_decision.get("execution_probability")
                    if persisted_final_decision.get("execution_probability") is not None
                    else (
                        1.0 - float(persisted_final_decision.get("meta_probability"))
                        if upstream_action == TradeAction.SELL
                        else float(persisted_final_decision.get("meta_probability"))
                    )
                )
            except (TypeError, ValueError):
                meta_prob = None

        # 5. Meta probability threshold (rejects if None or below threshold)
        if meta_prob is None or meta_prob < self.meta_threshold:
            return _reject(
                EntryRejectionReason.INSUFFICIENT_STATISTICAL_EDGE,
                stage=DecisionStage.ELIGIBILITY,
                meta_probability=meta_prob,
            )

        # 6. Side-agnostic strength threshold
        strength = sig_score.get("strength")
        if strength is None:
            strength = signal_strength_from_score(upstream_action.value, score)
        try:
            strength = float(strength)
        except (TypeError, ValueError):
            strength = signal_strength_from_score(upstream_action.value, score)

        # Causal anomaly conflict gate
        has_causal_anomaly = bool(
            sig_score.get("causal_anomaly_warning")
        ) or ("CAUSAL ANOMALY" in raw_signal_upper)
        meta_high = max(float(self.meta_threshold), 0.60)
        low_signal = max(int(self.score_threshold), 70)
        if (
            has_causal_anomaly
            and meta_prob >= meta_high
            and strength <= low_signal
        ):
            return _reject(
                EntryRejectionReason.CAUSAL_REGIME_VETO,
                stage=DecisionStage.ELIGIBILITY,
                meta_probability=meta_prob,
            )

        if strength < self.score_threshold:
            return _reject(
                EntryRejectionReason.INSUFFICIENT_STATISTICAL_EDGE,
                stage=DecisionStage.ELIGIBILITY,
                meta_probability=meta_prob,
            )

        # 7. RR gate
        rr_ratio = float(tp_sl.get("rr1", 0.0) or 0.0)
        if rr_ratio <= self.min_rr:
            return _reject(
                EntryRejectionReason.RR_BELOW_MINIMUM,
                stage=DecisionStage.ELIGIBILITY,
                meta_probability=meta_prob,
                rr_ratio=rr_ratio,
            )

        # 8. Kelly fraction
        signal_kelly = sig_score.get("kelly_fraction")
        kelly_raw_val: Optional[float] = None
        if signal_kelly is not None:
            try:
                kelly_raw_val = float(signal_kelly)
            except (TypeError, ValueError):
                kelly_raw_val = None

        if self.use_kelly and kelly_raw_val is not None and kelly_raw_val <= 0.0:
            return _reject(
                EntryRejectionReason.NON_POSITIVE_KELLY,
                stage=DecisionStage.ELIGIBILITY,
                meta_probability=meta_prob,
                rr_ratio=rr_ratio,
                kelly_raw=kelly_raw_val,
                kelly_applied=0.0,
            )

        # 9. Circuit Breaker Gate
        cb_ok, cb_reason = self._check_circuit_breaker()
        if not cb_ok:
            return _reject(
                EntryRejectionReason.CIRCUIT_BREAKER,
                stage=DecisionStage.ELIGIBILITY,
                meta_probability=meta_prob,
                rr_ratio=rr_ratio,
                kelly_raw=kelly_raw_val,
            )

        # 10. Existing Position check
        direction = "LONG" if upstream_action == TradeAction.BUY else "SHORT"
        if self._has_open_position(coin, direction):
            return _reject(
                EntryRejectionReason.EXISTING_POSITION,
                stage=DecisionStage.ELIGIBILITY,
                meta_probability=meta_prob,
                rr_ratio=rr_ratio,
                kelly_raw=kelly_raw_val,
            )

        # 11. Correlation Filter Check
        open_positions = exposure_manager.get_open_positions()
        for p in open_positions:
            open_coin = p.get("coin", "").upper()
            if open_coin != coin.upper():
                corr = correlation_engine.get_correlation(open_coin, coin)
                if corr > 0.75:
                    return _reject(
                        EntryRejectionReason.CORRELATION_FILTER,
                        stage=DecisionStage.ELIGIBILITY,
                        meta_probability=meta_prob,
                        rr_ratio=rr_ratio,
                        kelly_raw=kelly_raw_val,
                    )

        # ── Stage: EDGE — canonical EV computation ────────────────────────
        gross_ev: Optional[float] = None
        net_ev: Optional[float] = None
        estimated_cost = (
            self.estimated_fee_ratio
            + self.estimated_slippage_ratio
            + self.estimated_funding_cost
        )

        if rr_ratio > 0:
            gross_ev = meta_prob * rr_ratio - (1.0 - meta_prob)
            net_ev = gross_ev - estimated_cost

            if net_ev <= self.min_expected_edge:
                return _reject(
                    EntryRejectionReason.INSUFFICIENT_STATISTICAL_EDGE,
                    stage=DecisionStage.EDGE,
                    meta_probability=meta_prob,
                    rr_ratio=rr_ratio,
                    gross_expected_value=round(gross_ev, 6),
                    estimated_cost=round(estimated_cost, 6),
                    net_expected_value=round(net_ev, 6),
                    kelly_raw=kelly_raw_val,
                    kelly_applied=kelly_raw_val if kelly_raw_val and kelly_raw_val > 0 else 0.0,
                )

        # ── Stage: SIZING (P0-A) ──────────────────────────────────────────
        entry_price = float(tp_sl.get("entry") or analysis.get("close") or 0.0)
        sl_price = float(tp_sl.get("sl") or 0.0)

        risk_mult = float(resolved_risk.get("risk_multiplier", 1.0)) if resolved_risk else float(sig_score.get("risk_multiplier", 1.0))
        if ev_result is not None:
            event_cap = float(ev_result.approved_multiplier)
            risk_mult = min(risk_mult, event_cap)
        port_weight = float(resolved_portfolio.get("portfolio_weight")) if (resolved_portfolio and resolved_portfolio.get("portfolio_weight") is not None) else None

        sizing: Optional[SizingDecision] = None
        current_bal = current_balance if current_balance and current_balance > 0 else self.account_usdt

        if entry_price > 0.0 and sl_price > 0.0:
            sizing = self.compute_position_size(
                entry_price=entry_price,
                sl_price=sl_price,
                current_balance=current_bal,
                multiplier=risk_mult,
                win_prob=meta_prob,
                rr_ratio=rr_ratio,
                var_cap=var_cap,
                exposure_cap=exposure_cap,
                max_trade_cap=self.max_trade_usdt,
                min_trade_cap=self.min_trade_usdt,
                portfolio_weight=port_weight,
            )
            if sizing.rejected:
                return _reject(
                    sizing.rejection_reason or EntryRejectionReason.INVALID_SIZING_INPUT,
                    stage=DecisionStage.SIZING,
                    meta_probability=meta_prob,
                    rr_ratio=rr_ratio,
                    kelly_raw=kelly_raw_val,
                    risk_pct_applied=sizing.risk_pct,
                    risk_notional=sizing.risk_notional,
                    portfolio_weight=port_weight,
                    risk_multiplier=risk_mult,
                )

        decision_stage = DecisionStage.SIZING if sizing is not None else DecisionStage.ELIGIBILITY
        breakdown = DecisionBreakdown(
            decision_stage=decision_stage,
            technical_score=score,
            directional_score=normalized.directional_score,
            signal_strength=int(strength),
            signal_action=upstream_action,
            approved_action=upstream_action,
            meta_probability=meta_prob,
            rr_ratio=rr_ratio,
            gross_expected_value=round(gross_ev, 6) if gross_ev is not None else None,
            estimated_cost=round(estimated_cost, 6),
            net_expected_value=round(net_ev, 6) if net_ev is not None else None,
            kelly_raw=kelly_raw_val,
            kelly_applied=kelly_raw_val if kelly_raw_val and kelly_raw_val > 0 else None,
            risk_pct_applied=sizing.risk_pct if sizing else None,
            risk_notional=sizing.risk_notional if sizing else None,
            size_before_caps=sizing.raw_notional if sizing else None,
            var_cap=sizing.var_capped if sizing else var_cap,
            exposure_cap=sizing.exposure_capped if sizing else exposure_cap,
            max_trade_cap=sizing.max_trade_capped if sizing else self.max_trade_usdt,
            min_notional=self.min_trade_usdt if sizing else None,
            final_notional=sizing.final_notional if sizing else None,
            risk_multiplier=risk_mult,
            risk_status=str(resolved_risk.get("risk_status") or "OK") if resolved_risk else "OK",
            risk_blocked=False,
            portfolio_weight=port_weight,
            portfolio_cap=sizing.portfolio_capped if sizing else (round(current_bal * port_weight, 2) if port_weight is not None else None),
            event_risk=resolved_event_risk,
            event_risk_result=ev_result,
        )

        dec = EntryDecision(
            eligible=True,
            action=upstream_action,
            rejection_reason=None,
            final_status=FinalDecisionStatus.ELIGIBLE,
            breakdown=breakdown,
            sizing=sizing,
            signal_eligible=True,
            eligibility_reason=None,
            event_risk=resolved_event_risk,
            event_risk_result=ev_result,
            **lineage,
        )
        if (
            runtime_evidence_eligible()
            and lineage.get("prediction_id")
            and overlay_present
            and resolved_event_risk is not None
            and ev_result is not None
            and eval_time is not None
        ):
            self._persist_entry_evidence(entry_evidence_id, dec, resolved_event_risk, ev_result, eval_time, causal_decision)
        return dec

    def _persist_entry_evidence(
        self,
        evidence_entry_id: str,
        decision: EntryDecision,
        event_risk: EventRiskDecision,
        event_result: RiskEvaluationResult,
        eval_time: datetime,
        causal_decision: Dict[str, Any],
    ) -> None:
        """Persist immutable trading entry decision evidence linked to prediction and causal decision.

        Failures raise directly to ensure deterministic, observable persistence without silent dropping.
        """
        from btc_scraper.ml_engine.runtime_evidence_store import get_runtime_evidence_store
        store = get_runtime_evidence_store()
        causal_id = causal_decision.get("decision_id")
        record = {
            "entry_decision_id": evidence_entry_id,
            "prediction_id": str(decision.prediction_id),
            "causal_final_decision_id": str(causal_id) if causal_id else None,
            "eligible": decision.eligible,
            "rejection_reason": decision.rejection_reason.value if decision.rejection_reason else None,
            "action": decision.action.value,
            "event_risk": event_risk.to_dict(),
            "event_risk_result": event_result.to_dict(),
            "evaluation_timestamp": eval_time.isoformat(),
            "risk_state_version": event_risk.risk_state_version,
            "risk_policy_version": event_risk.risk_policy_version,
            "snapshot_payload": event_risk.to_dict(),
            "snapshot_hash": event_result.snapshot_hash,
        }
        store.append_entry_decision_evidence(record)

    def should_trade(
        self,
        coin: str,
        signal: str = None,
        meta_confidence: float = None,
        signal_score: int = None,
        sig_score_obj: Dict[str, Any] | None = None,
        *,
        analysis: Dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """Backward-compatible trade eligibility check.

        New callers should pass ``analysis`` directly.
        Legacy callers passing individual parameters will get a deprecation
        warning; the method builds a synthetic analysis dict and delegates
        to ``build_entry_decision()``.
        """
        if analysis is not None:
            decision = self.build_entry_decision(analysis, coin)
            if decision.eligible:
                return True, "OK"
            reason = decision.rejection_reason
            return False, reason.value if reason else "rejected"

        # Legacy path — build a minimal analysis dict
        warnings.warn(
            "Legacy should_trade() arguments are deprecated; pass analysis= instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        sig_score_obj = sig_score_obj or {}
        legacy_analysis: Dict[str, Any] = {
            "signal": signal or "",
            "signal_score": {
                **sig_score_obj,
                "score": signal_score if signal_score is not None else sig_score_obj.get("score", 50),
                "meta_probability": meta_confidence,
                "meta_confidence": meta_confidence,
            },
            "tp_sl": sig_score_obj.get("tp_sl") or {"rr1": sig_score_obj.get("rr1", 99.0)},
        }
        # Ensure strength is carried over
        if "strength" in sig_score_obj:
            legacy_analysis["signal_score"]["strength"] = sig_score_obj["strength"]
        if "action" in sig_score_obj:
            legacy_analysis["signal_score"]["action"] = sig_score_obj["action"]

        decision = self.build_entry_decision(legacy_analysis, coin)
        if decision.eligible:
            return True, "OK"
        reason = decision.rejection_reason
        return False, reason.value if reason else "rejected"

    def _has_open_position(self, coin: str, direction: str) -> bool:
        """Kiểm tra đã có position cùng coin+direction chưa."""
        try:
            from btc_scraper.trading.position_tracker import get_open_positions
            positions = get_open_positions()
            for p in positions:
                if p.get("coin", "").upper() == coin.upper() and p.get("direction", "").upper() == direction.upper():
                    return True
        except Exception:
            pass
        return False

    # ─── Core: Evaluate & Trade ─────────────────────────────────────────────────

    async def evaluate_and_trade(
        self,
        analysis: Dict[str, Any],
        mtf_analysis: Optional[Dict[str, Any]] = None,
        signals_info: Optional[Any] = None,
        risk_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        """
        Entry point chính. Gọi sau mỗi cycle fetch_and_display().

        Args:
            analysis: dict {coin:exchange → analysis_dict} từ analyze_market()
            mtf_analysis: optional MTF analysis dict
            signals_info: optional signals_info list/dict from multi-agent context
            risk_context: optional risk metrics dict from RiskManagerAgent

        Returns:
            List các lệnh đã được xử lý (để log/notify)
        """
        placed = []

        # 1. Run cycle-level candidate batch for prospective shadow logger (once per cycle)
        self._run_cycle_prospective_shadow_batch(analysis)

        from btc_scraper.trading.decision_types import build_risk_portfolio_map
        risk_portfolio_map = build_risk_portfolio_map(signals_info, risk_context)

        shadow_batch_logs: list[dict] = []
        for key, ana in analysis.items():
            coin = key.split(":")[0].upper()
            rp_item = risk_portfolio_map.get(coin)
            try:
                result = await self._process_signal(
                    key,
                    ana,
                    shadow_batch_collector=shadow_batch_logs,
                    risk_portfolio=rp_item,
                )
                if result:
                    placed.append(result)
            except Exception as e:
                _append_log({
                    "timestamp": datetime.now().isoformat(),
                    "key": key,
                    "mode": self._get_client().mode if False else ("DRY_RUN" if self.dry_run else "LIVE"),
                    "status": "error",
                    "error": str(e),
                })

        if shadow_batch_logs:
            _append_logs_batch(shadow_batch_logs)

        # Optionally evaluate & trade on higher timeframes (MTF)
        try:
            if _env_bool("AUTO_TRADE_MTF_ENABLED", False) and mtf_analysis:
                # TF list from env or default to ['1h']
                tfs_env = os.getenv("AUTO_TRADE_MTF_TFS", "1h").strip()
                tfs = [x.strip() for x in tfs_env.split(",") if x.strip()] if tfs_env else ["1h"]
                from btc_scraper.ml_engine.signal_score import evaluate_signal_score

                for coin, tf_map in mtf_analysis.items():
                    for tf in tfs:
                        tf_ana = tf_map.get(tf)
                        if not tf_ana:
                            continue
                        # Ensure close present
                        tf_ana["close"] = tf_ana.get("close") or tf_ana.get("close_price") or 0.0
                        tf_ana.setdefault("coin", coin)
                        tf_ana.setdefault("symbol", f"{coin}USDT")
                        base_analysis = analysis.get(f"{coin}:Binance") or {}
                        tf_ana.setdefault("cycle_id", base_analysis.get("cycle_id"))
                        try:
                            from btc_scraper.ml_engine.inference_coordinator import get_inference_coordinator
                            from btc_scraper.ml_engine.causal_context_bridge import enhance_signal_with_causal_context
                            tf_ana.setdefault("timeframe", tf)
                            meta_prediction = get_inference_coordinator().predict_once(
                                tf_ana,
                                symbol=coin,
                                timeframe=tf,
                                decision_context="entry",
                                caller_context="auto_trader_mtf",
                            )
                            sig_score = evaluate_signal_score(
                                tf_ana,
                                meta_prediction=meta_prediction.to_dict(),
                            )
                            tf_ana["signal_score"] = sig_score
                            tf_ana.update({
                                field: sig_score[field]
                                for field in (
                                    "signal_id", "prediction_id", "model_version",
                                    "artifact_sha256", "feature_schema_version",
                                    "deployment_id", "decision_context", "caller_context",
                                )
                                if sig_score.get(field) is not None
                            })
                            causal = enhance_signal_with_causal_context(
                                tf_ana,
                                {**tf_ana, **sig_score},
                            )
                            if causal:
                                tf_ana["causal_decision"] = causal
                        except Exception:
                            # fallback: leave as-is
                            pass

                        fake_key = f"{coin}:MTF:{tf}"
                        # B. Đóng bypass ở MTF: Mọi MTF call vào _process_signal phải nhận cùng RiskPortfolioItem của coin.
                        # Nếu risk result bị thiếu trong một cycle đã bật authoritative propagation, không được âm thầm chạy MTF bằng raw signal.
                        mtf_rp_item = risk_portfolio_map.get(coin)
                        if risk_portfolio_map and mtf_rp_item is None:
                            continue

                        try:
                            result = await self._process_signal(
                                fake_key,
                                tf_ana,
                                risk_portfolio=mtf_rp_item,
                            )
                            if result:
                                placed.append(result)
                        except Exception as e:
                            _append_log({
                                "timestamp": datetime.now().isoformat(),
                                "key": fake_key,
                                "mode": "DRY_RUN" if self.dry_run else "TESTNET",
                                "status": "error",
                                "error": str(e),
                            })
        except Exception:
            # Don't fail the whole cycle if MTF trading errors
            pass
        finally:
            client = getattr(self, "_client", None)
            if client is not None:
                await client.close()
                self._client = None

        return placed

    async def _process_signal(
        self,
        key: str,
        ana: Dict,
        shadow_batch_collector: Optional[List[Dict]] = None,
        risk_portfolio: Optional[Any] = None,
    ) -> Optional[Dict]:
        """Xử lý một signal từ một coin."""
        coin = key.split(":")[0].upper()
        signal = ana.get("signal", "")
        sig_score = ana.get("signal_score") or {}
        causal_decision = ana.get("causal_decision") or {}

        # 0. Canonical Paper Economic Policy Fast Path
        # When policy is NO_TRADE_SHADOW, short-circuit before ANY database queries,
        # balance fetching, position queries, VaR calculations, exposure queries,
        # canonical policy cooldown queries, or live market evaluation.
        from btc_scraper.ml_engine.economic_contract import (
            resolve_paper_economic_policy,
            is_paper_shadow_policy,
        )
        policy = resolve_paper_economic_policy(analysis_info=ana)
        if is_paper_shadow_policy(policy, analysis_info=ana):
            log_entry = self._build_shadow_fast_path_log(
                coin, signal, ana, causal_decision, policy
            )
            if shadow_batch_collector is not None:
                shadow_batch_collector.append(log_entry)
            else:
                _append_log(log_entry)
            # Routine shadow skips record local telemetry without synchronous Telegram alerts
            return log_entry

        # Resolve adapter-only account/exposure inputs before the canonical
        # evaluator. Eligibility and sizing themselves execute inside its
        # production EvaluationPipeline exactly once.
        real_balance = self.account_usdt
        if not self.dry_run:
            try:
                engine = self._get_execution_engine()
                adapter = getattr(engine, "_adapter", None)
                if adapter is not None:
                    balance = await adapter.get_usdt_balance()
                    if balance and balance > 0:
                        real_balance = float(balance)
            except Exception:
                real_balance = self.account_usdt

        open_positions = exposure_manager.get_open_positions()
        max_var_size = exposure_manager.calculate_max_size_by_var_limit(
            coin, open_positions, real_balance
        )
        total_pct, coin_pct, sector_pct = exposure_manager.get_portfolio_exposures(
            real_balance
        )
        sector = SECTOR_MAP.get(coin, "OTHER")
        remaining_single = max(
            0.0, (0.15 - coin_pct.get(coin, 0.0)) * real_balance
        )
        remaining_sector = max(
            0.0, (0.35 - sector_pct.get(sector, 0.0)) * real_balance
        )
        remaining_total = max(0.0, (0.75 - total_pct) * real_balance)
        max_exposure_size = min(
            remaining_single, remaining_sector, remaining_total
        )

        from btc_scraper.ml_engine.production_evaluator import evaluate_live_market

        market_evaluation = evaluate_live_market(
            analysis=ana,
            coin=coin,
            trader=self,
            current_balance=real_balance,
            var_cap=max_var_size,
            exposure_cap=max_exposure_size,
            risk_portfolio=risk_portfolio,
        )
        decision = market_evaluation.entry_decision
        ana["market_evaluation_result"] = market_evaluation.result.to_dict()
        final_decision = ana.get("causal_decision") or {}

        # 1. Canonical Execution Policy Evaluation (P4 shared contract)
        from btc_scraper.trading.execution_policy import CANONICAL_POLICY
        can_enter, policy_rejection = CANONICAL_POLICY.can_enter(
            symbol=coin,
            side="BUY" if "BUY" in str(signal).upper() else "SELL",
            current_time=datetime.now(timezone.utc),
            active_positions=open_positions,
            last_exit_timestamps=self.get_last_exit_timestamps(),
            total_equity=real_balance,
            available_cash=real_balance,
        )
        if not can_enter:
            log_entry = self._build_skip_log(
                coin,
                signal,
                f"canonical_policy_{policy_rejection}",
                ana,
                decision,
            )
            _append_log(log_entry)
            self._notify_trade(log_entry)
            return log_entry

        if not decision.eligible:
            # Silently skip low-priority or expected non-trade signals
            silent_reasons = {
                EntryRejectionReason.COIN_NOT_ALLOWED,
                EntryRejectionReason.ACTION_DISAGREEMENT,
                EntryRejectionReason.WEAK_SIGNAL,
                EntryRejectionReason.DIRECTION_ENCODING_INCONSISTENT,
                EntryRejectionReason.EXISTING_POSITION,
            }
            if decision.rejection_reason in silent_reasons:
                return None

            # Skip without logging if it failed meta probability / strength thresholds at eligibility stage
            if (
                decision.rejection_reason == EntryRejectionReason.INSUFFICIENT_STATISTICAL_EDGE
                and decision.breakdown
                and decision.breakdown.decision_stage == DecisionStage.ELIGIBILITY
            ):
                return None

            # Log skip for structural or risk failures (e.g. circuit breaker, EV edge, Kelly, correlation)
            meta_val = decision.breakdown.meta_probability if decision.breakdown else None
            score_val = decision.breakdown.technical_score if decision.breakdown else 50

            reason_str = decision.rejection_reason.value if decision.rejection_reason else "rejected"
            if decision.rejection_reason == EntryRejectionReason.NO_VIABLE_ECONOMIC_CANDIDATE:
                reason_str = "NO_VIABLE_ECONOMIC_CANDIDATE"
            elif decision.rejection_reason == EntryRejectionReason.NON_POSITIVE_KELLY:
                reason_str = "Kelly Fraction <= 0 (signal_score)"
            elif decision.rejection_reason == EntryRejectionReason.CIRCUIT_BREAKER:
                _, reason_str = self._check_circuit_breaker()
            elif decision.rejection_reason == EntryRejectionReason.CORRELATION_FILTER:
                # Match old correlation log format
                reason_str = "correlation_filter"
                open_positions = exposure_manager.get_open_positions()
                for p in open_positions:
                    open_coin = p.get("coin", "").upper()
                    if open_coin != coin:
                        corr = correlation_engine.get_correlation(open_coin, coin)
                        if corr > 0.75:
                            reason_str = f"Tuong quan cao voi vi the dang mo {open_coin} ({corr:.2f} > 0.75)"
                            break

            log_entry = self._build_skip_log(
                coin,
                signal,
                reason_str,
                ana,
                decision,
            )
            paper_policy = resolve_paper_economic_policy(analysis_info=ana)
            log_entry["paper_economic_policy"] = paper_policy
            causal = ana.get("causal_decision") or {}
            log_entry["shadow_action"] = (
                causal.get("shadow_action")
                or (decision.breakdown.signal_action.value if decision.breakdown and hasattr(decision.breakdown, "signal_action") else None)
                or (decision.action.value if decision.action else "HOLD")
            )
            _append_log(log_entry)
            self._notify_trade(log_entry)
            return log_entry

        # 2. Defense-in-depth: Enforce paper economic policy at AutoTrader execution boundary
        paper_economic_policy = resolve_paper_economic_policy(analysis_info=ana)
        if is_paper_shadow_policy(paper_economic_policy, analysis_info=ana):
            log_entry = self._build_skip_log(
                coin,
                signal,
                "NO_VIABLE_ECONOMIC_CANDIDATE",
                ana,
                decision,
            )
            log_entry["paper_economic_policy"] = paper_economic_policy
            log_entry["shadow_action"] = decision.action.value if decision.action else "HOLD"
            _append_log(log_entry)
            self._notify_trade(log_entry)
            return log_entry

        # Decision is eligible, proceed with sizing & execution
        if not self.dry_run:
            from btc_scraper.ml_engine.readiness_gate import live_entry_authorized
            authorized, readiness_reason = live_entry_authorized()
            if not authorized:
                log_entry = self._build_skip_log(coin, signal, readiness_reason, ana, decision)
                log_entry["ml_engine_live_gate"] = "BLOCKED"
                _append_log(log_entry)
                self._notify_trade(log_entry)
                return log_entry

        direction = "LONG" if decision.action == TradeAction.BUY else "SHORT"
        meta_prob = decision.breakdown.meta_probability
        score = decision.breakdown.technical_score
        strength = decision.breakdown.signal_strength
        action = decision.action.value

        # Lấy TP/SL data
        tp_sl = ana.get("tp_sl") or {}
        entry_price = tp_sl.get("entry") or ana.get("close") or 0.0
        sl_price = tp_sl.get("sl") or 0.0
        tp1_price = tp_sl.get("tp1") or 0.0

        rr_ratio = float(tp_sl.get("rr1", 0.0))
        symbol = f"{coin}/USDT"
        sizing_decision = decision.sizing
        if sizing_decision is None:
            raise RuntimeError("canonical evaluator returned eligible decision without sizing")
        # The order boundary consumes one authoritative field. Rejected and
        # non-actionable decisions can never recover exposure through a floor.
        usdt_amount = decision.final_position_size

        # Đặt lệnh qua ExecutionEngine (Phase 1: tất cả write đi qua đây)
        log_mode = "DRY_RUN" if self.dry_run else "TESTNET"
        trade_origin = "paper_mode" if self.dry_run else "live"
        execution_mode = "paper" if self.dry_run else "live"
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "timestamp_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": log_mode,
            "coin": coin,
            "symbol": symbol,
            "direction": direction,
            "signal": signal,
            "meta_confidence": round(float(meta_prob or 0.0), 4),
            "meta_probability": round(float(meta_prob or 0.0), 4),
            "meta_confidence_pct": int(round(float(meta_prob or 0.0) * 100)),
            "signal_score": int(score),
            "signal_strength": float(strength),
            "signal_action": action,
            "kelly_fraction": sig_score.get("kelly_fraction"),
            "b_estimate": sig_score.get("b_estimate"),
            "order_type": "market",
            "entry_price": float(entry_price),
            "sl_price": float(sl_price),
            "tp1_price": float(tp1_price),
            "usdt_amount": usdt_amount,
            "raw_position_size": sizing_decision.raw_position_size,
            "risk_adjusted_size": sizing_decision.risk_adjusted_size,
            "final_position_size": decision.final_position_size,
            "sizing_contract_version": "risk-sizing/v1",
            "gated": decision.gated,
            "account_balance_est": real_balance,
            "order_id": None,
            "status": None,
            "error": None,
            "decision_id": decision.decision_id,
            "signal_eligible": decision.signal_eligible,
            "live_authorized": decision.live_authorized,
            "final_status": decision.final_status.value,
            "decision_breakdown": decision.breakdown.to_dict() if decision.breakdown else None,
            "trade_origin": trade_origin,
            "execution_mode": execution_mode,
            "created_by": "auto_trader",
            "is_paper": trade_origin == "paper_mode",
            "is_manual": False,
            "is_test_record": False,
        }

        try:
            # Lấy candle mới nhất cho coin này (dùng trong execute_live)
            # ana có thể chứa 'candle' hoặc các field giá truc tiếp
            latest_candle = {
                "close": float(entry_price or ana.get("close", 0.0)),
                "open": float(ana.get("open", entry_price or 0.0)),
                "high": float(ana.get("high", entry_price or 0.0)),
                "low": float(ana.get("low", entry_price or 0.0)),
                "volume": float(ana.get("volume", 1.0)),
                "time": datetime.now().isoformat(),
            }
            signal_payload = {
                "coin": coin,
                "signal_raw": signal,
                "signal": signal,
                "id": ana.get("signal_id") or str(int(time.time())),
                "prediction_id": ana.get("prediction_id"),
                "signal_id": ana.get("signal_id") or ana.get("id"),
                "model_version": decision.model_version,
                "model_artifact_sha256": decision.artifact_hash,
                "feature_schema_version": decision.feature_schema_version,
                "deployment_id": decision.deployment_id,
                "paper_run_id": decision.paper_run_id,
                "cycle_id": decision.cycle_id,
                "decision_context": decision.decision_context,
                "caller_context": decision.caller_context,
                "entry_decision_id": decision.decision_id,
                "decision_id": decision.decision_id,
                "final_decision_id": final_decision.get("decision_id"),
                "final_decision_action": final_decision.get("action"),
                "final_decision_prediction_id": final_decision.get("prediction_id"),
                "final_decision_cycle_id": final_decision.get("cycle_id"),
                "final_decision_deployment_id": final_decision.get("deployment_id"),
                "final_decision_paper_run_id": final_decision.get("paper_run_id"),
                "final_decision_eligible": final_decision.get("eligible"),
                "final_decision_terminal_status": final_decision.get("terminal_status"),
                "final_decision_superseded": final_decision.get("superseded", False),
                "canonical_action": decision.action.value,
                "decision_sha256": decision.decision_sha256,
                "idempotency_key": ana.get("idempotency_key"),
                "lifecycle_schema_version": ana.get("lifecycle_schema_version", "trade-lifecycle-v1"),
                "entry_time": datetime.now().isoformat(),
                "latest_event_risk": (
                    decision.breakdown.event_risk
                    if decision.breakdown and decision.breakdown.event_risk
                    else ana.get("event_risk")
                ),
                "event_risk_snapshot_hash": (
                    ana.get("event_risk_snapshot_hash")
                    or (
                        getattr(decision.breakdown.event_risk, "snapshot_hash", None)
                        if decision.breakdown and decision.breakdown.event_risk
                        else None
                    )
                ),
            }

            engine = self._get_execution_engine()

            if self.dry_run:
                # Paper mode: simulate fill using the AutoTrader-computed size.
                rec = engine.submit_paper(signal_payload, latest_candle, notional_usdt=usdt_amount)
            else:
                # Live mode: route through ExchangeAdapter (guarded)
                import asyncio
                rec = asyncio.get_event_loop().run_until_complete(
                    engine.submit_live(signal_payload, latest_candle, usdt_amount)
                )

            log_entry["order_id"] = rec.execution_id
            log_entry["status"] = rec.status
            log_entry["filled_price"] = rec.avg_fill_price or entry_price
            log_entry["execution_id"] = rec.execution_id
            log_entry["guard_action"] = rec.guard_action
            log_entry["expected_slippage_bps"] = rec.expected_slippage_bps
            log_entry["liquidity_score"] = rec.liquidity_score
            log_entry["execution_mode"] = rec.execution_mode
            log_entry["fill_source"] = rec.fill_source
            log_entry["paper_run_id"] = rec.paper_run_id
            log_entry["trade_origin"] = "paper_mode" if rec.execution_mode == "paper" else trade_origin
            log_entry["is_paper"] = log_entry["trade_origin"] == "paper_mode"

            if rec.status == "REJECTED":
                log_entry["status"] = "rejected_by_guard"
                log_entry["reason_skip"] = rec.reason
                _append_log(log_entry)
                self._notify_trade(log_entry)
                return log_entry

            # Sync với position tracker
            try:
                from btc_scraper.trading.position_tracker import add_position
                add_position(
                    coin=coin,
                    entry_price=float(rec.avg_fill_price or entry_price),
                    direction=direction,
                    note=f"[AUTO-{log_entry['mode']}] {signal} | Meta={log_entry['meta_confidence_pct']}%",
                    invested_usdt=usdt_amount,
                    signal_score=sig_score,
                    confidence=float(meta_prob),
                    trade_origin=log_entry["trade_origin"],
                    execution_mode=rec.execution_mode,
                    fill_source=rec.fill_source,
                    paper_run_id=rec.paper_run_id,
                    cycle_id=rec.cycle_id,
                    created_by="auto_trader",
                    order_creator="system",
                    order_channel="paper_runner" if rec.execution_mode == "paper" else "live_runner",
                    prediction_id=rec.prediction_id or ana.get("prediction_id"),
                    signal_id=rec.signal_id,
                    entry_decision_id=rec.entry_decision_id or decision.decision_id,
                    reservation_id=rec.reservation_id,
                    idempotency_key=rec.idempotency_key,
                    client_order_id=rec.client_order_id,
                    exchange_order_id=rec.exchange_order_id,
                    fill_id=rec.fills[0].fill_id if rec.fills else rec.execution_id,
                    position_id=rec.position_id or None,
                    lifecycle_schema_version=rec.lifecycle_schema_version,
                    model_version=decision.model_version,
                    artifact_sha256=decision.artifact_hash,
                    feature_schema_version=decision.feature_schema_version,
                    deployment_id=decision.deployment_id,
                    decision_context=decision.decision_context,
                    caller_context=decision.caller_context,
                    regime_snapshot=ana.get("regime_snapshot") or sig_score.get("regime_snapshot"),
                )
            except Exception:
                pass

            # Record cho circuit breaker (OPEN = chưa biết WIN/LOSS)
            self._record_trade_result("OPEN")

            # Gửi Telegram
            self._notify_trade(log_entry)

        except Exception as e:
            err_str = str(e)
            if "insufficient balance" in err_str.lower() or "margin is insufficient" in err_str.lower():
                log_entry["status"] = "skipped"
                log_entry["reason_skip"] = "Không đủ số dư (Insufficient balance)"
                log_entry["error"] = err_str
            else:
                log_entry["status"] = "error"
                log_entry["error"] = err_str

        if log_entry.get("status") in ("skipped", "rejected_by_guard"):
            self._notify_trade(log_entry)

        _append_log(log_entry)
        return log_entry

    def _run_cycle_prospective_shadow_batch(self, analysis: Dict[str, Any]) -> None:
        """Runs the prospective shadow batch across candidate coins (BTC, ETH, BNB) once per cycle.

        Evaluates unseen closed candles in strict global (timestamp, symbol) order,
        persisting at most one atomic checkpoint transaction per cycle.
        """
        try:
            from btc_scraper.core.candle_store import candle_store

            logger = self._get_shadow_logger()
            batch_candles: dict[str, Any] = {}
            batch_flags: dict[str, Any] = {}

            for coin in logger.spec.universe:
                ana = (
                    analysis.get(coin)
                    or analysis.get(f"{coin}:Binance")
                    or analysis.get(f"{coin}:BINANCE")
                    or {}
                )
                candles = ana.get("_shadow_candles_15m") or ana.get("candles_15m")
                if not isinstance(candles, (list, tuple)):
                    candles = candle_store.get(coin, "15m")

                has_candles = bool(candles and len(candles) > 0)
                batch_candles[coin] = candles if has_candles else []

                causal_decision = ana.get("causal_decision") or {}
                c_fresh = bool(
                    ana.get("candle_store_fresh")
                    if ana.get("candle_store_fresh") is not None
                    else candle_store.is_fresh(coin, "15m")
                )
                macro_q = causal_decision.get("macro_quality_status") or ana.get("macro_quality_status") or "UNKNOWN"
                sent_q = causal_decision.get("sentiment_quality_status") or ana.get("sentiment_quality_status") or "UNKNOWN"
                fund_q = ana.get("funding_quality_status") or "UNKNOWN"
                batch_flags[coin] = {
                    "present": has_candles,
                    "candle_store_fresh": c_fresh,
                    "macro_quality_status": macro_q,
                    "sentiment_quality_status": sent_q,
                    "funding_quality_status": fund_q,
                }

            self._current_cycle_shadow_summaries = logger.observe_cycle_candidate_batch(
                batch_candles,
                data_quality_flags=batch_flags,
            )
        except Exception as e:
            self._current_cycle_shadow_summaries = {
                coin: {"status": "DEGRADED_LOGGER_EXCEPTION", "error": str(e), "symbol": coin}
                for coin in ("BTC", "ETH", "BNB")
            }

    def _build_shadow_fast_path_log(
        self,
        coin: str,
        signal: str,
        ana: Dict,
        causal_decision: Dict,
        policy: str,
    ) -> Dict:
        tp_sl = ana.get("tp_sl") or {}
        sig_score = ana.get("signal_score") or {}
        meta_prob = (
            causal_decision.get("execution_probability")
            if causal_decision.get("execution_probability") is not None
            else (
                causal_decision.get("meta_probability")
                if causal_decision.get("meta_probability") is not None
                else sig_score.get("meta_probability")
            )
        )
        score = sig_score.get("score", 50)
        strength = sig_score.get("strength", 0)
        raw_shadow = (
            causal_decision.get("shadow_action")
            or causal_decision.get("action")
            or sig_score.get("action")
            or ("BUY" if "BUY" in str(signal).upper() else ("SELL" if "SELL" in str(signal).upper() else "HOLD"))
        )
        shadow_action = str(raw_shadow).upper()
        prospective_shadow_meta = None
        if coin in ("BTC", "ETH", "BNB"):
            prospective_shadow_meta = getattr(self, "_current_cycle_shadow_summaries", {}).get(coin)
            if prospective_shadow_meta is None:
                # Fallback for isolated unit tests calling _build_shadow_fast_path_log directly:
                # read-only health lookup without mutating state or persisting
                try:
                    logger = self._get_shadow_logger()
                    prospective_shadow_meta = {
                        "status": "NOT_OBSERVED_IN_CYCLE_BATCH",
                        "symbol": coin,
                        "health": logger.get_health_status(coin),
                    }
                except Exception as e:
                    prospective_shadow_meta = {
                        "status": "DEGRADED_LOGGER_EXCEPTION",
                        "error": str(e),
                        "symbol": coin,
                    }

        return {
            "timestamp": datetime.now().isoformat(),
            "timestamp_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "DRY_RUN" if self.dry_run else "TESTNET",
            "coin": coin,
            "signal": signal,
            "meta_confidence": round(float(meta_prob), 4) if meta_prob is not None else None,
            "meta_probability": round(float(meta_prob), 4) if meta_prob is not None else None,
            "meta_confidence_pct": int(round(float(meta_prob) * 100)) if meta_prob is not None else None,
            "signal_score": int(score) if score is not None else 50,
            "signal_strength": float(strength) if strength is not None else 0.0,
            "kelly_fraction": sig_score.get("kelly_fraction"),
            "b_estimate": sig_score.get("b_estimate"),
            "status": "skipped",
            "reason_skip": "NO_VIABLE_ECONOMIC_CANDIDATE",
            "entry_price": tp_sl.get("entry") or ana.get("close"),
            "sl_price": tp_sl.get("sl"),
            "tp1_price": tp_sl.get("tp1"),
            "decision_id": causal_decision.get("decision_id"),
            "signal_eligible": False,
            "live_authorized": False,
            "final_status": "REJECTED",
            "rejection_reason": "NO_VIABLE_ECONOMIC_CANDIDATE",
            "paper_economic_policy": policy,
            "shadow_action": shadow_action,
            "prospective_shadow": prospective_shadow_meta,
            "decision_breakdown": None,
        }

    def _build_skip_log(
        self,
        coin: str,
        signal: str,
        reason: str,
        ana: Dict,
        decision: EntryDecision,
    ) -> Dict:
        tp_sl = ana.get("tp_sl") or {}
        sig_score = ana.get("signal_score") or {}
        meta_prob = decision.breakdown.meta_probability if decision.breakdown else None
        score = decision.breakdown.technical_score if decision.breakdown else 50
        strength = decision.breakdown.signal_strength if decision.breakdown else 0

        return {
            "timestamp": datetime.now().isoformat(),
            "timestamp_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "DRY_RUN" if self.dry_run else "TESTNET",
            "coin": coin,
            "signal": signal,
            "meta_confidence": round(float(meta_prob or 0.0), 4) if meta_prob is not None else None,
            "meta_probability": round(float(meta_prob or 0.0), 4) if meta_prob is not None else None,
            "meta_confidence_pct": int(round(float(meta_prob or 0.0) * 100)) if meta_prob is not None else None,
            "signal_score": int(score),
            "signal_strength": float(strength),
            "kelly_fraction": sig_score.get("kelly_fraction"),
            "b_estimate": sig_score.get("b_estimate"),
            "status": "skipped",
            "reason_skip": reason,
            "entry_price": tp_sl.get("entry") or ana.get("close"),
            "sl_price": tp_sl.get("sl"),
            "tp1_price": tp_sl.get("tp1"),
            "decision_id": decision.decision_id,
            "signal_eligible": decision.signal_eligible,
            "live_authorized": decision.live_authorized,
            "final_status": decision.final_status.value,
            "rejection_reason": decision.rejection_reason.value if decision.rejection_reason else None,
            "decision_breakdown": decision.breakdown.to_dict() if decision.breakdown else None,
        }

    def _notify_trade(self, entry: Dict) -> None:
        """Gửi Telegram alert về auto-trade."""
        try:
            # Routine paper shadow skips do not send Telegram notifications
            policy = str(entry.get("paper_economic_policy") or "").upper()
            if policy in {"NO_TRADE_SHADOW", "NO_TRADE", "SHADOW"} and entry.get("status") == "skipped":
                return

            from btc_scraper.telegram_bot import send_telegram_message
            mode = entry.get("mode", "DRY_RUN")
            coin = entry.get("coin", "?")
            direction = entry.get("direction", "?")
            signal = entry.get("signal", "?")
            meta_pct = entry.get("meta_confidence_pct", 0)
            score = entry.get("signal_score", 0)
            kelly = entry.get("kelly_fraction")
            try:
                kelly_line = f"Kelly: {float(kelly) * 100:.1f}%\n" if kelly is not None else ""
            except Exception:
                kelly_line = ""
            usdt = entry.get("usdt_amount", 0)
            entry_price = entry.get("entry_price", 0)
            sl = entry.get("sl_price", 0)
            tp1 = entry.get("tp1_price", 0)
            order_id = entry.get("order_id", "?")
            status = entry.get("status", "?")
            err = entry.get("error")
            reason_skip = entry.get("reason_skip")

            if status in ("skipped", "rejected_by_guard"):
                msg = (
                    f"[AUTO-TRADE SKIPPED] {mode}\n"
                    f"Coin: {coin} | {direction}\n"
                    f"Signal: {signal}\n"
                    f"Meta: {meta_pct}% | Score: {score}\n"
                    f"{kelly_line}"
                    f"Entry: ${entry_price:,.4f}\n"
                    f"Ly do skip: {reason_skip or err or 'Khong ro'}"
                )
            elif err:
                msg = (
                    f"[AUTO-TRADE ERROR] {coin}\n"
                    f"Mode: {mode}\n"
                    f"Signal: {signal}\n"
                    f"Loi: {err}"
                )
            else:
                msg = (
                    f"[AUTO-TRADE] {mode}\n"
                    f"Coin: {coin} | {direction}\n"
                    f"Signal: {signal}\n"
                    f"Meta: {meta_pct}% | Score: {score}\n"
                    f"{kelly_line}"
                    f"So tien: ${usdt:.2f} USDT\n"
                    f"Entry: ${entry_price:,.4f}\n"
                    f"SL: ${sl:,.4f}\n"
                    f"TP1: ${tp1:,.4f}\n"
                    f"Order ID: {order_id}\n"
                    f"Trang thai: {status}"
                )
            send_telegram_message(msg, parse_mode=None)
        except Exception:
            pass

    async def close_position_on_exchange(
        self,
        coin: str,
        direction: str,
        invested_usdt: float,
        entry_price: float,
        current_price: float,
    ) -> Optional[Dict]:
        """Close a position via ExecutionEngine.emergency_exit().

        Phase 1 Rule: This is the ONLY external method for exchange writes on close.
        Routes through ExecutionEngine (and thus ExchangeAdapter) — never directly.
        All write calls go through the guard pipeline.
        """
        coin_clean = str(coin or "").upper().removesuffix("USDT")
        self._last_exit_timestamps[coin_clean] = datetime.now(timezone.utc)
        if self.dry_run:
            return {"status": "dry_run", "coin": coin}
        if entry_price <= 0 or invested_usdt <= 0:
            return {"status": "skipped", "reason": "invalid_entry_price_or_invested_usdt"}

        current_val = invested_usdt * (current_price / entry_price)
        try:
            engine = self._get_execution_engine()
            rec = await engine.emergency_exit(
                coin=coin,
                direction=direction,
                invested_usdt=current_val,
                current_price=current_price,
                reason="auto_trade_close",
            )
            return {"status": rec.status, "execution_id": rec.execution_id, "fill_price": rec.avg_fill_price}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def status(self) -> Dict:
        """Trả về trạng thái hiện tại của AutoTrader."""
        state = _load_circuit()
        today = datetime.now().strftime("%Y-%m-%d")
        tripped = state.get("tripped_at")
        tripped_remaining_h = None
        if tripped:
            try:
                elapsed = (datetime.now() - datetime.fromisoformat(tripped)).total_seconds()
                remaining = max(0, 86400 - elapsed)
                tripped_remaining_h = round(remaining / 3600, 1)
            except Exception:
                pass

        logs = _load_log()
        today_logs = [l for l in logs if l.get("timestamp", "").startswith(today)]
        placed_today = [l for l in today_logs if l.get("status") not in ("skipped", "error")]

        # Execution engine stats (sử dụng nếu đã khởi tạo)
        execution_stats = {}
        try:
            if self._execution_engine is not None:
                execution_stats = self._execution_engine.get_stats()
        except Exception:
            pass

        return {
            "mode": "DRY_RUN" if self.dry_run else "TESTNET",
            "meta_threshold": self.meta_threshold,
            "score_threshold": self.score_threshold,
            "risk_pct": self.risk_pct,
            "max_trade_usdt": self.max_trade_usdt,
            "circuit_breaker_n": self.circuit_breaker_n,
            "circuit_tripped": bool(tripped),
            "circuit_tripped_remaining_h": tripped_remaining_h,
            "consecutive_losses": state.get("consecutive_losses", 0),
            "trades_today": state.get("total_trades_today", 0),
            "max_daily_trades": self.max_daily_trades,
            "allowed_coins": self.allowed_coins,
            "total_auto_trades": len([l for l in logs if l.get("status") not in ("skipped", "error")]),
            "execution_engine_stats": execution_stats,
        }


# Singleton instance — import trực tiếp từ module
auto_trader = AutoTrader()
