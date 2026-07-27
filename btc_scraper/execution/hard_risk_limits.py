"""
btc_scraper/execution/hard_risk_limits.py
Phase 6 — Task 6.2: Hard Risk Limits Engine

Enforces hard ceilings per order with stage-aware limits.
Daily loss computed as equity change (realized + unrealized + fees + funding).
Tracks both calendar-day and rolling 24h windows.

Intent types:
    ENTRY            - new position open (all guards apply)
    ADD_POSITION     - add to existing (tighter guards)
    REDUCE_POSITION  - reduce existing (most guards relaxed)
    EXIT             - close position (allowed unless forced halt)
    EMERGENCY_EXIT   - bypass optional guards
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional

from btc_scraper.core.paths import build_execution_data_path

STATE_PATH = build_execution_data_path("risk_state.json")

# ── Intent constants ──────────────────────────────────────────────────────────

class OrderIntent:
    ENTRY = "ENTRY"
    ADD_POSITION = "ADD_POSITION"
    REDUCE_POSITION = "REDUCE_POSITION"
    EXIT = "EXIT"
    EMERGENCY_EXIT = "EMERGENCY_EXIT"

ENTRY_INTENTS = {OrderIntent.ENTRY, OrderIntent.ADD_POSITION}
EXIT_INTENTS = {OrderIntent.REDUCE_POSITION, OrderIntent.EXIT, OrderIntent.EMERGENCY_EXIT}


# ── Stage-specific limit presets ──────────────────────────────────────────────

@dataclass
class RiskLimitSet:
    max_position_usdt: float = 20.0
    max_daily_loss_usdt: float = 5.0
    max_rolling_24h_loss_usdt: float = 7.0
    max_orders_per_day: int = 3
    max_open_positions: int = 1
    max_risk_per_trade_pct: float = 0.25      # % of portfolio equity per trade
    max_single_order_usdt: float = 15.0       # cap per individual order notional

STAGE_LIMITS: Dict[int, RiskLimitSet] = {
    1: RiskLimitSet(
        max_position_usdt=20,
        max_daily_loss_usdt=5,
        max_rolling_24h_loss_usdt=7,
        max_orders_per_day=3,
        max_open_positions=1,
        max_risk_per_trade_pct=0.25,
        max_single_order_usdt=15,
    ),
    2: RiskLimitSet(
        max_position_usdt=50,
        max_daily_loss_usdt=10,
        max_rolling_24h_loss_usdt=14,
        max_orders_per_day=10,
        max_open_positions=2,
        max_risk_per_trade_pct=0.50,
        max_single_order_usdt=30,
    ),
    3: RiskLimitSet(
        max_position_usdt=100,
        max_daily_loss_usdt=20,
        max_rolling_24h_loss_usdt=28,
        max_orders_per_day=50,
        max_open_positions=3,
        max_risk_per_trade_pct=1.0,
        max_single_order_usdt=80,
    ),
}


@dataclass
class RiskDecision:
    allowed: bool
    reason: str = ""
    severity: str = "INFO"         # INFO | WARNING | CRITICAL


@dataclass
class _DayAccumulator:
    """Calendar-day accumulator (resets at UTC midnight)."""
    calendar_date: str = ""     # ISO date YYYY-MM-DD
    order_count: int = 0
    realized_pnl: float = 0.0
    fees: float = 0.0
    funding: float = 0.0


@dataclass
class _RollingEntry:
    timestamp: float
    equity_change: float


class HardRiskLimits:
    """
    Pre-trade hard ceiling enforcer.

    Call `evaluate(...)` before each order submission.
    Call `record_fill(...)` after each confirmed fill.
    Call `update_unrealized(...)` periodically from the monitor.
    """

    def __init__(self, stage: int = 1, limits: Optional[RiskLimitSet] = None):
        self._stage = stage
        self._limits: RiskLimitSet = limits or STAGE_LIMITS.get(stage, STAGE_LIMITS[1])
        self._lock = RLock()

        # Calendar-day accumulator
        self._day = _DayAccumulator()

        # Rolling 24h window: list of (timestamp, equity_change)
        self._rolling: list[_RollingEntry] = []

        # Current unrealized PnL (updated externally)
        self._unrealized_pnl: float = 0.0

        self._load_state()

    # ── State persistence ─────────────────────────────────────────────────────

    def _load_state(self) -> None:
        try:
            if STATE_PATH.exists():
                raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                d = raw.get("day", {})
                self._day = _DayAccumulator(**{k: v for k, v in d.items() if k in _DayAccumulator.__dataclass_fields__})
                self._rolling = [_RollingEntry(**e) for e in raw.get("rolling", [])]
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "stage": self._stage,
                "day": asdict(self._day),
                "rolling": [asdict(e) for e in self._rolling],
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            tmp = STATE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(STATE_PATH)
        except Exception:
            pass

    # ── Day reset ─────────────────────────────────────────────────────────────

    def _ensure_day_reset(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._day.calendar_date != today:
            self._day = _DayAccumulator(calendar_date=today)
            self._save_state()

    # ── Rolling window maintenance ────────────────────────────────────────────

    def _prune_rolling(self) -> None:
        cutoff = time.time() - 86400  # 24h ago
        self._rolling = [e for e in self._rolling if e.timestamp >= cutoff]

    def _rolling_24h_loss(self) -> float:
        self._prune_rolling()
        total = sum(e.equity_change for e in self._rolling)
        return min(total, 0.0)  # only negative portion matters

    # ── Equity loss calculation ───────────────────────────────────────────────

    def _calendar_equity_loss(self) -> float:
        """Realized + unrealized + fees + funding for today (negative = loss)."""
        self._ensure_day_reset()
        return (
            self._day.realized_pnl
            + self._unrealized_pnl
            - self._day.fees
            - self._day.funding
        )

    # ── External update API ───────────────────────────────────────────────────

    def update_unrealized(self, unrealized_pnl: float) -> None:
        with self._lock:
            self._unrealized_pnl = unrealized_pnl

    def record_fill(
        self,
        realized_pnl: float = 0.0,
        fee: float = 0.0,
        funding: float = 0.0,
    ) -> None:
        with self._lock:
            self._ensure_day_reset()
            self._day.order_count += 1
            self._day.realized_pnl += realized_pnl
            self._day.fees += fee
            self._day.funding += funding

            equity_change = realized_pnl - fee - funding
            self._rolling.append(_RollingEntry(timestamp=time.time(), equity_change=equity_change))
            self._prune_rolling()
            self._save_state()

    def update_stage(self, stage: int) -> None:
        with self._lock:
            self._stage = stage
            self._limits = STAGE_LIMITS.get(stage, STAGE_LIMITS[1])

    # ── Main evaluation ───────────────────────────────────────────────────────

    def evaluate(
        self,
        intent: str,
        order_notional_usdt: float,
        open_positions_count: int,
        portfolio_equity_usdt: float = 0.0,
    ) -> RiskDecision:
        """
        Evaluate whether a new order is allowed under current risk limits.

        EXIT and EMERGENCY_EXIT intents bypass most limits.
        REDUCE_POSITION allows most checks but respects hard emergency stops.
        """
        with self._lock:
            self._ensure_day_reset()

            # Emergency exit always allowed
            if intent == OrderIntent.EMERGENCY_EXIT:
                return RiskDecision(allowed=True, reason="emergency_exit_bypass")

            # Exits and reduces always allowed (don't block from closing)
            if intent in EXIT_INTENTS:
                return RiskDecision(allowed=True, reason="exit_intent_allowed")

            # ── From here on: ENTRY and ADD_POSITION only ──────────────────

            # 1. Calendar-day equity loss check
            cal_loss = self._calendar_equity_loss()
            if cal_loss <= -self._limits.max_daily_loss_usdt:
                return RiskDecision(
                    allowed=False,
                    reason=f"calendar_daily_loss_breach: {cal_loss:.2f} USDT <= -{self._limits.max_daily_loss_usdt}",
                    severity="CRITICAL",
                )

            # 2. Rolling 24h equity loss check
            rolling_loss = self._rolling_24h_loss()
            if rolling_loss <= -self._limits.max_rolling_24h_loss_usdt:
                return RiskDecision(
                    allowed=False,
                    reason=f"rolling_24h_loss_breach: {rolling_loss:.2f} USDT <= -{self._limits.max_rolling_24h_loss_usdt}",
                    severity="CRITICAL",
                )

            # 3. Orders per day
            if self._day.order_count >= self._limits.max_orders_per_day:
                return RiskDecision(
                    allowed=False,
                    reason=f"daily_order_count_reached: {self._day.order_count} >= {self._limits.max_orders_per_day}",
                    severity="WARNING",
                )

            # 4. Max open positions
            if open_positions_count >= self._limits.max_open_positions:
                return RiskDecision(
                    allowed=False,
                    reason=f"max_open_positions_reached: {open_positions_count} >= {self._limits.max_open_positions}",
                    severity="WARNING",
                )

            # 5. Max single order notional
            if order_notional_usdt > self._limits.max_single_order_usdt:
                return RiskDecision(
                    allowed=False,
                    reason=f"order_too_large: {order_notional_usdt:.2f} > {self._limits.max_single_order_usdt} USDT",
                    severity="WARNING",
                )

            # 6. Max position size
            if order_notional_usdt > self._limits.max_position_usdt:
                return RiskDecision(
                    allowed=False,
                    reason=f"position_too_large: {order_notional_usdt:.2f} > {self._limits.max_position_usdt} USDT",
                    severity="WARNING",
                )

            # 7. Per-trade risk % (only if equity is provided)
            if portfolio_equity_usdt > 0 and self._limits.max_risk_per_trade_pct > 0:
                risk_pct = order_notional_usdt / portfolio_equity_usdt * 100
                if risk_pct > self._limits.max_risk_per_trade_pct:
                    return RiskDecision(
                        allowed=False,
                        reason=f"risk_per_trade_exceeded: {risk_pct:.2f}% > {self._limits.max_risk_per_trade_pct}%",
                        severity="WARNING",
                    )

            return RiskDecision(allowed=True, reason="all_limits_ok", severity="INFO")

    def get_state_summary(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_day_reset()
            return {
                "stage": self._stage,
                "calendar_date": self._day.calendar_date,
                "order_count_today": self._day.order_count,
                "calendar_equity_loss": round(self._calendar_equity_loss(), 4),
                "rolling_24h_loss": round(self._rolling_24h_loss(), 4),
                "unrealized_pnl": round(self._unrealized_pnl, 4),
                "limits": asdict(self._limits),
            }
