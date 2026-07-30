"""
Calibration helper for market regime thresholds.

Scans a CSV of historical candles, computes ADX and ATR% distributions,
and writes a suggested `regime_config.json` next to the detector.

Usage:
    python3 -m btc_scraper.regime_calibrate --csv data/april_BTC_1h.csv

This atomically updates the canonical `btc_scraper/regime/regime_config.json`
with percentile-based ADX/ATR thresholds while preserving the full v2 schema.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from btc_scraper.core.io import smart_read_csv

from btc_scraper.regime.market_regime import calculate_adx, calculate_atr, _get_col
from btc_scraper.regime.config import (
    atomic_write_regime_config,
    load_regime_config,
    resolve_regime_config_path,
)


def _load_csv(path: str) -> pd.DataFrame:
    df = smart_read_csv(path)
    if "timestamp" in df.columns:
        df = df.sort_values("timestamp")
    elif "time" in df.columns:
        df = df.sort_values("time")
    return df


def suggest_thresholds(df: pd.DataFrame, adx_pct: float = 0.75, atr_pct: float = 0.9):
    close = _get_col(df, "Close", "CLOSE", "close")
    adx = calculate_adx(df, window=14).dropna()
    atr = calculate_atr(df, window=14).dropna()
    atr_pct_series = (atr / close) * 100

    adx_val = float(adx.quantile(adx_pct))
    strong_adx_val = float(adx.quantile(min(0.95, max(adx_pct + 0.15, 0.9))))
    compression_val = float(atr_pct_series.quantile(0.25))
    mean_reversion_val = float(atr_pct_series.quantile(0.60))
    atr_val = float(atr_pct_series.quantile(atr_pct))
    extreme_val = float(atr_pct_series.quantile(0.99))

    return {
        "adx_threshold": round(adx_val, 2),
        "strong_adx_threshold": round(max(strong_adx_val, adx_val + 0.01), 2),
        "atr_pct_threshold": round(atr_val, 3),
        "atr_pct_compression_max": round(compression_val, 3),
        "atr_pct_mean_reversion_min": round(max(mean_reversion_val, compression_val + 0.001), 3),
        "atr_pct_breakout_min": round(max(atr_val, mean_reversion_val + 0.001), 3),
        "atr_pct_extreme_min": round(max(extreme_val, atr_val + 0.001), 3),
        "confidence": {"base": 0.35, "max": 0.98},
        "notes": f"suggested adx threshold at {int(adx_pct*100)}th percentile, atr_pct at {int(atr_pct*100)}th percentile",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="data/april_BTC_1h.csv")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    df = _load_csv(args.csv)
    rec = suggest_thresholds(df)
    outp = Path(args.out) if args.out else resolve_regime_config_path()
    cfg = load_regime_config(path=outp)
    cfg.update(rec)
    outp, config_hash = atomic_write_regime_config(cfg, path=outp)
    print(f"Wrote suggested config to {outp}")
    print(json.dumps({"config_sha256": config_hash, **rec}, indent=2))


if __name__ == "__main__":
    main()
