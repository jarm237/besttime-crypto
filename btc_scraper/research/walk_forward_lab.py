"""
btc_scraper/research/walk_forward_lab.py
Phase M4-D / M4-E: Walk-Forward Economic Screening Laboratory.

Implements:
1. WalkForwardSplitter: Chronological fold generation with label overlap purging and embargo.
2. FoldEconomicResult & StrategyEvaluationSummary: Full economic accounting (Gross/Net PnL, profit factor, max drawdown, expectancy).
3. CandidateDisposition: Rigorous classification into REJECTED, INSUFFICIENT_EVIDENCE, RESEARCH_ONLY, and CANDIDATE_FOR_M5.
4. WalkForwardLab: Orchestrates multi-fold evaluation through the canonical ExperimentRunner.
"""
from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from btc_scraper.research.baseline_runner import (
    BaselineStrategy,
    ExperimentRunner,
)
from btc_scraper.research.dataset_provider import HistoricalDatasetProvider
from btc_scraper.research.experiment_contract import (
    ExperimentResult,
    ExperimentSpec,
    freeze_nested,
    unfreeze_nested,
)
from btc_scraper.research.strategy_registry import (
    StrategyRegistry,
    StrategySpec,
)


@dataclass(frozen=True)
class WalkForwardFold:
    """
    Defines a single chronological walk-forward fold with train/val separation and purge embargo.
    """
    fold_id: int
    train_start: str
    train_end: str
    val_start: str
    val_end: str
    purge_gap_hours: int = 24

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WalkForwardSplitter:
    """
    Splits a historical time span into non-overlapping chronological validation windows.
    Guarantees strict train/val separation and enforces a purge gap to prevent label leakage.
    """

    @classmethod
    def generate_folds(
        cls,
        start_time: str,
        end_time: str,
        n_folds: int = 3,
        val_ratio: float = 0.25,
        purge_gap_hours: int = 24,
    ) -> List[WalkForwardFold]:
        """
        Generates expanding-window walk-forward folds.
        For fold k:
          train: [start_time, T_k]
          purge gap: [T_k, T_k + purge_gap_hours]
          val: [T_k + purge_gap_hours, V_k]
        """
        dt_start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        dt_end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        total_seconds = (dt_end - dt_start).total_seconds()

        if total_seconds <= 0:
            raise ValueError(f"Invalid time bounds: start_time={start_time} >= end_time={end_time}")

        # Total validation span
        val_total_seconds = total_seconds * val_ratio
        val_fold_seconds = val_total_seconds / n_folds
        purge_delta = timedelta(hours=purge_gap_hours)

        folds: List[WalkForwardFold] = []
        for i in range(n_folds):
            # Validation window boundaries
            fold_val_end = dt_end - timedelta(seconds=(n_folds - 1 - i) * val_fold_seconds)
            fold_val_start = fold_val_end - timedelta(seconds=val_fold_seconds)

            # Training window boundaries with purge gap before val
            fold_train_end = fold_val_start - purge_delta
            fold_train_start = dt_start

            if fold_train_end <= fold_train_start:
                raise ValueError(f"Insufficient history to generate fold {i} with purge gap {purge_gap_hours}h")

            folds.append(
                WalkForwardFold(
                    fold_id=i + 1,
                    train_start=fold_train_start.isoformat().replace("+00:00", "Z"),
                    train_end=fold_train_end.isoformat().replace("+00:00", "Z"),
                    val_start=fold_val_start.isoformat().replace("+00:00", "Z"),
                    val_end=fold_val_end.isoformat().replace("+00:00", "Z"),
                    purge_gap_hours=purge_gap_hours,
                )
            )

        return folds


@dataclass(frozen=True)
class FoldEconomicResult:
    """
    Economic performance metrics for a strategy on an individual walk-forward fold.
    """
    fold_id: int
    strategy_id: str
    symbol: str
    val_window: str
    gross_pnl: float
    net_pnl: float
    total_fees: float
    total_slippage: float
    final_equity: float
    trade_count: int
    win_rate: Optional[float]
    profit_factor: Optional[float]
    net_expectancy: Optional[float]
    max_drawdown: float
    exposure_time_pct: float
    turnover: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StrategyEvaluationSummary:
    """
    Aggregated multi-fold evaluation report and candidate disposition.
    """
    strategy_id: str
    strategy_name: str
    tier: str
    status: str
    symbol: str
    total_gross_pnl: float
    total_net_pnl: float
    total_fees: float
    total_slippage: float
    aggregate_profit_factor: Optional[float]
    aggregate_win_rate: Optional[float]
    total_trades: int
    max_drawdown: float
    disposition: str  # "REJECTED", "INSUFFICIENT_EVIDENCE", "RESEARCH_ONLY", "CANDIDATE_FOR_M5"
    disposition_reason: str
    fold_results: Tuple[FoldEconomicResult, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "tier": self.tier,
            "status": self.status,
            "symbol": self.symbol,
            "total_gross_pnl": self.total_gross_pnl,
            "total_net_pnl": self.total_net_pnl,
            "total_fees": self.total_fees,
            "total_slippage": self.total_slippage,
            "aggregate_profit_factor": self.aggregate_profit_factor,
            "aggregate_win_rate": self.aggregate_win_rate,
            "total_trades": self.total_trades,
            "max_drawdown": self.max_drawdown,
            "disposition": self.disposition,
            "disposition_reason": self.disposition_reason,
            "fold_results": [f.to_dict() for f in self.fold_results],
        }


