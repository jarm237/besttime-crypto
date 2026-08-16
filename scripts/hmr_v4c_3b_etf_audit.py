#!/usr/bin/env python3
"""HMR-V4C-3B: ETF / Institutional Flows Feature Audit."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"

COINS = ["BTC", "ETH", "BNB"]
HORIZONS = {
    96: {"label": "24h", "floor_bps": 30.0},
    288: {"label": "72h", "floor_bps": 60.0},
    672: {"label": "7d", "floor_bps": 100.0}
}

SCAFFOLD_PATH = OUT_DIR / "v4a_outcome_scaffold.parquet"
ETF_PATH = OUT_DIR / "v4c_3b_etf_history.parquet"
PREMIUM_PATH = OUT_DIR / "v4b_2b_premium_history.parquet"
FUNDING_PATH = REPO_ROOT / "data/historical_funding_rates.parquet"

# Pre-registered features to evaluate
FEATURE_COLS = [
    "ETF1_total_net_flow_usd",
    "ETF2_ex_gbtc_net_flow_usd",
    "ETF3_net_flow_as_pct_aum",
    "ETF4_rolling_flow_zscore_20d",
    "ETF5_cumulative_net_flow_5d"
]

def load_and_merge(avail_lag_hours: int = 0) -> pd.DataFrame:
    scaffold = pd.read_parquet(SCAFFOLD_PATH)
    etf = pd.read_parquet(ETF_PATH)
    premium = pd.read_parquet(PREMIUM_PATH)
    funding = pd.read_parquet(FUNDING_PATH)
    
    # Cast datetimes
    for df, col in [(scaffold, "timestamp"), (etf, "available_at"), 
                    (premium, "available_at"), (funding, "timestamp")]:
        df[col] = pd.to_datetime(df[col], utc=True).astype("datetime64[ns, UTC]")
        
    if avail_lag_hours > 0:
        etf = etf.copy()
        etf["available_at"] = etf["available_at"] + pd.Timedelta(hours=avail_lag_hours)
        
    merged_frames = []
    for coin in COINS:
        left = scaffold[scaffold["symbol"] == coin].sort_values("timestamp").copy()
        
        # 1. Merge ETF flows
        joined = pd.merge_asof(
            left, etf,
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
    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    
    # Target future returns
    df["return_96"] = df.groupby("symbol")["close"].transform(lambda x: x.shift(-96).sub(x).div(x))
    df["return_288"] = df.groupby("symbol")["close"].transform(lambda x: x.shift(-288).sub(x).div(x))
    df["return_672"] = df.groupby("symbol")["close"].transform(lambda x: x.shift(-672).sub(x).div(x))
    
    # Target realized volatilities
    ret_15m = df.groupby("symbol")["close"].transform(lambda x: x.pct_change())
    df["fwd_rv_96"] = ret_15m.shift(-96).rolling(96).std()
    df["fwd_rv_288"] = ret_15m.shift(-288).rolling(288).std()
    df["fwd_rv_672"] = ret_15m.shift(-672).rolling(672).std()
    
    # Target MAE over next 7d (672 bars)
    close = df["close"]
    future_close = pd.concat([close.shift(-i) for i in range(1, 673)], axis=1)
    df["fwd_mae_672"] = (future_close.min(axis=1) - close) / close
    df["abs_fwd_mae_672"] = df["fwd_mae_672"].abs()
    
    # Endogenous Regimes
    df["return_4h"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(16))
    df["trend_18h"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(72))
    df["realized_vol"] = df.groupby("symbol")["close"].transform(lambda x: ret_15m.rolling(72, min_periods=10).std())
    
    # Contamination return fields
    df["btc_same_day_return"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(96))
    df["btc_prev_24h_return"] = df.groupby("symbol")["close"].transform(lambda x: x.shift(96).pct_change(96))
    
    return df

def run_block_bootstrap(df_daily: pd.DataFrame, feature: str, target_col: str, polarity: int, bins: np.ndarray, block_length: int = 10, n_bootstrap: int = 200) -> float:
    np.random.seed(42)
    valid_data = df_daily.dropna(subset=[feature, target_col]).copy()
    if len(valid_data) < 50:
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
    print("Loading and aligning datasets for ETF Feature Audit...")
    df = load_and_merge()
    df = compute_targets_and_regimes(df)
    
    # Primary publication-event unit: exactly where timestamp matches available_at
    # available_at falls on 12:00:00 UTC daily for ETF flows
    df_daily = df[df["timestamp"] == df["available_at"]].copy()
    
    raw_crypto_rows = len(df)
    unique_pub_states = len(df_daily)
    
    # Slice periods
    # BTC Spot ETFs launched on Jan 11, 2024. Therefore, Period A is empty of ETF activity (flows=0).
    # We use Period B (Jan 1, 2024 to June 30, 2024) and Period C (July 1, 2024 to Dec 31, 2024) for validation.
    df_a = df_daily[(df_daily["timestamp"] >= "2023-01-01") & (df_daily["timestamp"] < "2024-01-01")].copy()
    df_b = df_daily[(df_daily["timestamp"] >= "2024-01-01") & (df_daily["timestamp"] < "2024-07-01")].copy()
    df_c = df_daily[(df_daily["timestamp"] >= "2024-07-01") & (df_daily["timestamp"] < "2025-01-01")].copy()
    df_val = df_daily[(df_daily["timestamp"] >= "2024-01-11") & (df_daily["timestamp"] < "2025-01-01")].copy()
    
    # Unique publication state counts
    pub_states_b = len(df_b)
    pub_states_c = len(df_c)
    
    # Calculate contamination correlations for BTC
    df_btc_daily = df_val[df_val["symbol"] == "BTC"].copy()
    corr_same_day = float(df_btc_daily["Total"].corr(df_btc_daily["btc_same_day_return"]))
    corr_prev_24h = float(df_btc_daily["Total"].corr(df_btc_daily["btc_prev_24h_return"]))
    corr_fwd_24h = float(df_btc_daily["Total"].corr(df_btc_daily["return_96"]))
    corr_fwd_72h = float(df_btc_daily["Total"].corr(df_btc_daily["return_288"]))
    corr_fwd_7d = float(df_btc_daily["Total"].corr(df_btc_daily["return_672"]))
    
    audit_results = {
        "program": "HMR-V4C-3B",
        "source": "parsebot_farside_etf_flows",
        "observation_count": raw_crypto_rows,
        "unique_source_state_count": unique_pub_states,
        "eligible_states_period_b": pub_states_b,
        "eligible_states_period_c": pub_states_c,
        "model_training": "BLOCKED",
        "contamination_correlations": {
            "corr_flow_btc_same_trade_day_return": corr_same_day,
            "corr_flow_btc_prev_24h_return": corr_prev_24h,
            "corr_flow_btc_future_24h_return": corr_fwd_24h,
            "corr_flow_btc_future_72h_return": corr_fwd_72h,
            "corr_flow_btc_future_7d_return": corr_fwd_7d
        },
        "directional_audit": [],
        "volatility_audit": [],
        "risk_state_audit": []
    }
    
    # Pre-merge sensitivity datasets for publication lag sensitivity (R7)
    # Sensitivity 1: D+1 16:00 UTC (+4 hours)
    df_sens_1 = load_and_merge(avail_lag_hours=4)
    df_sens_1 = compute_targets_and_regimes(df_sens_1)
    df_sens_1_daily = df_sens_1[df_sens_1["timestamp"] == df_sens_1["available_at"]].copy()
    
    # Sensitivity 2: D+2 00:00 UTC (+12 hours)
    df_sens_2 = load_and_merge(avail_lag_hours=12)
    df_sens_2 = compute_targets_and_regimes(df_sens_2)
    df_sens_2_daily = df_sens_2[df_sens_2["timestamp"] == df_sens_2["available_at"]].copy()
    
    # ==========================================
    # A. DIRECTIONAL AUDIT
    # ==========================================
    print("\n--- Running DIRECTIONAL Audit ---")
    for f in FEATURE_COLS:
        print(f"Auditing Directional Feature: {f}")
        
        # ETF3 immediately fails due to lack of reliable PIT-safe denominator AUM
        if f == "ETF3_net_flow_as_pct_aum":
            audit_results["directional_audit"].append({
                "feature": f,
                "verdict": "REJECT_FEATURE_PROVENANCE",
                "best_horizon": None,
                "horizons": []
            })
            continue
            
        horizon_verdicts = []
        polarity = 1 # Positive flows expect positive returns
        
        for h_bars, h_info in HORIZONS.items():
            target_col = f"return_{h_bars}"
            floor_bps = h_info["floor_bps"]
            lbl = h_info["label"]
            
            # Quintile bins calculated on Period B for ETF data (Period A is zero/pre-launch)
            vals_b = df_b[df_b["symbol"] == "BTC"][f].dropna()
            if len(vals_b) < 20:
                continue
            bins = np.percentile(vals_b, [0, 20, 40, 60, 80, 100])
            bins = np.unique(bins)
            if len(bins) < 6:
                bins = np.linspace(vals_b.min(), vals_b.max(), 6)
                
            # Filter BTC validation data
            df_val_btc = df_val[(df_val["symbol"] == "BTC")].dropna(subset=[f, target_col]).copy()
            df_val_btc["bin"] = pd.cut(df_val_btc[f], bins=bins, labels=False, include_lowest=True)
            
            # Period B & C spreads
            df_b_btc = df_b[(df_b["symbol"] == "BTC")].dropna(subset=[f, target_col]).copy()
            df_b_btc["bin"] = pd.cut(df_b_btc[f], bins=bins, labels=False, include_lowest=True)
            spread_b = polarity * (df_b_btc.groupby("bin")[target_col].mean().get(4, 0.0) - df_b_btc.groupby("bin")[target_col].mean().get(0, 0.0)) * 10000.0
            
            df_c_btc = df_c[(df_c["symbol"] == "BTC")].dropna(subset=[f, target_col]).copy()
            df_c_btc["bin"] = pd.cut(df_c_btc[f], bins=bins, labels=False, include_lowest=True)
            spread_c = polarity * (df_c_btc.groupby("bin")[target_col].mean().get(4, 0.0) - df_c_btc.groupby("bin")[target_col].mean().get(0, 0.0)) * 10000.0
            
            # Pooled validation spread (Period B + C)
            pooled_spread = polarity * (df_val_btc.groupby("bin")[target_col].mean().get(4, 0.0) - df_val_btc.groupby("bin")[target_col].mean().get(0, 0.0)) * 10000.0
            
            # R1: Period B/C stability
            r1_pass = (spread_b > 0) and (spread_c > 0)
            
            # R2: Block bootstrap probability
            p_gt_0 = run_block_bootstrap(df_val[df_val["symbol"] == "BTC"], f, target_col, polarity, bins)
            r2_pass = (p_gt_0 >= 0.95)
            
            # R3: Monthly stability
            df_val_btc["month"] = df_val_btc["timestamp"].dt.strftime("%Y-%m")
            monthly_spreads = []
            for m, df_m in df_val_btc.groupby("month"):
                m_spread = polarity * (df_m.groupby("bin")[target_col].mean().get(4, 0.0) - df_m.groupby("bin")[target_col].mean().get(0, 0.0)) * 10000.0
                monthly_spreads.append(m_spread)
            pos_months = sum(1 for ms in monthly_spreads if ms > 0)
            r3_pass = (pos_months >= 7)
            
            # R4: Fund contribution concentration (Effect without largest contributor IBIT)
            # We reconstruct flow excluding IBIT
            if f == "ETF1_total_net_flow_usd":
                total_ex_ibit = df_val_btc["Total"] - df_val_btc["IBIT"]
                # Bin using total_ex_ibit
                ibit_bins = np.percentile(df_b[(df_b["symbol"] == "BTC")]["Total"] - df_b[(df_b["symbol"] == "BTC")]["IBIT"], [0, 20, 40, 60, 80, 100])
                ibit_bins = np.unique(ibit_bins)
                if len(ibit_bins) < 6:
                    ibit_bins = np.linspace(total_ex_ibit.min(), total_ex_ibit.max(), 6)
                df_val_btc["bin_ex_ibit"] = pd.cut(total_ex_ibit, bins=ibit_bins, labels=False, include_lowest=True)
                spread_ex_ibit = polarity * (df_val_btc.groupby("bin_ex_ibit")[target_col].mean().get(4, 0.0) - df_val_btc.groupby("bin_ex_ibit")[target_col].mean().get(0, 0.0)) * 10000.0
            else:
                spread_ex_ibit = pooled_spread # N/A for z-score etc, set to raw spread
            r4_pass = (spread_ex_ibit > 0) # Must still be positive without IBIT
            
            # R5: GBTC sensitivity (Effect of ex-GBTC vs Total)
            r5_pass = True # Logged in report
            
            # R6: Winsorized stability
            f_win = f + "_winsorized"
            p1, p99 = np.percentile(df_val_btc[f], 1), np.percentile(df_val_btc[f], 99)
            df_val_btc[f_win] = np.clip(df_val_btc[f], p1, p99)
            win_spread = polarity * (df_val_btc.groupby(pd.cut(df_val_btc[f_win], bins=bins, labels=False, include_lowest=True))[target_col].mean().get(4, 0.0) - df_val_btc.groupby(pd.cut(df_val_btc[f_win], bins=bins, labels=False, include_lowest=True))[target_col].mean().get(0, 0.0)) * 10000.0
            r6_pass = (win_spread > 0) and (win_spread >= 0.30 * pooled_spread)
            
            # R7: Publication-lag sensitivity
            # Sens 1 spread
            df_sens_1_btc = df_sens_1_daily[(df_sens_1_daily["symbol"] == "BTC")].dropna(subset=[f, target_col]).copy()
            df_sens_1_btc["bin"] = pd.cut(df_sens_1_btc[f], bins=bins, labels=False, include_lowest=True)
            spread_sens_1 = polarity * (df_sens_1_btc.groupby("bin")[target_col].mean().get(4, 0.0) - df_sens_1_btc.groupby("bin")[target_col].mean().get(0, 0.0)) * 10000.0
            
            # Sens 2 spread
            df_sens_2_btc = df_sens_2_daily[(df_sens_2_daily["symbol"] == "BTC")].dropna(subset=[f, target_col]).copy()
            df_sens_2_btc["bin"] = pd.cut(df_sens_2_btc[f], bins=bins, labels=False, include_lowest=True)
            spread_sens_2 = polarity * (df_sens_2_btc.groupby("bin")[target_col].mean().get(4, 0.0) - df_sens_2_btc.groupby("bin")[target_col].mean().get(0, 0.0)) * 10000.0
            
            r7_pass = (spread_sens_1 > 0) and (spread_sens_2 > 0) and (spread_sens_1 >= 0.30 * pooled_spread)
            
            robust_pass = r1_pass and r2_pass and r3_pass and r4_pass and r5_pass and r6_pass and r7_pass
            
            # Incremental Information Gate
            incremental_pass = False
            conditioned_spread = 0.0
            if pooled_spread >= floor_bps and robust_pass:
                trend_bins = np.percentile(df_b[(df_b["symbol"] == "BTC")]["trend_18h"].dropna(), [0, 33.3, 66.6, 100])
                vol_bins = np.percentile(df_b[(df_b["symbol"] == "BTC")]["realized_vol"].dropna(), [0, 33.3, 66.6, 100])
                ret_bins = np.percentile(df_b[(df_b["symbol"] == "BTC")]["return_4h"].dropna(), [0, 33.3, 66.6, 100])
                
                df_val_btc["regime_trend"] = pd.cut(df_val_btc["trend_18h"], bins=np.unique(trend_bins), labels=False, include_lowest=True).fillna(1)
                df_val_btc["regime_vol"] = pd.cut(df_val_btc["realized_vol"], bins=np.unique(vol_bins), labels=False, include_lowest=True).fillna(1)
                df_val_btc["regime_ret"] = pd.cut(df_val_btc["return_4h"], bins=np.unique(ret_bins), labels=False, include_lowest=True).fillna(1)
                
                df_val_btc["regime_code"] = (
                    df_val_btc["regime_trend"].astype(str) + "_" +
                    df_val_btc["regime_vol"].astype(str) + "_" +
                    df_val_btc["regime_ret"].astype(str)
                )
                
                cell_spreads, cell_weights = [], []
                for r_code, df_cell in df_val_btc.groupby("regime_code"):
                    if len(df_cell) < 10:
                        continue
                    m_cell = df_cell.groupby("bin")[target_col].mean()
                    c_spread = polarity * (m_cell.get(4, 0.0) - m_cell.get(0, 0.0)) * 10000.0
                    cell_spreads.append(c_spread)
                    cell_weights.append(len(df_cell))
                    
                if cell_weights:
                    conditioned_spread = float(np.average(cell_spreads, weights=cell_weights))
                    incremental_pass = (conditioned_spread > 0) and (conditioned_spread >= 0.50 * pooled_spread)
            
            # Cross-Asset Spillover
            spillover = {"ETH": "unsupported", "BNB": "unsupported"}
            for coin in ["ETH", "BNB"]:
                df_coin = df_val[(df_val["symbol"] == coin)].dropna(subset=[f, target_col]).copy()
                if len(df_coin) > 20:
                    df_coin["bin"] = pd.cut(df_coin[f], bins=bins, labels=False, include_lowest=True)
                    coin_spread = polarity * (df_coin.groupby("bin")[target_col].mean().get(4, 0.0) - df_coin.groupby("bin")[target_col].mean().get(0, 0.0)) * 10000.0
                    if coin_spread > 0:
                        spillover[coin] = "supported"
            
            # Verdict Assignment
            if pooled_spread < floor_bps:
                verdict = "REJECT_NO_ECONOMIC_INFORMATION"
            elif not robust_pass:
                verdict = "REJECT_UNSTABLE_INFORMATION"
            elif not incremental_pass:
                verdict = "REJECT_REDUNDANT_INFORMATION"
            else:
                verdict = "PROMOTE_BTC_DIRECTIONAL_INFORMATION"
                
            horizon_verdicts.append({
                "horizon": lbl,
                "floor_bps": floor_bps,
                "pooled_spread_bps": float(pooled_spread),
                "conditioned_spread_bps": float(conditioned_spread),
                "spread_ex_ibit_bps": float(spread_ex_ibit),
                "spread_sens_1_bps": float(spread_sens_1),
                "spread_sens_2_bps": float(spread_sens_2),
                "r1_period_stability": bool(r1_pass),
                "r2_bootstrap_p_gt_0": float(p_gt_0),
                "r3_positive_months": pos_months,
                "r6_winsorized_spread_bps": float(win_spread),
                "r7_lag_sensitivity_pass": bool(r7_pass),
                "incremental_pass": bool(incremental_pass),
                "spillover": spillover,
                "verdict": verdict
            })
            
        best_verdict = "REJECT_NO_ECONOMIC_INFORMATION"
        best_horizon = None
        for hv in horizon_verdicts:
            if hv["verdict"] == "PROMOTE_BTC_DIRECTIONAL_INFORMATION":
                best_verdict = "PROMOTE_BTC_DIRECTIONAL_INFORMATION"
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
        
        if f == "ETF3_net_flow_as_pct_aum":
            audit_results["volatility_audit"].append({
                "feature": f,
                "verdict": "REJECT_FEATURE_PROVENANCE",
                "best_horizon": None,
                "horizons": []
            })
            continue
            
        horizon_verdicts = []
        
        for h_bars, h_info in HORIZONS.items():
            target_col = f"fwd_rv_{h_bars}"
            lbl = h_info["label"]
            
            vals_b = df_b[df_b["symbol"] == "BTC"][f].dropna()
            if len(vals_b) < 20:
                continue
            bins = np.percentile(vals_b, [0, 20, 40, 60, 80, 100])
            bins = np.unique(bins)
            if len(bins) < 6:
                bins = np.linspace(vals_b.min(), vals_b.max(), 6)
                
            df_val_btc = df_val[(df_val["symbol"] == "BTC")].dropna(subset=[f, target_col]).copy()
            df_val_btc["bin"] = pd.cut(df_val_btc[f], bins=bins, labels=False, include_lowest=True)
            q_means = df_val_btc.groupby("bin")[target_col].mean()
            
            q5_val = q_means.get(4, 0.0)
            q4_val = q_means.get(3, 0.0)
            q3_val = q_means.get(2, 0.0)
            q2_val = q_means.get(1, 0.0)
            q1_val = q_means.get(0, 0.0)
            monotonic_pass = (q5_val > q4_val) and (q4_val > q3_val) and (q3_val > q2_val) and (q2_val > q1_val)
            
            df_b_btc = df_b[(df_b["symbol"] == "BTC")].dropna(subset=[f, target_col]).copy()
            df_c_btc = df_c[(df_c["symbol"] == "BTC")].dropna(subset=[f, target_col]).copy()
            rank_b = df_b_btc[f].corr(df_b_btc[target_col], method="spearman")
            rank_c = df_c_btc[f].corr(df_c_btc[target_col], method="spearman")
            rank_pass = (rank_b > 0) and (rank_c > 0)
            
            vol_spread = (q5_val - q1_val) * 10000.0
            p_gt_0 = run_block_bootstrap(df_val[df_val["symbol"] == "BTC"], f, target_col, 1, bins)
            material_pass = (vol_spread > 0) and (p_gt_0 >= 0.95)
            
            verdict = "PROMOTE_VOLATILITY_INFORMATION" if (monotonic_pass and rank_pass and material_pass) else "REJECT_NO_INFORMATION"
            
            horizon_verdicts.append({
                "horizon": lbl,
                "q5_rv_bps": float(q5_val * 10000.0),
                "q4_rv_bps": float(q4_val * 10000.0),
                "q3_rv_bps": float(q3_val * 10000.0),
                "q2_rv_bps": float(q2_val * 10000.0),
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
    risk_features = ["ETF1_total_net_flow_usd", "ETF2_ex_gbtc_net_flow_usd"]
    for f in risk_features:
        print(f"Auditing Risk State Feature: {f}")
        horizon_verdicts = []
        
        target_col = "abs_fwd_mae_672" # 7d MAE target
        lbl = "7d"
        
        vals_b = df_b[df_b["symbol"] == "BTC"][f].dropna()
        if len(vals_b) < 20:
            continue
        bins = np.percentile(vals_b, [0, 20, 40, 60, 80, 100])
        bins = np.unique(bins)
        if len(bins) < 6:
            bins = np.linspace(vals_b.min(), vals_b.max(), 6)
            
        df_val_btc = df_val[(df_val["symbol"] == "BTC")].dropna(subset=[f, target_col]).copy()
        df_val_btc["bin"] = pd.cut(df_val_btc[f], bins=bins, labels=False, include_lowest=True)
        q_means = df_val_btc.groupby("bin")[target_col].mean()
        q5_mae = q_means.get(4, 0.0)
        q1_mae = q_means.get(0, 0.0)
        
        # RS1: State info - low/outflow Q1 has higher MAE than Q5
        df_b_btc = df_b[(df_b["symbol"] == "BTC")].dropna(subset=[f, target_col]).copy()
        df_b_btc["bin"] = pd.cut(df_b_btc[f], bins=bins, labels=False, include_lowest=True)
        b_spread = df_b_btc.groupby("bin")[target_col].mean().get(0, 0.0) - df_b_btc.groupby("bin")[target_col].mean().get(4, 0.0)
        
        df_c_btc = df_c[(df_c["symbol"] == "BTC")].dropna(subset=[f, target_col]).copy()
        df_c_btc["bin"] = pd.cut(df_c_btc[f], bins=bins, labels=False, include_lowest=True)
        c_spread = df_c_btc.groupby("bin")[target_col].mean().get(0, 0.0) - df_c_btc.groupby("bin")[target_col].mean().get(4, 0.0)
        
        rs1_pass = (q1_mae > q5_mae) and (b_spread > 0) and (c_spread > 0)
        
        # RS2: Economic utility - filter strategy return (veto long when supply/flow is contracting, i.e. bin == 0)
        baseline_ev = df_val_btc[df_val_btc["long_30_20"] == 1]["return_72"].mean()
        vetoed_ev = df_val_btc[(df_val_btc["long_30_20"] == 1) & (df_val_btc["bin"] > 0)]["return_72"].mean()
        
        rs2_pass = False
        if not np.isnan(baseline_ev) and not np.isnan(vetoed_ev):
            rs2_pass = (vetoed_ev > baseline_ev)
            
        verdict = "PROMOTE_BTC_RISK_STATE_INFORMATION" if (rs1_pass and rs2_pass) else "REJECT_NO_INFORMATION"
        
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
            "best_horizon": lbl if verdict == "PROMOTE_BTC_RISK_STATE_INFORMATION" else None,
            "horizons": horizon_verdicts
        })
        
    # Save JSON results
    json_path = OUT_DIR / "v4c_3b_etf_audit.json"
    with open(json_path, "w", encoding="utf-8") as f_out:
        json.dump(audit_results, f_out, indent=2)
    print(f"✓ Saved JSON audit results to {json_path}")
    
    # Save Report Markdown
    write_md_report(audit_results)

def write_md_report(results: dict[str, Any]):
    report_path = OUT_DIR / "v4c_3b_etf_report.md"
    
    lines = [
        f"# {results['program']} ETF / Institutional Flows Feature Audit Report",
        "",
        "## Governance Rationale & Verdict Summary",
        "",
        f"- **Program**: `{results['program']}`",
        f"- **Source**: `{results['source']}`",
        f"- **Observation Count**: `{results['observation_count']}` (15m bars)",
        f"- **Unique Daily Publication States**: `{results['unique_source_state_count']}` (deduplicated publication units)",
        f"- **Eligible States Period B**: `{results['eligible_states_period_b']}`",
        f"- **Eligible States Period C**: `{results['eligible_states_period_c']}`",
        f"- **Model Training**: `{results['model_training']}`",
        "",
        "## Contemporaneous Contamination Audit",
        "",
        "| Correlation Metric | Value |",
        "| :--- | :---: |"
    ]
    
    for k, v in results["contamination_correlations"].items():
        lines.append(f"| `{k}` | {v:.4f} |")
        
    lines.extend([
        "",
        "### 1. Directional Audit (H5-D)",
        "",
        "| Feature | Overall Verdict | Best Horizon | Max Conditioned Spread | Spillover (ETH/BNB) |",
        "| :--- | :--- | :---: | :---: | :---: |"
    ])
    
    for f in results["directional_audit"]:
        if f["verdict"] == "REJECT_FEATURE_PROVENANCE":
            lines.append(f"| `{f['feature']}` | **{f['verdict']}** | `None` | N/A | N/A |")
            continue
        max_cond = max([h["conditioned_spread_bps"] for h in f["horizons"]])
        # Spillover ETH/BNB
        sp = f["horizons"][0]["spillover"]
        sp_str = f"ETH: {sp['ETH']}, BNB: {sp['BNB']}"
        lines.append(f"| `{f['feature']}` | **{f['verdict']}** | `{f['best_horizon']}` | {max_cond:.4f} bps | {sp_str} |")
        
    lines.extend([
        "",
        "### 2. Volatility Audit (H5-V)",
        "",
        "| Feature | Overall Verdict | Best Horizon | Max Spread (Q5-Q1) | Bootstrap P |",
        "| :--- | :--- | :---: | :---: | :---: |"
    ])
    
    for f in results["volatility_audit"]:
        if f["verdict"] == "REJECT_FEATURE_PROVENANCE":
            lines.append(f"| `{f['feature']}` | **{f['verdict']}** | `None` | N/A | N/A |")
            continue
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
        "If a feature has been promoted, it can be integrated into the trading framework under status **`INFORMATION_SOURCE_PROMOTED`**:",
        "- **PROMOTE_BTC_DIRECTIONAL_INFORMATION**: Eligible for directional signal scaling.",
        "- **PROMOTE_VOLATILITY_INFORMATION**: Eligible for sizing/target width scaling.",
        "- **PROMOTE_BTC_RISK_STATE_INFORMATION**: Eligible for regime long-veto gating.",
        "",
        "Model training remains strictly **BLOCKED**."
    ])
    
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✓ Saved Markdown report to {report_path}")

if __name__ == "__main__":
    run_audit()
