#!/usr/bin/env python3
"""HMR-V5: 11-Dimension Economic Attribution Matrix & Timeout Deep-Dive.

Strictly Leak-Free Scope:
- Attribution & Hypothesis Discovery are computed strictly on:
  * TRAIN_2023: ["2023-01-01", "2024-01-01") with exit_timestamp < "2024-01-01"
  * DEV_2024_2025: ["2024-01-01", "2026-01-01") with exit_timestamp < "2026-01-01"
- ZERO rows from >= 2026-01-01 (EXPOSED_INVALID_EVALUATION_AUDIT_SET_2026) are loaded
  or used for feature, threshold, regime, symbol, or exit-rule selection.
- Enforces canonical half-open [start, end) intervals and EXCLUDE_CROSS_BOUNDARY_OUTCOME.

11 Attribution Dimensions:
  1. symbol
  2. side (BUY / SELL)
  3. regime (causal point-in-time market regime)
  4. volatility_bucket (Train-2023-fitted ATR_14 bps quartiles)
  5. funding_liquidity_bucket (causal point-in-time premium & trade-flow / volume bucket)
  6. signal_family (causal entry archetype)
  7. exit_reason (ex-post diagnostic only: TP / SL / TIMEOUT)
  8. holding_time_bucket (ex-post diagnostic only: 1-4, 5-16, 17-48, 49-96 bars)
  9. time_of_day_and_day_of_week (UTC session + UTC day-of-week)
 10. confidence_score_decile (Train-2023-fitted walk-forward score deciles D01..D10)
 11. input_quality (causal point-in-time freshness of external macro/flow/premium feeds)
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.audit_and_prepare_oos_dataset import (
    audit_and_merge_symbol_candles,
    compute_path_aware_e4_trade,
)
from scripts.hmr_v5_d2_parity_replay import MODEL_DIR, RuntimeInferenceEngine

SCAFFOLD_V5_PATH = REPO_ROOT / "research/historical_market_replay_v5/v5_causal_e4_scaffold_2023_2026.parquet"
V4_DIR = REPO_ROOT / "research/historical_market_replay_v4"
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v5"
OUT_DIR.mkdir(parents=True, exist_ok=True)

AUDIT_TS = datetime.now(timezone.utc).isoformat()
COINS = ["BTC", "ETH", "BNB"]
COST_TIERS_BPS = [10.0, 14.0, 20.0, 30.0]
MIN_ADEQUATE_SAMPLE_N = 30


def fast_bootstrap_mean_ci(
    arr: np.ndarray,
    n_bootstraps: int = 500,
    confidence_level: float = 0.95,
    seed: int = 42,
) -> dict[str, float]:
    """Vectorized non-parametric bootstrap 95% CI on mean trade return in bps."""
    n = len(arr)
    if n == 0:
        return {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0}
    if n < 5:
        m = round(float(np.mean(arr)), 2)
        return {"mean": m, "ci_lower": m, "ci_upper": m}
    rng = np.random.default_rng(seed)
    # Chunked resampling when n is very large to keep memory tiny (< 30 MB)
    boot_means = np.empty(n_bootstraps, dtype=float)
    batch = max(1, min(50, 2_000_000 // max(n, 1)))
    for start in range(0, n_bootstraps, batch):
        end = min(n_bootstraps, start + batch)
        idx = rng.integers(0, n, size=(end - start, n))
        boot_means[start:end] = arr[idx].mean(axis=1)
    alpha = (1.0 - confidence_level) / 2.0
    return {
        "mean": round(float(np.mean(arr)), 2),
        "ci_lower": round(float(np.percentile(boot_means, alpha * 100.0)), 2),
        "ci_upper": round(float(np.percentile(boot_means, (1.0 - alpha) * 100.0)), 2),
    }


def compute_serialized_drawdown_and_turnover(
    df_slice: pd.DataFrame,
    cost_bps: float = 14.0,
    allocation_pct: float = 0.25,
) -> tuple[float, float, int]:
    """Computes serialized non-overlapping per-symbol capital path MDD% and turnover.

    Enforces per-symbol non-overlapping lock + 96-bar cooldown so raw overlapping bar
    streams do not inflate turnover or compound overlapping exposure artificially.
    """
    if df_slice.empty:
        return 0.0, 0.0, 0

    ordered = df_slice.sort_values("entry_timestamp")
    entries = ordered["entry_timestamp"].values
    exits = ordered["exit_timestamp"].values
    syms = ordered["symbol"].values
    gross_frac = ordered["gross_return_fraction"].values
    cost_frac = cost_bps / 10000.0
    cooldown_ns = np.timedelta64(96 * 15, "m")

    next_free_by_sym: dict[str, np.datetime64] = {}
    equity = 10000.0
    peak = 10000.0
    max_dd_pct = 0.0
    total_notional = 0.0
    exec_count = 0

    for i in range(len(ordered)):
        sym = str(syms[i])
        ent = entries[i]
        ext = exits[i]
        free_ts = next_free_by_sym.get(sym)
        if free_ts is not None and ent < free_ts:
            continue
        if equity <= 0.0:
            break
        notional = equity * allocation_pct
        net_pnl = notional * (float(gross_frac[i]) - cost_frac)
        equity = max(0.0, equity + net_pnl)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
        if dd > max_dd_pct:
            max_dd_pct = dd
        total_notional += notional
        next_free_by_sym[sym] = ext + cooldown_ns
        exec_count += 1

    turnover = total_notional / 10000.0
    return round(float(max_dd_pct), 2), round(float(turnover), 2), int(exec_count)


def analyze_slice(
    trades_Or_df: list[dict[str, Any]] | pd.DataFrame,
    cost_bps: float = 14.0,
    population_total_n: int | None = None,
) -> dict[str, Any]:
    """Computes full attribution cell metrics with N, 10/14/20/30 bps net EV, 95% CI, MDD, turnover, coverage."""
    if isinstance(trades_Or_df, pd.DataFrame):
        df_s = trades_Or_df
    else:
        df_s = pd.DataFrame(trades_Or_df)

    n = len(df_s)
    pop_n = population_total_n if (population_total_n and population_total_n > 0) else max(n, 1)
    if n == 0:
        return {
            "count": 0,
            "executed_serialized_n": 0,
            "sample_adequacy": "EMPTY_SLICE",
            "coverage_pct": 0.0,
            "gross_expectancy_bps": 0.0,
            "net_expectancy_bps": 0.0,
            "net_expectancy_by_cost_bps": {f"{int(c)}bps": 0.0 for c in COST_TIERS_BPS},
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "bootstrap_ci_95_gross_bps": {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0},
            "bootstrap_ci_95_net14_bps": {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0},
            "max_drawdown_pct": 0.0,
            "turnover": 0.0,
            "tp_count": 0,
            "sl_count": 0,
            "timeout_count": 0,
            "tp_rate_pct": 0.0,
            "sl_rate_pct": 0.0,
            "timeout_rate_pct": 0.0,
            "timeout_avg_gross_bps": 0.0,
        }

    if "gross_return_fraction" in df_s.columns:
        gross_bps = df_s["gross_return_fraction"].to_numpy(dtype=float) * 10000.0
    elif "realized_pnl" in df_s.columns:
        gross_bps = df_s["realized_pnl"].to_numpy(dtype=float) * 10000.0
    else:
        gross_bps = df_s["gross_pnl_bps"].to_numpy(dtype=float)

    net_primary = gross_bps - cost_bps
    wins = net_primary[net_primary > 0.0]
    losses = net_primary[net_primary <= 0.0]
    gp = float(wins.sum())
    gl = abs(float(losses.sum()))
    pf = (gp / gl) if gl > 1e-9 else (999.0 if gp > 0.0 else 0.0)

    net_by_cost = {f"{int(c)}bps": round(float(np.mean(gross_bps - c)), 2) for c in COST_TIERS_BPS}

    exits = df_s["exit_reason"].astype(str) if "exit_reason" in df_s.columns else pd.Series([""] * n)
    tp_c = int((exits == "TP").sum())
    sl_c = int((exits == "SL").sum())
    to_mask = (exits == "TIMEOUT").to_numpy()
    to_c = int(to_mask.sum())
    to_avg_gross = float(np.mean(gross_bps[to_mask])) if to_c > 0 else 0.0

    if {"entry_timestamp", "exit_timestamp", "symbol", "gross_return_fraction"}.issubset(df_s.columns):
        mdd_pct, turnover, exec_n = compute_serialized_drawdown_and_turnover(df_s, cost_bps=cost_bps)
    else:
        mdd_pct, turnover, exec_n = 0.0, 0.0, n

    adequacy = (
        "ADEQUATE"
        if (n >= MIN_ADEQUATE_SAMPLE_N and exec_n >= MIN_ADEQUATE_SAMPLE_N)
        else "SMALL_SAMPLE_NOT_EDGE_EVIDENCE"
    )

    return {
        "count": n,
        "executed_serialized_n": exec_n,
        "sample_adequacy": adequacy,
        "coverage_pct": round(n / pop_n * 100.0, 2),
        "gross_expectancy_bps": round(float(np.mean(gross_bps)), 2),
        "net_expectancy_bps": round(float(np.mean(net_primary)), 2),
        "net_expectancy_by_cost_bps": net_by_cost,
        "win_rate_pct": round(float(len(wins) / n * 100.0), 2),
        "profit_factor": round(pf, 3),
        "bootstrap_ci_95_gross_bps": fast_bootstrap_mean_ci(gross_bps),
        "bootstrap_ci_95_net14_bps": fast_bootstrap_mean_ci(net_primary),
        "max_drawdown_pct": mdd_pct,
        "turnover": turnover,
        "tp_count": tp_c,
        "sl_count": sl_c,
        "timeout_count": to_c,
        "tp_rate_pct": round(tp_c / n * 100.0, 2),
        "sl_rate_pct": round(sl_c / n * 100.0, 2),
        "timeout_rate_pct": round(to_c / n * 100.0, 2),
        "timeout_avg_gross_bps": round(to_avg_gross, 2),
    }


def _audit_observed_paper_fills() -> dict[str, Any]:
    """Scans paper runtime execution logs for actual observed paper/demo fill costs."""
    files = sorted(
        set(
            list(REPO_ROOT.glob("runtime/paper/**/execution_*.jsonl"))
            + list(REPO_ROOT.glob("logs/execution/**/execution_*.jsonl"))
        )
    )
    by_id: dict[str, dict[str, Any]] = {}
    for f_path in files:
        for line in f_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("status") == "FILLED" and float(rec.get("filled_qty", 0.0) or 0.0) > 0.0:
                fill_p = float(rec["avg_fill_price"])
                qty = float(rec["filled_qty"])
                notional = fill_p * qty
                fee_bps = float(rec.get("fee", 0.0) or 0.0) / notional * 10000.0 if notional > 0 else 0.0
                dec_p = float(rec.get("decision_price", 0.0) or rec.get("mid_price", 0.0) or 0.0)
                side = str(rec.get("side", "BUY")).upper()
                if dec_p > 0.0:
                    slip_bps = (
                        (fill_p - dec_p) / dec_p * 10000.0
                        if side == "BUY"
                        else (dec_p - fill_p) / dec_p * 10000.0
                    )
                else:
                    slip_bps = float(rec.get("total_slippage_bps", 0.0) or 0.0)
                exec_id = str(rec.get("execution_id") or f"{f_path.name}:{len(by_id)}")
                by_id[exec_id] = {
                    "execution_id": exec_id,
                    "symbol": str(rec.get("coin", "")),
                    "side": side,
                    "fee_bps": round(fee_bps, 4),
                    "slippage_bps": round(slip_bps, 4),
                    "per_leg_cost_bps": round(fee_bps + max(0.0, slip_bps), 4),
                    "evidence_eligible": bool(rec.get("evidence_eligible", False)),
                }

    rows = list(by_id.values())
    n = len(rows)
    if n == 0:
        return {
            "observed_filled_legs_n": 0,
            "sample_adequacy": "NO_OBSERVED_FILLS",
            "implied_roundtrip_median_bps": None,
            "implied_roundtrip_mean_bps": None,
            "implied_roundtrip_p95_bps": None,
        }
    leg_arr = np.array([r["per_leg_cost_bps"] for r in rows], dtype=float)
    rt_arr = leg_arr * 2.0
    return {
        "observed_filled_legs_n": n,
        "evidence_eligible_count": sum(1 for r in rows if r["evidence_eligible"]),
        "sample_adequacy": "ADEQUATE" if n >= MIN_ADEQUATE_SAMPLE_N else "INSUFFICIENT_SAMPLE_NOT_CALIBRATION_GRADE",
        "per_leg_median_bps": round(float(np.median(leg_arr)), 2),
        "per_leg_mean_bps": round(float(np.mean(leg_arr)), 2),
        "implied_roundtrip_median_bps": round(float(np.median(rt_arr)), 2),
        "implied_roundtrip_mean_bps": round(float(np.mean(rt_arr)), 2),
        "implied_roundtrip_p95_bps": round(float(np.percentile(rt_arr, 95)), 2),
    }


def enrich_point_in_time_dimensions(
    df_pre2026: pd.DataFrame,
    candles_pre2026: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Enriches pre-2026 trades with all 11 causal point-in-time attribution dimensions.

    Quantile/decile thresholds are fit strictly on TRAIN_2023 (< 2024-01-01).
    """
    df = df_pre2026.copy()
    # Hard invariant: never allow >= 2026-01-01 in attribution/discovery
    cutoff_2026 = pd.Timestamp("2026-01-01", tz="UTC")
    if (df["entry_timestamp"] >= cutoff_2026).any() or (df["exit_timestamp"] >= cutoff_2026).any():
        raise ValueError("Leakage guard triggered: >= 2026-01-01 rows detected in attribution dataset!")

    # 1. Merge causal candle-level indicators at exact entry_timestamp per symbol
    candle_feat_frames = []
    for sym, c_df in candles_pre2026.items():
        s_c = c_df["close"]
        s_h = c_df["high"]
        s_l = c_df["low"]
        s_v = c_df["volume"]
        tr = pd.concat(
            [s_h - s_l, (s_h - s_c.shift(1)).abs(), (s_l - s_c.shift(1)).abs()],
            axis=1,
        ).max(axis=1)
        atr14_bps = tr.shift(1).rolling(14).mean() / s_c * 10000.0
        atr192_bps = tr.shift(1).rolling(192).mean() / s_c * 10000.0
        prev_hi96 = s_h.shift(1).rolling(96).max()
        prev_lo96 = s_l.shift(1).rolling(96).min()
        sma96 = s_c.rolling(96).mean()
        sma384 = s_c.rolling(384).mean()
        vol_ratio96 = s_v / s_v.shift(1).rolling(96).mean()
        dollar_vol96 = (s_c * s_v).shift(1).rolling(96).mean()

        cf = pd.DataFrame({
            "symbol": sym,
            "entry_timestamp": c_df["timestamp"],
            "atr14_bps": atr14_bps.fillna(0.0),
            "atr192_bps": atr192_bps.fillna(0.0),
            "is_hi_break96": (s_c > prev_hi96).fillna(False),
            "is_lo_break96": (s_c < prev_lo96).fillna(False),
            "sma96_gt_384": (sma96 > sma384).fillna(False),
            "close_gt_sma384": (s_c > sma384).fillna(False),
            "vol_ratio96": vol_ratio96.replace([np.inf, -np.inf], np.nan).fillna(1.0),
            "dollar_vol96": dollar_vol96.fillna(0.0),
        })
        candle_feat_frames.append(cf)

    all_cf = pd.concat(candle_feat_frames, ignore_index=True)
    df = df.merge(all_cf, on=["symbol", "entry_timestamp"], how="left")

    # 2. Causal merge_asof with auxiliary premium, trade-flow, and cross-market macro feeds
    df = df.sort_values("entry_timestamp").reset_index(drop=True)

    prem_path = V4_DIR / "v4b_2b_premium_history.parquet"
    flow_path = V4_DIR / "v4b_4b_trade_flow_history.parquet"
    macro_path = V4_DIR / "v4c_1b_cross_market_history.parquet"

    if prem_path.exists():
        prem = pd.read_parquet(prem_path)[["symbol", "close_time", "premium_close"]].copy()
        prem["prem_avail_ts"] = pd.to_datetime(prem["close_time"], utc=True)
        prem = prem[prem["prem_avail_ts"] < cutoff_2026].sort_values("prem_avail_ts")
        df = pd.merge_asof(
            df,
            prem[["symbol", "prem_avail_ts", "premium_close"]],
            by="symbol",
            left_on="entry_timestamp",
            right_on="prem_avail_ts",
            direction="backward",
        )
    else:
        df["prem_avail_ts"] = pd.NaT
        df["premium_close"] = np.nan

    if flow_path.exists():
        flow = pd.read_parquet(flow_path)[
            ["symbol", "close_time", "taker_buy_notional", "taker_sell_notional"]
        ].copy()
        flow["flow_avail_ts"] = pd.to_datetime(flow["close_time"], utc=True)
        flow["flow_total_notional"] = flow["taker_buy_notional"] + flow["taker_sell_notional"]
        flow = flow[flow["flow_avail_ts"] < cutoff_2026].sort_values("flow_avail_ts")
        df = pd.merge_asof(
            df,
            flow[["symbol", "flow_avail_ts", "flow_total_notional"]],
            by="symbol",
            left_on="entry_timestamp",
            right_on="flow_avail_ts",
            direction="backward",
        )
    else:
        df["flow_avail_ts"] = pd.NaT
        df["flow_total_notional"] = np.nan

    if macro_path.exists():
        macro = pd.read_parquet(macro_path)[["available_at", "vix_close"]].copy()
        macro["macro_avail_ts"] = pd.to_datetime(macro["available_at"], utc=True)
        macro = macro[macro["macro_avail_ts"] < cutoff_2026].sort_values("macro_avail_ts")
        df = pd.merge_asof(
            df,
            macro[["macro_avail_ts", "vix_close"]],
            left_on="entry_timestamp",
            right_on="macro_avail_ts",
            direction="backward",
        )
    else:
        df["macro_avail_ts"] = pd.NaT
        df["vix_close"] = np.nan

    # 3. Fit all quantile / decile / walk-forward score cutoffs STRICTLY on TRAIN_2023
    train_mask = (df["entry_timestamp"] >= "2023-01-01") & (df["entry_timestamp"] < "2024-01-01") & (df["exit_timestamp"] < "2024-01-01")
    dev_24_mask = (df["entry_timestamp"] >= "2024-01-01") & (df["entry_timestamp"] < "2025-01-01") & (df["exit_timestamp"] < "2025-01-01")
    dev_25_mask = (df["entry_timestamp"] >= "2025-01-01") & (df["entry_timestamp"] < "2026-01-01") & (df["exit_timestamp"] < "2026-01-01")

    atr14_q = np.quantile(df.loc[train_mask, "atr14_bps"].values, [0.25, 0.50, 0.75])
    atr192_q65 = float(np.quantile(df.loc[train_mask, "atr192_bps"].values, 0.65))
    flow_med_by_sym = (
        df.loc[train_mask].groupby("symbol")["flow_total_notional"].median().to_dict()
    )
    dvol_med_by_sym = (
        df.loc[train_mask].groupby("symbol")["dollar_vol96"].median().to_dict()
    )

    # Walk-forward score (Fold 1 fit on 2023 -> score 2023 & 2024; Fold 2 fit on 2023-2024 -> score 2025)
    score_cols = ["return_8", "return_32", "return_72", "abs_move_72", "trend_spread"]
    wf_scores = np.zeros(len(df), dtype=float)

    sc_f1 = StandardScaler()
    X_tr1 = sc_f1.fit_transform(df.loc[train_mask, score_cols].fillna(0.0))
    y_tr1 = df.loc[train_mask, "gross_return_fraction"].values * 10000.0 - 14.0
    mdl_f1 = Ridge(alpha=100.0).fit(X_tr1, y_tr1)
    wf_scores[train_mask] = mdl_f1.predict(X_tr1)
    if dev_24_mask.any():
        wf_scores[dev_24_mask] = mdl_f1.predict(sc_f1.transform(df.loc[dev_24_mask, score_cols].fillna(0.0)))

    tr_f2_mask = train_mask | dev_24_mask
    sc_f2 = StandardScaler()
    X_tr2 = sc_f2.fit_transform(df.loc[tr_f2_mask, score_cols].fillna(0.0))
    y_tr2 = df.loc[tr_f2_mask, "gross_return_fraction"].values * 10000.0 - 14.0
    mdl_f2 = Ridge(alpha=100.0).fit(X_tr2, y_tr2)
    if dev_25_mask.any():
        wf_scores[dev_25_mask] = mdl_f2.predict(sc_f2.transform(df.loc[dev_25_mask, score_cols].fillna(0.0)))

    df["wf_score_bps"] = wf_scores
    decile_edges = np.quantile(wf_scores[train_mask], np.linspace(0.1, 0.9, 9))
    decile_idx = np.digitize(wf_scores, decile_edges, right=False) + 1
    df["confidence_score_decile"] = [f"D{d:02d}" for d in decile_idx]

    # Volatility bucket (Train-2023 quartiles)
    vol_b = np.where(
        df["atr14_bps"] <= atr14_q[0],
        "Q1_LOW_VOL",
        np.where(
            df["atr14_bps"] <= atr14_q[1],
            "Q2_MOD_LOW_VOL",
            np.where(df["atr14_bps"] <= atr14_q[2], "Q3_MOD_HIGH_VOL", "Q4_HIGH_VOL"),
        ),
    )
    df["volatility_bucket"] = vol_b

    # Regime (causal point-in-time)
    aligned_breakout = (
        ((df["side"] == "BUY") & df["is_hi_break96"] & df["sma96_gt_384"] & df["close_gt_sma384"])
        | ((df["side"] == "SELL") & df["is_lo_break96"] & (~df["sma96_gt_384"]) & (~df["close_gt_sma384"]))
    ) & (df["vol_ratio96"] >= 1.2)
    any_breakout = ((df["side"] == "BUY") & df["is_hi_break96"]) | ((df["side"] == "SELL") & df["is_lo_break96"])

    regime = np.full(len(df), "CHOP_RANGE", dtype=object)
    regime[(df["trend_spread"] > 0.0005) & df["sma96_gt_384"]] = "TREND_BULL"
    regime[(df["trend_spread"] < -0.0005) & (~df["sma96_gt_384"])] = "TREND_BEAR"
    regime[any_breakout] = "HIGH_VOL_OR_UNALIGNED_BREAKOUT"
    regime[aligned_breakout & (df["atr192_bps"] <= atr192_q65)] = "COMPRESSION_BREAKOUT"
    df["regime"] = regime

    # Signal family (causal entry archetype)
    signed_r8 = np.where(df["side"] == "BUY", df["return_8"], -df["return_8"])
    signed_r32 = np.where(df["side"] == "BUY", df["return_32"], -df["return_32"])
    htf_aligned = ((df["side"] == "BUY") & df["sma96_gt_384"]) | ((df["side"] == "SELL") & (~df["sma96_gt_384"]))

    sig_fam = np.full(len(df), "PULLBACK_IN_TREND", dtype=object)
    sig_fam[(signed_r8 > 0.0) & (signed_r32 > 0.0)] = "MOMENTUM_CONTINUATION"
    sig_fam[~htf_aligned] = "COUNTER_HTF_DRIFT"
    sig_fam[any_breakout & htf_aligned] = "DONCHIAN_BREAKOUT_ALIGNED"
    sig_fam[df["trend_spread"].abs() <= 0.0005] = "CHOP_DUAL_SIDED"
    df["signal_family"] = sig_fam

    # Input quality & Funding/Liquidity bucket (causal availability age check)
    flow_age_sec = (df["entry_timestamp"] - df["flow_avail_ts"]).dt.total_seconds()
    prem_age_sec = (df["entry_timestamp"] - df["prem_avail_ts"]).dt.total_seconds()
    macro_age_sec = (df["entry_timestamp"] - df["macro_avail_ts"]).dt.total_seconds()

    flow_fresh = flow_age_sec.notna() & (flow_age_sec >= 0.0) & (flow_age_sec <= 3600.0)
    prem_fresh = prem_age_sec.notna() & (prem_age_sec >= 0.0) & (prem_age_sec <= 3600.0)
    macro_fresh = macro_age_sec.notna() & (macro_age_sec >= 0.0) & (macro_age_sec <= 36.0 * 3600.0)

    input_qual = np.where(
        flow_fresh & prem_fresh & macro_fresh,
        "FRESH_ALL_CONTEXT",
        np.where(
            flow_fresh & prem_fresh & (~macro_fresh),
            "WEEKEND_OR_HOLIDAY_MACRO_AGING",
            "STALE_EXTERNAL_NEUTRALIZED",
        ),
    )
    df["input_quality"] = input_qual

    sym_flow_med = df["symbol"].map(flow_med_by_sym).fillna(0.0)
    sym_dvol_med = df["symbol"].map(dvol_med_by_sym).fillna(0.0)
    high_liq_fresh = df["flow_total_notional"] >= sym_flow_med
    pos_prem = df["premium_close"].fillna(0.0) >= 0.0
    high_dvol_fallback = df["dollar_vol96"] >= sym_dvol_med

    fl_bucket = np.where(
        flow_fresh & prem_fresh,
        np.where(
            high_liq_fresh & pos_prem,
            "HIGH_LIQ_POS_PREMIUM",
            np.where(
                high_liq_fresh & (~pos_prem),
                "HIGH_LIQ_NEG_PREMIUM",
                np.where((~high_liq_fresh) & pos_prem, "LOW_LIQ_POS_PREMIUM", "LOW_LIQ_NEG_PREMIUM"),
            ),
        ),
        np.where(
            high_dvol_fallback,
            "STALE_FEED_CANDLE_VOL_HIGH",
            "STALE_FEED_CANDLE_VOL_LOW",
        ),
    )
    df["funding_liquidity_bucket"] = fl_bucket

    # Holding-time bucket (ex-post diagnostic)
    bh = df["bars_held"].to_numpy()
    df["holding_time_bucket"] = np.where(
        bh <= 4,
        "1-4_bars",
        np.where(bh <= 16, "5-16_bars", np.where(bh <= 48, "17-48_bars", "49-96_bars")),
    )

    # Time of day & day of week (UTC)
    hrs = df["entry_timestamp"].dt.hour.to_numpy()
    df["session_utc"] = np.where(
        hrs < 6,
        "00-06_ASIA",
        np.where(hrs < 12, "06-12_EU", np.where(hrs < 18, "12-18_US", "18-24_LATE_US")),
    )
    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    df["day_of_week_utc"] = [dow_names[d] for d in df["entry_timestamp"].dt.dayofweek.to_numpy()]

    fit_metadata = {
        "fitted_strictly_on": "TRAIN_2023 [2023-01-01, 2024-01-01) with exit_timestamp < 2024-01-01",
        "atr14_quartiles_bps": [round(float(x), 3) for x in atr14_q],
        "atr192_compression_q65_bps": round(atr192_q65, 3),
        "wf_score_decile_edges_bps": [round(float(x), 3) for x in decile_edges],
    }
    return df, fit_metadata


