#!/usr/bin/env python3
"""HMR-V4B-4B: Aggressive Trade Flow Feature and Economic Audit."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"

COINS = ["BTC", "ETH", "BNB"]
HORIZONS = {
    32: {"label": "8h", "floor_bps": 10.0},
    72: {"label": "18h", "floor_bps": 15.0},
    192: {"label": "48h", "floor_bps": 20.0}
}

# Paths to inputs
SCAFFOLD_PATH = OUT_DIR / "v4a_outcome_scaffold.parquet"
TRADE_FLOW_PATH = OUT_DIR / "v4b_4b_trade_flow_history.parquet"
PREMIUM_PATH = OUT_DIR / "v4b_2b_premium_history.parquet"
FUNDING_PATH = REPO_ROOT / "data/historical_funding_rates.parquet"

def load_and_merge() -> pd.DataFrame:
    print("Loading datasets...")
    scaffold = pd.read_parquet(SCAFFOLD_PATH)
    trade_flow = pd.read_parquet(TRADE_FLOW_PATH)
    premium = pd.read_parquet(PREMIUM_PATH)
    funding = pd.read_parquet(FUNDING_PATH)
    
    # Cast datetime columns to strict ns unit to avoid MergeError
    for df_item, col in [(scaffold, "timestamp"), (trade_flow, "available_at"), 
                    (trade_flow, "open_time"), (premium, "available_at"),
                    (funding, "timestamp")]:
        df_item[col] = pd.to_datetime(df_item[col], utc=True).astype("datetime64[ns, UTC]")
        
    merged_frames = []
    
    for coin in COINS:
        left = scaffold[scaffold["symbol"] == coin].sort_values("timestamp").copy()
        
        # 1. Merge trade flow
        tf_df = trade_flow[trade_flow["symbol"] == coin].sort_values("available_at").copy()
        joined = pd.merge_asof(
            left, tf_df[["available_at", "symbol", "taker_buy_notional", "taker_sell_notional", "taker_buy_qty", "taker_sell_qty"]],
            left_on="timestamp", right_on="available_at",
            by="symbol", direction="backward"
        )
        
        # 2. Merge premium
        prem_df = premium[premium["symbol"] == coin][["available_at", "premium_close"]].sort_values("available_at").copy()
        joined = pd.merge_asof(
            joined, prem_df,
            left_on="timestamp", right_on="available_at",
            direction="backward", suffixes=("", "_prem")
        )
        if "available_at_prem" in joined.columns:
            joined = joined.drop(columns=["available_at_prem"])
            
        # 3. Merge funding
        fund_df = funding[funding["symbol"] == coin][["timestamp", "funding_rate"]].sort_values("timestamp").copy()
        joined = pd.merge_asof(
            joined, fund_df,
            on="timestamp", direction="backward"
        )
        
        merged_frames.append(joined)
        
    df = pd.concat(merged_frames, ignore_index=True)
    return df

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    print("Computing aggressive trade flow features (TF1-TF5)...")
    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    
    # TF1: taker_imbalance_15m
    buy = df["taker_buy_notional"]
    sell = df["taker_sell_notional"]
    df["TF1_taker_imbalance_15m"] = np.where(buy + sell > 0, (buy - sell) / (buy + sell), 0.0)
    
    # TF2: rolling 1h imbalance (4 bars)
    grouped = df.groupby("symbol")
    sum_buy_1h = grouped["taker_buy_notional"].transform(lambda x: x.rolling(4, min_periods=1).sum())
    sum_sell_1h = grouped["taker_sell_notional"].transform(lambda x: x.rolling(4, min_periods=1).sum())
    df["TF2_taker_imbalance_1h"] = np.where(sum_buy_1h + sum_sell_1h > 0, (sum_buy_1h - sum_sell_1h) / (sum_buy_1h + sum_sell_1h), 0.0)
    
    # TF3: signed_notional_zscore (7d = 672 bars)
    signed_notional = buy - sell
    mean_7d = grouped["taker_buy_notional"].transform(lambda x: signed_notional.rolling(672, min_periods=100).mean().shift(1))
    std_7d = grouped["taker_buy_notional"].transform(lambda x: signed_notional.rolling(672, min_periods=100).std().shift(1))
    df["TF3_signed_notional_zscore"] = np.where(std_7d > 0, (signed_notional - mean_7d) / std_7d, 0.0)
    
    # TF4: aggressive_volume_percentile_30d (30d = 2880 bars)
    agg_vol = buy + sell
    df["TF4_aggressive_volume_percentile_30d"] = grouped["taker_buy_notional"].transform(
        lambda x: agg_vol.rolling(2880, min_periods=100).rank(pct=True)
    ).fillna(0.5)
    
    # TF5: flow_acceleration_1h
    df["TF5_flow_acceleration_1h"] = df.groupby("symbol")["TF2_taker_imbalance_1h"].diff(4).fillna(0.0)
    
    # 4h return for momentum regime
    df["return_4h"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(16))
    
    # Realized volatility (rolling 72 bars std of returns)
    ret_15m = df.groupby("symbol")["close"].transform(lambda x: x.pct_change())
    df["realized_vol"] = df.groupby("symbol")["close"].transform(lambda x: ret_15m.rolling(72, min_periods=10).std())
    
    # Trend (18h return = 72 bars)
    df["trend_18h"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(72))
    
    # Reconstruct return_192 for the 48h horizon
    df["return_192"] = df.groupby("symbol")["close"].transform(lambda x: x.shift(-192).sub(x).div(x))
    
    return df

def run_block_bootstrap(df: pd.DataFrame, feature: str, target_col: str, polarity: int, bins: np.ndarray, block_length: int = 192, n_bootstrap: int = 200) -> float:
    # Overlapping block bootstrap to account for serial correlation of horizons
    valid_data = df.dropna(subset=[feature, target_col]).copy()
    if len(valid_data) < 500:
        return 0.0
        
    # Pre-assign bins
    valid_data["bin"] = pd.cut(valid_data[feature], bins=bins, labels=False, include_lowest=True)
    
    spreads = []
    n = len(valid_data)
    
    for _ in range(n_bootstrap):
        # Sample random blocks with replacement
        bootstrap_indices = []
        while len(bootstrap_indices) < n:
            start = np.random.randint(0, n - block_length)
            bootstrap_indices.extend(range(start, start + block_length))
        bootstrap_indices = bootstrap_indices[:n]
        
        sample = valid_data.iloc[bootstrap_indices]
        q_means = sample.groupby("bin")[target_col].mean()
        
        q5 = q_means.get(4, np.nan)
        q1 = q_means.get(0, np.nan)
        
        if not np.isnan(q5) and not np.isnan(q1):
            spreads.append(polarity * (q5 - q1))
            
    if not spreads:
        return 0.0
    return float(np.mean(np.array(spreads) > 0))

def run_audit():
    df = load_and_merge()
    df = compute_features(df)
    
    # Split periods
    # Period A: 2023-01-01 to 2023-12-31
    # Period B: 2024-01-01 to 2024-06-30
    # Period C: 2024-07-01 to 2024-12-31
    df_a = df[(df["timestamp"] >= "2023-01-01") & (df["timestamp"] < "2024-01-01")].copy()
    df_b = df[(df["timestamp"] >= "2024-01-01") & (df["timestamp"] < "2024-07-01")].copy()
    df_c = df[(df["timestamp"] >= "2024-07-01") & (df["timestamp"] < "2025-01-01")].copy()
    df_val = df[(df["timestamp"] >= "2024-01-01") & (df["timestamp"] < "2025-01-01")].copy()
    
    features = [
        "TF1_taker_imbalance_15m",
        "TF2_taker_imbalance_1h",
        "TF3_signed_notional_zscore",
        "TF4_aggressive_volume_percentile_30d",
        "TF5_flow_acceleration_1h"
    ]
    
    verdicts = []
    
    for f in features:
        print(f"\nAuditing feature: {f}")
        feature_verdicts = []
        
        for h_bars, h_info in HORIZONS.items():
            target_col = f"return_{h_bars}"
            floor_bps = h_info["floor_bps"]
            lbl = h_info["label"]
            
            # Step 1: Compute bins (quintiles) on Period A
            vals_a = df_a[f].dropna()
            if len(vals_a) < 100:
                continue
            bins = np.percentile(vals_a, [0, 20, 40, 60, 80, 100])
            # Ensure unique bins to avoid binning errors
            bins = np.unique(bins)
            if len(bins) < 6:
                # Add tiny perturbations to make edges unique
                bins = np.linspace(vals_a.min(), vals_a.max(), 6)
                
            # Determine Polarity on Period A
            corr_a = df_a[f].corr(df_a[target_col])
            polarity = -1 if corr_a < 0 else 1
            
            # Bin validation data
            # Period B
            df_b_valid = df_b.dropna(subset=[f, target_col]).copy()
            df_b_valid["bin"] = pd.cut(df_b_valid[f], bins=bins, labels=False, include_lowest=True)
            means_b = df_b_valid.groupby("bin")[target_col].mean()
            spread_b = polarity * (means_b.get(4, 0.0) - means_b.get(0, 0.0)) * 10000.0
            
            # Period C
            df_c_valid = df_c.dropna(subset=[f, target_col]).copy()
            df_c_valid["bin"] = pd.cut(df_c_valid[f], bins=bins, labels=False, include_lowest=True)
            means_c = df_c_valid.groupby("bin")[target_col].mean()
            spread_c = polarity * (means_c.get(4, 0.0) - means_c.get(0, 0.0)) * 10000.0
            
            # Pooled Validation (Period B + C)
            df_val_valid = df_val.dropna(subset=[f, target_col]).copy()
            df_val_valid["bin"] = pd.cut(df_val_valid[f], bins=bins, labels=False, include_lowest=True)
            means_val = df_val_valid.groupby("bin")[target_col].mean()
            pooled_spread = polarity * (means_val.get(4, 0.0) - means_val.get(0, 0.0)) * 10000.0
            
            # Correlations
            corr_recent = float(df_val_valid[f].corr(df_val_valid["return_4h"]))
            corr_future = float(df_val_valid[f].corr(df_val_valid[target_col]))
            
            # Robustness Checks
            # R1: Period Stability
            r1_pass = (spread_b > 0) and (spread_c > 0)
            
            # R2: Asset Breadth
            asset_spreads = {}
            r2_signs_ok = 0
            for coin in COINS:
                df_asset = df_val_valid[df_val_valid["symbol"] == coin]
                means_asset = df_asset.groupby("bin")[target_col].mean()
                a_spread = polarity * (means_asset.get(4, 0.0) - means_asset.get(0, 0.0)) * 10000.0
                asset_spreads[coin] = a_spread
                if a_spread > 0:
                    r2_signs_ok += 1
            r2_pass = (r2_signs_ok >= 2) and (pooled_spread > 0)
            
            # R3: Block Bootstrap
            p_gt_0 = run_block_bootstrap(df_val, f, target_col, polarity, bins, block_length=192, n_bootstrap=200)
            r3_pass = (p_gt_0 >= 0.95)
            
            # R4: Monthly Stability
            monthly_spreads = []
            df_val_valid["month"] = df_val_valid["timestamp"].dt.strftime("%Y-%m")
            for m, df_m in df_val_valid.groupby("month"):
                means_m = df_m.groupby("bin")[target_col].mean()
                m_spread = polarity * (means_m.get(4, 0.0) - means_m.get(0, 0.0)) * 10000.0
                monthly_spreads.append(m_spread)
            
            pos_months = sum(1 for ms in monthly_spreads if ms > 0)
            median_ms = float(np.median(monthly_spreads)) if monthly_spreads else 0.0
            worst_ms = float(np.min(monthly_spreads)) if monthly_spreads else 0.0
            
            r4_pass = (pos_months >= 7)
            if monthly_spreads:
                total_pos = sum(ms for ms in monthly_spreads if ms > 0)
                if total_pos > 0:
                    r4_pass = r4_pass and (max(monthly_spreads) / total_pos <= 0.70)
                    
            # R5: Tail Sensitivity
            f_win = f + "_winsorized"
            p1 = np.percentile(df_val_valid[f], 1)
            p99 = np.percentile(df_val_valid[f], 99)
            df_val_valid[f_win] = np.clip(df_val_valid[f], p1, p99)
            
            means_win = df_val_valid.groupby(pd.cut(df_val_valid[f_win], bins=bins, labels=False, include_lowest=True))[target_col].mean()
            win_spread = polarity * (means_win.get(4, 0.0) - means_win.get(0, 0.0)) * 10000.0
            r5_pass = (win_spread > 0) and (win_spread >= 0.30 * pooled_spread)
            
            robust_pass = r1_pass and r2_pass and r3_pass and r4_pass and r5_pass
            
            # Incremental Gate
            # We condition on trend, volatility, funding, premium, and recent return regimes
            incremental_pass = False
            conditioned_spread = 0.0
            
            if pooled_spread >= floor_bps:
                # Pre-calculate conditioning bins on Period A
                trend_bins = np.percentile(df_a["trend_18h"].dropna(), [0, 33.3, 66.6, 100])
                vol_bins = np.percentile(df_a["realized_vol"].dropna(), [0, 33.3, 66.6, 100])
                fund_bins = np.percentile(df_a["funding_rate"].dropna(), [0, 33.3, 66.6, 100])
                prem_bins = np.percentile(df_a["premium_close"].dropna(), [0, 33.3, 66.6, 100])
                ret_bins = np.percentile(df_a["return_4h"].dropna(), [0, 33.3, 66.6, 100])
                
                # Assign regimes
                df_val_valid["regime_trend"] = pd.cut(df_val_valid["trend_18h"], bins=np.unique(trend_bins), labels=False, include_lowest=True).fillna(1)
                df_val_valid["regime_vol"] = pd.cut(df_val_valid["realized_vol"], bins=np.unique(vol_bins), labels=False, include_lowest=True).fillna(1)
                df_val_valid["regime_fund"] = pd.cut(df_val_valid["funding_rate"], bins=np.unique(fund_bins), labels=False, include_lowest=True).fillna(1)
                df_val_valid["regime_prem"] = pd.cut(df_val_valid["premium_close"], bins=np.unique(prem_bins), labels=False, include_lowest=True).fillna(1)
                df_val_valid["regime_ret"] = pd.cut(df_val_valid["return_4h"], bins=np.unique(ret_bins), labels=False, include_lowest=True).fillna(1)
                
                # We aggregate spreads across all conditioning dimensions
                cell_spreads = []
                cell_weights = []
                
                # Generate cross-sectional regime codes
                df_val_valid["regime_code"] = (
                    df_val_valid["regime_trend"].astype(str) + "_" +
                    df_val_valid["regime_vol"].astype(str) + "_" +
                    df_val_valid["regime_fund"].astype(str) + "_" +
                    df_val_valid["regime_prem"].astype(str) + "_" +
                    df_val_valid["regime_ret"].astype(str)
                )
                
                for r_code, df_cell in df_val_valid.groupby("regime_code"):
                    if len(df_cell) < 20:
                        continue
                    m_cell = df_cell.groupby("bin")[target_col].mean()
                    c_spread = polarity * (m_cell.get(4, 0.0) - m_cell.get(0, 0.0)) * 10000.0
                    cell_spreads.append(c_spread)
                    cell_weights.append(len(df_cell))
                    
                if cell_weights:
                    conditioned_spread = float(np.average(cell_spreads, weights=cell_weights))
                    # Pass condition: same sign and at least 50% magnitude of raw pooled spread
                    incremental_pass = (conditioned_spread > 0) and (conditioned_spread >= 0.50 * pooled_spread)
                else:
                    conditioned_spread = 0.0
                    incremental_pass = False
            
            # Final Verdict Selection
            if pooled_spread < floor_bps:
                verdict = "REJECT_NO_ECONOMIC_INFORMATION"
            elif not robust_pass:
                verdict = "REJECT_UNSTABLE_INFORMATION"
            elif not incremental_pass:
                verdict = "REJECT_REDUNDANT_ENDOGENOUS_INFORMATION"
            else:
                verdict = "PROMOTE_INDEPENDENT_INFORMATION"
                
            horizon_verdict = {
                "horizon": lbl,
                "floor_bps": floor_bps,
                "spread_b_bps": float(spread_b),
                "spread_c_bps": float(spread_c),
                "pooled_spread_bps": float(pooled_spread),
                "conditioned_spread_bps": float(conditioned_spread),
                "polarity": int(polarity),
                "corr_recent_momentum": corr_recent,
                "corr_future_return": corr_future,
                "r1_period_stability": bool(r1_pass),
                "r2_asset_breadth": bool(r2_pass),
                "r2_asset_spreads": {k: float(v) for k, v in asset_spreads.items()},
                "r3_bootstrap_p_gt_0": float(p_gt_0),
                "r3_bootstrap_pass": bool(r3_pass),
                "r4_monthly_stability_pass": bool(r4_pass),
                "r4_positive_months": pos_months,
                "r5_winsorized_spread_bps": float(win_spread),
                "r5_winsorized_pass": bool(r5_pass),
                "incremental_pass": bool(incremental_pass),
                "verdict": verdict
            }
            
            feature_verdicts.append(horizon_verdict)
            
        # Determine overall feature verdict
        best_verdict = "REJECT_NO_ECONOMIC_INFORMATION"
        best_horizon = None
        for hv in feature_verdicts:
            v = hv["verdict"]
            # Rank verdicts: PROMOTE > REJECT_REDUNDANT > REJECT_UNSTABLE > REJECT_NO_ECONOMIC
            if v == "PROMOTE_INDEPENDENT_INFORMATION":
                best_verdict = "PROMOTE_INDEPENDENT_INFORMATION"
                best_horizon = hv["horizon"]
                break
            elif v == "REJECT_REDUNDANT_ENDOGENOUS_INFORMATION" and best_verdict != "PROMOTE_INDEPENDENT_INFORMATION":
                best_verdict = "REJECT_REDUNDANT_ENDOGENOUS_INFORMATION"
                best_horizon = hv["horizon"]
            elif v == "REJECT_UNSTABLE_INFORMATION" and best_verdict not in ["PROMOTE_INDEPENDENT_INFORMATION", "REJECT_REDUNDANT_ENDOGENOUS_INFORMATION"]:
                best_verdict = "REJECT_UNSTABLE_INFORMATION"
                best_horizon = hv["horizon"]
                
        verdicts.append({
            "feature": f,
            "verdict": best_verdict,
            "best_horizon": best_horizon,
            "horizons": feature_verdicts
        })
        
    # Write JSON results
    audit_output = {
        "program": "HMR-V4B-4B",
        "source": "binance_um_trade_flow",
        "information_family": "MICROSTRUCTURE_FLOW",
        "provenance": "MARKET_OBSERVED",
        "model_training": "BLOCKED",
        "feature_verdicts": verdicts
    }
    
    json_path = OUT_DIR / "v4b_4b_trade_flow_audit.json"
    with open(json_path, "w", encoding="utf-8") as f_out:
        json.dump(audit_output, f_out, indent=2)
    print(f"✓ Saved JSON audit results to {json_path}")
    
    # Write Markdown Report
    write_md_report(audit_output)

def write_md_report(output: dict[str, Any]):
    report_path = OUT_DIR / "v4b_4b_trade_flow_report.md"
    
    lines = [
        f"# {output['program']} Aggressive Trade Flow Feature Audit Report",
        "",
        "## Governance Rationale & Verdict Summary",
        "",
        f"- **Program**: `{output['program']}`",
        f"- **Source**: `{output['source']}`",
        f"- **Information Family**: `{output['information_family']}`",
        f"- **Provenance Status**: `{output['provenance']}`",
        f"- **Model Training**: `{output['model_training']}`",
        "",
        "### Overall Feature Verdicts Table",
        "",
        "| Feature | Overall Verdict | Best Horizon | Max Conditioned Spread |",
        "| :--- | :--- | :---: | :---: |"
    ]
    
    for fv in output["feature_verdicts"]:
        max_cond = max([h["conditioned_spread_bps"] for h in fv["horizons"]])
        lines.append(f"| `{fv['feature']}` | **{fv['verdict']}** | `{fv['best_horizon']}` | {max_cond:.4f} bps |")
        
    lines.extend([
        "",
        "## Detailed Horizon Gates Status",
        ""
    ])
    
    for fv in output["feature_verdicts"]:
        lines.append(f"### Feature: `{fv['feature']}`")
        lines.append("")
        lines.append("| Horizon | Raw Spread | R1 (Period) | R2 (Breadth) | R3 (Boot. P) | R4 (Months) | R5 (Winsor.) | Incremental | Verdict |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |")
        
        for h in fv["horizons"]:
            r1 = "PASS" if h["r1_period_stability"] else "FAIL"
            r2 = "PASS" if h["r2_asset_breadth"] else "FAIL"
            r3_p = f"{h['r3_bootstrap_p_gt_0']:.1%}"
            r4 = f"{h['r4_positive_months']}/12"
            r5 = f"{h['r5_winsorized_spread_bps']:.2f} bps"
            inc = f"{h['conditioned_spread_bps']:.2f} bps"
            lines.append(
                f"| `{h['horizon']}` | {h['pooled_spread_bps']:.2f} bps | **{r1}** | **{r2}** | {r3_p} | {r4} | {r5} | {inc} | **{h['verdict']}** |"
            )
        lines.append("")
        
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✓ Saved Markdown report to {report_path}")

if __name__ == "__main__":
    run_audit()
