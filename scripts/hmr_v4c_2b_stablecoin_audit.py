#!/usr/bin/env python3
"""HMR-V4C-2B: Stablecoin Liquidity Feature Audit."""
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
    192: {"label": "48h", "floor_bps": 20.0},
    672: {"label": "7d", "floor_bps": 50.0},
    1344: {"label": "14d", "floor_bps": 100.0}
}

SCAFFOLD_PATH = OUT_DIR / "v4a_outcome_scaffold.parquet"
STABLECOIN_PATH = OUT_DIR / "v4c_2b_stablecoin_history.parquet"
PREMIUM_PATH = OUT_DIR / "v4b_2b_premium_history.parquet"
FUNDING_PATH = REPO_ROOT / "data/historical_funding_rates.parquet"

# Pre-registered features to evaluate
FEATURE_COLS = [
    "SC1_stablecoin_supply_growth_7d",
    "SC2_stablecoin_supply_growth_30d",
    "SC3_net_issuance_7d_normalized",
    "SC4_net_issuance_percentile_90d"
]

def load_and_merge() -> pd.DataFrame:
    print("Loading datasets...")
    scaffold = pd.read_parquet(SCAFFOLD_PATH)
    stable = pd.read_parquet(STABLECOIN_PATH)
    premium = pd.read_parquet(PREMIUM_PATH)
    funding = pd.read_parquet(FUNDING_PATH)
    
    # Cast datetime columns to strict ns UTC
    for df, col in [(scaffold, "timestamp"), (stable, "available_at"), 
                    (premium, "available_at"), (funding, "timestamp")]:
        df[col] = pd.to_datetime(df[col], utc=True).astype("datetime64[ns, UTC]")
        
    merged_frames = []
    for coin in COINS:
        left = scaffold[scaffold["symbol"] == coin].sort_values("timestamp").copy()
        
        # 1. Merge stablecoin supply
        joined = pd.merge_asof(
            left, stable,
            left_on="timestamp", right_on="available_at",
            direction="backward"
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

def compute_targets_and_regimes(df: pd.DataFrame) -> pd.DataFrame:
    print("Reconstructing future realized volatilities and MAE...")
    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    
    # Horizontally shift closes to calculate forward returns
    df["return_192"] = df.groupby("symbol")["close"].transform(lambda x: x.shift(-192).sub(x).div(x))
    df["return_672"] = df.groupby("symbol")["close"].transform(lambda x: x.shift(-672).sub(x).div(x))
    df["return_1344"] = df.groupby("symbol")["close"].transform(lambda x: x.shift(-1344).sub(x).div(x))
    
    # Future realized volatilities
    ret_15m = df.groupby("symbol")["close"].transform(lambda x: x.pct_change())
    df["fwd_rv_192"] = ret_15m.shift(-192).rolling(192).std()
    df["fwd_rv_672"] = ret_15m.shift(-672).rolling(672).std()
    df["fwd_rv_1344"] = ret_15m.shift(-1344).rolling(1344).std()
    
    # Forward MAE (excursion) over next 7d (672 bars)
    close = df["close"]
    future_close = pd.concat([close.shift(-i) for i in range(1, 673)], axis=1)
    df["fwd_mae_672"] = (future_close.min(axis=1) - close) / close
    df["abs_fwd_mae_672"] = df["fwd_mae_672"].abs()
    
    # Endogenous Regimes
    df["return_4h"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(16))
    df["trend_18h"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(72))
    df["realized_vol"] = df.groupby("symbol")["close"].transform(lambda x: ret_15m.rolling(72, min_periods=10).std())
    
    return df

def run_block_bootstrap(df: pd.DataFrame, feature: str, target_col: str, polarity: int, bins: np.ndarray, block_length: int = 10, n_bootstrap: int = 200) -> float:
    np.random.seed(42)
    valid_data = df.dropna(subset=[feature, target_col]).copy()
    if len(valid_data) < 100:
        return 0.0
    valid_data["bin"] = pd.cut(valid_data[feature], bins=bins, labels=False, include_lowest=True)
    
    spreads = []
    n = len(valid_data)
    for _ in range(n_bootstrap):
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
    df = compute_targets_and_regimes(df)
    
    # Daily-Anchored dataset: exactly where timestamp == available_at
    df_daily = df[df["timestamp"] == df["available_at"]].copy()
    
    print(f"Total 15m Observations: {len(df)}")
    print(f"Unique Daily Stablecoin States: {len(df_daily)}")
    
    # Split periods
    df_a = df_daily[(df_daily["timestamp"] >= "2023-01-01") & (df_daily["timestamp"] < "2024-01-01")].copy()
    df_b = df_daily[(df_daily["timestamp"] >= "2024-01-01") & (df_daily["timestamp"] < "2024-07-01")].copy()
    df_c = df_daily[(df_daily["timestamp"] >= "2024-07-01") & (df_daily["timestamp"] < "2025-01-01")].copy()
    df_val = df_daily[(df_daily["timestamp"] >= "2024-01-01") & (df_daily["timestamp"] < "2025-01-01")].copy()
    
    audit_results = {
        "program": "HMR-V4C-2B",
        "source": "defillama_stablecoin_supply",
        "observation_count": len(df),
        "unique_source_state_count": len(df_daily),
        "model_training": "BLOCKED",
        "directional_audit": [],
        "volatility_audit": [],
        "risk_state_audit": []
    }
    
    # ==========================================
    # A. DIRECTIONAL AUDIT
    # ==========================================
    print("\n--- Running DIRECTIONAL Audit ---")
    for f in FEATURE_COLS:
        print(f"Auditing Directional Feature: {f}")
        horizon_verdicts = []
        polarity = 1 # High supply growth is expected to predict positive returns
        
        for h_bars, h_info in HORIZONS.items():
            target_col = f"return_{h_bars}"
            floor_bps = h_info["floor_bps"]
            lbl = h_info["label"]
            
            # Quintiles on Period A
            vals_a = df_a[f].dropna()
            if len(vals_a) < 50:
                continue
            bins = np.percentile(vals_a, [0, 20, 40, 60, 80, 100])
            bins = np.unique(bins)
            if len(bins) < 6:
                bins = np.linspace(vals_a.min(), vals_a.max(), 6)
                
            # Period B spread
            df_b_v = df_b.dropna(subset=[f, target_col]).copy()
            df_b_v["bin"] = pd.cut(df_b_v[f], bins=bins, labels=False, include_lowest=True)
            spread_b = polarity * (df_b_v.groupby("bin")[target_col].mean().get(4, 0.0) - df_b_v.groupby("bin")[target_col].mean().get(0, 0.0)) * 10000.0
            
            # Period C spread
            df_c_v = df_c.dropna(subset=[f, target_col]).copy()
            df_c_v["bin"] = pd.cut(df_c_v[f], bins=bins, labels=False, include_lowest=True)
            spread_c = polarity * (df_c_v.groupby("bin")[target_col].mean().get(4, 0.0) - df_c_v.groupby("bin")[target_col].mean().get(0, 0.0)) * 10000.0
            
            # Pooled spread
            df_val_v = df_val.dropna(subset=[f, target_col]).copy()
            df_val_v["bin"] = pd.cut(df_val_v[f], bins=bins, labels=False, include_lowest=True)
            pooled_spread = polarity * (df_val_v.groupby("bin")[target_col].mean().get(4, 0.0) - df_val_v.groupby("bin")[target_col].mean().get(0, 0.0)) * 10000.0
            
            # Period B/C stability
            r1_pass = (spread_b > 0) and (spread_c > 0)
            
            # Asset breadth
            r2_signs_ok = 0
            for coin in COINS:
                df_asset = df_val_v[df_val_v["symbol"] == coin]
                if len(df_asset) > 10:
                    means_asset = df_asset.groupby("bin")[target_col].mean()
                    a_spread = polarity * (means_asset.get(4, 0.0) - means_asset.get(0, 0.0)) * 10000.0
                    if a_spread > 0:
                        r2_signs_ok += 1
            r2_pass = (r2_signs_ok >= 2) and (pooled_spread > 0)
            
            # Bootstrap
            p_gt_0 = run_block_bootstrap(df_val, f, target_col, polarity, bins, block_length=10)
            r3_pass = (p_gt_0 >= 0.95)
            
            # Monthly stability
            monthly_spreads = []
            df_val_v["month"] = df_val_v["timestamp"].dt.strftime("%Y-%m")
            for m, df_m in df_val_v.groupby("month"):
                m_spread = polarity * (df_m.groupby("bin")[target_col].mean().get(4, 0.0) - df_m.groupby("bin")[target_col].mean().get(0, 0.0)) * 10000.0
                monthly_spreads.append(m_spread)
            pos_months = sum(1 for ms in monthly_spreads if ms > 0)
            r4_pass = (pos_months >= 7)
            if monthly_spreads:
                total_pos = sum(ms for ms in monthly_spreads if ms > 0)
                if total_pos > 0:
                    r4_pass = r4_pass and (max(monthly_spreads) / total_pos <= 0.70)
                    
            # Tail sensitivity
            f_win = f + "_winsorized"
            p1, p99 = np.percentile(df_val_v[f], 1), np.percentile(df_val_v[f], 99)
            df_val_v[f_win] = np.clip(df_val_v[f], p1, p99)
            win_spread = polarity * (df_val_v.groupby(pd.cut(df_val_v[f_win], bins=bins, labels=False, include_lowest=True))[target_col].mean().get(4, 0.0) - df_val_v.groupby(pd.cut(df_val_v[f_win], bins=bins, labels=False, include_lowest=True))[target_col].mean().get(0, 0.0)) * 10000.0
            r5_pass = (win_spread > 0) and (win_spread >= 0.30 * pooled_spread)
            
            robust_pass = r1_pass and r2_pass and r3_pass and r4_pass and r5_pass
            
            # Incremental Information Gate
            incremental_pass = False
            conditioned_spread = 0.0
            if pooled_spread >= floor_bps and robust_pass:
                # Conditioning bins on Period A
                trend_bins = np.percentile(df_a["trend_18h"].dropna(), [0, 33.3, 66.6, 100])
                vol_bins = np.percentile(df_a["realized_vol"].dropna(), [0, 33.3, 66.6, 100])
                fund_bins = np.percentile(df_a["funding_rate"].dropna(), [0, 33.3, 66.6, 100])
                prem_bins = np.percentile(df_a["premium_close"].dropna(), [0, 33.3, 66.6, 100])
                ret_bins = np.percentile(df_a["return_4h"].dropna(), [0, 33.3, 66.6, 100])
                
                df_val_v["regime_trend"] = pd.cut(df_val_v["trend_18h"], bins=np.unique(trend_bins), labels=False, include_lowest=True).fillna(1)
                df_val_v["regime_vol"] = pd.cut(df_val_v["realized_vol"], bins=np.unique(vol_bins), labels=False, include_lowest=True).fillna(1)
                df_val_v["regime_fund"] = pd.cut(df_val_v["funding_rate"], bins=np.unique(fund_bins), labels=False, include_lowest=True).fillna(1)
                df_val_v["regime_prem"] = pd.cut(df_val_v["premium_close"], bins=np.unique(prem_bins), labels=False, include_lowest=True).fillna(1)
                df_val_v["regime_ret"] = pd.cut(df_val_v["return_4h"], bins=np.unique(ret_bins), labels=False, include_lowest=True).fillna(1)
                
                df_val_v["regime_code"] = (
                    df_val_v["regime_trend"].astype(str) + "_" +
                    df_val_v["regime_vol"].astype(str) + "_" +
                    df_val_v["regime_fund"].astype(str) + "_" +
                    df_val_v["regime_prem"].astype(str) + "_" +
                    df_val_v["regime_ret"].astype(str)
                )
                
                cell_spreads, cell_weights = [], []
                for r_code, df_cell in df_val_v.groupby("regime_code"):
                    if len(df_cell) < 10:
                        continue
                    m_cell = df_cell.groupby("bin")[target_col].mean()
                    c_spread = polarity * (m_cell.get(4, 0.0) - m_cell.get(0, 0.0)) * 10000.0
                    cell_spreads.append(c_spread)
                    cell_weights.append(len(df_cell))
                    
                if cell_weights:
                    conditioned_spread = float(np.average(cell_spreads, weights=cell_weights))
                    incremental_pass = (conditioned_spread > 0) and (conditioned_spread >= 0.50 * pooled_spread)
                    
            # Verdict
            if pooled_spread < floor_bps:
                verdict = "REJECT_NO_ECONOMIC_INFORMATION"
            elif not robust_pass:
                verdict = "REJECT_UNSTABLE_INFORMATION"
            elif not incremental_pass:
                verdict = "REJECT_REDUNDANT_INFORMATION"
            else:
                verdict = "PROMOTE_DIRECTIONAL_INFORMATION"
                
            horizon_verdicts.append({
                "horizon": lbl,
                "floor_bps": floor_bps,
                "pooled_spread_bps": float(pooled_spread),
                "conditioned_spread_bps": float(conditioned_spread),
                "r1_period_stability": bool(r1_pass),
                "r2_asset_breadth": bool(r2_pass),
                "r3_bootstrap_p_gt_0": float(p_gt_0),
                "r4_positive_months": pos_months,
                "r5_winsorized_spread_bps": float(win_spread),
                "incremental_pass": bool(incremental_pass),
                "verdict": verdict
            })
            
        best_verdict = "REJECT_NO_ECONOMIC_INFORMATION"
        best_horizon = None
        for hv in horizon_verdicts:
            if hv["verdict"] == "PROMOTE_DIRECTIONAL_INFORMATION":
                best_verdict = "PROMOTE_DIRECTIONAL_INFORMATION"
                best_horizon = hv["horizon"]
                break
                
        audit_results["directional_audit"].append({
            "feature": f,
            "verdict": best_verdict,
            "best_horizon": best_horizon,
            "horizons": horizon_verdicts
        })
        
    # ==========================================
    # B. VOLATILITY AUDIT
    # ==========================================
    print("\n--- Running VOLATILITY Audit ---")
    for f in FEATURE_COLS:
        print(f"Auditing Volatility Feature: {f}")
        horizon_verdicts = []
        
        for h_bars, h_info in HORIZONS.items():
            target_col = f"fwd_rv_{h_bars}" # Future realized volatility target
            lbl = h_info["label"]
            
            vals_a = df_a[f].dropna()
            if len(vals_a) < 50:
                continue
            bins = np.percentile(vals_a, [0, 20, 40, 60, 80, 100])
            bins = np.unique(bins)
            if len(bins) < 6:
                bins = np.linspace(vals_a.min(), vals_a.max(), 6)
                
            df_val_v = df_val.dropna(subset=[f, target_col]).copy()
            df_val_v["bin"] = pd.cut(df_val_v[f], bins=bins, labels=False, include_lowest=True)
            q_means = df_val_v.groupby("bin")[target_col].mean()
            
            q5_val = q_means.get(4, 0.0)
            q4_val = q_means.get(3, 0.0)
            q2_val = q_means.get(1, 0.0)
            q1_val = q_means.get(0, 0.0)
            monotonic_pass = (q5_val > q4_val) and (q4_val > q2_val) and (q2_val > q1_val)
            
            # Rank association
            df_b_v = df_b.dropna(subset=[f, target_col]).copy()
            df_c_v = df_c.dropna(subset=[f, target_col]).copy()
            rank_b = df_b_v[f].corr(df_b_v[target_col], method="spearman")
            rank_c = df_c_v[f].corr(df_c_v[target_col], method="spearman")
            rank_pass = (rank_b > 0) and (rank_c > 0)
            
            # Material spread
            vol_spread = (q5_val - q1_val) * 10000.0
            p_gt_0 = run_block_bootstrap(df_val, f, target_col, 1, bins, block_length=10)
            material_pass = (vol_spread > 0) and (p_gt_0 >= 0.95)
            
            verdict = "PROMOTE_VOLATILITY_INFORMATION" if (monotonic_pass and rank_pass and material_pass) else "REJECT_NO_INFORMATION"
            
            horizon_verdicts.append({
                "horizon": lbl,
                "q5_rv_bps": float(q5_val * 10000.0),
                "q1_rv_bps": float(q1_val * 10000.0),
                "spread_bps": float(vol_spread),
                "monotonic_pass": bool(monotonic_pass),
                "rank_corr_b": float(rank_b),
                "rank_corr_c": float(rank_c),
                "bootstrap_p_gt_0": float(p_gt_0),
                "verdict": verdict
            })
            
        best_verdict = "REJECT_NO_INFORMATION"
        best_horizon = None
        for hv in horizon_verdicts:
            if hv["verdict"] == "PROMOTE_VOLATILITY_INFORMATION":
                best_verdict = "PROMOTE_VOLATILITY_INFORMATION"
                best_horizon = hv["horizon"]
                break
                
        audit_results["volatility_audit"].append({
            "feature": f,
            "verdict": best_verdict,
            "best_horizon": best_horizon,
            "horizons": horizon_verdicts
        })
        
    # ==========================================
    # C. RISK STATE AUDIT
    # ==========================================
    print("\n--- Running RISK STATE Audit ---")
    risk_features = ["SC1_stablecoin_supply_growth_7d", "SC3_net_issuance_7d_normalized"]
    for f in risk_features:
        print(f"Auditing Risk State Feature: {f}")
        horizon_verdicts = []
        
        # Max Adverse Excursion (MAE) target over next 7d (672 bars)
        target_col = "abs_fwd_mae_672"
        lbl = "7d"
        
        vals_a = df_a[f].dropna()
        if len(vals_a) < 50:
            continue
        bins = np.percentile(vals_a, [0, 20, 40, 60, 80, 100])
        bins = np.unique(bins)
        if len(bins) < 6:
            bins = np.linspace(vals_a.min(), vals_a.max(), 6)
            
        # RS1: State info - low growth Q1 (stablecoin contraction) has higher MAE than Q5 (high growth)
        # So spread is calculated as Q1_mae - Q5_mae
        df_val_v = df_val.dropna(subset=[f, target_col]).copy()
        df_val_v["bin"] = pd.cut(df_val_v[f], bins=bins, labels=False, include_lowest=True)
        q_means = df_val_v.groupby("bin")[target_col].mean()
        q5_mae = q_means.get(4, 0.0)
        q1_mae = q_means.get(0, 0.0)
        
        # Period B & C spreads separately
        df_b_v = df_b.dropna(subset=[f, target_col]).copy()
        df_b_v["bin"] = pd.cut(df_b_v[f], bins=bins, labels=False, include_lowest=True)
        b_spread = df_b_v.groupby("bin")[target_col].mean().get(0, 0.0) - df_b_v.groupby("bin")[target_col].mean().get(4, 0.0)
        
        df_c_v = df_c.dropna(subset=[f, target_col]).copy()
        df_c_v["bin"] = pd.cut(df_c_v[f], bins=bins, labels=False, include_lowest=True)
        c_spread = df_c_v.groupby("bin")[target_col].mean().get(0, 0.0) - df_c_v.groupby("bin")[target_col].mean().get(4, 0.0)
        
        rs1_pass = (q1_mae > q5_mae) and (b_spread > 0) and (c_spread > 0)
        
        # RS2: Economic utility - filter strategy return (veto long signals when supply is contracting, i.e. bin == 0)
        # Baseline EV (18h return)
        baseline_ev = df_val_v[df_val_v["long_30_20"] == 1]["return_72"].mean()
        # Vetoed EV
        vetoed_ev = df_val_v[(df_val_v["long_30_20"] == 1) & (df_val_v["bin"] > 0)]["return_72"].mean()
        
        rs2_pass = False
        if not np.isnan(baseline_ev) and not np.isnan(vetoed_ev):
            rs2_pass = (vetoed_ev > baseline_ev)
            
        verdict = "PROMOTE_RISK_STATE_INFORMATION" if (rs1_pass and rs2_pass) else "REJECT_NO_INFORMATION"
        
        horizon_verdicts.append({
            "horizon": lbl,
            "q1_mae_bps": float(q1_mae * 10000.0),
            "q5_mae_bps": float(q5_mae * 10000.0),
            "rs1_state_info_pass": bool(rs1_pass),
            "baseline_strategy_ev_bps": float(baseline_ev * 10000.0) if not np.isnan(baseline_ev) else 0.0,
            "vetoed_strategy_ev_bps": float(vetoed_ev * 10000.0) if not np.isnan(vetoed_ev) else 0.0,
            "rs2_utility_pass": bool(rs2_pass),
            "verdict": verdict
        })
        
        audit_results["risk_state_audit"].append({
            "feature": f,
            "verdict": verdict,
            "best_horizon": lbl if verdict == "PROMOTE_RISK_STATE_INFORMATION" else None,
            "horizons": horizon_verdicts
        })
        
    # Save JSON results
    json_path = OUT_DIR / "v4c_2b_stablecoin_audit.json"
    with open(json_path, "w", encoding="utf-8") as f_out:
        json.dump(audit_results, f_out, indent=2)
    print(f"✓ Saved JSON audit results to {json_path}")
    
    # Save Report Markdown
    write_md_report(audit_results)

def write_md_report(results: dict[str, Any]):
    report_path = OUT_DIR / "v4c_2b_stablecoin_report.md"
    
    lines = [
        f"# {results['program']} Stablecoin Liquidity Feature Audit Report",
        "",
        "## Governance Rationale & Verdict Summary",
        "",
        f"- **Program**: `{results['program']}`",
        f"- **Source**: `{results['source']}`",
        f"- **Observation Count**: `{results['observation_count']}` (15m bars)",
        f"- **Unique Daily Stablecoin States**: `{results['unique_source_state_count']}` (deduplicated statistical units)",
        f"- **Model Training**: `{results['model_training']}`",
        "",
        "### 1. Directional Audit (H5-D)",
        "",
        "| Feature | Overall Verdict | Best Horizon | Max Conditioned Spread |",
        "| :--- | :--- | :---: | :---: |"
    ]
    
    for f in results["directional_audit"]:
        max_cond = max([h["conditioned_spread_bps"] for h in f["horizons"]])
        lines.append(f"| `{f['feature']}` | **{f['verdict']}** | `{f['best_horizon']}` | {max_cond:.4f} bps |")
        
    lines.extend([
        "",
        "### 2. Volatility Audit (H5-V)",
        "",
        "| Feature | Overall Verdict | Best Horizon | Max Spread (Q5-Q1) | Bootstrap P |",
        "| :--- | :--- | :---: | :---: | :---: |"
    ])
    
    for f in results["volatility_audit"]:
        max_spread = max([h["spread_bps"] for h in f["horizons"]])
        max_p = max([h["bootstrap_p_gt_0"] for h in f["horizons"]])
        lines.append(f"| `{f['feature']}` | **{f['verdict']}** | `{f['best_horizon']}` | {max_spread:.4f} bps | {max_p:.1%} |")
        
    lines.extend([
        "",
        "### 3. Risk State Audit (H5-R)",
        "",
        "| Feature | Overall Verdict | Target MAE | RS1 (State Pass) | Baseline EV | Vetoed EV | RS2 (Utility) |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: |"
    ])
    
    for f in results["risk_state_audit"]:
        h = f["horizons"][0]
        lines.append(
            f"| `{f['feature']}` | **{f['verdict']}** | `7d MAE` | **{h['rs1_state_info_pass']}** | {h['baseline_strategy_ev_bps']:.2f} bps | {h['vetoed_strategy_ev_bps']:.2f} bps | **{h['rs2_utility_pass']}** |"
        )
        
    lines.extend([
        "",
        "## Conclusion & Next Steps",
        "",
        "If a feature has been promoted under any information class, it is eligible for strategy-level integration:",
        "- **PROMOTE_DIRECTIONAL_INFORMATION**: Eligible as signal/predictor.",
        "- **PROMOTE_VOLATILITY_INFORMATION**: Eligible for sizing/target width scaling.",
        "- **PROMOTE_RISK_STATE_INFORMATION**: Eligible for regime veto/gating.",
        "",
        "Model training remains strictly **BLOCKED**."
    ])
    
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✓ Saved Markdown report to {report_path}")

if __name__ == "__main__":
    run_audit()
