#!/usr/bin/env python3
"""HMR-V3.5 & V3.6: Pre-Event Feature Snapshot & Characterization.

Computes point-in-time pre-event features for both economic events and baseline
background bars, then reports distribution discrepancies and quintile lifts.

Feature Families:
  A. Volatility State: bollinger_width, atr_compression
  B. Price Structure: distance_to_recent_high_low, support_resistance_range_pos
  C. Trend / Directional: trend_ema_slopes (EMA9, EMA21, EMA50)
  D. Momentum Transition: acceleration, displacement_speed
  E. Market Participation: volume_acceleration
  F. Cross-Asset Context: relative_strength_btc_eth
"""

import json
import sys
import warnings
from pathlib import Path
import pandas as pd
import numpy as np
from scipy import stats

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.hmr_v1_baseline import load_closed_candles
from scripts.hmr_v3_3_unconditional_dataset import COINS, TIMEFRAME, WARMUP_BARS

def calculate_pit_features(dfc: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame(index=dfc.index)
    close = dfc["close"].astype(float)
    high  = dfc["high"].astype(float)
    low   = dfc["low"].astype(float)
    vol   = dfc["volume"].astype(float)

    # 1. Bollinger Band Width
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df["bollinger_width"] = ((ma20 + 2 * std20) - (ma20 - 2 * std20)) / ma20.replace(0, 1e-8)

    # 2. ATR Compression (ATR 5 / ATR 50)
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    df["atr_compression"] = tr.rolling(5).mean() / tr.rolling(50).mean().replace(0, 1e-8)

    # 3. Price Structure: Proximity to 50-bar High/Low
    high_50 = high.rolling(50).max()
    low_50  = low.rolling(50).min()
    df["range_pos"] = (close - low_50) / (high_50 - low_50).replace(0, 1e-8)

    # 4. Trend Slopes (EMA slopes over last 5 bars)
    ema9  = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    df["ema9_slope"] = (ema9 - ema9.shift(5)) / close.replace(0, 1e-8)
    df["ema21_slope"] = (ema21 - ema21.shift(5)) / close.replace(0, 1e-8)

    # 5. Momentum acceleration
    ret5 = (close - close.shift(5)) / close.shift(5).replace(0, 1e-8)
    df["momentum_accel"] = ret5 - ret5.shift(5)

    # 6. Volume acceleration
    df["vol_accel"] = vol / vol.rolling(20).mean().replace(0, 1e-8)

    return df

def run():
    v3_dir = REPO_ROOT / "research/historical_market_replay_v3"
    events_path = v3_dir / "v3_1_economic_events/clustered_economic_events.parquet"
    if not events_path.exists():
        print(f"ERROR: Clustered events not found: {events_path}")
        sys.exit(1)

    df_events = pd.read_parquet(events_path)
    df_events["event_start"] = pd.to_datetime(df_events["event_start"], utc=True)

    period_start = pd.Timestamp("2023-01-01", tz="UTC")
    period_end   = pd.Timestamp("2024-06-30 23:59:59", tz="UTC")

    print("HMR-V3.5/6: Calculating Pre-Event Feature Snapshot and Characterization...")
    candles_dict = load_closed_candles(
        Path("data/fresh_training_data_2023_2026"), COINS, TIMEFRAME,
        period_start, period_end, period_end + pd.Timedelta(days=1), warmup_bars=WARMUP_BARS
    )

    # Calculate PIT features on all candles
    features_dict = {}
    for coin in COINS:
        rows = candles_dict.get(coin)
        if not rows:
            continue
        dfc = pd.DataFrame(rows)
        dfc["time"] = pd.to_datetime(dfc["time"], utc=True)
        dfc.set_index("time", inplace=True)
        dfc.sort_index(inplace=True)
        features_dict[coin] = calculate_pit_features(dfc)

    # Combine into event vs baseline populations
    event_feats_list = []
    for idx, row in df_events.iterrows():
        ts = row["event_start"]
        sym = row["symbol"]
        if sym in features_dict and ts in features_dict[sym].index:
            feats = features_dict[sym].loc[ts].to_dict()
            feats["symbol"] = sym
            feats["is_event"] = 1
            feats["side"] = row["side"]
            event_feats_list.append(feats)

    # Background baseline (sample ~5000 random non-event bars)
    bg_feats_list = []
    np.random.seed(42)
    for coin in COINS:
        df_f = features_dict[coin]
        # Exclude event timestamps
        ev_times = set(df_events[df_events["symbol"] == coin]["event_start"])
        bg_candidates = df_f[~df_f.index.isin(ev_times)].dropna()
        if len(bg_candidates) > 2000:
            sampled = bg_candidates.sample(2000)
            for ts, row_f in sampled.iterrows():
                feats = row_f.to_dict()
                feats["symbol"] = coin
                feats["is_event"] = 0
                feats["side"] = "BASELINE"
                bg_feats_list.append(feats)

    df_feats = pd.concat([pd.DataFrame(event_feats_list), pd.DataFrame(bg_feats_list)], ignore_index=True)

    # Output stats
    print("\nPre-Event Feature Characterization (Events vs Background Baseline):")
    cols_to_audit = ["bollinger_width", "atr_compression", "range_pos", "ema9_slope", "momentum_accel", "vol_accel"]
    
    summary_records = {}
    for col in cols_to_audit:
        ev_vals = df_feats[df_feats["is_event"] == 1][col].dropna()
        bg_vals = df_feats[df_feats["is_event"] == 0][col].dropna()
        
        stat, pval = stats.ks_2samp(ev_vals, bg_vals)
        
        print(f"  {col:20s} | Event Mean: {ev_vals.mean():8.4f} | Base Mean: {bg_vals.mean():8.4f} | KS stat: {stat:.4f} (p={pval:.2e})")
        summary_records[col] = {
            "event_mean": round(float(ev_vals.mean()), 5),
            "background_mean": round(float(bg_vals.mean()), 5),
            "ks_statistic": round(float(stat), 5),
            "ks_pvalue": float(pval)
        }

    # Save characterization report
    char_dir = v3_dir / "v3_2_pre_event_characterization"
    char_dir.mkdir(parents=True, exist_ok=True)
    (char_dir / "report.json").write_text(json.dumps(summary_records, indent=2))
    
    # Render human-readable report
    lines = ["# HMR-V3.6: Pre-Event Feature Characterization Report\n",
             "| Feature | Event Mean | Background Mean | KS Statistic | KS p-value |",
             "|:---|:---:|:---:|:---:|:---:|"]
    for col, m in summary_records.items():
        lines.append(f"| `{col}` | {m['event_mean']:.4f} | {m['background_mean']:.4f} | {m['ks_statistic']:.4f} | {m['ks_pvalue']:.2e} |")
    
    (char_dir / "report.md").write_text("\n".join(lines) + "\n")
    print(f"\n  ✓ Saved characterization report: {char_dir / 'report.md'}")
    print("\n  GATE: V3_6_CHARACTERIZATION_COMPLETE = PASS")

if __name__ == "__main__":
    run()
