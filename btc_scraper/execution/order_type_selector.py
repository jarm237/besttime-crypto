"""
btc_scraper/execution/order_type_selector.py
Phase 10 – Sprint 10.4: Order Type Selector

Decides the best order type and parameters given market conditions.
Decision rules mirror plan § 9.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional


# ── Urgency levels ─────────────────────────────────────────────────────────────
class Urgency:
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"       # e.g. emergency SL exit
    EMERGENCY = "EMERGENCY"


# ── Order type constants ───────────────────────────────────────────────────────
class OrderType:
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    AGGRESSIVE_LIMIT = "AGGRESSIVE_LIMIT"
    LIMIT_MAKER = "LIMIT_MAKER"
    TWAP = "TWAP"
    SKIP = "SKIP"


class TimeInForce:
    GTC = "GTC"     # Good Till Cancelled
    IOC = "IOC"     # Immediate Or Cancel
    FOK = "FOK"     # Fill Or Kill
    GTX = "GTX"     # Post-Only (maker)


@dataclass
class OrderDecision:
    order_type: str = OrderType.LIMIT
    limit_price: Optional[float] = None
    time_in_force: str = TimeInForce.GTC
    max_wait_seconds: int = 30
    fallback_action: str = "CANCEL"  # CANCEL | MARKET | TIMEOUT
    adjusted_qty_usdt: Optional[float] = None
    reason: str = ""


class OrderTypeSelector:
    """
    Selects the optimal order type and parameters based on:
    - urgency
    - spread
    - liquidity score
    - expected slippage
    - orderbook context

    Decision rules (plan § 9):
        urgency=HIGH             → MARKET or AGGRESSIVE_LIMIT
        spread > max_spread_bps  → SKIP or passive LIMIT
        liquidity < min          → reduce size or SKIP
        slippage > max           → TWAP or reduce size
        else                     → LIMIT_MAKER or passive LIMIT
    """

    def __init__(self, config: Dict[str, Any] = None):
        cfg = config or {}
        self.max_spread_bps: float = cfg.get("max_spread_bps", 20.0)
        self.max_slippage_bps: float = cfg.get("max_slippage_bps", 30.0)
        self.min_liquidity_score: float = cfg.get("min_liquidity_score", 0.4)
        self.limit_order_max_wait_seconds: int = cfg.get("limit_order_max_wait_seconds", 30)
        self.tick_size: float = cfg.get("tick_size", 0.01)

    def select(
        self,
        side: str,                        # "BUY" | "SELL"
        top_bid: float,
        top_ask: float,
        mid_price: float,
        spread_bps: float,
        liquidity_score: float,
        expected_slippage_bps: float,
        max_safe_order_size_usdt: float,
        intended_notional_usdt: float,
        urgency: str = Urgency.NORMAL,
        volume_participation_rate: float = 0.0,
    ) -> OrderDecision:

        is_buy = side.upper() in ("BUY", "LONG")

        # ── Emergency / High urgency → MARKET ──────────────────────────────
        if urgency in (Urgency.HIGH, Urgency.EMERGENCY):
            return OrderDecision(
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.IOC,
                max_wait_seconds=0,
                fallback_action="NONE",
                reason=f"urgency={urgency} → market fill",
            )

        # ── Spread too wide → SKIP ──────────────────────────────────────────
        if spread_bps > self.max_spread_bps:
            return OrderDecision(
                order_type=OrderType.SKIP,
                reason=f"spread {spread_bps:.1f} bps > max {self.max_spread_bps}",
            )

        # ── Insufficient liquidity → reduce or skip ─────────────────────────
        if liquidity_score < self.min_liquidity_score:
            if intended_notional_usdt > max_safe_order_size_usdt * 0.5:
                return OrderDecision(
                    order_type=OrderType.SKIP,
                    reason=f"liquidity_score {liquidity_score:.2f} < min {self.min_liquidity_score}",
                )
            # Allow reduced size with passive limit
            adjusted = min(intended_notional_usdt, max_safe_order_size_usdt * 0.5)
            limit_price = self._passive_limit_price(is_buy, top_bid, top_ask)
            return OrderDecision(
                order_type=OrderType.LIMIT,
                limit_price=limit_price,
                time_in_force=TimeInForce.GTC,
                max_wait_seconds=self.limit_order_max_wait_seconds,
                fallback_action="CANCEL",
                adjusted_qty_usdt=adjusted,
                reason=f"low liquidity, size reduced to {adjusted:.0f} USDT",
            )

        # ── High expected slippage → TWAP or reduce ─────────────────────────
        if expected_slippage_bps > self.max_slippage_bps:
            if volume_participation_rate > 0.02:
                return OrderDecision(
                    order_type=OrderType.TWAP,
                    time_in_force=TimeInForce.GTC,
                    max_wait_seconds=180,
                    fallback_action="CANCEL",
                    reason=f"high slippage {expected_slippage_bps:.1f} bps, TWAP recommended",
                )
            # Otherwise just reduce size
            adjusted = intended_notional_usdt * 0.5
            limit_price = self._passive_limit_price(is_buy, top_bid, top_ask)
            return OrderDecision(
                order_type=OrderType.LIMIT,
                limit_price=limit_price,
                time_in_force=TimeInForce.GTC,
                max_wait_seconds=self.limit_order_max_wait_seconds,
                fallback_action="CANCEL",
                adjusted_qty_usdt=adjusted,
                reason=f"slippage {expected_slippage_bps:.1f} bps > max, reduced size",
            )

        # ── Normal: prefer LIMIT ───────────────────────────────────────────
        if spread_bps < 5.0 and liquidity_score > 0.7:
            # Tight spread + high liquidity → aggressive limit (≈ market)
            limit_price = self._aggressive_limit_price(is_buy, top_bid, top_ask)
            return OrderDecision(
                order_type=OrderType.AGGRESSIVE_LIMIT,
                limit_price=limit_price,
                time_in_force=TimeInForce.IOC,
                max_wait_seconds=5,
                fallback_action="MARKET",
                reason="tight spread, aggressive limit for fast fill",
            )

        limit_price = self._passive_limit_price(is_buy, top_bid, top_ask)
        return OrderDecision(
            order_type=OrderType.LIMIT,
            limit_price=limit_price,
            time_in_force=TimeInForce.GTC,
            max_wait_seconds=self.limit_order_max_wait_seconds,
            fallback_action="CANCEL",
            reason="standard passive limit",
        )

    # ── Price helpers ──────────────────────────────────────────────────────────

    def _passive_limit_price(self, is_buy: bool, top_bid: float, top_ask: float) -> float:
        """Place one tick better than best bid/ask — improves queue position."""
        tick = self.tick_size
        return (top_bid + tick) if is_buy else (top_ask - tick)

    def _aggressive_limit_price(self, is_buy: bool, top_bid: float, top_ask: float) -> float:
        """Place at the opposite side — crosses spread for immediate fill."""
        return top_ask if is_buy else top_bid
