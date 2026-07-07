"""
btc_scraper/execution/execution_planner.py
Phase 10 – Sprint 10.5: Execution Planner

Coordinates the full execution lifecycle:
  1. Receives order decision from OrderTypeSelector
  2. Builds smart order spec (SmartOrderFactory)
  3. Optionally creates TWAP plan (TWAPExecutor)
  4. Hands spec to ExecutionEngine for dispatch
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

from .smart_orders import (
    SmartOrderFactory, BaseOrderSpec, MarketOrderSpec,
    LimitOrderSpec, AggressiveLimitSpec, TWAPOrderSpec,
)
from .twap import TWAPExecutor, TWAPPlan
from .order_type_selector import OrderDecision, OrderType


@dataclass
class ExecutionPlan:
    order_spec: Optional[BaseOrderSpec] = None
    twap_plan: Optional[TWAPPlan] = None
    is_twap: bool = False
    skip: bool = False
    reason: str = ""


class ExecutionPlanner:
    """
    Translates an OrderDecision into a concrete execution plan.
    """

    def __init__(self, twap_config: Dict[str, Any] = None):
        self._twap = TWAPExecutor()
        self._twap_cfg = twap_config or {
            "slices": 5,
            "interval_seconds": 30,
            "max_duration_seconds": 180,
            "cancel_on_signal_reversal": True,
        }

    def plan(
        self,
        decision: OrderDecision,
        coin: str,
        side: str,
        qty: float,
        notional_usdt: float,
        top_bid: float,
        top_ask: float,
        tick_size: float = 0.01,
    ) -> ExecutionPlan:

        if decision.order_type == OrderType.SKIP:
            return ExecutionPlan(skip=True, reason=decision.reason)

        # If decision adjusted size, apply it
        actual_notional = (
            decision.adjusted_qty_usdt
            if decision.adjusted_qty_usdt is not None
            else notional_usdt
        )
        # Adjust qty proportionally
        ratio = actual_notional / notional_usdt if notional_usdt > 0 else 1.0
        actual_qty = qty * ratio

        if decision.order_type == OrderType.TWAP:
            plan = self._twap.plan(
                total_qty=actual_qty,
                total_notional_usdt=actual_notional,
                slices=self._twap_cfg.get("slices", 5),
                interval_seconds=self._twap_cfg.get("interval_seconds", 30),
                max_duration_seconds=self._twap_cfg.get("max_duration_seconds", 180),
                cancel_on_signal_reversal=self._twap_cfg.get("cancel_on_signal_reversal", True),
            )
            spec = SmartOrderFactory.twap(coin=coin, side=side, total_qty=actual_qty,
                                          notional=actual_notional)
            return ExecutionPlan(order_spec=spec, twap_plan=plan, is_twap=True, reason=decision.reason)

        if decision.order_type == OrderType.MARKET:
            spec = SmartOrderFactory.market(coin=coin, side=side, qty=actual_qty, notional=actual_notional)
            return ExecutionPlan(order_spec=spec, reason=decision.reason)

        if decision.order_type == OrderType.AGGRESSIVE_LIMIT:
            spec = SmartOrderFactory.aggressive_limit(
                coin=coin, side=side, qty=actual_qty, notional=actual_notional,
                top_bid=top_bid, top_ask=top_ask,
            )
            return ExecutionPlan(order_spec=spec, reason=decision.reason)

        # Default: LIMIT / LIMIT_MAKER
        spec = SmartOrderFactory.limit(
            coin=coin, side=side, qty=actual_qty, notional=actual_notional,
            limit_price=decision.limit_price or top_bid,
            top_bid=top_bid, top_ask=top_ask, tick_size=tick_size,
            max_wait_seconds=decision.max_wait_seconds,
        )
        return ExecutionPlan(order_spec=spec, reason=decision.reason)

    def check_twap_cancel(
        self,
        plan: TWAPPlan,
        entry_signal: str,
        current_signal: str,
    ) -> bool:
        """Delegates to TWAPExecutor.check_cancel."""
        return self._twap.check_cancel(plan, entry_signal, current_signal)

    def cancel_twap(self, plan: TWAPPlan) -> int:
        return self._twap.cancel_remaining(plan)

    def get_due_twap_slices(self, plan: TWAPPlan):
        return self._twap.get_due_slices(plan)
