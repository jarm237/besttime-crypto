"""CARM Read-Only Prospective Shadow Observer.

Provides causal, read-only shadow observation of the canonical CARM strategy
evaluated in lockstep against two benchmarks:
  1. CARM_WEEKLY_ONLY (Original research parity: equal-weight inception, top-3 weekly momentum)
  2. BTC_BUY_AND_HOLD_BENCHMARK (100% BTC spot hold from identical initial capital)
  3. CASH_BENCHMARK (100% USD/USDT hold with zero return and zero drawdown)

Guarantees:
  - STRICT RESEARCH PARITY: Exactly mirrors `simulate_carm_top_momentum_strategy()` from `0d9f6660`.
  - HOURLY SIGNAL INTEGRITY: Causal 168h momentum evaluated strictly on authenticated hourly bar closes with shift(2) delay.
  - TICKER VALUATION DECOUPLING: Sub-hourly observation ticks update mark-to-market valuation without distorting the 168h momentum window.
  - DURABLE HISTORY: Hourly price buffer is persisted across process restarts to prevent signal starvation.
  - UTC REBALANCE CLOCK: Rebalances anchored to deterministic weekly UTC boundaries (missing ticks do not shift schedule).
  - STRICT READ-ONLY: ZERO exchange orders, ZERO execution API calls, ZERO real trades.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

from btc_scraper.research.carm_market_data import CANONICAL_UNIVERSE

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
DEFAULT_CAUSAL_DELAY_BARS: int = 2  # shift(2) matching 0d9f6660
BENCHMARK_BTC_SYMBOL: str = "BTCUSDT"
STRATEGY_VERSION_CANONICAL: str = "CARM_ORIGINAL_RESEARCH_V1"
STRATEGY_VERSION_CASH_GATED: str = "CARM_CASH_GATED_V2"

# Canonical UTC Weekly Anchor: Sunday 00:00:00 UTC (1970-01-04T00:00:00Z)
CANONICAL_WEEKLY_ANCHOR_EPOCH_SECONDS: int = 259200  # Jan 4, 1970 00:00:00 UTC
SECONDS_PER_WEEK: int = 168 * 3600  # 604,800 seconds


def compute_configuration_fingerprint(
    strategy_version: str,
    universe: Sequence[str],
    top_k: int,
    fee_bps: float,
    rebalance_hours: int,
    require_positive_momentum: bool,
    causal_delay_bars: int,
    initial_allocation_mode: str = "EQUAL_WEIGHT",
    anchor_epoch_seconds: int = CANONICAL_WEEKLY_ANCHOR_EPOCH_SECONDS,
) -> str:
    """Deterministic SHA-256 fingerprint of the frozen strategy configuration."""
    canonical_repr = json.dumps(
        {
            "strategy_version": strategy_version,
            "universe": sorted(list(universe)),
            "top_k": int(top_k),
            "fee_bps": float(fee_bps),
            "rebalance_hours": int(rebalance_hours),
            "require_positive_momentum": bool(require_positive_momentum),
            "causal_delay_bars": int(causal_delay_bars),
            "initial_allocation_mode": str(initial_allocation_mode),
            "anchor_epoch_seconds": int(anchor_epoch_seconds),
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()[:16]


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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VirtualPortfolioState:
        return cls(
            portfolio_name=str(data["portfolio_name"]),
            cash_usd=float(data["cash_usd"]),
            holdings={k: float(v) for k, v in data.get("holdings", {}).items()},
            equity_usd=float(data["equity_usd"]),
            cumulative_fees_usd=float(data.get("cumulative_fees_usd", 0.0)),
            cumulative_turnover=float(data.get("cumulative_turnover", 0.0)),
            rebalance_count=int(data.get("rebalance_count", 0)),
            peak_equity_usd=float(data.get("peak_equity_usd", data["equity_usd"])),
            max_drawdown_pct=float(data.get("max_drawdown_pct", 0.0)),
        )


@dataclass
class ObserverTickResult:
    """Results from a single clock step of the shadow observer."""

    timestamp: str  # ISO 8601 UTC string
    prices: Dict[str, float]
    carm_state: Dict[str, Any]
    btc_bh_state: Dict[str, Any]
    cash_state: Dict[str, Any]
    rebalance_triggered: bool
    data_quality_status: str = "VALID"
    rebalance_details: Optional[Dict[str, Any]] = None
    rejection_reason: Optional[str] = None

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
    Maintains causal order, UTC weekly rebalance schedule, and durable recovery.
    """

    def __init__(
        self,
        universe: Optional[Sequence[str]] = None,
        initial_capital_usd: float = DEFAULT_INITIAL_CAPITAL_USD,
        fee_bps: float = DEFAULT_FEE_BPS,
        rebalance_interval_hours: int = DEFAULT_REBALANCE_HOURS,
        top_k: int = DEFAULT_TOP_K,
        causal_delay_bars: int = DEFAULT_CAUSAL_DELAY_BARS,
        require_positive_momentum: bool = False,  # False = canonical 0d9f6660 parity
        initial_allocation_mode: str = "EQUAL_WEIGHT",  # "EQUAL_WEIGHT" = 0d9f6660 parity
        anchor_epoch_seconds: int = CANONICAL_WEEKLY_ANCHOR_EPOCH_SECONDS,
        epoch_id: str = "EPOCH_20261116_01",
    ) -> None:
        self.universe: List[str] = sorted(list(universe or CANONICAL_UNIVERSE))
        self.initial_capital_usd: float = float(initial_capital_usd)
        self.fee_bps: float = float(fee_bps)
        self.fee_rate: float = self.fee_bps / 10_000.0
        self.rebalance_interval_hours: int = int(rebalance_interval_hours)
        self.top_k: int = int(top_k)
        self.causal_delay_bars: int = int(causal_delay_bars)
        self.require_positive_momentum: bool = bool(require_positive_momentum)
        self.initial_allocation_mode: str = str(initial_allocation_mode)
        self.anchor_epoch_seconds: int = int(anchor_epoch_seconds)
        self.epoch_id: str = str(epoch_id)

        self.strategy_version: str = (
            STRATEGY_VERSION_CASH_GATED if self.require_positive_momentum else STRATEGY_VERSION_CANONICAL
        )
        self.configuration_fingerprint: str = compute_configuration_fingerprint(
            self.strategy_version,
            self.universe,
            self.top_k,
            self.fee_bps,
            self.rebalance_interval_hours,
            self.require_positive_momentum,
            self.causal_delay_bars,
            initial_allocation_mode=self.initial_allocation_mode,
            anchor_epoch_seconds=self.anchor_epoch_seconds,
        )

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

        # Dedicated hourly bar history for causal momentum signal: List of (datetime_utc, prices_dict)
        self.hourly_price_history: List[Tuple[datetime, Dict[str, float]]] = []
        self._last_recorded_bar_hour: Optional[datetime] = None

        self._btc_incepted: bool = False
        self._carm_incepted: bool = False

        # UTC Decision Clock State
        self.last_accepted_timestamp_utc: Optional[datetime] = None
        self.last_accepted_observation_id: Optional[str] = None
        self.last_completed_period_index: Optional[int] = None
        self.last_rebalance_timestamp_utc: Optional[str] = None

        # Modeled Virtual Fills Ledger
        self.virtual_fills: List[Dict[str, Any]] = []

        # Distinct Operational Counters
        self.authentic_forward_observations_count: int = 0
        self.historical_warmup_observations_count: int = 0
        self.rejected_observations_count: int = 0
        self.inception_rebalances_count: int = 0
        self.scheduled_rebalances_count: int = 0
        self.forced_probes_count: int = 0
        self.modeled_virtual_fills_count: int = 0
        self.portfolio_valuations_count: int = 0

    def _parse_timestamp(self, ts: Any) -> datetime:
        """Parse diverse timestamp representations into aware UTC datetime."""
        if isinstance(ts, datetime):
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc)
            return ts.astimezone(timezone.utc)
        if isinstance(ts, (int, float)):
            val = float(ts)
            if val > 1e11:  # ms
                val /= 1000.0
            return datetime.fromtimestamp(val, tz=timezone.utc)
        if isinstance(ts, str):
            clean = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        if hasattr(ts, "to_pydatetime"):
            pydt = ts.to_pydatetime()
            if pydt.tzinfo is None:
                return pydt.replace(tzinfo=timezone.utc)
            return pydt.astimezone(timezone.utc)
        raise ValueError(f"Unsupported timestamp format: {type(ts)} ({ts})")

    def get_period_index(self, ts_utc: datetime) -> int:
        """Calculate canonical 168-hour UTC weekly period index."""
        epoch_sec = ts_utc.timestamp()
        return int((epoch_sec - self.anchor_epoch_seconds) // SECONDS_PER_WEEK)

    def ingest_hourly_bars(self, bars: Sequence[Tuple[Any, Dict[str, float]]]) -> int:
        """Ingest authentic historical or newly completed hourly bars.

        Returns:
            Number of newly added hourly bars.
        """
        existing_ts = {b[0] for b in self.hourly_price_history}
        added = 0
        for raw_ts, p_dict in bars:
            ts_utc = self._parse_timestamp(raw_ts).replace(minute=0, second=0, microsecond=0)
            if ts_utc not in existing_ts:
                clean_p = {sym: float(p_dict[sym]) for sym in self.universe if sym in p_dict and float(p_dict[sym]) > 0.0}
                self.hourly_price_history.append((ts_utc, clean_p))
                existing_ts.add(ts_utc)
                added += 1

        self.hourly_price_history.sort(key=lambda x: x[0])
        if self.hourly_price_history:
            self._last_recorded_bar_hour = self.hourly_price_history[-1][0]
        return added

    def step(
        self,
        timestamp: Any,
        prices: Dict[str, float],
        warmup_history: Optional[pd.DataFrame] = None,
        is_forward: bool = True,
        observation_id: Optional[str] = None,
        force_rebalance: bool = False,
    ) -> ObserverTickResult:
        """Execute one clock step with given timestamp and market prices.

        Args:
            timestamp: Clock timestamp (ISO string, datetime, or epoch).
            prices: Dictionary of current spot closing prices for universe symbols.
            warmup_history: Optional historical price DataFrame used for momentum calculation.
            is_forward: True if authentic forward data, False if historical warmup.
            observation_id: Optional observation tracking ID.
            force_rebalance: If True, forces rebalancing check immediately.
        """
        ts_utc = self._parse_timestamp(timestamp)
        ts_str = ts_utc.isoformat().replace("+00:00", "Z")

        # 1. Causal Timestamp Ordering & Duplicate Idempotency Check
        if self.last_accepted_timestamp_utc is not None:
            if ts_utc < self.last_accepted_timestamp_utc:
                self.rejected_observations_count += 1
                logger.warning("Rejected out-of-order timestamp: %s < %s", ts_str, self.last_accepted_timestamp_utc)
                return ObserverTickResult(
                    timestamp=ts_str,
                    prices=prices,
                    carm_state=self.carm_portfolio.to_dict(),
                    btc_bh_state=self.btc_portfolio.to_dict(),
                    cash_state=self.cash_portfolio.to_dict(),
                    rebalance_triggered=False,
                    data_quality_status="REJECTED_OUT_OF_ORDER",
                    rejection_reason=f"Timestamp {ts_str} is earlier than last accepted {self.last_accepted_timestamp_utc.isoformat()}",
                )
            if ts_utc == self.last_accepted_timestamp_utc:
                self.rejected_observations_count += 1
                logger.info("Rejected duplicate timestamp: %s", ts_str)
                return ObserverTickResult(
                    timestamp=ts_str,
                    prices=prices,
                    carm_state=self.carm_portfolio.to_dict(),
                    btc_bh_state=self.btc_portfolio.to_dict(),
                    cash_state=self.cash_portfolio.to_dict(),
                    rebalance_triggered=False,
                    data_quality_status="REJECTED_DUPLICATE",
                    rejection_reason=f"Timestamp {ts_str} already accepted",
                )

        # 2. Price Validation & Data Quality Filter
        clean_prices: Dict[str, float] = {}
        for sym, p in prices.items():
            try:
                p_val = float(p)
                if p_val > 0.0 and not (p_val != p_val or p_val == float("inf") or p_val == float("-inf")):
                    clean_prices[sym] = p_val
            except (ValueError, TypeError):
                continue

        # Data-Quality Integrity: Check if any currently held asset has missing or non-positive price
        held_assets = [sym for sym, qty in self.carm_portfolio.holdings.items() if qty > 1e-8]
        missing_held = [sym for sym in held_assets if sym not in clean_prices]
        if self._btc_incepted and BENCHMARK_BTC_SYMBOL not in clean_prices:
            missing_held.append(BENCHMARK_BTC_SYMBOL)

        if missing_held:
            self.rejected_observations_count += 1
            logger.error("Data quality failure: missing prices for held assets: %s", missing_held)
            return ObserverTickResult(
                timestamp=ts_str,
                prices=clean_prices,
                carm_state=self.carm_portfolio.to_dict(),
                btc_bh_state=self.btc_portfolio.to_dict(),
                cash_state=self.cash_portfolio.to_dict(),
                rebalance_triggered=False,
                data_quality_status="DATA_QUALITY_FAILURE_MISSING_PRICE",
                rejection_reason=f"Missing or non-positive price for held assets: {missing_held}. Preserving last valid equity.",
            )

        # Accept observation
        self.last_accepted_timestamp_utc = ts_utc
        self.last_accepted_observation_id = observation_id or f"obs-{ts_utc.strftime('%Y%m%d%H%M%S')}"
        if is_forward:
            self.authentic_forward_observations_count += 1
        else:
            self.historical_warmup_observations_count += 1

        # 3. Inception Handling: BTC Buy & Hold (Executes once at inception)
        if not self._btc_incepted and BENCHMARK_BTC_SYMBOL in clean_prices:
            btc_price = clean_prices[BENCHMARK_BTC_SYMBOL]
            fee = self.initial_capital_usd * self.fee_rate
            investable = self.initial_capital_usd - fee
            units = investable / btc_price
            self.btc_portfolio.holdings[BENCHMARK_BTC_SYMBOL] = units
            self.btc_portfolio.cash_usd = 0.0
            self.btc_portfolio.equity_usd = investable
            self.btc_portfolio.cumulative_fees_usd += fee
            self.btc_portfolio.cumulative_turnover += 1.0
            self.btc_portfolio.rebalance_count += 1
            if self.btc_portfolio.peak_equity_usd > 0.0:
                btc_dd = (investable - self.btc_portfolio.peak_equity_usd) / self.btc_portfolio.peak_equity_usd * 100.0
                if btc_dd < self.btc_portfolio.max_drawdown_pct:
                    self.btc_portfolio.max_drawdown_pct = float(btc_dd)
            self._btc_incepted = True
            self.modeled_virtual_fills_count += 1
            self.virtual_fills.append({
                "fill_id": f"fill-btc-{len(self.virtual_fills) + 1}",
                "portfolio": "BTC_BUY_AND_HOLD",
                "timestamp_utc": ts_str,
                "symbol": BENCHMARK_BTC_SYMBOL,
                "side": "BUY",
                "units": round(units, 8),
                "price": round(btc_price, 4),
                "notional_usd": round(investable, 2),
                "fee_usd": round(fee, 4),
                "trigger_type": "INCEPTION",
                "is_modeled_virtual_fill": True,
            })

        # 4. Inception Handling: CARM Initial Allocation (Matching 0d9f6660 current_target_w = 1.0 / N)
        rebalance_triggered = False
        rebalance_details: Optional[Dict[str, Any]] = None
        period_idx = self.get_period_index(ts_utc)

        # Check if CARM initial inception allocation is due
        if not self._carm_incepted:
            if self.initial_allocation_mode == "EQUAL_WEIGHT":
                # Incept into 1/N equal weight across all universe symbols present
                available_syms = [s for s in self.universe if s in clean_prices and clean_prices[s] > 0.0]
                if available_syms:
                    rebalance_details = self._execute_target_allocation(
                        current_prices=clean_prices,
                        target_w={s: 1.0 / len(available_syms) for s in available_syms},
                        timestamp_utc=ts_str,
                        reason="INCEPTION_EQUAL_WEIGHT",
                        rebalance_type="INCEPTION",
                    )
                    rebalance_triggered = True
                    self._carm_incepted = True
                    self.inception_rebalances_count += 1
                    self.last_completed_period_index = period_idx
                    self.last_rebalance_timestamp_utc = ts_str
            else:
                self._carm_incepted = True

        # 5. Check Weekly UTC Rebalance Decision Clock
        rebalance_due = (
            force_rebalance
            or (self.last_completed_period_index is None)
            or (period_idx > self.last_completed_period_index)
        )

        if rebalance_due and self._carm_incepted:
            momentum_scores = self._compute_causal_momentum(warmup_history, decision_time_utc=ts_utc)
            if momentum_scores is not None:
                rebal_type = "FORCED_PROBE" if force_rebalance else "SCHEDULED_WEEKLY"
                rebalance_details = self._rebalance_carm(
                    clean_prices,
                    momentum_scores,
                    ts_str,
                    rebalance_type=rebal_type,
                )
                rebalance_triggered = True
                if force_rebalance:
                    self.forced_probes_count += 1
                else:
                    self.scheduled_rebalances_count += 1
                    self.last_completed_period_index = period_idx
                self.last_rebalance_timestamp_utc = ts_str
            else:
                logger.warning(
                    "Rebalance due at %s but momentum signal was rejected or unavailable. "
                    "Postponing virtual rebalance while maintaining mark-to-market valuation.",
                    ts_str,
                )

        # 6. Mark-to-Market Valuations for all 3 portfolios
        self.carm_portfolio.update_valuation(clean_prices)
        self.btc_portfolio.update_valuation(clean_prices)
        self.cash_portfolio.update_valuation(clean_prices)
        self.portfolio_valuations_count += 1

        return ObserverTickResult(
            timestamp=ts_str,
            prices=clean_prices,
            carm_state=self.carm_portfolio.to_dict(),
            btc_bh_state=self.btc_portfolio.to_dict(),
            cash_state=self.cash_portfolio.to_dict(),
            rebalance_triggered=rebalance_triggered,
            data_quality_status="VALID",
            rebalance_details=rebalance_details,
        )

    def _compute_causal_momentum(
        self,
        warmup_history: Optional[pd.DataFrame] = None,
        decision_time_utc: Optional[datetime] = None,
    ) -> Optional[Dict[str, float]]:
        """Compute causal 168h percentage return with shift(2) delay.

        Guarantees:
          - EXACT LOOKBACK: dt_eval - dt_base must equal exactly rebalance_interval_hours.
          - SEQUENTIAL CONTINUITY: Every single hour in the window must be present without missing bars.
          - SIGNAL FRESHNESS: dt_eval must be within allowed latency of decision_time_utc.
          - FAIL CLOSED: Returns None on any continuity or freshness violation.
        """
        from datetime import timedelta
        required_len = self.rebalance_interval_hours + self.causal_delay_bars + 1

        # Source 1: Warmup history DataFrame if provided
        if warmup_history is not None and len(warmup_history) >= required_len:
            t_eval = len(warmup_history) - 1 - self.causal_delay_bars
            t_base = t_eval - self.rebalance_interval_hours
            if t_base >= 0:
                p_eval = warmup_history.iloc[t_eval]
                p_base = warmup_history.iloc[t_base]
                mom: Dict[str, float] = {}
                for sym in self.universe:
                    if sym in p_eval and sym in p_base and float(p_base[sym]) > 0.0:
                        mom[sym] = float((p_eval[sym] / p_base[sym]) - 1.0)
                    else:
                        mom[sym] = float("-inf")
                return mom

        # Source 2: Dedicated hourly history buffer
        if len(self.hourly_price_history) >= required_len:
            t_eval_idx = len(self.hourly_price_history) - 1 - self.causal_delay_bars
            t_base_idx = t_eval_idx - self.rebalance_interval_hours
            if t_base_idx >= 0:
                dt_eval, p_eval_dict = self.hourly_price_history[t_eval_idx]
                dt_base, p_base_dict = self.hourly_price_history[t_base_idx]

                # 1. Exact 168-hour lookback verification
                expected_lookback = timedelta(hours=self.rebalance_interval_hours)
                actual_lookback = dt_eval - dt_base
                if actual_lookback != expected_lookback:
                    logger.error(
                        "Signal rejected: Lookback window between base (%s) and eval (%s) is %s != %s",
                        dt_base.isoformat(),
                        dt_eval.isoformat(),
                        actual_lookback,
                        expected_lookback,
                    )
                    return None

                # 2. Sequential continuity verification (no missing hours between base and eval)
                for k in range(t_base_idx + 1, t_eval_idx + 1):
                    if self.hourly_price_history[k][0] - self.hourly_price_history[k - 1][0] != timedelta(hours=1):
                        logger.error(
                            "Signal rejected: Missing hourly bar between %s and %s",
                            self.hourly_price_history[k - 1][0].isoformat(),
                            self.hourly_price_history[k][0].isoformat(),
                        )
                        return None

                # 3. Freshness verification relative to decision time
                if decision_time_utc is not None:
                    freshness_diff = abs(decision_time_utc - dt_eval)
                    max_allowed_stale = timedelta(hours=self.causal_delay_bars + 3)
                    if freshness_diff > max_allowed_stale:
                        logger.error(
                            "Signal rejected: Stale signal. Eval bar (%s) is %s behind decision time (%s)",
                            dt_eval.isoformat(),
                            freshness_diff,
                            decision_time_utc.isoformat(),
                        )
                        return None

                mom = {}
                for sym in self.universe:
                    if sym in p_eval_dict and sym in p_base_dict and p_base_dict[sym] > 0.0:
                        mom[sym] = float((p_eval_dict[sym] / p_base_dict[sym]) - 1.0)
                    else:
                        mom[sym] = float("-inf")
                return mom

        return None

    def _rebalance_carm(
        self,
        current_prices: Dict[str, float],
        momentum_scores: Dict[str, float],
        timestamp_utc: str,
        rebalance_type: str = "SCHEDULED_WEEKLY",
    ) -> Dict[str, Any]:
        """Rank universe assets and execute scheduled weekly or forced probe virtual rebalancing."""
        valid_candidates = [
            sym for sym in self.universe
            if sym in momentum_scores and momentum_scores[sym] > float("-inf")
        ]
        # Rank by momentum descending
        ranked_assets = sorted(valid_candidates, key=lambda s: momentum_scores[s], reverse=True)
        top_k_candidates = ranked_assets[: self.top_k]

        target_w = {sym: 0.0 for sym in self.universe}
        selected_assets: List[str] = []

        if self.require_positive_momentum:
            # Variant V2 (Cash Gated): only positive momentum allocated, rest cash
            slot_w = 1.0 / self.top_k
            for sym in top_k_candidates:
                if momentum_scores[sym] > 0.0:
                    selected_assets.append(sym)
                    target_w[sym] = slot_w
        else:
            # Canonical 0d9f6660 Parity: nlargest(top_k) equal-weighted
            selected_assets = top_k_candidates
            if selected_assets:
                slot_w = 1.0 / len(selected_assets)
                for sym in selected_assets:
                    target_w[sym] = slot_w

        reason = "FORCED_PROBE_MOMENTUM_REBALANCE" if rebalance_type == "FORCED_PROBE" else "SCHEDULED_WEEKLY_MOMENTUM_REBALANCE"
        return self._execute_target_allocation(
            current_prices=current_prices,
            target_w=target_w,
            timestamp_utc=timestamp_utc,
            reason=reason,
            rebalance_type=rebalance_type,
            momentum_scores={s: momentum_scores[s] for s in top_k_candidates},
            selected_assets=selected_assets,
        )

    def _execute_target_allocation(
        self,
        current_prices: Dict[str, float],
        target_w: Dict[str, float],
        timestamp_utc: str,
        reason: str,
        rebalance_type: str = "SCHEDULED_WEEKLY",
        momentum_scores: Optional[Dict[str, float]] = None,
        selected_assets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Execute virtual portfolio rebalancing to target weights."""
        current_asset_vals = {
            sym: self.carm_portfolio.holdings.get(sym, 0.0) * current_prices.get(sym, 0.0)
            for sym in self.universe
        }
        equity_before = self.carm_portfolio.cash_usd + sum(current_asset_vals.values())
        if equity_before <= 1e-6:
            equity_before = self.initial_capital_usd

        current_w = {
            sym: current_asset_vals.get(sym, 0.0) / equity_before
            for sym in self.universe
        }

        # Turnover dw across asset weights: sum(|target_w - current_w|)
        dw = sum(abs(target_w.get(sym, 0.0) - current_w.get(sym, 0.0)) for sym in self.universe)

        # Proportional fee deduction on traded asset notional
        fee = equity_before * dw * self.fee_rate
        post_fee_equity = max(equity_before - fee, 0.0)

        new_holdings = {sym: 0.0 for sym in self.universe}
        allocated_val = 0.0
        fill_records: List[Dict[str, Any]] = []

        for sym in self.universe:
            curr_units = self.carm_portfolio.holdings.get(sym, 0.0)
            w_tgt = target_w.get(sym, 0.0)
            sym_price = current_prices.get(sym, 0.0)
            target_units = 0.0

            if w_tgt > 0.0 and sym_price > 0.0:
                asset_alloc = post_fee_equity * w_tgt
                target_units = asset_alloc / sym_price
                new_holdings[sym] = target_units
                allocated_val += asset_alloc

            delta_units = target_units - curr_units
            if abs(delta_units) > 1e-8 and sym_price > 0.0:
                self.modeled_virtual_fills_count += 1
                fill_records.append({
                    "fill_id": f"fill-carm-{len(self.virtual_fills) + 1}",
                    "portfolio": "CARM_WEEKLY_ONLY",
                    "timestamp_utc": timestamp_utc,
                    "symbol": sym,
                    "side": "BUY" if delta_units > 0 else "SELL",
                    "units": round(abs(delta_units), 8),
                    "price": round(sym_price, 4),
                    "notional_usd": round(abs(delta_units) * sym_price, 2),
                    "fee_usd": round(abs(delta_units) * sym_price * self.fee_rate, 4),
                    "trigger_type": rebalance_type,
                    "is_modeled_virtual_fill": True,
                })

        new_cash = max(post_fee_equity - allocated_val, 0.0)

        # Update portfolio state
        self.carm_portfolio.holdings = new_holdings
        self.carm_portfolio.cash_usd = new_cash
        self.carm_portfolio.equity_usd = post_fee_equity
        self.carm_portfolio.cumulative_fees_usd += fee
        self.carm_portfolio.cumulative_turnover += dw
        self.carm_portfolio.rebalance_count += 1
        if post_fee_equity > self.carm_portfolio.peak_equity_usd:
            self.carm_portfolio.peak_equity_usd = post_fee_equity
        if self.carm_portfolio.peak_equity_usd > 0.0:
            carm_dd = (post_fee_equity - self.carm_portfolio.peak_equity_usd) / self.carm_portfolio.peak_equity_usd * 100.0
            if carm_dd < self.carm_portfolio.max_drawdown_pct:
                self.carm_portfolio.max_drawdown_pct = float(carm_dd)

        self.virtual_fills.extend(fill_records)

        target_cash_w = 1.0 - sum(target_w.values())

        return {
            "reason": reason,
            "rebalance_type": rebalance_type,
            "selected_assets": selected_assets or [s for s, w in target_w.items() if w > 0],
            "target_cash_weight": round(max(target_cash_w, 0.0), 6),
            "momentum_scores": momentum_scores or {},
            "turnover": round(dw, 6),
            "fee_usd": round(fee, 4),
            "equity_before": round(equity_before, 2),
            "post_fee_equity": round(post_fee_equity, 2),
            "target_weights": {s: round(target_w[s], 6) for s in self.universe if target_w.get(s, 0) > 0},
            "virtual_fills_generated": len(fill_records),
        }

    def save_state(self, filepath: Union[str, Path]) -> Dict[str, Any]:
        """Persist complete observer state atomically including hourly price buffer."""
        import os
        import uuid
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        state_data = {
            "epoch_id": self.epoch_id,
            "strategy_version": self.strategy_version,
            "configuration_fingerprint": self.configuration_fingerprint,
            "universe": self.universe,
            "initial_capital_usd": self.initial_capital_usd,
            "fee_bps": self.fee_bps,
            "rebalance_interval_hours": self.rebalance_interval_hours,
            "top_k": self.top_k,
            "require_positive_momentum": self.require_positive_momentum,
            "initial_allocation_mode": self.initial_allocation_mode,
            "causal_delay_bars": self.causal_delay_bars,
            "anchor_epoch_seconds": self.anchor_epoch_seconds,
            "carm_portfolio": self.carm_portfolio.to_dict(),
            "btc_portfolio": self.btc_portfolio.to_dict(),
            "cash_portfolio": self.cash_portfolio.to_dict(),
            "btc_incepted": self._btc_incepted,
            "carm_incepted": self._carm_incepted,
            "clock": {
                "last_accepted_timestamp_utc": self.last_accepted_timestamp_utc.isoformat() if self.last_accepted_timestamp_utc else None,
                "last_accepted_observation_id": self.last_accepted_observation_id,
                "last_completed_period_index": self.last_completed_period_index,
                "last_rebalance_timestamp_utc": self.last_rebalance_timestamp_utc,
            },
            "counters": {
                "authentic_forward_observations_count": self.authentic_forward_observations_count,
                "historical_warmup_observations_count": self.historical_warmup_observations_count,
                "rejected_observations_count": self.rejected_observations_count,
                "inception_rebalances_count": self.inception_rebalances_count,
                "scheduled_rebalances_count": self.scheduled_rebalances_count,
                "forced_probes_count": self.forced_probes_count,
                "modeled_virtual_fills_count": self.modeled_virtual_fills_count,
                "portfolio_valuations_count": self.portfolio_valuations_count,
            },
            # Persist latest 250 hourly bars to guarantee continuous causal momentum availability across restarts
            "hourly_price_history": [
                {"timestamp_utc": dt.isoformat(), "prices": p}
                for dt, p in self.hourly_price_history[-250:]
            ],
            "virtual_fills": self.virtual_fills[-50:],
        }

        # Atomic replacement to avoid file corruption on crash
        tmp_path = path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)

        return state_data

    @classmethod
    def load_state(cls, filepath: Union[str, Path]) -> CarmShadowObserver:
        """Recover observer state idempotently from JSON file."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"State file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        observer = cls(
            universe=data.get("universe", CANONICAL_UNIVERSE),
            initial_capital_usd=data.get("initial_capital_usd", DEFAULT_INITIAL_CAPITAL_USD),
            fee_bps=data.get("fee_bps", DEFAULT_FEE_BPS),
            rebalance_interval_hours=data.get("rebalance_interval_hours", DEFAULT_REBALANCE_HOURS),
            top_k=data.get("top_k", DEFAULT_TOP_K),
            causal_delay_bars=data.get("causal_delay_bars", DEFAULT_CAUSAL_DELAY_BARS),
            require_positive_momentum=data.get("require_positive_momentum", False),
            initial_allocation_mode=data.get("initial_allocation_mode", "EQUAL_WEIGHT"),
            anchor_epoch_seconds=data.get("anchor_epoch_seconds", CANONICAL_WEEKLY_ANCHOR_EPOCH_SECONDS),
            epoch_id=data.get("epoch_id", "EPOCH_20261116_01"),
        )

        observer.carm_portfolio = VirtualPortfolioState.from_dict(data["carm_portfolio"])
        observer.btc_portfolio = VirtualPortfolioState.from_dict(data["btc_portfolio"])
        observer.cash_portfolio = VirtualPortfolioState.from_dict(data["cash_portfolio"])
        observer._btc_incepted = bool(data.get("btc_incepted", False))
        observer._carm_incepted = bool(data.get("carm_incepted", False))

        clock = data.get("clock", {})
        if clock.get("last_accepted_timestamp_utc"):
            observer.last_accepted_timestamp_utc = observer._parse_timestamp(clock["last_accepted_timestamp_utc"])
        observer.last_accepted_observation_id = clock.get("last_accepted_observation_id")
        observer.last_completed_period_index = clock.get("last_completed_period_index")
        observer.last_rebalance_timestamp_utc = clock.get("last_rebalance_timestamp_utc")

        counters = data.get("counters", {})
        observer.authentic_forward_observations_count = int(counters.get("authentic_forward_observations_count", 0))
        observer.historical_warmup_observations_count = int(counters.get("historical_warmup_observations_count", 0))
        observer.rejected_observations_count = int(counters.get("rejected_observations_count", 0))
        observer.inception_rebalances_count = int(counters.get("inception_rebalances_count", 0))
        observer.scheduled_rebalances_count = int(counters.get("scheduled_rebalances_count", 0))
        observer.forced_probes_count = int(counters.get("forced_probes_count", 0))
        observer.modeled_virtual_fills_count = int(counters.get("modeled_virtual_fills_count", 0))
        observer.portfolio_valuations_count = int(counters.get("portfolio_valuations_count", 0))

        # Restore hourly price history
        for item in data.get("hourly_price_history", []):
            dt = observer._parse_timestamp(item["timestamp_utc"])
            observer.hourly_price_history.append((dt, {k: float(v) for k, v in item["prices"].items()}))
        if observer.hourly_price_history:
            observer._last_recorded_bar_hour = observer.hourly_price_history[-1][0]

        observer.virtual_fills = data.get("virtual_fills", [])

        return observer

    def run_simulation(
        self,
        piv_close: pd.DataFrame,
    ) -> List[ObserverTickResult]:
        """Run batch simulation over a panel of hourly close prices."""
        results: List[ObserverTickResult] = []
        n_bars = len(piv_close)

        for i in range(n_bars):
            ts = piv_close.index[i]
            prices = piv_close.iloc[i].to_dict()
            sub_history = piv_close.iloc[: i + 1]
            res = self.step(
                timestamp=ts,
                prices=prices,
                warmup_history=sub_history,
                is_forward=False,
            )
            results.append(res)

        return results
