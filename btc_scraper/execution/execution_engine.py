"""
btc_scraper/execution/execution_engine.py
Phase 10 – Sprint 10.1: Execution Engine

Core coordinator for the full execution lifecycle.
Integrates: LiquidityAnalyzer → SlippagePredictor → ExecutionRiskMonitor
             → OrderTypeSelector → ExecutionPlanner → FillTracker
             → PostTradeAnalyzer

In dry_run mode, simulates fills using candle prices (Phase 9 compatible).
"""
from __future__ import annotations

import uuid
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from .execution_config import ExecutionConfig
from .fill_tracker import FillTracker, ExecutionRecord, FillEvent, OrderStatus
from .liquidity_analyzer import LiquidityAnalyzer
from .slippage_predictor import SlippagePredictor
from .execution_risk_monitor import ExecutionRiskMonitor, GuardAction
from .order_type_selector import OrderTypeSelector, Urgency
from .execution_planner import ExecutionPlanner
from .post_trade_analyzer import PostTradeAnalyzer

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """
    Main execution coordinator.

    Usage (paper/backtest mode):
        engine = ExecutionEngine()
        record = engine.submit_paper(signal, candle)
    """

    def __init__(
        self,
        config: ExecutionConfig = None,
        log_dir: str = "logs/execution",
        fills_dir: str = "data/execution/fills",
        reports_dir: str = "data/execution/reports",
    ):
        self.config = config or ExecutionConfig()
        self._tracker = FillTracker(log_dir=log_dir, fills_dir=fills_dir)
        self._liquidity = LiquidityAnalyzer({
            "max_spread_bps": self.config.max_spread_bps,
            "min_liquidity_score": self.config.min_liquidity_score,
            "max_participation_rate": self.config.max_participation_rate,
        })
        self._slippage = SlippagePredictor()
        self._risk = ExecutionRiskMonitor({
            "max_spread_bps": self.config.max_spread_bps,
            "max_slippage_bps": self.config.max_slippage_bps,
            "min_liquidity_score": self.config.min_liquidity_score,
            "max_latency_ms": self.config.max_latency_ms,
            "max_participation_rate": self.config.max_participation_rate,
        })
        self._selector = OrderTypeSelector({
            "max_spread_bps": self.config.max_spread_bps,
            "max_slippage_bps": self.config.max_slippage_bps,
            "min_liquidity_score": self.config.min_liquidity_score,
            "limit_order_max_wait_seconds": self.config.limit_order_max_wait_seconds,
        })
        self._planner = ExecutionPlanner(self.config.twap.__dict__)
        self._post_trade = PostTradeAnalyzer(reports_dir=reports_dir)

    # ── Public API ─────────────────────────────────────────────────────────────

    def submit_paper(
        self,
        signal: Dict[str, Any],
        candle: Dict[str, Any],
        urgency: str = Urgency.NORMAL,
    ) -> ExecutionRecord:
        """
        Simulate order submission in paper/backtest mode.
        Uses synthetic liquidity from the candle.
        """
        coin = signal.get("coin", "BTC")
        side = self._signal_to_side(signal.get("signal_raw", signal.get("signal", "")))
        decision_price = float(candle.get("close", 0.0))

        # Notional sizing: use 1% of default capital (configurable)
        capital = 10_000.0
        notional_usdt = capital * 0.01
        qty = notional_usdt / decision_price if decision_price > 0 else 0.0

        record = ExecutionRecord(
            signal_id=signal.get("id", str(uuid.uuid4())[:8]),
            coin=coin,
            side=side,
            intended_qty=qty,
            intended_notional=notional_usdt,
            decision_price=decision_price,
            timestamp=signal.get("entry_time", datetime.now(timezone.utc).isoformat()),
        )

        # ── 1. Liquidity analysis ─────────────────────────────────────────
        snap = self._liquidity.analyze_from_candle(
            coin=coin, candle=candle, order_notional_usdt=notional_usdt,
        )
        record.spread_bps_at_submit = snap.spread_bps
        record.orderbook_imbalance_at_submit = snap.orderbook_imbalance
        record.top_bid = snap.top_bid
        record.top_ask = snap.top_ask
        record.mid_price = snap.mid_price
        record.liquidity_score = snap.liquidity_score
        record.max_safe_order_size = snap.max_safe_order_size_usdt

        # ── 2. Slippage prediction ────────────────────────────────────────
        expected_slip = self._slippage.predict_from_snapshot(
            snap=snap, order_notional_usdt=notional_usdt,
        )
        record.expected_slippage_bps = expected_slip

        # ── 3. Pre-trade risk check ───────────────────────────────────────
        guard = self._risk.evaluate(
            spread_bps=snap.spread_bps,
            expected_slippage_bps=expected_slip,
            liquidity_score=snap.liquidity_score,
            order_notional_usdt=notional_usdt,
            max_safe_order_size_usdt=snap.max_safe_order_size_usdt,
        )
        record.guard_action = guard.action

        if guard.action == GuardAction.REJECT:
            logger.info(f"[Execution] REJECTED {coin} {side}: {guard.reason}")
            return self._tracker.reject(record, reason=guard.reason)

        if guard.action == GuardAction.REDUCE and guard.adjusted_qty_usdt:
            notional_usdt = guard.adjusted_qty_usdt
            qty = notional_usdt / decision_price if decision_price > 0 else qty
            record.intended_qty = qty
            record.intended_notional = notional_usdt

        # ── 4. Order type selection ──────────────────────────────────────
        order_decision = self._selector.select(
            side=side,
            top_bid=snap.top_bid,
            top_ask=snap.top_ask,
            mid_price=snap.mid_price,
            spread_bps=snap.spread_bps,
            liquidity_score=snap.liquidity_score,
            expected_slippage_bps=expected_slip,
            max_safe_order_size_usdt=snap.max_safe_order_size_usdt,
            intended_notional_usdt=notional_usdt,
            urgency=urgency,
            volume_participation_rate=snap.volume_participation_rate,
        )

        if order_decision.order_type == "SKIP":
            return self._tracker.reject(record, reason=order_decision.reason)

        record.order_type = order_decision.order_type
        record.submitted_price = order_decision.limit_price or decision_price

        # ── 5. Simulate fill in paper mode ───────────────────────────────
        # Apply spread + slippage to get realistic fill price
        is_buy = side == "BUY"
        fill_price = snap.top_ask if is_buy else snap.top_bid
        slip_mult = (1.0 + expected_slip / 10_000.0) if is_buy else (1.0 - expected_slip / 10_000.0)
        fill_price = fill_price * slip_mult

        record.submit_time = datetime.now(timezone.utc).isoformat()
        self._tracker.register(record)
        self._tracker.simulate_fill(record, fill_price=fill_price)

        logger.debug(
            f"[Execution] FILLED {coin} {side} @ {fill_price:.4f} "
            f"(slip {expected_slip:.1f} bps, liq {snap.liquidity_score:.2f})"
        )
        return record

    def get_stats(self) -> Dict[str, Any]:
        """Aggregate execution stats for dashboard/API."""
        history = self._tracker.get_history(limit=500)
        if not history:
            return {"n_fills": 0, "reject_rate": 0.0}

        filled = [r for r in history if r.status == OrderStatus.FILLED]
        rejected = [r for r in history if r.status == OrderStatus.REJECTED]

        avg_slip = (
            sum(r.expected_slippage_bps for r in filled) / len(filled)
            if filled else 0.0
        )
        avg_liq = (
            sum(r.liquidity_score for r in filled) / len(filled)
            if filled else 0.0
        )

        by_coin: Dict[str, Dict] = {}
        for r in filled:
            c = by_coin.setdefault(r.coin, {"n_fills": 0, "avg_spread_bps": 0.0, "avg_slippage_bps": 0.0})
            c["n_fills"] += 1
            c["avg_spread_bps"] += r.spread_bps_at_submit
            c["avg_slippage_bps"] += r.expected_slippage_bps
        for c in by_coin.values():
            n = c["n_fills"]
            c["avg_spread_bps"] = round(c["avg_spread_bps"] / n, 3)
            c["avg_slippage_bps"] = round(c["avg_slippage_bps"] / n, 3)

        reject_reasons: Dict[str, int] = {}
        for r in rejected:
            reject_reasons[r.reason] = reject_reasons.get(r.reason, 0) + 1

        return {
            "n_fills": len(filled),
            "n_rejected": len(rejected),
            "reject_rate": round(self._tracker.reject_rate(), 4),
            "avg_expected_slippage_bps": round(avg_slip, 3),
            "avg_liquidity_score": round(avg_liq, 3),
            "by_coin": by_coin,
            "reject_reasons": reject_reasons,
        }

    def get_recent_fills(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._tracker.get_history(limit=limit)
                if r.status == OrderStatus.FILLED]

    def analyze_quality(self, limit: int = 200) -> Dict[str, Any]:
        filled = [r.to_dict() for r in self._tracker.get_history(limit=limit)
                  if r.status == OrderStatus.FILLED]
        if not filled:
            return {}
        return self._post_trade.generate_report(filled)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _signal_to_side(signal_raw: str) -> str:
        s = signal_raw.upper()
        if any(w in s for w in ("BUY", "LONG", "BULLISH", "STRONG BUY")):
            return "BUY"
        return "SELL"
