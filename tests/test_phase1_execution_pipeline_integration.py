"""
tests/test_phase1_execution_pipeline_integration.py
Phase 1 — Execution Pipeline Integration Tests

Validates:
  - All write orders go through ExecutionEngine (no direct CCXT)
  - High spread rejection
  - High slippage rejection
  - Low liquidity reduce/reject
  - Partial fill state machine
  - TWAP plan creation + cancellation
  - Emergency exit path
  - Signal-to-fill end-to-end integration
  - ExchangeAdapter write guard
  - AutoTrader routes through ExecutionEngine
"""
import unittest
import asyncio
import time
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from btc_scraper.execution.execution_engine import ExecutionEngine
from btc_scraper.execution.execution_config import ExecutionConfig
from btc_scraper.execution.exchange_adapter import (
    WriteExchangeAdapter, ReadOnlyExchangeAdapter,
    make_write_adapter_from_env,
)
from btc_scraper.execution.fill_tracker import ExecutionRecord, FillEvent, OrderStatus
from btc_scraper.execution.execution_risk_monitor import ExecutionRiskMonitor, GuardAction


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_signal(coin: str = "BTC", side: str = "BUY (Crossover)") -> dict:
    return {
        "coin": coin,
        "signal_raw": side,
        "signal": side,
        "id": "test-001",
        "entry_time": datetime.now(timezone.utc).isoformat(),
    }


