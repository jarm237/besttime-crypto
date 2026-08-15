#!/usr/bin/env python3
"""Fetch complete historical funding rates from Binance Futures public API."""

import sys
import time
from pathlib import Path
import requests
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "data/historical_funding_rates.parquet"

COINS = ["BTC", "ETH", "BNB"]
START_TIME = int(pd.Timestamp("2023-01-01", tz="UTC").timestamp() * 1000)
END_TIME = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1000)

def fetch_funding_history(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    records = []
    current_start = start_ms
    
    print(f"Fetching funding rates for {symbol}...")
    while current_start < end_ms:
        params = {
            "symbol": symbol,
            "startTime": current_start,
            "endTime": end_ms,
            "limit": 1000
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                print("Rate limit hit, sleeping 10s...")
                time.sleep(10)
                continue
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"Error fetching {symbol} at {current_start}: {e}")
            break
            
        if not data:
            break
            
        for d in data:
            records.append({
                "timestamp": pd.to_datetime(d["fundingTime"], unit="ms", utc=True),
                "symbol": symbol.replace("USDT", ""),
                "funding_rate": float(d["fundingRate"])
            })
            
        last_ms = int(data[-1]["fundingTime"])
        if last_ms >= end_ms or len(data) < 1000:
            break
        current_start = last_ms + 1
        time.sleep(0.2)
        
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df

def main():
    all_dfs = []
    for coin in COINS:
        df = fetch_funding_history(f"{coin}USDT", START_TIME, END_TIME)
        print(f"  ✓ Fetched {len(df)} rows for {coin}")
        all_dfs.append(df)
        
    df_all = pd.concat(all_dfs, ignore_index=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_all.to_parquet(OUT_PATH, index=False)
    print(f"✓ Saved all funding rates to {OUT_PATH} (total {len(df_all)} rows)")

if __name__ == "__main__":
    main()
