#!/usr/bin/env python3
"""HMR-V5: Leak-Free Candidate Evaluation & Statistical Gate Runner (2023-2026) v2.

Enforces strict causal backtest and statistical governance:
1. Next-Bar-Open Execution Contract for VOL_COMPRESSION_BREAKOUT_V1:
   - Signal confirmed strictly at close of bar `i` using data `<= i` (`signal_index = i`,
     `signal_timestamp = ts[i]`, `signal_close_timestamp = ts[i] + 15m`).
   - Earliest entry strictly at open of bar `i + 1` (`entry_index = i + 1`,
     `entry_timestamp = ts[i + 1]`, `entry_price = opens[i + 1]`).
   - Zero lookahead into `high[i+1]`, `low[i+1]`, `close[i+1]`, or `volume[i+1]` for signal admission.
   - Path simulation runs from `entry_index` for `max_hold` bars (`entry_index .. entry_index + max_hold - 1`),
     enforcing conservative SL-first intrabar collision resolution and adverse open-price fills on
     gap-through-stop events (`SL_GAP`).
2. Honest Split & Multiple-Testing Semantics:
   - `EXPLORATORY_TRAIN_2023` `[2023-01-01, 2024-01-01)`: exploratory discovery / fold 1 training.
   - `DEV_SELECTION_2024` `[2024-01-01, 2025-01-01)` & `DEV_SELECTION_2025` `[2025-01-01, 2026-01-01)` ->
     `DEV_WALK_FORWARD_SELECTION_2024_2025`: development/selection evidence (NOT independent OOS).
   - `BURNED_EXPOSED_AUDIT_2026_H1` `[2026-01-01, 2026-07-01)`: exposed one-shot audit set; failed and
     permanently burned (never used for tuning or re-selection).
   - Multiple-testing count is recorded as `UNKNOWN`; all historical CIs prior to an immutable prospective
     shadow lock are strictly exploratory.
3. Time-Block / Stationary Portfolio Uncertainty Gate:
   - Primary statistical gate (`gate_7`) evaluates Moving-Block & Politis-Romano Stationary Bootstrap 95% CIs
     on cross-symbol daily Mark-to-Market (MTM) portfolio returns (`bps/day`), clustering BTC/ETH/BNB
     positions occurring in the same calendar days/blocks together.
   - IID trade-level bootstrap CI is retained strictly as a non-gating diagnostic.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import brier_score_loss
from sklearn.preprocessing import StandardScaler

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.trading.event_driven_accounting import (
    AccountingConfig,
    EventDrivenAccountingEngine,
)
from scripts.audit_and_prepare_oos_dataset import (
    audit_and_merge_symbol_candles,
    compute_path_aware_e4_trade,
)
from scripts.hmr_v5_d2_parity_replay import MODEL_DIR, RuntimeInferenceEngine

SCAFFOLD_PATH = REPO_ROOT / "research/historical_market_replay_v5/v5_causal_e4_scaffold_2023_2026.parquet"
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v5"
OUT_DIR.mkdir(parents=True, exist_ok=True)

AUDIT_TS = datetime.now(timezone.utc).isoformat()
COINS = ["BTC", "ETH", "BNB"]

PERIOD_SPLITS = {
    "EXPLORATORY_TRAIN_2023": ("2023-01-01", "2024-01-01"),
    "DEV_SELECTION_2024": ("2024-01-01", "2025-01-01"),
    "DEV_SELECTION_2025": ("2025-01-01", "2026-01-01"),
    "DEV_WALK_FORWARD_SELECTION_2024_2025": ("2024-01-01", "2026-01-01"),
    "BURNED_EXPOSED_AUDIT_2026_H1": ("2026-01-01", "2026-07-01"),
}
COST_SENSITIVITY_TIERS_BPS = [10.0, 14.0, 20.0, 30.0]


def _to_utc_ts(ts: Any) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return t.tz_convert("UTC") if t.tzinfo is not None else t.tz_localize("UTC")


def build_leak_free_fold_mask(
    df: pd.DataFrame,
    start_str: str,
    end_str: str,
) -> pd.Series:
    """Enforces half-open [start, end) on entry AND exit_timestamp < end to prevent cross-boundary leakage."""
    start_ts = pd.Timestamp(start_str, tz="UTC")
    end_ts = pd.Timestamp(end_str, tz="UTC")
    return (
        (df["entry_timestamp"] >= start_ts)
        & (df["entry_timestamp"] < end_ts)
        & (df["exit_timestamp"] < end_ts)
    )


def bootstrap_trade_returns_ci(
    returns_bps: np.ndarray,
    n_bootstraps: int = 2000,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    """Diagnostic-only IID non-parametric bootstrap CI on trade returns (ignores overlap & cross-symbol correlation)."""
    arr = np.asarray(returns_bps, dtype=float)
    if len(arr) < 5:
        m = float(np.mean(arr)) if len(arr) > 0 else 0.0
        return {
            "role": "DIAGNOSTIC_ONLY_IGNORES_OVERLAP_AND_CROSS_SYMBOL_CORRELATION",
            "used_for_promotion_gate": False,
            "mean": m,
            "ci_lower": m if len(arr) > 0 else 0.0,
            "ci_upper": m if len(arr) > 0 else 0.0,
            "n_trades": int(len(arr)),
        }
    rng = np.random.default_rng(42)
    n = len(arr)
    idx = rng.integers(0, n, size=(n_bootstraps, n))
    boot_means = arr[idx].mean(axis=1)
    alpha = (1.0 - confidence_level) / 2.0
    return {
        "role": "DIAGNOSTIC_ONLY_IGNORES_OVERLAP_AND_CROSS_SYMBOL_CORRELATION",
        "used_for_promotion_gate": False,
        "mean": float(np.mean(arr)),
        "ci_lower": float(np.percentile(boot_means, alpha * 100.0)),
        "ci_upper": float(np.percentile(boot_means, (1.0 - alpha) * 100.0)),
        "n_trades": int(n),
    }


def block_bootstrap_daily_mtm_ci(
    daily_returns: Sequence[float],
    block_size: int = 10,
    n_bootstraps: int = 2000,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    """Primary cross-symbol daily portfolio return uncertainty via Moving-Block & Stationary Bootstrap (bps/day).

    Because `daily_returns` is computed from the portfolio Mark-to-Market equity curve across all active
    symbols simultaneously on each UTC calendar day, every daily observation naturally clusters concurrent
    BTC/ETH/BNB exposures into the same date, and contiguous multi-day blocks preserve serial overlap
    (`max_hold = 2d`, `cooldown = 1d`) and volatility clustering.
    """
    rets = np.asarray(daily_returns, dtype=float) * 10000.0
    n = len(rets)
    if n < max(block_size * 2, 10) or np.allclose(rets, 0.0):
        m = float(np.mean(rets)) if n > 0 else 0.0
        return {
            "role": "PRIMARY_PORTFOLIO_TIME_BLOCK_GATE",
            "used_for_promotion_gate": True,
            "n_days": int(n),
            "block_size_days": int(block_size),
            "mean_daily_bps": m,
            "ci_lower": m if (n >= max(block_size * 2, 10) and m < 0.0) else 0.0,
            "ci_upper": m if n > 0 else 0.0,
            "moving_block_ci_lower": 0.0,
            "moving_block_ci_upper": 0.0,
            "stationary_ci_lower": 0.0,
            "stationary_ci_upper": 0.0,
        }

    alpha = (1.0 - confidence_level) / 2.0
    rng_mbb = np.random.default_rng(42)

    # 1. Circular Moving-Block Bootstrap (preserves uniform day marginal weight across boundaries)
    extended = np.concatenate([rets, rets[: block_size - 1]])
    num_blocks = int(np.ceil(n / block_size))
    starts = rng_mbb.integers(0, n, size=(n_bootstraps, num_blocks))
    offsets = np.arange(block_size)[None, None, :]
    block_idx = (starts[:, :, None] + offsets).reshape(n_bootstraps, num_blocks * block_size)[:, :n]
    mbb_means = extended[block_idx].mean(axis=1)
    mbb_lo = float(np.percentile(mbb_means, alpha * 100.0))
    mbb_hi = float(np.percentile(mbb_means, (1.0 - alpha) * 100.0))

    # 2. Politis-Romano Stationary Bootstrap (geometric random block lengths with mean = block_size)
    rng_stat = np.random.default_rng(1042)
    p_restart = 1.0 / float(block_size)
    stat_idx = np.empty((n_bootstraps, n), dtype=int)
    stat_idx[:, 0] = rng_stat.integers(0, n, size=n_bootstraps)
    restarts = rng_stat.random(size=(n_bootstraps, n - 1)) < p_restart
    random_jumps = rng_stat.integers(0, n, size=(n_bootstraps, n - 1))
    for t in range(1, n):
        stat_idx[:, t] = np.where(restarts[:, t - 1], random_jumps[:, t - 1], (stat_idx[:, t - 1] + 1) % n)
    stat_means = rets[stat_idx].mean(axis=1)
    stat_lo = float(np.percentile(stat_means, alpha * 100.0))
    stat_hi = float(np.percentile(stat_means, (1.0 - alpha) * 100.0))

    # Conservative lower bound across Moving-Block and Stationary bootstrap
    conservative_lo = min(mbb_lo, stat_lo)
    conservative_hi = max(mbb_hi, stat_hi)

    return {
        "role": "PRIMARY_PORTFOLIO_TIME_BLOCK_GATE",
        "used_for_promotion_gate": True,
        "n_days": int(n),
        "block_size_days": int(block_size),
        "mean_daily_bps": float(np.mean(rets)),
        "ci_lower": conservative_lo,
        "ci_upper": conservative_hi,
        "moving_block_ci_lower": mbb_lo,
        "moving_block_ci_upper": mbb_hi,
        "stationary_ci_lower": stat_lo,
        "stationary_ci_upper": stat_hi,
    }


def time_cluster_trade_bootstrap_ci(
    executed_trades: Sequence[Any],
    cluster_days: int = 7,
    n_bootstraps: int = 2000,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    """Time-clustered bootstrap pooling all BTC/ETH/BNB trades in the same calendar window into one cluster."""
    if len(executed_trades) < 5:
        return {
            "role": "TIME_CLUSTER_CROSS_SYMBOL_DIAGNOSTIC",
            "cluster_days": cluster_days,
            "n_clusters": 0,
            "mean_cluster_net_bps": 0.0,
            "ci_lower": 0.0,
            "ci_upper": 0.0,
        }

    records = []
    for t in executed_trades:
        ts = _to_utc_ts(t["entry_timestamp"] if isinstance(t, Mapping) else getattr(t, "entry_timestamp"))
        net_bps = float(t["net_return_bps"] if isinstance(t, Mapping) else getattr(t, "net_return_bps"))
        records.append((ts, net_bps))

    min_ts = min(r[0] for r in records).floor("D")
    cluster_buckets: dict[int, list[float]] = {}
    for ts, nbps in records:
        cid = int((ts - min_ts).total_seconds() // (cluster_days * 86400))
        cluster_buckets.setdefault(cid, []).append(nbps)

    cluster_sums = np.array([sum(v) for v in cluster_buckets.values()], dtype=float)
    cluster_counts = np.array([len(v) for v in cluster_buckets.values()], dtype=float)
    k = len(cluster_sums)
    if k < 5:
        mean_bps = float(cluster_sums.sum() / max(1.0, cluster_counts.sum()))
        return {
            "role": "TIME_CLUSTER_CROSS_SYMBOL_DIAGNOSTIC",
            "cluster_days": cluster_days,
            "n_clusters": int(k),
            "mean_cluster_net_bps": mean_bps,
            "ci_lower": mean_bps,
            "ci_upper": mean_bps,
        }

    rng = np.random.default_rng(42)
    idx = rng.integers(0, k, size=(n_bootstraps, k))
    boot_sums = cluster_sums[idx].sum(axis=1)
    boot_cnts = np.maximum(1.0, cluster_counts[idx].sum(axis=1))
    boot_means = boot_sums / boot_cnts
    alpha = (1.0 - confidence_level) / 2.0
    return {
        "role": "TIME_CLUSTER_CROSS_SYMBOL_DIAGNOSTIC",
        "cluster_days": cluster_days,
        "n_clusters": int(k),
        "mean_cluster_net_bps": float(cluster_sums.sum() / cluster_counts.sum()),
        "ci_lower": float(np.percentile(boot_means, alpha * 100.0)),
        "ci_upper": float(np.percentile(boot_means, (1.0 - alpha) * 100.0)),
    }


def compute_diversification_metrics(executed_trades: Sequence[Any]) -> dict[str, Any]:
    """Evaluates symbol and single-trade concentration to prevent 1-symbol or 1-trade flukes."""
    n = len(executed_trades)
    if n == 0:
        return {
            "active_symbols_count": 0,
            "symbol_trade_counts": {},
            "symbol_breakdown": {},
            "max_symbol_trade_share_pct": 100.0,
            "max_single_trade_profit_share_pct": 100.0,
        }

    sym_counts: dict[str, int] = {}
    sym_gross: dict[str, list[float]] = {}
    sym_net: dict[str, list[float]] = {}
    pos_pnls: list[float] = []
    for t in executed_trades:
        sym = str(t["symbol"] if isinstance(t, Mapping) else getattr(t, "symbol"))
        net_usd = float(t["net_pnl_usd"] if isinstance(t, Mapping) else getattr(t, "net_pnl_usd"))
        gross_bps = float(
            t["gross_return_fraction"] if isinstance(t, Mapping) else getattr(t, "gross_return_fraction")
        ) * 10000.0
        net_bps = float(t["net_return_bps"] if isinstance(t, Mapping) else getattr(t, "net_return_bps"))
        sym_counts[sym] = sym_counts.get(sym, 0) + 1
        sym_gross.setdefault(sym, []).append(gross_bps)
        sym_net.setdefault(sym, []).append(net_bps)
        if net_usd > 0.0:
            pos_pnls.append(net_usd)

    sym_breakdown = {
        sym: {
            "executed_n": sym_counts[sym],
            "gross_expectancy_bps": round(float(np.mean(sym_gross[sym])), 2),
            "net_expectancy_14bps": round(float(np.mean(sym_net[sym])), 2),
        }
        for sym in sorted(sym_counts)
    }
    max_sym_share = max(sym_counts.values()) / n * 100.0
    total_pos_pnl = sum(pos_pnls)
    max_trade_profit_share = (
        (max(pos_pnls) / total_pos_pnl * 100.0) if (total_pos_pnl > 1e-9 and pos_pnls) else 100.0
    )
    return {
        "active_symbols_count": len(sym_counts),
        "symbol_trade_counts": sym_counts,
        "symbol_breakdown": sym_breakdown,
        "max_symbol_trade_share_pct": round(float(max_sym_share), 2),
        "max_single_trade_profit_share_pct": round(float(max_trade_profit_share), 2),
    }


def evaluate_gates(
    result: Mapping[str, Any],
    *,
    executed_trades: Sequence[Any] | None = None,
    daily_returns: Sequence[float] | None = None,
    gross_expectancy_bps: float | None = None,
    net_expectancy_20bps: float | None = None,
    primary_daily_block_ci_lower_bps: float | None = None,
    diagnostic_trade_ci_lower_bps: float | None = None,
    fold_counts: Sequence[int] | None = None,
    block_size_days: int = 10,
) -> dict[str, Any]:
    """Evaluates statistical & economic gates using Daily Portfolio Block Bootstrap as primary Gate 7.

    Crucial invariant (P0 #3):
    - `gate_7_primary_daily_portfolio_block_ci` strictly requires `primary_daily_block_ci_lower_bps > 0.0`
      computed from cross-symbol daily portfolio returns (Moving-Block & Stationary Bootstrap).
    - IID trade-level bootstrap CI is recorded strictly as a diagnostic and CANNOT pass `gate_7`.
    """
    n_exec = int(result["executed_trades_count"])
    net_exp = float(result["expectancy_bps"])
    pf = float(result["profit_factor"])
    mdd = float(result["max_drawdown_pct"])

    if executed_trades is not None and len(executed_trades) > 0:
        gross_arr = np.array([
            float(t["gross_return_fraction"] if isinstance(t, Mapping) else getattr(t, "gross_return_fraction")) * 10000.0
            for t in executed_trades
        ])
        net_arr = np.array([
            float(t["net_return_bps"] if isinstance(t, Mapping) else getattr(t, "net_return_bps"))
            for t in executed_trades
        ])
        if gross_expectancy_bps is None:
            gross_expectancy_bps = float(np.mean(gross_arr))
        if net_expectancy_20bps is None:
            net_expectancy_20bps = float(np.mean(gross_arr - 20.0))
        if diagnostic_trade_ci_lower_bps is None:
            diagnostic_trade_ci_lower_bps = float(bootstrap_trade_returns_ci(net_arr)["ci_lower"])
        div = compute_diversification_metrics(executed_trades)
    else:
        if gross_expectancy_bps is None:
            gross_expectancy_bps = net_exp + 14.0 if n_exec > 0 else 0.0
        if net_expectancy_20bps is None:
            net_expectancy_20bps = gross_expectancy_bps - 20.0 if n_exec > 0 else 0.0
        if diagnostic_trade_ci_lower_bps is None:
            diagnostic_trade_ci_lower_bps = 0.0
        div = {
            "active_symbols_count": 0,
            "symbol_trade_counts": {},
            "max_symbol_trade_share_pct": 100.0,
            "max_single_trade_profit_share_pct": 100.0,
        }

    if primary_daily_block_ci_lower_bps is None:
        if daily_returns is not None and len(daily_returns) >= max(block_size_days * 2, 10):
            block_ci = block_bootstrap_daily_mtm_ci(daily_returns, block_size=block_size_days)
            primary_daily_block_ci_lower_bps = float(block_ci["ci_lower"])
            n_days = int(block_ci["n_days"])
        else:
            # Fail-closed when daily portfolio return series is missing or too short:
            # IID trade CI can NEVER substitute for the primary daily portfolio block CI.
            primary_daily_block_ci_lower_bps = -999.0
            n_days = len(daily_returns) if daily_returns is not None else 0
    else:
        n_days = len(daily_returns) if daily_returns is not None else 0

    g1_net14 = bool(net_exp > 0.0)
    g2_pf = bool(pf > 1.0)
    g3_mdd = bool(mdd <= 20.0)
    g4_sample = bool(n_exec >= 30)
    g5_gross = bool(gross_expectancy_bps > 0.0)
    g6_cost20 = bool(net_expectancy_20bps >= -5.0)
    g7_block_ci = bool(n_exec >= 30 and primary_daily_block_ci_lower_bps > 0.0)
    g8_div = bool(
        div["active_symbols_count"] >= 2
        and div["max_symbol_trade_share_pct"] <= 80.0
        and div["max_single_trade_profit_share_pct"] <= 50.0
    )
    g9_folds = bool(all(c > 0 for c in fold_counts)) if fold_counts is not None else bool(n_exec > 0)

    all_passed = (
        g1_net14 and g2_pf and g3_mdd and g4_sample
        and g5_gross and g6_cost20 and g7_block_ci and g8_div and g9_folds
    )

    return {
        "gate_1_positive_net_expectancy": {"passed": g1_net14, "value_bps": round(net_exp, 2), "required": "> 0.0"},
        "gate_2_profit_factor": {"passed": g2_pf, "value": round(pf, 2), "required": "> 1.0"},
        "gate_3_max_drawdown": {"passed": g3_mdd, "value_pct": round(mdd, 2), "required": "<= 20.0%"},
        "gate_4_sample_size": {"passed": g4_sample, "value_n": n_exec, "required": ">= 30"},
        "gate_5_positive_gross_expectancy": {"passed": g5_gross, "value_bps": round(float(gross_expectancy_bps), 2), "required": "> 0.0"},
        "gate_6_cost_resilience_20bps": {"passed": g6_cost20, "value_bps": round(float(net_expectancy_20bps), 2), "required": ">= -5.0"},
        "gate_7_primary_daily_portfolio_block_ci": {
            "passed": g7_block_ci,
            "primary_daily_block_ci_lower_bps": round(float(primary_daily_block_ci_lower_bps), 4),
            "diagnostic_iid_trade_ci_lower_bps": round(float(diagnostic_trade_ci_lower_bps), 2),
            "iid_trade_ci_allowed_for_promotion": False,
            "n_days": int(n_days),
            "block_size_days": int(block_size_days),
            "required": "primary_daily_block_ci_lower_bps > 0.0 (Moving-Block & Stationary 95% CI on daily portfolio returns, N >= 30)",
        },
        "gate_8_diversification": {
            "passed": g8_div,
            "active_symbols_count": div["active_symbols_count"],
            "max_symbol_trade_share_pct": div["max_symbol_trade_share_pct"],
            "max_single_trade_profit_share_pct": div["max_single_trade_profit_share_pct"],
            "required": "active_symbols >= 2, max_sym <= 80%, max_trade <= 50%",
        },
        "gate_9_no_zero_coverage_fold": {
            "passed": g9_folds,
            "fold_counts": list(fold_counts) if fold_counts is not None else [n_exec],
            "required": "all folds > 0",
        },
        "all_gates_passed": all_passed,
        "multiple_testing_trials_count": "UNKNOWN",
        "historical_ci_epistemic_status": "EXPLORATORY_PRE_PROSPECTIVE_LOCK",
        "prospective_shadow_mandatory_before_active_paper": True,
    }


def simulate_next_bar_open_barrier_trade(
    side: str,
    signal_idx: int,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    timestamps: Sequence[Any],
    *,
    max_hold: int = 192,
    tp_bps: float = 350.0,
    sl_bps: float = 150.0,
    bar_interval_minutes: int = 15,
) -> dict[str, Any]:
    """Simulates causal next-bar-open entry with SL-first collision & adverse gap-through-stop fills.

    Contract invariants:
    - Signal confirmed at close of bar `signal_idx` (`signal_timestamp = ts[signal_idx]`,
      `signal_close_timestamp = ts[signal_idx] + 15m`).
    - Entry strictly at open of `entry_idx = signal_idx + 1` (`entry_timestamp = ts[entry_idx]`,
      `entry_price = opens[entry_idx]`).
    - Never inspects `highs[entry_idx]`, `lows[entry_idx]`, or `closes[entry_idx]` to decide admission.
    - Evaluates up to `max_hold` candles starting from `entry_idx` (`entry_idx .. entry_idx + max_hold - 1`).
    - Same-candle TP & SL collision resolves conservatively as `SL` (SL-first).
    - Gap through stop at candle open fills at the adverse `opens[curr_idx]` (`SL_GAP`), never assuming
      exact stop price across a gap.
    """
    side_norm = str(side).strip().upper()
    if side_norm not in {"BUY", "SELL"}:
        raise ValueError(f"Unsupported side: {side}")
    n = len(opens)
    if not (len(highs) == n and len(lows) == n and len(closes) == n and len(timestamps) == n):
        raise ValueError("OHLC and timestamp arrays must have identical length")
    if max_hold < 1:
        raise ValueError(f"max_hold must be >= 1, got {max_hold}")
    entry_idx = int(signal_idx) + 1
    if signal_idx < 0 or entry_idx >= n:
        raise ValueError(f"signal_idx={signal_idx} has no next bar in series of length {n}")

    bar_delta = pd.Timedelta(minutes=bar_interval_minutes)
    signal_ts = _to_utc_ts(timestamps[signal_idx])
    signal_close_ts = signal_ts + bar_delta
    entry_ts = _to_utc_ts(timestamps[entry_idx])
    entry_price = float(opens[entry_idx])
    if entry_price <= 0.0 or not np.isfinite(entry_price):
        raise ValueError(f"Invalid next-bar open price at index {entry_idx}: {entry_price}")

    tp_frac = tp_bps / 10000.0
    sl_frac = sl_bps / 10000.0
    if side_norm == "BUY":
        tp_target = entry_price * (1.0 + tp_frac)
        sl_target = entry_price * (1.0 - sl_frac)
    else:
        tp_target = entry_price * (1.0 - tp_frac)
        sl_target = entry_price * (1.0 + sl_frac)

    exit_idx = entry_idx
    exit_price = entry_price
    exit_ts = entry_ts + bar_delta
    exit_reason = "TIMEOUT"
    bars_held = max_hold
    same_bar_collision = False
    gap_through_stop = False
    resolved = False

    for step in range(max_hold):
        curr_idx = entry_idx + step
        if curr_idx >= n:
            # Unresolved before end of dataset -> project exit timestamp to true horizon end (>= split end)
            # so EXCLUDE_CROSS_BOUNDARY_OUTCOME excludes incomplete end-of-series positions cleanly.
            exit_idx = n - 1
            exit_price = float(closes[exit_idx])
            remaining = max_hold - step
            exit_ts = _to_utc_ts(timestamps[exit_idx]) + bar_delta * remaining
            exit_reason = "UNRESOLVED_END_OF_SERIES"
            bars_held = step
            resolved = True
            break

        b_open = float(opens[curr_idx])
        b_high = float(highs[curr_idx])
        b_low = float(lows[curr_idx])
        b_ts = _to_utc_ts(timestamps[curr_idx])

        if side_norm == "BUY":
            if step >= 1 and b_open <= sl_target:
                exit_idx = curr_idx
                exit_price = b_open
                exit_ts = b_ts
                exit_reason = "SL_GAP"
                bars_held = step
                gap_through_stop = True
                resolved = True
                break
            if b_low <= sl_target:
                exit_idx = curr_idx
                exit_price = min(b_open, sl_target)
                exit_ts = b_ts + bar_delta
                exit_reason = "SL"
                bars_held = step + 1
                same_bar_collision = bool(b_high >= tp_target)
                resolved = True
                break
            if b_high >= tp_target:
                exit_idx = curr_idx
                exit_price = tp_target
                exit_ts = b_ts + bar_delta
                exit_reason = "TP"
                bars_held = step + 1
                resolved = True
                break
        else:
            if step >= 1 and b_open >= sl_target:
                exit_idx = curr_idx
                exit_price = b_open
                exit_ts = b_ts
                exit_reason = "SL_GAP"
                bars_held = step
                gap_through_stop = True
                resolved = True
                break
            if b_high >= sl_target:
                exit_idx = curr_idx
                exit_price = max(b_open, sl_target)
                exit_ts = b_ts + bar_delta
                exit_reason = "SL"
                bars_held = step + 1
                same_bar_collision = bool(b_low <= tp_target)
                resolved = True
                break
            if b_low <= tp_target:
                exit_idx = curr_idx
                exit_price = tp_target
                exit_ts = b_ts + bar_delta
                exit_reason = "TP"
                bars_held = step + 1
                resolved = True
                break

    if not resolved:
        exit_idx = entry_idx + max_hold - 1
        exit_price = float(closes[exit_idx])
        exit_ts = _to_utc_ts(timestamps[exit_idx]) + bar_delta
        exit_reason = "TIMEOUT"
        bars_held = max_hold

    gross_ret = (
        (exit_price - entry_price) / entry_price
        if side_norm == "BUY"
        else (entry_price - exit_price) / entry_price
    )

    return {
        "side": side_norm,
        "signal_index": int(signal_idx),
        "entry_index": int(entry_idx),
        "exit_index": int(exit_idx),
        "signal_timestamp": signal_ts,
        "signal_close_timestamp": signal_close_ts,
        "entry_timestamp": entry_ts,
        "exit_timestamp": exit_ts,
        "signal_close_price": float(closes[signal_idx]),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "bars_held": int(bars_held),
        "same_bar_collision": same_bar_collision,
        "gap_through_stop": gap_through_stop,
        "gross_return_fraction": float(gross_ret),
        "gross_pnl_bps": float(gross_ret * 10000.0),
    }


def extract_vcb_causal_signals_for_symbol(
    sym: str,
    c_df: pd.DataFrame,
    *,
    donchian_bars: int = 96,
    sma_fast_bars: int = 96,
    sma_slow_bars: int = 384,
    min_vol_ratio: float = 1.2,
    atr_bars: int = 192,
) -> list[dict[str, Any]]:
    """Extracts causal signal-bar triggers for VOL_COMPRESSION_BREAKOUT_V1 using ONLY bars <= i."""
    closes = c_df["close"].to_numpy(dtype=float)
    highs = c_df["high"].to_numpy(dtype=float)
    lows = c_df["low"].to_numpy(dtype=float)
    vols = c_df["volume"].to_numpy(dtype=float)
    ts_list = c_df["timestamp"].tolist()
    n = len(c_df)

    s_c = pd.Series(closes)
    s_h = pd.Series(highs)
    s_l = pd.Series(lows)
    s_v = pd.Series(vols)

    prev_hi = s_h.shift(1).rolling(donchian_bars).max().to_numpy()
    prev_lo = s_l.shift(1).rolling(donchian_bars).min().to_numpy()
    sma_f = s_c.rolling(sma_fast_bars).mean().to_numpy()
    sma_s = s_c.rolling(sma_slow_bars).mean().to_numpy()
    vol_ma = s_v.shift(1).rolling(donchian_bars).mean().to_numpy()

    tr = pd.concat(
        [s_h - s_l, (s_h - s_c.shift(1)).abs(), (s_l - s_c.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    atr_arr = tr.shift(1).rolling(atr_bars).mean().to_numpy()

    signals: list[dict[str, Any]] = []
    start_idx = max(sma_slow_bars + 2, atr_bars + 2, donchian_bars + 2)
    for i in range(start_idx, n - 1):
        if (
            np.isnan(prev_hi[i])
            or np.isnan(sma_s[i])
            or np.isnan(vol_ma[i])
            or vol_ma[i] <= 0.0
            or np.isnan(atr_arr[i])
            or atr_arr[i] <= 0.0
        ):
            continue

        vol_ratio = float(vols[i] / vol_ma[i])
        if vol_ratio < min_vol_ratio:
            continue

        side = None
        if closes[i] > prev_hi[i] and closes[i] > sma_s[i] and sma_f[i] > sma_s[i]:
            side = "BUY"
        elif closes[i] < prev_lo[i] and closes[i] < sma_s[i] and sma_f[i] < sma_s[i]:
            side = "SELL"
        if side is None:
            continue

        atr_bps = float(atr_arr[i] / closes[i] * 10000.0)
        signals.append({
            "symbol": sym,
            "signal_index": int(i),
            "signal_timestamp": _to_utc_ts(ts_list[i]),
            "side": side,
            "signal_close": float(closes[i]),
            "donchian_prev_high": float(prev_hi[i]),
            "donchian_prev_low": float(prev_lo[i]),
            "sma_fast": float(sma_f[i]),
            "sma_slow": float(sma_s[i]),
            "vol_ratio": vol_ratio,
            "atr_bps": atr_bps,
        })
    return signals


def _apply_fold_q65_filter(df_raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    """Fits ATR Q65 thresholds strictly inside each leak-free training window (exit_timestamp < fold_end)."""
    df = df_raw.copy()
    df["entry_timestamp"] = pd.to_datetime(df["entry_timestamp"], utc=True)
    df["exit_timestamp"] = pd.to_datetime(df["exit_timestamp"], utc=True)

    tr_f1 = build_leak_free_fold_mask(df, "2023-01-01", "2024-01-01")
    tr_f2 = build_leak_free_fold_mask(df, "2023-01-01", "2025-01-01")
    tr_audit = build_leak_free_fold_mask(df, "2023-01-01", "2026-01-01")

    q65_f1 = float(df.loc[tr_f1, "atr_bps"].quantile(0.65))
    q65_f2 = float(df.loc[tr_f2, "atr_bps"].quantile(0.65))
    q65_audit = float(df.loc[tr_audit, "atr_bps"].quantile(0.65))

    m_23 = (df["entry_timestamp"] >= "2023-01-01") & (df["entry_timestamp"] < "2024-01-01")
    m_24 = (df["entry_timestamp"] >= "2024-01-01") & (df["entry_timestamp"] < "2025-01-01")
    m_25 = (df["entry_timestamp"] >= "2025-01-01") & (df["entry_timestamp"] < "2026-01-01")
    m_26 = (df["entry_timestamp"] >= "2026-01-01") & (df["entry_timestamp"] < "2026-07-01")

    vcb_pass = np.zeros(len(df), dtype=bool)
    vcb_pass[m_23] = df.loc[m_23, "atr_bps"].to_numpy() <= q65_f1
    vcb_pass[m_24] = df.loc[m_24, "atr_bps"].to_numpy() <= q65_f1
    vcb_pass[m_25] = df.loc[m_25, "atr_bps"].to_numpy() <= q65_f2
    vcb_pass[m_26] = df.loc[m_26, "atr_bps"].to_numpy() <= q65_audit
    df["vcb_pass"] = vcb_pass

    thresholds = {
        "fold_1_train_2023_applied_to_2024": round(q65_f1, 3),
        "fold_2_train_2023_2024_applied_to_2025": round(q65_f2, 3),
        "audit_train_2023_2025_applied_to_2026": round(q65_audit, 3),
    }
    return df[df["vcb_pass"]].copy(), thresholds


def build_locked_vol_compression_breakout_stream(
    symbol_candles: Mapping[str, pd.DataFrame] | None = None,
    *,
    include_retracted_same_close_diagnostic: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]] | tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    """Builds causal VOL_COMPRESSION_BREAKOUT_V1 candidate stream using strict NEXT_BAR_OPEN execution."""
    next_open_rows: list[dict[str, Any]] = []
    retracted_same_close_rows: list[dict[str, Any]] = []
    max_hold = 192

    for sym in COINS:
        c_df = symbol_candles[sym] if symbol_candles is not None else audit_and_merge_symbol_candles(sym)[0]
        opens = c_df["open"].to_numpy(dtype=float)
        highs = c_df["high"].to_numpy(dtype=float)
        lows = c_df["low"].to_numpy(dtype=float)
        closes = c_df["close"].to_numpy(dtype=float)
        ts_list = c_df["timestamp"].tolist()
        n = len(c_df)

        signals = extract_vcb_causal_signals_for_symbol(sym, c_df)
        for sig in signals:
            i = sig["signal_index"]
            side = sig["side"]
            sim = simulate_next_bar_open_barrier_trade(
                side,
                i,
                opens,
                highs,
                lows,
                closes,
                ts_list,
                max_hold=max_hold,
                tp_bps=350.0,
                sl_bps=150.0,
            )
            next_open_rows.append({
                "trade_id": f"VCB_NEXTOPEN_{sym}_{i}_{side}",
                "symbol": sym,
                "side": side,
                "signal_index": sim["signal_index"],
                "entry_index": sim["entry_index"],
                "exit_index": sim["exit_index"],
                "signal_timestamp": sim["signal_timestamp"],
                "signal_close_timestamp": sim["signal_close_timestamp"],
                "entry_timestamp": sim["entry_timestamp"],
                "exit_timestamp": sim["exit_timestamp"],
                "signal_close_price": sim["signal_close_price"],
                "entry_price": sim["entry_price"],
                "exit_price": sim["exit_price"],
                "exit_reason": sim["exit_reason"],
                "bars_held": sim["bars_held"],
                "same_bar_collision": sim["same_bar_collision"],
                "gap_through_stop": sim["gap_through_stop"],
                "gross_return_fraction": sim["gross_return_fraction"],
                "gross_pnl_bps": sim["gross_pnl_bps"],
                "atr_bps": sig["atr_bps"],
                "vol_ratio": sig["vol_ratio"],
                "source_contract_version": "vcb-v1-next-bar-open",
            })

            if include_retracted_same_close_diagnostic and i < n - max_hold:
                ret_sc, ep_sc, xp_sc, stop_sc, target_sc, bars_sc, exit_i_sc = compute_path_aware_e4_trade(
                    side, i, closes, highs, lows, max_hold=max_hold, tp_bps=350.0, sl_bps=150.0
                )
                retracted_same_close_rows.append({
                    "trade_id": f"VCB_RETRACTED_SAMECLOSE_{sym}_{i}_{side}",
                    "symbol": sym,
                    "side": side,
                    "entry_timestamp": ts_list[i],
                    "exit_timestamp": ts_list[exit_i_sc],
                    "entry_price": ep_sc,
                    "exit_price": xp_sc,
                    "exit_reason": "TP" if target_sc else ("SL" if stop_sc else "TIMEOUT"),
                    "bars_held": bars_sc,
                    "gross_return_fraction": ret_sc,
                    "gross_pnl_bps": ret_sc * 10000.0,
                    "atr_bps": sig["atr_bps"],
                    "source_contract_version": "retracted-same-close-diagnostic",
                })

    df_vcb_filtered, q65_thresholds = _apply_fold_q65_filter(pd.DataFrame(next_open_rows))

    spec_payload = {
        "candidate_id": "VOL_COMPRESSION_BREAKOUT_V1",
        "spec_version": "1.1.0-next-bar-open",
        "execution_timing_contract": {
            "signal_confirmation": "bar_i_close (signal_close_timestamp = signal_timestamp + 15m)",
            "earliest_entry": "bar_i_plus_1_open (entry_index = signal_index + 1, entry_price = opens[i+1])",
            "future_bar_admission_leakage": False,
            "intrabar_tp_sl_collision_policy": "SL_FIRST_CONSERVATIVE",
            "gap_through_stop_policy": "ADVERSE_OPEN_PRICE_FILL (SL_GAP)",
            "max_hold_anchor": "entry_index (entry_index .. entry_index + max_hold - 1)",
        },
        "parameters": {
            "universe": COINS,
            "donchian_bars": 96,
            "sma_fast_bars": 96,
            "sma_slow_bars": 384,
            "min_vol_ratio_96": 1.2,
            "atr_compression_bars": 192,
            "atr_compression_quantile": 0.65,
            "tp_bps": 350.0,
            "sl_bps": 150.0,
            "max_hold_bars": 192,
        },
    }
    spec_sha256 = hashlib.sha256(
        json.dumps(spec_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    vcb_meta = {
        **spec_payload,
        "spec_sha256": spec_sha256,
        "split_governance": {
            "exploratory_discovery_split": "EXPLORATORY_TRAIN_2023 [2023-01-01, 2024-01-01)",
            "development_selection_split": "DEV_WALK_FORWARD_SELECTION_2024_2025 [2024-01-01, 2026-01-01)",
            "is_2024_2025_independent_confirmatory_oos": False,
            "exposed_one_shot_audit_split": "BURNED_EXPOSED_AUDIT_2026_H1 [2026-01-01, 2026-07-01)",
            "audit_2026_status": "BURNED_FAILED_ONE_SHOT_AUDIT_NEVER_REUSED_FOR_TUNING",
            "audit_2026_used_in_design_or_selection": False,
            "multiple_testing_trials_count": "UNKNOWN",
            "historical_ci_epistemic_status": (
                "EXPLORATORY_ONLY — candidate family, symbol set, and barrier scale were selected across "
                "2023 discovery and 2024-2025 development folds without a pre-registered exhaustive trial counter."
            ),
        },
        "fold_fitted_atr_q65_thresholds_bps": q65_thresholds,
        "next_bar_open_diagnostics": {
            "total_filtered_signals": int(len(df_vcb_filtered)),
            "gap_through_stop_count": int(df_vcb_filtered["gap_through_stop"].sum()),
            "same_bar_collision_count": int(df_vcb_filtered["same_bar_collision"].sum()),
            "entry_bar_immediate_exit_count": int((df_vcb_filtered["exit_index"] == df_vcb_filtered["entry_index"]).sum()),
        },
    }

    if include_retracted_same_close_diagnostic:
        df_sc_filtered, _ = _apply_fold_q65_filter(pd.DataFrame(retracted_same_close_rows))
        return df_vcb_filtered, vcb_meta, df_sc_filtered
    return df_vcb_filtered, vcb_meta


def _build_hourly_mtm_candles(
    symbol_candles_15m: Mapping[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Builds exact 1h mark-to-market close grids from verified 15m candles for cross-symbol MTM daily returns."""
    hourly: dict[str, pd.DataFrame] = {}
    for sym, c_df in symbol_candles_15m.items():
        s = c_df.set_index("timestamp")["close"].resample("1h").last().dropna()
        hourly[sym] = pd.DataFrame({"timestamp": s.index, "close": s.to_numpy(dtype=float)})
    return hourly


def _slice_candle_map(
    candle_map: Mapping[str, pd.DataFrame],
    start_d: str,
    end_d: str,
) -> dict[str, pd.DataFrame]:
    start_ts = pd.Timestamp(start_d, tz="UTC")
    end_ts = pd.Timestamp(end_d, tz="UTC")
    return {
        sym: df[(df["timestamp"] >= start_ts) & (df["timestamp"] < end_ts)]
        for sym, df in candle_map.items()
    }


def _evaluate_candidate_across_periods(
    cand_name: str,
    cand_df: pd.DataFrame,
    acct: EventDrivenAccountingEngine,
    hourly_candles: Mapping[str, pd.DataFrame],
) -> dict[str, Any]:
    periods_out: dict[str, Any] = {}
    for period_name, (start_d, end_d) in PERIOD_SPLITS.items():
        start_ts = pd.Timestamp(start_d, tz="UTC")
        end_ts = pd.Timestamp(end_d, tz="UTC")
        sub_mask = (cand_df["entry_timestamp"] >= start_ts) & (cand_df["entry_timestamp"] < end_ts)
        period_trades = cand_df[sub_mask].to_dict("records")
        period_signal_count = len(period_trades)
        period_candles = _slice_candle_map(hourly_candles, start_d, end_d)

        if cand_name == "NO_TRADE" or period_signal_count == 0:
            sim_res = acct.run(
                [],
                date_range=(start_d, end_d),
                cross_boundary_policy="EXCLUDE_CROSS_BOUNDARY_OUTCOME",
            )
            sim_metrics = sim_res.to_dict()
            executed_trades = []
            executed_returns_bps = np.array([])
            gross_bps_arr = np.array([])
            daily_rets = sim_res.daily_returns
            cost_sens = {
                str(c): {"expectancy_bps": 0.0, "win_rate_pct": 0.0, "profit_factor": 0.0}
                for c in COST_SENSITIVITY_TIERS_BPS
            }
        else:
            sim_res = acct.run(
                period_trades,
                date_range=(start_d, end_d),
                candle_data=period_candles,
                cross_boundary_policy="EXCLUDE_CROSS_BOUNDARY_OUTCOME",
            )
            sim_metrics = sim_res.to_dict()
            executed_trades = sim_res.executed_trades
            executed_returns_bps = np.array([t.net_return_bps for t in executed_trades], dtype=float)
            gross_bps_arr = np.array([t.gross_return_fraction * 10000.0 for t in executed_trades], dtype=float)
            daily_rets = sim_res.daily_returns

            cost_sens = {}
            for c_bps in COST_SENSITIVITY_TIERS_BPS:
                if len(gross_bps_arr) > 0:
                    net_arr = gross_bps_arr - c_bps
                    c_exp = float(np.mean(net_arr))
                    c_wr = float(np.mean(net_arr > 0) * 100.0)
                    pos = net_arr[net_arr > 0]
                    neg = net_arr[net_arr < 0]
                    if len(neg) > 0 and abs(np.sum(neg)) > 0:
                        c_pf: Any = round(float(np.sum(pos) / abs(np.sum(neg))), 2)
                    elif len(pos) > 0:
                        c_pf = "INF_UNDEFINED_SMALL_SAMPLE"
                    else:
                        c_pf = 0.0
                else:
                    c_exp, c_wr, c_pf = 0.0, 0.0, 0.0
                cost_sens[str(c_bps)] = {
                    "expectancy_bps": round(c_exp, 2),
                    "win_rate_pct": round(c_wr, 1),
                    "profit_factor": c_pf,
                }

        gross_exp_bps = round(float(np.mean(gross_bps_arr)), 2) if len(gross_bps_arr) > 0 else 0.0
        sim_metrics["candidate_signals_in_window"] = int(period_signal_count)
        sim_metrics["gross_expectancy_bps"] = gross_exp_bps

        trade_ci = bootstrap_trade_returns_ci(executed_returns_bps)
        gross_ci = bootstrap_trade_returns_ci(gross_bps_arr)
        block_ci = block_bootstrap_daily_mtm_ci(daily_rets, block_size=10)
        cluster_ci = time_cluster_trade_bootstrap_ci(executed_trades, cluster_days=7)
        div_metrics = compute_diversification_metrics(executed_trades)

        fold_counts = None
        if period_name == "DEV_WALK_FORWARD_SELECTION_2024_2025":
            n_24 = periods_out["DEV_SELECTION_2024"]["metrics"]["executed_trades_count"]
            n_25 = periods_out["DEV_SELECTION_2025"]["metrics"]["executed_trades_count"]
            fold_counts = [n_24, n_25]

        gates = evaluate_gates(
            sim_metrics,
            executed_trades=executed_trades,
            daily_returns=daily_rets,
            gross_expectancy_bps=gross_exp_bps,
            net_expectancy_20bps=float(cost_sens["20.0"]["expectancy_bps"]),
            primary_daily_block_ci_lower_bps=float(block_ci["ci_lower"]),
            diagnostic_trade_ci_lower_bps=float(trade_ci["ci_lower"]),
            fold_counts=fold_counts,
            block_size_days=10,
        )

        periods_out[period_name] = {
            "metrics": sim_metrics,
            "diversification": div_metrics,
            "gates": gates,
            "primary_daily_portfolio_block_bootstrap_ci_bps": block_ci,
            "time_cluster_7d_bootstrap_ci_bps": cluster_ci,
            "diagnostic_iid_bootstrap_ci_trade_gross_bps": gross_ci,
            "diagnostic_iid_bootstrap_ci_trade_net_bps": trade_ci,
            "cost_sensitivity": cost_sens,
        }
    return periods_out


def main() -> None:
    print("=== HMR-V5 v2: Causal Next-Bar-Open & Time-Block Portfolio Gate Evaluation ===")
    print(f"Timestamp: {AUDIT_TS}\n")

    print(f"Loading verified E4 scaffold from {SCAFFOLD_PATH}...")
    df_scaffold = pd.read_parquet(SCAFFOLD_PATH)
    df_scaffold["entry_timestamp"] = pd.to_datetime(df_scaffold["entry_timestamp"], utc=True)
    df_scaffold["exit_timestamp"] = pd.to_datetime(df_scaffold["exit_timestamp"], utc=True)
    total_trades = len(df_scaffold)
    print(f"Loaded {total_trades:,} E4 candidate trades across {df_scaffold['symbol'].unique()}.\n")

    print("Loading verified 15m candles for BTC, ETH, BNB and building 1h MTM grid...")
    symbol_candles_15m = {sym: audit_and_merge_symbol_candles(sym)[0] for sym in COINS}
    hourly_mtm_candles = _build_hourly_mtm_candles(symbol_candles_15m)

    # 1. Evaluate S3 Legacy Model Probabilities (Diagnostic Comparison)
    print("Evaluating S3 Legacy model inference on E4 trades...")
    s3_engine = RuntimeInferenceEngine(MODEL_DIR)
    s3_X_cols = ["return_8", "return_32", "return_72", "abs_move_72"]
    s3_probs = []
    s3_passes = []
    for _, row in df_scaffold[["symbol"] + s3_X_cols].iterrows():
        prob, dec = s3_engine.predict_score_and_decision(row["symbol"], [row[c] for c in s3_X_cols])
        s3_probs.append(prob)
        s3_passes.append(bool(dec))

    df_scaffold["s3_prob"] = s3_probs
    df_scaffold["s3_pass"] = s3_passes

    # 2. Leak-Free Walk-Forward Modeling for NET_RETURN_RANKER
    print("Running Leak-Free Walk-Forward Estimation for NET_RETURN_RANKER...")
    ranker_features = ["return_8", "return_32", "return_72", "abs_move_72", "trend_spread"]
    y_all_net14 = df_scaffold["gross_return_fraction"].to_numpy(dtype=float) * 10000.0 - 14.0

    tr_mask_f1 = build_leak_free_fold_mask(df_scaffold, "2023-01-01", "2024-01-01")
    tr_mask_f2 = build_leak_free_fold_mask(df_scaffold, "2023-01-01", "2025-01-01")
    tr_mask_2026 = build_leak_free_fold_mask(df_scaffold, "2023-01-01", "2026-01-01")

    eval_2023 = (df_scaffold["entry_timestamp"] >= "2023-01-01") & (df_scaffold["entry_timestamp"] < "2024-01-01")
    eval_2024 = (df_scaffold["entry_timestamp"] >= "2024-01-01") & (df_scaffold["entry_timestamp"] < "2025-01-01")
    eval_2025 = (df_scaffold["entry_timestamp"] >= "2025-01-01") & (df_scaffold["entry_timestamp"] < "2026-01-01")
    eval_2026 = (df_scaffold["entry_timestamp"] >= "2026-01-01") & (df_scaffold["entry_timestamp"] < "2026-07-01")

    pred_net_returns = np.zeros(len(df_scaffold), dtype=float)
    pred_win_probs = np.zeros(len(df_scaffold), dtype=float)

    scaler_f1 = StandardScaler()
    X_tr_f1 = scaler_f1.fit_transform(df_scaffold.loc[tr_mask_f1, ranker_features].fillna(0.0))
    y_tr_f1 = y_all_net14[tr_mask_f1]
    ridge_f1 = Ridge(alpha=100.0).fit(X_tr_f1, y_tr_f1)
    logit_f1 = LogisticRegression(C=0.1, max_iter=500).fit(X_tr_f1, (y_tr_f1 > 0).astype(int))

    X_eval_23 = scaler_f1.transform(df_scaffold.loc[eval_2023, ranker_features].fillna(0.0))
    pred_net_returns[eval_2023] = ridge_f1.predict(X_eval_23)
    pred_win_probs[eval_2023] = logit_f1.predict_proba(X_eval_23)[:, 1]

    X_val_f1 = scaler_f1.transform(df_scaffold.loc[eval_2024, ranker_features].fillna(0.0))
    pred_net_returns[eval_2024] = ridge_f1.predict(X_val_f1)
    pred_win_probs[eval_2024] = logit_f1.predict_proba(X_val_f1)[:, 1]

    scaler_f2 = StandardScaler()
    X_tr_f2 = scaler_f2.fit_transform(df_scaffold.loc[tr_mask_f2, ranker_features].fillna(0.0))
    y_tr_f2 = y_all_net14[tr_mask_f2]
    ridge_f2 = Ridge(alpha=100.0).fit(X_tr_f2, y_tr_f2)
    logit_f2 = LogisticRegression(C=0.1, max_iter=500).fit(X_tr_f2, (y_tr_f2 > 0).astype(int))

    X_val_f2 = scaler_f2.transform(df_scaffold.loc[eval_2025, ranker_features].fillna(0.0))
    pred_net_returns[eval_2025] = ridge_f2.predict(X_val_f2)
    pred_win_probs[eval_2025] = logit_f2.predict_proba(X_val_f2)[:, 1]

    scaler_2026 = StandardScaler()
    X_tr_2026 = scaler_2026.fit_transform(df_scaffold.loc[tr_mask_2026, ranker_features].fillna(0.0))
    y_tr_2026 = y_all_net14[tr_mask_2026]
    ridge_2026 = Ridge(alpha=100.0).fit(X_tr_2026, y_tr_2026)
    logit_2026 = LogisticRegression(C=0.1, max_iter=500).fit(X_tr_2026, (y_tr_2026 > 0).astype(int))

    X_val_2026 = scaler_2026.transform(df_scaffold.loc[eval_2026, ranker_features].fillna(0.0))
    pred_net_returns[eval_2026] = ridge_2026.predict(X_val_2026)
    pred_win_probs[eval_2026] = logit_2026.predict_proba(X_val_2026)[:, 1]

    df_scaffold["pred_net_return_bps"] = pred_net_returns
    df_scaffold["pred_win_prob"] = pred_win_probs

    mask_dev_clean = build_leak_free_fold_mask(df_scaffold, "2024-01-01", "2026-01-01")
    y_dev_true = y_all_net14[mask_dev_clean]
    dev_brier = float(brier_score_loss((y_dev_true > 0).astype(int), pred_win_probs[mask_dev_clean]))
    dev_spearman, _ = stats.spearmanr(pred_net_returns[mask_dev_clean], y_dev_true)

    positive_ev_floor_bps = 0.0
    raw_p80_hurdle_f1 = float(np.percentile(ridge_f1.predict(X_tr_f1), 80))
    effective_hurdle_f1 = max(raw_p80_hurdle_f1, positive_ev_floor_bps)
    raw_p80_hurdle_f2 = float(np.percentile(ridge_f2.predict(X_tr_f2), 80))
    effective_hurdle_f2 = max(raw_p80_hurdle_f2, positive_ev_floor_bps)
    raw_p80_hurdle_2026 = float(np.percentile(ridge_2026.predict(X_tr_2026), 80))
    effective_hurdle_2026 = max(raw_p80_hurdle_2026, positive_ev_floor_bps)

    net_ranker_pass = np.zeros(len(df_scaffold), dtype=bool)
    net_ranker_pass[eval_2023] = pred_net_returns[eval_2023] >= effective_hurdle_f1
    net_ranker_pass[eval_2024] = pred_net_returns[eval_2024] >= effective_hurdle_f1
    net_ranker_pass[eval_2025] = pred_net_returns[eval_2025] >= effective_hurdle_f2
    net_ranker_pass[eval_2026] = pred_net_returns[eval_2026] >= effective_hurdle_2026
    df_scaffold["net_ranker_pass"] = net_ranker_pass

    # 3. Build Causal Next-Bar-Open Candidate (plus retracted same-close baseline solely for before/after audit)
    print("Building VOL_COMPRESSION_BREAKOUT_V1 with strict NEXT_BAR_OPEN execution & gap-aware stops...")
    df_vcb, vcb_meta, df_vcb_retracted_sc = build_locked_vol_compression_breakout_stream(
        symbol_candles_15m,
        include_retracted_same_close_diagnostic=True,
    )
    print(f"VOL_COMPRESSION_BREAKOUT_V1 next-bar-open signals generated: {len(df_vcb):,}\n")

    acct_config = AccountingConfig(
        initial_capital=10000.0,
        max_concurrent_positions=3,
        max_positions_per_asset=1,
        cooldown_bars=96,
        bar_interval_minutes=15,
        allocation_pct_per_trade=0.25,
        fee_rate_bps=5.0,
        slippage_bps=2.0,
    )
    acct = EventDrivenAccountingEngine(acct_config)

    candidate_specs = {
        "NO_TRADE": {
            "type": "BASELINE_ABSTENTION",
            "source_df": df_scaffold.iloc[0:0],
            "description": "Baseline abstention (zero orders, zero risk, preserves capital)",
        },
        "CONTROL": {
            "type": "PASSIVE_BASELINE",
            "source_df": df_scaffold,
            "description": "Raw unguided E4 trend-spread candidates (TP=50, SL=30, H=96)",
        },
        "S3_LEGACY": {
            "type": "OUT_OF_DOMAIN_DIAGNOSTIC",
            "source_df": df_scaffold[df_scaffold["s3_pass"] == True],
            "description": "Legacy S3 filter evaluated out-of-domain on E4 trend-spread stream",
        },
        "NET_RETURN_RANKER": {
            "type": "COST_AWARE_RANKER_E4",
            "source_df": df_scaffold[df_scaffold["net_ranker_pass"] == True],
            "description": "Cost-aware walk-forward Ridge ranker on narrow E4 stream (collapses to tiny N)",
        },
        "VOL_COMPRESSION_BREAKOUT_V1": {
            "type": "EXPLORATORY_DEV_DIRECTIONAL_CANDIDATE_NEXT_BAR_OPEN",
            "source_df": df_vcb,
            "description": (
                "Causal bar-i close signal -> bar-(i+1) open fill + gap-aware SL + SL-first barriers "
                "(24h Donchian + SMA_96/384 + vol>=1.2x + fold-fitted ATR_192<=Q65, TP=350, SL=150, H=192)"
            ),
        },
    }

    evaluation_results: dict[str, Any] = {
        "evaluation_timestamp": AUDIT_TS,
        "scaffold_path": str(SCAFFOLD_PATH),
        "total_scaffold_trades": total_trades,
        "interval_and_boundary_contract": {
            "interval_semantics": "half_open_[start,end)",
            "cross_boundary_policy": "EXCLUDE_CROSS_BOUNDARY_OUTCOME",
            "training_fold_outcome_guard": "entry_timestamp < fold_end AND exit_timestamp < fold_end",
        },
        "split_and_multiple_testing_governance": {
            "EXPLORATORY_TRAIN_2023": "Exploratory discovery & fold-1 training [2023-01-01, 2024-01-01)",
            "DEV_WALK_FORWARD_SELECTION_2024_2025": (
                "Development selection / walk-forward development evidence [2024-01-01, 2026-01-01) — "
                "participated in candidate/barrier/universe selection; NOT independent confirmatory OOS."
            ),
            "BURNED_EXPOSED_AUDIT_2026_H1": (
                "Exposed one-shot audit [2026-01-01, 2026-07-01) — failed and permanently burned; "
                "never reusable for parameter tuning or candidate selection."
            ),
            "multiple_testing_trials_count": "UNKNOWN",
            "ci_interpretation_warning": (
                "Because the exact count of informal feature/barrier hypotheses explored prior to lock is "
                "UNKNOWN, all historical confidence intervals prior to prospective shadow lock are exploratory "
                "and unadjusted for selection bias."
            ),
            "primary_statistical_gate": (
                "Moving-Block & Politis-Romano Stationary Bootstrap (block_size=10d) on cross-symbol daily "
                "MTM portfolio returns; IID trade-level bootstrap is strictly diagnostic and cannot pass promotion."
            ),
        },
        "walk_forward_metrics": {
            "dev_brier_score": dev_brier,
            "dev_spearman_rank_correlation": float(dev_spearman),
            "positive_ev_floor_bps": positive_ev_floor_bps,
            "fold_1": {
                "raw_p80_hurdle_bps": raw_p80_hurdle_f1,
                "effective_hurdle_bps": effective_hurdle_f1,
                "excluded_cross_boundary_train_rows": int(
                    ((df_scaffold["entry_timestamp"] >= "2023-01-01") & (df_scaffold["entry_timestamp"] < "2024-01-01") & (df_scaffold["exit_timestamp"] >= "2024-01-01")).sum()
                ),
            },
            "fold_2": {
                "raw_p80_hurdle_bps": raw_p80_hurdle_f2,
                "effective_hurdle_bps": effective_hurdle_f2,
                "excluded_cross_boundary_train_rows": int(
                    ((df_scaffold["entry_timestamp"] >= "2023-01-01") & (df_scaffold["entry_timestamp"] < "2025-01-01") & (df_scaffold["exit_timestamp"] >= "2025-01-01")).sum()
                ),
            },
            "audit_set_2026": {
                "raw_p80_hurdle_bps": raw_p80_hurdle_2026,
                "effective_hurdle_bps": effective_hurdle_2026,
                "excluded_cross_boundary_train_rows": int(
                    ((df_scaffold["entry_timestamp"] >= "2023-01-01") & (df_scaffold["entry_timestamp"] < "2026-01-01") & (df_scaffold["exit_timestamp"] >= "2026-01-01")).sum()
                ),
            },
            "vol_compression_breakout_v1_governance": vcb_meta,
        },
        "candidates": {},
    }

    for cand_name, spec in candidate_specs.items():
        print(f"=== Replaying Candidate: {cand_name} ({spec['type']}) ===")
        periods_out = _evaluate_candidate_across_periods(
            cand_name,
            spec["source_df"],
            acct,
            hourly_mtm_candles,
        )
        evaluation_results["candidates"][cand_name] = {
            "classification": spec["type"],
            "description": spec["description"],
            "periods": periods_out,
        }
        for period_name, p_entry in periods_out.items():
            m = p_entry["metrics"]
            bci = p_entry["primary_daily_portfolio_block_bootstrap_ci_bps"]
            tci = p_entry["diagnostic_iid_bootstrap_ci_trade_net_bps"]
            print(
                f"  [{period_name}] Sig={m['candidate_signals_in_window']} Exec={m['executed_trades_count']} "
                f"Rej={m['rejected_capacity_count']} ExclCross={m['excluded_cross_boundary_count']} | "
                f"Gross={m['gross_expectancy_bps']:+.2f} | Net14={m['expectancy_bps']:+.2f} | "
                f"Net20={p_entry['cost_sensitivity']['20.0']['expectancy_bps']:+.2f} | "
                f"PF={m['profit_factor']:.2f} | MDD={m['max_drawdown_pct']:.2f}% | "
                f"BlockCI=[{bci['ci_lower']:+.2f},{bci['ci_upper']:+.2f}] bps/d | "
                f"DiagTradeCI=[{tci['ci_lower']:+.1f},{tci['ci_upper']:+.1f}] | "
                f"Gates={p_entry['gates']['all_gates_passed']}"
            )

    # 4. Compute Retracted Same-Close vs Corrected Next-Bar-Open Reconciliation for V1
    print("\n=== Computing Retracted Same-Close vs Corrected Next-Bar-Open Reconciliation ===")
    retracted_sc_periods = _evaluate_candidate_across_periods(
        "RETRACTED_SAME_CLOSE_V1_DIAGNOSTIC",
        df_vcb_retracted_sc,
        acct,
        hourly_mtm_candles,
    )
    timing_reconciliation: dict[str, Any] = {}
    for pk in PERIOD_SPLITS:
        old_p = retracted_sc_periods[pk]
        new_p = evaluation_results["candidates"]["VOL_COMPRESSION_BREAKOUT_V1"]["periods"][pk]
        timing_reconciliation[pk] = {
            "retracted_same_close": {
                "signals": old_p["metrics"]["candidate_signals_in_window"],
                "executed_n": old_p["metrics"]["executed_trades_count"],
                "rejected_capacity_n": old_p["metrics"]["rejected_capacity_count"],
                "excluded_cross_boundary_n": old_p["metrics"]["excluded_cross_boundary_count"],
                "gross_expectancy_bps": old_p["metrics"]["gross_expectancy_bps"],
                "net_expectancy_14bps": old_p["metrics"]["expectancy_bps"],
                "profit_factor": old_p["metrics"]["profit_factor"],
                "max_drawdown_pct": old_p["metrics"]["max_drawdown_pct"],
                "cost_sensitivity": old_p["cost_sensitivity"],
                "primary_daily_block_ci_bps": old_p["primary_daily_portfolio_block_bootstrap_ci_bps"],
                "diagnostic_iid_trade_ci_bps": old_p["diagnostic_iid_bootstrap_ci_trade_net_bps"],
                "symbol_breakdown": old_p["diversification"]["symbol_breakdown"],
            },
            "corrected_next_bar_open": {
                "signals": new_p["metrics"]["candidate_signals_in_window"],
                "executed_n": new_p["metrics"]["executed_trades_count"],
                "rejected_capacity_n": new_p["metrics"]["rejected_capacity_count"],
                "excluded_cross_boundary_n": new_p["metrics"]["excluded_cross_boundary_count"],
                "gross_expectancy_bps": new_p["metrics"]["gross_expectancy_bps"],
                "net_expectancy_14bps": new_p["metrics"]["expectancy_bps"],
                "profit_factor": new_p["metrics"]["profit_factor"],
                "max_drawdown_pct": new_p["metrics"]["max_drawdown_pct"],
                "cost_sensitivity": new_p["cost_sensitivity"],
                "primary_daily_block_ci_bps": new_p["primary_daily_portfolio_block_bootstrap_ci_bps"],
                "diagnostic_iid_trade_ci_bps": new_p["diagnostic_iid_bootstrap_ci_trade_net_bps"],
                "symbol_breakdown": new_p["diversification"]["symbol_breakdown"],
            },
        }
    evaluation_results["vcb_v1_execution_timing_reconciliation"] = timing_reconciliation

    # 5. Honest System Disposition (2024-2025 = Development Selection, 2026-H1 = Burned One-Shot Audit)
    print("\n=== SYSTEM DISPOSITION (DEV SELECTION 2024-2025 + BURNED 2026-H1 AUDIT) ===")
    dev_period = "DEV_WALK_FORWARD_SELECTION_2024_2025"
    audit_period = "BURNED_EXPOSED_AUDIT_2026_H1"
    promotion_verdicts: dict[str, Any] = {}

    for cand_name, spec in candidate_specs.items():
        dev_data = evaluation_results["candidates"][cand_name]["periods"][dev_period]
        audit_data = evaluation_results["candidates"][cand_name]["periods"][audit_period]
        dev_passed = bool(dev_data["gates"]["all_gates_passed"])
        audit_passed = bool(audit_data["gates"]["all_gates_passed"])
        dev_gross = float(dev_data["metrics"]["gross_expectancy_bps"])
        dev_net14 = float(dev_data["metrics"]["expectancy_bps"])

        if cand_name == "NO_TRADE":
            verdict = "BASELINE_ABSTENTION"
        elif cand_name == "CONTROL":
            verdict = "REJECTED_NEGATIVE_EXPECTANCY"
        elif cand_name == "S3_LEGACY":
            verdict = "OUT_OF_DOMAIN_DIAGNOSTIC_REJECTED"
        elif cand_name == "NET_RETURN_RANKER":
            verdict = "REJECTED_INSUFFICIENT_SAMPLE_AND_ZERO_FOLD_COVERAGE"
        else:
            if dev_gross <= 0.0 or dev_net14 <= 0.0:
                verdict = "REJECTED_DEV_EDGE_COLLAPSED_UNDER_NEXT_BAR_OPEN"
            elif not audit_passed:
                verdict = "EXPLORATORY_DEV_EDGE_AUDIT_FAILED_NO_VALIDATED_EDGE"
            elif dev_passed and audit_passed:
                verdict = "EXPLORATORY_CANDIDATE_REQUIRES_PROSPECTIVE_SHADOW_VALIDATION"
            else:
                verdict = "EXPLORATORY_DEV_POSITIVE_BLOCK_CI_WIDE_AUDIT_FAILED_NO_VALIDATED_EDGE"

        promotion_verdicts[cand_name] = {
            "classification": spec["type"],
            "dev_selection_2024_2025_gates_passed": dev_passed,
            "burned_audit_2026_gates_passed": audit_passed,
            "dev_selection_executed_n": dev_data["metrics"]["executed_trades_count"],
            "dev_selection_gross_expectancy_bps": dev_data["metrics"]["gross_expectancy_bps"],
            "dev_selection_net_expectancy_14bps": dev_data["metrics"]["expectancy_bps"],
            "dev_selection_net_expectancy_20bps": dev_data["cost_sensitivity"]["20.0"]["expectancy_bps"],
            "dev_selection_primary_daily_block_ci_95_bps": dev_data["primary_daily_portfolio_block_bootstrap_ci_bps"],
            "dev_selection_diagnostic_iid_trade_ci_95_bps": dev_data["diagnostic_iid_bootstrap_ci_trade_net_bps"],
            "burned_audit_2026_executed_n": audit_data["metrics"]["executed_trades_count"],
            "burned_audit_2026_gross_expectancy_bps": audit_data["metrics"]["gross_expectancy_bps"],
            "burned_audit_2026_net_expectancy_14bps": audit_data["metrics"]["expectancy_bps"],
            "burned_audit_2026_net_expectancy_20bps": audit_data["cost_sensitivity"]["20.0"]["expectancy_bps"],
            "burned_audit_2026_primary_daily_block_ci_95_bps": audit_data["primary_daily_portfolio_block_bootstrap_ci_bps"],
            "burned_audit_2026_diagnostic_iid_trade_ci_95_bps": audit_data["diagnostic_iid_bootstrap_ci_trade_net_bps"],
            "burned_audit_2026_profit_factor": audit_data["metrics"]["profit_factor"],
            "burned_audit_2026_max_drawdown_pct": audit_data["metrics"]["max_drawdown_pct"],
            "verdict": verdict,
        }
        print(
            f"Candidate '{cand_name}': {verdict} | "
            f"DEV_24_25(N={dev_data['metrics']['executed_trades_count']}, Gross={dev_gross:+.2f}, Net14={dev_net14:+.2f}, "
            f"BlockCI_lo={dev_data['primary_daily_portfolio_block_bootstrap_ci_bps']['ci_lower']:+.2f} bps/d, Gates={dev_passed}) | "
            f"BURNED_2026(N={audit_data['metrics']['executed_trades_count']}, Gross={audit_data['metrics']['gross_expectancy_bps']:+.2f}, "
            f"Net14={audit_data['metrics']['expectancy_bps']:+.2f}, Gates={audit_passed})"
        )

    evaluation_results["promotion_verdict"] = "NO_VALIDATED_OOS_EDGE_ENFORCE_NO_TRADE_SHADOW"
    evaluation_results["shadow_qualified_candidates"] = []
    evaluation_results["recommended_runtime_policy"] = "ENFORCE_NO_TRADE_SHADOW"
    evaluation_results["candidate_disposition_summary"] = promotion_verdicts
    evaluation_results["prospective_shadow_epoch_spec"] = {
        "status": "MANDATORY_ONLY_FOR_LOCKED_PLAUSIBLE_DEV_CANDIDATES",
        "policy": "NO_TRADE_SHADOW",
        "zero_order_invariants_guaranteed": True,
    }

    report_json_path = OUT_DIR / "oos_candidate_evaluation_report.json"
    report_json_path.write_text(json.dumps(evaluation_results, indent=2), encoding="utf-8")
    print(f"\nSaved evaluation JSON report to: {report_json_path}")

    write_markdown_report(
        evaluation_results,
        candidate_specs,
        promotion_verdicts,
        OUT_DIR / "oos_candidate_evaluation_report.md",
    )
    print(f"Saved evaluation Markdown report to: {OUT_DIR / 'oos_candidate_evaluation_report.md'}")


def write_markdown_report(
    evaluation_results: dict[str, Any],
    candidate_specs: dict[str, Any],
    promotion_verdicts: dict[str, Any],
    report_md_path: Path,
) -> None:
    md_lines = [
        "# HMR-V5 v2: Causal Next-Bar-Open & Time-Block Candidate Evaluation Report (2023–2026)",
        "",
        f"- **Evaluation Timestamp**: `{evaluation_results['evaluation_timestamp']}`",
        "- **Execution Timing Contract (`VOL_COMPRESSION_BREAKOUT_V1`)**: Signal confirmed at close of bar `i`; earliest entry at `opens[i+1]` (`entry_index = signal_index + 1`); SL-first collision resolution; adverse `opens[curr_idx]` fill on gap-through-stop (`SL_GAP`); `max_hold` anchored at `entry_index`.",
        "- **Split Taxonomy**: `2023` = Exploratory Discovery/Train; `2024–2025` = Development Selection (NOT independent confirmatory OOS); `2026-H1` = Exposed One-Shot Audit Set (failed & permanently burned; zero retuning).",
        "- **Multiple-Testing & CI Governance**: `multiple_testing_trials_count = UNKNOWN`; all pre-lock historical CIs are exploratory. Primary Gate 7 uses **Moving-Block & Stationary Bootstrap (`B=10d`) on cross-symbol daily MTM portfolio returns**; IID trade-level CI is strictly diagnostic.",
        f"- **System Disposition**: `{evaluation_results['promotion_verdict']}` (`{evaluation_results['recommended_runtime_policy']}`)",
        "",
        "## 1. Development Selection (2024–2025) & Burned 2026-H1 Audit Summary",
        "",
        "| Candidate |Dev 24–25 N | Dev Gross (bps) | Dev Net @14 | Dev Net @20 | Primary Daily Block 95% CI (bps/d) | Diag IID Trade 95% CI (bps) | Burned 2026 N | Burned 2026 Gross / Net @14 | Verdict |",
        "| :--- | ---: | ---: | ---: | ---: | :---: | :---: | ---: | :---: | :--- |",
    ]

    for cand_name, d in promotion_verdicts.items():
        bci = d["dev_selection_primary_daily_block_ci_95_bps"]
        tci = d["dev_selection_diagnostic_iid_trade_ci_95_bps"]
        bci_str = f"[{bci['ci_lower']:+.2f}, {bci['ci_upper']:+.2f}]"
        tci_str = f"[{tci['ci_lower']:+.1f}, {tci['ci_upper']:+.1f}]"
        md_lines.append(
            f"| **{cand_name}** | {d['dev_selection_executed_n']} | "
            f"{d['dev_selection_gross_expectancy_bps']:+.2f} | {d['dev_selection_net_expectancy_14bps']:+.2f} | "
            f"{d['dev_selection_net_expectancy_20bps']:+.2f} | `{bci_str}` | `{tci_str}` | "
            f"{d['burned_audit_2026_executed_n']} | "
            f"{d['burned_audit_2026_gross_expectancy_bps']:+.2f} / {d['burned_audit_2026_net_expectancy_14bps']:+.2f} | `{d['verdict']}` |"
        )

    md_lines.extend([
        "",
        "## 2. Retracted Same-Close vs. Corrected Next-Bar-Open (`VOL_COMPRESSION_BREAKOUT_V1`)",
        "",
        "| Split | Timing Mode | Signals | Exec / Rej | Gross (bps) | Net @14 | Net @20 | PF | MDD% | Primary Daily Block CI (bps/d) | Diag IID Trade CI (bps) |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: |",
    ])
    recon = evaluation_results["vcb_v1_execution_timing_reconciliation"]
    for pk, rdata in recon.items():
        for mode_label, key in [("Retracted Same-Close", "retracted_same_close"), ("Corrected Next-Bar-Open", "corrected_next_bar_open")]:
            m = rdata[key]
            bci = m["primary_daily_block_ci_bps"]
            tci = m["diagnostic_iid_trade_ci_bps"]
            md_lines.append(
                f"| `{pk}` | {mode_label} | {m['signals']} | {m['executed_n']} / {m['rejected_capacity_n']} | "
                f"{m['gross_expectancy_bps']:+.2f} | {m['net_expectancy_14bps']:+.2f} | "
                f"{m['cost_sensitivity']['20.0']['expectancy_bps']:+.2f} | {m['profit_factor']:.2f} | "
                f"{m['max_drawdown_pct']:.2f}% | `[{bci['ci_lower']:+.2f}, {bci['ci_upper']:+.2f}]` | "
                f"`[{tci['ci_lower']:+.1f}, {tci['ci_upper']:+.1f}]` |"
            )

    md_lines.extend([
        "",
        "## 3. Per-Symbol Breakdown (`VOL_COMPRESSION_BREAKOUT_V1`: Retracted Same-Close vs. Corrected Next-Bar-Open)",
        "",
        "| Split | Symbol | Same-Close N | Same-Close Gross / Net@14 | Next-Bar-Open N | Next-Bar-Open Gross / Net@14 |",
        "| :--- | :--- | ---: | :---: | ---: | :---: |",
    ])
    for pk, rdata in recon.items():
        sc_syms = rdata["retracted_same_close"]["symbol_breakdown"]
        no_syms = rdata["corrected_next_bar_open"]["symbol_breakdown"]
        for sym in COINS:
            sc_s = sc_syms.get(sym, {"executed_n": 0, "gross_expectancy_bps": 0.0, "net_expectancy_14bps": 0.0})
            no_s = no_syms.get(sym, {"executed_n": 0, "gross_expectancy_bps": 0.0, "net_expectancy_14bps": 0.0})
            md_lines.append(
                f"| `{pk}` | **{sym}** | {sc_s['executed_n']} | {sc_s['gross_expectancy_bps']:+.2f} / {sc_s['net_expectancy_14bps']:+.2f} | "
                f"{no_s['executed_n']} | {no_s['gross_expectancy_bps']:+.2f} / {no_s['net_expectancy_14bps']:+.2f} |"
            )

    def _fmt_pf(val: Any) -> str:
        return f"PF {val:.2f}" if isinstance(val, (int, float)) else f"PF {val}"

    for section_title, pk in [
        ("4A. Cost-Sensitivity Matrix — Development Selection (2024–2025)", "DEV_WALK_FORWARD_SELECTION_2024_2025"),
        ("4B. Cost-Sensitivity Matrix — Burned Exposed 2026-H1 Audit Set", "BURNED_EXPOSED_AUDIT_2026_H1"),
    ]:
        md_lines.extend([
            f"\n## {section_title}\n",
            "| Candidate | Executed N | Gross (bps) | 10 bps Friction | 14 bps (Baseline) | 20 bps (Stressed) | 30 bps (Extreme) |",
            "| :--- | ---: | ---: | :--- | :--- | :--- | :--- |",
        ])
        for cand_name in candidate_specs:
            pd_entry = evaluation_results["candidates"][cand_name]["periods"][pk]
            c_sens = pd_entry["cost_sensitivity"]
            m = pd_entry["metrics"]
            md_lines.append(
                f"| **{cand_name}** | {m['executed_trades_count']} | {m['gross_expectancy_bps']:+.2f} bps | "
                f"{c_sens['10.0']['expectancy_bps']:+.2f} bps ({_fmt_pf(c_sens['10.0']['profit_factor'])}) | "
                f"{c_sens['14.0']['expectancy_bps']:+.2f} bps ({_fmt_pf(c_sens['14.0']['profit_factor'])}) | "
                f"{c_sens['20.0']['expectancy_bps']:+.2f} bps ({_fmt_pf(c_sens['20.0']['profit_factor'])}) | "
                f"{c_sens['30.0']['expectancy_bps']:+.2f} bps ({_fmt_pf(c_sens['30.0']['profit_factor'])}) |"
            )

    report_md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
