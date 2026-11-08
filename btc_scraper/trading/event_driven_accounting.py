"""Event-Driven Self-Financing Capital & Equity Accounting Engine.

Provides mathematically rigorous, path-dependent portfolio accounting:
- Capital locking at entry, release at exit.
- PnL booked strictly at exit timestamp (no lookahead, no premature booking).
- Capacity, concurrency, side-lock, and asset cooldown (P4) enforced at every timestamp.
- Explicit transaction fees and slippage directions on both entry and exit legs.
- Dual equity tracking: Realized Event Equity vs. Bar-by-Bar Mark-to-Market (MTM) Equity.
- Intratrade Excursions and MTM Drawdown alongside Realized Drawdown.
- Conservative same-bar conflict resolution (SL triggers first).
- Daily sampled returns for Sharpe & Sortino ratios (365 days for 24/7 crypto).
- Capital turnover, exposure percentage, and capital utilization tracking.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Mapping, Sequence
import numpy as np
import pandas as pd

from btc_scraper.trading.execution_policy import CANONICAL_POLICY, CanonicalExecutionPolicy


@dataclass(frozen=True)
class EconomicReplayTrade:
    """Canonical economic replay trade contract for portfolio simulation.

    Ensures mathematical consistency between prices, gross returns, and accounting events.
    """
    trade_id: str
    symbol: str
    side: str
    entry_timestamp: pd.Timestamp
    exit_timestamp: pd.Timestamp
    entry_price: float
    exit_price: float
    gross_return_fraction: float  # Gross return before fees: +0.0050 = +50 bps
    exit_reason: str = "UNKNOWN"  # TP, SL, TIMEOUT, etc.
    bars_held: int = 0
    source_contract_version: str = "causal-e4-v1"
    mark_price_path: Sequence[float] | None = None
    gross_pnl_bps: float | None = None
    net_pnl_bps: float | None = None


def validate_economic_replay_trade(t: Mapping[str, Any], idx: int = 0) -> EconomicReplayTrade:
    """Validates and normalizes candidate trade into canonical EconomicReplayTrade.

    Canonical contract semantics:
    - ``gross_return_fraction`` is the canonical economic input.
    - ``gross_pnl_bps`` is an equivalent representation and is consistency-checked when supplied.
    - ``net_pnl_bps`` is an optional informational/transport field (``None`` when omitted).
      It is not derived implicitly and is never used as accounting truth by
      ``EventDrivenAccountingEngine`` (which computes realized net return strictly from
      ``gross_return_fraction`` and explicit ``AccountingConfig``).
    - Cross-checking ``net_pnl_bps`` is performed only when the record explicitly provides
      full cost-contract metadata (``cost_contract_version``, ``fee_rate_bps``,
      ``slippage_bps``, and ``roundtrip_cost_semantics``).

    Raises ValueError on missing gross return, price/return mismatch, or non-finite values.
    Silent zero PnL default is strictly prohibited.
    """
    trade_id = str(t.get("trade_id", f"trade_{idx}"))
    raw_symbol = str(t.get("symbol", "UNKNOWN")).strip().upper()
    symbol = raw_symbol.replace("/", "").replace("-", "").removesuffix("USDT")
    side = str(t.get("side", "BUY")).strip().upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError(f"Trade {trade_id} has invalid side: {side}")

    entry_ts = _normalize_timestamp(t["entry_timestamp"])
    exit_ts = _normalize_timestamp(t["exit_timestamp"])
    if exit_ts < entry_ts:
        raise ValueError(f"Trade {trade_id} exit_timestamp ({exit_ts}) < entry_timestamp ({entry_ts})")

    # 1. Gross Return Extraction - Silent Zero Strictly Prohibited
    gross_ret: float | None = None
    if "gross_return_fraction" in t and t["gross_return_fraction"] is not None:
        gross_ret = float(t["gross_return_fraction"])
    elif "gross_pnl_bps" in t and t["gross_pnl_bps"] is not None:
        gross_ret = float(t["gross_pnl_bps"]) / 10000.0
    elif "raw_pnl" in t and t["raw_pnl"] is not None:
        gross_ret = float(t["raw_pnl"])
    elif "realized_pnl" in t and t["realized_pnl"] is not None:
        gross_ret = float(t["realized_pnl"])
    elif "pnl" in t and t["pnl"] is not None:
        gross_ret = float(t["pnl"])

    if gross_ret is None or not math.isfinite(gross_ret):
        raise ValueError(
            f"Trade {trade_id} missing gross return (gross_return_fraction, gross_pnl_bps, or raw_pnl required, silent zero prohibited)"
        )

    # 2. Consistency between gross_pnl_bps and gross_return_fraction
    gross_pnl_bps_val: float | None = None
    if "gross_pnl_bps" in t and t["gross_pnl_bps"] is not None:
        gross_pnl_bps_val = float(t["gross_pnl_bps"])
        if abs(gross_pnl_bps_val / 10000.0 - gross_ret) > 1e-5:
            raise ValueError(
                f"Trade {trade_id} inconsistency: gross_pnl_bps={gross_pnl_bps_val} != gross_return_fraction={gross_ret}"
            )
    else:
        gross_pnl_bps_val = gross_ret * 10000.0

    # 3. Price and Return Consistency
    has_entry = "entry_price" in t and t["entry_price"] is not None and float(t["entry_price"]) > 0
    has_exit = "exit_price" in t and t["exit_price"] is not None and float(t["exit_price"]) > 0

    if has_entry and has_exit:
        entry_p = float(t["entry_price"])
        exit_p = float(t["exit_price"])
        calc_ret = (exit_p - entry_p) / entry_p if side == "BUY" else (entry_p - exit_p) / entry_p
        if abs(calc_ret - gross_ret) > 1e-4:
            raise ValueError(
                f"Trade {trade_id} price-return inconsistency for {side}: "
                f"calc_from_prices={calc_ret:.6f}, reported_return={gross_ret:.6f}"
            )
    elif has_entry:
        entry_p = float(t["entry_price"])
        exit_p = entry_p * (1.0 + gross_ret) if side == "BUY" else entry_p * (1.0 - gross_ret)
    elif has_exit:
        exit_p = float(t["exit_price"])
        entry_p = exit_p / (1.0 + gross_ret) if side == "BUY" else exit_p / (1.0 - gross_ret)
    else:
        entry_p = 100.0
        exit_p = entry_p * (1.0 + gross_ret) if side == "BUY" else entry_p * (1.0 - gross_ret)

    exit_reason = str(t.get("exit_reason") or "UNKNOWN")
    bars_held = int(t.get("bars_held", 0))
    source_ver = str(t.get("source_contract_version", "causal-e4-v1"))
    net_pnl_bps_val = float(t["net_pnl_bps"]) if "net_pnl_bps" in t and t["net_pnl_bps"] is not None else None
    if net_pnl_bps_val is not None:
        if not math.isfinite(net_pnl_bps_val):
            raise ValueError(f"Trade {trade_id} has non-finite net_pnl_bps: {net_pnl_bps_val}")
        has_explicit_cost_contract = all(
            k in t and t[k] is not None
            for k in ("cost_contract_version", "fee_rate_bps", "slippage_bps", "roundtrip_cost_semantics")
        )
        if has_explicit_cost_contract:
            fee_bps = float(t["fee_rate_bps"])
            slip_bps = float(t["slippage_bps"])
            semantics = str(t["roundtrip_cost_semantics"]).strip().lower()
            leg_bps = fee_bps + slip_bps
            if semantics == "additive_bps":
                expected_net_bps = gross_pnl_bps_val - 2.0 * leg_bps
            elif semantics == "compounded_notional":
                leg_frac = leg_bps / 10000.0
                expected_net_bps = (gross_ret - leg_frac - max(0.0, 1.0 + gross_ret) * leg_frac) * 10000.0
            else:
                raise ValueError(
                    f"Trade {trade_id} has unsupported roundtrip_cost_semantics: {semantics}"
                )
            if abs(net_pnl_bps_val - expected_net_bps) > 1e-2:
                raise ValueError(
                    f"Trade {trade_id} explicit cost-contract net_pnl_bps mismatch: "
                    f"supplied={net_pnl_bps_val:.4f}, expected={expected_net_bps:.4f}"
                )

    return EconomicReplayTrade(
        trade_id=trade_id,
        symbol=symbol,
        side=side,
        entry_timestamp=entry_ts,
        exit_timestamp=exit_ts,
        entry_price=entry_p,
        exit_price=exit_p,
        gross_return_fraction=gross_ret,
        exit_reason=exit_reason,
        bars_held=bars_held,
        source_contract_version=source_ver,
        mark_price_path=t.get("mark_price_path"),
        gross_pnl_bps=gross_pnl_bps_val,
        net_pnl_bps=net_pnl_bps_val,
    )


@dataclass(frozen=True)
class AccountingConfig:
    """Configuration for event-driven capital accounting."""
    initial_capital: float = 10000.0
    max_concurrent_positions: int = 3
    max_positions_per_asset: int = 1
    cooldown_bars: int = 96               # 96 bars cooldown (canonical P4)
    bar_interval_minutes: int = 15        # 15m candle interval (96 bars = 24h)
    allocation_pct_per_trade: float = 0.25  # 25% allocation per trade (max 75% for 3 trades)
    fixed_allocation_usd: float | None = None
    fee_rate_bps: float = 5.0             # 0.05% per leg (maker/taker contract)
    slippage_bps: float = 2.0             # 0.02% per leg
    annualization_factor: int = 365       # 365 for 24/7 crypto markets


@dataclass
class Position:
    """Active open position tracking locked capital and trade parameters."""
    trade_id: str
    symbol: str
    side: str
    entry_timestamp: pd.Timestamp
    exit_timestamp: pd.Timestamp
    entry_price: float
    exit_price: float
    raw_pnl_fraction: float  # (exit - entry)/entry for LONG, (entry - exit)/entry for SHORT
    locked_capital: float
    entry_cost: float
    entry_fill_price: float = 0.0
    exit_fill_price: float = 0.0
    exit_reason: str = "UNKNOWN"


@dataclass
class ExecutedTradeRecord:
    """Historical executed trade record with full accounting breakdown."""
    trade_id: str
    symbol: str
    side: str
    entry_timestamp: pd.Timestamp
    exit_timestamp: pd.Timestamp
    entry_price: float
    exit_price: float
    entry_fill_price: float
    exit_fill_price: float
    locked_capital: float
    entry_cost: float
    exit_cost: float
    total_cost: float
    gross_pnl_usd: float
    net_pnl_usd: float
    net_pnl_pct: float
    net_return_bps: float
    equity_after_exit: float
    bars_held: int = 0
    exit_reason: str = "UNKNOWN"
    gross_return_fraction: float = 0.0


@dataclass
class SimulationResult:
    """Summary of event-driven portfolio accounting simulation."""
    initial_capital: float
    final_equity: float
    total_net_pnl_usd: float
    total_net_pnl_pct: float
    executed_trades_count: int
    rejected_capacity_count: int
    win_count: int
    loss_count: int
    win_rate_pct: float
    gross_profit_usd: float
    gross_loss_usd: float
    profit_factor: float
    expectancy_usd: float
    expectancy_bps: float
    realized_drawdown_pct: float
    realized_drawdown_usd: float
    mtm_drawdown_pct: float
    mtm_drawdown_usd: float
    max_drawdown_pct: float  # Aliased to mtm_drawdown_pct for backward compatibility
    max_drawdown_usd: float  # Aliased to mtm_drawdown_usd for backward compatibility
    capital_turnover: float
    exposure_pct: float
    capital_utilization_pct: float
    daily_sharpe: float
    daily_sortino: float
    daily_returns: pd.Series
    equity_curve: pd.DataFrame
    mtm_equity_curve: pd.DataFrame
    executed_trades: list[ExecutedTradeRecord]
    excluded_cross_boundary_count: int = 0
    cross_boundary_policy: str = "EXCLUDE_CROSS_BOUNDARY_OUTCOME"

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_capital": round(self.initial_capital, 2),
            "final_equity": round(self.final_equity, 2),
            "total_net_pnl_usd": round(self.total_net_pnl_usd, 2),
            "total_net_pnl_pct": round(self.total_net_pnl_pct, 4),
            "executed_trades_count": self.executed_trades_count,
            "rejected_capacity_count": self.rejected_capacity_count,
            "excluded_cross_boundary_count": self.excluded_cross_boundary_count,
            "cross_boundary_policy": self.cross_boundary_policy,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate_pct": round(self.win_rate_pct, 2),
            "gross_profit_usd": round(self.gross_profit_usd, 2),
            "gross_loss_usd": round(self.gross_loss_usd, 2),
            "profit_factor": round(self.profit_factor, 4),
            "expectancy_usd": round(self.expectancy_usd, 4),
            "expectancy_bps": round(self.expectancy_bps, 2),
            "realized_drawdown_pct": round(self.realized_drawdown_pct, 4),
            "realized_drawdown_usd": round(self.realized_drawdown_usd, 2),
            "mtm_drawdown_pct": round(self.mtm_drawdown_pct, 4),
            "mtm_drawdown_usd": round(self.mtm_drawdown_usd, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "max_drawdown_usd": round(self.max_drawdown_usd, 2),
            "capital_turnover": round(self.capital_turnover, 4),
            "exposure_pct": round(self.exposure_pct, 4),
            "capital_utilization_pct": round(self.capital_utilization_pct, 4),
            "daily_sharpe": round(self.daily_sharpe, 4),
            "daily_sortino": round(self.daily_sortino, 4),
        }


def _normalize_timestamp(ts: Any) -> pd.Timestamp:
    if isinstance(ts, pd.Timestamp):
        return ts.tz_convert("UTC") if ts.tzinfo is not None else ts.tz_localize("UTC")
    ts_dt = pd.to_datetime(ts)
    return ts_dt.tz_convert("UTC") if ts_dt.tzinfo is not None else ts_dt.tz_localize("UTC")


class EventDrivenAccountingEngine:
    """Event-driven, self-financing capital accounting simulator.
    
    Processes candidate trades sequentially through time. Maintains cash, locked capital,
    active positions, enforces concurrency, cooldown, and side-locks, and evaluates
    both Realized Event Equity and Mark-to-Market (MTM) Equity.
    """

    def __init__(
        self,
        config: AccountingConfig | None = None,
        policy: CanonicalExecutionPolicy | None = None,
    ) -> None:
        if config is not None:
            self.config = config
            self.policy = policy or CanonicalExecutionPolicy(
                max_concurrent_positions=config.max_concurrent_positions,
                max_positions_per_asset=config.max_positions_per_asset,
                cooldown_bars=config.cooldown_bars,
                bar_interval_minutes=config.bar_interval_minutes,
                allocation_pct_per_trade=config.allocation_pct_per_trade,
                fee_rate_bps=config.fee_rate_bps,
                slippage_bps=config.slippage_bps,
            )
        else:
            self.policy = policy or CANONICAL_POLICY
            self.config = AccountingConfig(
                initial_capital=10000.0,
                max_concurrent_positions=self.policy.max_concurrent_positions,
                max_positions_per_asset=self.policy.max_positions_per_asset,
                cooldown_bars=self.policy.cooldown_bars,
                bar_interval_minutes=self.policy.bar_interval_minutes,
                allocation_pct_per_trade=self.policy.allocation_pct_per_trade,
                fee_rate_bps=self.policy.fee_rate_bps,
                slippage_bps=self.policy.slippage_bps,
            )

    def run(
        self,
        candidate_trades: Sequence[dict[str, Any] | EconomicReplayTrade],
        *,
        date_range: tuple[Any, Any] | None = None,
        candle_data: Mapping[str, pd.DataFrame] | None = None,
        cross_boundary_policy: str = "EXCLUDE_CROSS_BOUNDARY_OUTCOME",
    ) -> SimulationResult:
        """Execute event-driven replay over candidate trades.

        When ``date_range=(start, end)`` is provided, strict half-open ``[start, end)``
        filtering is enforced across candidate entries, cross-boundary outcomes, MTM bar
        grids, and daily EOD calendars.

        Canonical cross-boundary trade policy (``entry_timestamp < end`` and ``exit_timestamp >= end``):
        - ``EXCLUDE_CROSS_BOUNDARY_OUTCOME`` (default, alias ``exclude``): excludes trades whose
          realized exit occurs at or after ``end``, preventing forward outcome leakage across
          split boundaries; excluded count is recorded in ``excluded_cross_boundary_count``.
        - ``TRUNCATE_AT_END`` (alias ``truncate``): marks open cross-boundary candidates to the
          last available candle bar strictly ``< end`` (requires ``candle_data``).
        """
        cfg = self.config
        fee_rate = cfg.fee_rate_bps / 10000.0
        slippage_rate = cfg.slippage_bps / 10000.0
        cooldown_delta = pd.Timedelta(minutes=cfg.cooldown_bars * cfg.bar_interval_minutes)

        policy_key = str(cross_boundary_policy or "EXCLUDE_CROSS_BOUNDARY_OUTCOME").strip().upper()
        if policy_key in {"EXCLUDE", "EXCLUDE_CROSS_BOUNDARY_OUTCOME"}:
            canonical_boundary_policy = "EXCLUDE_CROSS_BOUNDARY_OUTCOME"
        elif policy_key in {"TRUNCATE", "TRUNCATE_AT_END"}:
            canonical_boundary_policy = "TRUNCATE_AT_END"
        else:
            raise ValueError(f"Unsupported cross_boundary_policy: {cross_boundary_policy}")

        # 1. Normalize and sort trades deterministically using canonical EconomicReplayTrade:
        # Deterministic tie-breaking: (entry_timestamp, symbol, side, trade_id)
        normalized_candidates: list[EconomicReplayTrade] = []
        for idx, t in enumerate(candidate_trades):
            if isinstance(t, EconomicReplayTrade):
                cand = t
            else:
                cand = validate_economic_replay_trade(t, idx)
            normalized_candidates.append(cand)

        # Build candle lookup once when candle_data is provided (shared by TRUNCATE_AT_END and MTM)
        price_map: dict[tuple[str, pd.Timestamp], float] = {}
        all_candle_ts: set[pd.Timestamp] = set()
        symbol_candle_ts: dict[str, list[pd.Timestamp]] = {}
        if candle_data is not None:
            for sym, df_c in candle_data.items():
                norm_sym = sym.upper().removesuffix("USDT")
                sym_ts_list: list[pd.Timestamp] = []
                if "timestamp" in df_c.columns:
                    for _, row in df_c.iterrows():
                        ts = _normalize_timestamp(row["timestamp"])
                        price_map[(norm_sym, ts)] = float(row.get("close", 1.0))
                        all_candle_ts.add(ts)
                        sym_ts_list.append(ts)
                elif isinstance(df_c.index, pd.DatetimeIndex):
                    for ts, row in df_c.iterrows():
                        norm_ts = _normalize_timestamp(ts)
                        price_map[(norm_sym, norm_ts)] = float(row.get("close", 1.0))
                        all_candle_ts.add(norm_ts)
                        sym_ts_list.append(norm_ts)
                if sym_ts_list:
                    symbol_candle_ts[norm_sym] = sorted(set(sym_ts_list))

        # Enforce half-open [start_ts, end_ts) and leak-free cross-boundary trade policy
        excluded_cross_boundary_count = 0
        start_ts: pd.Timestamp | None = None
        end_ts: pd.Timestamp | None = None
        if date_range is not None:
            start_ts = _normalize_timestamp(date_range[0])
            end_ts = _normalize_timestamp(date_range[1])
            if end_ts <= start_ts:
                raise ValueError(
                    f"Invalid half-open date_range [{start_ts}, {end_ts}): end must be strictly after start"
                )
            bounded_candidates: list[EconomicReplayTrade] = []
            for c in normalized_candidates:
                if not (start_ts <= c.entry_timestamp < end_ts):
                    continue
                if c.exit_timestamp >= end_ts:
                    if canonical_boundary_policy == "EXCLUDE_CROSS_BOUNDARY_OUTCOME":
                        excluded_cross_boundary_count += 1
                        continue
                    # TRUNCATE_AT_END: mark-to-market strictly before end_ts
                    if candle_data is None:
                        raise ValueError(
                            "TRUNCATE_AT_END requires candle_data with mark prices in [entry_timestamp, end_ts)"
                        )
                    avail_ts = [
                        ts for ts in symbol_candle_ts.get(c.symbol, [])
                        if c.entry_timestamp <= ts < end_ts
                    ]
                    if not avail_ts:
                        raise ValueError(
                            f"TRUNCATE_AT_END found no mark candle in [{c.entry_timestamp}, {end_ts}) for {c.symbol}"
                        )
                    trunc_ts = avail_ts[-1]
                    trunc_price = price_map[(c.symbol, trunc_ts)]
                    trunc_ret = (
                        (trunc_price - c.entry_price) / c.entry_price
                        if c.side == "BUY"
                        else (c.entry_price - trunc_price) / c.entry_price
                    )
                    trunc_bars = max(
                        0,
                        int((trunc_ts - c.entry_timestamp).total_seconds() // (cfg.bar_interval_minutes * 60)),
                    )
                    c = EconomicReplayTrade(
                        trade_id=c.trade_id,
                        symbol=c.symbol,
                        side=c.side,
                        entry_timestamp=c.entry_timestamp,
                        exit_timestamp=trunc_ts,
                        entry_price=c.entry_price,
                        exit_price=trunc_price,
                        gross_return_fraction=trunc_ret,
                        exit_reason="BOUNDARY_TRUNCATED",
                        bars_held=trunc_bars,
                        source_contract_version=c.source_contract_version,
                        mark_price_path=None,
                        gross_pnl_bps=trunc_ret * 10000.0,
                        net_pnl_bps=None,
                    )
                bounded_candidates.append(c)
            normalized_candidates = bounded_candidates

        # Deterministic sorting
        normalized_candidates.sort(
            key=lambda x: (x.entry_timestamp, x.symbol, x.side, x.trade_id)
        )

        # 2. Extract discrete timeline events
        # Events: (timestamp, priority, event_type, payload)
        # Priority: 0 for EXIT (to free capital/capacity first), 1 for ENTRY
        events: list[tuple[pd.Timestamp, int, str, EconomicReplayTrade]] = []
        for c in normalized_candidates:
            events.append((c.entry_timestamp, 1, "ENTRY", c))

        events.sort(key=lambda x: (x[0], x[1]))

        # State
        cash = cfg.initial_capital
        active_positions: dict[str, Position] = {}  # trade_id -> Position
        last_exit_ts_per_asset: dict[str, pd.Timestamp] = {}  # symbol -> Timestamp
        executed_records: list[ExecutedTradeRecord] = []
        rejected_count = 0

        # Realized event timeline tracking: (timestamp, cash, locked_capital, equity)
        realized_timeline: list[dict[str, Any]] = []

        def current_realized_equity() -> float:
            return cash + sum(p.locked_capital for p in active_positions.values())

        # Start timeline
        if start_ts is not None:
            init_ts = start_ts
        elif normalized_candidates:
            init_ts = normalized_candidates[0].entry_timestamp
        else:
            init_ts = pd.Timestamp.now(tz="UTC")
        realized_timeline.append({
            "timestamp": init_ts,
            "cash": cash,
            "locked_capital": 0.0,
            "equity": cash,
        })

        pending_entries = list(events)
        pending_exits: list[tuple[pd.Timestamp, int, str, Position]] = []

        total_volume_traded = 0.0

        while pending_entries or pending_exits:
            next_entry_ts = pending_entries[0][0] if pending_entries else None
            next_exit_ts = pending_exits[0][0] if pending_exits else None

            # EXIT has priority if timestamps are equal (releases capital & capacity for same-bar entry)
            process_exit = False
            if next_exit_ts is not None and next_entry_ts is not None:
                if next_exit_ts <= next_entry_ts:
                    process_exit = True
                else:
                    process_exit = False
            elif next_exit_ts is not None:
                process_exit = True
            else:
                process_exit = False

            if process_exit:
                ts, _, _, pos = pending_exits.pop(0)
                del active_positions[pos.trade_id]

                # Update per-asset cooldown timestamp
                last_exit_ts_per_asset[pos.symbol] = max(
                    last_exit_ts_per_asset.get(pos.symbol, pos.exit_timestamp),
                    pos.exit_timestamp,
                )

                # Gross PnL in USD based on allocated locked capital
                gross_pnl_usd = pos.locked_capital * pos.raw_pnl_fraction

                # Calculate exit fill price with slippage
                if pos.side == "BUY":
                    # Sell to close: exit fill receives (1 - slippage)
                    exit_fill_price = pos.exit_price * (1.0 - slippage_rate)
                else:
                    # Buy to cover: exit fill pays (1 + slippage)
                    exit_fill_price = pos.exit_price * (1.0 + slippage_rate)

                # Nominal exit value = locked_capital * (1.0 + raw_pnl_fraction)
                nominal_exit_value = max(0.0, pos.locked_capital * (1.0 + pos.raw_pnl_fraction))
                exit_fee = nominal_exit_value * fee_rate
                exit_slippage_cost = nominal_exit_value * slippage_rate
                exit_cost = exit_fee + exit_slippage_cost

                total_cost = pos.entry_cost + exit_cost
                net_pnl_usd = gross_pnl_usd - total_cost
                net_pnl_pct = (net_pnl_usd / pos.locked_capital) * 100.0 if pos.locked_capital > 0 else 0.0
                net_return_bps = (net_pnl_usd / pos.locked_capital) * 10000.0 if pos.locked_capital > 0 else 0.0

                # Release locked capital + gross proceeds - exit cost
                # (Entry cost was already deducted from cash at entry time)
                cash += (pos.locked_capital + gross_pnl_usd - exit_cost)
                total_volume_traded += (pos.locked_capital + nominal_exit_value)

                eq_after = current_realized_equity()
                realized_timeline.append({
                    "timestamp": ts,
                    "cash": cash,
                    "locked_capital": sum(p.locked_capital for p in active_positions.values()),
                    "equity": eq_after,
                })

                bars = 0
                for c in normalized_candidates:
                    if c.trade_id == pos.trade_id:
                        bars = c.bars_held
                        break

                executed_records.append(ExecutedTradeRecord(
                    trade_id=pos.trade_id,
                    symbol=pos.symbol,
                    side=pos.side,
                    entry_timestamp=pos.entry_timestamp,
                    exit_timestamp=pos.exit_timestamp,
                    entry_price=pos.entry_price,
                    exit_price=pos.exit_price,
                    entry_fill_price=pos.entry_fill_price,
                    exit_fill_price=exit_fill_price,
                    locked_capital=pos.locked_capital,
                    entry_cost=pos.entry_cost,
                    exit_cost=exit_cost,
                    total_cost=total_cost,
                    gross_pnl_usd=gross_pnl_usd,
                    net_pnl_usd=net_pnl_usd,
                    net_pnl_pct=net_pnl_pct,
                    net_return_bps=net_return_bps,
                    equity_after_exit=eq_after,
                    bars_held=bars,
                    exit_reason=pos.exit_reason,
                    gross_return_fraction=pos.raw_pnl_fraction,
                ))

            else:
                ts, _, _, candidate = pending_entries.pop(0)
                cand_sym = candidate.symbol

                # 1. Canonical Policy Evaluation
                allowed, _ = self.policy.can_enter(
                    symbol=cand_sym,
                    side=candidate.side,
                    current_time=candidate.entry_timestamp,
                    active_positions=[{"symbol": p.symbol, "side": p.side} for p in active_positions.values()],
                    last_exit_timestamps=last_exit_ts_per_asset,
                    total_equity=current_realized_equity(),
                    available_cash=cash,
                )
                if not allowed:
                    rejected_count += 1
                    continue

                # 2. Side Lock check (opposing side conflict)
                asset_active = [p for p in active_positions.values() if p.symbol == cand_sym]
                if asset_active and asset_active[0].side != candidate.side:
                    rejected_count += 1
                    continue

                # 3. Capital Allocation & Sizing
                if cfg.fixed_allocation_usd is not None:
                    allocated_capital = cfg.fixed_allocation_usd
                else:
                    curr_eq = current_realized_equity()
                    allocated_capital = curr_eq * cfg.allocation_pct_per_trade

                # Calculate entry fill price with slippage
                if candidate.side == "BUY":
                    # Buying: pay (1 + slippage)
                    entry_fill_price = candidate.entry_price * (1.0 + slippage_rate)
                else:
                    # Selling: receive (1 - slippage)
                    entry_fill_price = candidate.entry_price * (1.0 - slippage_rate)

                entry_fee = allocated_capital * fee_rate
                entry_slippage_cost = allocated_capital * slippage_rate
                entry_cost = entry_fee + entry_slippage_cost

                total_required = allocated_capital + entry_cost

                if total_required > cash or allocated_capital <= 0:
                    rejected_count += 1
                    continue

                # Deduct cash and lock capital
                cash -= total_required

                pos = Position(
                    trade_id=candidate.trade_id,
                    symbol=cand_sym,
                    side=candidate.side,
                    entry_timestamp=candidate.entry_timestamp,
                    exit_timestamp=candidate.exit_timestamp,
                    entry_price=candidate.entry_price,
                    exit_price=candidate.exit_price,
                    raw_pnl_fraction=candidate.gross_return_fraction,
                    locked_capital=allocated_capital,
                    entry_cost=entry_cost,
                    entry_fill_price=entry_fill_price,
                    exit_reason=candidate.exit_reason,
                )
                active_positions[pos.trade_id] = pos

                # Schedule exit event in sorted order
                pending_exits.append((pos.exit_timestamp, 0, "EXIT", pos))
                pending_exits.sort(key=lambda x: (x[0], x[1]))

                realized_timeline.append({
                    "timestamp": ts,
                    "cash": cash,
                    "locked_capital": sum(p.locked_capital for p in active_positions.values()),
                    "equity": current_realized_equity(),
                })

        # 3. Build Realized Equity Curve
        df_realized = pd.DataFrame(realized_timeline).drop_duplicates(subset=["timestamp"], keep="last")
        df_realized = df_realized.sort_values("timestamp").reset_index(drop=True)

        final_equity = current_realized_equity()
        total_net_pnl_usd = final_equity - cfg.initial_capital
        total_net_pnl_pct = (total_net_pnl_usd / cfg.initial_capital) * 100.0

        # Compute Realized Drawdown
        if not df_realized.empty:
            r_equities = df_realized["equity"].values
            r_peaks = np.maximum.accumulate(r_equities)
            r_dd_usd = r_peaks - r_equities
            r_dd_pct = np.where(r_peaks > 0, r_dd_usd / r_peaks, 0.0)
            realized_dd_pct = float(np.max(r_dd_pct)) * 100.0
            realized_dd_usd = float(np.max(r_dd_usd))
        else:
            realized_dd_pct = 0.0
            realized_dd_usd = 0.0

        # 4. Mark-To-Market (MTM) Evaluation
        # If candle_data is provided, evaluate bar-by-bar MTM equity over half-open [start_ts, end_ts)
        mtm_records: list[dict[str, Any]] = []
        if candle_data is not None and executed_records:
            sorted_grid = sorted(all_candle_ts)
            if start_ts is not None and end_ts is not None:
                sorted_grid = [ts for ts in sorted_grid if start_ts <= ts < end_ts]

            # Re-simulate active positions against bar timestamps to calculate MTM
            # We can map each executed trade's life span: [entry_ts, exit_ts)
            for bar_ts in sorted_grid:
                # Find which executed trades were open at bar_ts
                open_trades = [
                    t for t in executed_records
                    if t.entry_timestamp <= bar_ts < t.exit_timestamp
                ]
                # Realized cash at bar_ts:
                # Cash = initial_capital + net_pnl of all trades exited before or at bar_ts - locked_capital of active trades - entry_costs of active trades
                exited_before = [
                    t for t in executed_records
                    if t.exit_timestamp <= bar_ts
                ]
                cash_realized = cfg.initial_capital + sum(t.net_pnl_usd for t in exited_before)
                active_locked = sum(t.locked_capital for t in open_trades)
                active_entry_costs = sum(t.entry_cost for t in open_trades)
                current_cash = cash_realized - active_locked - active_entry_costs

                unrealized_mtm_value = 0.0
                for ot in open_trades:
                    curr_price = price_map.get((ot.symbol, bar_ts), ot.entry_price)
                    if ot.side == "BUY":
                        unrealized_mtm_value += ot.locked_capital * (curr_price / ot.entry_price)
                    else:
                        unrealized_mtm_value += ot.locked_capital * (1.0 + (ot.entry_price - curr_price) / ot.entry_price)

                mtm_equity = current_cash + unrealized_mtm_value
                mtm_records.append({
                    "timestamp": bar_ts,
                    "cash": current_cash,
                    "locked_capital": active_locked,
                    "unrealized_value": unrealized_mtm_value,
                    "equity": mtm_equity,
                    "open_positions": len(open_trades),
                })

        if mtm_records:
            df_mtm = pd.DataFrame(mtm_records).sort_values("timestamp").reset_index(drop=True)
            mtm_equities = df_mtm["equity"].values
            mtm_peaks = np.maximum.accumulate(mtm_equities)
            mtm_dd_usd = mtm_peaks - mtm_equities
            mtm_dd_pct = np.where(mtm_peaks > 0, mtm_dd_usd / mtm_peaks, 0.0)
            mtm_drawdown_pct = float(np.max(mtm_dd_pct)) * 100.0
            mtm_drawdown_usd = float(np.max(mtm_dd_usd))
        else:
            df_mtm = df_realized.copy()
            mtm_drawdown_pct = realized_dd_pct
            mtm_drawdown_usd = realized_dd_usd

        # True Max Drawdown = max(realized_dd, mtm_dd)
        overall_max_dd_pct = max(realized_dd_pct, mtm_drawdown_pct)
        overall_max_dd_usd = max(realized_dd_usd, mtm_drawdown_usd)

        # 5. Portfolio Utilization & Exposure
        n_bars = len(df_mtm)
        if n_bars > 0 and "locked_capital" in df_mtm.columns:
            active_bars = len(df_mtm[df_mtm["locked_capital"] > 0])
            exposure_pct = (active_bars / n_bars) * 100.0
            ratios = np.where(df_mtm["equity"] > 0, df_mtm["locked_capital"] / df_mtm["equity"], 0.0)
            capital_utilization_pct = float(np.mean(ratios)) * 100.0
        else:
            exposure_pct = 0.0
            capital_utilization_pct = 0.0

        capital_turnover = (total_volume_traded / cfg.initial_capital) if cfg.initial_capital > 0 else 0.0

        # 6. Daily Sharpe and Sortino Ratios (from daily EOD equity)
        daily_sharpe = 0.0
        daily_sortino = 0.0
        daily_returns = pd.Series(dtype=float)

        base_df_for_returns = df_mtm if not df_mtm.empty else df_realized
        if not base_df_for_returns.empty and len(executed_records) > 0:
            df_indexed = base_df_for_returns.set_index("timestamp")
            if start_ts is not None and end_ts is not None:
                df_indexed = df_indexed[(df_indexed.index >= start_ts) & (df_indexed.index < end_ts)]
            daily_equity = df_indexed["equity"].resample("1D").last().ffill()

            if start_ts is not None and end_ts is not None:
                first_day = start_ts.floor("D")
                last_day = (end_ts - pd.Timedelta(nanoseconds=1)).floor("D")
                cal_idx = pd.date_range(start=first_day, end=last_day, freq="1D", tz="UTC")
                anchor_day = first_day - pd.Timedelta(days=1)
                full_idx = pd.DatetimeIndex([anchor_day]).append(cal_idx)
                anchored_equity = daily_equity.reindex(full_idx)
                anchored_equity.loc[anchor_day] = cfg.initial_capital
                anchored_equity = anchored_equity.ffill().fillna(cfg.initial_capital)
                daily_returns = anchored_equity.pct_change().dropna()
            elif len(daily_equity) > 1:
                daily_returns = daily_equity.pct_change().dropna()

            if len(daily_returns) > 1:
                mean_daily = float(daily_returns.mean())
                std_daily = float(daily_returns.std(ddof=1))

                if std_daily > 1e-12:
                    daily_sharpe = (mean_daily / std_daily) * math.sqrt(cfg.annualization_factor)

                downside_returns = daily_returns[daily_returns < 0.0]
                downside_std = float(np.sqrt(np.mean(downside_returns**2))) if len(downside_returns) > 0 else 0.0
                if downside_std > 1e-12:
                    daily_sortino = (mean_daily / downside_std) * math.sqrt(cfg.annualization_factor)

        # 7. Win / Loss Statistics
        n_exec = len(executed_records)
        wins = [r for r in executed_records if r.net_pnl_usd > 0.0]
        losses = [r for r in executed_records if r.net_pnl_usd <= 0.0]
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / n_exec * 100.0) if n_exec > 0 else 0.0

        gross_profit = sum(r.net_pnl_usd for r in wins)
        gross_loss = abs(sum(r.net_pnl_usd for r in losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 1e-9 else (999.0 if gross_profit > 0 else 0.0)

        expectancy_usd = (total_net_pnl_usd / n_exec) if n_exec > 0 else 0.0
        total_allocated = sum(r.locked_capital for r in executed_records)
        expectancy_bps = ((total_net_pnl_usd / total_allocated) * 10000.0) if total_allocated > 0 else 0.0

        return SimulationResult(
            initial_capital=cfg.initial_capital,
            final_equity=final_equity,
            total_net_pnl_usd=total_net_pnl_usd,
            total_net_pnl_pct=total_net_pnl_pct,
            executed_trades_count=n_exec,
            rejected_capacity_count=rejected_count,
            win_count=win_count,
            loss_count=loss_count,
            win_rate_pct=win_rate,
            gross_profit_usd=gross_profit,
            gross_loss_usd=gross_loss,
            profit_factor=profit_factor,
            expectancy_usd=expectancy_usd,
            expectancy_bps=expectancy_bps,
            realized_drawdown_pct=realized_dd_pct,
            realized_drawdown_usd=realized_dd_usd,
            mtm_drawdown_pct=mtm_drawdown_pct,
            mtm_drawdown_usd=mtm_drawdown_usd,
            max_drawdown_pct=overall_max_dd_pct,
            max_drawdown_usd=overall_max_dd_usd,
            capital_turnover=capital_turnover,
            exposure_pct=exposure_pct,
            capital_utilization_pct=capital_utilization_pct,
            daily_sharpe=daily_sharpe,
            daily_sortino=daily_sortino,
            daily_returns=daily_returns,
            equity_curve=df_realized,
            mtm_equity_curve=df_mtm,
            executed_trades=executed_records,
            excluded_cross_boundary_count=excluded_cross_boundary_count,
            cross_boundary_policy=canonical_boundary_policy,
        )
