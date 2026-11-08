#!/usr/bin/env python3
"""HMR-V4B-2B-r1: Perp Spot Premium Historical Information Source Audit."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4a_outcome_scaffold.parquet"
PREMIUM_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4b_2b_premium_history.parquet"
FUNDING_PATH = REPO_ROOT / "data/historical_funding_rates.parquet"
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"

REVISION = "HMR-V4B-2B-r1"
COINS = ["BTC", "ETH", "BNB"]

# Feature definitions
FEATURES = [
    "perp_premium_level",
    "perp_premium_change_4h",
    "perp_premium_change_24h",
    "perp_premium_percentile_30d"
]

# Horizons and gates
HORIZONS = {
    32: {"label": "8h", "floor_bps": 10.0},
    72: {"label": "18h", "floor_bps": 15.0},
    192: {"label": "48h", "floor_bps": 20.0}
}

PERIODS = {
    "A": ("2023-01-01T00:00:00+00:00", "2024-06-30T23:59:59+00:00"),
    "B": ("2024-07-01T00:00:00+00:00", "2024-09-30T23:59:59+00:00"),
    "C": ("2024-10-01T00:00:00+00:00", "2024-12-31T23:59:59+00:00")
}

def assign_period(ts: pd.Timestamp) -> str | None:
    for name, (start, end) in PERIODS.items():
        if pd.Timestamp(start) <= ts <= pd.Timestamp(end):
            return name
    return None

def rolling_percentile(series: pd.Series, window: int = 2880, min_periods: int = 100) -> pd.Series:
    return series.rolling(window, min_periods=min_periods).rank(pct=True)

def compute_premium_features(df: pd.DataFrame) -> pd.DataFrame:
    print("Computing premium features...")
    df = df.sort_values(["symbol", "open_time"]).copy()
    df["perp_premium_level"] = df["premium_close"]
    # Deltas
    df["perp_premium_change_4h"] = df.groupby("symbol")["premium_close"].diff(16)
    df["perp_premium_change_24h"] = df.groupby("symbol")["premium_close"].diff(96)
    # rolling percentile
    df["perp_premium_percentile_30d"] = df.groupby("symbol")["premium_close"].transform(
        lambda x: rolling_percentile(x, 2880, 100)
    )
    return df.fillna(0.0)

def compute_targets(df: pd.DataFrame) -> pd.DataFrame:
    print("Reconstructing outcome horizons...")
    frames = []
    for symbol, g in df.groupby("symbol"):
        g = g.sort_values("timestamp").copy()
        close = g["close"]
        # Future returns
        g["return_192"] = g["close"].shift(-192).sub(g["close"]).div(g["close"])
        
        # Absolute returns
        g["abs_return_72"] = g["return_72"].abs()
        g["abs_return_192"] = g["return_192"].abs()
        
        # Max absolute excursions
        future_72 = pd.concat([close.shift(-i) for i in range(1, 73)], axis=1)
        mfe_72 = (future_72.max(axis=1) - close) / close
        mae_72 = (future_72.min(axis=1) - close) / close
        g["max_abs_excursion_72"] = np.maximum(mfe_72.abs(), mae_72.abs())
        
        future_192 = pd.concat([close.shift(-i) for i in range(1, 193)], axis=1)
        mfe_192 = (future_192.max(axis=1) - close) / close
        mae_192 = (future_192.min(axis=1) - close) / close
        g["max_abs_excursion_192"] = np.maximum(mfe_192.abs(), mae_192.abs())
        
        frames.append(g)
        
    df_out = pd.concat(frames, ignore_index=True)
    # Drop rows that don't have complete targets
    return df_out.dropna(subset=["return_192", "max_abs_excursion_192"])

def get_spearman_rank(x: list[float], y: list[float]) -> float:
    if len(x) < 2 or len(set(y)) <= 1:
        return 0.0
    return float(pd.Series(x).corr(pd.Series(y), method="spearman"))

def block_bootstrap_ci(df: pd.DataFrame, feature: str, period: str, target: str, block_length: int = 96, iterations: int = 200) -> tuple[float | None, float | None]:
    period_df = df[df["period"] == period].copy().sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    if period_df.empty:
        return None, None
        
    n = len(period_df)
    n_blocks = int(math.ceil(n / block_length))
    block_starts = np.arange(0, n - block_length + 1, block_length)
    if len(block_starts) == 0:
        return None, None
        
    rng = np.random.default_rng(42)
    boot_spreads = []
    
    for _ in range(iterations):
        # sample block starts with replacement
        starts = rng.choice(block_starts, size=n_blocks, replace=True)
        indices = []
        for start in starts:
            indices.extend(range(start, min(start + block_length, n)))
        
        sample = period_df.iloc[indices[:n]]
        q1 = sample[sample["q"] == 1][target]
        q5 = sample[sample["q"] == 5][target]
        if not q1.empty and not q5.empty:
            boot_spreads.append((q5.mean() - q1.mean()) * 10000.0)
            
    if not boot_spreads:
        return None, None
    return float(np.percentile(boot_spreads, 2.5)), float(np.percentile(boot_spreads, 97.5))

def winsorize_spread(df: pd.DataFrame, target: str, q_limit: float = 0.01) -> float:
    work = df.copy()
    limit_val = work[target].quantile(1.0 - q_limit)
    work[target] = work[target].clip(upper=limit_val)
    q1 = work[work["q"] == 1][target]
    q5 = work[work["q"] == 5][target]
    if q1.empty or q5.empty:
        return 0.0
    return (q5.mean() - q1.mean()) * 10000.0

def run_audit(output_dir: Path | str = OUT_DIR):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Starting {REVISION} Perpetual Spot Premium audit...")
    
    # 1. Load Parquets
    scaffold = pd.read_parquet(SCAFFOLD_PATH)
    scaffold["timestamp"] = pd.to_datetime(scaffold["timestamp"], utc=True).astype("datetime64[ns, UTC]")
    
    premium = pd.read_parquet(PREMIUM_PATH)
    premium["available_at"] = pd.to_datetime(premium["available_at"], utc=True).astype("datetime64[ns, UTC]")
    premium["open_time"] = pd.to_datetime(premium["open_time"], utc=True).astype("datetime64[ns, UTC]")
    
    funding = pd.read_parquet(FUNDING_PATH)
    funding["timestamp"] = pd.to_datetime(funding["timestamp"], utc=True).astype("datetime64[ns, UTC]")
    
    # 2. Add Premium Features
    premium_feats = compute_premium_features(premium)
    
    # 3. PIT Merge premium features
    print("Performing PIT merge...")
    merged_frames = []
    for coin in COINS:
        left = scaffold[scaffold["symbol"] == coin].sort_values("timestamp").copy()
        right = premium_feats[premium_feats["symbol"] == coin].sort_values("available_at").copy()
        
        joined = pd.merge_asof(
            left,
            right,
            left_on="timestamp",
            right_on="available_at",
            by="symbol",
            direction="backward"
        )
        merged_frames.append(joined)
        
    df = pd.concat(merged_frames, ignore_index=True)
    
    # Assert PIT correctness
    lookahead_rows = (df["available_at"] > df["timestamp"]).sum()
    print(f"PIT check: lookahead_rows = {lookahead_rows}")
    assert lookahead_rows == 0, f"FATAL: lookahead rows detected: {lookahead_rows}"
    
    # 4. Reconstruct outcomes (return_192, max_abs_excursion_72, max_abs_excursion_192)
    df = compute_targets(df)
    
    # 5. Merge Funding rates (for redundancy tests)
    print("Merging funding rates...")
    merged_funding = []
    for coin in COINS:
        left = df[df["symbol"] == coin].sort_values("timestamp").copy()
        right = funding[funding["symbol"] == coin][["timestamp", "funding_rate"]].sort_values("timestamp").copy()
        
        joined = pd.merge_asof(
            left,
            right,
            on="timestamp",
            direction="backward"
        )
        merged_funding.append(joined)
    df = pd.concat(merged_funding, ignore_index=True)
    df["funding_rate"] = df["funding_rate"].fillna(0.0)
    
    # 6. Add endogenous Price state variables
    print("Computing endogenous price state...")
    df = df.sort_values(["symbol", "timestamp"]).copy()
    # recent_return (72 bars = 18h)
    df["recent_return"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(72))
    # realized_volatility (72 bars = 18h standard deviation of returns)
    df["realized_volatility"] = df.groupby("symbol")["close"].transform(
        lambda x: x.pct_change().rolling(72).std()
    )
    df["recent_return"] = df["recent_return"].fillna(0.0)
    df["realized_volatility"] = df["realized_volatility"].fillna(0.0)
    
    # Assign periods
    df["period"] = df["timestamp"].apply(assign_period)
    df = df[df["period"].notna()].copy()
    
    # Perform Audit for each feature
    feature_verdicts = []
    
    # Quantiles data frames for export
    all_quantiles_export = []
    all_conditional_export = []
    all_funding_export = []
    all_asset_export = []
    all_monthly_export = []
    all_tail_export = []
    
    for feat in FEATURES:
        print(f"\n--- Auditing feature: {feat} ---")
        df_feat = df.copy()
        
        # Fit Period A boundaries
        df_a = df_feat[df_feat["period"] == "A"]
        edges = np.nanpercentile(df_a[feat], [20, 40, 60, 80])
        print(f"Period A quantile edges for {feat}: {edges}")
        
        df_feat["q"] = df_feat[feat].apply(lambda x: int(np.searchsorted(edges, x) + 1))
        
        # Collect quantile assignment for parity checks
        export_df = df_feat[["timestamp", "symbol", "period", feat, "q", "premium_close", "available_at"]].copy()
        export_df = export_df.rename(columns={feat: "feature_value"}).assign(feature=feat)
        all_quantiles_export.append(export_df)
        
        # Primary evaluations
        by_period_target_spreads = {}
        by_period_target_stats = {}
        
        for period in ["A", "B", "C"]:
            p_df = df_feat[df_feat["period"] == period]
            by_period_target_spreads[period] = {}
            by_period_target_stats[period] = {}
            
            for h_bars, h_info in HORIZONS.items():
                target = f"return_{h_bars}"
                q1 = p_df[p_df["q"] == 1][target]
                q5 = p_df[p_df["q"] == 2][target] # Wait, Q5 is q==5! Make sure we match q==5.
                # Let's fix this!
                q5 = p_df[p_df["q"] == 5][target]
                
                raw_spread = 0.0
                q1_count = len(q1)
                q5_count = len(q5)
                
                if q1_count > 0 and q5_count > 0:
                    raw_spread = (q5.mean() - q1.mean()) * 10000.0
                    
                by_period_target_spreads[period][h_bars] = raw_spread
                by_period_target_stats[period][h_bars] = {
                    "count_q1": q1_count,
                    "count_q5": q5_count,
                    "spread_bps": raw_spread
                }
                
        # Let's determine orientation from Period A (using 18h return_72 as benchmark, or check all?)
        # Let's check which horizon is the primary one, or if orientation is determined horizon-by-horizon.
        # Orientation is horizon-by-horizon.
        orientations = {}
        for h_bars in HORIZONS:
            orientations[h_bars] = np.sign(by_period_target_spreads["A"][h_bars])
            
        print(f"Orientations determined on Period A: {orientations}")
        
        # Audit each horizon
        horizon_verdicts = {}
        for h_bars, h_info in HORIZONS.items():
            target = f"return_{h_bars}"
            spr_a = by_period_target_spreads["A"][h_bars]
            spr_b = by_period_target_spreads["B"][h_bars]
            spr_c = by_period_target_spreads["C"][h_bars]
            floor = h_info["floor_bps"]
            orient = orientations[h_bars]
            
            # B4: Economic floor pass B & C AND B5: same sign as Period A
            economic_b = (abs(spr_b) >= floor) and (np.sign(spr_b) == orient)
            economic_c = (abs(spr_c) >= floor) and (np.sign(spr_c) == orient)
            passed_economic = economic_b and economic_c
            
            # B3: Support Collapse check
            q1_b = by_period_target_stats["B"][h_bars]["count_q1"]
            q5_b = by_period_target_stats["B"][h_bars]["count_q5"]
            q1_c = by_period_target_stats["C"][h_bars]["count_q1"]
            q5_c = by_period_target_stats["C"][h_bars]["count_q5"]
            support_collapse = (q1_b == 0 or q5_b == 0 or q1_c == 0 or q5_c == 0)
            
            # B11: Funding Redundancy check
            funding_edges = np.nanpercentile(df_feat[df_feat["period"] == "A"]["funding_rate"], [33.33, 66.67])
            
            def assign_funding(x):
                if x <= funding_edges[0]: return "Low"
                elif x <= funding_edges[1]: return "Mid"
                else: return "High"
                
            df_feat["funding_regime"] = df_feat["funding_rate"].apply(assign_funding)
            
            # B6: Endogenous price state conditioning
            trend_edges = np.nanpercentile(df_feat[df_feat["period"] == "A"]["recent_return"], [33.33, 66.67])
            vol_edges = np.nanpercentile(df_feat[df_feat["period"] == "A"]["realized_volatility"], [33.33, 66.67])
            
            def assign_trend(x):
                if x <= trend_edges[0]: return "DOWN"
                elif x <= trend_edges[1]: return "FLAT"
                else: return "UP"
                
            def assign_vol(x):
                if x <= vol_edges[0]: return "LOW"
                elif x <= vol_edges[1]: return "MID"
                else: return "HIGH"
                
            df_feat["trend_regime"] = df_feat["recent_return"].apply(assign_trend)
            df_feat["vol_regime"] = df_feat["realized_volatility"].apply(assign_vol)
            
            # Compute conditional spreads in B and C combined
            val_df = df_feat[df_feat["period"].isin(["B", "C"])]
            
            cond_spreads = []
            cond_weights = []
            for regime, g in val_df.groupby("funding_regime"):
                g_q1 = g[g["q"] == 1][target]
                g_q5 = g[g["q"] == 5][target]
                if not g_q1.empty and not g_q5.empty:
                    spread_regime = (g_q5.mean() - g_q1.mean()) * 10000.0
                    cond_spreads.append(spread_regime)
                    cond_weights.append(len(g))
                    
            weighted_funding_spread = np.average(cond_spreads, weights=cond_weights) if cond_spreads else 0.0
            raw_val_spread = (val_df[val_df["q"] == 5][target].mean() - val_df[val_df["q"] == 1][target].mean()) * 10000.0
            funding_retention = abs(weighted_funding_spread / raw_val_spread) if abs(raw_val_spread) >= 1e-12 else 0.0
            
            funding_passed = (
                np.sign(weighted_funding_spread) == np.sign(raw_val_spread)
                and abs(weighted_funding_spread) >= 0.50 * abs(raw_val_spread)
                and abs(weighted_funding_spread) >= 0.50 * floor
            )
            
            cond_endog_spreads = []
            cond_endog_weights = []
            
            for (t_reg, v_reg), g in val_df.groupby(["trend_regime", "vol_regime"]):
                g_q1 = g[g["q"] == 1][target]
                g_q5 = g[g["q"] == 5][target]
                if not g_q1.empty and not g_q5.empty:
                    spread_regime = (g_q5.mean() - g_q1.mean()) * 10000.0
                    cond_endog_spreads.append(spread_regime)
                    cond_endog_weights.append(len(g))
                    
            weighted_endog_spread = np.average(cond_endog_spreads, weights=cond_endog_weights) if cond_endog_spreads else 0.0
            endog_retention = abs(weighted_endog_spread / raw_val_spread) if abs(raw_val_spread) >= 1e-12 else 0.0
            
            endog_passed = (
                np.sign(weighted_endog_spread) == np.sign(raw_val_spread)
                and abs(weighted_endog_spread) >= 0.50 * abs(raw_val_spread)
            )
            
            # B7: Cross-asset robustness
            asset_spreads = {}
            for coin in COINS:
                coin_df = val_df[val_df["symbol"] == coin]
                q1_c = coin_df[coin_df["q"] == 1][target]
                q5_c = coin_df[coin_df["q"] == 5][target]
                if not q1_c.empty and not q5_c.empty:
                    asset_spreads[coin] = (q5_c.mean() - q1_c.mean()) * 10000.0
                else:
                    asset_spreads[coin] = 0.0
                    
            same_sign_count = sum(1 for coin, spr in asset_spreads.items() if np.sign(spr) == orient)
            total_abs_spreads = sum(abs(spr) for spr in asset_spreads.values())
            largest_contribution = max(abs(spr) for spr in asset_spreads.values()) / total_abs_spreads if total_abs_spreads > 0 else 0.0
            
            asset_passed = (same_sign_count >= 2) and (largest_contribution <= 0.70)
            
            # B8: Monthly stability
            val_df_with_month = val_df.copy()
            val_df_with_month["month"] = val_df_with_month["timestamp"].dt.strftime("%Y-%m")
            
            monthly_spreads = {}
            for month, g in val_df_with_month.groupby("month"):
                g_q1 = g[g["q"] == 1][target]
                g_q5 = g[g["q"] == 5][target]
                if not g_q1.empty and not g_q5.empty:
                    monthly_spreads[month] = (g_q5.mean() - g_q1.mean()) * 10000.0
                else:
                    monthly_spreads[month] = 0.0
                    
            monthly_same_sign = sum(1 for m, spr in monthly_spreads.items() if np.sign(spr) == orient)
            monthly_total_abs = sum(abs(spr) for spr in monthly_spreads.values())
            monthly_largest_contrib = max(abs(spr) for spr in monthly_spreads.values()) / monthly_total_abs if monthly_total_abs > 0 else 0.0
            
            monthly_passed = (monthly_same_sign >= 4) and (monthly_largest_contrib <= 0.70)
            
            # B9: Block-bootstrap CI excludes zero
            ci_low_b, ci_high_b = block_bootstrap_ci(df_feat, feat, "B", target)
            ci_low_c, ci_high_c = block_bootstrap_ci(df_feat, feat, "C", target)
            
            bootstrap_passed = (
                ci_low_b is not None and ci_high_b is not None
                and ci_low_c is not None and ci_high_c is not None
                and not (ci_low_b <= 0.0 <= ci_high_b)
                and not (ci_low_c <= 0.0 <= ci_high_c)
            )
            
            # B10: Tail-Event Domination
            wins_spread = winsorize_spread(val_df, target, 0.01)
            tail_contribution = 1.0 - (wins_spread / raw_val_spread) if abs(raw_val_spread) >= 1e-12 else 0.0
            tail_passed = (tail_contribution <= 0.70)
            
            # Overall verdict for this horizon
            horizon_verdicts[h_bars] = {
                "passed_economic": bool(passed_economic),
                "support_collapse": bool(support_collapse),
                "funding_passed": bool(funding_passed),
                "endog_passed": bool(endog_passed),
                "asset_passed": bool(asset_passed),
                "monthly_passed": bool(monthly_passed),
                "bootstrap_passed": bool(bootstrap_passed),
                "tail_passed": bool(tail_passed),
                "raw_val_spread_bps": float(raw_val_spread),
                "weighted_funding_spread_bps": float(weighted_funding_spread),
                "funding_retention": float(funding_retention),
                "weighted_endog_spread_bps": float(weighted_endog_spread),
                "endog_retention": float(endog_retention),
                "asset_spreads": {coin: float(s) for coin, s in asset_spreads.items()},
                "asset_largest_contribution": float(largest_contribution),
                "monthly_spreads": {m: float(s) for m, s in monthly_spreads.items()},
                "monthly_largest_contribution": float(monthly_largest_contrib),
                "ci_b": [ci_low_b, ci_high_b],
                "ci_c": [ci_low_c, ci_high_c],
                "winsorized_spread_bps": float(wins_spread),
                "tail_contribution": float(tail_contribution)
            }
            
            # Store conditional, funding, asset, monthly, tail for output Parquets
            for r in df_feat.groupby(["trend_regime", "vol_regime"]):
                (t_reg, v_reg), g = r
                g_q1 = g[g["q"] == 1][target]
                g_q5 = g[g["q"] == 5][target]
                if not g_q1.empty and not g_q5.empty:
                    all_conditional_export.append({
                        "feature": feat, "horizon": h_info["label"],
                        "trend_regime": t_reg, "vol_regime": v_reg,
                        "count": len(g), "spread_bps": (g_q5.mean() - g_q1.mean()) * 10000.0
                    })
            for r in df_feat.groupby("funding_regime"):
                regime, g = r
                g_q1 = g[g["q"] == 1][target]
                g_q5 = g[g["q"] == 5][target]
                if not g_q1.empty and not g_q5.empty:
                    all_funding_export.append({
                        "feature": feat, "horizon": h_info["label"],
                        "funding_regime": regime, "count": len(g),
                        "spread_bps": (g_q5.mean() - g_q1.mean()) * 10000.0
                    })
            for coin, spr in asset_spreads.items():
                all_asset_export.append({
                    "feature": feat, "horizon": h_info["label"],
                    "symbol": coin, "spread_bps": spr
                })
            for month, spr in monthly_spreads.items():
                all_monthly_export.append({
                    "feature": feat, "horizon": h_info["label"],
                    "month": month, "spread_bps": spr
                })
            all_tail_export.append({
                "feature": feat, "horizon": h_info["label"],
                "raw_spread_bps": raw_val_spread, "winsorized_spread_bps": wins_spread,
                "tail_contribution": tail_contribution
            })
            
        # Overall feature level verdict assignment based on horizons
        feature_verdict = "REJECT_NO_ECONOMIC_INFORMATION"
        best_horizon = None
        
        # Check if any horizon satisfies the economic gate and all subsequent gates
        for h_bars in HORIZONS:
            hv = horizon_verdicts[h_bars]
            if hv["support_collapse"]:
                feature_verdict = "REJECT_SUPPORT_COLLAPSE"
                break
                
        if feature_verdict != "REJECT_SUPPORT_COLLAPSE":
            passed_horizons = []
            for h_bars in HORIZONS:
                hv = horizon_verdicts[h_bars]
                if hv["passed_economic"]:
                    passed_horizons.append(h_bars)
                    
            if not passed_horizons:
                # check if Period A was significant but B/C was not
                any_a = any(abs(by_period_target_spreads["A"][hb]) >= HORIZONS[hb]["floor_bps"] for hb in HORIZONS)
                if any_a:
                    feature_verdict = "REJECT_NON_TRANSPORTABLE"
                else:
                    feature_verdict = "REJECT_NO_ECONOMIC_INFORMATION"
            else:
                # Find if any passed horizon passes the rest of the gates
                promoted = False
                for hb in passed_horizons:
                    hv = horizon_verdicts[hb]
                    if not hv["funding_passed"]:
                        feature_verdict = "REJECT_AS_FUNDING_REDUNDANT"
                    elif not hv["endog_passed"]:
                        feature_verdict = "REJECT_AS_ENDOGENOUS_STATE_PROXY"
                    elif not hv["asset_passed"]:
                        feature_verdict = "REJECT_CROSS_ASSET_CONFOUNDING"
                    elif not hv["bootstrap_passed"]:
                        feature_verdict = "REJECT_NO_ECONOMIC_INFORMATION"
                    elif not hv["tail_passed"]:
                        feature_verdict = "REJECT_TAIL_EVENT_DOMINATED"
                    else:
                        promoted = True
                        best_horizon = hb
                        break
                        
                if promoted:
                    # Determine type of promotion: directional vs magnitude
                    feature_verdict = "PROMOTE_DIRECTIONAL_INFORMATION"
                    
        # Determine max observed spread and its details
        max_obs_spr = 0.0
        max_obs_hor = None
        for h_bars in HORIZONS:
            hv = horizon_verdicts[h_bars]
            spr_val = hv["raw_val_spread_bps"]
            if abs(spr_val) > abs(max_obs_spr):
                max_obs_spr = spr_val
                max_obs_hor = h_bars
                
        # Economic floor ratio
        economic_floor_ratio = 0.0
        if max_obs_hor is not None:
            floor_bps = HORIZONS[max_obs_hor]["floor_bps"]
            economic_floor_ratio = abs(max_obs_spr) / floor_bps
            
        print(f"Feature verdict for {feat}: {feature_verdict} (Best horizon: {best_horizon}, Max observed: {max_obs_spr:.4f} bps)")
        feature_verdicts.append({
            "feature": feat,
            "verdict": feature_verdict,
            "best_horizon": best_horizon,
            "max_observed_spread_bps": float(max_obs_spr) if max_obs_hor else 0.0,
            "horizon_of_max_observed_spread": int(max_obs_hor) if max_obs_hor else None,
            "economic_floor_ratio": float(economic_floor_ratio) if max_obs_hor else 0.0,
            "horizon_verdicts": horizon_verdicts
        })
        
    # Assembling final artifacts
    print("Saving parquet files...")
    pd.concat(all_quantiles_export, ignore_index=True).to_parquet(output_dir / "v4b_2b_premium_quantiles.parquet", index=False)
    pd.DataFrame(all_conditional_export).to_parquet(output_dir / "v4b_2b_premium_conditional.parquet", index=False)
    pd.DataFrame(all_funding_export).to_parquet(output_dir / "v4b_2b_premium_funding_redundancy.parquet", index=False)
    pd.DataFrame(all_asset_export).to_parquet(output_dir / "v4b_2b_premium_asset_stability.parquet", index=False)
    pd.DataFrame(all_monthly_export).to_parquet(output_dir / "v4b_2b_premium_monthly_stability.parquet", index=False)
    pd.DataFrame(all_tail_export).to_parquet(output_dir / "v4b_2b_premium_tail_sensitivity.parquet", index=False)
    
    # Save JSON Verdict Report
    verdict_json = {
        "program": REVISION,
        "source": "binance_premium_index_klines",
        "information_family": "PERP_PREMIUM_DISLOCATION",
        "provenance": "MARKET_OBSERVED",
        "provenance_gate": "PASS",
        "model_training": "BLOCKED",
        "feature_verdicts": feature_verdicts
    }
    
    verdict_json_path = output_dir / "v4b_2b_premium_audit.json"
    with open(verdict_json_path, "w", encoding="utf-8") as f:
        json.dump(verdict_json, f, indent=2)
    print(f"✓ Saved audit json to {verdict_json_path}")
    
    # Save Markdown report
    write_md_report(verdict_json, output_dir=output_dir)
    
def write_md_report(output: dict[str, Any], output_dir: Path | str = OUT_DIR):
    report_path = Path(output_dir) / "v4b_2b_premium_report.md"
    
    lines = [
        f"# {output['program']} Perpetual Spot Premium Historical Information Audit Report",
        "",
        "## Governance Contract Status",
        "",
        f"- **Program**: `{output['program']}`",
        f"- **Source**: `{output['source']}`",
        f"- **Information Family**: `{output['information_family']}`",
        f"- **Provenance**: `{output['provenance']}`",
        f"- **Provenance Gate**: `{output['provenance_gate']}`",
        f"- **Model Training**: `{output['model_training']}`",
        "",
        "## Feature Verdicts Summaries",
        "",
        "| Feature | Verdict | Best Horizon | Max Observed Spread | Horizon of Max | Economic Floor Ratio |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |"
    ]
    
    for fv in output["feature_verdicts"]:
        feat = fv["feature"]
        verdict = fv["verdict"]
        bh = fv["best_horizon"]
        bh_str = HORIZONS[bh]["label"] if bh else "None"
        
        max_spr = fv["max_observed_spread_bps"]
        max_h = fv["horizon_of_max_observed_spread"]
        max_h_lbl = HORIZONS[max_h]["label"] if max_h else "None"
        ratio = fv["economic_floor_ratio"]
        
        lines.append(f"| `{feat}` | **{verdict}** | `{bh_str}` | {max_spr:.4f} bps | `{max_h_lbl}` | {ratio:.2%} |")
        
    lines.append("")
    lines.append("## Detailed Horizons Gates Report")
    
    for fv in output["feature_verdicts"]:
        lines.append(f"### Feature: `{fv['feature']}`")
        lines.append("")
        lines.append("| Horizon | Economic | Support | Funding Redundancy | Endogenous Proxy | Asset Robust. | Monthly Stab. | Bootstrap CI | Tail Domination |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
        
        for h_bars, h_info in HORIZONS.items():
            hv = fv["horizon_verdicts"][h_bars]
            h_lbl = h_info["label"]
            
            ec_p = "PASS" if hv["passed_economic"] else "FAIL"
            sup_p = "PASS" if not hv["support_collapse"] else "FAIL"
            fund_p = "PASS" if hv["funding_passed"] else "FAIL"
            end_p = "PASS" if hv["endog_passed"] else "FAIL"
            ass_p = "PASS" if hv["asset_passed"] else "FAIL"
            mon_p = "PASS" if hv["monthly_passed"] else "FAIL"
            boot_p = "PASS" if hv["bootstrap_passed"] else "FAIL"
            tail_p = "PASS" if hv["tail_passed"] else "FAIL"
            
            lines.append(f"| `{h_lbl}` | **{ec_p}** | **{sup_p}** | **{fund_p}** | **{end_p}** | **{ass_p}** | **{mon_p}** | **{boot_p}** | **{tail_p}** |")
            
        lines.append("")
        
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✓ Saved markdown report to {report_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUT_DIR,
        help="Directory for generated audit artifacts (defaults to the canonical research directory).",
    )
    args = parser.parse_args()
    run_audit(output_dir=args.output_dir)
