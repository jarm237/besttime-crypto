"""
neural_trading/engine/portfolio_simulator.py

First-principles multi-asset portfolio simulator with realistic execution friction,
deterministic cash accounting, exact risky-asset notional fee deduction,
and rigorous distinction between initial entry, natural drift, and active rebalancing.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import numpy as np
import pandas as pd

from neural_trading.engine.hard_risk import DeterministicHardRiskBarrier


class NeuralPortfolioSimulator:
    """
    Simulates sequential multi-asset execution of neural allocation policies.
    Guarantees strict cash balance conservation, realistic fee/spread/slippage models,
    and exact turnover calculation based strictly on executed risky-asset notional.
    """

    def __init__(
        self,
        symbols: Sequence[str],
        initial_capital: float = 20_000.0,
        fee_bps: float = 5.0,              # 5 bps fee per leg (10 bps roundtrip)
        slippage_bps: float = 1.0,         # 1 bps slippage per leg (2 bps roundtrip)
        typical_spread_bps: float = 1.0,   # 1 bps half-spread per leg (2 bps roundtrip)
        hard_risk_barrier: Optional[DeterministicHardRiskBarrier] = None,
        min_trade_notional: float = 1.0,   # Filter out sub-$1 floating-point dust
    ):
        self.symbols = list(symbols)
        self.initial_capital = initial_capital
        # Standard Baseline: 7 bps per leg = 14 bps round-trip
        self.cost_per_leg_bps = fee_bps + slippage_bps + typical_spread_bps
        self.cost_round_trip_bps = self.cost_per_leg_bps * 2.0
        self.friction_rate = self.cost_per_leg_bps / 10_000.0
        self.risk_barrier = hard_risk_barrier or DeterministicHardRiskBarrier()
        self.min_trade_notional = min_trade_notional

    def simulate(
        self,
        target_weights_seq: np.ndarray,            # Shape (K, N + 1)
        price_relatives_seq: np.ndarray,           # Shape (K, N)
        timestamps: Sequence[str],                 # Length K
        is_halt_seq: Optional[np.ndarray] = None,  # Length K boolean array for trading halts
        is_hold_seq: Optional[np.ndarray] = None,  # Length K boolean array for explicit HOLD action
        enforce_barrier: bool = True,              # If False (pure Buy & Hold), natural drift without rebalance
    ) -> Dict[str, Any]:
        """
        Executes a sequence of portfolio rebalancing decisions.
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
        total_executed_notional = 0.0
        total_buy_notional = 0.0
        total_sell_notional = 0.0
        actual_rebalance_orders = 0
        initial_entry_orders = 0
        risk_forced_rebalance_count = 0
        hold_decision_count = 0
        rebalance_decision_count = 0

        for t in range(K):
            t_str = timestamps[t]
            is_halt = bool(is_halt_seq[t]) if is_halt_seq is not None else False
            is_explicit_hold = bool(is_hold_seq[t]) if is_hold_seq is not None else False

            # Check if hold violates hard risk barrier
            must_intervene = False
            if enforce_barrier and is_explicit_hold and t > 0:
                violates_cash = current_weights[0] < (self.risk_barrier.min_cash_pct - 1e-6)
                violates_conc = (current_weights[1:] > (self.risk_barrier.max_asset_pct + 1e-6)).any()
                if violates_cash or violates_conc:
                    must_intervene = True

            if is_halt or (is_explicit_hold and t > 0 and not must_intervene):
                # Pure HOLD or HALT: maintain existing drifted weights with ZERO trades and ZERO fees
                target_w = current_weights.copy()
                risky_turnover_t = 0.0
                cost_t = 0.0
                y_t = np.ones(N_plus_1, dtype=np.float64) if is_halt else np.concatenate([[1.0], price_relatives_seq[t]])
                hold_decision_count += 1
            else:
                if must_intervene:
                    raw_w_target = current_weights.copy()
                    risk_forced_rebalance_count += 1
                else:
                    raw_w_target = target_weights_seq[t]

                if enforce_barrier:
                    target_w = self.risk_barrier.enforce_numpy(raw_w_target, current_weights)
                else:
                    target_w = raw_w_target.copy()

                # Calculate delta strictly on RISKY ASSETS (1..N)
                delta_risky = target_w[1:] - current_weights[1:]
                step_notional_deltas = np.abs(delta_risky) * current_capital

                # Filter out sub-$1 floating point dust
                is_real_trade = step_notional_deltas >= self.min_trade_notional
                cleaned_deltas = np.where(is_real_trade, np.abs(delta_risky), 0.0)
                risky_turnover_t = float(np.sum(cleaned_deltas))

                # Leg accounting
                buy_deltas = np.where((delta_risky > 0) & is_real_trade, delta_risky, 0.0)
                sell_deltas = np.where((delta_risky < 0) & is_real_trade, -delta_risky, 0.0)
                buy_notional_t = float(np.sum(buy_deltas)) * current_capital
                sell_notional_t = float(np.sum(sell_deltas)) * current_capital

                total_buy_notional += buy_notional_t
                total_sell_notional += sell_notional_t

                num_trades = int(np.sum(is_real_trade))
                if t == 0:
                    initial_entry_orders += num_trades
                else:
                    actual_rebalance_orders += num_trades

                if num_trades > 0:
                    rebalance_decision_count += 1
                else:
                    hold_decision_count += 1

                # Transaction cost on executed risky notional
                executed_notional_t = risky_turnover_t * current_capital
                total_executed_notional += executed_notional_t
                cost_t = executed_notional_t * self.friction_rate

                y_t = np.concatenate([[1.0], price_relatives_seq[t]])

            turnovers.append(risky_turnover_t)
            frictions_paid.append(cost_t)
            current_capital -= cost_t

            # Portfolio growth across step t -> t+1
            portfolio_growth = float(np.sum(target_w * y_t))
            net_return_t = (portfolio_growth - 1.0) - (risky_turnover_t * self.friction_rate)
            net_returns.append(net_return_t)

            current_capital *= portfolio_growth

            # Drift weights to end-of-bar allocation
            drifted_w = (target_w * y_t) / np.sum(target_w * y_t)
            current_weights = drifted_w

            equity_curve.append({
                "time": t_str,
                "equity": round(current_capital, 2),
                "cash_weight": round(float(target_w[0]), 4),
                "risky_weight": round(float(np.sum(target_w[1:])), 4),
                "risky_turnover": round(risky_turnover_t, 4),
                "friction_cost": round(cost_t, 4),
                "is_halt": is_halt,
            })

        df_eq = pd.DataFrame(equity_curve)
        equities = df_eq["equity"].values
        cum_returns = (equities - self.initial_capital) / self.initial_capital
        total_net_pnl = current_capital - self.initial_capital

        peaks = np.maximum.accumulate(equities)
        drawdowns = (peaks - equities) / np.maximum(peaks, 1e-8)
        max_drawdown_pct = float(np.max(drawdowns)) * 100.0

        r_arr = np.array(net_returns)
        mean_r = float(np.mean(r_arr))
        std_r = float(np.std(r_arr)) if len(r_arr) > 1 else 1e-6
        ann_sharpe = float((mean_r / std_r) * np.sqrt(24.0 * 365.0)) if std_r > 0 else 0.0

        downside_r = r_arr[r_arr < 0]
        std_downside = float(np.std(downside_r)) if len(downside_r) > 1 else 1e-6
        ann_sortino = float((mean_r / std_downside) * np.sqrt(24.0 * 365.0)) if std_downside > 0 else 0.0

        num_hours = len(r_arr)
        years = num_hours / (24.0 * 365.0) if num_hours > 0 else 1.0
        annualized_return_pct = float(((current_capital / self.initial_capital) ** (1.0 / years) - 1.0) * 100.0) if current_capital > 0 else -100.0

        total_friction = sum(frictions_paid)
        mean_turnover = float(np.mean(turnovers))
        ann_turnover = float(mean_turnover * 24.0 * 365.0)

        avg_cash = float(df_eq["cash_weight"].mean())
        avg_risky = float(df_eq["risky_weight"].mean())

        gains = r_arr[r_arr > 0]
        losses = np.abs(r_arr[r_arr < 0])
        profit_factor = float(np.sum(gains) / np.sum(losses)) if len(losses) > 0 and np.sum(losses) > 0 else 0.0

        hold_rate = (hold_decision_count / K) * 100.0 if K > 0 else 0.0
        rebal_rate = (rebalance_decision_count / K) * 100.0 if K > 0 else 0.0

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
            "cost_per_leg_bps": self.cost_per_leg_bps,
            "cost_round_trip_bps": self.cost_round_trip_bps,
            "total_friction_usd": round(total_friction, 2),
            "total_executed_notional": round(total_executed_notional, 2),
            "buy_executed_notional": round(total_buy_notional, 2),
            "sell_executed_notional": round(total_sell_notional, 2),
            "initial_entry_orders": initial_entry_orders,
            "actual_rebalance_orders": actual_rebalance_orders,
            "actual_trade_count": initial_entry_orders + actual_rebalance_orders,
            "total_trade_count": initial_entry_orders + actual_rebalance_orders,
            "risk_forced_rebalance_count": risk_forced_rebalance_count,
            "decision_count": K,
            "hold_decision_count": hold_decision_count,
            "rebalance_decision_count": rebalance_decision_count,
            "hold_decision_rate_pct": round(hold_rate, 2),
            "rebalance_decision_rate_pct": round(rebal_rate, 2),
            "mean_turnover_per_bar": round(mean_turnover, 4),
            "annualized_turnover": round(ann_turnover, 2),
            "average_cash_weight": round(avg_cash, 4),
            "average_risky_weight": round(avg_risky, 4),
            "equity_curve": equity_curve,
        }
