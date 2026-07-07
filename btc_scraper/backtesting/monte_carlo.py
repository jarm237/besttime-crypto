from typing import List, Dict, Any
import numpy as np

class MonteCarloEngine:
    """
    Runs bootstrap and trade-shuffling simulations to test strategy statistical robustness.
    """
    
    @staticmethod
    def analyze(
        trade_log: List[Dict[str, Any]],
        initial_capital: float,
        n_simulations: int = 1000,
        ruin_threshold_pct: float = 0.50  # Ruined if capital drops by 50%
    ) -> Dict[str, Any]:
        """
        Runs Monte Carlo simulations on trade PnLs.
        
        Using numpy vectorization for high-speed calculation of 1,000-10,000 paths.
        """
        if not trade_log:
            return {
                "p05_return": 0.0,
                "p50_return": 0.0,
                "p95_return": 0.0,
                "probability_of_loss": 1.0,
                "probability_max_dd_gt_10pct": 1.0,
                "expected_max_drawdown": 1.0,
                "risk_of_ruin": 1.0
            }

        pnls = np.array([t["pnl"] for t in trade_log])
        n_trades = len(pnls)
        
        # Set seed for reproducibility
        rng = np.random.default_rng(42)
        
        # Draw random samples from PnLs: shape (n_simulations, n_trades)
        # Bootstrap: sample with replacement
        sim_indices = rng.integers(0, n_trades, size=(n_simulations, n_trades))
        sim_pnls = pnls[sim_indices]
        
        # Add random noise representing slippage/spread variance (e.g. ±1 bps of average notional)
        # Assuming average trade size is e.g. $3300 (initial 10000 / 3)
        avg_trade_size = initial_capital / 3.0
        noise = rng.normal(0, avg_trade_size * 0.0002, size=(n_simulations, n_trades))
        sim_pnls += noise
        
        # Cumulative returns
        # Path equity: shape (n_simulations, n_trades + 1)
        equities = np.zeros((n_simulations, n_trades + 1))
        equities[:, 0] = initial_capital
        
        for col in range(1, n_trades + 1):
            equities[:, col] = equities[:, col - 1] + sim_pnls[:, col - 1]
            
        final_returns = (equities[:, -1] - initial_capital) / initial_capital
        
        # Expected drawdown per path
        # Running peaks
        peaks = np.maximum.accumulate(equities, axis=1)
        drawdowns = (peaks - equities) / peaks
        max_drawdowns = np.max(drawdowns, axis=1)
        
        # Probability of loss (final equity < initial capital)
        prob_of_loss = float(np.mean(final_returns < 0.0))
        
        # Probability of drawdown > 10%
        prob_dd_gt_10 = float(np.mean(max_drawdowns > 0.10))
        
        # Expected max drawdown
        expected_max_dd = float(np.mean(max_drawdowns))
        
        # Risk of ruin (equity drops below ruin_threshold_pct * initial_capital)
        ruin_level = initial_capital * (1.0 - ruin_threshold_pct)
        ruined_paths = np.any(equities <= ruin_level, axis=1)
        risk_of_ruin = float(np.mean(ruined_paths))
        
        # Percentiles
        p05 = float(np.percentile(final_returns, 5))
        p50 = float(np.percentile(final_returns, 50))
        p95 = float(np.percentile(final_returns, 95))
        
        return {
            "p05_return": p05,
            "p50_return": p50,
            "p95_return": p95,
            "probability_of_loss": prob_of_loss,
            "probability_max_dd_gt_10pct": prob_dd_gt_10,
            "expected_max_drawdown": expected_max_dd,
            "risk_of_ruin": risk_of_ruin
        }
