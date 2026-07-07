"""
tests/test_phase10_execution_pipeline.py
Phase 10 – Execution Intelligence Unit Tests

Tests cover:
  - LiquidityAnalyzer composite score
  - SlippagePredictor v1 formula
  - OrderTypeSelector decision logic
  - ExecutionRiskMonitor guard checks
  - TWAPExecutor slice planning + cancel logic
  - PostTradeAnalyzer shortfall formula
  - ExecutionEngine paper dry-run end-to-end
"""
import unittest
from datetime import datetime, timezone

from btc_scraper.execution.liquidity_analyzer import LiquidityAnalyzer
from btc_scraper.execution.slippage_predictor import SlippagePredictorV1
from btc_scraper.execution.order_type_selector import (
    OrderTypeSelector, OrderType, Urgency
)
from btc_scraper.execution.execution_risk_monitor import (
    ExecutionRiskMonitor, GuardAction
)
from btc_scraper.execution.twap import TWAPExecutor
from btc_scraper.execution.post_trade_analyzer import PostTradeAnalyzer
from btc_scraper.execution.execution_engine import ExecutionEngine
from btc_scraper.execution.execution_config import ExecutionConfig


class TestLiquidityAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = LiquidityAnalyzer()

    def test_score_is_between_0_and_1(self):
        snap = self.analyzer.analyze(
            coin="BTC",
            mid_price=50_000.0,
            top_bid=49_995.0,
            top_ask=50_005.0,
            orderbook_bids=[[49_995, 10], [49_990, 8]],
            orderbook_asks=[[50_005, 10], [50_010, 8]],
            volume_1h_usdt=5_000_000.0,
            atr_pct=0.01,
            order_notional_usdt=10_000.0,
        )
        self.assertGreaterEqual(snap.liquidity_score, 0.0)
        self.assertLessEqual(snap.liquidity_score, 1.0)

    def test_spread_computed_correctly(self):
        snap = self.analyzer.analyze(
            coin="ETH",
            mid_price=3_000.0,
            top_bid=2_999.0,
            top_ask=3_001.0,
            volume_1h_usdt=1_000_000.0,
        )
        # spread = (3001-2999)/3000 * 10000 = 6.67 bps
        self.assertAlmostEqual(snap.spread_bps, 6.667, places=1)

    def test_wide_spread_triggers_warning(self):
        analyzer = LiquidityAnalyzer({"max_spread_bps": 10.0})
        snap = analyzer.analyze(
            coin="SOL",
            mid_price=100.0,
            top_bid=99.0,
            top_ask=101.0,
            volume_1h_usdt=500_000.0,
        )
        # spread = (101-99)/100 * 10000 = 200 bps → triggers SKIP
        self.assertEqual(snap.recommended_order_type, "SKIP")
        self.assertIn("spread", snap.liquidity_warning.lower())

    def test_candle_mode(self):
        candle = {"close": 60_000.0, "high": 61_000.0, "low": 59_000.0, "volume": 100.0}
        snap = self.analyzer.analyze_from_candle("BTC", candle, 10_000.0)
        self.assertGreater(snap.liquidity_score, 0.0)
        self.assertGreater(snap.mid_price, 0.0)


class TestSlippagePredictorV1(unittest.TestCase):

    def setUp(self):
        self.predictor = SlippagePredictorV1({"base_slippage_bps": 1.0})

    def test_formula(self):
        # slippage = 1.0 + 0.3*10 + 0.2*(0.02*10000) + 0.4*(1000/50000*100) - 0.2*(0.6*100)
        # = 1.0 + 3.0 + 40.0 + 0.8 + 10.0 - 12.0 = 42.8
        result = self.predictor.predict(
            spread_bps=10.0,
            atr_pct=0.02,
            order_notional_usdt=1_000.0,
            depth_5bps_usdt=50_000.0,
            liquidity_score=0.6,
            volatility_score=0.5,
        )
        self.assertAlmostEqual(result, 42.8, places=1)

    def test_never_negative(self):
        result = self.predictor.predict(
            spread_bps=1.0,
            atr_pct=0.001,
            order_notional_usdt=100.0,
            depth_5bps_usdt=1_000_000.0,
            liquidity_score=0.95,
            volatility_score=0.1,
        )
        self.assertGreaterEqual(result, 0.0)