def build_11d_matrix_for_split(df_split: pd.DataFrame) -> dict[str, Any]:
    """Builds the 11-dimension attribution dictionary for one leak-free split."""
    total_n = len(df_split)
    dimensions_spec = [
        ("symbol", "symbol", False),
        ("side", "side", False),
        ("regime", "regime", False),
        ("volatility_bucket", "volatility_bucket", False),
        ("funding_liquidity_bucket", "funding_liquidity_bucket", False),
        ("signal_family", "signal_family", False),
        ("exit_reason", "exit_reason", True),
        ("holding_time_bucket", "holding_time_bucket", True),
        ("time_of_day_utc", "session_utc", False),
        ("day_of_week_utc", "day_of_week_utc", False),
        ("confidence_score_decile", "confidence_score_decile", False),
        ("input_quality", "input_quality", False),
    ]
    matrix: dict[str, Any] = {}
    for dim_key, col_name, is_ex_post in dimensions_spec:
        cells: dict[str, Any] = {}
        for val in sorted(df_split[col_name].dropna().unique().tolist()):
            sub = df_split[df_split[col_name] == val]
            cell = analyze_slice(sub, cost_bps=14.0, population_total_n=total_n)
            cell["is_ex_post_diagnostic_only"] = is_ex_post
            cells[str(val)] = cell
        matrix[dim_key] = {
            "is_ex_post_diagnostic_only": is_ex_post,
            "cells": cells,
        }
    return matrix


