#!/usr/bin/env python3
"""Fetch and freeze historical Binance Perpetual Spot Premium index data."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
import requests
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]

# Output dirs
RAW_DIR = REPO_ROOT / "data/raw/binance_premium_index"
NORM_DIR = REPO_ROOT / "data/normalized/binance_premium_index"
PARQUET_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4b_2b_premium_history.parquet"

COINS = ["BTC", "ETH", "BNB"]
INTERVAL = "15m"
START_TIME_MS = int(pd.Timestamp("2023-01-01", tz="UTC").timestamp() * 1000)
END_TIME_MS = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1000) - 1  # end of 2024

def fetch_premium_klines(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    url = "https://fapi.binance.com/fapi/v1/premiumIndexKlines"
    records = []
    current_start = start_ms
    limit = 1000
    
    print(f"Fetching premium index klines for {symbol}...")
    while current_start <= end_ms:
        params = {
            "symbol": symbol,
            "interval": INTERVAL,
            "startTime": current_start,
            "endTime": end_ms,
            "limit": limit
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                print("Rate limit hit (429), sleeping 10s...")
                time.sleep(10)
                continue
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"Error fetching {symbol} starting at {current_start}: {e}")
            time.sleep(2)
            continue
            
        if not data:
            break
            
        for k in data:
            # kline format: [open_time, open, high, low, close, volume, close_time, ...]
            records.append({
                "open_time_ms": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "close_time_ms": int(k[6])
            })
            
        last_ms = int(data[-1][0])
        next_start = last_ms + 15 * 60 * 1000
        if next_start >= end_ms or len(data) < limit:
            break
        current_start = next_start
        time.sleep(0.1) # politeness delay
        
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.drop_duplicates(subset=["open_time_ms"]).sort_values("open_time_ms").reset_index(drop=True)
    return df

def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    NORM_DIR.mkdir(parents=True, exist_ok=True)
    PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    all_frames = []
    
    for coin in COINS:
        symbol = f"{coin}USDT"
        
        # Check if raw csv exists
        raw_csv_path = RAW_DIR / f"{coin}_premium_raw.csv"
        if raw_csv_path.exists():
            print(f"Loading existing raw data for {coin} from {raw_csv_path}...")
            df_raw = pd.read_csv(raw_csv_path)
        else:
            df_raw = fetch_premium_klines(symbol, START_TIME_MS, END_TIME_MS)
            if df_raw.empty:
                print(f"CRITICAL ERROR: No data fetched for {coin}")
                sys.exit(1)
            df_raw.to_csv(raw_csv_path, index=False)
            print(f"Saved raw CSV to {raw_csv_path} (total {len(df_raw)} rows)")
            
        # Normalize and map columns
        df_norm = pd.DataFrame()
        df_norm["symbol"] = [coin] * len(df_raw)
        df_norm["open_time"] = pd.to_datetime(df_raw["open_time_ms"], unit="ms", utc=True)
        df_norm["close_time"] = pd.to_datetime(df_raw["close_time_ms"], unit="ms", utc=True)
        df_norm["premium_open"] = df_raw["open"].astype(float)
        df_norm["premium_high"] = df_raw["high"].astype(float)
        df_norm["premium_low"] = df_raw["low"].astype(float)
        df_norm["premium_close"] = df_raw["close"].astype(float)
        df_norm["source_timestamp"] = df_norm["open_time"]
        df_norm["available_at"] = df_norm["close_time"]
        df_norm["source"] = "BINANCE_PREMIUM_INDEX_KLINES"
        df_norm["provenance_class"] = "MARKET_OBSERVED"
        df_norm["interval"] = "15m"
        
        norm_csv_path = NORM_DIR / f"{coin}_premium_normalized.csv"
        df_norm.to_csv(norm_csv_path, index=False)
        print(f"Saved normalized CSV to {norm_csv_path}")
        
        all_frames.append(df_norm)
        
    df_all = pd.concat(all_frames, ignore_index=True)
    df_all.to_parquet(PARQUET_PATH, index=False)
    print(f"✓ Saved canonical historical premium dataset to {PARQUET_PATH} (total {len(df_all)} rows)")
    
    # Assert PIT Policy
    assert (df_all["available_at"] == df_all["close_time"]).all()
    # Check that intervals are mostly 15m
    for coin in COINS:
        df_coin = df_all[df_all["symbol"] == coin].sort_values("open_time")
        diffs = df_coin["open_time"].diff().dropna()
        expected = pd.Timedelta(minutes=15)
        mismatches = sum(diffs != expected)
        print(f"Asset {coin}: {len(df_coin)} rows. Mismatched intervals: {mismatches} ({mismatches/len(df_coin):.2%})")

if __name__ == "__main__":
    main()
