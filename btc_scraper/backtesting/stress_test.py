import copy
from typing import List, Dict, Any, TYPE_CHECKING
import pandas as pd

if TYPE_CHECKING:
    from btc_scraper.backtesting.engine import BacktestEngine

class StressTestEngine:
    """
    Simulates strategy performance under historical stress periods and synthetic shocks.
    """
    
    HISTORICAL_WINDOWS = [
        {"name": "LUNA_Collapse", "start": "2022-05-01", "end": "2022-05-20"},
        {"name": "FTX_Collapse", "start": "2022-11-01", "end": "2022-11-20"},
        {"name": "COVID_Crash", "start": "2020-03-01", "end": "2020-03-20"},
        {"name": "ETF_Approval", "start": "2024-01-01", "end": "2024-01-20"},
    ]

    SYNTHETIC_SHOCKS = [
        {"name": "double_fees", "fee_multiplier": 2.0, "slippage_multiplier": 1.0, "latency_ms": 250},
        {"name": "double_slippage", "fee_multiplier": 1.0, "slippage_multiplier": 2.0, "latency_ms": 250},
        {"name": "latency_1s", "fee_multiplier": 1.0, "slippage_multiplier": 1.0, "latency_ms": 1000},
        {"name": "latency_3s", "fee_multiplier": 1.0, "slippage_multiplier": 1.0, "latency_ms": 3000},
    ]

    @classmethod
    def analyze(
        cls,
        engine: "BacktestEngine",
        candles_dict: Dict[str, List[Dict[str, Any]]],
        signals: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Runs historical stress windows and synthetic parameter shock tests.
        """
        results = {
            "historical": {},
            "synthetic": {}
        }

        # 1. Historical Stress Windows
        for window in cls.HISTORICAL_WINDOWS:
            name = window["name"]
            start_dt = pd.to_datetime(window["start"]).tz_localize('UTC')
            end_dt = pd.to_datetime(window["end"]).tz_localize('UTC')
            
            # Filter candles
            filtered_candles = {}
            for coin, candles in candles_dict.items():
                filtered = []
                for c in candles:
                    c_time = pd.to_datetime(c["time"])
                    if c_time.tzinfo is None:
                        c_time = c_time.tz_localize('UTC')
                    if start_dt <= c_time <= end_dt:
                        filtered.append(c)
                if filtered:
                    filtered_candles[coin] = filtered
                    
            # Filter signals
            filtered_signals = []
            for s in signals:
                s_time = pd.to_datetime(s["entry_time"])
                if s_time.tzinfo is None:
                    s_time = s_time.tz_localize('UTC')
                if start_dt <= s_time <= end_dt:
                    filtered_signals.append(s)

            if not filtered_candles or not filtered_signals:
                results["historical"][name] = {
                    "status": "skipped",
                    "reason": "Insufficient historical data in this period"
                }
                continue

            # Run engine
            try:
                # Use a fresh config for historical runs to avoid bleeding state
                window_engine = copy.deepcopy(engine)
                res = window_engine.run(filtered_candles, filtered_signals)
                results["historical"][name] = {
                    "status": "completed",
                    "total_return": res.metrics.get("total_return", 0.0),
                    "max_drawdown": res.metrics.get("max_drawdown", 0.0),
                    "sharpe": res.metrics.get("sharpe", 0.0),
                    "n_trades": res.metrics.get("n_trades", 0)
                }
            except Exception as e:
                results["historical"][name] = {
                    "status": "error",
                    "error": str(e)
                }

        # 2. Synthetic Parameter Shocks (on the full data)
        for shock in cls.SYNTHETIC_SHOCKS:
            name = shock["name"]
            
            # Create modified engine
            shock_engine = copy.deepcopy(engine)
            
            # Modify fees
            for k in ["spot_maker_bps", "spot_taker_bps", "futures_maker_bps", "futures_taker_bps"]:
                if k in shock_engine.config.fee_model:
                    shock_engine.config.fee_model[k] *= shock["fee_multiplier"]
            shock_engine.cost_model = type(shock_engine.cost_model)(shock_engine.config.fee_model)
            
            # Modify slippage
            shock_engine.config.slippage_model["base_slippage_bps"] *= shock["slippage_multiplier"]
            shock_engine.slippage_model = type(shock_engine.slippage_model)(shock_engine.config.slippage_model)
            
            # Modify latency
            shock_engine.config.latency_model["latency_ms"] = shock["latency_ms"]
            shock_engine.latency_model = type(shock_engine.latency_model)(shock_engine.config.latency_model)

            try:
                # We skip re-running full sub-metrics like monte carlo and stress tests within a stress test to avoid infinite recursion!
                # Let's override engine.run to only calculate basic metrics:
                # We will temporally swap run and compile basic results:
                # We disable deep analysis by temporarily overriding analyze/monte_carlo/regime inside this run:
                results["synthetic"][name] = cls._run_basic_shock(shock_engine, candles_dict, signals)
            except Exception as e:
                results["synthetic"][name] = {
                    "status": "error",
                    "error": str(e)
                }

        return results

    @classmethod
    def _run_basic_shock(cls, engine: "BacktestEngine", candles, signals) -> Dict[str, Any]:
        """Runs a simplified backtest for shock measurement to avoid infinite recursion."""
        # Save real analyze methods
        old_regime = RegimeSplitAnalyzer.analyze
        old_stress = cls.analyze
        old_mc = MonteCarloEngine.analyze
        old_attr = AttributionAnalyzer.analyze
        
        # Stub them out
        RegimeSplitAnalyzer.analyze = lambda x: {}
        cls.analyze = lambda a, b, c: {}
        MonteCarloEngine.analyze = lambda x, y: {}
        AttributionAnalyzer.analyze = lambda x: {}
        
        try:
            res = engine.run(candles, signals)
            return {
                "status": "completed",
                "total_return": res.metrics.get("total_return", 0.0),
                "max_drawdown": res.metrics.get("max_drawdown", 0.0),
                "sharpe": res.metrics.get("sharpe", 0.0),
                "total_costs": res.metrics.get("total_costs", 0.0),
                "cost_drag": res.metrics.get("cost_drag", 0.0),
                "n_trades": res.metrics.get("n_trades", 0)
            }
        finally:
            # Restore
            RegimeSplitAnalyzer.analyze = old_regime
            cls.analyze = old_stress
            MonteCarloEngine.analyze = old_mc
            AttributionAnalyzer.analyze = old_attr
