#!/usr/bin/env python3
"""Fetch historical macro indices, compute daily features, and apply timezone-aware DST closes."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
import requests
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
PARQUET_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4c_1b_cross_market_history.parquet"

TICKERS = {
    "vix": "^VIX",
    "spx": "^SPX",
    "dxy": "DX-Y.NYB",
    "us10y": "^TNX"
}

# 2023-01-01 to 2024-12-31
START_SEC = 1672531200
END_SEC = 1735689600

def fetch_ticker_data(ticker: str) -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={START_SEC}&period2={END_SEC}&interval=1d"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    print(f"Fetching {ticker}...")
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        result = data["chart"]["result"][0]
        timestamps = result.get("timestamp", [])
        closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
        
        # Build df
        df = pd.DataFrame({
            "timestamp_sec": timestamps,
            "close": closes
        })
        # Convert timestamp to date string in local market day
        df["date"] = pd.to_datetime(df["timestamp_sec"], unit="s", utc=True).dt.date
        return df[["date", "close"]].dropna()
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        sys.exit(1)

def main():
    PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    ticker_dfs = {}
    for name, ticker in TICKERS.items():
        df_ticker = fetch_ticker_data(ticker)
        df_ticker = df_ticker.rename(columns={"close": f"{name}_close"})
        ticker_dfs[name] = df_ticker
        time.sleep(0.1)
        
    # Merge all tickers on date
    df_merged = ticker_dfs["vix"]
    for name in ["spx", "dxy", "us10y"]:
        df_merged = pd.merge(df_merged, ticker_dfs[name], on="date", how="outer")
        
    df_merged = df_merged.sort_values("date").reset_index(drop=True)
    df_merged["date"] = pd.to_datetime(df_merged["date"])
    
    # Reindex to cover ALL days (including weekends and holidays)
    full_range = pd.date_range(start="2023-01-01", end="2024-12-31", freq="D")
    df_merged = df_merged.set_index("date").reindex(full_range)
    
    # Forward fill missing values (weekends/holidays)
    for col in [f"{n}_close" for n in TICKERS]:
        df_merged[col] = df_merged[col].ffill().bfill()
        
    df_merged = df_merged.reset_index().rename(columns={"index": "date"})
    
    # Calculate DST-Aware available_at in America/New_York time + 1 hour lag
    available_at_list = []
    for d in df_merged["date"]:
        # Localize to NY time at 16:00 (Market close)
        ny_close = d.tz_localize("America/New_York") + pd.Timedelta(hours=16)
        # Add 1 hour conservative lag -> 17:00 NY time
        ny_avail = ny_close + pd.Timedelta(hours=1)
        # Convert to UTC
        available_at_list.append(ny_avail.tz_convert("UTC"))
        
    df_merged["available_at"] = available_at_list
    df_merged["available_at"] = pd.to_datetime(df_merged["available_at"], utc=True).astype("datetime64[ns, UTC]")
    
    # Compute macro features on daily dataset BEFORE merging to 15m
    df_merged["CM1_VIX_percentile_60d"] = df_merged["vix_close"].rolling(60, min_periods=15).rank(pct=True).fillna(0.5)
    df_merged["CM2_VIX_change_5d"] = df_merged["vix_close"].diff(5).fillna(0.0)
    df_merged["CM3_SPX_return_5d"] = df_merged["spx_close"].pct_change(5).fillna(0.0)
    df_merged["CM4_DXY_return_5d"] = df_merged["dxy_close"].pct_change(5).fillna(0.0)
    df_merged["CM5_US10Y_change_5d"] = df_merged["us10y_close"].diff(5).fillna(0.0)
    
    # SPX 30-day realized volatility
    spx_ret = df_merged["spx_close"].pct_change()
    df_merged["spx_rv_30d"] = spx_ret.rolling(30, min_periods=10).std().fillna(0.0)
    
    df_merged["source"] = "YAHOO_FINANCE"
    df_merged["provenance_class"] = "MARKET_OBSERVED"
    
    # Save Parquet
    df_merged.to_parquet(PARQUET_PATH, index=False)
    print(f"✓ Saved daily macro history Parquet to {PARQUET_PATH} (total {len(df_merged)} rows)")

if __name__ == "__main__":
    main()
