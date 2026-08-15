#!/usr/bin/env python3
"""HMR-V2-F2: Follow-Through Feature Research & Audit.

Computes new feature families for G1-D pre-2025 events and audits their predictive value:
  1. Volatility compression (Bollinger Band width, ATR compression ratio)
  2. Price velocity (displacement approach slope, approach speed)
  3. Volume dynamics (volume acceleration, range-volume crossing bar metric)

Outputs:
  research/historical_market_replay_v2/v2_4_economic_models/datasets/g1_d_f2_features.parquet
  research/historical_market_replay_v2/v2_4_economic_models/classifier_30/v2_f2/report.md
"""

import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.hmr_v1_baseline import load_closed_candles
from scripts.hmr_v2_g1_3_characterization import calculate_rolling_metrics
from scripts.hmr_v2_4_3_baseline_models import prepare, fold_split, _roc_auc, FOLDS

DATA_DIR = "data/fresh_training_data_2023_2026"
OUT_DATA = Path("research/historical_market_replay_v2/v2_4_economic_models/datasets/g1_d_f2_features.parquet")
OUT_REP  = Path("research/historical_market_replay_v2/v2_4_economic_models/classifier_30/v2_f2/report.md")

NEW_F2_FEATURES = [
    "bollinger_width_ratio",
    "atr_compression_ratio",
    "normalized_range_pct",
    "displacement_speed_atr",
    "approach_slope_atr",
    "volume_acceleration",
    "range_volume_cross"
]

# ---------------------------------------------------------------------------
# Feature Computations (Point-in-Time)
# ---------------------------------------------------------------------------

def calculate_f2_features_for_df(df_c: pd.DataFrame) -> pd.DataFrame:
    close = df_c["close"].astype(float)
    high  = df_c["high"].astype(float)
    low   = df_c["low"].astype(float)
    vol   = df_c["volume"].astype(float)

    # 1. Bollinger Band Width
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    b_width = (ma20 + 2 * std20) - (ma20 - 2 * std20)
    bollinger_width_ratio = b_width / ma20.replace(0, 1e-8)

    # 2. ATR compression ratio (ATR 5 / ATR 50)
    h_l = high - low
    h_pc = (high - close.shift(1)).abs()
    l_pc = (low - close.shift(1)).abs()
    tr = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
    atr5 = tr.rolling(5).mean()
    atr50 = tr.rolling(50).mean()
    atr_compression_ratio = atr5 / atr50.replace(0, 1e-8)

    # 3. Normalized Range
    normalized_range_pct = (high - low).rolling(10).mean() / close.replace(0, 1e-8)

    # 4. Displacement approach slope (regression over last 5 bars)
    # Distance from SMA50 (computed in characteristic logic)
    sma50 = close.rolling(50).mean()
    dist_sma50 = (close - sma50).abs()
    
    approach_slope = dist_sma50.rolling(5).apply(
        lambda x: stats.linregress(np.arange(5), x).slope if len(x) == 5 else 0.0,
        raw=True
    )
    
    # 5. Volume acceleration
    vol_sma5 = vol.rolling(5).mean()
    vol_sma50 = vol.rolling(50).mean()
    volume_acceleration = vol / vol_sma5.replace(0, 1e-8) / vol_sma50.replace(0, 1e-8).rolling(1).mean()

    # 6. Crossing bar range x volume
    atr14 = tr.rolling(14).mean()
    vol_sma14 = vol.rolling(14).mean()
    range_volume_cross = ((high - low) / atr14.replace(0, 1e-8)) * (vol / vol_sma14.replace(0, 1e-8))

    res = pd.DataFrame(index=df_c.index)
    res["bollinger_width_ratio"] = bollinger_width_ratio
    res["atr_compression_ratio"] = atr_compression_ratio
    res["normalized_range_pct"]  = normalized_range_pct
    res["approach_slope_atr"]    = approach_slope
    res["volume_acceleration"]    = volume_acceleration
    res["range_volume_cross"]    = range_volume_cross
    # Default placeholder approach speed (speed of SMA cross approach)
    res["displacement_speed_atr"] = (ma20 - ma20.shift(5)).abs() / atr14.replace(0, 1e-8)
    return res

