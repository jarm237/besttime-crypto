"""
btc_scraper/execution/execution_risk_monitor.py
Phase 10 – Sprint 10.6: Execution Risk Monitor

Pre-trade guard implementing all checks from plan § 11.
Returns a GuardDecision that the ExecutionEngine uses to
PASS, REDUCE, or REJECT an order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class GuardAction:
    PASS = "PASS"
    REDUCE = "REDUCE"
    REJECT = "REJECT"


@dataclass
class GuardDecision:
    action: str = GuardAction.PASS
    reason: str = ""
    adjusted_qty_usdt: Optional[float] = None   # set when action=REDUCE
    adjusted_qty_asset: Optional[float] = None


class ExecutionRiskMonitor:
    """
    Pre-trade execution guard.

    Checks:
        1. Spread       → reject if too wide
        2. Slippage     → reject if expected slippage is too high
        3. Liquidity    → reject or reduce size
        4. Latency      → reject if exchange response is too slow
        5. Order size   → reduce if exceeds max_safe_order_size
    """

    def __init__(self, config: Dict[str, Any] = None):
        cfg = config or {}
        self.max_spread_bps: float = cfg.get("max_spread_bps", 20.0)
        self.max_slippage_bps: float = cfg.get("max_slippage_bps", 30.0)
        self.min_liquidity_score: float = cfg.get("min_liquidity_score", 0.4)
        self.max_latency_ms: int = cfg.get("max_latency_ms", 1500)
        self.max_participation_rate: float = cfg.get("max_participation_rate", 0.02)

    # ── Individual checks ──────────────────────────────────────────────────────

    def check_spread(self, spread_bps: float) -> GuardDecision:
        if spread_bps > self.max_spread_bps:
            return GuardDecision(
                action=GuardAction.REJECT,
                reason=f"spread_too_wide: {spread_bps:.1f} bps > max {self.max_spread_bps} bps",
            )
        return GuardDecision(action=GuardAction.PASS)

    def check_slippage(self, expected_slippage_bps: float) -> GuardDecision:
        if expected_slippage_bps > self.max_slippage_bps:
            return GuardDecision(
                action=GuardAction.REJECT,
                reason=f"slippage_too_high: {expected_slippage_bps:.1f} bps > max {self.max_slippage_bps} bps",
            )
        return GuardDecision(action=GuardAction.PASS)

    def check_liquidity(
        self, liquidity_score: float, order_notional_usdt: float,
        max_safe_order_size_usdt: float,
    ) -> GuardDecision:
        if liquidity_score < self.min_liquidity_score:
            # If order is small relative to safe size, we can still allow
            if order_notional_usdt <= max_safe_order_size_usdt * 0.3:
                return GuardDecision(
                    action=GuardAction.REDUCE,
                    reason=f"low_liquidity: score={liquidity_score:.2f}, allowing small size",
                    adjusted_qty_usdt=min(order_notional_usdt, max_safe_order_size_usdt * 0.3),
                )
            return GuardDecision(
                action=GuardAction.REJECT,
                reason=f"insufficient_liquidity: score={liquidity_score:.2f} < min {self.min_liquidity_score}",
            )
        return GuardDecision(action=GuardAction.PASS)

    def check_latency(self, latency_ms: int) -> GuardDecision:
        if latency_ms > self.max_latency_ms:
            return GuardDecision(
                action=GuardAction.REJECT,
                reason=f"latency_too_high: {latency_ms}ms > max {self.max_latency_ms}ms",
            )
        return GuardDecision(action=GuardAction.PASS)

    def check_size(
        self, order_notional_usdt: float, max_safe_order_size_usdt: float,
    ) -> GuardDecision:
        if order_notional_usdt > max_safe_order_size_usdt:
            reduced = max_safe_order_size_usdt
            return GuardDecision(
                action=GuardAction.REDUCE,
                reason=f"order_too_large: {order_notional_usdt:.0f} USDT > safe {max_safe_order_size_usdt:.0f} USDT",
                adjusted_qty_usdt=reduced,
            )
        return GuardDecision(action=GuardAction.PASS)

    # ── Combined pre-trade check ───────────────────────────────────────────────

    def evaluate(
        self,
        spread_bps: float,
        expected_slippage_bps: float,
        liquidity_score: float,
        order_notional_usdt: float,
        max_safe_order_size_usdt: float,
        latency_ms: int = 0,
    ) -> GuardDecision:
        """
        Runs all pre-trade checks in priority order.
        Returns the first non-PASS decision, or PASS if all clear.
        """

        # 1. Spread check (instant reject, no partial allowed)
        d = self.check_spread(spread_bps)
        if d.action == GuardAction.REJECT:
            logger.info(f"[RiskMonitor] REJECT: {d.reason}")
            return d

        # 2. Slippage check
        d = self.check_slippage(expected_slippage_bps)
        if d.action == GuardAction.REJECT:
            logger.info(f"[RiskMonitor] REJECT: {d.reason}")
            return d

        # 3. Liquidity check (may reduce)
        d = self.check_liquidity(liquidity_score, order_notional_usdt, max_safe_order_size_usdt)
        if d.action != GuardAction.PASS:
            logger.info(f"[RiskMonitor] {d.action}: {d.reason}")
            if d.action == GuardAction.REJECT:
                return d
            # REDUCE: update notional for subsequent checks
            order_notional_usdt = d.adjusted_qty_usdt or order_notional_usdt

        # 4. Latency check
        d_lat = self.check_latency(latency_ms)
        if d_lat.action == GuardAction.REJECT:
            logger.info(f"[RiskMonitor] REJECT: {d_lat.reason}")
            return d_lat

        # 5. Order size check (may reduce)
        d_size = self.check_size(order_notional_usdt, max_safe_order_size_usdt)
        if d_size.action == GuardAction.REDUCE:
            logger.info(f"[RiskMonitor] REDUCE: {d_size.reason}")
            return d_size

        return GuardDecision(action=GuardAction.PASS, reason="all_checks_passed")