class WalkForwardLab:
    """
    Strategy Laboratory executor.
    Runs baseline and candidate strategies across walk-forward folds and assigns empirical dispositions.
    """

    def __init__(
        self,
        provider: HistoricalDatasetProvider,
        registry: StrategyRegistry,
    ):
        self.provider = provider
        self.registry = registry

    def evaluate_strategy_on_folds(
        self,
        strategy_id: str,
        symbol: str,
        timeframe: str,
        folds: Sequence[WalkForwardFold],
        base_spec: ExperimentSpec,
    ) -> StrategyEvaluationSummary:
        """
        Evaluates a strategy across all specified walk-forward folds.
        """
        spec_meta = self.registry.get_spec(strategy_id)
        fold_results: List[FoldEconomicResult] = []

        total_gross = 0.0
        total_net = 0.0
        total_fees = 0.0
        total_slip = 0.0
        total_trades = 0
        total_wins = 0
        gross_wins = 0.0
        gross_losses = 0.0
        max_dd = 0.0

        for fold in folds:
            # Load validation candles
            candles = self.provider.load_candles(
                symbol=symbol,
                timeframe=timeframe,
                start_time=fold.val_start,
                end_time=fold.val_end,
                include_warmup=True,
            )

            if len(candles) < 20:
                continue

            # Instantiate strategy & runner with fold-specific ExperimentSpec
            strategy = self.registry.create(strategy_id)
            fold_spec = ExperimentSpec(
                experiment_id=f"{base_spec.experiment_id}_{strategy_id}_{symbol}_fold{fold.fold_id}",
                strategy_id=strategy_id,
                strategy_version=base_spec.strategy_version,
                dataset_manifest_identity=base_spec.dataset_manifest_identity,
                feature_set_version=base_spec.feature_set_version,
                symbol_universe=(symbol,),
                timeframe=timeframe,
                oos_window=(fold.val_start, fold.val_end),
                strategy_tier=spec_meta.tier,
                initial_capital=base_spec.initial_capital,
                allocation_pct=base_spec.allocation_pct,
                max_open_positions=base_spec.max_open_positions,
                fee_model=base_spec.fee_model,
                slippage_model=base_spec.slippage_model,
                spread_model=base_spec.spread_model,
                funding_model=base_spec.funding_model,
                execution_timing_policy=base_spec.execution_timing_policy,
                same_candle_policy=base_spec.same_candle_policy,
            )
            runner = ExperimentRunner(fold_spec, liquidate_at_end=True)
            res = runner.run(strategy, {symbol: candles})

            # Extract pre-computed metrics from canonical ExperimentResult
            trades = list(res.trade_lineage)
            t_count = res.total_trades
            win_r = res.win_rate if t_count > 0 else None

            fold_gross = res.gross_pnl
            fold_net = res.net_pnl
            fold_fees = res.total_fees
            fold_slip = res.total_slippage
            fold_pf = res.profit_factor if t_count > 0 else None
            # Normalize max_drawdown to fraction (0.0 to 1.0) for consistent threshold comparison
            fold_dd = (res.max_drawdown_pct / 100.0) if res.max_drawdown_pct is not None else 0.0
            fold_exp = res.expectancy_usd if t_count > 0 else None
            exposure_pct = res.exposure_pct
            turnover = res.turnover

            fold_res = FoldEconomicResult(
                fold_id=fold.fold_id,
                strategy_id=strategy_id,
                symbol=symbol,
                val_window=f"{fold.val_start[:10]} -> {fold.val_end[:10]}",
                gross_pnl=round(fold_gross, 2),
                net_pnl=round(fold_net, 2),
                total_fees=round(fold_fees, 2),
                total_slippage=round(fold_slip, 2),
                final_equity=round(res.final_equity, 2),
                trade_count=t_count,
                win_rate=round(win_r, 4) if win_r is not None else None,
                profit_factor=round(fold_pf, 4) if (fold_pf is not None and not math.isinf(fold_pf)) else (999.0 if (fold_pf is not None and math.isinf(fold_pf)) else None),
                net_expectancy=round(fold_exp, 2) if fold_exp is not None else None,
                max_drawdown=round(fold_dd, 4) if fold_dd is not None else 0.0,
                exposure_time_pct=round(exposure_pct, 4) if exposure_pct is not None else 0.0,
                turnover=round(turnover, 2) if turnover is not None else 0.0,
            )
            fold_results.append(fold_res)

            # Accumulators
            total_gross += fold_gross
            total_net += fold_net
            total_fees += fold_fees
            total_slip += fold_slip
            total_trades += t_count
            total_wins += res.winning_trades
            if fold_dd > max_dd:
                max_dd = fold_dd

            for t in trades:
                pnl = float(t.get("gross_pnl", 0.0))
                if pnl > 0:
                    gross_wins += pnl
                else:
                    gross_losses += abs(pnl)

        # Aggregate metrics (None if 0 trades)
        agg_win_rate = (total_wins / total_trades) if total_trades > 0 else None
        agg_pf = (gross_wins / gross_losses) if gross_losses > 0 else (999.0 if (gross_wins > 0 and total_trades > 0) else None)

        # Assign empirical disposition
        disposition, reason = self._classify_candidate(
            tier=spec_meta.tier,
            total_net=total_net,
            total_trades=total_trades,
            agg_pf=agg_pf,
            max_dd=max_dd,
            fold_results=fold_results,
        )

        return StrategyEvaluationSummary(
            strategy_id=strategy_id,
            strategy_name=spec_meta.strategy_name,
            tier=spec_meta.tier,
            status=spec_meta.status,
            symbol=symbol,
            total_gross_pnl=round(total_gross, 2),
            total_net_pnl=round(total_net, 2),
            total_fees=round(total_fees, 2),
            total_slippage=round(total_slip, 2),
            aggregate_profit_factor=round(agg_pf, 4) if agg_pf is not None else None,
            aggregate_win_rate=round(agg_win_rate, 4) if agg_win_rate is not None else None,
            total_trades=total_trades,
            max_drawdown=round(max_dd, 4),
            disposition=disposition,
            disposition_reason=reason,
            fold_results=tuple(fold_results),
        )

    def _classify_candidate(
        self,
        tier: str,
        total_net: float,
        total_trades: int,
        agg_pf: Optional[float],
        max_dd: float,
        fold_results: Sequence[FoldEconomicResult],
    ) -> Tuple[str, str]:
        """Classifies strategy based on statistical and economic thresholds."""
        if tier == "BENCHMARK":
            return "BENCHMARK", "Passive control or reference baseline"

        if tier == "PROXY":
            return "DIAGNOSTIC_ONLY", "Heuristic proxy; barred from production claim"

        if total_trades < 10:
            return "INSUFFICIENT_EVIDENCE", f"Too few trades ({total_trades} < 10) for statistical significance"

        if total_net <= 0.0:
            return "REJECTED", f"Negative net economic payoff ({total_net:+.2f} USD after costs)"

        pf_val = agg_pf if agg_pf is not None else 0.0
        if pf_val < 1.0:
            return "REJECTED", f"Profit factor ({pf_val:.2f}) < 1.0 after execution costs"

        if max_dd > 0.25:
            return "REJECTED", f"Excessive max drawdown ({max_dd * 100:.1f}% > 25.0%)"

        # Check fold consistency: negative on too many folds
        losing_folds = [f for f in fold_results if f.net_pnl < 0]
        if len(losing_folds) > len(fold_results) // 2:
            return "REJECTED", f"Inconsistent across walk-forward folds ({len(losing_folds)}/{len(fold_results)} folds negative)"

        if total_trades < 30 or pf_val < 1.20:
            return "RESEARCH_ONLY", f"Positive net PnL ({total_net:+.2f} USD) but moderate edge (PF={pf_val:.2f}, N={total_trades})"

        return "CANDIDATE_FOR_M5", f"Consistent positive expectancy across folds (PF={pf_val:.2f}, N={total_trades}, DD={max_dd * 100:.1f}%)"

    def run_screening_suite(
        self,
        symbols: Sequence[str],
        strategy_ids: Sequence[str],
        timeframe: str,
        folds: Sequence[WalkForwardFold],
        base_spec: ExperimentSpec,
    ) -> Dict[str, List[StrategyEvaluationSummary]]:
        """
        Runs complete screening matrix across symbols and strategies.
        Returns mapping from symbol to list of StrategyEvaluationSummary.
        """
        results: Dict[str, List[StrategyEvaluationSummary]] = {}
        for sym in symbols:
            sym_results = []
            for s_id in strategy_ids:
                summary = self.evaluate_strategy_on_folds(
                    strategy_id=s_id,
                    symbol=sym,
                    timeframe=timeframe,
                    folds=folds,
                    base_spec=base_spec,
                )
                sym_results.append(summary)
            results[sym] = sym_results
        return results