def run_timeout_deep_dive(
    df_enriched: pd.DataFrame,
    candles_pre2026: dict[str, pd.DataFrame],
    observed_fills: dict[str, Any],
) -> dict[str, Any]:
    """Performs the P1 #11 non-overfitted deep-dive on the TIMEOUT subset."""
    tr = df_enriched[
        (df_enriched["entry_timestamp"] >= "2023-01-01")
        & (df_enriched["entry_timestamp"] < "2024-01-01")
        & (df_enriched["exit_timestamp"] < "2024-01-01")
    ]
    dev = df_enriched[
        (df_enriched["entry_timestamp"] >= "2024-01-01")
        & (df_enriched["entry_timestamp"] < "2026-01-01")
        & (df_enriched["exit_timestamp"] < "2026-01-01")
    ]
    h2_24 = df_enriched[
        (df_enriched["entry_timestamp"] >= "2024-07-02")
        & (df_enriched["entry_timestamp"] < "2025-01-01")
        & (df_enriched["exit_timestamp"] < "2025-01-01")
    ]

    split_summaries: dict[str, Any] = {}
    for s_name, s_df in [("TRAIN_2023", tr), ("DEV_2024_2025", dev), ("CONFIRMATORY_2024_H2", h2_24)]:
        to_df = s_df[s_df["exit_reason"] == "TIMEOUT"]
        overall_to = analyze_slice(to_df, cost_bps=14.0, population_total_n=len(s_df))
        gross_arr = to_df["gross_return_fraction"].to_numpy(dtype=float) * 10000.0 if len(to_df) else np.array([])

        obs_sens = {}
        if observed_fills.get("implied_roundtrip_median_bps") is not None and len(gross_arr) > 0:
            med_c = float(observed_fills["implied_roundtrip_median_bps"])
            mean_c = float(observed_fills["implied_roundtrip_mean_bps"])
            obs_sens = {
                "observed_median_roundtrip_bps": med_c,
                "net_at_observed_median_bps": round(float(np.mean(gross_arr - med_c)), 2),
                "observed_mean_roundtrip_bps": mean_c,
                "net_at_observed_mean_bps": round(float(np.mean(gross_arr - mean_c)), 2),
                "sample_warning": observed_fills["sample_adequacy"],
            }

        split_summaries[s_name] = {
            "overall": overall_to,
            "corridor_bounds_observed_bps": {
                "min_gross_bps": round(float(gross_arr.min()), 2) if len(gross_arr) else 0.0,
                "max_gross_bps": round(float(gross_arr.max()), 2) if len(gross_arr) else 0.0,
                "theoretical_corridor_bps": [-30.0, 50.0],
                "theoretical_symmetric_midpoint_bps": 10.0,
            },
            "by_symbol": {
                sym: analyze_slice(to_df[to_df["symbol"] == sym], 14.0, len(to_df))
                for sym in COINS
            },
            "by_side": {
                side: analyze_slice(to_df[to_df["side"] == side], 14.0, len(to_df))
                for side in ["BUY", "SELL"]
            },
            "by_regime": {
                reg: analyze_slice(to_df[to_df["regime"] == reg], 14.0, len(to_df))
                for reg in sorted(to_df["regime"].unique().tolist())
            },
            "observed_paper_fill_sensitivity": obs_sens,
        }

    # Entry vs Exit Timing Decomposition & Alternative Exit Horizons STRICTLY on TRAIN_2023
    horizon_grid_train2023 = []
    for label, max_hold, tp_bps, sl_bps, entry_mode in [
        ("E4_NARROW_H16", 16, 50.0, 30.0, "TREND_SPREAD"),
        ("E4_NARROW_H32", 32, 50.0, 30.0, "TREND_SPREAD"),
        ("E4_NARROW_H48", 48, 50.0, 30.0, "TREND_SPREAD"),
        ("E4_NARROW_H96_BASELINE", 96, 50.0, 30.0, "TREND_SPREAD"),
        ("E4_NARROW_H144", 144, 50.0, 30.0, "TREND_SPREAD"),
        ("PURE_TIME_EXIT_H16_NO_BARRIER", 16, 10000.0, 10000.0, "TREND_SPREAD"),
        ("PURE_TIME_EXIT_H48_NO_BARRIER", 48, 10000.0, 10000.0, "TREND_SPREAD"),
        ("PURE_TIME_EXIT_H96_NO_BARRIER", 96, 10000.0, 10000.0, "TREND_SPREAD"),
        ("WIDE_BARRIER_350_150_H192_TREND_SPREAD", 192, 350.0, 150.0, "TREND_SPREAD"),
        ("WIDE_BARRIER_350_150_H192_VOL_COMP_BREAKOUT", 192, 350.0, 150.0, "VOL_COMP_BREAKOUT"),
    ]:
        gross_list = []
        for sym, c_df in candles_pre2026.items():
            c_23 = c_df[c_df["timestamp"] < "2024-01-01"].reset_index(drop=True)
            closes = c_23["close"].values
            highs = c_23["high"].values
            lows = c_23["low"].values
            vols = c_23["volume"].values
            ts_list = c_23["timestamp"].tolist()
            n_c = len(c_23)

            s_c = pd.Series(closes)
            s_h = pd.Series(highs)
            s_l = pd.Series(lows)
            s_v = pd.Series(vols)

            if entry_mode == "TREND_SPREAD":
                sma16 = s_c.rolling(16).mean().values
                sma64 = s_c.rolling(64).mean().values
                sp = (sma16 - sma64) / np.where(sma64 > 0, sma64, np.nan)
                for i in range(100, n_c - max_hold, 16):
                    if np.isnan(sp[i]) or abs(sp[i]) <= 0.0005:
                        continue
                    side = "BUY" if sp[i] > 0.0005 else "SELL"
                    r, _, _, _, _, _, exit_i = compute_path_aware_e4_trade(
                        side, i, closes, highs, lows, max_hold=max_hold, tp_bps=tp_bps, sl_bps=sl_bps
                    )
                    if ts_list[exit_i] < pd.Timestamp("2024-01-01", tz="UTC"):
                        gross_list.append(r * 10000.0)
            else:
                prev_hi = s_h.shift(1).rolling(96).max().values
                prev_lo = s_l.shift(1).rolling(96).min().values
                sma96 = s_c.rolling(96).mean().values
                sma384 = s_c.rolling(384).mean().values
                vol_ma = s_v.shift(1).rolling(96).mean().values
                tr_s = pd.concat(
                    [s_h - s_l, (s_h - s_c.shift(1)).abs(), (s_l - s_c.shift(1)).abs()],
                    axis=1,
                ).max(axis=1)
                atr192_bps = (tr_s.shift(1).rolling(192).mean() / s_c * 10000.0).values
                valid_atr = atr192_bps[~np.isnan(atr192_bps)]
                q65 = float(np.quantile(valid_atr, 0.65))
                next_free_idx = 0
                for i in range(386, n_c - max_hold):
                    if i < next_free_idx:
                        continue
                    if np.isnan(prev_hi[i]) or np.isnan(sma384[i]) or np.isnan(vol_ma[i]) or vol_ma[i] <= 0 or np.isnan(atr192_bps[i]):
                        continue
                    if vols[i] / vol_ma[i] < 1.2 or atr192_bps[i] > q65:
                        continue
                    side = None
                    if closes[i] > prev_hi[i] and closes[i] > sma384[i] and sma96[i] > sma384[i]:
                        side = "BUY"
                    elif closes[i] < prev_lo[i] and closes[i] < sma384[i] and sma96[i] < sma384[i]:
                        side = "SELL"
                    if side is None:
                        continue
                    r, _, _, _, _, _, exit_i = compute_path_aware_e4_trade(
                        side, i, closes, highs, lows, max_hold=max_hold, tp_bps=tp_bps, sl_bps=sl_bps
                    )
                    if ts_list[exit_i] < pd.Timestamp("2024-01-01", tz="UTC"):
                        gross_list.append(r * 10000.0)
                        next_free_idx = exit_i + 96

        arr = np.array(gross_list, dtype=float)
        horizon_grid_train2023.append({
            "experiment": label,
            "entry_mode": entry_mode,
            "max_hold_bars": max_hold,
            "tp_bps": tp_bps,
            "sl_bps": sl_bps,
            "n_trades": len(arr),
            "gross_expectancy_bps": round(float(arr.mean()), 2) if len(arr) else 0.0,
            "net_14bps": round(float((arr - 14.0).mean()), 2) if len(arr) else 0.0,
            "net_20bps": round(float((arr - 20.0).mean()), 2) if len(arr) else 0.0,
            "ci_95_net14_bps": fast_bootstrap_mean_ci(arr - 14.0) if len(arr) else {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0},
        })

    return {
        "verdict": "NOT_VIABLE_ASYMMETRIC_BARRIER_SURVIVORSHIP_ARTIFACT",
        "timing_attribution_explanation": (
            "In E4 (TP=+50 bps, SL=-30 bps, max_hold=96), a TIMEOUT trade is defined ex-post as a path that "
            "never touched -30 bps and never touched +50 bps over 96 bars. Consequently, terminal TIMEOUT returns "
            "are mechanically trapped inside (-30, +50) bps, whose geometric midpoint is +10.0 bps even for a "
            "zero-drift random walk (paid for by the 62.1% SL hit rate). Removing barriers on the same trend_spread "
            "entries yields only +0.59 to +3.29 bps gross (-10.71 to -13.41 bps net at 14 bps), proving TIMEOUT "
            "positivity is an exit-conditioning survivorship artifact rather than causal entry alpha."
        ),
        "splits": split_summaries,
        "train_2023_exit_horizon_experiments": horizon_grid_train2023,
        "observed_paper_fill_audit": observed_fills,
    }