class TestOrderTypeSelector(unittest.TestCase):

    def setUp(self):
        self.selector = OrderTypeSelector({
            "max_spread_bps": 20.0,
            "max_slippage_bps": 30.0,
            "min_liquidity_score": 0.4,
            "limit_order_max_wait_seconds": 30,
        })

    def _base_kwargs(self):
        return dict(
            side="BUY",
            top_bid=49_998.0,
            top_ask=50_002.0,
            mid_price=50_000.0,
            spread_bps=8.0,
            liquidity_score=0.7,
            expected_slippage_bps=10.0,
            max_safe_order_size_usdt=50_000.0,
            intended_notional_usdt=10_000.0,
            urgency=Urgency.NORMAL,
        )

    def test_high_urgency_returns_market(self):
        kwargs = self._base_kwargs()
        kwargs["urgency"] = Urgency.HIGH
        decision = self.selector.select(**kwargs)
        self.assertEqual(decision.order_type, OrderType.MARKET)

    def test_wide_spread_returns_skip(self):
        kwargs = self._base_kwargs()
        kwargs["spread_bps"] = 50.0
        decision = self.selector.select(**kwargs)
        self.assertEqual(decision.order_type, OrderType.SKIP)

    def test_low_liquidity_returns_reduce_or_skip(self):
        kwargs = self._base_kwargs()
        kwargs["liquidity_score"] = 0.1
        decision = self.selector.select(**kwargs)
        # Could be SKIP or LIMIT with reduced size
        self.assertIn(decision.order_type, [OrderType.SKIP, OrderType.LIMIT])

    def test_normal_conditions_returns_limit(self):
        kwargs = self._base_kwargs()
        decision = self.selector.select(**kwargs)
        self.assertIn(decision.order_type, [OrderType.LIMIT, OrderType.AGGRESSIVE_LIMIT])

    def test_high_slippage_suggests_twap(self):
        kwargs = self._base_kwargs()
        kwargs["expected_slippage_bps"] = 100.0
        kwargs["volume_participation_rate"] = 0.05
        decision = self.selector.select(**kwargs)
        self.assertEqual(decision.order_type, OrderType.TWAP)


class TestExecutionRiskMonitor(unittest.TestCase):

    def setUp(self):
        self.monitor = ExecutionRiskMonitor({
            "max_spread_bps": 20.0,
            "max_slippage_bps": 30.0,
            "min_liquidity_score": 0.4,
            "max_latency_ms": 1500,
        })

    def test_wide_spread_rejected(self):
        result = self.monitor.evaluate(
            spread_bps=50.0,
            expected_slippage_bps=10.0,
            liquidity_score=0.8,
            order_notional_usdt=1000.0,
            max_safe_order_size_usdt=50_000.0,
        )
        self.assertEqual(result.action, GuardAction.REJECT)
        self.assertIn("spread", result.reason)

    def test_high_slippage_rejected(self):
        result = self.monitor.evaluate(
            spread_bps=5.0,
            expected_slippage_bps=100.0,
            liquidity_score=0.8,
            order_notional_usdt=1000.0,
            max_safe_order_size_usdt=50_000.0,
        )
        self.assertEqual(result.action, GuardAction.REJECT)

    def test_low_liquidity_reduces_size(self):
        result = self.monitor.check_liquidity(
            liquidity_score=0.1,
            order_notional_usdt=500.0,         # small order — under 30% of safe size
            max_safe_order_size_usdt=10_000.0,
        )
        self.assertEqual(result.action, GuardAction.REDUCE)

    def test_high_latency_rejected(self):
        result = self.monitor.evaluate(
            spread_bps=5.0,
            expected_slippage_bps=10.0,
            liquidity_score=0.8,
            order_notional_usdt=1000.0,
            max_safe_order_size_usdt=50_000.0,
            latency_ms=3000,
        )
        self.assertEqual(result.action, GuardAction.REJECT)
        self.assertIn("latency", result.reason)

    def test_all_clear_passes(self):
        result = self.monitor.evaluate(
            spread_bps=5.0,
            expected_slippage_bps=10.0,
            liquidity_score=0.8,
            order_notional_usdt=5_000.0,
            max_safe_order_size_usdt=50_000.0,
            latency_ms=100,
        )
        self.assertEqual(result.action, GuardAction.PASS)


