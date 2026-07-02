from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import pandas as pd

from btc_scraper.core.config import FRESH_TRAINING_DATA_DIR


def _find_monthly_files_for_coin(coin: str, interval: str, data_dir: Optional[str] = None) -> List[Path]:
    base = Path(data_dir) if data_dir else FRESH_TRAINING_DATA_DIR
    # Look under <base>/<COIN>/<INTERVAL>/*.csv
    candidate = base / coin / interval
    if candidate.exists():
        files = sorted(candidate.glob(f"{coin}_{interval}_*.csv"))
        return files

    # Fallback: search recursively for files that contain _<interval> in name
    matches = list(base.rglob(f"*_{interval}_*.csv"))
    return sorted(matches)


def smart_read_csv(path_or_key: str | Path, *, data_dir: Optional[str] = None, **kwargs) -> pd.DataFrame:
    """
    Read a CSV that may be either:
    - an actual existing file path -> delegated to pd.read_csv
    - a legacy flat path like data/BTC_1h.csv -> treated as coin_interval key and
      the function will locate monthly files under `FRESH_TRAINING_DATA_DIR` and concat them.

    Supports pandas.read_csv kwargs (e.g., parse_dates). When reading multiple monthly
    files the frames are concatenated and sorted by `time` if present.
    """
    p = Path(path_or_key)
    if p.exists():
        return pd.read_csv(p, **kwargs)

    # If not an existing file, try to interpret as COIN_INTERVAL (e.g., BTC_1h or BTC_15m)
    name = p.name
    parts = name.split("_")
    if len(parts) >= 2:
        coin = parts[0].upper()
        interval = parts[1]
        files = _find_monthly_files_for_coin(coin, interval, data_dir=data_dir)
        if not files:
            # As a last resort, try treating path_or_key as relative to repo 'data' dir
            # letting pd.read_csv raise a helpful error
            return pd.read_csv(str(path_or_key), **kwargs)

        # If kwargs contains nrows or use only first file, honor that to avoid reading everything
        if kwargs.get("nrows"):
            return pd.read_csv(files[0], **kwargs)

        frames = []
        for f in files:
            try:
                frames.append(pd.read_csv(f, **kwargs))
            except Exception:
                continue

        if not frames:
            raise FileNotFoundError(f"No CSV data found for {coin} {interval} under {FRESH_TRAINING_DATA_DIR}")

        df = pd.concat(frames, ignore_index=True)
        if "time" in df.columns:
            try:
                df["time"] = pd.to_datetime(df["time"])
            except Exception:
                pass
            df = df.sort_values(by="time").reset_index(drop=True)

        return df

    # Fallback to normal read_csv which will raise the appropriate error
    return pd.read_csv(str(path_or_key), **kwargs)
