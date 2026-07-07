"""
btc_scraper/execution/liquidity_analyzer.py
Phase 10 – Sprint 10.2: Liquidity Analyzer

Analyses orderbook depth, spread, volume and computes a composite
liquidity_score ∈ [0, 1] and max_safe_order_size.
"""
from __future__ import annotations

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import math


@dataclass
class LiquiditySnapshot:
    coin: str = ""
    exchange: str = "binance"

    # Raw inputs
    spread_bps: float = 0.0
    mid_price: float = 0.0
    top_bid: float = 0.0
    top_ask: float = 0.0

    # Orderbook depth (USDT notional at each band)
    bid_depth_1bps: float = 0.0
    ask_depth_1bps: float = 0.0
    bid_depth_5bps: float = 0.0
    ask_depth_5bps: float = 0.0
    bid_depth_10bps: float = 0.0
    ask_depth_10bps: float = 0.0

    # Volume
    volume_1m_usdt: float = 0.0
    volume_5m_usdt: float = 0.0
    volume_1h_usdt: float = 0.0

    # Volatility
    atr_pct: float = 0.0

    # Derived
    orderbook_imbalance: float = 0.0    # (bid_depth - ask_depth) / (bid + ask)
    market_impact_estimate: float = 0.0  # bps to move price 1% with our order
    volume_participation_rate: float = 0.0

    # Scores
    liquidity_score: float = 0.0        # [0, 1]
    max_safe_order_size_usdt: float = 0.0
    recommended_order_type: str = "LIMIT"
    liquidity_warning: str = ""


