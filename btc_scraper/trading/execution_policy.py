"""Canonical shared execution policy component.

Enforces unified execution policy (P4 contract) shared across:
1. Event-driven accounting replay (event_driven_accounting.py)
2. Live/Paper AutoTrader & ExposureManager (auto_trader.py)

Rules:
- Max 3 concurrent positions globally
- Max 1 position per asset
- 96-bar cooldown (24 hours at 15m) per asset after position exit
- Fixed 25% equity allocation per trade
- Slippage (2 bps) and taker fee (5 bps) modeling
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

import pandas as pd


@dataclass(frozen=True)
class CanonicalExecutionPolicy:
    """Canonical P4 execution policy configuration."""
    max_concurrent_positions: int = 3
    max_positions_per_asset: int = 1
    cooldown_bars: int = 96
    bar_interval_minutes: int = 15
    allocation_pct_per_trade: float = 0.25
    fee_rate_bps: float = 5.0
    slippage_bps: float = 2.0

    @property
    def cooldown_duration(self) -> timedelta:
        return timedelta(minutes=self.cooldown_bars * self.bar_interval_minutes)

    def can_enter(
        self,
        *,
        symbol: str,
        side: str,
        current_time: Any,
        active_positions: Sequence[Mapping[str, Any]],
        last_exit_timestamps: Mapping[str, Any],
        total_equity: float,
        available_cash: float,
    ) -> tuple[bool, str | None]:
        """Evaluates whether an entry order is permitted under the canonical P4 policy.

        Returns:
            (allowed: bool, rejection_reason: str | None)
        """
        sym_clean = str(symbol or "").strip().upper().replace("/", "").replace("-", "").removesuffix("USDT")
        curr_ts = self._to_utc_timestamp(current_time)

        # 1. Cooldown Check (96 bars = 24h)
        last_exit = last_exit_timestamps.get(sym_clean)
        if last_exit is not None:
            last_exit_ts = self._to_utc_timestamp(last_exit)
            if curr_ts < last_exit_ts + self.cooldown_duration:
                return False, "cooldown_active"

        # 2. Per-Asset Concurrency Limit (max 1 per asset)
        asset_active = [
            p for p in active_positions
            if str(p.get("symbol") or p.get("coin") or "").strip().upper().replace("/", "").replace("-", "").removesuffix("USDT") == sym_clean
        ]
        if len(asset_active) >= self.max_positions_per_asset:
            return False, "existing_position"

        # 3. Global Concurrency Limit (max 3 concurrent)
        if len(active_positions) >= self.max_concurrent_positions:
            return False, "max_concurrent_positions"

        # 4. Capital Allocation & Cash Capacity
        required_allocation = total_equity * self.allocation_pct_per_trade
        fee_rate = self.fee_rate_bps / 10000.0
        slippage_rate = self.slippage_bps / 10000.0
        est_entry_cost = required_allocation * (fee_rate + slippage_rate)

        if available_cash < (required_allocation + est_entry_cost):
            return False, "capital_capacity_exceeded"

        return True, None

    def calculate_allocation(self, total_equity: float) -> float:
        """Calculates 25% position sizing."""
        return max(0.0, float(total_equity) * self.allocation_pct_per_trade)

    def calculate_entry_fill_price(self, side: str, price: float) -> float:
        """Applies 2 bps slippage adversely to entry price."""
        slip = self.slippage_bps / 10000.0
        p = float(price)
        return p * (1.0 + slip) if side.upper() == "BUY" else p * (1.0 - slip)

    def calculate_exit_fill_price(self, side: str, price: float) -> float:
        """Applies 2 bps slippage adversely to exit price."""
        slip = self.slippage_bps / 10000.0
        p = float(price)
        return p * (1.0 - slip) if side.upper() == "BUY" else p * (1.0 + slip)

    def calculate_fee(self, notional: float) -> float:
        """Applies 5 bps taker fee."""
        return max(0.0, float(notional) * (self.fee_rate_bps / 10000.0))

    @staticmethod
    def _to_utc_timestamp(ts: Any) -> pd.Timestamp:
        if isinstance(ts, pd.Timestamp):
            return ts.tz_convert("UTC") if ts.tzinfo is not None else ts.tz_localize("UTC")
        if isinstance(ts, datetime):
            return pd.Timestamp(ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc))
        ts_dt = pd.to_datetime(ts)
        return ts_dt.tz_convert("UTC") if ts_dt.tzinfo is not None else ts_dt.tz_localize("UTC")


CANONICAL_POLICY = CanonicalExecutionPolicy()

