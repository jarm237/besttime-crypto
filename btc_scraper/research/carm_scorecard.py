"""CARM Comparative Economic Scorecard & Append-Only Valuation Ledger.

Provides forward valuation ledger recording and economic performance attribution
comparing:
  1. CARM_WEEKLY_ONLY
  2. BTC_BUY_AND_HOLD_BENCHMARK
  3. CASH_BENCHMARK
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

from btc_scraper.research.carm_shadow_observer import ObserverTickResult


@dataclass
class PortfolioMetrics:
    """Summary metrics for an evaluated portfolio."""

    portfolio_name: str
    initial_capital_usd: float
    final_equity_usd: float
    net_return_pct: float
    max_drawdown_pct: float
    annualized_sharpe: float
    annualized_sortino: float
    total_turnover: float
    rebalance_count: int
    total_fees_usd: float
    excess_return_vs_btc_pct: float = 0.0
    excess_return_vs_cash_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CarmValuationLedger:
    """Append-only forward valuation ledger for CARM shadow observation."""

    def __init__(self, log_path: Optional[Union[str, Path]] = None) -> None:
        self.log_path: Optional[Path] = Path(log_path) if log_path else None
        self.records: List[Dict[str, Any]] = []

        if self.log_path and self.log_path.exists():
            self._load_existing_records()

    def _load_existing_records(self) -> None:
        """Load pre-existing JSONL records."""
        if not self.log_path:
            return
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self.records.append(json.loads(line))

    def append(self, tick_result: ObserverTickResult) -> Dict[str, Any]:
        """Append an observation tick record."""
        ts_str = str(tick_result.timestamp)
        carm_eq = float(tick_result.carm_equity)
        btc_eq = float(tick_result.btc_bh_equity)
        cash_eq = float(tick_result.cash_equity)

        entry = {
            "timestamp": ts_str,
            "carm_equity": round(carm_eq, 2),
            "btc_bh_equity": round(btc_eq, 2),
            "cash_equity": round(cash_eq, 2),
            "data_quality_status": getattr(tick_result, "data_quality_status", "VALID"),
            "rebalance_triggered": tick_result.rebalance_triggered,
            "carm_fees_usd": tick_result.carm_state["cumulative_fees_usd"],
            "carm_turnover": tick_result.carm_state["cumulative_turnover"],
            "carm_rebalances": tick_result.carm_state["rebalance_count"],
            "carm_drawdown_pct": tick_result.carm_state["max_drawdown_pct"],
            "btc_drawdown_pct": tick_result.btc_bh_state["max_drawdown_pct"],
            "carm_holdings": tick_result.carm_state["holdings"],
        }
        if tick_result.rebalance_details:
            entry["rebalance_details"] = tick_result.rebalance_details
        if getattr(tick_result, "rejection_reason", None):
            entry["rejection_reason"] = tick_result.rejection_reason

        self.records.append(entry)

        # Write to JSONL if persistent path specified
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

        return entry

    def to_dataframe(self) -> pd.DataFrame:
        """Convert ledger records to a pandas DataFrame."""
        if not self.records:
            return pd.DataFrame()
        df = pd.DataFrame(self.records)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.set_index("timestamp", inplace=True)
        return df


class CarmComparativeScorecard:
    """Calculates and renders comparative economic metrics across all 3 portfolios."""

    @staticmethod
    def calculate_metrics(
        ledger_df: pd.DataFrame,
        initial_capital_usd: float = 10_000.0,
        periods_per_year: float = 8760.0,  # Hourly bars by default
    ) -> Dict[str, PortfolioMetrics]:
        """Compute performance metrics for CARM, BTC Buy & Hold, and Cash."""
        if ledger_df.empty:
            raise ValueError("Cannot calculate scorecard on empty ledger DataFrame.")

        # Series of equities
        eq_carm = ledger_df["carm_equity"].astype(float)
        eq_btc = ledger_df["btc_bh_equity"].astype(float)
        eq_cash = ledger_df["cash_equity"].astype(float)

        def _compute_for_series(
            name: str,
            series: pd.Series,
            fees: float,
            turnover: float,
            rebalances: int,
        ) -> Tuple[float, float, float, float, float]:
            fin_eq = float(series.iloc[-1])
            net_ret = ((fin_eq / initial_capital_usd) - 1.0) * 100.0

            # Drawdown
            peaks = series.cummax()
            dd_series = (series - peaks) / np.maximum(peaks, 1e-6) * 100.0
            max_dd = float(dd_series.min())

            # Returns for Sharpe / Sortino
            rets = series.pct_change().dropna()
            if len(rets) > 1 and rets.std() > 1e-8:
                mean_r = float(rets.mean())
                std_r = float(rets.std())
                ann_sharpe = float((mean_r / std_r) * np.sqrt(periods_per_year))

                downside = rets[rets < 0.0]
                if len(downside) > 0 and downside.std() > 1e-8:
                    ann_sortino = float((mean_r / downside.std()) * np.sqrt(periods_per_year))
                else:
                    ann_sortino = ann_sharpe
            else:
                ann_sharpe = 0.0
                ann_sortino = 0.0

            return fin_eq, net_ret, max_dd, ann_sharpe, ann_sortino

        # CARM metrics
        carm_fees = float(ledger_df["carm_fees_usd"].iloc[-1]) if "carm_fees_usd" in ledger_df else 0.0
        carm_turnover = float(ledger_df["carm_turnover"].iloc[-1]) if "carm_turnover" in ledger_df else 0.0
        carm_rebal = int(ledger_df["carm_rebalances"].iloc[-1]) if "carm_rebalances" in ledger_df else 0

        fin_carm, ret_carm, mdd_carm, sh_carm, so_carm = _compute_for_series(
            "CARM_WEEKLY_ONLY", eq_carm, carm_fees, carm_turnover, carm_rebal
        )

        # BTC metrics
        fin_btc, ret_btc, mdd_btc, sh_btc, so_btc = _compute_for_series(
            "BTC_BUY_AND_HOLD", eq_btc, 12.0, 1.0, 1
        )

        # Cash metrics
        fin_cash, ret_cash, mdd_cash, sh_cash, so_cash = _compute_for_series(
            "CASH", eq_cash, 0.0, 0.0, 0
        )

        metrics = {
            "CARM_WEEKLY_ONLY": PortfolioMetrics(
                portfolio_name="CARM_WEEKLY_ONLY",
                initial_capital_usd=initial_capital_usd,
                final_equity_usd=round(fin_carm, 2),
                net_return_pct=round(ret_carm, 2),
                max_drawdown_pct=round(mdd_carm, 2),
                annualized_sharpe=round(sh_carm, 3),
                annualized_sortino=round(so_carm, 3),
                total_turnover=round(carm_turnover, 2),
                rebalance_count=carm_rebal,
                total_fees_usd=round(carm_fees, 2),
                excess_return_vs_btc_pct=round(ret_carm - ret_btc, 2),
                excess_return_vs_cash_pct=round(ret_carm - ret_cash, 2),
            ),
            "BTC_BUY_AND_HOLD": PortfolioMetrics(
                portfolio_name="BTC_BUY_AND_HOLD",
                initial_capital_usd=initial_capital_usd,
                final_equity_usd=round(fin_btc, 2),
                net_return_pct=round(ret_btc, 2),
                max_drawdown_pct=round(mdd_btc, 2),
                annualized_sharpe=round(sh_btc, 3),
                annualized_sortino=round(so_btc, 3),
                total_turnover=1.0,
                rebalance_count=1,
                total_fees_usd=12.0,
                excess_return_vs_btc_pct=0.0,
                excess_return_vs_cash_pct=round(ret_btc - ret_cash, 2),
            ),
            "CASH": PortfolioMetrics(
                portfolio_name="CASH",
                initial_capital_usd=initial_capital_usd,
                final_equity_usd=round(fin_cash, 2),
                net_return_pct=round(ret_cash, 2),
                max_drawdown_pct=round(mdd_cash, 2),
                annualized_sharpe=0.0,
                annualized_sortino=0.0,
                total_turnover=0.0,
                rebalance_count=0,
                total_fees_usd=0.0,
                excess_return_vs_btc_pct=round(ret_cash - ret_btc, 2),
                excess_return_vs_cash_pct=0.0,
            ),
        }
        return metrics

    @staticmethod
    def generate_markdown_scorecard(metrics: Dict[str, PortfolioMetrics]) -> str:
        """Render markdown comparative scorecard table."""
        lines = [
            "| Portfolio / Benchmark | Initial Capital ($) | Final Equity ($) | Net Return (%) | Max Drawdown (%) | Ann. Sharpe | Ann. Sortino | Turnover | Rebalances | Total Fees ($) | Excess vs BTC (%) |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        order = ["CARM_WEEKLY_ONLY", "BTC_BUY_AND_HOLD", "CASH"]
        for key in order:
            m = metrics.get(key)
            if not m:
                continue
            ret_str = f"**{m.net_return_pct:+.2f}%**" if m.net_return_pct > 0 else f"{m.net_return_pct:+.2f}%"
            exc_str = f"{m.excess_return_vs_btc_pct:+.2f}%" if key != "BTC_BUY_AND_HOLD" else "—"
            lines.append(
                f"| **{m.portfolio_name}** | ${m.initial_capital_usd:,.2f} | ${m.final_equity_usd:,.2f} | "
                f"{ret_str} | {m.max_drawdown_pct:.2f}% | {m.annualized_sharpe:.3f} | {m.annualized_sortino:.3f} | "
                f"{m.total_turnover:.1f} | {m.rebalance_count} | ${m.total_fees_usd:,.2f} | {exc_str} |"
            )
        return "\n".join(lines)
