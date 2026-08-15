#!/usr/bin/env python3
"""HMR-V3.4: Economic Event Clustering.

Filters unconditional dataset for overlapping price moves and clusters adjacent
timestamps into distinct, independent Economic Events to prevent training contamination.
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

# Target threshold for event definitions
MFE_LIMIT = 0.0030 # 30 bps
MAE_LIMIT = 0.0020 # 20 bps
HORIZON = 72

def cluster_events(df: pd.DataFrame, side: str) -> pd.DataFrame:
    # Filter for bars where maximum favorable excursion (MFE) was reached before adverse excursion (MAE)
    mfe_col = f"mfe_{side.lower()}_{HORIZON}"
    mae_col = f"mae_{side.lower()}_{HORIZON}"
    
    positives = df[(df[mfe_col] >= MFE_LIMIT) & (df[mae_col] < MAE_LIMIT)].copy()
    if len(positives) == 0:
        return pd.DataFrame()
        
    positives["timestamp"] = pd.to_datetime(positives["timestamp"])
    positives = positives.sort_values(["symbol", "timestamp"])
    
    events = []
    for symbol, g in positives.groupby("symbol"):
        g = g.sort_values("timestamp")
        
        # Cluster consecutive timestamps (within 72 bars = 18 hours threshold)
        cluster_id = 0
        prev_ts = None
        
        cluster_labels = []
        for ts in g["timestamp"]:
            if prev_ts is None:
                cluster_labels.append(cluster_id)
            elif (ts - prev_ts) > pd.Timedelta(minutes=15 * HORIZON):
                cluster_id += 1
                cluster_labels.append(cluster_id)
            else:
                cluster_labels.append(cluster_id)
            prev_ts = ts
            
        g["cluster_idx"] = cluster_labels
        
        # Aggregate clusters into single representative events
        for c_idx, cg in g.groupby("cluster_idx"):
            start_ts = cg["timestamp"].min()
            end_ts = cg["timestamp"].max()
            
            # Rep entry is the first bar in the squeeze/move initiation
            rep_bar = cg.iloc[0]
            
            events.append({
                "economic_event_id": f"V3_{symbol}_{side}_{start_ts.strftime('%Y%m%d%H%M')}",
                "symbol": symbol,
                "side": side,
                "event_start": start_ts,
                "event_end": end_ts,
                "duration_bars": len(cg),
                "close_entry": rep_bar["close"],
                f"mfe_{HORIZON}": rep_bar[mfe_col],
                f"mae_{HORIZON}": rep_bar[mae_col]
            })
            
    return pd.DataFrame(events)

def run():
    base_dir = REPO_ROOT / "research/historical_market_replay_v3/v3_1_economic_events"
    ds_path  = base_dir / "unconditional_market_dataset.parquet"
    if not ds_path.exists():
        print(f"ERROR: Dataset not found: {ds_path}")
        sys.exit(1)
        
    print("HMR-V3.4: Clustering Overlapping Economic Events...")
    df = pd.read_parquet(ds_path)
    
    buy_events = cluster_events(df, "BUY")
    sell_events = cluster_events(df, "SELL")
    
    all_events = pd.concat([buy_events, sell_events], ignore_index=True) if not buy_events.empty or not sell_events.empty else pd.DataFrame()
    
    if not all_events.empty:
        all_events["event_start"] = all_events["event_start"].astype(str)
        all_events["event_end"] = all_events["event_end"].astype(str)
        
        out_path = base_dir / "clustered_economic_events.parquet"
        all_events.to_parquet(out_path, index=False)
        print(f"  ✓ Saved clustered events: {out_path} ({len(all_events)} events)")
        
        # Print metrics
        print("\nClustering Metrics:")
        print(f"  Total BUY events: {len(buy_events)}")
        print(f"  Total SELL events: {len(sell_events)}")
        if len(buy_events) > 0:
            print(f"  Average BUY event overlap: {buy_events['duration_bars'].mean():.1f} bars")
        if len(sell_events) > 0:
            print(f"  Average SELL event overlap: {sell_events['duration_bars'].mean():.1f} bars")
    else:
        print("  WARN: No positive target events found matching MFE/MAE threshold constraints.")

if __name__ == "__main__":
    run()
