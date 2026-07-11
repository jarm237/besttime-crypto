"""
btc_scraper/execution/live_execution_guard.py
Phase 6 — Task 6.4: Central Live Execution Guard

THE central validation checkpoint. ALL live orders MUST pass through this guard.
No order should be submitted to ExchangeAdapter without calling validate() first.

Sequential validation chain:
    1. Phase5 live gate (per-order, cache TTL 30s)
    2. Live mode enabled flag
    3. Kill-switch state
    4. Rollout stage gate (symbol / position count)
    5. Hard risk limits (respects order intent)
    6. System health check (model, data, DB)
    7. Execution risk monitor (spread, slippage, latency, liquidity)

Entry point:
    ExecutionEngine.submit_live(signal)
        → LiveExecutionGuard.validate(order_context)
        → ExchangeAdapter.submit(order)

Exit/Reduce intents skip most guards (they must be able to close).
EMERGENCY_EXIT bypasses all optional guards.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional

from .hard_risk_limits import HardRiskLimits, OrderIntent, RiskDecision
from .kill_switch import KillSwitch, KSState
from .live_audit_log import LiveAuditLog
from .execution_risk_monitor import ExecutionRiskMonitor, GuardAction

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
PHASE5_REPORT_PATH = BASE_DIR / "data" / "execution" / "reports" / "phase5_report_latest.json"
LIVE_MODE_FLAG_PATH = BASE_DIR / "data" / "live_mode_enabled.json"
PHASE5_GATE_CACHE_TTL_SECONDS = 30


@dataclass
class GuardResult:
    allowed: bool
    reason: str
    severity: str = "INFO"          # INFO | WARNING | CRITICAL
    blocked_by: Optional[str] = None  # which check blocked the order
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "severity": self.severity,
            "blocked_by": self.blocked_by,
            "checked_at": self.checked_at,
        }


@dataclass
class OrderContext:
    """Context object describing an order to be evaluated."""
    symbol: str
    intent: str                    # OrderIntent constant
    notional_usdt: float
    open_positions_count: int = 0
    portfolio_equity_usdt: float = 0.0
    # Execution risk inputs
    spread_bps: float = 0.0
    expected_slippage_bps: float = 0.0
    liquidity_score: float = 1.0
    latency_ms: int = 0
    # Rollout stage snapshot (for logging)
    current_stage: int = 1


class LiveExecutionGuard:
    """
    Central enforcement gate for all live order submissions.

    Must be instantiated once per application and shared.
    Call validate(order_context) before any ExchangeAdapter.submit().
    """

    def __init__(
        self,
        kill_switch: Optional[KillSwitch] = None,
        hard_risk_limits: Optional[HardRiskLimits] = None,
        audit_log: Optional[LiveAuditLog] = None,
        execution_risk_monitor: Optional[ExecutionRiskMonitor] = None,
        phase5_report_path: Optional[str] = None,
        live_mode_flag_path: Optional[str] = None,
    ):
        self._kill_switch = kill_switch or KillSwitch()
        self._risk_limits = hard_risk_limits or HardRiskLimits(stage=1)
        self._audit = audit_log or LiveAuditLog()
        self._exec_risk = execution_risk_monitor or ExecutionRiskMonitor()
        self._phase5_path = Path(phase5_report_path) if phase5_report_path else PHASE5_REPORT_PATH
        self._live_mode_flag_path = Path(live_mode_flag_path) if live_mode_flag_path else LIVE_MODE_FLAG_PATH


        self._lock = RLock()
        # Phase5 gate cache
        self._phase5_gate_cache: Optional[bool] = None
        self._phase5_gate_cache_at: float = 0.0

        # System health cache
        self._health_cache: Dict[str, Any] = {}
        self._health_cache_at: float = 0.0
        self._health_ttl = 15.0  # 15 seconds

    # ── Individual checks ─────────────────────────────────────────────────────

    def _check_phase5_gate(self, intent: str) -> Optional[GuardResult]:
        """
        Verify Phase5 live gate is open.
        Exits are allowed even if gate is closed.
        Uses TTL cache to avoid repeated disk reads.
        """
        if intent in (OrderIntent.EXIT, OrderIntent.EMERGENCY_EXIT, OrderIntent.REDUCE_POSITION):
            return None  # exits always pass this check

        with self._lock:
            now = time.time()
            if now - self._phase5_gate_cache_at < PHASE5_GATE_CACHE_TTL_SECONDS and self._phase5_gate_cache is not None:
                gate_open = self._phase5_gate_cache
            else:
                gate_open = self._read_phase5_gate()
                self._phase5_gate_cache = gate_open
                self._phase5_gate_cache_at = now

        if not gate_open:
            return GuardResult(
                allowed=False,
                reason="phase5_live_gate_closed — real paper fills threshold not yet met",
                severity="CRITICAL",
                blocked_by="phase5_gate",
            )
        return None

    def _read_phase5_gate(self) -> bool:
        try:
            if not self._phase5_path.exists():
                return False
            report = json.loads(self._phase5_path.read_text(encoding="utf-8"))
            return bool(report.get("live_readiness_gate", {}).get("passed", False))
        except Exception:
            return False

    def _check_live_mode(self) -> Optional[GuardResult]:
        try:
            if self._live_mode_flag_path.exists():
                flag = json.loads(self._live_mode_flag_path.read_text(encoding="utf-8"))
                if not flag.get("enabled", False):
                    return GuardResult(
                        allowed=False, reason="live_mode_disabled (flag file)",
                        severity="CRITICAL", blocked_by="live_mode_flag"
                    )
            else:
                return GuardResult(
                    allowed=False, reason="live_mode not enabled — flag file missing",
                    severity="CRITICAL", blocked_by="live_mode_flag"
                )
        except Exception as exc:
            return GuardResult(
                allowed=False, reason=f"live_mode_flag read error: {exc}",
                severity="CRITICAL", blocked_by="live_mode_flag"
            )
        return None


    def _check_kill_switch(self, intent: str) -> Optional[GuardResult]:
        state = self._kill_switch.state
        if state == KSState.ARMED:
            return None
        # Exits are always allowed
        if intent in (OrderIntent.EXIT, OrderIntent.EMERGENCY_EXIT, OrderIntent.REDUCE_POSITION):
            return None
        return GuardResult(
            allowed=False,
            reason=f"kill_switch_state={state} — entries blocked",
            severity="CRITICAL",
            blocked_by="kill_switch",
        )

    def _check_rollout_stage(self, ctx: OrderContext) -> Optional[GuardResult]:
        """
        Basic rollout gate: Stage 1 enforces 1 symbol at a time by convention.
        Detailed enforcement is delegated to HardRiskLimits.
        """
        if ctx.intent in (OrderIntent.EXIT, OrderIntent.EMERGENCY_EXIT, OrderIntent.REDUCE_POSITION):
            return None
        if ctx.current_stage == 1 and ctx.open_positions_count >= 1:
            return GuardResult(
                allowed=False,
                reason=f"rollout_stage_1: already has {ctx.open_positions_count} open position(s), max=1",
                severity="WARNING",
                blocked_by="rollout_stage",
            )
        return None

    def _check_hard_risk(self, ctx: OrderContext) -> Optional[GuardResult]:
        decision: RiskDecision = self._risk_limits.evaluate(
            intent=ctx.intent,
            order_notional_usdt=ctx.notional_usdt,
            open_positions_count=ctx.open_positions_count,
            portfolio_equity_usdt=ctx.portfolio_equity_usdt,
        )
        if not decision.allowed:
            return GuardResult(
                allowed=False,
                reason=decision.reason,
                severity=decision.severity,
                blocked_by="hard_risk_limits",
            )
        return None

    def _check_system_health(self) -> Optional[GuardResult]:
        """
        Check model, data, DB health via cached snapshot.
        Only blocks ENTRY-type orders.
        """
        now = time.time()
        if now - self._health_cache_at < self._health_ttl and self._health_cache:
            health = self._health_cache
        else:
            health = self._read_health()
            self._health_cache = health
            self._health_cache_at = now

        if not health.get("ready", True):
            failing = [k for k, v in health.get("dependencies", {}).items() if not v]
            return GuardResult(
                allowed=False,
                reason=f"system_health_check_failed: {failing}",
                severity="CRITICAL",
                blocked_by="system_health",
            )
        return None

    def _read_health(self) -> Dict[str, Any]:
        try:
            monitor_snap = BASE_DIR / "data" / "execution" / "live_monitor_snapshot.json"
            if monitor_snap.exists():
                snap = json.loads(monitor_snap.read_text(encoding="utf-8"))
                return snap.get("system_health", {"ready": True})
        except Exception:
            pass
        return {"ready": True}

    def _check_execution_risk(self, ctx: OrderContext) -> Optional[GuardResult]:
        if ctx.intent in (OrderIntent.EXIT, OrderIntent.EMERGENCY_EXIT):
            return None  # exits bypass execution risk checks
        decision = self._exec_risk.evaluate(
            spread_bps=ctx.spread_bps,
            expected_slippage_bps=ctx.expected_slippage_bps,
            liquidity_score=ctx.liquidity_score,
            order_notional_usdt=ctx.notional_usdt,
            max_safe_order_size_usdt=ctx.notional_usdt * 2,  # generous; hard limits already applied
            latency_ms=ctx.latency_ms,
        )
        if decision.action == GuardAction.REJECT:
            return GuardResult(
                allowed=False,
                reason=f"execution_risk: {decision.reason}",
                severity="WARNING",
                blocked_by="execution_risk",
            )
        return None

    # ── Main validation chain ─────────────────────────────────────────────────

    def validate(self, ctx: OrderContext) -> GuardResult:
        """
        Run the full sequential validation chain.
        Returns immediately on first blocking check.

        Order:
            1. Phase5 gate (entries only, cached)
            2. Live mode flag
            3. Kill-switch
            4. Rollout stage
            5. Hard risk limits
            6. System health
            7. Execution risk
        """
        is_emergency = ctx.intent == OrderIntent.EMERGENCY_EXIT

        # EMERGENCY_EXIT bypasses everything except kill-switch state check
        if not is_emergency:
            checks = [
                ("phase5_gate",     lambda: self._check_phase5_gate(ctx.intent)),
                ("live_mode",       self._check_live_mode),
                ("kill_switch",     lambda: self._check_kill_switch(ctx.intent)),
                ("rollout_stage",   lambda: self._check_rollout_stage(ctx)),
                ("hard_risk",       lambda: self._check_hard_risk(ctx)),
                ("system_health",   self._check_system_health),
                ("execution_risk",  lambda: self._check_execution_risk(ctx)),
            ]
        else:
            # Emergency exit only checks kill-switch for CLOSE_ALL propagation
            checks = [
                ("kill_switch", lambda: self._check_kill_switch(ctx.intent)),
            ]

        for name, check_fn in checks:
            try:
                result = check_fn()
                if result is not None and not result.allowed:
                    self._audit.log_order_decision(
                        allowed=False,
                        reason=result.reason,
                        symbol=ctx.symbol,
                        intent=ctx.intent,
                        notional=ctx.notional_usdt,
                    )
                    logger.warning(
                        f"[LiveGuard] BLOCKED {ctx.symbol} ({ctx.intent}): [{name}] {result.reason}"
                    )
                    return result
            except Exception as exc:
                logger.error(f"[LiveGuard] Check {name} raised: {exc}")
                # Fail safe — block on unexpected error in guards
                result = GuardResult(
                    allowed=False,
                    reason=f"guard_error in {name}: {exc}",
                    severity="CRITICAL",
                    blocked_by=name,
                )
                self._audit.log_order_decision(
                    allowed=False,
                    reason=result.reason,
                    symbol=ctx.symbol,
                    intent=ctx.intent,
                    notional=ctx.notional_usdt,
                )
                return result

        final = GuardResult(allowed=True, reason="all_guards_passed", severity="INFO")
        self._audit.log_order_decision(
            allowed=True,
            reason="all_guards_passed",
            symbol=ctx.symbol,
            intent=ctx.intent,
            notional=ctx.notional_usdt,
        )
        return final
