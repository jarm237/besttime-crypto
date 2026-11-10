import glob
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

base_dir = Path("data/fresh_training_data_2023_2026")
sample_coins = ["BTC", "ETH", "SOL", "WLD", "AEVO"]
timeframes = ["15m", "1h"]

tf_deltas = {
    "15m": pd.Timedelta(minutes=15),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}

print("=== DEEP DATA QUALITY VALIDATION ===")

for coin in sample_coins:
    for tf in timeframes:
        delta = tf_deltas[tf]
        csvs = sorted(glob.glob(str(base_dir / coin / tf / "*.csv")))
        if not csvs:
            continue
        
        total_rows = 0
        total_warmup = 0
        total_gaps = 0
        gap_intervals = []
        invalid_ohlc = 0
        negative_vol = 0
        duplicate_ts = 0
        non_monotonic = 0
        
        prev_dt = None
        
        for c in csvs:
            df = pd.read_csv(c)
            total_rows += len(df)
            total_warmup += (df.get("is_warmup", 0) == 1).sum()
            
            # Check OHLC validity
            bad_high = (df["high"] < df[["open", "close"]].max(axis=1)).sum()
            bad_low = (df["low"] > df[["open", "close"]].min(axis=1)).sum()
            invalid_ohlc += (bad_high + bad_low)
            negative_vol += (df["volume"] < 0).sum()
            
            # Check timestamps
            ts_series = pd.to_datetime(df["time"], format="%Y-%m-%d %H:%M", utc=True)
            
            # Monotonicity & duplicates within file
            diffs = ts_series.diff()
            if len(diffs) > 1:
                duplicate_ts += (diffs[1:] == pd.Timedelta(0)).sum()
                non_monotonic += (diffs[1:] < pd.Timedelta(0)).sum()
            
            # Cross-file check
            for dt in ts_series:
                if prev_dt is not None:
                    step = dt - prev_dt
                    if step == pd.Timedelta(0):
                        duplicate_ts += 1
                    elif step < pd.Timedelta(0):
                        non_monotonic += 1
                    elif step > delta:
                        # Gap detected!
                        missing_bars = int(step / delta) - 1
                        total_gaps += missing_bars
                        gap_intervals.append((str(prev_dt), str(dt), missing_bars))
                prev_dt = dt
                
        print(f"[{coin} {tf}] Rows: {total_rows} | Warmup: {total_warmup} | Invalid OHLC: {invalid_ohlc} | Neg Vol: {negative_vol} | Dups: {duplicate_ts} | Non-mono: {non_monotonic} | Gaps: {total_gaps}")
        if gap_intervals:
            print(f"   First 3 gaps in {coin} {tf}: {gap_intervals[:3]}")