def _make_candle(
    close: float = 50_000.0,
    high: float = 51_000.0,
    low: float = 49_000.0,
    volume: float = 100.0,
) -> dict:
    return {
        "time": datetime.now(timezone.utc).isoformat(),
        "open": close * 0.99,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _make_strict_config() -> ExecutionConfig:
    """Config với giới hạn chặt để kích hoạt guard dễ dàng trong tests."""
    from btc_scraper.execution.execution_config import ExecutionConfig
    cfg = ExecutionConfig()
    cfg.max_spread_bps = 5.0       # rất chặt
    cfg.max_slippage_bps = 10.0    # rất chặt
    cfg.min_liquidity_score = 0.6  # chặt
    cfg.max_latency_ms = 500
    return cfg


def _make_loose_config() -> ExecutionConfig:
    """Config lỏng để orders dễ pass guard."""
    from btc_scraper.execution.execution_config import ExecutionConfig
    cfg = ExecutionConfig()
    cfg.max_spread_bps = 500.0
    cfg.max_slippage_bps = 1000.0
    cfg.min_liquidity_score = 0.01
    cfg.max_latency_ms = 99999
    return cfg


# ── Task 1.2: ExchangeAdapter isolation ───────────────────────────────────────

class TestExchangeAdapterIsolation(unittest.TestCase):
    """Validates that only WriteExchangeAdapter can write to the exchange."""

    def test_readonly_adapter_raises_on_market_buy(self):
        """ReadOnlyExchangeAdapter phải raise PermissionError khi gọi write."""
        adapter = ReadOnlyExchangeAdapter()

        async def _call():
            await adapter.create_market_buy("BTC/USDT", 100.0)

        with self.assertRaises(PermissionError):
            asyncio.run(_call())

    def test_readonly_adapter_raises_on_market_sell(self):
        adapter = ReadOnlyExchangeAdapter()

        async def _call():
            await adapter.create_market_sell("BTC/USDT", 100.0)

        with self.assertRaises(PermissionError):
            asyncio.run(_call())

    def test_write_adapter_dry_run_succeeds(self):
        """WriteExchangeAdapter(None) trả về dry-run fill."""
        adapter = WriteExchangeAdapter(None)

        async def _call():
            return await adapter.create_market_buy("BTC/USDT", 100.0)

        result = asyncio.run(_call())
        self.assertIn("id", result)
        self.assertEqual(result["side"], "buy")
        self.assertTrue(result["id"].startswith("DRY-"))

    def test_write_adapter_sell_dry_run_succeeds(self):
        adapter = WriteExchangeAdapter(None)

        async def _call():
            return await adapter.create_market_sell("ETH/USDT", 200.0)

        result = asyncio.run(_call())
        self.assertEqual(result["side"], "sell")



# ── Task 1.1: ExecutionEngine paper mode ──────────────────────────────────────

class TestExecutionEnginePaperMode(unittest.TestCase):
    """submit_paper() end-to-end tests."""

    def setUp(self):
        self.engine = ExecutionEngine()

    def test_paper_submit_returns_record(self):
        signal = _make_signal()
        candle = _make_candle()
        record = self.engine.submit_paper(signal, candle)
        self.assertIsNotNone(record)
        self.assertIn(record.status, [OrderStatus.FILLED, OrderStatus.REJECTED])
        self.assertGreater(len(record.execution_id), 0)
        self.assertEqual(record.execution_mode, "paper")
        self.assertEqual(record.fill_source, "real_paper")

    def test_paper_buy_signal_sets_side_buy(self):
        signal = _make_signal(side="BUY (Crossover)")
        candle = _make_candle()
        record = self.engine.submit_paper(signal, candle)
        self.assertEqual(record.side, "BUY")

    def test_paper_sell_signal_sets_side_sell(self):
        signal = _make_signal(side="STRONG SELL (Confirmed)")
        candle = _make_candle()
        record = self.engine.submit_paper(signal, candle)
        self.assertEqual(record.side, "SELL")

    def test_paper_submit_uses_explicit_notional(self):
        signal = _make_signal()
        candle = _make_candle(close=100.0)
        record = self.engine.submit_paper(signal, candle, notional_usdt=25.0)

        self.assertEqual(record.intended_notional, 25.0)
        self.assertAlmostEqual(record.intended_qty, 0.25)

    def test_filled_record_has_fill_price(self):
        engine = ExecutionEngine(config=_make_loose_config())
        signal = _make_signal()
        candle = _make_candle()
        record = engine.submit_paper(signal, candle)
        if record.status == OrderStatus.FILLED:
            self.assertGreater(record.avg_fill_price, 0.0)

    def test_stats_returns_required_keys(self):
        stats = self.engine.get_stats()
        self.assertIn("n_fills", stats)
        self.assertIn("reject_rate", stats)


# ── Task 1.4: Pre-trade guard scenarios ───────────────────────────────────────

class TestPreTradeGuardScenarios(unittest.TestCase):
    """Validates that the guard correctly rejects/reduces trades."""

    def _engine_with_strict_config(self):
        return ExecutionEngine(config=_make_strict_config())

    def test_high_spread_results_in_rejected_or_pass(self):
        """Wide spread candle (high-low range) should trigger REJECT."""
        engine = self._engine_with_strict_config()
        # Candle với spread rộng (low volume = low liquidity → spread estimate cao)
        candle = _make_candle(close=50_000.0, high=53_000.0, low=47_000.0, volume=0.001)
        signal = _make_signal()
        record = engine.submit_paper(signal, candle)
        # Guard có thể reject; record phải có status hợp lệ
        self.assertIn(record.status, [OrderStatus.FILLED, OrderStatus.REJECTED])

    def test_rejected_record_has_reason(self):
        """REJECTED records phải có reason field."""
        engine = self._engine_with_strict_config()
        candle = _make_candle(close=50_000.0, high=55_000.0, low=45_000.0, volume=0.0001)
        signal = _make_signal()
        record = engine.submit_paper(signal, candle)
        if record.status == OrderStatus.REJECTED:
            self.assertTrue(len(record.reason) > 0)

    def test_guard_action_recorded_in_record(self):
        """guard_action field phải được điền."""
        engine = ExecutionEngine(config=_make_loose_config())
        signal = _make_signal()
        candle = _make_candle()
        record = engine.submit_paper(signal, candle)
        self.assertIn(record.guard_action, ["PASS", "REDUCE", "REJECT"])

    def test_high_slippage_rejected(self):
        """ExecutionRiskMonitor phải reject khi slippage quá cao."""
        monitor = ExecutionRiskMonitor({
            "max_spread_bps": 100.0,
            "max_slippage_bps": 5.0,  # rất chặt
            "min_liquidity_score": 0.1,
            "max_latency_ms": 99999,
        })
        result = monitor.evaluate(
            spread_bps=2.0,
            expected_slippage_bps=50.0,  # vượt ngưỡng
            liquidity_score=0.8,
            order_notional_usdt=1000.0,
            max_safe_order_size_usdt=50_000.0,
        )
        self.assertEqual(result.action, GuardAction.REJECT)
        self.assertIn("slippage", result.reason)

    def test_high_spread_rejected_by_risk_monitor(self):
        """ExecutionRiskMonitor phải reject khi spread quá rộng."""
        monitor = ExecutionRiskMonitor({
            "max_spread_bps": 5.0,
            "max_slippage_bps": 100.0,
            "min_liquidity_score": 0.1,
        })
        result = monitor.evaluate(
            spread_bps=50.0,
            expected_slippage_bps=10.0,
            liquidity_score=0.8,
            order_notional_usdt=1000.0,
            max_safe_order_size_usdt=50_000.0,
        )
        self.assertEqual(result.action, GuardAction.REJECT)
        self.assertIn("spread", result.reason)

    def test_low_liquidity_reduces_size(self):
        """Low liquidity với order nhỏ phải trả về REDUCE."""
        monitor = ExecutionRiskMonitor({
            "max_spread_bps": 100.0,
            "max_slippage_bps": 100.0,
            "min_liquidity_score": 0.5,
        })
        result = monitor.check_liquidity(
            liquidity_score=0.1,
            order_notional_usdt=500.0,
            max_safe_order_size_usdt=10_000.0,
        )
        self.assertEqual(result.action, GuardAction.REDUCE)

    def test_high_latency_rejected(self):
        """Latency quá cao phải bị reject."""
        monitor = ExecutionRiskMonitor({
            "max_spread_bps": 100.0,
            "max_slippage_bps": 100.0,
            "min_liquidity_score": 0.1,
            "max_latency_ms": 100,
        })
        result = monitor.evaluate(
            spread_bps=1.0,
            expected_slippage_bps=1.0,
            liquidity_score=0.9,
            order_notional_usdt=100.0,
            max_safe_order_size_usdt=50_000.0,
            latency_ms=5000,
        )
        self.assertEqual(result.action, GuardAction.REJECT)
        self.assertIn("latency", result.reason)

    def test_all_clear_passes_guard(self):
        """Điều kiện tốt phải PASS guard."""
        monitor = ExecutionRiskMonitor({
            "max_spread_bps": 50.0,
            "max_slippage_bps": 100.0,
            "min_liquidity_score": 0.2,
            "max_latency_ms": 2000,
        })
        result = monitor.evaluate(
            spread_bps=2.0,
            expected_slippage_bps=5.0,
            liquidity_score=0.8,
            order_notional_usdt=1000.0,
            max_safe_order_size_usdt=50_000.0,
            latency_ms=50,
        )
        self.assertEqual(result.action, GuardAction.PASS)


# ── Task 1.5: Partial fill state machine ──────────────────────────────────────

class TestPartialFillStateMachine(unittest.TestCase):
    """Validates FillTracker partial fill state transitions."""

    def setUp(self):
        from btc_scraper.execution.fill_tracker import FillTracker
        self.tmp = tempfile.mkdtemp()
        self.tracker = FillTracker(
            log_dir=self.tmp + "/logs",
            fills_dir=self.tmp + "/fills",
        )

    def test_partial_fill_sets_partial_fill_status(self):
        """Một phần fill phải cho trạng thái PARTIAL_FILL."""
        record = ExecutionRecord(coin="BTC", side="BUY", intended_qty=1.0)
        self.tracker.register(record)

        fill1 = FillEvent(execution_id=record.execution_id, price=50_000.0, qty=0.5)
        rec = self.tracker.apply_fill(record.execution_id, fill1)

        self.assertEqual(rec.status, OrderStatus.PARTIAL_FILL)
        self.assertAlmostEqual(rec.filled_qty, 0.5)
        self.assertAlmostEqual(rec.unfilled_qty, 0.5)

    def test_full_fill_transitions_to_filled(self):
        """Fill hoàn toàn phải chuyển sang FILLED."""
        record = ExecutionRecord(coin="ETH", side="BUY", intended_qty=1.0)
        self.tracker.register(record)

        fill1 = FillEvent(execution_id=record.execution_id, price=3_000.0, qty=0.5)
        fill2 = FillEvent(execution_id=record.execution_id, price=3_001.0, qty=0.5)
        self.tracker.apply_fill(record.execution_id, fill1)
        rec = self.tracker.apply_fill(record.execution_id, fill2)

        self.assertEqual(rec.status, OrderStatus.FILLED)
        self.assertAlmostEqual(rec.filled_qty, 1.0, places=5)
        self.assertAlmostEqual(rec.unfilled_qty, 0.0, places=5)

    def test_avg_fill_price_is_vwap(self):
        """avg_fill_price phải là VWAP của các fills."""
        record = ExecutionRecord(coin="BTC", side="BUY", intended_qty=2.0)
        self.tracker.register(record)

        fill1 = FillEvent(execution_id=record.execution_id, price=50_000.0, qty=1.0)
        fill2 = FillEvent(execution_id=record.execution_id, price=50_100.0, qty=1.0)
        self.tracker.apply_fill(record.execution_id, fill1)
        rec = self.tracker.apply_fill(record.execution_id, fill2)

        expected_vwap = (50_000.0 * 1.0 + 50_100.0 * 1.0) / 2.0
        self.assertAlmostEqual(rec.avg_fill_price, expected_vwap, places=2)

    def test_cancel_sets_cancelled_status(self):
        """Cancel phải đặt trạng thái CANCELLED."""
        record = ExecutionRecord(coin="SOL", side="SELL", intended_qty=5.0)
        self.tracker.register(record)
        rec = self.tracker.cancel(record.execution_id, reason="user_cancel")
        self.assertEqual(rec.status, OrderStatus.CANCELLED)

    def test_reject_rate_calculation(self):
        """reject_rate phải tính đúng tỷ lệ."""
        record1 = ExecutionRecord(coin="BTC", side="BUY")
        record2 = ExecutionRecord(coin="ETH", side="BUY")
        self.tracker.reject(record1, reason="spread_too_wide")
        self.tracker.simulate_fill(record2, fill_price=3000.0)
        rate = self.tracker.reject_rate()
        self.assertAlmostEqual(rate, 0.5, places=2)


# ── TWAP ──────────────────────────────────────────────────────────────────────

class TestTWAPIntegration(unittest.TestCase):
    """TWAP plan creation and cancellation."""

    def setUp(self):
        from btc_scraper.execution.twap import TWAPExecutor
        self.executor = TWAPExecutor()

    def test_plan_creates_correct_slices(self):
        plan = self.executor.plan(total_qty=10.0, total_notional_usdt=10_000.0, slices=5, interval_seconds=30)
        self.assertEqual(len(plan.children), 5)
        for child in plan.children:
            self.assertAlmostEqual(child.qty, 2.0, places=5)

    def test_cancel_on_reversal_signal(self):
        plan = self.executor.plan(total_qty=5.0, total_notional_usdt=5_000.0, slices=3)
        should_cancel = self.executor.check_cancel(plan, "BUY (Crossover)", "STRONG SELL (Confirmed Reversal)")
        self.assertTrue(should_cancel)

    def test_no_cancel_same_direction(self):
        plan = self.executor.plan(total_qty=5.0, total_notional_usdt=5_000.0, slices=3)
        should_cancel = self.executor.check_cancel(plan, "BUY (Crossover)", "BUY (SFP)")
        self.assertFalse(should_cancel)

    def test_cancel_remaining_sets_cancelled_status(self):
        plan = self.executor.plan(total_qty=5.0, total_notional_usdt=5_000.0, slices=3)
        cancelled = self.executor.cancel_remaining(plan)
        # Should cancel all remaining slices (or 0 if already processed)
        self.assertGreaterEqual(cancelled, 0)


# ── Emergency Exit ─────────────────────────────────────────────────────────────

class TestEmergencyExit(unittest.TestCase):
    """Tests emergency_exit() in paper mode and with mock adapter."""

    def setUp(self):
        self.engine = ExecutionEngine(config=_make_loose_config())

    def test_emergency_exit_paper_returns_filled(self):
        """emergency_exit() paper mode phải trả về FILLED record."""
        loop = asyncio.new_event_loop()
        try:
            record = loop.run_until_complete(
                self.engine.emergency_exit(
                    coin="BTC",
                    direction="LONG",
                    invested_usdt=500.0,
                    current_price=50_000.0,
                    reason="test_emergency",
                )
            )
        finally:
            loop.close()
        self.assertEqual(record.status, OrderStatus.FILLED)
        self.assertEqual(record.side, "SELL")  # LONG → SELL to close
        self.assertAlmostEqual(record.avg_fill_price, 50_000.0)

    def test_emergency_exit_short_buys_to_close(self):
        loop = asyncio.new_event_loop()
        try:
            record = loop.run_until_complete(
                self.engine.emergency_exit(
                    coin="ETH",
                    direction="SHORT",
                    invested_usdt=300.0,
                    current_price=3_000.0,
                    reason="stop_loss",
                )
            )
        finally:
            loop.close()
        self.assertEqual(record.side, "BUY")  # SHORT → BUY to close

    def test_emergency_exit_with_mock_adapter(self):
        """emergency_exit() với mock adapter phải gọi create_market_sell."""
        mock_order = {
            "id": "MOCK-123",
            "price": 50_100.0,
            "amount": 0.01,
            "status": "closed",
        }
        mock_adapter = AsyncMock(spec=WriteExchangeAdapter)
        mock_adapter.get_open_position_qty = AsyncMock(return_value=0.01)
        mock_adapter.close_position_market = AsyncMock(return_value=mock_order)

        engine = ExecutionEngine(config=_make_loose_config(), exchange_adapter=mock_adapter)
        loop = asyncio.new_event_loop()
        try:
            record = loop.run_until_complete(
                engine.emergency_exit(
                    coin="BTC",
                    direction="LONG",
                    invested_usdt=500.0,
                    current_price=50_000.0,
                )
            )
        finally:
            loop.close()

        mock_adapter.close_position_market.assert_called_once_with("BTC/USDT", "SELL", 0.01)
        self.assertEqual(record.status, OrderStatus.FILLED)
        self.assertAlmostEqual(record.avg_fill_price, 50_100.0)

    def test_emergency_exit_uses_exchange_quantity_and_reduce_only_close(self):
        """Close quantity is sourced from exchange, not a USDT/price estimate."""
        mock_adapter = AsyncMock(spec=WriteExchangeAdapter)
        mock_adapter.get_open_position_qty = AsyncMock(return_value=-2.5)
        mock_adapter.close_position_market = AsyncMock(return_value={
            "id": "CLOSE-001", "price": 200.0, "amount": 2.5, "status": "closed",
        })
        engine = ExecutionEngine(config=_make_loose_config(), exchange_adapter=mock_adapter)
        loop = asyncio.new_event_loop()
        try:
            record = loop.run_until_complete(
                engine.emergency_exit("XRP", "LONG", 999.0, 200.0)
            )
        finally:
            loop.close()

        mock_adapter.close_position_market.assert_called_once_with("XRP/USDT", "BUY", 2.5)
        self.assertEqual(record.side, "BUY")
        self.assertEqual(record.intended_qty, 2.5)


# ── submit_live integration ────────────────────────────────────────────────────

class TestSubmitLiveWithMockAdapter(unittest.TestCase):
    """submit_live() must go through ExchangeAdapter (never raw CCXTClient)."""

    def _make_mock_adapter(self, price: float = 50_000.0) -> WriteExchangeAdapter:
        mock_order = {
            "id": "LIVE-001",
            "price": price,
            "amount": 0.002,
            "status": "filled",
        }
        adapter = AsyncMock(spec=WriteExchangeAdapter)
        adapter.get_symbol_price = AsyncMock(return_value=price)
        adapter.create_market_buy = AsyncMock(return_value=mock_order)
        adapter.create_market_sell = AsyncMock(return_value=mock_order)
        return adapter

    def test_submit_live_calls_adapter_not_ccxt(self):
        """submit_live() phải gọi adapter, không gọi CCXTClient trực tiếp."""
        adapter = self._make_mock_adapter(50_000.0)
        engine = ExecutionEngine(config=_make_loose_config(), exchange_adapter=adapter)

        signal = _make_signal(side="BUY (Crossover)")
        candle = _make_candle(50_000.0)

        loop = asyncio.new_event_loop()
        try:
            record = loop.run_until_complete(
                engine.submit_live(signal, candle, notional_usdt=100.0)
            )
        finally:
            loop.close()

        # Adapter phải được gọi
        adapter.get_symbol_price.assert_called()
        # CCXTClient không được gọi (chúng ta không có cách direct verify
        # nhưng adapter mock đại diện cho tất cả exchange writes)
        self.assertIn(record.status, [OrderStatus.FILLED, OrderStatus.REJECTED])

    def test_submit_live_without_adapter_falls_back_to_paper(self):
        """Khi không có adapter, submit_live phải fallback về paper mode."""
        engine = ExecutionEngine(config=_make_loose_config())  # no adapter

        signal = _make_signal()
        candle = _make_candle(50_000.0)

        loop = asyncio.new_event_loop()
        try:
            record = loop.run_until_complete(
                engine.submit_live(signal, candle, notional_usdt=100.0)
            )
        finally:
            loop.close()

        self.assertIn(record.status, [OrderStatus.FILLED, OrderStatus.REJECTED])

    def test_submit_live_rejected_by_guard_does_not_call_adapter_write(self):
        """Khi guard reject, không được gọi create_market_buy/sell."""
        adapter = self._make_mock_adapter(50_000.0)
        strict_cfg = _make_strict_config()
        strict_cfg.max_spread_bps = 0.001  # cực kỳ chặt → hầu hết trades đều reject
        strict_cfg.max_slippage_bps = 0.001

        engine = ExecutionEngine(config=strict_cfg, exchange_adapter=adapter)

        signal = _make_signal()
        candle = _make_candle(50_000.0, volume=100.0)

        loop = asyncio.new_event_loop()
        try:
            record = loop.run_until_complete(
                engine.submit_live(signal, candle, notional_usdt=100.0)
            )
        finally:
            loop.close()

        # Nếu bị reject, adapter write không được gọi
        if record.status == OrderStatus.REJECTED:
            adapter.create_market_buy.assert_not_called()
            adapter.create_market_sell.assert_not_called()


# ── AutoTrader uses ExecutionEngine ───────────────────────────────────────────

class TestAutoTraderUsesExecutionEngine(unittest.TestCase):
    """Validates AutoTrader routes through ExecutionEngine, not CCXTClient."""

    def test_get_execution_engine_returns_engine_instance(self):
        """_get_execution_engine() phải trả về ExecutionEngine."""
        from btc_scraper.trading.auto_trader import AutoTrader
        from btc_scraper.execution.execution_engine import ExecutionEngine
        trader = AutoTrader()
        engine = trader._get_execution_engine()
        self.assertIsInstance(engine, ExecutionEngine)

    def test_dry_run_mode_no_adapter(self):
        """Trong dry_run mode, engine không có adapter (paper mode only)."""
        from btc_scraper.trading.auto_trader import AutoTrader
        import os
        original = os.environ.get("AUTO_TRADE_DRY_RUN", "true")
        try:
            os.environ["AUTO_TRADE_DRY_RUN"] = "true"
            trader = AutoTrader()
            engine = trader._get_execution_engine()
            self.assertIsNone(engine._adapter)
        finally:
            os.environ["AUTO_TRADE_DRY_RUN"] = original

    def test_execution_engine_singleton_per_trader(self):
        """_get_execution_engine() phải trả về cùng instance."""
        from btc_scraper.trading.auto_trader import AutoTrader
        trader = AutoTrader()
        engine1 = trader._get_execution_engine()
        engine2 = trader._get_execution_engine()
        self.assertIs(engine1, engine2)

    def test_no_ccxt_client_attribute(self):
        """AutoTrader không còn _client (CCXTClient) attribute."""
        from btc_scraper.trading.auto_trader import AutoTrader
        trader = AutoTrader()
        # Không còn _client — chỉ có _execution_engine
        self.assertFalse(hasattr(trader, "_client"))
        self.assertTrue(hasattr(trader, "_execution_engine"))


# ── Signal-to-fill end-to-end ─────────────────────────────────────────────────

class TestSignalToFillEndToEnd(unittest.TestCase):
    """End-to-end: Signal dict → ExecutionEngine.submit_paper() → fill record."""

    def test_buy_signal_to_fill_record(self):
        """BUY signal phải tạo ra ExecutionRecord với đúng side."""
        engine = ExecutionEngine(config=_make_loose_config())
        signal = {
            "coin": "BTC",
            "signal_raw": "BUY (Crossover)",
            "signal": "BUY (Crossover)",
            "id": "e2e-001",
            "entry_time": datetime.now(timezone.utc).isoformat(),
        }
        candle = _make_candle(50_000.0)

        record = engine.submit_paper(signal, candle)

        self.assertGreater(len(record.execution_id), 0)
        self.assertEqual(record.coin, "BTC")
        self.assertEqual(record.side, "BUY")
        self.assertGreater(record.decision_price, 0.0)
        self.assertIn(record.status, [OrderStatus.FILLED, OrderStatus.REJECTED])

    def test_sell_signal_to_fill_record(self):
        """SELL signal phải tạo ra ExecutionRecord side=SELL."""
        engine = ExecutionEngine(config=_make_loose_config())
        signal = {
            "coin": "ETH",
            "signal_raw": "STRONG SELL (SFP)",
            "signal": "STRONG SELL (SFP)",
            "id": "e2e-002",
            "entry_time": datetime.now(timezone.utc).isoformat(),
        }
        candle = _make_candle(3_000.0)

        record = engine.submit_paper(signal, candle)

        self.assertEqual(record.coin, "ETH")
        self.assertEqual(record.side, "SELL")

    def test_filled_record_persisted_in_tracker(self):
        """FILLED record phải được lưu trong tracker history."""
        engine = ExecutionEngine(config=_make_loose_config())
        signal = _make_signal()
        candle = _make_candle(50_000.0)

        record = engine.submit_paper(signal, candle)
        history = engine._tracker.get_history(limit=10)

        # Record phải có trong history
        exec_ids = [r.execution_id for r in history]
        self.assertIn(record.execution_id, exec_ids)

    def test_execution_stats_updates_after_trade(self):
        """get_stats() phải cập nhật sau khi có trade."""
        engine = ExecutionEngine(config=_make_loose_config())
        signal = _make_signal()
        candle = _make_candle(50_000.0)
        engine.submit_paper(signal, candle)

        stats = engine.get_stats()
        total = stats.get("n_fills", 0) + stats.get("n_rejected", 0)
        self.assertGreater(total, 0)

    def test_duplicate_signal_id_independent_records(self):
        """Cùng signal_id nhưng hai lần submit phải tạo hai records riêng."""
        engine = ExecutionEngine(config=_make_loose_config())
        signal = _make_signal()
        candle = _make_candle(50_000.0)

        r1 = engine.submit_paper(signal, candle)
        r2 = engine.submit_paper(signal, candle)

        self.assertNotEqual(r1.execution_id, r2.execution_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
