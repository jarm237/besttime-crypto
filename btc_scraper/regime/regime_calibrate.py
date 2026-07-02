"""
Calibration helper for market regime thresholds.

Scans a CSV of historical candles, computes ADX and ATR% distributions,
and writes a suggested `regime_config.json` next to the detector.

Usage:
    python3 -m btc_scraper.regime_calibrate --csv data/april_BTC_1h.csv

This produces `btc_scraper/regime_config.json` with recommended `adx_threshold`
and `atr_pct_threshold` (percentile-based suggestions) and simple confidence weights.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from btc_scraper.core.io import smart_read_csv

from btc_scraper.regime.market_regime import calculate_adx, calculate_atr, _get_col


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
    atr_val = float(atr_pct_series.quantile(atr_pct))

    return {
        "adx_threshold": round(adx_val, 2),
        "atr_pct_threshold": round(atr_val, 3),
        "confidence": {"base": 0.2, "adx_weight": 0.5, "trend_weight": 0.3, "max": 0.98},
        "notes": f"suggested adx threshold at {int(adx_pct*100)}th percentile, atr_pct at {int(atr_pct*100)}th percentile",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="data/april_BTC_1h.csv")
    p.add_argument("--out", default="btc_scraper/regime_config.json")
    args = p.parse_args()

    df = _load_csv(args.csv)
    rec = suggest_thresholds(df)
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    with open(outp, "w") as f:
        json.dump(rec, f, indent=2)
    print(f"Wrote suggested config to {outp}")
    print(json.dumps(rec, indent=2))


if __name__ == "__main__":
    main()
