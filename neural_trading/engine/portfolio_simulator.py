"""
neural_trading/engine/portfolio_simulator.py

Independent multi-asset portfolio simulator with realistic execution friction,
deterministic cash accounting, and mark-to-market performance metrics.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence
import numpy as np
import pandas as pd

from neural_trading.engine.hard_risk import DeterministicHardRiskBarrier


class NeuralPortfolioSimulator:
    """
    Simulates sequential multi-asset execution of neural allocation policies.
    Guarantees strict cash balance conservation and realistic fee/spread/slippage models.
    """

    def __init__(
        self,
        symbols: Sequence[str],
        initial_capital: float = 20_000.0,
        fee_bps: float = 10.0,             # 10 bps roundtrip fee (5 bps entry, 5 bps exit)
        slippage_bps: float = 2.0,         # 2 bps roundtrip slippage
        typical_spread_bps: float = 2.0,   # 2 bps roundtrip spread
        hard_risk_barrier: DeterministicHardRiskBarrier | None = None,
    ):
        self.symbols = list(symbols)
        self.initial_capital = initial_capital
        self.friction_rate = (fee_bps + slippage_bps + typical_spread_bps) / 10_000.0
        self.risk_barrier = hard_risk_barrier or DeterministicHardRiskBarrier()

    def simulate(
        self,
        target_weights_seq: np.ndarray,      # Shape (K, N + 1)
        price_relatives_seq: np.ndarray,     # Shape (K, N)
        timestamps: Sequence[str],           # Length K
    ) -> Dict[str, Any]:
        """
        Executes a sequence of portfolio rebalancing decisions.
        Args:
            target_weights_seq: Proposed weights for each step t (index 0 is Cash, 1..N are assets)
            price_relatives_seq: Price relatives p_{t+1} / p_t for the N risky assets
            timestamps: Array of ISO string timestamps
        Returns:
            Dict containing final equity, returns, Sharpe, drawdown, and daily equity curve
        """
        K, N_plus_1 = target_weights_seq.shape
        N = N_plus_1 - 1

        current_capital = self.initial_capital
        # Initial portfolio allocation is 100% Cash: [1, 0, ..., 0]
        current_weights = np.zeros(N_plus_1, dtype=np.float64)
        current_weights[0] = 1.0

        equity_curve: List[Dict[str, Any]] = []
        turnovers: List[float] = []
        frictions_paid: List[float] = []
        net_returns: List[float] = []

        for t in range(K):
            t_str = timestamps[t]
            raw_w_target = target_weights_seq[t]
            # 1. Pass through deterministic hard risk barrier
            target_w = self.risk_barrier.enforce_numpy(raw_w_target, current_weights)

            # 2. Compute turnover between current (drifted) weights and target weights
            turnover_t = float(np.sum(np.abs(target_w - current_weights)))
            turnovers.append(turnover_t)

            # 3. Transaction cost deduction
            cost_t = turnover_t * self.friction_rate * current_capital
            frictions_paid.append(cost_t)
            current_capital -= cost_t

            # 4. Form price relative vector including Cash (1.0)
            y_t = np.concatenate([[1.0], price_relatives_seq[t]])

            # 5. Asset return transition across step t -> t+1
            portfolio_growth = float(np.sum(target_w * y_t))
            net_return_t = (portfolio_growth - 1.0) - (turnover_t * self.friction_rate)
            net_returns.append(net_return_t)

            # Update capital based on market movement
            current_capital *= portfolio_growth

            # 6. Drift weights to end-of-bar allocation
            drifted_w = (target_w * y_t) / np.sum(target_w * y_t)
            current_weights = drifted_w

            equity_curve.append({
                "time": t_str,
                "equity": round(current_capital, 2),
                "cash_weight": round(float(target_w[0]), 4),
                "turnover": round(turnover_t, 4),
                "friction_cost": round(cost_t, 4),
            })

        # Final Performance Metrics
        df_eq = pd.DataFrame(equity_curve)
        equities = df_eq["equity"].values
        cum_returns = (equities - self.initial_capital) / self.initial_capital
        total_net_pnl = current_capital - self.initial_capital

        # High-water mark drawdown
        peaks = np.maximum.accumulate(equities)
        drawdowns = (peaks - equities) / peaks
        max_drawdown_pct = float(np.max(drawdowns)) * 100.0

        # Mean and std of net returns
        r_arr = np.array(net_returns)
        mean_r = float(np.mean(r_arr))
        std_r = float(np.std(r_arr)) if len(r_arr) > 1 else 1e-6
        ann_sharpe = float((mean_r / std_r) * np.sqrt(24.0 * 365.0)) if std_r > 0 else 0.0

        # Sortino (Downside risk)
        downside_r = r_arr[r_arr < 0]
        std_downside = float(np.std(downside_r)) if len(downside_r) > 1 else 1e-6
        ann_sortino = float((mean_r / std_downside) * np.sqrt(24.0 * 365.0)) if std_downside > 0 else 0.0

        # Annualized Return (assuming 1h steps)
        num_hours = len(r_arr)
        years = num_hours / (24.0 * 365.0) if num_hours > 0 else 1.0
        annualized_return_pct = float(((current_capital / self.initial_capital) ** (1.0 / years) - 1.0) * 100.0) if current_capital > 0 else -100.0

        total_friction = sum(frictions_paid)
        mean_turnover = float(np.mean(turnovers))
        ann_turnover = float(mean_turnover * 24.0 * 365.0)

        # Winning vs losing steps for Profit Factor
        gains = r_arr[r_arr > 0]
        losses = np.abs(r_arr[r_arr < 0])
        profit_factor = float(np.sum(gains) / np.sum(losses)) if len(losses) > 0 and np.sum(losses) > 0 else 0.0

        return {
            "initial_capital": self.initial_capital,
            "final_equity": round(float(current_capital), 2),
            "net_pnl_usd": round(float(total_net_pnl), 2),
            "total_return_pct": round(float(cum_returns[-1] * 100.0), 2),
            "annualized_return_pct": round(annualized_return_pct, 2),
            "annualized_sharpe": round(ann_sharpe, 2),
            "annualized_sortino": round(ann_sortino, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "profit_factor": round(profit_factor, 2),
            "total_friction_usd": round(total_friction, 2),
            "mean_turnover_per_bar": round(mean_turnover, 4),
            "annualized_turnover": round(ann_turnover, 2),
            "equity_curve": equity_curve,
        }