class TestTWAPExecutor(unittest.TestCase):

    def setUp(self):
        self.executor = TWAPExecutor()

    def test_plan_creates_correct_slices(self):
        plan = self.executor.plan(
            total_qty=10.0,
            total_notional_usdt=10_000.0,
            slices=5,
            interval_seconds=30,
        )
        self.assertEqual(len(plan.children), 5)
        for child in plan.children:
            self.assertAlmostEqual(child.qty, 2.0, places=5)

    def test_slice_timings(self):
        import time
        t0 = time.time()
        plan = self.executor.plan(
            total_qty=5.0,
            total_notional_usdt=5_000.0,
            slices=3,
            interval_seconds=60,
            start_time=t0,
        )
        self.assertAlmostEqual(plan.children[0].scheduled_at, t0, places=0)
        self.assertAlmostEqual(plan.children[1].scheduled_at, t0 + 60, places=0)
        self.assertAlmostEqual(plan.children[2].scheduled_at, t0 + 120, places=0)

    def test_cancel_on_reversal(self):
        plan = self.executor.plan(total_qty=5.0, total_notional_usdt=5_000.0, slices=3)
        should_cancel = self.executor.check_cancel(plan, "BUY (Crossover)", "STRONG SELL (Confirmed Reversal)")
        self.assertTrue(should_cancel)

    def test_no_cancel_same_direction(self):
        plan = self.executor.plan(total_qty=5.0, total_notional_usdt=5_000.0, slices=3)
        should_cancel = self.executor.check_cancel(plan, "BUY (Crossover)", "BUY (SFP)")
        self.assertFalse(should_cancel)


class TestPostTradeAnalyzer(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.analyzer = PostTradeAnalyzer(reports_dir=self.tmp)

    def _make_record(self, dp, fp, side="BUY", spread=5.0, fee=5.0, notional=10_000.0, latency=200):
        return {
            "execution_id": "test_001",
            "coin": "BTC",
            "side": side,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision_price": dp,
            "avg_fill_price": fp,
            "spread_bps_at_submit": spread,
            "fee": fee,
            "intended_notional": notional,
            "intended_qty": notional / dp,
            "latency_ms": latency,
            "expected_slippage_bps": 10.0,
        }

    def test_shortfall_buy(self):
        # BUY at 100, filled at 101 → IS = (101-100)/100 * 10000 = 100 bps
        b = self.analyzer.analyze(self._make_record(100.0, 101.0, "BUY"))
        self.assertAlmostEqual(b.implementation_shortfall_bps, 100.0, places=2)

    def test_shortfall_sell(self):
        # SELL at 100, filled at 99 → IS = (100-99)/100 * 10000 = 100 bps
        b = self.analyzer.analyze(self._make_record(100.0, 99.0, "SELL"))
        self.assertAlmostEqual(b.implementation_shortfall_bps, 100.0, places=2)

    def test_perfect_fill_excellent(self):
        # Fill exactly at decision price
        b = self.analyzer.analyze(self._make_record(100.0, 100.0, "BUY", spread=0.1, fee=0.01, latency=10))
        self.assertIn(b.quality_label, ["EXCELLENT", "GOOD"])

    def test_bad_fill_poor(self):
        # Very bad fill — 200 bps IS
        b = self.analyzer.analyze(self._make_record(100.0, 102.0, "BUY"))
        self.assertEqual(b.quality_label, "POOR")


class TestExecutionEnginePaper(unittest.TestCase):

    def test_paper_submit_returns_record(self):
        engine = ExecutionEngine()
        signal = {
            "coin": "BTC",
            "signal_raw": "BUY (Crossover)",
            "entry_time": datetime.now(timezone.utc).isoformat(),
        }
        candle = {
            "time": datetime.now(timezone.utc).isoformat(),
            "open": 50_000.0,
            "high": 51_000.0,
            "low": 49_000.0,
            "close": 50_500.0,
            "volume": 120.0,
        }
        record = engine.submit_paper(signal, candle)
        self.assertIsNotNone(record)
        self.assertIn(record.status, ["FILLED", "REJECTED"])
        self.assertGreater(len(record.execution_id), 0)

    def test_stats_returns_dict(self):
        engine = ExecutionEngine()
        stats = engine.get_stats()
        self.assertIn("n_fills", stats)
        self.assertIn("reject_rate", stats)


if __name__ == "__main__":
    unittest.main()
