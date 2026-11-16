"""CARM Read-Only Shadow Observer.

Provides causal, read-only shadow observation of the CARM_WEEKLY_ONLY candidate strategy
evaluated in lockstep against two canonical benchmarks:
  1. CARM_VIRTUAL_PORTFOLIO_STATE (Weekly rebalanced top-3 cross-sectional momentum)
  2. BTC_BUY_AND_HOLD_BENCHMARK (100% BTC spot hold from identical initial capital)
  3. CASH_BENCHMARK (100% USD/USDT hold with zero return and zero drawdown)

Guarantees:
  - STRICT READ-ONLY: ZERO exchange orders, ZERO execution API calls, ZERO real trades.
  - CAUSAL EXECUTION: Signal computation strictly precedes execution price application.
  - IDENTICAL CAPITAL: All 3 portfolios begin with exactly $10,000.00 initial capital.
  - IDENTICAL TIMELINE: All portfolios step synchronously on the same timestamp clock.
  - EXACT TRANSACTION COSTS: 12 bps standard execution friction deducted on every rebalance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Safety enforcement flags
REAL_TRADING: bool = False
LIVE_EXCHANGE_PERMISSION: bool = False
PRODUCTION_CANDIDATE: bool = False

# Default Canonical CARM Constants
DEFAULT_INITIAL_CAPITAL_USD: float = 10_000.0
DEFAULT_FEE_BPS: float = 12.0  # 12 bps = 0.0012 per leg
DEFAULT_REBALANCE_HOURS: int = 168  # 7 days * 24 hours
DEFAULT_TOP_K: int = 3
CANONICAL_UNIVERSE: Tuple[str, ...] = (
    "ADAUSDT",
    "BNBUSDT",
    "BTCUSDT",
    "ETHUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "SOLUSDT",
    "XRPUSDT",
)
BENCHMARK_BTC_SYMBOL: str = "BTCUSDT"


@dataclass
class VirtualPortfolioState:
    """Represents the in-memory state of an observed virtual portfolio."""

    portfolio_name: str
    cash_usd: float
    holdings: Dict[str, float] = field(default_factory=dict)
    equity_usd: float = 0.0
    cumulative_fees_usd: float = 0.0
    cumulative_turnover: float = 0.0
    rebalance_count: int = 0
    peak_equity_usd: float = 0.0
    max_drawdown_pct: float = 0.0

    def update_valuation(self, prices: Dict[str, float]) -> float:
        """Mark holdings to current market prices and update equity & drawdown."""
        assets_val = sum(
            qty * prices[sym]
            for sym, qty in self.holdings.items()
            if sym in prices and prices[sym] > 0.0
        )
        self.equity_usd = float(self.cash_usd + assets_val)
        if self.equity_usd > self.peak_equity_usd:
            self.peak_equity_usd = self.equity_usd

        if self.peak_equity_usd > 0.0:
            dd = (self.equity_usd - self.peak_equity_usd) / self.peak_equity_usd * 100.0
            if dd < self.max_drawdown_pct:
                self.max_drawdown_pct = float(dd)

        return self.equity_usd

    def get_asset_weights(self, prices: Dict[str, float]) -> Dict[str, float]:
        """Calculate current portfolio weights for each held asset."""
        if self.equity_usd <= 1e-6:
            return {sym: 0.0 for sym in self.holdings}
        return {
            sym: (self.holdings.get(sym, 0.0) * prices.get(sym, 0.0)) / self.equity_usd
            for sym in self.holdings
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize state snapshot to dictionary."""
        return {
            "portfolio_name": self.portfolio_name,
            "cash_usd": round(self.cash_usd, 4),
            "holdings": {k: round(v, 8) for k, v in self.holdings.items() if abs(v) > 1e-8},
            "equity_usd": round(self.equity_usd, 2),
            "cumulative_fees_usd": round(self.cumulative_fees_usd, 4),
            "cumulative_turnover": round(self.cumulative_turnover, 4),
            "rebalance_count": self.rebalance_count,
            "peak_equity_usd": round(self.peak_equity_usd, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
        }


@dataclass
class ObserverTickResult:
    """Results from a single clock step of the shadow observer."""

    timestamp: Any
    prices: Dict[str, float]
    carm_state: Dict[str, Any]
    btc_bh_state: Dict[str, Any]
    cash_state: Dict[str, Any]
    rebalance_triggered: bool
    rebalance_details: Optional[Dict[str, Any]] = None

    @property
    def carm_equity(self) -> float:
        return self.carm_state["equity_usd"]

    @property
    def btc_bh_equity(self) -> float:
        return self.btc_bh_state["equity_usd"]

    @property
    def cash_equity(self) -> float:
        return self.cash_state["equity_usd"]


class CarmShadowObserver:
    """Multi-portfolio forward shadow observer for CARM vs Benchmarks.

    Operates completely decoupled from live trading infrastructure.
    Maintains causal order and accurate transaction cost deduction.
    """

    def __init__(
        self,
        universe: Optional[Sequence[str]] = None,
        initial_capital_usd: float = DEFAULT_INITIAL_CAPITAL_USD,
        fee_bps: float = DEFAULT_FEE_BPS,
        rebalance_interval_hours: int = DEFAULT_REBALANCE_HOURS,
        top_k: int = DEFAULT_TOP_K,
        causal_delay_bars: int = 1,
    ) -> None:
        self.universe: List[str] = sorted(list(universe or CANONICAL_UNIVERSE))
        self.initial_capital_usd: float = float(initial_capital_usd)
        self.fee_bps: float = float(fee_bps)
        self.fee_rate: float = self.fee_bps / 10_000.0
        self.rebalance_interval_hours: int = int(rebalance_interval_hours)
        self.top_k: int = int(top_k)
        self.causal_delay_bars: int = int(causal_delay_bars)

        # Internal virtual portfolios
        self.carm_portfolio = VirtualPortfolioState(
            portfolio_name="CARM_WEEKLY_ONLY",
            cash_usd=self.initial_capital_usd,
            holdings={sym: 0.0 for sym in self.universe},
            equity_usd=self.initial_capital_usd,
            peak_equity_usd=self.initial_capital_usd,
        )
        self.btc_portfolio = VirtualPortfolioState(
            portfolio_name="BTC_BUY_AND_HOLD",
            cash_usd=self.initial_capital_usd,
            holdings={BENCHMARK_BTC_SYMBOL: 0.0},
            equity_usd=self.initial_capital_usd,
            peak_equity_usd=self.initial_capital_usd,
        )
        self.cash_portfolio = VirtualPortfolioState(
            portfolio_name="CASH",
            cash_usd=self.initial_capital_usd,
            holdings={},
            equity_usd=self.initial_capital_usd,
            peak_equity_usd=self.initial_capital_usd,
        )

        # Price history buffer for causal momentum calculation
        self._price_history: List[Tuple[Any, Dict[str, float]]] = []
        self._step_count: int = 0
        self._btc_incepted: bool = False
        self._carm_incepted: bool = False

    def step(
        self,
        timestamp: Any,
        prices: Dict[str, float],
        warmup_history: Optional[pd.DataFrame] = None,
    ) -> ObserverTickResult:
        """Execute one forward step with given timestamp and market prices.

        Args:
            timestamp: Clock timestamp (ISO string, datetime, or integer timestamp).
            prices: Dictionary of current spot closing prices for universe symbols.
            warmup_history: Optional historical price DataFrame with columns matching universe
                used when starting observation without pre-buffered history.

        Returns:
            ObserverTickResult containing updated states and rebalance details.
        """
        # Validate inputs
        clean_prices = {sym: float(prices[sym]) for sym in self.universe if sym in prices}
        if BENCHMARK_BTC_SYMBOL not in clean_prices and BENCHMARK_BTC_SYMBOL in prices:
            clean_prices[BENCHMARK_BTC_SYMBOL] = float(prices[BENCHMARK_BTC_SYMBOL])

        # Buffer price
        self._price_history.append((timestamp, clean_prices))
        self._step_count += 1

        # 1. Update BTC Buy and Hold Inception
        if not self._btc_incepted and BENCHMARK_BTC_SYMBOL in clean_prices:
            btc_price = clean_prices[BENCHMARK_BTC_SYMBOL]
            if btc_price > 0.0:
                fee = self.initial_capital_usd * self.fee_rate
                investable = self.initial_capital_usd - fee
                self.btc_portfolio.holdings[BENCHMARK_BTC_SYMBOL] = investable / btc_price
                self.btc_portfolio.cash_usd = 0.0
                self.btc_portfolio.cumulative_fees_usd += fee
                self.btc_portfolio.cumulative_turnover += 1.0
                self.btc_portfolio.rebalance_count += 1
                self._btc_incepted = True

        # 2. Check CARM Rebalance Decision Clock
        rebalance_triggered = False
        rebalance_details: Optional[Dict[str, Any]] = None

        # Check if scheduled rebalance tick
        is_scheduled_rebalance = (self._step_count - 1) % self.rebalance_interval_hours == 0

        # Calculate momentum if rebalance point
        if is_scheduled_rebalance:
            momentum_scores = self._compute_causal_momentum(warmup_history)
            if momentum_scores is not None:
                rebalance_details = self._rebalance_carm(clean_prices, momentum_scores)
                rebalance_triggered = True
                self._carm_incepted = True

        # 3. Update Mark-to-Market Valuations for all 3 portfolios
        self.carm_portfolio.update_valuation(clean_prices)
        self.btc_portfolio.update_valuation(clean_prices)
        self.cash_portfolio.update_valuation(clean_prices)

        return ObserverTickResult(
            timestamp=timestamp,
            prices=clean_prices,
            carm_state=self.carm_portfolio.to_dict(),
            btc_bh_state=self.btc_portfolio.to_dict(),
            cash_state=self.cash_portfolio.to_dict(),
            rebalance_triggered=rebalance_triggered,
            rebalance_details=rebalance_details,
        )

    def _compute_causal_momentum(
        self,
        warmup_history: Optional[pd.DataFrame] = None,
    ) -> Optional[Dict[str, float]]:
        """Compute causal 168h percentage return for each universe symbol.

        Applies causal delay to ensure zero lookahead bias.
        """
        required_len = self.rebalance_interval_hours + self.causal_delay_bars + 1

        # If warmup history DataFrame is provided, use it
        if warmup_history is not None and len(warmup_history) >= required_len:
            # Last available causal decision bar is at index -(1 + causal_delay_bars)
            t_eval = len(warmup_history) - 1 - self.causal_delay_bars
            t_base = t_eval - self.rebalance_interval_hours
            if t_base >= 0:
                p_eval = warmup_history.iloc[t_eval]
                p_base = warmup_history.iloc[t_base]
                mom = {}
                for sym in self.universe:
                    if sym in p_eval and sym in p_base and p_base[sym] > 0.0:
                        mom[sym] = float((p_eval[sym] / p_base[sym]) - 1.0)
                    else:
                        mom[sym] = float("-inf")
                return mom

        # Otherwise check internal price history buffer
        if len(self._price_history) >= required_len:
            t_eval_idx = len(self._price_history) - 1 - self.causal_delay_bars
            t_base_idx = t_eval_idx - self.rebalance_interval_hours
            if t_base_idx >= 0:
                p_eval = self._price_history[t_eval_idx][1]
                p_base = self._price_history[t_base_idx][1]
                mom = {}
                for sym in self.universe:
                    if sym in p_eval and sym in p_base and p_base[sym] > 0.0:
                        mom[sym] = float((p_eval[sym] / p_base[sym]) - 1.0)
                    else:
                        mom[sym] = float("-inf")
                return mom

        # Not enough history yet for momentum calculation
        return None

    def _rebalance_carm(
        self,
        current_prices: Dict[str, float],
        momentum_scores: Dict[str, float],
    ) -> Dict[str, Any]:
        """Execute causal virtual rebalancing for CARM_WEEKLY_ONLY portfolio."""
        # Rank assets by momentum descending
        ranked_assets = sorted(
            [sym for sym in self.universe if sym in momentum_scores and momentum_scores[sym] > float("-inf")],
            key=lambda s: momentum_scores[s],
            reverse=True,
        )

        # Select Top-K assets
        selected_assets = ranked_assets[: self.top_k]

        # Calculate current equity before trade
        current_asset_vals = {
            sym: self.carm_portfolio.holdings.get(sym, 0.0) * current_prices.get(sym, 0.0)
            for sym in self.universe
        }
        equity_before = self.carm_portfolio.cash_usd + sum(current_asset_vals.values())
        if equity_before <= 1e-6:
            equity_before = self.initial_capital_usd

        # Current asset weights
        current_w = {
            sym: current_asset_vals.get(sym, 0.0) / equity_before
            for sym in self.universe
        }

        # Target weights: Top-K equal-weighted
        target_w = {sym: 0.0 for sym in self.universe}
        if selected_assets:
            weight_per_asset = 1.0 / len(selected_assets)
            for sym in selected_assets:
                target_w[sym] = weight_per_asset

        # Delta weight turnover: sum(|w_target - w_current|)
        dw = sum(abs(target_w[sym] - current_w[sym]) for sym in self.universe)

        # Transaction fee deduction: equity_before * turnover * fee_rate
        fee = equity_before * dw * self.fee_rate
        post_fee_equity = max(equity_before - fee, 0.0)

        # Apply target holdings
        new_holdings = {sym: 0.0 for sym in self.universe}
        allocated_val = 0.0
        for sym in selected_assets:
            sym_price = current_prices.get(sym, 0.0)
            if sym_price > 0.0:
                asset_alloc = post_fee_equity * target_w[sym]
                new_holdings[sym] = asset_alloc / sym_price
                allocated_val += asset_alloc

        new_cash = max(post_fee_equity - allocated_val, 0.0)

        # Update CARM portfolio state
        self.carm_portfolio.holdings = new_holdings
        self.carm_portfolio.cash_usd = new_cash
        self.carm_portfolio.equity_usd = post_fee_equity
        self.carm_portfolio.cumulative_fees_usd += fee
        self.carm_portfolio.cumulative_turnover += dw
        self.carm_portfolio.rebalance_count += 1

        return {
            "selected_assets": selected_assets,
            "momentum_scores": {s: round(momentum_scores[s], 6) for s in selected_assets},
            "turnover": round(dw, 6),
            "fee_usd": round(fee, 4),
            "equity_before": round(equity_before, 2),
            "post_fee_equity": round(post_fee_equity, 2),
            "target_weights": {s: round(target_w[s], 4) for s in selected_assets},
        }

    def run_simulation(
        self,
        piv_close: pd.DataFrame,
    ) -> List[ObserverTickResult]:
        """Run batch simulation over a panel of hourly close prices.

        Args:
            piv_close: DataFrame indexed by timestamp with columns as symbols.

        Returns:
            List of ObserverTickResult for each timestamp.
        """
        results: List[ObserverTickResult] = []
        n_bars = len(piv_close)

        for i in range(n_bars):
            ts = piv_close.index[i]
            prices = piv_close.iloc[i].to_dict()
            # Provide causal sub-slice up to bar i as warmup
            sub_history = piv_close.iloc[: i + 1]
            res = self.step(timestamp=ts, prices=prices, warmup_history=sub_history)
            results.append(res)

        return results
