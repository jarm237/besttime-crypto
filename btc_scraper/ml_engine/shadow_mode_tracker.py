"""
Shadow Mode Tracker - Track PnL differences between Original vs Context-Adjusted decisions

Enables safe verification without risking real capital:
- Logs both Original (Meta only) and Context-Adjusted decisions in parallel
- Tracks hypothetical PnL for both strategies
- Compares key metrics: Win Rate, Profit Factor, Max Drawdown
- Runs for 2-4 weeks before transitioning to live context adjustments
"""

import json
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """Record of a single trade for comparison."""
    timestamp: str
    symbol: str
    original_action: str  # BUY, SELL, HOLD
    adjusted_action: str  # BUY, SELL, HOLD
    original_posterior: float
    adjusted_posterior: float
    entry_price: float
    exit_price: Optional[float] = None
    pnl_pct: Optional[float] = None
    strategy_taken: str = "ORIGINAL"  # Which strategy was actually executed
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class StrategyMetrics:
    """Aggregated metrics for a strategy."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0  # Gross profit / Gross loss
    total_pnl_pct: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    closed_trades: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


class ShadowModeTracker:
    """Tracks and compares Original vs Context-Adjusted trading decisions."""

    def __init__(
        self,
        log_dir: str = "logs/shadow_mode",
        enable_shadow_mode: bool = True,
    ):
        """
        Initialize shadow mode tracker.
        
        Args:
            log_dir: Directory to store shadow mode logs
            enable_shadow_mode: Whether shadow mode is enabled
        """
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.enable_shadow_mode = enable_shadow_mode

        self.trades: List[TradeRecord] = []
        self.original_trades: List[TradeRecord] = []
        self.adjusted_trades: List[TradeRecord] = []

        self.original_metrics = StrategyMetrics()
        self.adjusted_metrics = StrategyMetrics()

        self.session_start = datetime.utcnow()
        self.phase: str = "shadow"  # "shadow" or "live"

        logger.info(f"Shadow Mode {'ENABLED' if enable_shadow_mode else 'DISABLED'}")

    def log_decision(
        self,
        symbol: str,
        original_decision: Dict,
        adjusted_decision: Dict,
        context_report: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        """
        Log both original and adjusted decisions.
        
        Args:
            symbol: Trading symbol (e.g., "BTC/USDT")
            original_decision: Decision from Meta model only
            adjusted_decision: Decision after context adjustment
            context_report: Context report if available
            metadata: Additional metadata
        """
        if not self.enable_shadow_mode:
            return

        timestamp = datetime.utcnow().isoformat()

        original_action = original_decision.get("action", "HOLD")
        adjusted_action = adjusted_decision.get("action", "HOLD")

        original_posterior = original_decision.get("posterior_probability", 0.5)
        adjusted_posterior = adjusted_decision.get("adjusted_posterior", adjusted_decision.get("posterior_probability", 0.5))

        entry_price = original_decision.get("expected_return", 0)

        meta = {
            "original_meta_prob": original_decision.get("meta_probability"),
            "context_risk_level": adjusted_decision.get("context_risk_level"),
            "context_adjustments_count": len(adjusted_decision.get("context_adjustments", [])),
        }
        if metadata:
            meta.update(metadata)

        record = TradeRecord(
            timestamp=timestamp,
            symbol=symbol,
            original_action=original_action,
            adjusted_action=adjusted_action,
            original_posterior=original_posterior,
            adjusted_posterior=adjusted_posterior,
            entry_price=entry_price,
            metadata=meta,
        )

        self.trades.append(record)

        # Log to file (real-time)
        self._write_trade_log(record)

        # Log summary if actions differ
        if original_action != adjusted_action:
            logger.info(
                f"⚠️ Decision CHANGED: {symbol} {original_action} → {adjusted_action} "
                f"(posteriors: {original_posterior:.3f} → {adjusted_posterior:.3f})"
            )
            self._write_decision_change_log(record, context_report)

    def update_trade_exit(
        self,
        symbol: str,
        exit_price: float,
        timestamp: Optional[str] = None,
    ) -> None:
        """
        Update a trade with exit price and calculate PnL.
        
        Args:
            symbol: Trading symbol
            exit_price: Exit/close price
            timestamp: Trade entry timestamp (to match records)
        """
        if not self.enable_shadow_mode or not self.trades:
            return

        # Find matching trade (latest for symbol if timestamp not provided)
        matching_trade = None
        for trade in reversed(self.trades):
            if trade.symbol == symbol and trade.exit_price is None:
                if timestamp is None or trade.timestamp == timestamp:
                    matching_trade = trade
                    break

        if not matching_trade:
            logger.warning(f"No open trade found for {symbol}")
            return

        # Calculate PnL
        pnl_pct = ((exit_price - matching_trade.entry_price) / matching_trade.entry_price * 100)
        matching_trade.exit_price = exit_price
        matching_trade.pnl_pct = pnl_pct

        logger.info(f"Trade closed: {symbol} PnL: {pnl_pct:+.2f}%")

    def calculate_metrics(self) -> Dict:
        """
        Calculate metrics for both strategies.
        
        Returns:
            Comparison dict with both metrics
        """
        closed_trades = [t for t in self.trades if t.pnl_pct is not None]

        if not closed_trades:
            logger.warning("No closed trades yet for metrics calculation")
            return {
                "status": "NO_CLOSED_TRADES",
                "trades_closed": 0,
            }

        # Separate by action/strategy
        original_pnls = []
        adjusted_pnls = []

        for trade in closed_trades:
            if trade.original_action in ["BUY", "SELL"]:
                original_pnls.append(trade.pnl_pct)
            if trade.adjusted_action in ["BUY", "SELL"]:
                adjusted_pnls.append(trade.pnl_pct)

        # Calculate metrics
        original_metrics = self._calculate_strategy_metrics(original_pnls)
        adjusted_metrics = self._calculate_strategy_metrics(adjusted_pnls)

        self.original_metrics = original_metrics
        self.adjusted_metrics = adjusted_metrics

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "total_trades_tracked": len(self.trades),
            "closed_trades": len(closed_trades),
            "decision_changes": sum(1 for t in self.trades if t.original_action != t.adjusted_action),
            "original_strategy": original_metrics.to_dict(),
            "adjusted_strategy": adjusted_metrics.to_dict(),
            "comparison": self._compare_strategies(original_metrics, adjusted_metrics),
        }

    def _calculate_strategy_metrics(self, pnls: List[float]) -> StrategyMetrics:
        """Calculate metrics from PnL list."""
        if not pnls:
            return StrategyMetrics()

        winning = [p for p in pnls if p > 0]
        losing = [p for p in pnls if p < 0]

        avg_win = sum(winning) / len(winning) if winning else 0.0
        avg_loss = abs(sum(losing) / len(losing)) if losing else 0.0

        gross_profit = sum(winning) if winning else 0.0
        gross_loss = abs(sum(losing)) if losing else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        total_pnl = sum(pnls)
        win_rate = len(winning) / len(pnls) * 100

        # Simple max drawdown (approximation)
        cumsum = np.cumsum(pnls)
        max_drawdown = min(0, min(cumsum - cumsum.max()))

        return StrategyMetrics(
            total_trades=len(pnls),
            winning_trades=len(winning),
            losing_trades=len(losing),
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_pnl_pct=total_pnl,
            max_drawdown=max_drawdown,
            closed_trades=len(pnls),
        )

    def _compare_strategies(
        self,
        original: StrategyMetrics,
        adjusted: StrategyMetrics,
    ) -> Dict:
        """Compare two strategies."""
        return {
            "win_rate_delta_pct": adjusted.win_rate - original.win_rate,
            "profit_factor_delta": adjusted.profit_factor - original.profit_factor,
            "total_pnl_delta_pct": adjusted.total_pnl_pct - original.total_pnl_pct,
            "max_drawdown_delta_pct": adjusted.max_drawdown - original.max_drawdown,
            "recommendation": self._get_recommendation(original, adjusted),
        }

    def _get_recommendation(
        self,
        original: StrategyMetrics,
        adjusted: StrategyMetrics,
    ) -> str:
        """Determine if context adjustments improved performance."""
        improvement_score = 0

        if adjusted.win_rate > original.win_rate:
            improvement_score += 1
        if adjusted.profit_factor > original.profit_factor:
            improvement_score += 1
        if adjusted.total_pnl_pct > original.total_pnl_pct:
            improvement_score += 1
        if adjusted.max_drawdown > original.max_drawdown:  # Higher (less negative) is better
            improvement_score += 1

        if improvement_score >= 3:
            return "ENABLE_CONTEXT_ADJUSTMENTS"
        elif improvement_score <= 1:
            return "CONTINUE_SHADOW_MODE"
        else:
            return "INCONCLUSIVE_NEED_MORE_DATA"

    def _write_trade_log(self, record: TradeRecord) -> None:
        """Write trade record to log file."""
        log_file = self.log_dir / f"trades_{self.session_start.strftime('%Y%m%d_%H%M%S')}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(record.to_dict()) + "\n")

    def _write_decision_change_log(
        self,
        record: TradeRecord,
        context_report: Optional[Dict],
    ) -> None:
        """Log when decisions change due to context."""
        change_log = {
            "timestamp": record.timestamp,
            "symbol": record.symbol,
            "change": f"{record.original_action} → {record.adjusted_action}",
            "posteriors": {
                "original": record.original_posterior,
                "adjusted": record.adjusted_posterior,
            },
            "context_details": context_report,
        }
        
        log_file = self.log_dir / f"decision_changes_{self.session_start.strftime('%Y%m%d_%H%M%S')}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(change_log) + "\n")

    def generate_report(self) -> Dict:
        """Generate comprehensive shadow mode report."""
        metrics = self.calculate_metrics()

        days_tracked = (datetime.utcnow() - self.session_start).days + 1

        report = {
            "session_duration_days": days_tracked,
            "phase": self.phase,
            "metrics": metrics,
            "recommendation": self._get_recommendation(
                self.original_metrics,
                self.adjusted_metrics,
            ),
            "timestamp": datetime.utcnow().isoformat(),
        }

        return report

    def save_report(self, filename: Optional[str] = None) -> str:
        """Save report to file."""
        report = self.generate_report()

        if filename is None:
            filename = f"shadow_mode_report_{self.session_start.strftime('%Y%m%d_%H%M%S')}.json"

        filepath = self.log_dir / filename
        with open(filepath, "w") as f:
            json.dump(report, f, indent=2)

        logger.info(f"✓ Report saved to {filepath}")
        return str(filepath)


import numpy as np


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Example usage
    tracker = ShadowModeTracker(enable_shadow_mode=True)

    # Log some decisions
    for i in range(5):
        original_decision = {
            "action": "BUY" if i < 3 else "SELL",
            "posterior_probability": 0.7 + i * 0.01,
            "meta_probability": 0.75,
        }

        adjusted_decision = {
            "action": "HOLD" if i == 2 else original_decision["action"],
            "adjusted_posterior": 0.65 + i * 0.01,
            "context_risk_level": "HIGH" if i == 2 else "LOW",
            "context_adjustments": [] if i != 2 else [{"layer": "macro", "impact": -0.1}],
        }

        tracker.log_decision(
            f"BTC/USDT",
            original_decision,
            adjusted_decision,
            metadata={"attempt": i},
        )

    # Report
    report = tracker.generate_report()
    print(json.dumps(report, indent=2))
