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
    AUTO_TRADE_COINS=                     # Để trống = tất cả COINS
"""
from __future__ import annotations

import json
import os
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path
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
)
from btc_scraper.core.paths import build_logs_path

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
    data = _load_log()
    data.append(entry)
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

    def __init__(self):
        self._execution_engine = None  # Lazy init ExecutionEngine with WriteAdapter

    @property
    def dry_run(self) -> bool:
        return _env_bool("AUTO_TRADE_DRY_RUN", True)

    @property
    def meta_threshold(self) -> float:
        return _env_float("AUTO_TRADE_META_THRESHOLD", 0.85)

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
        """List coins cho phép auto-trade. Để trống = tất cả."""
        from btc_scraper.core.config import COINS
        return _env_list("AUTO_TRADE_COINS", list(COINS))

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
                rejected=True,
                rejection_reason=EntryRejectionReason.INVALID_SIZING_INPUT,
            )

        balance = current_balance if current_balance and current_balance > 0 else self.account_usdt

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
                    rejected=True,
                    rejection_reason=EntryRejectionReason.NON_POSITIVE_KELLY,
                )
            kelly_risk_pct = kelly_f * self.kelly_fraction * 100.0
            kelly_risk_notional = balance * kelly_risk_pct / 100.0
            kelly_adjusted = kelly_risk_notional / sl_distance_pct
            notional = min(notional, kelly_adjusted)

        # 5. VaR Cap
        var_capped = None
        if var_cap is not None:
            var_capped = var_cap
            notional = min(notional, var_capped)

        # 6. Exposure Cap
        exposure_capped = None
        if exposure_cap is not None:
            exposure_capped = exposure_cap
            notional = min(notional, exposure_capped)

        # 7. Hard Max Cap
        max_trade_capped = None
        max_limit = max_trade_cap if max_trade_cap is not None else self.max_trade_usdt
        if notional > max_limit:
            max_trade_capped = max_limit
            notional = min(notional, max_limit)

        # 8. Min Notional Validation
        min_limit = min_trade_cap if min_trade_cap is not None else self.min_trade_usdt
        allowed_risk = risk_notional
        if kelly_f is not None:
            kelly_risk_pct = kelly_f * self.kelly_fraction * 100.0
            allowed_risk = min(allowed_risk, balance * kelly_risk_pct / 100.0)

        if notional < min_limit:
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
                    var_capped=var_capped,
                    exposure_capped=exposure_capped,
                    max_trade_capped=max_trade_capped,
                    final_notional=0.0,
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
            var_capped=var_capped,
            exposure_capped=exposure_capped,
            max_trade_capped=max_trade_capped,
            final_notional=round(notional, 2),
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

        # Helper to build rejection quickly
        def _reject(
            reason: EntryRejectionReason,
            stage: DecisionStage = DecisionStage.NORMALIZATION,
            **extra_breakdown,
        ) -> EntryDecision:
            bd = DecisionBreakdown(
                decision_stage=stage,
                technical_score=score,
                directional_score=normalized.directional_score,
                signal_strength=normalized.strength,
                signal_action=upstream_action,
                rejection_reason=reason,
                **extra_breakdown,
            )
            return EntryDecision(
                eligible=False,
                action=upstream_action,
                rejection_reason=reason,
                final_status=FinalDecisionStatus.REJECTED,
                breakdown=bd,
                sizing=None,
                signal_eligible=False,
                eligibility_reason=reason,
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

        # ── Build successful breakdown (SIZING stage will be added by caller) ──
        breakdown = DecisionBreakdown(
            decision_stage=DecisionStage.ELIGIBILITY,
            technical_score=score,
            directional_score=normalized.directional_score,
            signal_strength=int(strength),
            signal_action=upstream_action,
            meta_probability=meta_prob,
            rr_ratio=rr_ratio,
            gross_expected_value=round(gross_ev, 6) if gross_ev is not None else None,
            estimated_cost=round(estimated_cost, 6),
            net_expected_value=round(net_ev, 6) if net_ev is not None else None,
            kelly_raw=kelly_raw_val,
            kelly_applied=kelly_raw_val if kelly_raw_val and kelly_raw_val > 0 else None,
        )

        return EntryDecision(
            eligible=True,
            action=upstream_action,
            rejection_reason=None,
            final_status=FinalDecisionStatus.ELIGIBLE,
            breakdown=breakdown,
            sizing=None,
            signal_eligible=True,
            eligibility_reason=None,
        )

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

    async def evaluate_and_trade(self, analysis: Dict[str, Any], mtf_analysis: Optional[Dict[str, Any]] = None) -> List[Dict]:
        """
        Entry point chính. Gọi sau mỗi cycle fetch_and_display().

        Args:
            analysis: dict {coin:exchange → analysis_dict} từ analyze_market()

        Returns:
            List các lệnh đã được xử lý (để log/notify)
        """
        placed = []

        for key, ana in analysis.items():
            try:
                result = await self._process_signal(key, ana)
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
                        try:
                            sig_score = evaluate_signal_score(tf_ana)
                            tf_ana["signal_score"] = sig_score
                        except Exception:
                            # fallback: leave as-is
                            pass

                        fake_key = f"{coin}:MTF:{tf}"
                        try:
                            result = await self._process_signal(fake_key, tf_ana)
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

    async def _process_signal(self, key: str, ana: Dict) -> Optional[Dict]:
        """Xử lý một signal từ một coin."""
        coin = key.split(":")[0].upper()
        signal = ana.get("signal", "")
        sig_score = ana.get("signal_score") or {}

        # 1. Evaluate canonical entry decision
        decision = self.build_entry_decision(ana, coin)

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
            if decision.rejection_reason == EntryRejectionReason.NON_POSITIVE_KELLY:
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

        # Tính position size
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

        rr_ratio = float(tp_sl.get("rr1", 0.0))

        # --- 2. Portfolio VaR Sizing Scale Down ---
        symbol = f"{coin}/USDT"
        open_positions = exposure_manager.get_open_positions()
        max_var_size = exposure_manager.calculate_max_size_by_var_limit(coin, open_positions, real_balance)

        # --- 3. Exposure Caps (Total, Sector, Single) Scale Down ---
        total_pct, coin_pct, sector_pct = exposure_manager.get_portfolio_exposures(real_balance)
        sector = SECTOR_MAP.get(coin, "OTHER")
        remaining_single = max(0.0, (0.15 - coin_pct.get(coin, 0.0)) * real_balance)
        remaining_sector = max(0.0, (0.35 - sector_pct.get(sector, 0.0)) * real_balance)
        remaining_total = max(0.0, (0.75 - total_pct) * real_balance)
        max_exposure_size = min(remaining_single, remaining_sector, remaining_total)

        sizing_decision = self.compute_position_size(
            entry_price=float(entry_price),
            sl_price=float(sl_price),
            current_balance=real_balance,
            multiplier=float(sig_score.get("position_size", 1.0)),
            win_prob=float(meta_prob or 0.5),
            rr_ratio=rr_ratio,
            var_cap=max_var_size,
            exposure_cap=max_exposure_size,
            max_trade_cap=self.max_trade_usdt,
            min_trade_cap=self.min_trade_usdt,
        )

        if sizing_decision.rejected:
            import dataclasses
            decision = dataclasses.replace(
                decision,
                eligible=False,
                rejection_reason=sizing_decision.rejection_reason,
                sizing=sizing_decision,
            )
            
            reason_str = "sizing_rejected"
            if sizing_decision.rejection_reason == EntryRejectionReason.NON_POSITIVE_KELLY:
                reason_str = "Kelly Fraction <= 0 (Ky vong am)"
            elif sizing_decision.rejection_reason == EntryRejectionReason.INVALID_SIZING_INPUT:
                reason_str = f"Size lenh sau co gian {sizing_decision.final_notional:.2f} USDT < min {self.min_trade_usdt:.2f} USDT"
            
            log_entry = self._build_skip_log(
                coin,
                signal,
                reason_str,
                ana,
                decision,
            )
            _append_log(log_entry)
            self._notify_trade(log_entry)
            return log_entry

        usdt_amount = sizing_decision.final_notional
        import dataclasses
        decision = dataclasses.replace(decision, sizing=sizing_decision)

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
                "entry_decision_id": decision.decision_id,
                "decision_id": decision.decision_id,
                "idempotency_key": ana.get("idempotency_key"),
                "lifecycle_schema_version": ana.get("lifecycle_schema_version", "trade-lifecycle-v1"),
                "entry_time": datetime.now().isoformat(),
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
