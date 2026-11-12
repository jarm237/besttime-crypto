import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np
from neural_trading.data.pipeline import MultiAssetDataPipeline
from neural_trading.data.schema import CORE_PILOT_UNIVERSE

def audit_timeline():
    pipeline = MultiAssetDataPipeline()
    print("=== AUDITING RAW DATA PER SYMBOL ===")
    raw_data = {}
    for sym in CORE_PILOT_UNIVERSE:
        df = pipeline.load_raw_candles_for_symbol(sym, "2023-01", "2025-12")
        raw_data[sym] = df
        warmup_cnt = (df["is_warmup"] == 1).sum() if "is_warmup" in df.columns else 0
        non_warmup_cnt = (df["is_warmup"] == 0).sum() if "is_warmup" in df.columns else len(df)
        print(f"Symbol: {sym:<8} | Total: {len(df):<6} | Warmup: {warmup_cnt:<5} | Non-Warmup: {non_warmup_cnt:<6} | Start: {df['time'].min()} | End: {df['time'].max()}")

    # Theoretical hourly bars from 2023-01-01 00:00:00 to 2025-12-31 23:00:00
    expected_range = pd.date_range("2023-01-01 00:00:00", "2025-12-31 23:00:00", freq="1h")
    print(f"\nTheoretical 1h bars (2023-01-01 00:00 to 2025-12-31 23:00): {len(expected_range)} bars (3 years = 365 + 366 + 365 = 1096 days * 24 = 26,304 bars)")

    # Check non-warmup start times
    for sym, df in raw_data.items():
        nw = df[df["is_warmup"] == 0]
        print(f"Non-warmup {sym:<8}: Start={nw['time'].min()} | End={nw['time'].max()} | Count={len(nw)}")
        # Check diffs in nw
        diffs = nw["time"].diff()
        jumps = nw[diffs > pd.Timedelta(hours=1)]
        print(f"  Jumps > 1h in non-warmup {sym}: {len(jumps)}")
        if len(jumps) > 0:
            for idx, row in jumps.head(5).iterrows():
                prev_time = nw.loc[idx - 1, 'time'] if (idx - 1) in nw.index else 'N/A'
                print(f"    Gap: {prev_time} -> {row['time']} (diff: {row['time'] - prev_time if prev_time != 'N/A' else 'N/A'})")

    # Common times as done in N0 pipeline
    common_times = None
    for sym, df in raw_data.items():
        valid_times = set(df[df["is_warmup"] == 0]["time"])
        if common_times is None:
            common_times = valid_times
        else:
            common_times = common_times.intersection(valid_times)

    sorted_times = sorted(list(common_times))
    print(f"\nN0 Intersection common_times count: {len(sorted_times)}")
    print(f"Start: {sorted_times[0]}, End: {sorted_times[-1]}")
    s_series = pd.Series(sorted_times)
    diffs = s_series.diff()
    gaps = s_series[diffs > pd.Timedelta(hours=1)]
    print(f"Number of gaps > 1h in N0 sorted_times: {len(gaps)}")
    for idx in gaps.index:
        prev_t = s_series.iloc[idx - 1]
        curr_t = s_series.iloc[idx]
        print(f"  Gap at idx {idx}: {prev_t} -> {curr_t} (diff={curr_t - prev_t})")

if __name__ == "__main__":
    audit_timeline()