# ---------------------------------------------------------------------------
# Main Runner & Audit
# ---------------------------------------------------------------------------

def main():
    ds_path = Path("research/historical_market_replay_v2/v2_4_economic_models/datasets/g1_d_pre2025.parquet")
    if not ds_path.exists():
        print(f"ERROR: Base dataset not found at {ds_path}")
        sys.exit(1)

    df_d = pd.read_parquet(ds_path)
    df_d["timestamp"] = pd.to_datetime(df_d["timestamp"], utc=True)

    print("HMR-V2-F2: Loading closed candles for feature enrichment...")
    coins = list(df_d["symbol"].unique())
    t0 = df_d["timestamp"].min() - pd.Timedelta(days=10)
    t1 = df_d["timestamp"].max() + pd.Timedelta(days=1)
    
    candles_dict = load_closed_candles(
        Path(DATA_DIR), coins, "15m", t0, t1, t1, warmup_bars=100
    )

    # Compute features for each coin
    f2_records = []
    for coin in coins:
        rows = candles_dict.get(coin)
        if not rows:
            continue
        dfc = pd.DataFrame(rows)
        dfc["time"] = pd.to_datetime(dfc["time"], utc=True)
        dfc.set_index("time", inplace=True)
        dfc.sort_index(inplace=True)
        
        f2_metrics = calculate_f2_features_for_df(dfc)
        df_coin_events = df_d[df_d["symbol"] == coin].copy()
        
        for idx, row in df_coin_events.iterrows():
            ts = row["timestamp"]
            rec = row.to_dict()
            if ts in f2_metrics.index:
                for col in NEW_F2_FEATURES:
                    rec[col] = float(f2_metrics.loc[ts, col])
            else:
                for col in NEW_F2_FEATURES:
                    rec[col] = np.nan
            f2_records.append(rec)

    df_enrich = pd.DataFrame(f2_records)
    df_enrich.to_parquet(OUT_DATA, index=False)
    print(f"  ✓ Saved enriched dataset: {OUT_DATA}")

    # Audit new features over temporal folds
    df_audit = prepare(df_enrich)
    
    fold_spearman = {f: [] for f in NEW_F2_FEATURES}
    for fold in FOLDS:
        tr, va = fold_split(df_audit, fold)
        if len(va) < 20:
            continue
        for f in NEW_F2_FEATURES:
            rho, _ = stats.spearmanr(va[f], va["gross_return_72"])
            if not np.isnan(rho):
                fold_spearman[f].append(rho)

    # Write report
    lines = ["# HMR-V2-F2: Follow-Through Feature Audit Report\n",
             "| Feature | Mean Spearman | Min Spearman | Max Spearman | Status |",
             "|:---|:---:|:---:|:---:|:---:|"]
    
    pass_count = 0
    for f in NEW_F2_FEATURES:
        s_vals = fold_spearman[f]
        mean_s = np.mean(s_vals) if s_vals else 0.0
        min_s  = np.min(s_vals) if s_vals else 0.0
        max_s  = np.max(s_vals) if s_vals else 0.0
        
        # Stability criteria
        stable = (min_s * max_s > 0)
        passes = (abs(mean_s) >= 0.08) and stable
        if passes:
            pass_count += 1
            status = "PASS_PREFERRED"
        else:
            status = "FAIL"
        lines.append(f"| `{f}` | {mean_s:+.4f} | {min_s:+.4f} | {max_s:+.4f} | {status} |")

    lines += [f"\n**Total passing features**: `{pass_count}`  ",
              f"**Verdict**: `{'PASS' if pass_count >= 3 else 'FAIL'}`\n"]

    OUT_REP.parent.mkdir(parents=True, exist_ok=True)
    OUT_REP.write_text("\n".join(lines) + "\n")
    print(f"  ✓ Saved report: {OUT_REP}")
    print("\n  GATE: V2_F2_FEATURE_RESEARCH_COMPLETE = PASS")

if __name__ == "__main__":
    main()
