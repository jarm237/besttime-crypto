#!/usr/bin/env python3
"""Fetch historical stablecoin supply, compute daily features, and apply conservative availability lag."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
import requests
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
PARQUET_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4c_2b_stablecoin_history.parquet"

DEFILLAMA_CHARTS_URL = "https://stablecoins.llama.fi/stablecoincharts/all"

def main():
    PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    print("Fetching historical stablecoin supply from DefiLlama...")
    try:
        resp = requests.get(DEFILLAMA_CHARTS_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error fetching stablecoin supply: {e}")
        sys.exit(1)
        
    records = []
    for row in data:
        dt = pd.to_datetime(int(row["date"]), unit="s", utc=True)
        # We target aggregate circulating USD-pegged supply
        val = row.get("totalCirculatingUSD", {}).get("peggedUSD")
        if val is not None:
            records.append({
                "date": dt.date(),
                "stablecoin_supply": float(val)
            })
            
    df = pd.DataFrame(records).dropna().drop_duplicates(subset=["date"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    
    # Filter 2023-01-01 to 2024-12-31
    full_range = pd.date_range(start="2023-01-01", end="2024-12-31", freq="D")
    df = df.set_index("date").reindex(full_range)
    df["stablecoin_supply"] = df["stablecoin_supply"].ffill().bfill()
    df = df.reset_index().rename(columns={"index": "date"})
    
    # available_at: 1-day conservative release lag at 00:00 UTC
    df["available_at"] = df["date"] + pd.Timedelta(days=1)
    df["available_at"] = pd.to_datetime(df["available_at"], utc=True).astype("datetime64[ns, UTC]")
    
    # Compute daily rolling features
    supply = df["stablecoin_supply"]
    df["SC1_stablecoin_supply_growth_7d"] = supply.pct_change(7).fillna(0.0)
    df["SC2_stablecoin_supply_growth_30d"] = supply.pct_change(30).fillna(0.0)
    
    # SC3: net_issuance_7d_normalized
    daily_diff = supply.diff(1)
    rolling_std = daily_diff.rolling(90, min_periods=30).std().fillna(1.0)
    normalized_diff = daily_diff / rolling_std
    df["SC3_net_issuance_7d_normalized"] = normalized_diff.rolling(7).sum().fillna(0.0)
    
    # SC4: net_issuance_percentile_90d
    diff_7d = supply - supply.shift(7)
    df["SC4_net_issuance_percentile_90d"] = diff_7d.rolling(90, min_periods=30).rank(pct=True).fillna(0.5)
    
    df["source"] = "DEFILLAMA"
    df["provenance_class"] = "MARKET_OBSERVED"
    
    df.to_parquet(PARQUET_PATH, index=False)
    print(f"✓ Saved daily stablecoin history Parquet to {PARQUET_PATH} (total {len(df)} rows)")

if __name__ == "__main__":
    main()
