#!/usr/bin/env python3
"""Fetch historical ETF flows, compute pre-registered features, and apply conservative availability lag."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))
PARQUET_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4c_3b_etf_history.parquet"

FUNDS = ["IBIT", "FBTC", "BITB", "ARKB", "BTCO", "EZBC", "BRRR", "HODL", "BTCW", "MSBT", "GBTC"]

def main():
    load_dotenv()
    PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    print("Fetching historical ETF flows from Parsebot...")
    try:
        from btc_scraper.collectors.parsebot_farside_collector import ParsebotFarsideETFCollector
        collector = ParsebotFarsideETFCollector()
        res = collector.fetch(symbol="BTC", mode="all")
        if res.get("status") != "ok":
            print(f"Error fetching from Parsebot: {res.get('error')}")
            sys.exit(1)
        data = res["value"]["data"]["data"]
    except Exception as e:
        print(f"Error initializing collector: {e}")
        sys.exit(1)
        
    records = []
    for row in data:
        # Date format: e.g. "11 Jan 2024"
        dt = pd.to_datetime(row["Date"])
        rec = {"date": dt.date()}
        
        # Pull fund values, missing fields filled with 0.0
        for fund in FUNDS:
            rec[fund] = float(row.get(fund, 0.0) or 0.0)
            
        rec["Total"] = float(row.get("Total", 0.0) or 0.0)
        records.append(rec)
        
    df_raw = pd.DataFrame(records).drop_duplicates(subset=["date"])
    df_raw["date"] = pd.to_datetime(df_raw["date"])
    df_raw = df_raw.sort_values("date").reset_index(drop=True)
    
    # Complete calendar from 2023-01-01 to 2024-12-31
    full_range = pd.date_range(start="2023-01-01", end="2024-12-31", freq="D")
    df = df_raw.set_index("date").reindex(full_range)
    
    # Fill missing dates (weekends, holidays) with 0.0 flows
    for col in FUNDS + ["Total"]:
        df[col] = df[col].fillna(0.0)
        
    df = df.reset_index().rename(columns={"index": "date"})
    
    # available_at: trade_date + 1 day at 12:00 UTC
    df["available_at"] = df["date"] + pd.Timedelta(days=1) + pd.Timedelta(hours=12)
    df["available_at"] = pd.to_datetime(df["available_at"], utc=True).astype("datetime64[ns, UTC]")
    
    # Feature Calculations
    # ETF1: total_net_flow_usd (rolling 7-day sum of daily total flow)
    df["ETF1_total_net_flow_usd"] = df["Total"].rolling(7, min_periods=1).sum().fillna(0.0)
    
    # ETF2: ex_gbtc_net_flow_usd (rolling 7-day sum of daily flow excluding GBTC)
    ex_gbtc_daily = df["Total"] - df["GBTC"]
    df["ETF2_ex_gbtc_net_flow_usd"] = ex_gbtc_daily.rolling(7, min_periods=1).sum().fillna(0.0)
    
    # ETF3: net_flow_as_pct_aum (set to NaN to represent REJECT_FEATURE_PROVENANCE due to no verified PIT-safe AUM data)
    df["ETF3_net_flow_as_pct_aum"] = np.nan
    
    # ETF4: rolling_flow_zscore_20d (calculated PIT-safely using lagged rolling window)
    mean_20d = df["Total"].shift(1).rolling(20, min_periods=5).mean().fillna(0.0)
    std_20d = df["Total"].shift(1).rolling(20, min_periods=5).std().fillna(1.0)
    # prevent divide by zero
    std_20d = std_20d.replace(0.0, 1.0)
    df["ETF4_rolling_flow_zscore_20d"] = ((df["Total"] - mean_20d) / std_20d).fillna(0.0)
    
    # ETF5: cumulative_net_flow_5d (rolling 5-day sum of total daily flow)
    df["ETF5_cumulative_net_flow_5d"] = df["Total"].rolling(5, min_periods=1).sum().fillna(0.0)
    
    df["source"] = "PARSEBOT_FARSIDE"
    df["provenance_class"] = "MARKET_OBSERVED"
    
    df.to_parquet(PARQUET_PATH, index=False)
    print(f"✓ Saved daily ETF history Parquet to {PARQUET_PATH} (total {len(df)} rows)")

if __name__ == "__main__":
    main()
