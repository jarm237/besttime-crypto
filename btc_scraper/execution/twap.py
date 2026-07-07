"""
btc_scraper/execution/twap.py
Phase 10 – Sprint 10.5: TWAP Executor

Breaks a large order into equally-sized time slices.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime, timezone


@dataclass
class ChildOrderSlice:
    slice_index: int = 0
    qty: float = 0.0
    notional_usdt: float = 0.0
    scheduled_at: float = 0.0       # unix timestamp
    submitted_at: Optional[float] = None
    fill_price: Optional[float] = None
    filled: bool = False
    cancelled: bool = False


@dataclass
class TWAPPlan:
    total_qty: float = 0.0
    total_notional_usdt: float = 0.0
    slices: int = 5
    interval_seconds: int = 30
    max_duration_seconds: int = 180
    cancel_on_signal_reversal: bool = True
    planned_at: float = field(default_factory=time.time)
    children: List[ChildOrderSlice] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        active = [c for c in self.children if not c.cancelled]
        return all(c.filled for c in active)

    @property
    def is_expired(self) -> bool:
        return time.time() > self.planned_at + self.max_duration_seconds

    @property
    def filled_qty(self) -> float:
        return sum(c.qty for c in self.children if c.filled)

    @property
    def avg_fill_price(self) -> float:
        filled = [c for c in self.children if c.filled and c.fill_price]
        if not filled:
            return 0.0
        total_val = sum(c.qty * c.fill_price for c in filled)
        total_qty = sum(c.qty for c in filled)
        return total_val / total_qty if total_qty > 0 else 0.0


class TWAPExecutor:
    """
    Plans and manages TWAP (Time-Weighted Average Price) execution.
    """

    def plan(
        self,
        total_qty: float,
        total_notional_usdt: float,
        slices: int = 5,
        interval_seconds: int = 30,
        max_duration_seconds: int = 180,
        cancel_on_signal_reversal: bool = True,
        start_time: Optional[float] = None,
    ) -> TWAPPlan:
        """
        Creates a TWAP execution plan with equally-sized time slices.
        """
        t0 = start_time or time.time()
        slice_qty = total_qty / slices
        slice_notional = total_notional_usdt / slices

        children = []
        for i in range(slices):
            children.append(ChildOrderSlice(
                slice_index=i,
                qty=slice_qty,
                notional_usdt=slice_notional,
                scheduled_at=t0 + i * interval_seconds,
            ))

        return TWAPPlan(
            total_qty=total_qty,
            total_notional_usdt=total_notional_usdt,
            slices=slices,
            interval_seconds=interval_seconds,
            max_duration_seconds=max_duration_seconds,
            cancel_on_signal_reversal=cancel_on_signal_reversal,
            planned_at=t0,
            children=children,
        )

    def get_due_slices(self, plan: TWAPPlan) -> List[ChildOrderSlice]:
        """Returns slices that are due to be submitted now."""
        now = time.time()
        return [
            c for c in plan.children
            if not c.filled and not c.cancelled and c.scheduled_at <= now
        ]

    def check_cancel(
        self,
        plan: TWAPPlan,
        entry_signal: str,
        current_signal: str,
    ) -> bool:
        """
        Returns True if the TWAP plan should be cancelled due to signal reversal.
        """
        if not plan.cancel_on_signal_reversal:
            return False
        entry_dir = self._signal_direction(entry_signal)
        current_dir = self._signal_direction(current_signal)
        return entry_dir != "NEUTRAL" and current_dir != "NEUTRAL" and entry_dir != current_dir

    def cancel_remaining(self, plan: TWAPPlan) -> int:
        """Cancel all unfilled slices. Returns count cancelled."""
        count = 0
        for c in plan.children:
            if not c.filled:
                c.cancelled = True
                count += 1
        return count

    @staticmethod
    def _signal_direction(signal: str) -> str:
        s = signal.upper()
        if any(w in s for w in ("BUY", "LONG", "BULLISH")):
            return "LONG"
        if any(w in s for w in ("SELL", "SHORT", "BEARISH")):
            return "SHORT"
        return "NEUTRAL"
