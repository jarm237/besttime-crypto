"""
btc_scraper/execution/execution_engine.py
Phase 10 – Sprint 10.1 | Phase 1 Remediation: Execution Engine

Core coordinator for the full execution lifecycle.
Integrates: LiquidityAnalyzer → SlippagePredictor → ExecutionRiskMonitor
             → OrderTypeSelector → ExecutionPlanner → FillTracker
             → PostTradeAnalyzer → ExchangeAdapter

In dry_run mode, simulates fills using candle prices (Phase 9 compatible).
In live mode, routes ALL write orders through WriteExchangeAdapter.
Direct CCXTClient calls outside this module are FORBIDDEN.
"""
from __future__ import annotations

import uuid
import time
import logging
import math
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from .execution_config import ExecutionConfig
from .fill_tracker import FillTracker, ExecutionRecord, FillEvent, OrderStatus
from .liquidity_analyzer import LiquidityAnalyzer
from .slippage_predictor import SlippagePredictor
from .execution_risk_monitor import ExecutionRiskMonitor, GuardAction
from .order_type_selector import OrderTypeSelector, Urgency, OrderType, OrderDecision
from .execution_planner import ExecutionPlanner
from .post_trade_analyzer import PostTradeAnalyzer
from .exchange_adapter import WriteExchangeAdapter, make_write_adapter_from_env
from btc_scraper.execution.reservation_store import ReservationStore
from btc_scraper.trading.decision_types import ReservationStatus
from btc_scraper.execution.hard_risk_limits import OrderIntent
from btc_scraper.core.paths import build_execution_data_path, build_logs_path

logger = logging.getLogger(__name__)

