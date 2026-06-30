"""
A/B Backtest Comparison - Validate context adjustments on historical data

Compares:
- Baseline: Original Meta model decisions
- Treatment: Context-adjusted decisions
- Metrics: Win Rate, Profit Factor, Max Drawdown, Sharpe Ratio

Success criteria for enabling live context adjustments:
- Profit Factor improvement > 0.1
- Max Drawdown reduction > 5%
- Win rate improvement > 5% (OR negative trades reduction > 10%)
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import logging
import json


logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Result of a single backtest run."""
    strategy_name: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win_pct: float
    avg_loss_pct: float
    win_rate: float
    profit_factor: float
    total_pnl_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    consecutive_wins: int
    consecutive_losses: int

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class BacktestComparison:
    """Comparison between two backtest runs."""
    baseline_result: BacktestResult
    treatment_result: BacktestResult
    improvement: Dict
    recommendation: str
    timestamp: str

    def to_dict(self) -> Dict:
        return {
            "baseline": self.baseline_result.to_dict(),
            "treatment": self.treatment_result.to_dict(),
            "improvement": self.improvement,
            "recommendation": self.recommendation,
            "timestamp": self.timestamp,
        }


class ABBacktestComparator:
    """Runs and compares A/B backtests."""

    def __init__(self, context_engine=None, decision_engine=None):
        """
        Initialize A/B backtest comparator.
        
        Args:
            context_engine: ContextEngine instance
            decision_engine: MetaDecisionEngine instance
        """
        self.context_engine = context_engine
        self.decision_engine = decision_engine

    def run_backtest(
        self,
        signals_df: pd.DataFrame,
        context_data_df: Optional[pd.DataFrame] = None,
        use_context: bool = False,
    ) -> BacktestResult:
        """
        Run backtest on historical signals.
        
        Args:
            signals_df: DataFrame with columns:
                - timestamp (index or column)
                - posterior_probability (or action)
                - entry_price
                - exit_price (optional)
                - pnl_pct (optional)
            context_data_df: DataFrame with context features
            use_context: Whether to apply context adjustments
            
        Returns:
            BacktestResult with metrics
        """
        pnls = []
        trades_data = []

        for idx, row in signals_df.iterrows():
            posterior = row.get("posterior_probability", 0.5)
            action = row.get("action", "HOLD")
            entry_price = row.get("entry_price", 0)
            exit_price = row.get("exit_price", entry_price)
            pnl_pct = row.get("pnl_pct")

            # Apply context adjustment if enabled
            if use_context and self.context_engine and context_data_df is not None:
                try:
                    context_report = self.context_engine.generate_context_report(
                        posterior,
                        context_data_df.loc[idx].to_dict() if idx in context_data_df.index else {}
                    )
                    posterior = context_report.adjusted_score
                except Exception as e:
                    logger.debug(f"Context adjustment failed at {idx}: {str(e)}")

            # Calculate PnL if not provided
            if pnl_pct is None and entry_price > 0 and exit_price > 0:
                pnl_pct = (exit_price - entry_price) / entry_price * 100
            elif pnl_pct is None:
                pnl_pct = 0

            # Determine trade direction based on action/posterior
            if posterior > 0.65:
                direction = "LONG"
            elif posterior < 0.35:
                direction = "SHORT"
                pnl_pct = -pnl_pct  # Reverse for short
            else:
                continue  # Skip neutral

            pnls.append(pnl_pct)
            trades_data.append({
                "timestamp": idx,
                "direction": direction,
                "posterior": posterior,
                "pnl_pct": pnl_pct,
            })

        return self._calculate_metrics(pnls, use_context, trades_data)

    def run_ab_backtest(
        self,
        signals_df: pd.DataFrame,
        context_data_df: Optional[pd.DataFrame] = None,
    ) -> BacktestComparison:
        """
        Run A/B backtest comparing original vs context-adjusted.
        
        Args:
            signals_df: Historical signals with posterior probabilities
            context_data_df: Historical context data
            
        Returns:
            BacktestComparison with results and recommendation
        """
        logger.info("Running A/B backtest...")
        logger.info(f"  Total historical samples: {len(signals_df)}")

        # Baseline: Original (no context)
        logger.info("  [A] Baseline: Meta model only...")
        baseline = self.run_backtest(signals_df, context_data_df, use_context=False)
        logger.info(f"     Win Rate: {baseline.win_rate:.1f}% | PF: {baseline.profit_factor:.2f} | DD: {baseline.max_drawdown_pct:.1f}%")

        # Treatment: With context
        logger.info("  [B] Treatment: Context-adjusted...")
        treatment = self.run_backtest(signals_df, context_data_df, use_context=True)
        logger.info(f"     Win Rate: {treatment.win_rate:.1f}% | PF: {treatment.profit_factor:.2f} | DD: {treatment.max_drawdown_pct:.1f}%")

        # Compare
        improvement = self._compare_results(baseline, treatment)
        recommendation = self._get_recommendation(improvement)

        logger.info(f"\n  Improvement: {json.dumps(improvement, indent=2)}")
        logger.info(f"  Recommendation: {recommendation}\n")

        return BacktestComparison(
            baseline_result=baseline,
            treatment_result=treatment,
            improvement=improvement,
            recommendation=recommendation,
            timestamp=datetime.utcnow().isoformat(),
        )

    def _calculate_metrics(
        self,
        pnls: List[float],
        use_context: bool,
        trades_data: Optional[List[Dict]] = None,
    ) -> BacktestResult:
        """Calculate backtest metrics from PnL list."""
        if not pnls:
            return BacktestResult(
                strategy_name="CONTEXT" if use_context else "BASELINE",
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                avg_win_pct=0,
                avg_loss_pct=0,
                win_rate=0,
                profit_factor=0,
                total_pnl_pct=0,
                max_drawdown_pct=0,
                sharpe_ratio=0,
                consecutive_wins=0,
                consecutive_losses=0,
            )

        pnls_array = np.array(pnls)
        winning = pnls_array[pnls_array > 0]
        losing = pnls_array[pnls_array < 0]

        avg_win = float(winning.mean()) if len(winning) > 0 else 0.0
        avg_loss = float(abs(losing.mean())) if len(losing) > 0 else 0.0

        win_rate = len(winning) / len(pnls) * 100
        gross_profit = float(winning.sum()) if len(winning) > 0 else 0.0
        gross_loss = float(abs(losing.sum())) if len(losing) > 0 else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0.0)

        total_pnl = float(pnls_array.sum())

        # Max drawdown
        cumsum = np.cumsum(pnls_array)
        running_max = np.maximum.accumulate(cumsum)
        drawdown = (cumsum - running_max) / (np.abs(running_max) + 1e-10) * 100
        max_drawdown = float(np.min(drawdown))

        # Sharpe ratio
        returns = pnls_array / 100.0  # Convert to decimal
        if returns.std() > 0:
            sharpe = (returns.mean() / returns.std()) * np.sqrt(252)  # Annualized
        else:
            sharpe = 0.0

        # Consecutive wins/losses
        consecutive_wins = self._max_consecutive(pnls_array > 0)
        consecutive_losses = self._max_consecutive(pnls_array < 0)

        return BacktestResult(
            strategy_name="CONTEXT" if use_context else "BASELINE",
            total_trades=len(pnls),
            winning_trades=len(winning),
            losing_trades=len(losing),
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_pnl_pct=total_pnl,
            max_drawdown_pct=max_drawdown,
            sharpe_ratio=sharpe,
            consecutive_wins=int(consecutive_wins),
            consecutive_losses=int(consecutive_losses),
        )

    def _max_consecutive(self, condition: np.ndarray) -> int:
        """Find max consecutive True values."""
        consecutive = np.diff(np.concatenate([[0], condition.astype(int), [0]]))
        starts = np.where(consecutive == 1)[0]
        ends = np.where(consecutive == -1)[0]
        if len(starts) == 0:
            return 0
        return int(max(ends - starts))

    def _compare_results(
        self,
        baseline: BacktestResult,
        treatment: BacktestResult,
    ) -> Dict:
        """Compare baseline vs treatment results."""
        return {
            "win_rate_delta_pct": treatment.win_rate - baseline.win_rate,
            "profit_factor_delta": treatment.profit_factor - baseline.profit_factor,
            "total_pnl_delta_pct": treatment.total_pnl_pct - baseline.total_pnl_pct,
            "max_drawdown_delta_pct": treatment.max_drawdown_pct - baseline.max_drawdown_pct,  # Negative is better
            "sharpe_delta": treatment.sharpe_ratio - baseline.sharpe_ratio,
            "trade_count_change": treatment.total_trades - baseline.total_trades,
        }

    def _get_recommendation(self, improvement: Dict) -> str:
        """Determine if context adjustments should be enabled."""
        score = 0
        details = []

        # Criteria 1: Profit Factor improvement
        if improvement["profit_factor_delta"] > 0.1:
            score += 2
            details.append(f"✓ PF improved by {improvement['profit_factor_delta']:.2f}")
        elif improvement["profit_factor_delta"] > 0:
            score += 1
            details.append(f"◐ PF improved by {improvement['profit_factor_delta']:.2f}")
        else:
            details.append(f"✗ PF degraded by {abs(improvement['profit_factor_delta']):.2f}")

        # Criteria 2: Drawdown reduction
        if improvement["max_drawdown_delta_pct"] > 5:  # Positive = less negative = better
            score += 2
            details.append(f"✓ Max DD reduced by {improvement['max_drawdown_delta_pct']:.1f}%")
        elif improvement["max_drawdown_delta_pct"] > 0:
            score += 1
            details.append(f"◐ Max DD reduced by {improvement['max_drawdown_delta_pct']:.1f}%")
        else:
            details.append(f"✗ Max DD increased by {abs(improvement['max_drawdown_delta_pct']):.1f}%")

        # Criteria 3: Win rate or total PnL
        if improvement["win_rate_delta_pct"] > 5:
            score += 2
            details.append(f"✓ Win rate improved by {improvement['win_rate_delta_pct']:.1f}%")
        elif improvement["total_pnl_delta_pct"] > 10:
            score += 2
            details.append(f"✓ Total PnL improved by {improvement['total_pnl_delta_pct']:.1f}%")
        elif improvement["total_pnl_delta_pct"] > 0:
            score += 1
            details.append(f"◐ Total PnL improved by {improvement['total_pnl_delta_pct']:.1f}%")
        else:
            details.append(f"✗ Total PnL degraded by {abs(improvement['total_pnl_delta_pct']):.1f}%")

        # Criteria 4: Reduced trades (fewer signals = better quality)
        if improvement["trade_count_change"] < -10:  # Fewer trades
            score += 1
            details.append(f"✓ Reduced low-quality signals ({abs(improvement['trade_count_change'])} fewer)")

        recommendation = ""
        if score >= 5:
            recommendation = "ENABLE_CONTEXT_ADJUSTMENTS_LIVE"
            logger.info("✓ Context adjustments IMPROVED performance significantly - RECOMMEND ENABLING")
        elif score >= 3:
            recommendation = "ENABLE_CONTEXT_ADJUSTMENTS_CAUTIOUSLY"
            logger.info("◐ Context adjustments showed modest improvement - RECOMMEND CAREFUL MONITORING")
        elif score >= 1:
            recommendation = "CONTINUE_TESTING"
            logger.info("◐ Mixed results - RECOMMEND MORE DATA COLLECTION")
        else:
            recommendation = "DO_NOT_ENABLE"
            logger.warning("✗ Context adjustments DEGRADED performance - DO NOT ENABLE")

        logger.info(f"  Recommendation details:")
        for detail in details:
            logger.info(f"    {detail}")

        return recommendation


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Example: Create synthetic backtest data
    dates = pd.date_range("2026-01-01", periods=100, freq="1H")
    signals_df = pd.DataFrame({
        "posterior_probability": np.random.uniform(0.3, 0.8, 100),
        "action": np.random.choice(["BUY", "SELL", "HOLD"], 100),
        "entry_price": np.random.uniform(50000, 60000, 100),
        "exit_price": np.random.uniform(50000, 60000, 100),
    }, index=dates)

    context_df = pd.DataFrame({
        "DXY": np.random.uniform(103, 105, 100),
        "VIX": np.random.uniform(15, 25, 100),
    }, index=dates)

    comparator = ABBacktestComparator()
    comparison = comparator.run_ab_backtest(signals_df, context_df)

    print("\n" + "="*80)
    print("BACKTEST COMPARISON RESULTS")
    print("="*80)
    print(json.dumps(comparison.to_dict(), indent=2))
