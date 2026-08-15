#!/usr/bin/env python3
"""HMR-V4A-0: Build Neutral Outcome Scaffold."""

import sys
import warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.hmr_v1_baseline import load_closed_candles

COINS = ["BTC", "ETH", "BNB"]
TIMEFRAME = "15m"
HORIZON = 72
WARMUP_BARS = 100

def compute_triple_barrier_targets(close, high, low, tp_bps, sl_bps, horizon):
    n = len(close)
    target = np.zeros(n)
    tp = tp_bps / 10000.0
    sl = sl_bps / 10000.0
    
    for i in range(n):
        ep = close[i]
        tp_price = ep * (1.0 + tp)
        sl_price = ep * (1.0 - sl)
        
        # Check window
        for k in range(1, horizon + 1):
            if i + k >= n:
                break
            # conservative check: SL first
            if low[i + k] <= sl_price:
                target[i] = 0.0
                break
            if high[i + k] >= tp_price:
                target[i] = 1.0
                break
    return target

def compute_short_triple_barrier_targets(close, high, low, tp_bps, sl_bps, horizon):
    n = len(close)
    target = np.zeros(n)
    tp = tp_bps / 10000.0
    sl = sl_bps / 10000.0
    
    for i in range(n):
        ep = close[i]
        tp_price = ep * (1.0 - tp)
        sl_price = ep * (1.0 + sl)
        
        # Check window
        for k in range(1, horizon + 1):
            if i + k >= n:
                break
            # conservative check: SL first
            if high[i + k] >= sl_price:
                target[i] = 0.0
                break
            if low[i + k] <= tp_price:
                target[i] = 1.0
                break
    return target

def main():
    out_dir = REPO_ROOT / "research/historical_market_replay_v4"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    period_start = pd.Timestamp("2023-01-01", tz="UTC")
    period_end   = pd.Timestamp("2024-12-31 23:59:59", tz="UTC")
    settle_end   = pd.Timestamp("2025-01-03", tz="UTC")  # buffer for 72-bar exits
    
    print("HMR-V4A-0: Loading candles...")
    candles_dict = load_closed_candles(
        Path("data/fresh_training_data_2023_2026"), COINS, TIMEFRAME,
        period_start, period_end, settle_end, warmup_bars=WARMUP_BARS
    )
    
    all_dfs = []
    for coin in COINS:
        rows = candles_dict.get(coin)
        if not rows:
            print(f"ERROR: No candle data for {coin}")
            continue
            
        dfc = pd.DataFrame(rows)
        dfc["time"] = pd.to_datetime(dfc["time"], utc=True)
        dfc.set_index("time", inplace=True)
        dfc.sort_index(inplace=True)
        
        print(f"Processing targets for {coin} ({len(dfc)} bars)...")
        close = dfc["close"].values
        high  = dfc["high"].values
        low   = dfc["low"].values
        
        # Targets
        long_30_20 = compute_triple_barrier_targets(close, high, low, 30, 20, HORIZON)
        short_30_20 = compute_short_triple_barrier_targets(close, high, low, 30, 20, HORIZON)
        
        # Forward returns
        ret_8 = np.full(len(close), np.nan)
        ret_32 = np.full(len(close), np.nan)
        ret_72 = np.full(len(close), np.nan)
        
        for i in range(len(close)):
            if i + 8 < len(close):
                ret_8[i] = (close[i+8] - close[i]) / close[i]
            if i + 32 < len(close):
                ret_32[i] = (close[i+32] - close[i]) / close[i]
            if i + 72 < len(close):
                ret_72[i] = (close[i+72] - close[i]) / close[i]
                
        # Absolute move magnitude (expansion in 72 bars)
        abs_move_72 = np.full(len(close), np.nan)
        for i in range(len(close)):
            if i + HORIZON < len(close):
                window_h = high[i+1 : i+HORIZON+1]
                window_l = low[i+1 : i+HORIZON+1]
                max_dev = max(window_h.max() - close[i], close[i] - window_l.min())
                abs_move_72[i] = max_dev / close[i]
                
        df_coin = pd.DataFrame({
            "timestamp": dfc.index,
            "symbol": coin,
            "close": close,
            "long_30_20": long_30_20,
            "short_30_20": short_30_20,
            "return_8": ret_8,
            "return_32": ret_32,
            "return_72": ret_72,
            "abs_move_72": abs_move_72
        })
        
        # Filter to exact Period A/B/C validation range
        df_coin = df_coin[(df_coin["timestamp"] >= period_start) & (df_coin["timestamp"] <= period_end)]
        all_dfs.append(df_coin)
        
    df_all = pd.concat(all_dfs, ignore_index=True)
    out_path = out_dir / "v4a_outcome_scaffold.parquet"
    df_all.to_parquet(out_path, index=False)
    print(f"✓ Saved outcome scaffold to {out_path} ({len(df_all)} rows)")

if __name__ == "__main__":
    main()
