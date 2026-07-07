import unittest
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from btc_scraper.backtesting.config import BacktestConfig, APPROVAL_RULES
from btc_scraper.backtesting.cost_model import CostModel
from btc_scraper.backtesting.slippage_model_v1 import SlippageModel
from btc_scraper.backtesting.latency_model import LatencyModel
from btc_scraper.backtesting.engine import BacktestEngine
from btc_scraper.backtesting.vectorized_engine import VectorizedEngine
from btc_scraper.backtesting.walk_forward import WalkForwardValidator
from btc_scraper.backtesting.purged_kfold import PurgedKFold
from btc_scraper.backtesting.embargo import embargo_train_indices
from btc_scraper.backtesting.regime_split import RegimeSplitAnalyzer
from btc_scraper.backtesting.stress_test import StressTestEngine
from btc_scraper.backtesting.monte_carlo import MonteCarloEngine
from btc_scraper.backtesting.report_builder import ReportBuilder

class TestPhase9Backtesting(unittest.TestCase):
    
    def test_cost_model(self):
        # Futures config
        model = CostModel({"futures_taker_bps": 5.0, "futures_maker_bps": 2.0, "is_futures": True})
        self.assertEqual(model.calculate_fee(10000.0, is_taker=True), 5.0)
        self.assertEqual(model.calculate_fee(10000.0, is_taker=False), 2.0)
        
        # Spot config
        spot_model = CostModel({"spot_taker_bps": 10.0, "spot_maker_bps": 10.0, "is_futures": False})
        self.assertEqual(spot_model.calculate_fee(10000.0, is_taker=True), 10.0)
        
        # Spread fill price
        base_price = 100.0
        # Ask fill (buy)
        self.assertAlmostEqual(model.get_fill_price_with_spread(base_price, is_buy=True, spread_bps=10.0), 100.05)
        # Bid fill (sell)
        self.assertAlmostEqual(model.get_fill_price_with_spread(base_price, is_buy=False, spread_bps=10.0), 99.95)

    def test_slippage_model(self):
        model = SlippageModel({"enabled": True, "base_slippage_bps": 1.0})
        # slippage_bps = 1.0 + 0.2 * (atr_pct*100) + 0.5 * (size_pct*100) + 0.3 * spread
        # atr_pct = 0.02 (2%), size_pct = 0.001 (0.1%), spread_bps = 2.0
        # 1.0 + 0.2*2.0 + 0.5*0.1 + 0.3*2.0 = 1.0 + 0.4 + 0.05 + 0.6 = 2.05 bps
        bps = model.calculate_slippage_bps(atr_pct=0.02, order_size_pct_adv=0.001, spread_bps=2.0)
        self.assertAlmostEqual(bps, 2.05)
        
        # Apply slippage
        price = 100.0
        self.assertAlmostEqual(model.apply_slippage(price, is_buy=True, slippage_bps=10.0), 100.10)
        self.assertAlmostEqual(model.apply_slippage(price, is_buy=False, slippage_bps=10.0), 99.90)

    def test_latency_model(self):
        model = LatencyModel({"enabled": True, "latency_ms": 250})
        
        candles = [
            {"time": "2026-07-01 00:00:00", "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
            {"time": "2026-07-01 00:15:00", "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0},
            {"time": "2026-07-01 00:30:00", "open": 102.0, "high": 104.0, "low": 101.0, "close": 103.0},
        ]
        
        # Signal generated at close of index 0. Standard execution is index 1.
        # latency = 250ms delay, timeframe = 15m (900,000 ms).
        # delay_bars = 0, remainder = 250ms
        res = model.compute_delayed_execution(candles, current_idx=0, is_buy=True, timeframe_min=15)
        self.assertEqual(res["fill_index"], 1)
        self.assertEqual(res["fill_time"], "2026-07-01 00:15:00")
        # Penalty should be small but positive (increasing buy price)
        self.assertGreater(res["base_price"], 101.0)
        self.assertLessEqual(res["base_price"], 103.0)

    def test_purged_kfold(self):
        # Create 10 sample times spanning consecutive 1-hour intervals
        times = pd.date_range("2026-07-01 00:00:00", periods=10, freq="h")
        df = pd.DataFrame({
            "entry_time": times,
            "exit_time": times + pd.Timedelta(hours=2) # 2-hour duration labels
        })
        
        pkf = PurgedKFold(n_splits=3, embargo_pct=0.1)
        splits = list(pkf.split(df))
        
        self.assertEqual(len(splits), 3)
        for train_idx, test_idx in splits:
            # Check overlap prevention
            # Overlapping evaluation intervals: train evaluation shouldn't intersect test evaluation
            for tr_i in train_idx:
                tr_t1 = df["entry_time"].iloc[tr_i]
                tr_t2 = df["exit_time"].iloc[tr_i]
                for ts_i in test_idx:
                    ts_t1 = df["entry_time"].iloc[ts_i]
                    ts_t2 = df["exit_time"].iloc[ts_i]
                    
                    # They shouldn't overlap
                    is_overlap = (tr_t1 <= ts_t2) and (tr_t2 >= ts_t1)
                    self.assertFalse(is_overlap, f"Overlap detected between train index {tr_i} and test index {ts_i}")

    def test_embargo(self):
        train = np.array([0, 1, 2, 3, 7, 8, 9])
        test = np.array([4, 5, 6])
        # Embargo elements from 7 to max_test + offset
        res = embargo_train_indices(train, test, embargo_offset=2)
        # Should drop index 7 and 8
        np.testing.assert_array_equal(res, np.array([0, 1, 2, 3, 9]))

    def test_monte_carlo(self):
        trade_log = [
            {"pnl": 50.0, "hold_bars": 4, "result": "TP1"},
            {"pnl": -30.0, "hold_bars": 2, "result": "SL"},
            {"pnl": 100.0, "hold_bars": 8, "result": "TP2"},
            {"pnl": -15.0, "hold_bars": 3, "result": "SL"},
        ]
        mc_results = MonteCarloEngine.analyze(trade_log, initial_capital=1000, n_simulations=100)
        self.assertIn("p05_return", mc_results)
        self.assertIn("probability_of_loss", mc_results)
        self.assertIn("risk_of_ruin", mc_results)

    def test_report_builder(self):
        metrics = {"sharpe": 1.2, "profit_factor": 1.5, "max_drawdown": 0.05, "n_trades": 120, "cost_drag": 0.15}
        mc_metrics = {"probability_of_loss": 0.10, "probability_max_dd_gt_10pct": 0.05}
        regime_metrics = {
            "Bull": {"total_return": 100.0, "n_trades": 40},
            "Bear": {"total_return": 50.0, "n_trades": 30},
            "Ranging": {"total_return": 10.0, "n_trades": 50}
        }
        
        status = ReportBuilder.check_approval_gate(metrics, mc_metrics, regime_metrics)
        self.assertTrue(status["passed"])
        
        # Test rejection
        bad_metrics = {"sharpe": 0.5, "profit_factor": 1.1, "max_drawdown": 0.25, "n_trades": 40, "cost_drag": 0.45}
        bad_status = ReportBuilder.check_approval_gate(bad_metrics, mc_metrics, regime_metrics)
        self.assertFalse(bad_status["passed"])

if __name__ == "__main__":
    unittest.main()
