#!/usr/bin/env python3
"""Fetch and freeze historical Binance futures klines representing aggressive trade flow."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
import requests
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]

# Output path
PARQUET_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4b_4b_trade_flow_history.parquet"

COINS = ["BTC", "ETH", "BNB"]
INTERVAL = "15m"
START_TIME_MS = int(pd.Timestamp("2023-01-01", tz="UTC").timestamp() * 1000)
END_TIME_MS = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1000) - 1

def fetch_klines(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    url = "https://fapi.binance.com/fapi/v1/klines"
    records = []
    current_start = start_ms
    limit = 1000
    
    print(f"Fetching futures klines for {symbol}...")
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
            # kline format:
            # [open_time, open, high, low, close, volume, close_time, quote_volume, trades, taker_base, taker_quote, ignore]
            records.append({
                "open_time_ms": int(k[0]),
                "close_time_ms": int(k[6]),
                "volume": float(k[5]),
                "quote_volume": float(k[7]),
                "trades": int(k[8]),
                "taker_buy_base_vol": float(k[9]),
                "taker_buy_quote_vol": float(k[10])
            })
            
        last_ms = int(data[-1][0])
        next_start = last_ms + 15 * 60 * 1000
        if next_start >= end_ms or len(data) < limit:
            break
        current_start = next_start
        time.sleep(0.1)
        
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.drop_duplicates(subset=["open_time_ms"]).sort_values("open_time_ms").reset_index(drop=True)
    return df

def main():
    PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    all_frames = []
    
    for coin in COINS:
        symbol = f"{coin}USDT"
        df_raw = fetch_klines(symbol, START_TIME_MS, END_TIME_MS)
        if df_raw.empty:
            print(f"CRITICAL ERROR: No data fetched for {coin}")
            sys.exit(1)
            
        # Normalize and map columns
        df_norm = pd.DataFrame()
        df_norm["symbol"] = [coin] * len(df_raw)
        df_norm["open_time"] = pd.to_datetime(df_raw["open_time_ms"], unit="ms", utc=True)
        df_norm["close_time"] = pd.to_datetime(df_raw["close_time_ms"], unit="ms", utc=True)
        
        # Taker buy notional = taker_buy_quote_vol
        df_norm["taker_buy_notional"] = df_raw["taker_buy_quote_vol"]
        # Taker sell notional = quote_volume - taker_buy_quote_vol
        df_norm["taker_sell_notional"] = df_raw["quote_volume"] - df_raw["taker_buy_quote_vol"]
        
        # Taker buy qty = taker_buy_base_vol
        df_norm["taker_buy_qty"] = df_raw["taker_buy_base_vol"]
        # Taker sell qty = volume - taker_buy_base_vol
        df_norm["taker_sell_qty"] = df_raw["volume"] - df_raw["taker_buy_base_vol"]
        
        df_norm["trade_count"] = df_raw["trades"]
        df_norm["source_timestamp"] = df_norm["open_time"]
        df_norm["available_at"] = df_norm["open_time"] + pd.Timedelta(minutes=15)
        df_norm["source"] = "BINANCE_AGGREGATED_TRADES"
        df_norm["provenance_class"] = "MARKET_OBSERVED"
        df_norm["interval"] = "15m"
        
        all_frames.append(df_norm)
        
    df_all = pd.concat(all_frames, ignore_index=True)
    df_all.to_parquet(PARQUET_PATH, index=False)
    print(f"✓ Saved canonical historical trade flow dataset to {PARQUET_PATH} (total {len(df_all)} rows)")
    
    # Assert PIT Policy
    assert (df_all["available_at"] == df_all["open_time"] + pd.Timedelta(minutes=15)).all()
    # Check that intervals are 15m
    for coin in COINS:
        df_coin = df_all[df_all["symbol"] == coin].sort_values("open_time")
        diffs = df_coin["open_time"].diff().dropna()
        expected = pd.Timedelta(minutes=15)
        mismatches = sum(diffs != expected)
        print(f"Asset {coin}: {len(df_coin)} rows. Mismatched intervals: {mismatches} ({mismatches/len(df_coin):.2%})")

if __name__ == "__main__":
    main()