class LiquidityAnalyzer:
    """
    Computes liquidity metrics from orderbook and market data.

    Composite formula (from plan § 7.3):
        liquidity_score = (
            0.25 * normalized_depth
          + 0.20 * inverse_spread_score
          + 0.20 * volume_score
          + 0.15 * orderbook_stability
          + 0.10 * inverse_volatility
          + 0.10 * fill_probability_score
        )
    """

    # Reference values for normalization
    MAX_SPREAD_BPS_REF: float = 50.0      # spread at which score → 0
    MAX_DEPTH_REF_USDT: float = 500_000.0  # 500k USDT depth → score 1
    MAX_VOLUME_REF_USDT: float = 10_000_000.0  # 10M USDT/hr → score 1
    MAX_ATR_PCT_REF: float = 0.05          # 5% ATR → volatility score 0
    PARTICIPATION_RATE_CAP: float = 0.05   # never more than 5% of ADV

    def __init__(self, config: Dict[str, Any] = None):
        cfg = config or {}
        self.max_spread_bps = cfg.get("max_spread_bps", 20.0)
        self.min_liquidity_score = cfg.get("min_liquidity_score", 0.4)
        self.max_participation_rate = cfg.get("max_participation_rate", 0.02)

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        coin: str,
        mid_price: float,
        top_bid: float,
        top_ask: float,
        orderbook_bids: List[List[float]] = None,   # [[price, qty], …] sorted desc
        orderbook_asks: List[List[float]] = None,   # [[price, qty], …] sorted asc
        volume_1m_usdt: float = 0.0,
        volume_5m_usdt: float = 0.0,
        volume_1h_usdt: float = 0.0,
        atr_pct: float = 0.0,
        order_notional_usdt: float = 10_000.0,
        exchange: str = "binance",
    ) -> LiquiditySnapshot:

        snap = LiquiditySnapshot(coin=coin, exchange=exchange, mid_price=mid_price,
                                  top_bid=top_bid, top_ask=top_ask)

        # ── Spread ──────────────────────────────────────────────────────────
        if mid_price > 0:
            snap.spread_bps = (top_ask - top_bid) / mid_price * 10_000.0
        else:
            snap.spread_bps = 0.0

        # ── Depth by band ───────────────────────────────────────────────────
        bids = orderbook_bids or []
        asks = orderbook_asks or []

        snap.bid_depth_1bps, snap.ask_depth_1bps = self._depth_at_band(
            bids, asks, mid_price, band_bps=1.0)
        snap.bid_depth_5bps, snap.ask_depth_5bps = self._depth_at_band(
            bids, asks, mid_price, band_bps=5.0)
        snap.bid_depth_10bps, snap.ask_depth_10bps = self._depth_at_band(
            bids, asks, mid_price, band_bps=10.0)

        # ── Orderbook imbalance ──────────────────────────────────────────────
        total_bid = snap.bid_depth_5bps
        total_ask = snap.ask_depth_5bps
        denom = total_bid + total_ask
        snap.orderbook_imbalance = (total_bid - total_ask) / denom if denom > 0 else 0.0

        # ── Volume & participation ───────────────────────────────────────────
        snap.volume_1m_usdt = volume_1m_usdt
        snap.volume_5m_usdt = volume_5m_usdt
        snap.volume_1h_usdt = volume_1h_usdt
        snap.atr_pct = atr_pct

        adv_per_min = volume_1h_usdt / 60.0 if volume_1h_usdt > 0 else volume_1m_usdt
        snap.volume_participation_rate = (
            order_notional_usdt / (adv_per_min * 5.0) if adv_per_min > 0 else 1.0
        )  # expressed as fraction of 5-min volume

        # ── Market impact estimate ───────────────────────────────────────────
        # Rough: how many bps does our order move the book?
        depth_5bps = (snap.bid_depth_5bps + snap.ask_depth_5bps) / 2.0
        snap.market_impact_estimate = (
            (order_notional_usdt / depth_5bps * 5.0) if depth_5bps > 0 else 999.0
        )  # bps

        # ── Composite liquidity score ─────────────────────────────────────────
        snap.liquidity_score = self._compute_score(snap, order_notional_usdt)

        # ── Max safe order size ───────────────────────────────────────────────
        # Do not exceed max_participation_rate × 5-min volume
        adv_5min = max(volume_5m_usdt, volume_1m_usdt * 5.0)
        snap.max_safe_order_size_usdt = max(
            1000.0, adv_5min * self.max_participation_rate
        )

        # ── Recommended order type ────────────────────────────────────────────
        if snap.spread_bps > self.max_spread_bps:
            snap.recommended_order_type = "SKIP"
            snap.liquidity_warning = f"Spread {snap.spread_bps:.1f} bps > max {self.max_spread_bps}"
        elif snap.liquidity_score < self.min_liquidity_score:
            snap.recommended_order_type = "REDUCE_OR_SKIP"
            snap.liquidity_warning = f"Liquidity score {snap.liquidity_score:.2f} < min {self.min_liquidity_score}"
        elif snap.volume_participation_rate > self.PARTICIPATION_RATE_CAP:
            snap.recommended_order_type = "TWAP"
            snap.liquidity_warning = f"Order is {snap.volume_participation_rate*100:.1f}% of 5-min volume"
        elif snap.spread_bps < 5.0 and snap.liquidity_score > 0.7:
            snap.recommended_order_type = "MARKET"
        else:
            snap.recommended_order_type = "LIMIT"

        return snap

    def analyze_from_candle(
        self,
        coin: str,
        candle: Dict[str, Any],
        order_notional_usdt: float = 10_000.0,
        exchange: str = "binance",
    ) -> LiquiditySnapshot:
        """
        Synthetic liquidity analysis from a candle when orderbook is unavailable.
        Used in backtesting mode.
        """
        close = candle.get("close", 0.0) or 0.0
        high = candle.get("high", close)
        low = candle.get("low", close)
        volume_usdt = candle.get("volume", 0.0) * close if "volume" in candle else 0.0
        atr = candle.get("atr", (high - low))
        atr_pct = atr / close if close > 0 else 0.01

        # Synthetic spread: 2 * ATR-derived volatility estimate
        synthetic_spread_bps = max(1.0, atr_pct * 10_000.0 * 0.05)
        bid = close * (1 - synthetic_spread_bps / 20_000.0)
        ask = close * (1 + synthetic_spread_bps / 20_000.0)

        # Synthetic depth: assume 2% of hourly volume sits at 5bps
        depth_5bps = volume_usdt * 0.02

        return self.analyze(
            coin=coin,
            mid_price=close,
            top_bid=bid,
            top_ask=ask,
            orderbook_bids=[[bid, depth_5bps / bid]] if bid > 0 else [],
            orderbook_asks=[[ask, depth_5bps / ask]] if ask > 0 else [],
            volume_1m_usdt=volume_usdt / 15.0,   # approximate 1-min volume
            volume_5m_usdt=volume_usdt / 3.0,
            volume_1h_usdt=volume_usdt * 4.0,    # rough hourly estimate from 15m
            atr_pct=atr_pct,
            order_notional_usdt=order_notional_usdt,
            exchange=exchange,
        )

    # ── Internals ─────────────────────────────────────────────────────────────

    def _depth_at_band(
        self,
        bids: List[List[float]],
        asks: List[List[float]],
        mid_price: float,
        band_bps: float,
    ):
        """Sum notional within ±band_bps of mid_price."""
        lower = mid_price * (1 - band_bps / 10_000.0)
        upper = mid_price * (1 + band_bps / 10_000.0)

        bid_depth = sum(p * q for p, q in bids if lower <= p <= mid_price)
        ask_depth = sum(p * q for p, q in asks if mid_price <= p <= upper)
        return bid_depth, ask_depth

    def _compute_score(self, snap: LiquiditySnapshot, order_notional: float) -> float:
        # 0.25 * normalized_depth (at 5bps)
        avg_depth_5bps = (snap.bid_depth_5bps + snap.ask_depth_5bps) / 2.0
        normalized_depth = min(1.0, avg_depth_5bps / self.MAX_DEPTH_REF_USDT)

        # 0.20 * inverse_spread_score
        inverse_spread = max(0.0, 1.0 - snap.spread_bps / self.MAX_SPREAD_BPS_REF)

        # 0.20 * volume_score
        volume_score = min(1.0, snap.volume_1h_usdt / self.MAX_VOLUME_REF_USDT)

        # 0.15 * orderbook_stability (1 - abs(imbalance))
        orderbook_stability = 1.0 - abs(snap.orderbook_imbalance)

        # 0.10 * inverse_volatility
        inverse_volatility = max(0.0, 1.0 - snap.atr_pct / self.MAX_ATR_PCT_REF)

        # 0.10 * fill_probability_score (inverse of participation rate)
        fill_probability_score = max(0.0, 1.0 - snap.volume_participation_rate / self.PARTICIPATION_RATE_CAP)

        score = (
            0.25 * normalized_depth
            + 0.20 * inverse_spread
            + 0.20 * volume_score
            + 0.15 * orderbook_stability
            + 0.10 * inverse_volatility
            + 0.10 * fill_probability_score
        )
        return round(min(1.0, max(0.0, score)), 4)
