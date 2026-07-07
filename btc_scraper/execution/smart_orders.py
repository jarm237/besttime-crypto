"""
btc_scraper/execution/smart_orders.py
Phase 10 – Sprint 10.5: Smart Order Builders

Helper dataclasses and factories for constructing order specs.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone


@dataclass
class BaseOrderSpec:
    order_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    coin: str = ""
    side: str = "BUY"          # BUY | SELL
    qty: float = 0.0
    notional_usdt: float = 0.0
    order_type: str = "LIMIT"
    time_in_force: str = "GTC"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_reduce_only: bool = False
    is_post_only: bool = False


@dataclass
class MarketOrderSpec(BaseOrderSpec):
    order_type: str = "MARKET"
    time_in_force: str = "IOC"


@dataclass
class LimitOrderSpec(BaseOrderSpec):
    order_type: str = "LIMIT"
    limit_price: float = 0.0
    time_in_force: str = "GTC"
    max_wait_seconds: int = 30
    fallback_to_market: bool = False


@dataclass
class AggressiveLimitSpec(BaseOrderSpec):
    order_type: str = "AGGRESSIVE_LIMIT"
    limit_price: float = 0.0
    time_in_force: str = "IOC"
    max_wait_seconds: int = 5
    fallback_to_market: bool = True


@dataclass
class TWAPOrderSpec(BaseOrderSpec):
    order_type: str = "TWAP"
    slices: int = 5
    interval_seconds: int = 30
    max_duration_seconds: int = 180
    cancel_on_signal_reversal: bool = True
    child_orders: list = field(default_factory=list)


class SmartOrderFactory:
    """
    Creates order specs with proper price adjustments.
    """

    @staticmethod
    def market(coin: str, side: str, qty: float, notional: float) -> MarketOrderSpec:
        return MarketOrderSpec(coin=coin, side=side, qty=qty, notional_usdt=notional)

    @staticmethod
    def limit(
        coin: str,
        side: str,
        qty: float,
        notional: float,
        limit_price: float,
        top_bid: float,
        top_ask: float,
        tick_size: float = 0.01,
        max_wait_seconds: int = 30,
    ) -> LimitOrderSpec:
        """Passive limit — one tick better than best bid/ask."""
        is_buy = side.upper() in ("BUY", "LONG")
        price = (top_bid + tick_size) if is_buy else (top_ask - tick_size)
        return LimitOrderSpec(
            coin=coin, side=side, qty=qty, notional_usdt=notional,
            limit_price=price, max_wait_seconds=max_wait_seconds,
        )

    @staticmethod
    def aggressive_limit(
        coin: str,
        side: str,
        qty: float,
        notional: float,
        top_bid: float,
        top_ask: float,
    ) -> AggressiveLimitSpec:
        """Crosses the spread for immediate fill."""
        is_buy = side.upper() in ("BUY", "LONG")
        price = top_ask if is_buy else top_bid
        return AggressiveLimitSpec(coin=coin, side=side, qty=qty, notional_usdt=notional,
                                    limit_price=price)

    @staticmethod
    def twap(
        coin: str,
        side: str,
        total_qty: float,
        notional: float,
        slices: int = 5,
        interval_seconds: int = 30,
        max_duration_seconds: int = 180,
        cancel_on_signal_reversal: bool = True,
    ) -> TWAPOrderSpec:
        return TWAPOrderSpec(
            coin=coin, side=side, qty=total_qty, notional_usdt=notional,
            slices=slices, interval_seconds=interval_seconds,
            max_duration_seconds=max_duration_seconds,
            cancel_on_signal_reversal=cancel_on_signal_reversal,
        )