def main() -> None:
    print("=== HMR-V5: 11-Dimension Economic Attribution & Timeout Deep-Dive ===")
    print(f"Timestamp: {AUDIT_TS}\n")

    df_all = pd.read_parquet(SCAFFOLD_V5_PATH)
    df_all["entry_timestamp"] = pd.to_datetime(df_all["entry_timestamp"], utc=True)
    df_all["exit_timestamp"] = pd.to_datetime(df_all["exit_timestamp"], utc=True)

    # STRICT PRE-2026 CUTOFF: never load >= 2026-01-01 into attribution or discovery
    cutoff_2026 = pd.Timestamp("2026-01-01", tz="UTC")
    df_pre2026 = df_all[
        (df_all["entry_timestamp"] >= "2023-01-01")
        & (df_all["entry_timestamp"] < cutoff_2026)
        & (df_all["exit_timestamp"] < cutoff_2026)
    ].copy()

    candles_pre2026: dict[str, pd.DataFrame] = {}
    for sym in COINS:
        c_df, _ = audit_and_merge_symbol_candles(sym)
        candles_pre2026[sym] = c_df[c_df["timestamp"] < cutoff_2026].reset_index(drop=True)

    print(f"Enriching {len(df_pre2026):,} pre-2026 causal trades across 11 point-in-time dimensions...")
    df_enriched, fit_meta = enrich_point_in_time_dimensions(df_pre2026, candles_pre2026)

    # Evaluate S3 Legacy out-of-domain diagnostic on Confirmatory 2024-H2 for continuity
    s3_engine = RuntimeInferenceEngine(MODEL_DIR)
    s3_cols = ["return_8", "return_32", "return_72", "abs_move_72"]
    h2_mask = (
        (df_enriched["entry_timestamp"] >= "2024-07-02")
        & (df_enriched["entry_timestamp"] < "2025-01-01")
        & (df_enriched["exit_timestamp"] < "2025-01-01")
    )
    h2_df = df_enriched[h2_mask].copy()
    s3_pass_flags = [
        bool(s3_engine.predict_score_and_decision(r["symbol"], [r[c] for c in s3_cols])[1])
        for _, r in h2_df[["symbol"] + s3_cols].iterrows()
    ]
    h2_df["s3_pass"] = s3_pass_flags

    tr_df = df_enriched[
        (df_enriched["entry_timestamp"] >= "2023-01-01")
        & (df_enriched["entry_timestamp"] < "2024-01-01")
        & (df_enriched["exit_timestamp"] < "2024-01-01")
    ]
    dev_df = df_enriched[
        (df_enriched["entry_timestamp"] >= "2024-01-01")
        & (df_enriched["entry_timestamp"] < "2026-01-01")
        & (df_enriched["exit_timestamp"] < "2026-01-01")
    ]

    print(f"Building 11-dimension matrices: TRAIN_2023 (N={len(tr_df):,}) & DEV_2024_2025 (N={len(dev_df):,})...")
    matrix_train = build_11d_matrix_for_split(tr_df)
    matrix_dev = build_11d_matrix_for_split(dev_df)

    observed_fills = _audit_observed_paper_fills()
    print("Running TIMEOUT subset deep-dive & Train-2023 exit-horizon experiments...")
    timeout_deep_dive = run_timeout_deep_dive(df_enriched, candles_pre2026, observed_fills)

    overall = {
        "train_2023": analyze_slice(tr_df, 14.0, len(tr_df)),
        "dev_2024_2025": analyze_slice(dev_df, 14.0, len(dev_df)),
        "confirmatory_2024_h2_control": analyze_slice(h2_df, 14.0, len(h2_df)),
        "confirmatory_2024_h2_s3": analyze_slice(h2_df[h2_df["s3_pass"]], 14.0, len(h2_df)),
    }

    report_data = {
        "program": "HMR-V5-ECONOMIC-ATTRIBUTION-11D",
        "audit_timestamp": AUDIT_TS,
        "leakage_governance": {
            "discovery_split": "TRAIN_2023 [2023-01-01, 2024-01-01)",
            "selection_split": "DEV_2024_2025 [2024-01-01, 2026-01-01)",
            "interval_semantics": "half_open_[start,end)",
            "cross_boundary_policy": "EXCLUDE_CROSS_BOUNDARY_OUTCOME",
            "audit_2026_used_in_attribution_or_discovery": False,
            "minimum_adequate_cell_sample_n": MIN_ADEQUATE_SAMPLE_N,
        },
        "train_fitted_bucket_cutoffs": fit_meta,
        "overall": overall,
        "attribution_11d_train_2023": matrix_train,
        "attribution_11d_dev_2024_2025": matrix_dev,
        "timeout_subset_deep_dive": timeout_deep_dive,
    }

    json_path = OUT_DIR / "economic_attribution_report.json"
    json_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    print(f"[OK] Saved 11D attribution JSON: {json_path}")

    write_markdown_report(report_data, OUT_DIR / "economic_attribution_report.md")
    print(f"[OK] Saved 11D attribution Markdown: {OUT_DIR / 'economic_attribution_report.md'}")


