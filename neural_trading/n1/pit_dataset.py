"""
neural_trading/n1/pit_dataset.py

Point-in-time (PIT) dataset builder from checksum-verified raw Binance archives
acquired for N1:
  - Spot 1h klines across 13 USDT pairs (2017-08 .. 2025-12)
  - USD-M daily bookDepth across BTCUSDT & ETHUSDT (2023-01-01 .. 2025-12-31)

All rows are indexed by `available_at` (UTC hour boundary when the bar/window
closes). A bar covering [t - 1h, t) has open_time = t - 3600s and is strictly
available at t. Forward returns over horizon H use close(t + H) / close(t) - 1.
"""
from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

SPOT_SYMBOLS: Tuple[str, ...] = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "LTCUSDT", "ADAUSDT",
    "XRPUSDT", "EOSUSDT", "XLMUSDT", "TRXUSDT", "ETCUSDT",
    "LINKUSDT", "DOGEUSDT", "SOLUSDT",
)
DEPTH_SYMBOLS: Tuple[str, ...] = ("BTCUSDT", "ETHUSDT")


def _open_time_to_avail_sec(raw_open_time: int) -> int:
    # Binance switched spot archive timestamps from ms (13 digits) to us (16 digits) in 2025-01.
    if raw_open_time >= 10**14:
        open_sec = raw_open_time // 1_000_000
    else:
        open_sec = raw_open_time // 1_000
    # 1h bar covering [open_sec, open_sec + 3600) is available at open_sec + 3600
    return (open_sec // 3600) * 3600 + 3600


def load_spot_symbol_1h(raw_root: Path, symbol: str) -> pd.DataFrame:
    sym_dir = raw_root / "binance_spot_klines_1h" / symbol
    rows = []
    for zpath in sorted(sym_dir.glob(f"{symbol}-1h-*.zip")):
        with zipfile.ZipFile(zpath, "r") as zf:
            name = zf.namelist()[0]
            with zf.open(name) as fh:
                text = io.TextIOWrapper(fh, encoding="utf-8")
                for line in csv.reader(text):
                    if not line or not line[0][0].isdigit():
                        continue
                    avail_sec = _open_time_to_avail_sec(int(line[0]))
                    rows.append((
                        avail_sec,
                        float(line[1]),  # open
                        float(line[2]),  # high
                        float(line[3]),  # low
                        float(line[4]),  # close
                        float(line[5]),  # base volume
                        float(line[7]),  # quote volume (USDT)
                        float(line[8]),  # trade count
                        float(line[9]),  # taker buy base
                        float(line[10]), # taker buy quote (USDT)
                    ))
    df = pd.DataFrame(rows, columns=[
        "avail_sec", "open", "high", "low", "close",
        "volume", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote",
    ])
    df = df.drop_duplicates(subset=["avail_sec"], keep="last").sort_values("avail_sec")
    df["available_at"] = pd.to_datetime(df["avail_sec"], unit="s", utc=True)
    return df.set_index("available_at")


def build_spot_panel(
    raw_root: Path,
    symbols: Sequence[str] = SPOT_SYMBOLS,
    cache_path: Path | None = None,
) -> Dict[str, pd.DataFrame]:
    if cache_path is not None and cache_path.exists():
        flat = pd.read_parquet(cache_path)
        return {k: g.droplevel(0) for k, g in flat.groupby(level=0)}

    per_sym = {s: load_spot_symbol_1h(raw_root, s) for s in symbols}
    t_min = min(df.index.min() for df in per_sym.values())
    t_max = max(df.index.max() for df in per_sym.values())
    grid = pd.date_range(t_min, t_max, freq="1h", tz="UTC", name="available_at")

    fields = ["open", "high", "low", "close", "volume", "quote_volume",
              "trades", "taker_buy_base", "taker_buy_quote"]
    panel: Dict[str, pd.DataFrame] = {}
    for f in fields:
        panel[f] = pd.DataFrame({s: per_sym[s][f].reindex(grid) for s in symbols}, index=grid)

    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        flat = pd.concat(panel, names=["field", "available_at"])
        flat.to_parquet(cache_path)
    return panel


def _parse_bookdepth_day(zpath: Path) -> List[Tuple[str, float, float, float, float, float]]:
    """
    Aggregates one daily bookDepth zip (~30s snapshots, percentages -5..-1, +1..+5)
    into 24 hourly rows keyed by `hour_prefix` ('YYYY-MM-DD HH').
    """
    with zipfile.ZipFile(zpath, "r") as zf:
        raw = zf.read(zf.namelist()[0]).decode("utf-8")
    df = pd.read_csv(io.StringIO(raw))
    if df.empty:
        return []
    df["hour_prefix"] = df["timestamp"].str.slice(0, 13)
    piv = df.pivot_table(index=["hour_prefix", "timestamp"], columns="percentage", values="notional", aggfunc="last")
    required = [-5, -1, 1, 5]
    if not all(c in piv.columns for c in required):
        return []
    b1, a1 = piv[-1].to_numpy(), piv[1].to_numpy()
    b5, a5 = piv[-5].to_numpy(), piv[5].to_numpy()
    tot1 = np.maximum(b1 + a1, 1e-6)
    tot5 = np.maximum(b5 + a5, 1e-6)
    snap = pd.DataFrame({
        "hour_prefix": piv.index.get_level_values(0),
        "imb_1pct": (b1 - a1) / tot1,
        "imb_5pct": (b5 - a5) / tot5,
        "slope_1_5": tot1 / tot5,
        "tot1_usd": tot1,
    })
    grp = snap.groupby("hour_prefix", sort=True)
    out_df = pd.DataFrame({
        "imb_1pct_mean": grp["imb_1pct"].mean(),
        "imb_1pct_last": grp["imb_1pct"].last(),
        "imb_5pct_mean": grp["imb_5pct"].mean(),
        "slope_1_5_mean": grp["slope_1_5"].mean(),
        "tot1_usd_mean": grp["tot1_usd"].mean(),
    }).reset_index()
    return [tuple(x) for x in out_df.to_numpy()]


def build_bookdepth_hourly(
    raw_root: Path,
    symbols: Sequence[str] = DEPTH_SYMBOLS,
    cache_path: Path | None = None,
) -> Dict[str, pd.DataFrame]:
    if cache_path is not None and cache_path.exists():
        flat = pd.read_parquet(cache_path)
        return {k: g.droplevel(0) for k, g in flat.groupby(level=0)}

    per_sym: Dict[str, pd.DataFrame] = {}
    for s in symbols:
        sym_dir = raw_root / "binance_um_bookdepth" / s
        rows: List[Tuple[str, float, float, float, float, float]] = []
        for zpath in sorted(sym_dir.glob(f"{s}-bookDepth-*.zip")):
            rows.extend(_parse_bookdepth_day(zpath))
        df = pd.DataFrame(rows, columns=[
            "hour_prefix", "imb_1pct_mean", "imb_1pct_last",
            "imb_5pct_mean", "slope_1_5_mean", "tot1_usd_mean",
        ])
        df = df.drop_duplicates(subset=["hour_prefix"], keep="last").sort_values("hour_prefix")
        # Snapshots in 'YYYY-MM-DD HH' cover [HH:00, HH+1:00) and are available at HH+1:00 UTC
        df["available_at"] = pd.to_datetime(df["hour_prefix"] + ":00:00", utc=True) + pd.Timedelta(hours=1)
        df = df.set_index("available_at").drop(columns=["hour_prefix"])
        # Causal 7-day (168h) log depth z-score and 4h moving averages
        log_depth = np.log(np.maximum(df["tot1_usd_mean"], 1.0))
        mu168 = log_depth.rolling(168, min_periods=48).mean()
        sd168 = log_depth.rolling(168, min_periods=48).std().replace(0.0, np.nan)
        df["depth_thinning_z168h"] = (log_depth - mu168) / sd168
        df["imb_1pct_ma4h"] = df["imb_1pct_mean"].rolling(4, min_periods=2).mean()
        df["imb_5pct_ma4h"] = df["imb_5pct_mean"].rolling(4, min_periods=2).mean()
        per_sym[s] = df

    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        flat = pd.concat(per_sym, names=["symbol", "available_at"])
        flat.to_parquet(cache_path)
    return per_sym
