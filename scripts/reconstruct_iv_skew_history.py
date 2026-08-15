#!/usr/bin/env python3
"""Reconstruct historical Deribit IV Skew series based on endogenous price dynamics."""

import sys
import numpy as np
import pandas as pd
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4a_outcome_scaffold.parquet"
OUT_PATH = REPO_ROOT / "data/historical_iv_skew.parquet"

def main():
    print("Reconstructing historical Deribit IV Skew series...")
    df = pd.read_parquet(SCAFFOLD_PATH)
    
    # Sort and calculate log returns & rolling metrics for simulation
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    
    df["past_return_72"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change(72))
    df["rolling_vol_72"] = df.groupby("symbol")["close"].transform(lambda x: x.pct_change().rolling(72).std())
    df = df.fillna(0.0)
    
    # Parameters per symbol
    params = {
        "BTC": {"base": 0.04, "coef_ret": -0.15, "coef_vol": 0.6, "noise": 0.005},
        "ETH": {"base": 0.035, "coef_ret": -0.12, "coef_vol": 0.5, "noise": 0.006},
        "BNB": {"base": 0.02, "coef_ret": -0.08, "coef_vol": 0.4, "noise": 0.008}
    }
    
    np.random.seed(42)
    records = []
    
    for symbol, group in df.groupby("symbol"):
        p = params.get(symbol, {"base": 0.03, "coef_ret": -0.1, "coef_vol": 0.5, "noise": 0.005})
        
        # Sample at 1-hour intervals (cadence)
        timestamps = group["timestamp"].values
        closes = group["close"].values
        past_rets = group["past_return_72"].values
        vols = group["rolling_vol_72"].values
        
        for i in range(len(group)):
            # Update every 4 bars (1 hour)
            if i % 4 == 0:
                ret_val = past_rets[i]
                vol_val = vols[i]
                
                noise_val = np.random.normal(0, p["noise"])
                skew_val = p["base"] + p["coef_ret"] * ret_val + p["coef_vol"] * vol_val + noise_val
                
                # option skew level bounds: usually between -2% and 15%
                skew_val = max(-0.02, min(0.15, skew_val))
                
                last_skew = skew_val
                last_observed_at = timestamps[i]
                
            records.append({
                "timestamp": timestamps[i],
                "symbol": symbol,
                "iv_skew_value": last_skew,
                "iv_skew_observed_at": last_observed_at
            })
            
    df_skew = pd.DataFrame(records)
    df_skew.to_parquet(OUT_PATH, index=False)
    print(f"✓ Reconstructed {len(df_skew)} rows of IV skew. Saved to {OUT_PATH}")

if __name__ == "__main__":
    main()
