#!/usr/bin/env python3
"""HMR-V3.3: Unconditional Market Event Dataset Builder.

Samples every 15-minute bar over Period A (2023-01-01 -> 2024-06-30) for BTC, ETH, BNB.
Computes forward returns, MFE, and MAE across our frozen horizon grid.

Outputs:
  research/historical_market_replay_v3/v3_1_economic_events/
    unconditional_market_dataset.parquet
    economic_event_contract.json
"""

import sys
import warnings
from pathlib import Path
import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.hmr_v1_baseline import load_closed_candles

COINS = ["BTC", "ETH", "BNB"]
TIMEFRAME = "15m"
HORIZONS = [8, 16, 32, 48, 72, 96]
WARMUP_BARS = 100

def run():
    out_dir = REPO_ROOT / "research/historical_market_replay_v3/v3_1_economic_events"
    out_dir.mkdir(parents=True, exist_ok=True)

    period_start = pd.Timestamp("2023-01-01", tz="UTC")
    period_end   = pd.Timestamp("2024-06-30 23:59:59", tz="UTC")
    settle_end   = pd.Timestamp("2024-07-02", tz="UTC") # buffer for 96-bar returns

    print("HMR-V3.3: Building Unconditional Market Dataset...")
    print(f"  Sampling Period: {period_start.date()} -> {period_end.date()}")
    
    candles_dict = load_closed_candles(
        Path("data/fresh_training_data_2023_2026"), COINS, TIMEFRAME,
        period_start, period_end, settle_end, warmup_bars=WARMUP_BARS
    )

    all_dfs = []
    for coin in COINS:
        rows = candles_dict.get(coin)
        if not rows:
            continue
        dfc = pd.DataFrame(rows)
        dfc["time"] = pd.to_datetime(dfc["time"], utc=True)
        dfc.set_index("time", inplace=True)
        dfc.sort_index(inplace=True)
        
        close = dfc["close"].astype(float)
        high  = dfc["high"].astype(float)
        low   = dfc["low"].astype(float)

        print(f"  Processing {coin} ({len(dfc)} bars)...")
        records = []
        for i in range(len(dfc)):
            ts = dfc.index[i]
            if ts < period_start or ts > period_end:
                continue
            
            ep = float(close.iloc[i])
            rec = {
                "timestamp": ts,
                "symbol": coin,
                "close": ep
            }
            
            # Compute forward horizons
            for h in HORIZONS:
                if i + h < len(dfc):
                    window_c = close.iloc[i+1 : i+h+1]
                    window_h = high.iloc[i+1 : i+h+1]
                    window_l = low.iloc[i+1 : i+h+1]
                    
                    # Favorable returns for BUY & SELL
                    rec[f"ret_buy_{h}"] = (window_c.iloc[-1] - ep) / ep
                    rec[f"ret_sell_{h}"] = (ep - window_c.iloc[-1]) / ep
                    
                    # Excursions
                    rec[f"mfe_buy_{h}"] = (window_h.max() - ep) / ep
                    rec[f"mae_buy_{h}"] = (ep - window_l.min()) / ep
                    rec[f"mfe_sell_{h}"] = (ep - window_l.min()) / ep
                    rec[f"mae_sell_{h}"] = (window_h.max() - ep) / ep
                else:
                    rec[f"ret_buy_{h}"] = np.nan
                    rec[f"ret_sell_{h}"] = np.nan
                    rec[f"mfe_buy_{h}"] = np.nan
                    rec[f"mae_buy_{h}"] = np.nan
                    rec[f"mfe_sell_{h}"] = np.nan
                    rec[f"mae_sell_{h}"] = np.nan
            
            records.append(rec)
        
        all_dfs.append(pd.DataFrame(records))

    df_all = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    df_all["timestamp"] = df_all["timestamp"].astype(str)
    
    parquet_path = out_dir / "unconditional_market_dataset.parquet"
    df_all.to_parquet(parquet_path, index=False)
    print(f"  ✓ Saved unconditional dataset: {parquet_path} ({len(df_all)} samples)")

if __name__ == "__main__":
    run()