PAPER_RECOVERY_SIMULATION_FLAGS = (
    "simulate_timeout_after_reserve",
    "simulate_crash_after_fill_before_commit",
    "paper_fill_fraction",
    "paper_cancel_remaining",
)


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
        log_dir: str | None = None,
        fills_dir: str | None = None,
        reports_dir: str | None = None,
        exchange_adapter: Optional[WriteExchangeAdapter] = None,
        live_guard: Optional[Any] = None,
        reservation_db_path: Optional[str] = None,
    ):
        self.config = config or ExecutionConfig()
        if live_guard is not None:
            self._live_guard = live_guard
        else:
            from .live_execution_guard import LiveExecutionGuard
            self._live_guard = LiveExecutionGuard()
        log_dir = log_dir or str(build_logs_path("execution"))
        fills_dir = fills_dir or str(build_execution_data_path("fills"))
        reports_dir = reports_dir or str(build_execution_data_path("reports"))
        # ── Write adapter — ONLY this engine holds a write-capable adapter ──
        self._adapter: Optional[WriteExchangeAdapter] = exchange_adapter
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
        self._reservation_store = ReservationStore(db_path=reservation_db_path)
        import asyncio
        self._execution_lock = asyncio.Lock()

    def attach_adapter(self, adapter: WriteExchangeAdapter) -> None:
        """Attach (or replace) the exchange write adapter at runtime."""
        self._adapter = adapter

    @staticmethod
    def _build_idempotency_key(signal: Dict[str, Any], record: ExecutionRecord, symbol: str, side: str) -> str:
        """Build a stable fallback idempotency key for callers that do not pass one.

        Production callers should pass an explicit key from EntryDecision. This
        fallback still includes the fields from the remediation plan so unrelated
        tests/runs with the same signal id do not collide with stale reservations.
        """
        strategy = signal.get("strategy") or signal.get("signal_strategy") or "default"
        bucket = signal.get("decision_timestamp_bucket")
        if not bucket:
            entry_time = signal.get("entry_time")
            bucket = str(entry_time)[:16] if entry_time else record.timestamp
        signal_id = signal.get("id") or record.signal_id
        return f"{signal_id}:{symbol}:{side}:{strategy}:{bucket}"

    # ── Public API ─────────────────────────────────────────────────────────────

    def submit_paper(
        self,
        signal: Dict[str, Any],
        candle: Dict[str, Any],
        notional_usdt: Optional[float] = None,
        urgency: str = Urgency.NORMAL,
    ) -> ExecutionRecord:
        """
        Simulate order submission in paper/backtest mode.
        Uses synthetic liquidity from the candle.
        """
        coin = signal.get("coin", "BTC")
        side = self._signal_to_side(signal.get("signal_raw", signal.get("signal", "")))
        decision_price = float(candle.get("close", 0.0))

        # Notional sizing: use caller-provided size when available, otherwise
        # keep the legacy default of 1% of 10k capital for direct paper tests.
        if notional_usdt is None:
            capital = 10_000.0
            notional_usdt = capital * 0.01
        qty = notional_usdt / decision_price if decision_price > 0 else 0.0

        record = ExecutionRecord(
            signal_id=signal.get("id", str(uuid.uuid4())[:8]),
            prediction_id=signal.get("prediction_id", ""),
            entry_decision_id=signal.get("entry_decision_id") or signal.get("decision_id", ""),
            model_version=signal.get("model_version", ""),
            model_artifact_sha256=signal.get("model_artifact_sha256", ""),
            feature_schema_version=signal.get("feature_schema_version", ""),
            deployment_id=signal.get("deployment_id", ""),
            decision_context=signal.get("decision_context", ""),
            caller_context=signal.get("caller_context", ""),
            reservation_id=signal.get("reservation_id", ""),
            idempotency_key=signal.get("idempotency_key", ""),
            client_order_id=signal.get("client_order_id", ""),
            exchange_order_id=signal.get("exchange_order_id", ""),
            position_id=signal.get("position_id", ""),
            lifecycle_schema_version=signal.get("lifecycle_schema_version", "trade-lifecycle-v1"),
            coin=coin,
            side=side,
            intended_qty=qty,
            intended_notional=notional_usdt,
            decision_price=decision_price,
            timestamp=signal.get("entry_time", datetime.now(timezone.utc).isoformat()),
            fill_source="real_paper",
            execution_mode="paper",
            paper_run_id=os.getenv("PAPER_RUN_ID", "").strip(),
        )

        intent = signal.get("intent", OrderIntent.ENTRY)
        is_entry = intent in (OrderIntent.ENTRY, OrderIntent.ADD_POSITION)
        if is_entry:
            symbol = f"{coin}/USDT"
            reservation_id = signal.get("reservation_id") or f"res-{uuid.uuid4()}"
            idempotency_key = signal.get("idempotency_key") or self._build_idempotency_key(signal, record, symbol, side)
            rec_res, created_new = self._reservation_store.reserve(
                reservation_id=reservation_id,
                idempotency_key=idempotency_key,
                entry_decision_id=record.entry_decision_id or record.signal_id,
                symbol=symbol,
                side=side.lower(),
                reserved_notional=notional_usdt,
                signal_id=record.signal_id,
                prediction_id=record.prediction_id,
                model_version=record.model_version,
                model_artifact_sha256=record.model_artifact_sha256,
                feature_schema_version=record.feature_schema_version,
                deployment_id=record.deployment_id,
                decision_context=record.decision_context,
                caller_context=record.caller_context,
            )
            record.reservation_id = rec_res.reservation_id
            record.idempotency_key = rec_res.idempotency_key
            record.client_order_id = signal.get("client_order_id") or rec_res.idempotency_key
            if not created_new and rec_res.status in (ReservationStatus.COMMITTED, ReservationStatus.PARTIALLY_COMMITTED):
                record.status = OrderStatus.FILLED
                record.reason = "duplicate_idempotency_key_already_committed"
                record.filled_qty = rec_res.filled_notional / decision_price if decision_price > 0 else 0.0
                record.avg_fill_price = decision_price
                record.submit_time = datetime.now(timezone.utc).isoformat()
                self._tracker._history.append(record)
                self._tracker._write_jsonl(record)
                return record
            if not created_new and rec_res.status in (ReservationStatus.RELEASED, ReservationStatus.EXPIRED):
                record.status = OrderStatus.REJECTED
                record.reason = f"reservation_{rec_res.status.value}"
                self._tracker._history.append(record)
                self._tracker._write_jsonl(record)
                return record
            if signal.get("simulate_timeout_after_reserve"):
                record.status = OrderStatus.TIMEOUT
                record.reason = "simulated_timeout_after_reserve"
                self._tracker._history.append(record)
                self._tracker._write_jsonl(record)
                return record

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
            if record.reservation_id:
                self._reservation_store.release(record.reservation_id)
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
            if record.reservation_id:
                self._reservation_store.release(record.reservation_id)
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
        fill_fraction = float(signal.get("paper_fill_fraction", 1.0) or 1.0)
        fill_fraction = max(0.0, min(1.0, fill_fraction))
        if fill_fraction < 1.0:
            fill = FillEvent(
                execution_id=record.execution_id,
                price=fill_price,
                qty=record.intended_qty * fill_fraction,
                fee=record.intended_notional * fill_fraction * 0.0005,
            )
            record.add_fill(fill)
            self._tracker._write_jsonl(record)
            if record.reservation_id:
                self._reservation_store.partial_commit(
                    record.reservation_id,
                    filled_notional=record.filled_qty * record.avg_fill_price,
                    client_order_id=record.client_order_id,
                )
            if signal.get("paper_cancel_remaining"):
                self._tracker.cancel(record.execution_id, reason="paper_cancel_remaining")
                if record.reservation_id:
                    self._reservation_store.release(record.reservation_id)
            return record

        self._tracker.simulate_fill(record, fill_price=fill_price)
        if signal.get("simulate_crash_after_fill_before_commit"):
            return record
        if record.reservation_id:
            filled_notional = record.filled_qty * record.avg_fill_price
            if filled_notional < 0.9 * notional_usdt:
                self._reservation_store.partial_commit(
                    record.reservation_id,
                    filled_notional=filled_notional,
                    client_order_id=record.client_order_id,
                )
            else:
                self._reservation_store.commit(
                    record.reservation_id,
                    filled_notional=filled_notional,
                    client_order_id=record.client_order_id,
                )

        logger.debug(
            f"[Execution] FILLED {coin} {side} @ {fill_price:.4f} "
            f"(slip {expected_slip:.1f} bps, liq {snap.liquidity_score:.2f})"
        )
        return record

    async def _dispatch_live_order(
        self,
        *,
        order_decision: OrderDecision,
        side: str,
        symbol: str,
        notional_usdt: float,
        limit_price: float,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Submit the selected live order type without silently changing it.

        TWAP is intentionally fail-closed until there is a complete live child
        order dispatcher and recovery story.
        """
        if self._adapter is None:
            raise RuntimeError("live exchange adapter is not attached")

        order_type = order_decision.order_type
        is_buy = side == "BUY"
        if order_type == OrderType.MARKET:
            return (
                await self._adapter.create_market_buy(symbol, notional_usdt, params)
                if is_buy else
                await self._adapter.create_market_sell(symbol, notional_usdt, params)
            )

        if order_type in (OrderType.LIMIT, OrderType.AGGRESSIVE_LIMIT, OrderType.LIMIT_MAKER):
            if limit_price <= 0:
                raise ValueError(f"{order_type} requires a positive limit_price")
            order_params = dict(params)
            if order_decision.time_in_force:
                order_params["timeInForce"] = order_decision.time_in_force
            return (
                await self._adapter.create_limit_buy(symbol, notional_usdt, limit_price, order_params)
                if is_buy else
                await self._adapter.create_limit_sell(symbol, notional_usdt, limit_price, order_params)
            )

        if order_type == OrderType.TWAP:
            raise NotImplementedError("TWAP live dispatch is disabled until E2E recovery tests exist")

        raise ValueError(f"unsupported live order type: {order_type}")

    async def submit_live(
        self,
        signal: Dict[str, Any],
        candle: Dict[str, Any],
        notional_usdt: float,
        urgency: str = Urgency.NORMAL,
    ) -> ExecutionRecord:
        """
        Execute a LIVE order through the exchange via the isolated WriteExchangeAdapter.
        Runs full pre-trade guard: liquidity → slippage → risk → order selection.
        This is the ONLY entry point for live write operations.

        Args:
            signal: dict with 'coin', 'signal_raw'/'signal', 'id', 'entry_time'
            candle: latest OHLCV candle dict
            notional_usdt: position size in USDT
            urgency: Urgency.NORMAL | Urgency.HIGH
        """
        if any(flag in signal for flag in PAPER_RECOVERY_SIMULATION_FLAGS):
            raise ValueError("Paper recovery simulation flags are not allowed in live mode")

        if self._adapter is None:
            logger.warning("[ExecutionEngine] No exchange adapter — falling back to paper mode")
            return self.submit_paper(signal, candle, notional_usdt=notional_usdt, urgency=urgency)

        coin = signal.get("coin", "BTC")
        side = self._signal_to_side(signal.get("signal_raw", signal.get("signal", "")))
        symbol = f"{coin}/USDT"

        # Get current market price from exchange
        try:
            t0 = time.time()
            decision_price = await self._adapter.get_symbol_price(symbol)
            latency_ms = int((time.time() - t0) * 1000)
        except Exception as exc:
            logger.error(f"[ExecutionEngine] Cannot fetch price for {symbol}: {exc}")
            decision_price = float(candle.get("close", 0.0))
            latency_ms = 9999

        qty = notional_usdt / decision_price if decision_price > 0 else 0.0

        record = ExecutionRecord(
            signal_id=signal.get("id", str(uuid.uuid4())[:8]),
            prediction_id=signal.get("prediction_id", ""),
            entry_decision_id=signal.get("entry_decision_id") or signal.get("decision_id", ""),
            model_version=signal.get("model_version", ""),
            model_artifact_sha256=signal.get("model_artifact_sha256", ""),
            feature_schema_version=signal.get("feature_schema_version", ""),
            deployment_id=signal.get("deployment_id", ""),
            decision_context=signal.get("decision_context", ""),
            caller_context=signal.get("caller_context", ""),
            reservation_id=signal.get("reservation_id", ""),
            idempotency_key=signal.get("idempotency_key", ""),
            client_order_id=signal.get("client_order_id", ""),
            exchange_order_id=signal.get("exchange_order_id", ""),
            position_id=signal.get("position_id", ""),
            lifecycle_schema_version=signal.get("lifecycle_schema_version", "trade-lifecycle-v1"),
            coin=coin,
            side=side,
            intended_qty=qty,
            intended_notional=notional_usdt,
            decision_price=decision_price,
            timestamp=signal.get("entry_time", datetime.now(timezone.utc).isoformat()),
            latency_ms=latency_ms,
            fill_source="live",
            execution_mode="live",
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

        # ── Central LiveExecutionGuard validation with atomic snapshot and concurrency lock ──
        from .live_execution_guard import OrderContext, LiveStateSnapshot
        from .hard_risk_limits import OrderIntent
        from pathlib import Path
        import json

        async with self._execution_lock:
            intent = signal.get("intent", OrderIntent.ENTRY)
            intent_value = str(getattr(intent, "value", intent)).upper()
            is_entry = intent_value in {
                str(getattr(OrderIntent.ENTRY, "value", OrderIntent.ENTRY)).upper(),
                str(getattr(OrderIntent.ADD_POSITION, "value", OrderIntent.ADD_POSITION)).upper(),
            }
            risk_state_failures: list[str] = []
            open_positions_count = 0
            try:
                from btc_scraper.trading.exposure_manager import exposure_manager
                open_positions = exposure_manager.get_open_positions()
                if open_positions is None:
                    raise ValueError("position state returned None")
                open_positions_count = len(open_positions)
            except Exception as exc:
                risk_state_failures.append(f"position_state_unavailable:{type(exc).__name__}")

            portfolio_equity_usdt = 0.0
            try:
                portfolio_equity_usdt = float(await self._adapter.get_usdt_balance())
                if not math.isfinite(portfolio_equity_usdt) or portfolio_equity_usdt <= 0:
                    raise ValueError("invalid portfolio equity")
            except Exception as exc:
                risk_state_failures.append(f"equity_unavailable:{type(exc).__name__}")

            current_stage = 1
            try:
                rollout_path = build_execution_data_path("rollout_state.json")
                if rollout_path.exists():
                    rollout_data = json.loads(rollout_path.read_text(encoding="utf-8"))
                    current_stage = int(rollout_data.get("current_stage", 1))
            except Exception:
                pass

            if is_entry and risk_state_failures:
                reason = "BLOCK_ENTRY:risk_data_unavailable:" + ",".join(risk_state_failures)
                logger.error("[ExecutionEngine] %s", reason)
                record.guard_action = "REJECT"
                return self._tracker.reject(record, reason=reason)

            # ── SQLite Atomic Reservation Gate ──
            reservation_id = None

            if is_entry:
                reservation_id = f"res-{uuid.uuid4()}"
                idempotency_key = signal.get("idempotency_key") or self._build_idempotency_key(signal, record, symbol, side)
                record.reservation_id = reservation_id
                record.idempotency_key = idempotency_key
                record.client_order_id = idempotency_key

                rec_res, created_new = self._reservation_store.reserve(
                    reservation_id=reservation_id,
                    idempotency_key=idempotency_key,
                    entry_decision_id=record.entry_decision_id or record.signal_id,
                    symbol=symbol,
                    side=side.lower(),
                    reserved_notional=notional_usdt,
                    signal_id=record.signal_id,
                    prediction_id=record.prediction_id,
                    model_version=record.model_version,
                    model_artifact_sha256=record.model_artifact_sha256,
                    feature_schema_version=record.feature_schema_version,
                    deployment_id=record.deployment_id,
                    decision_context=record.decision_context,
                    caller_context=record.caller_context,
                )
                reservation_id = rec_res.reservation_id
                idempotency_key = rec_res.idempotency_key
                record.reservation_id = reservation_id
                record.idempotency_key = idempotency_key
                record.client_order_id = idempotency_key

                if not created_new:
                    logger.warning(f"[ExecutionEngine] Duplicate request detected via idempotency: {idempotency_key}")
                    if rec_res.status in (ReservationStatus.COMMITTED, ReservationStatus.PARTIALLY_COMMITTED):
                        record.status = OrderStatus.FILLED
                        record.reason = "Duplicate request already completed"
                        return record
                    elif rec_res.status == ReservationStatus.PENDING:
                        record.guard_action = "REJECT"
                        return self._tracker.reject(record, reason="Duplicate request in progress")
                    else:
                        record.guard_action = "REJECT"
                        return self._tracker.reject(
                            record,
                            reason="Idempotency key already used; reconciliation required",
                        )

            # Add active totals from SQLite store to pre-trade count
            active_notional, active_slots = self._reservation_store.get_active_notional_and_slots(
                exclude_reservation_id=reservation_id
            )
            open_positions_count += active_slots

            state_snap = LiveStateSnapshot(
                observed_at=datetime.now(timezone.utc),
                portfolio_equity_usdt=portfolio_equity_usdt,
                open_positions_count=open_positions_count,
                rollout_stage=current_stage,
            )

            ctx = OrderContext(
                symbol=symbol,
                intent=intent,
                notional_usdt=notional_usdt,
                spread_bps=snap.spread_bps,
                expected_slippage_bps=expected_slip,
                liquidity_score=snap.liquidity_score,
                latency_ms=latency_ms,
                state=state_snap,
            )

            guard_result = self._live_guard.validate(ctx)
            if not guard_result.allowed:
                logger.warning(f"[ExecutionEngine] LiveExecutionGuard BLOCKED: {guard_result.reason}")
                if reservation_id:
                    self._reservation_store.release(reservation_id)
                record.guard_action = "REJECT"
                return self._tracker.reject(record, reason=guard_result.reason)

            # ── 3. Pre-trade risk check (legacy execution risk monitor) ───────────────────────
            guard = self._risk.evaluate(
                spread_bps=snap.spread_bps,
                expected_slippage_bps=expected_slip,
                liquidity_score=snap.liquidity_score,
                order_notional_usdt=notional_usdt,
                max_safe_order_size_usdt=snap.max_safe_order_size_usdt,
                latency_ms=latency_ms,
            )
            record.guard_action = guard.action

            if guard.action == GuardAction.REJECT:
                logger.info(f"[ExecutionEngine] LIVE REJECTED {coin} {side}: {guard.reason}")
                if reservation_id:
                    self._reservation_store.release(reservation_id)
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
                if reservation_id:
                    self._reservation_store.release(reservation_id)
                return self._tracker.reject(record, reason=order_decision.reason)

            record.order_type = order_decision.order_type
            record.submitted_price = order_decision.limit_price or decision_price
            record.submit_time = datetime.now(timezone.utc).isoformat()

            if order_decision.order_type == OrderType.TWAP:
                if reservation_id:
                    self._reservation_store.release(reservation_id)
                record.guard_action = "REJECT"
                return self._tracker.reject(
                    record,
                    reason="TWAP live dispatch disabled until E2E recovery tests exist",
                )

            # ── 5. Execute via WriteExchangeAdapter ──────────────────────────
            self._tracker.register(record)
            try:
                params = {}
                if reservation_id:
                    params["clientOrderId"] = idempotency_key
                    params["reservationId"] = reservation_id

                order = await self._dispatch_live_order(
                    order_decision=order_decision,
                    side=side,
                    symbol=symbol,
                    notional_usdt=notional_usdt,
                    limit_price=record.submitted_price,
                    params=params,
                )

                # Build fill from exchange response
                fill_price = float(order.get("price") or record.submitted_price)
                fill_qty = float(order.get("amount") or qty)
                fee = float(order.get("fee", {}).get("cost", 0.0) if isinstance(order.get("fee"), dict) else 0.0)
                if fee == 0.0:
                    fee = notional_usdt * 0.0005  # fallback: 5 bps taker

                fill = FillEvent(
                    execution_id=record.execution_id,
                    price=fill_price,
                    qty=fill_qty,
                    fee=fee,
                )
                record.add_fill(fill)
                record.status = OrderStatus.FILLED
                self._tracker._complete(record)
                self._tracker._write_jsonl(record)

                logger.info(
                    f"[ExecutionEngine] LIVE FILLED {coin} {side} @ {fill_price:.4f} "
                    f"qty={fill_qty:.6f} fee={fee:.4f} "
                    f"(slip {expected_slip:.1f} bps, liq {snap.liquidity_score:.2f})"
                )

                # SQLite Reservation store updates
                if reservation_id:
                    filled_notional = fill_qty * fill_price
                    ex_id = order.get("id")
                    record.exchange_order_id = str(ex_id or "")
                    if filled_notional < 0.9 * notional_usdt:
                        self._reservation_store.partial_commit(
                            reservation_id,
                            filled_notional=filled_notional,
                            exchange_order_id=ex_id,
                            client_order_id=idempotency_key,
                        )
                    else:
                        self._reservation_store.commit(
                            reservation_id,
                            filled_notional=filled_notional,
                            exchange_order_id=ex_id,
                            client_order_id=idempotency_key,
                        )

                # ── 6. Post-trade analysis ───────────────────────────────────
                self._post_trade.analyze(record.to_dict())

            except Exception as exc:
                logger.error(f"[ExecutionEngine] Order submission failed: {exc}")
                if reservation_id:
                    self._reservation_store.release(reservation_id)
                record.status = OrderStatus.REJECTED
                record.reason = str(exc)
                self._tracker._history.append(record)
                self._tracker._write_jsonl(record)

        return record

    async def emergency_exit(
        self,
        coin: str,
        direction: str,
        invested_usdt: float,
        current_price: float,
        reason: str = "emergency",
    ) -> ExecutionRecord:
        """
        Emergency exit policy: close a position IMMEDIATELY at market.
        Bypasses slippage/liquidity checks — uses REJECT-safe path only if adapter is missing.
        Only spreads and latency guard still apply (for catastrophic failure protection).
        """
        symbol = f"{coin.upper()}/USDT"
        side = "SELL" if direction == "LONG" else "BUY"
        record = ExecutionRecord(
            signal_id=f"EMERGENCY-{coin}-{int(time.time())}",
            coin=coin,
            side=side,
            intended_qty=invested_usdt / current_price if current_price > 0 else 0.0,
            intended_notional=invested_usdt,
            decision_price=current_price,
            timestamp=datetime.now(timezone.utc).isoformat(),
            order_type="MARKET",
            fill_source="live",
            execution_mode="live",
        )
        record.reason = reason

        if self._adapter is None:
            logger.warning(f"[ExecutionEngine] Emergency exit paper mode: {coin} {side}")
            self._tracker.register(record)
            self._tracker.simulate_fill(record, fill_price=current_price)
            return record

        try:
            # Close the exchange-reported base quantity.  A notional/price
            # estimate can leave a residual (or reverse the position) when
            # the price moves between entry and exit.
            signed_qty = await self._adapter.get_open_position_qty(symbol)
            if signed_qty == 0:
                raise RuntimeError(f"No open exchange position for {symbol}")

            side = "SELL" if signed_qty > 0 else "BUY"
            quantity = abs(signed_qty)
            record.side = side
            record.intended_qty = quantity
            record.intended_notional = quantity * current_price
            self._tracker.register(record)
            order = await self._adapter.close_position_market(symbol, side, quantity)

            fill_price = float(order.get("price") or current_price)
            fill = FillEvent(
                execution_id=record.execution_id,
                price=fill_price,
                qty=float(order.get("filled") or order.get("amount") or quantity),
                fee=record.intended_notional * 0.0005,
            )
            record.add_fill(fill)
            record.status = OrderStatus.FILLED
            self._tracker._complete(record)
            self._tracker._write_jsonl(record)
            logger.info(f"[ExecutionEngine] EMERGENCY EXIT {coin} {side} @ {fill_price:.4f}")
        except Exception as exc:
            logger.error(f"[ExecutionEngine] Emergency exit failed: {exc}")
            record.status = OrderStatus.REJECTED
            record.reason = f"emergency_failed: {exc}"
            self._tracker._history.append(record)
            self._tracker._write_jsonl(record)

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
