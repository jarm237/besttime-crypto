import sys
from pathlib import Path
import pandas as pd

for s in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'DOGEUSDT']:
    files = sorted(list(Path(f'data/historical/normalized/futures_funding/{s}').glob('*.parquet')))
    if files:
        dfs = [pd.read_parquet(f) for f in files]
        full = pd.concat(dfs, ignore_index=True)
        print(f"{s}: {len(files)} parquet files | {len(full)} rows | cols={list(full.columns)} | min={full['available_at'].min()} | max={full['available_at'].max()}")
    else:
        print(f"{s}: NO FILES")
