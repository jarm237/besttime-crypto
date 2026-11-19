"""S5-P0 Economic Replay Engine: Fee-Aware Portfolio Accounting, Causal Signals, and Gate Evaluation.

Pre-registration: research/s5_economic_opportunity/s5_p0_executable_preregistration.md
Pre-execution erratum: research/s5_economic_opportunity/s5_p0_pre_execution_erratum.md
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd

from btc_scraper.research.s4_dataset_audit import (
    AUDIT_END,
    AUDIT_START,
    UNIVERSE,
    load_binance_archives,
    indexed_panel,
)

PRIMARY_COST_BPS = 12.0
PRIMARY_NO_TRADE_BAND = 0.05
PRIMARY_INITIAL_CAPITAL = 10000.0


class ReplayError(RuntimeError):
    """Raised when an accounting invariant or causal dependency is violated."""


def solve_post_fee_equity(
    v_pre: float,
    current_notionals: np.ndarray,
    target_weights: np.ndarray,
    fee_rate: float,
    tol: float = 1e-12,
    max_iter: int = 100,
) -> tuple[float, float]:
    """Solve for the unique post-fee equity V_post satisfying:

    V_post = V_pre - fee_rate * sum(|w_i * V_post - N_i|)

    Returns (V_post, realized_fee).
    Guarantees:
      V_post + realized_fee == V_pre
      V_post >= 0
      realized_fee >= 0
    """
    if v_pre < 0:
        raise ReplayError(f"Negative pre-trade equity: {v_pre}")
    if v_pre == 0 or fee_rate == 0:
        return float(v_pre), 0.0

    current_notionals = np.asarray(current_notionals, dtype=float)
    target_weights = np.asarray(target_weights, dtype=float)

    if (current_notionals < 0).any():
        raise ReplayError(f"Negative current notionals: {current_notionals}")
    if (target_weights < 0).any():
        raise ReplayError(f"Negative target weights: {target_weights}")

    sum_weights = float(np.sum(target_weights))
    if sum_weights > 1.0 + 1e-6:
        raise ReplayError(f"Target weights sum exceeds 1.0: {sum_weights}")

    # f(V) = V + fee_rate * sum(|w_i * V - N_i|) - V_pre
    def f(v: float) -> float:
        turnovers = np.abs(target_weights * v - current_notionals)
        return float(v + fee_rate * np.sum(turnovers) - v_pre)

    low = 0.0
    high = float(v_pre)
    f_low = f(low)
    f_high = f(high)

    if f_low > 0:
        # Should not occur since f(0) = fee_rate * sum(N_i) - V_pre <= 0
        return float(v_pre), 0.0
    if f_high <= 0:
        return high, 0.0

    for _ in range(max_iter):
        mid = 0.5 * (low + high)
        f_mid = f(mid)
        if abs(f_mid) < tol or (high - low) < tol:
            break
        if f_mid < 0:
            low = mid
        else:
            high = mid

    v_post = 0.5 * (low + high)
    turnover = float(np.sum(np.abs(target_weights * v_post - current_notionals)))
    realized_fee = fee_rate * turnover

    # Adjust slightly if floating point drift
    if abs(v_post + realized_fee - v_pre) > 1e-9:
        v_post = v_pre - realized_fee

    return float(v_post), float(realized_fee)


def compute_one_way_deviation(
    current_notionals: np.ndarray,
    current_cash: float,
    target_weights: np.ndarray,
) -> float:
    """Compute one-way portfolio weight deviation:

    dev = 0.5 * (sum(|w_i^target - w_i^drifted|) + |w_cash^target - w_cash^drifted|)
    """
    v_total = float(np.sum(current_notionals) + current_cash)
    if v_total <= 0:
        return 0.0
    w_drifted = current_notionals / v_total
    w_cash_drifted = current_cash / v_total
    w_cash_target = max(0.0, 1.0 - float(np.sum(target_weights)))

    dev = 0.5 * (float(np.sum(np.abs(target_weights - w_drifted))) + abs(w_cash_target - w_cash_drifted))
    return float(dev)


def get_causal_bars(
    panels: Mapping[str, pd.DataFrame],
    decision_dt: pd.Timestamp,
    lookback_hours: int = 168,
) -> pd.DataFrame | None:
    """Extract closed hourly close prices up to decision_dt - 1h.

    Binance timestamp is candle open. At decision_dt (e.g. 00:00 UTC),
    the latest closed candle is timestamped decision_dt - 1h (23:00 UTC).
    Returns a DataFrame with columns [UNIVERSE] and index length lookback_hours + 1,
    or None if missing bars.
    """
    cutoff = decision_dt - pd.Timedelta(hours=1)
    start = cutoff - pd.Timedelta(hours=lookback_hours)
    idx = pd.date_range(start, cutoff, freq="h", tz="UTC")

    closes = {}
    for s in UNIVERSE:
        panel = panels[s]
        if not idx.isin(panel.index).all():
            return None
        sub = panel.loc[idx, "close"]
        if sub.isna().any() or (sub <= 0).any():
            return None
        closes[s] = sub.to_numpy(dtype=float)

    return pd.DataFrame(closes, index=idx)


def compute_market_trend_168h(
    panels: Mapping[str, pd.DataFrame],
    decision_dt: pd.Timestamp,
) -> float | None:
    """Compute 168h return of equal-weight 4-asset basket:

    R_mkt = 0.25 * sum(P_{t-1h} / P_{t-169h} - 1)
    """
    df = get_causal_bars(panels, decision_dt, lookback_hours=168)
    if df is None:
        return None
    p_start = df.iloc[0].to_numpy()
    p_end = df.iloc[-1].to_numpy()
    ret_168h = (p_end / p_start) - 1.0
    return float(np.mean(ret_168h))


def compute_market_volatility_168h(
    panels: Mapping[str, pd.DataFrame],
    decision_dt: pd.Timestamp,
) -> float | None:
    """Compute annualized sample volatility of hourly log returns over 168h."""
    df = get_causal_bars(panels, decision_dt, lookback_hours=168)
    if df is None:
        return None
    # Equal-weight hourly returns
    log_rets = np.log(df / df.shift(1)).dropna()
    mkt_log_rets = log_rets.mean(axis=1).to_numpy()
    hourly_std = float(np.std(mkt_log_rets, ddof=1))
    annualized_vol = hourly_std * math.sqrt(8760)
    return float(annualized_vol)


def compute_asset_momentums_168h(
    panels: Mapping[str, pd.DataFrame],
    decision_dt: pd.Timestamp,
) -> dict[str, float] | None:
    """Compute individual asset 168h log return: ln(P_{t-1h} / P_{t-169h})."""
    df = get_causal_bars(panels, decision_dt, lookback_hours=168)
    if df is None:
        return None
    p_start = df.iloc[0]
    p_end = df.iloc[-1]
    return {s: float(np.log(p_end[s] / p_start[s])) for s in UNIVERSE}


def compute_asset_volatilities_168h(
    panels: Mapping[str, pd.DataFrame],
    decision_dt: pd.Timestamp,
) -> dict[str, float] | None:
    """Compute individual asset 168h realized volatility."""
    df = get_causal_bars(panels, decision_dt, lookback_hours=168)
    if df is None:
        return None
    log_rets = np.log(df / df.shift(1)).dropna()
    vols = {}
    for s in UNIVERSE:
        std = float(np.std(log_rets[s].to_numpy(), ddof=1))
        vols[s] = float(std * math.sqrt(8760))
    return vols


# -------------------------------------------------------------------------
# Policy Definitions
# -------------------------------------------------------------------------

PolicyFunc = Callable[[Mapping[str, pd.DataFrame], pd.Timestamp], tuple[np.ndarray, str]]


def policy_cash_100(
    panels: Mapping[str, pd.DataFrame], decision_dt: pd.Timestamp
) -> tuple[np.ndarray, str]:
    return np.zeros(4, dtype=float), "CASH_100"


def policy_btc_bh(
    panels: Mapping[str, pd.DataFrame], decision_dt: pd.Timestamp
) -> tuple[np.ndarray, str]:
    w = np.zeros(4, dtype=float)
    w[0] = 1.0  # BTCUSDT is index 0
    return w, "BTC_BH"


def policy_ew4(
    panels: Mapping[str, pd.DataFrame], decision_dt: pd.Timestamp
) -> tuple[np.ndarray, str]:
    return np.full(4, 0.25, dtype=float), "EW4"


def policy_trend_cash_gate_btc(
    panels: Mapping[str, pd.DataFrame], decision_dt: pd.Timestamp
) -> tuple[np.ndarray, str]:
    trend = compute_market_trend_168h(panels, decision_dt)
    if trend is None:
        return np.full(4, float("nan")), "HOLD_DATA_GAP"
    w = np.zeros(4, dtype=float)
    if trend > 0.0:
        w[0] = 1.0
        return w, "BULL_EXPOSURE_1.0"
    return w, "BEAR_CASH_1.0"


def policy_trend_cash_gate_ew4(
    panels: Mapping[str, pd.DataFrame], decision_dt: pd.Timestamp
) -> tuple[np.ndarray, str]:
    trend = compute_market_trend_168h(panels, decision_dt)
    if trend is None:
        return np.full(4, float("nan")), "HOLD_DATA_GAP"
    if trend > 0.0:
        return np.full(4, 0.25, dtype=float), "BULL_EXPOSURE_1.0"
    return np.zeros(4, dtype=float), "BEAR_CASH_1.0"


def policy_causal_vol_target_btc(
    panels: Mapping[str, pd.DataFrame], decision_dt: pd.Timestamp
) -> tuple[np.ndarray, str]:
    vol = compute_market_volatility_168h(panels, decision_dt)
    if vol is None:
        return np.full(4, float("nan")), "HOLD_DATA_GAP"
    target_vol = 0.40
    g = min(1.0, target_vol / max(vol, 0.10))
    w = np.zeros(4, dtype=float)
    w[0] = g
    return w, f"VOL_SCALE_{g:.4f}"


def policy_causal_vol_target_ew4(
    panels: Mapping[str, pd.DataFrame], decision_dt: pd.Timestamp
) -> tuple[np.ndarray, str]:
    vol = compute_market_volatility_168h(panels, decision_dt)
    if vol is None:
        return np.full(4, float("nan")), "HOLD_DATA_GAP"
    target_vol = 0.40
    g = min(1.0, target_vol / max(vol, 0.10))
    return np.full(4, g * 0.25, dtype=float), f"VOL_SCALE_{g:.4f}"


def policy_momentum_top1_full(
    panels: Mapping[str, pd.DataFrame], decision_dt: pd.Timestamp
) -> tuple[np.ndarray, str]:
    moms = compute_asset_momentums_168h(panels, decision_dt)
    if moms is None:
        return np.full(4, float("nan")), "HOLD_DATA_GAP"
    # Sort descending by momentum, ties by symbol order
    ranked = sorted(UNIVERSE, key=lambda s: (moms[s]), reverse=True)
    top1 = ranked[0]
    w = np.zeros(4, dtype=float)
    w[UNIVERSE.index(top1)] = 1.0
    return w, f"TOP1_{top1}"


def policy_momentum_top1_trend_gate(
    panels: Mapping[str, pd.DataFrame], decision_dt: pd.Timestamp
) -> tuple[np.ndarray, str]:
    trend = compute_market_trend_168h(panels, decision_dt)
    if trend is None:
        return np.full(4, float("nan")), "HOLD_DATA_GAP"
    if trend <= 0.0:
        return np.zeros(4, dtype=float), "BEAR_CASH_1.0"
    moms = compute_asset_momentums_168h(panels, decision_dt)
    if moms is None:
        return np.full(4, float("nan")), "HOLD_DATA_GAP"
    ranked = sorted(UNIVERSE, key=lambda s: (moms[s]), reverse=True)
    top1 = ranked[0]
    w = np.zeros(4, dtype=float)
    w[UNIVERSE.index(top1)] = 1.0
    return w, f"BULL_TOP1_{top1}"


def policy_momentum_top2_full(
    panels: Mapping[str, pd.DataFrame], decision_dt: pd.Timestamp
) -> tuple[np.ndarray, str]:
    """MOMENTUM_TOP2 (alias CARM4_ADAPTATION)."""
    moms = compute_asset_momentums_168h(panels, decision_dt)
    if moms is None:
        return np.full(4, float("nan")), "HOLD_DATA_GAP"
    ranked = sorted(UNIVERSE, key=lambda s: (moms[s]), reverse=True)
    top2 = ranked[:2]
    w = np.zeros(4, dtype=float)
    for s in top2:
        w[UNIVERSE.index(s)] = 0.50
    return w, f"TOP2_{top2[0]}_{top2[1]}"


def policy_momentum_top2_trend_gate(
    panels: Mapping[str, pd.DataFrame], decision_dt: pd.Timestamp
) -> tuple[np.ndarray, str]:
    """MOMENTUM_TOP2 x TREND_CASH_GATE (alias CARM4_ADAPTATION x TREND_CASH_GATE)."""
    trend = compute_market_trend_168h(panels, decision_dt)
    if trend is None:
        return np.full(4, float("nan")), "HOLD_DATA_GAP"
    if trend <= 0.0:
        return np.zeros(4, dtype=float), "BEAR_CASH_1.0"
    moms = compute_asset_momentums_168h(panels, decision_dt)
    if moms is None:
        return np.full(4, float("nan")), "HOLD_DATA_GAP"
    ranked = sorted(UNIVERSE, key=lambda s: (moms[s]), reverse=True)
    top2 = ranked[:2]
    w = np.zeros(4, dtype=float)
    for s in top2:
        w[UNIVERSE.index(s)] = 0.50
    return w, f"BULL_TOP2_{top2[0]}_{top2[1]}"


def policy_inverse_vol4_full(
    panels: Mapping[str, pd.DataFrame], decision_dt: pd.Timestamp
) -> tuple[np.ndarray, str]:
    vols = compute_asset_volatilities_168h(panels, decision_dt)
    if vols is None:
        return np.full(4, float("nan")), "HOLD_DATA_GAP"
    invs = np.array([1.0 / max(vols[s], 0.01) for s in UNIVERSE], dtype=float)
    w = invs / np.sum(invs)
    return w, "INV_VOL_FULL"


def policy_inverse_vol4_trend_gate(
    panels: Mapping[str, pd.DataFrame], decision_dt: pd.Timestamp
) -> tuple[np.ndarray, str]:
    trend = compute_market_trend_168h(panels, decision_dt)
    if trend is None:
        return np.full(4, float("nan")), "HOLD_DATA_GAP"
    if trend <= 0.0:
        return np.zeros(4, dtype=float), "BEAR_CASH_1.0"
    vols = compute_asset_volatilities_168h(panels, decision_dt)
    if vols is None:
        return np.full(4, float("nan")), "HOLD_DATA_GAP"
    invs = np.array([1.0 / max(vols[s], 0.01) for s in UNIVERSE], dtype=float)
    w = invs / np.sum(invs)
    return w, "BULL_INV_VOL"


POLICIES: dict[str, PolicyFunc] = {
    "CASH_100": policy_cash_100,
    "BTC_BH": policy_btc_bh,
    "EW4": policy_ew4,
    "EW4_BUY_AND_HOLD": policy_ew4,  # Handled via static hold
    "TREND_GATE_BTC": policy_trend_cash_gate_btc,
    "TREND_GATE_EW4": policy_trend_cash_gate_ew4,
    "VOL_TARGET_BTC": policy_causal_vol_target_btc,
    "VOL_TARGET_EW4": policy_causal_vol_target_ew4,
    "MOMENTUM_TOP1": policy_momentum_top1_full,
    "MOMENTUM_TOP1_TREND_GATE": policy_momentum_top1_trend_gate,
    "MOMENTUM_TOP2": policy_momentum_top2_full,  # CARM4_ADAPTATION alias
    "MOMENTUM_TOP2_TREND_GATE": policy_momentum_top2_trend_gate,
    "INVERSE_VOL4": policy_inverse_vol4_full,
    "INVERSE_VOL4_TREND_GATE": policy_inverse_vol4_trend_gate,
}


@dataclass
class ReplayResult:
    policy_name: str
    fee_bps: float
    no_trade_band: float
    rebalance_freq: str
    timestamps: list[pd.Timestamp]
    equities: np.ndarray
    cash_history: np.ndarray
    holdings_history: np.ndarray
    weights_history: np.ndarray
    turnovers: np.ndarray
    fees: np.ndarray
    rebalance_events: list[dict[str, object]]
    cagr: float
    cum_return: float
    max_drawdown: float
    calmar: float
    sharpe: float
    avg_cash: float
    annualized_turnover: float
    total_fees: float


def run_stateful_replay(
    panels: Mapping[str, pd.DataFrame],
    policy_name: str,
    start_dt: pd.Timestamp = pd.Timestamp("2022-01-01 00:00:00", tz="UTC"),
    end_dt: pd.Timestamp = pd.Timestamp("2023-12-31 23:00:00", tz="UTC"),
    initial_capital: float = PRIMARY_INITIAL_CAPITAL,
    fee_bps: float = PRIMARY_COST_BPS,
    no_trade_band: float = PRIMARY_NO_TRADE_BAND,
    rebalance_freq: str = "WEEKLY",  # WEEKLY or DAILY
    target_weights_cache: dict[tuple[str, pd.Timestamp], tuple[np.ndarray, str]] | None = None,
) -> ReplayResult:
    """Execute stateful fee-aware portfolio simulation."""
    fee_rate = fee_bps / 10000.0
    policy_func = POLICIES[policy_name]

    def _get_target_weights(dt: pd.Timestamp) -> tuple[np.ndarray, str]:
        if target_weights_cache is not None and (policy_name, dt) in target_weights_cache:
            return target_weights_cache[(policy_name, dt)]
        res = policy_func(panels, dt)
        if target_weights_cache is not None:
            target_weights_cache[(policy_name, dt)] = res
        return res

    # Find common hourly timeline
    timeline = panels["BTCUSDT"].loc[start_dt:end_dt].index
    for s in UNIVERSE:
        timeline = timeline.intersection(panels[s].loc[start_dt:end_dt].index)

    # Determine rebalancing schedule
    # Decisions are at 00:00 UTC, execution at 01:00 UTC
    decision_dates = []
    curr = start_dt
    while curr <= end_dt:
        if rebalance_freq == "WEEKLY":
            # Sunday is day 6 in pandas (Monday=0, Sunday=6)
            if curr.dayofweek == 6 and curr.hour == 0:
                decision_dates.append(curr)
        elif rebalance_freq == "DAILY":
            if curr.hour == 0:
                decision_dates.append(curr)
        curr += pd.Timedelta(hours=1)

    decision_set = set(decision_dates)

    # Pre-extract open and close arrays for maximum performance
    opens_arr = np.column_stack([panels[s].loc[timeline, "open"].to_numpy(dtype=float) for s in UNIVERSE])
    closes_arr = np.column_stack([panels[s].loc[timeline, "close"].to_numpy(dtype=float) for s in UNIVERSE])

    # State variables
    cash = float(initial_capital)
    holdings = np.zeros(4, dtype=float)

    n_bars = len(timeline)
    equities = np.empty(n_bars, dtype=float)
    cash_hist = np.empty(n_bars, dtype=float)
    holdings_hist = np.empty((n_bars, 4), dtype=float)
    weights_hist = np.empty((n_bars, 4), dtype=float)
    turnover_hist = np.zeros(n_bars, dtype=float)
    fees_hist = np.zeros(n_bars, dtype=float)
    events: list[dict[str, object]] = []

    is_buy_and_hold = policy_name in ("BTC_BH", "EW4_BUY_AND_HOLD")
    has_initialized = False

    for t_idx, t_bar in enumerate(timeline):
        # Current open prices for all 4 assets from pre-extracted array
        p_open = opens_arr[t_idx]

        # Check if this bar is an execution bar:
        # Execution is at 01:00 UTC if 00:00 UTC was a decision date
        is_exec_bar = False
        decision_dt = t_bar - pd.Timedelta(hours=1)
        if decision_dt in decision_set and t_bar.hour == 1:
            is_exec_bar = True

        # Handle initial allocation at first execution bar or inception
        if not has_initialized and (is_exec_bar or t_idx == 0):
            # Compute target weights
            target_w, reason = _get_target_weights(decision_dt if is_exec_bar else t_bar)
            if np.isnan(target_w).any():
                target_w = np.zeros(4, dtype=float)

            current_notionals = holdings * p_open
            v_pre = cash + float(np.sum(current_notionals))

            v_post, fee = solve_post_fee_equity(v_pre, current_notionals, target_w, fee_rate)
            new_notionals = target_w * v_post
            holdings = new_notionals / p_open
            cash = max(0.0, (1.0 - float(np.sum(target_w))) * v_post)

            turnover = float(np.sum(np.abs(new_notionals - current_notionals)))
            turnover_hist[t_idx] = turnover
            fees_hist[t_idx] = fee
            has_initialized = True
            events.append({
                "bar": t_bar.isoformat(),
                "action": "INITIAL_ALLOCATION",
                "reason": reason,
                "v_pre": v_pre,
                "v_post": v_post,
                "fee": fee,
                "target_weights": target_w.tolist(),
            })

        elif is_exec_bar and not is_buy_and_hold:
            target_w, reason = _get_target_weights(decision_dt)
            if np.isnan(target_w).any():
                # Data gap / invalid: HOLD existing position
                events.append({
                    "bar": t_bar.isoformat(),
                    "action": "HOLD_DATA_GAP",
                    "reason": reason,
                })
            else:
                current_notionals = holdings * p_open
                v_pre = cash + float(np.sum(current_notionals))

                # Check no-trade band
                dev = compute_one_way_deviation(current_notionals, cash, target_w)
                if dev > no_trade_band:
                    v_post, fee = solve_post_fee_equity(v_pre, current_notionals, target_w, fee_rate)
                    new_notionals = target_w * v_post
                    holdings = new_notionals / p_open
                    cash = max(0.0, (1.0 - float(np.sum(target_w))) * v_post)

                    turnover = float(np.sum(np.abs(new_notionals - current_notionals)))
                    turnover_hist[t_idx] = turnover
                    fees_hist[t_idx] = fee
                    events.append({
                        "bar": t_bar.isoformat(),
                        "action": "REBALANCE",
                        "reason": reason,
                        "deviation": dev,
                        "v_pre": v_pre,
                        "v_post": v_post,
                        "fee": fee,
                        "target_weights": target_w.tolist(),
                    })
                else:
                    events.append({
                        "bar": t_bar.isoformat(),
                        "action": "SKIP_WITHIN_BAND",
                        "reason": reason,
                        "deviation": dev,
                    })

        # Valuation at current bar close from pre-extracted array
        p_close = closes_arr[t_idx]
        current_eq = cash + float(np.sum(holdings * p_close))
        equities[t_idx] = current_eq
        cash_hist[t_idx] = cash
        holdings_hist[t_idx] = holdings
        weights_hist[t_idx] = (holdings * p_close) / max(current_eq, 1e-12)

    # Compute summary performance metrics
    total_days = (timeline[-1] - timeline[0]).total_seconds() / 86400.0
    cum_ret = float(equities[-1] / initial_capital - 1.0)
    cagr = float((equities[-1] / initial_capital) ** (365.25 / total_days) - 1.0) if equities[-1] > 0 else -1.0

    # Max Drawdown
    peak = np.maximum.accumulate(equities)
    drawdowns = (equities - peak) / peak
    max_dd = float(np.min(drawdowns))  # negative float

    calmar = float(cagr / abs(max_dd)) if abs(max_dd) > 1e-6 else 0.0

    # Sharpe ratio from hourly log returns
    hourly_rets = np.diff(np.log(equities))
    if len(hourly_rets) > 1 and np.std(hourly_rets) > 1e-12:
        sharpe = float(np.mean(hourly_rets) / np.std(hourly_rets) * math.sqrt(8760))
    else:
        sharpe = 0.0

    avg_cash = float(np.mean(cash_hist / equities))
    total_turnover = float(np.sum(turnover_hist))
    ann_turnover = float(total_turnover / initial_capital * (365.25 / total_days))
    total_fees = float(np.sum(fees_hist))

    return ReplayResult(
        policy_name=policy_name,
        fee_bps=fee_bps,
        no_trade_band=no_trade_band,
        rebalance_freq=rebalance_freq,
        timestamps=list(timeline),
        equities=equities,
        cash_history=cash_hist,
        holdings_history=holdings_hist,
        weights_history=weights_hist,
        turnovers=turnover_hist,
        fees=fees_hist,
        rebalance_events=events,
        cagr=cagr,
        cum_return=cum_ret,
        max_drawdown=max_dd,
        calmar=calmar,
        sharpe=sharpe,
        avg_cash=avg_cash,
        annualized_turnover=ann_turnover,
        total_fees=total_fees,
    )


def compute_breakeven_cost(
    panels: Mapping[str, pd.DataFrame],
    policy_name: str,
    benchmark_name: str = "BTC_BH",
    start_dt: pd.Timestamp = pd.Timestamp("2022-01-01 00:00:00", tz="UTC"),
    end_dt: pd.Timestamp = pd.Timestamp("2023-12-31 23:00:00", tz="UTC"),
    no_trade_band: float = PRIMARY_NO_TRADE_BAND,
    rebalance_freq: str = "WEEKLY",
    target_weights_cache: dict[tuple[str, pd.Timestamp], tuple[np.ndarray, str]] | None = None,
) -> tuple[float | None, str]:
    """Find the one-way fee rate c* in [0, 100 bps] where terminal excess log-wealth = 0."""
    # Pre-extract BTC benchmark ratio for closed-form instantaneous evaluation
    sub_btc = panels["BTCUSDT"].loc[start_dt:end_dt]
    p_btc_0 = float(sub_btc.iloc[0]["open"])
    p_btc_T = float(sub_btc.iloc[-1]["close"])
    btc_ratio = p_btc_T / p_btc_0

    def diff_log_wealth(c_bps: float) -> float:
        r_pol = run_stateful_replay(
            panels, policy_name, start_dt, end_dt, fee_bps=c_bps,
            no_trade_band=no_trade_band, rebalance_freq=rebalance_freq,
            target_weights_cache=target_weights_cache,
        )
        if benchmark_name == "BTC_BH":
            v_bm = (PRIMARY_INITIAL_CAPITAL / (1.0 + c_bps / 10000.0)) * btc_ratio
        else:
            r_bm = run_stateful_replay(
                panels, benchmark_name, start_dt, end_dt, fee_bps=c_bps,
                no_trade_band=no_trade_band, rebalance_freq=rebalance_freq,
                target_weights_cache=target_weights_cache,
            )
            v_bm = float(r_bm.equities[-1])
        return float(np.log(r_pol.equities[-1] / v_bm))

    diff_0 = diff_log_wealth(0.0)
    if diff_0 <= 0:
        return None, "NO_POSITIVE_BREAKEVEN_EDGE"

    diff_100 = diff_log_wealth(100.0)
    if diff_100 > 0:
        return 100.0, "NO_CROSSING_IN_RANGE"

    # Bracketed between 0 and 100 bps
    low = 0.0
    high = 100.0
    for _ in range(12):  # 100 / 2^12 = 0.024 bps precision (< 0.1 bps tolerance)
        mid = 0.5 * (low + high)
        d_mid = diff_log_wealth(mid)
        if abs(d_mid) < 1e-5:
            return float(mid), "ROOT_FOUND"
        if d_mid > 0:
            low = mid
        else:
            high = mid

    return float(0.5 * (low + high)), "ROOT_FOUND"


@dataclass
class GateVerdict:
    status: str  # S5_P0_ECONOMIC_OPPORTUNITY_CANDIDATE / S5_P0_NO_DEMONSTRATED_OPPORTUNITY / S5_P0_INCONCLUSIVE_OR_INVALID
    qualifying_policies: list[str]
    policy_checks: dict[str, dict[str, bool]]
    btc_cagr: float
    btc_max_dd: float
    btc_calmar: float
    is_btc_cagr_positive: bool


def evaluate_economic_gates(
    primary_results: dict[str, ReplayResult],
    stress_results_20bps: dict[str, ReplayResult],
) -> GateVerdict:
    """Evaluate candidate policies against pre-registered economic gates."""
    btc_res = primary_results["BTC_BH"]
    btc_cagr = btc_res.cagr
    btc_max_dd = btc_res.max_drawdown
    btc_calmar = btc_res.calmar
    is_positive = btc_cagr > 0

    qualifying: list[str] = []
    checks: dict[str, dict[str, bool]] = {}

    for name, res in primary_results.items():
        if name in ("CASH_100", "BTC_BH", "EW4_BUY_AND_HOLD"):
            continue

        cagr_cond = bool(res.cagr >= 0.75 * btc_cagr) if is_positive else True
        cagr_condition_label = "cagr_retention_gte_75pct" if is_positive else "not_applicable"

        # Fallback when BTC CAGR <= 0
        if not is_positive:
            cap_preservation = bool(res.equities[-1] > PRIMARY_INITIAL_CAPITAL or (res.cagr - btc_cagr >= 0.15))
        else:
            cap_preservation = bool(res.equities[-1] > PRIMARY_INITIAL_CAPITAL)

        dd_cond = bool(abs(res.max_drawdown) <= 0.65 * abs(btc_max_dd))
        calmar_cond = bool(res.calmar > btc_calmar)
        active_cond = bool(res.avg_cash <= 0.85)  # must have at least 15% crypto exposure

        # Stress 20 bps survival
        stress_res = stress_results_20bps.get(name)
        if stress_res:
            stress_survives = bool(
                stress_res.equities[-1] > PRIMARY_INITIAL_CAPITAL
                and abs(stress_res.max_drawdown) <= 0.65 * abs(btc_max_dd)
                and stress_res.calmar > btc_calmar
            )
        else:
            stress_survives = False

        policy_check = {
            cagr_condition_label: cagr_cond,
            "capital_preservation": cap_preservation,
            "drawdown_compression_lte_65pct": dd_cond,
            "calmar_superiority": calmar_cond,
            "active_crypto_participation": active_cond,
            "stress_20bps_survival": stress_survives,
        }
        checks[name] = policy_check

        if all(policy_check.values()):
            qualifying.append(name)

    if len(qualifying) > 0:
        status = "S5_P0_ECONOMIC_OPPORTUNITY_CANDIDATE"
    else:
        status = "S5_P0_NO_DEMONSTRATED_OPPORTUNITY"

    return GateVerdict(
        status=status,
        qualifying_policies=qualifying,
        policy_checks=checks,
        btc_cagr=btc_cagr,
        btc_max_dd=btc_max_dd,
        btc_calmar=btc_calmar,
        is_btc_cagr_positive=is_positive,
    )