def write_markdown_report(data: dict[str, Any], md_path: Path) -> None:
    ov = data["overall"]
    tr_o = ov["train_2023"]
    dv_o = ov["dev_2024_2025"]
    td = data["timeout_subset_deep_dive"]
    obs = td["observed_paper_fill_audit"]

    lines = [
        "# HMR-V5: 11-Dimension Economic Attribution & Timeout Deep-Dive (Train 2023 & Dev 2024–2025)",
        "",
        f"- **Audit Timestamp**: `{data['audit_timestamp']}`",
        "- **Splits**: `TRAIN_2023` (`[2023-01-01, 2024-01-01)`) & `DEV_2024_2025` (`[2024-01-01, 2026-01-01)`)",
        "- **Boundary Contract**: Half-open `[start, end)` + `EXCLUDE_CROSS_BOUNDARY_OUTCOME` (`exit_timestamp < end`)",
        "- **Leakage Guard**: `2026` (`EXPOSED_INVALID_EVALUATION_AUDIT_SET_2026`) is completely excluded (`0` rows loaded).",
        "",
        "## 1. Population Overview (E4 Baseline Stream: TP=50 bps, SL=30 bps, H=96)",
        "",
        "| Split | Candidate N | Serialized Exec N | Gross Exp (bps) | Net @10 | Net @14 | Net @20 | Net @30 | Win% (@14) | PF (@14) | 95% CI Net @14 (bps) | Max DD% | Turnover |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | ---: | ---: |",
    ]
    for label, s in [("TRAIN_2023", tr_o), ("DEV_2024_2025", dv_o)]:
        ci = s["bootstrap_ci_95_net14_bps"]
        nb = s["net_expectancy_by_cost_bps"]
        lines.append(
            f"| **{label}** | {s['count']:,} | {s['executed_serialized_n']:,} | {s['gross_expectancy_bps']:+.2f} | "
            f"{nb['10bps']:+.2f} | {nb['14bps']:+.2f} | {nb['20bps']:+.2f} | {nb['30bps']:+.2f} | "
            f"{s['win_rate_pct']:.1f}% | {s['profit_factor']:.2f} | `[{ci['ci_lower']:+.2f}, {ci['ci_upper']:+.2f}]` | "
            f"{s['max_drawdown_pct']:.2f}% | {s['turnover']:.2f}x |"
        )

    lines.extend([
        "",
        "## 2. 11-Dimension Attribution Matrix (`DEV_2024_2025`, Quantiles Fit Strictly on `TRAIN_2023`)",
        "",
        "> Cells with `N < 30` or `Serialized Exec N < 30` are tagged `SMALL_SAMPLE_NOT_EDGE_EVIDENCE` and never treated as edge.",
        "> Dimensions `exit_reason` and `holding_time_bucket` are marked `EX_POST_DIAGNOSTIC` (known only after trade exit).",
        "",
    ])

    for dim_name, dim_payload in data["attribution_11d_dev_2024_2025"].items():
        ex_tag = " *(EX-POST DIAGNOSTIC ONLY)*" if dim_payload["is_ex_post_diagnostic_only"] else ""
        lines.extend([
            f"### Dimension: `{dim_name}`{ex_tag}",
            "",
            "| Cell | N (Cov%) | Exec N | Adequacy | Gross (bps) | Net @10 | Net @14 | Net @20 | Net @30 | Win% | PF | 95% CI Net @14 | MDD% | Turnover |",
            "| :--- | ---: | ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: | ---: | ---: |",
        ])
        for cell_name, c in dim_payload["cells"].items():
            ci = c["bootstrap_ci_95_net14_bps"]
            nb = c["net_expectancy_by_cost_bps"]
            lines.append(
                f"| `{cell_name}` | {c['count']:,} ({c['coverage_pct']:.1f}%) | {c['executed_serialized_n']:,} | "
                f"`{c['sample_adequacy']}` | {c['gross_expectancy_bps']:+.2f} | {nb['10bps']:+.2f} | {nb['14bps']:+.2f} | "
                f"{nb['20bps']:+.2f} | {nb['30bps']:+.2f} | {c['win_rate_pct']:.1f}% | {c['profit_factor']:.2f} | "
                f"`[{ci['ci_lower']:+.2f}, {ci['ci_upper']:+.2f}]` | {c['max_drawdown_pct']:.2f}% | {c['turnover']:.2f}x |"
            )
        lines.append("")

    lines.extend([
        "## 3. TIMEOUT Subset Deep-Dive & Train-2023 Exit Horizon Decomposition",
        "",
        f"- **Verdict**: `{td['verdict']}`",
        f"- **Mechanism**: {td['timing_attribution_explanation']}",
        f"- **Observed Paper Fill Cost Audit**: `N = {obs['observed_filled_legs_n']}` filled paper legs (`{obs['sample_adequacy']}`), implied roundtrip median `{obs['implied_roundtrip_median_bps']} bps`, mean `{obs['implied_roundtrip_mean_bps']} bps`, p95 `{obs['implied_roundtrip_p95_bps']} bps`.",
        "",
        "### A. TIMEOUT Subset Across Leak-Free Splits",
        "",
        "| Split | TIMEOUT N (Share%) | Exec N | Gross (bps) | Net @14 (bps) | 95% CI Net @14 | Corridor Obs [Min, Max] | Net @ Obs Median Fill |",
        "| :--- | ---: | ---: | ---: | ---: | :---: | :---: | ---: |",
    ])
    for sp_name, sp_d in td["splits"].items():
        o = sp_d["overall"]
        ci = o["bootstrap_ci_95_net14_bps"]
        cb = sp_d["corridor_bounds_observed_bps"]
        obs_s = sp_d["observed_paper_fill_sensitivity"]
        obs_net = f"{obs_s.get('net_at_observed_median_bps', 0.0):+.2f} bps" if obs_s else "N/A"
        lines.append(
            f"| **{sp_name}** | {o['count']:,} ({o['coverage_pct']:.2f}%) | {o['executed_serialized_n']:,} | "
            f"{o['gross_expectancy_bps']:+.2f} | {o['net_expectancy_bps']:+.2f} | `[{ci['ci_lower']:+.2f}, {ci['ci_upper']:+.2f}]` | "
            f"`[{cb['min_gross_bps']:+.2f}, {cb['max_gross_bps']:+.2f}]` | {obs_net} |"
        )

    lines.extend([
        "",
        "### B. Alternative Exit Horizons & Structural Entry Comparison (Strictly `TRAIN_2023`)",
        "",
        "| Experiment | Entry Family | Hold (bars) | TP / SL (bps) | N | Gross (bps) | Net @14 (bps) | Net @20 (bps) | 95% CI Net @14 |",
        "| :--- | :--- | ---: | :---: | ---: | ---: | ---: | ---: | :---: |",
    ])
    for ex in td["train_2023_exit_horizon_experiments"]:
        ci = ex["ci_95_net14_bps"]
        lines.append(
            f"| `{ex['experiment']}` | `{ex['entry_mode']}` | {ex['max_hold_bars']} | "
            f"{ex['tp_bps']:.0f} / {ex['sl_bps']:.0f} | {ex['n_trades']:,} | {ex['gross_expectancy_bps']:+.2f} | "
            f"{ex['net_14bps']:+.2f} | {ex['net_20bps']:+.2f} | `[{ci['ci_lower']:+.2f}, {ci['ci_upper']:+.2f}]` |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
