"""
Simple Market Regime detector.

Outputs a JSON dict with keys: regime, confidence, adx, atr_pct

Usage (from repo root):
    python -m btc_scraper.market_regime --csv data/april_BTC_1h.csv --out logs/market_regime.json

This implementation uses pure pandas/numpy (no extra TA libs).
"""
from __future__ import annotations

import argparse
import json
from typing import Dict

import numpy as np
import pandas as pd
import os
from pathlib import Path


def _get_col(df: pd.DataFrame, *names):
    for n in names:
        if n in df.columns:
            return df[n]
        if n.lower() in df.columns:
            return df[n.lower()]
    raise KeyError(f"None of the columns {names} found in dataframe")


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=1).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


def calculate_atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high = _get_col(df, "High", "HIGH", "high")
    low = _get_col(df, "Low", "LOW", "low")
    close = _get_col(df, "Close", "CLOSE", "close")

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=window, min_periods=1).mean()
    return atr


def calculate_adx(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high = _get_col(df, "High", "HIGH", "high")
    low = _get_col(df, "Low", "LOW", "low")
    close = _get_col(df, "Close", "CLOSE", "close")

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.rolling(window=window, min_periods=1).mean()

    # smooth the DM by Wilder's moving average approximation (rolling mean works acceptably here)
    plus_dm_smooth = pd.Series(plus_dm).rolling(window=window, min_periods=1).mean()
    minus_dm_smooth = pd.Series(minus_dm).rolling(window=window, min_periods=1).mean()

    plus_di = 100 * (plus_dm_smooth / atr.replace(0, np.nan))
    minus_di = 100 * (minus_dm_smooth / atr.replace(0, np.nan))

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    adx = dx.rolling(window=window, min_periods=1).mean()
    return adx


_REGIME_CONFIG_CACHE = None

def _load_config() -> dict:
    global _REGIME_CONFIG_CACHE
    if _REGIME_CONFIG_CACHE is not None:
        return _REGIME_CONFIG_CACHE

    defaults = {
        "adx_threshold": 25.0,
        "atr_pct_threshold": 4.0,
        "confidence": {
            "base": 0.2,
            "adx_weight": 0.5,
            "trend_weight": 0.3,
            "max": 0.98,
        },
    }
    cfg_path = Path(__file__).parent / "regime_config.json"
    if not cfg_path.exists():
        cfg_path = Path(__file__).with_name("regime_config.json")
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                user = json.load(f)
            # merge shallowly
            defaults.update({k: user.get(k, v) for k, v in defaults.items()})
        except Exception:
            pass
    _REGIME_CONFIG_CACHE = defaults
    return _REGIME_CONFIG_CACHE


def detect_regime(df: pd.DataFrame) -> Dict:
    close = _get_col(df, "Close", "CLOSE", "close")

    sma200 = sma(close, 200)
    sma50 = sma(close, 50)
    ema21 = ema(close, 21)

    atr = calculate_atr(df, window=14)
    atr_pct = (atr / close) * 100

    adx = calculate_adx(df, window=14)

    latest_close = float(close.iloc[-1])
    latest_sma200 = float(sma200.iloc[-1])
    latest_sma50 = float(sma50.iloc[-1])
    latest_ema21 = float(ema21.iloc[-1])
    latest_adx = float(adx.iloc[-1]) if not np.isnan(adx.iloc[-1]) else 0.0
    latest_atr_pct = float(atr_pct.iloc[-1]) if not np.isnan(atr_pct.iloc[-1]) else 0.0

    cfg = _load_config()
    adx_thresh = float(cfg.get("adx_threshold", 25.0))
    atr_thresh = float(cfg.get("atr_pct_threshold", 4.0))
    conf_cfg = cfg.get("confidence", {})

    # High volatility override
    if latest_atr_pct > atr_thresh:
        regime = "HIGH_VOLATILITY"
        # confidence rises with atr_pct above threshold
        confidence = min(conf_cfg.get("max", 0.98), 0.5 + (latest_atr_pct - atr_thresh) / (atr_thresh * 2 + 1e-9))
    else:
        # determine regime using ADX and trend alignment
        if latest_adx > adx_thresh:
            if latest_close > latest_sma200 and latest_ema21 > latest_sma50:
                regime = "TRENDING_BULL"
            elif latest_close < latest_sma200 and latest_ema21 < latest_sma50:
                regime = "TRENDING_BEAR"
            else:
                regime = "RANGING"
        else:
            regime = "RANGING"

        # compute a refined confidence score combining ADX and trend alignment
        base = float(conf_cfg.get("base", 0.2))
        adx_weight = float(conf_cfg.get("adx_weight", 0.5))
        trend_weight = float(conf_cfg.get("trend_weight", 0.3))
        max_conf = float(conf_cfg.get("max", 0.98))

        # adx component: how much above threshold, normalized
        adx_component = max(0.0, (latest_adx - adx_thresh) / max(1.0, adx_thresh))
        # trend alignment boolean
        trend_align = 1.0 if ((regime == "TRENDING_BULL" and latest_ema21 > latest_sma50) or (regime == "TRENDING_BEAR" and latest_ema21 < latest_sma50)) else 0.0

        confidence = base + adx_weight * adx_component + trend_weight * trend_align
        confidence = float(min(max_conf, max(0.0, confidence)))

    result = {
        "regime": regime,
        "confidence": round(float(confidence), 3),
        "adx": round(float(latest_adx), 2),
        "atr_pct": round(float(latest_atr_pct), 3),
        "sma200": round(float(latest_sma200), 6),
        "ema21": round(float(latest_ema21), 6),
        "sma50": round(float(latest_sma50), 6),
    }

    return result


def regime_from_values(close: float, sma200: float, ema21: float, sma50: float, adx: float, atr_pct: float, cfg: Dict | None = None) -> Dict:
    """Determine regime and confidence from raw indicator values.

    Returns dict: {regime, confidence, adx, atr_pct}
    """
    if cfg is None:
        # reuse local config loader
        try:
            cfg = _load_config()
        except Exception:
            cfg = None

    adx_thresh = float(cfg.get("adx_threshold", 25.0)) if cfg else 25.0
    atr_thresh = float(cfg.get("atr_pct_threshold", 4.0)) if cfg else 4.0
    conf_cfg = cfg.get("confidence", {}) if cfg else {"base": 0.2, "adx_weight": 0.5, "trend_weight": 0.3, "max": 0.98}

    latest_adx = float(adx)
    latest_atr_pct = float(atr_pct)
    latest_close = float(close)
    latest_sma200 = float(sma200)
    latest_sma50 = float(sma50)
    latest_ema21 = float(ema21)

    # High volatility override
    if latest_atr_pct > atr_thresh:
        regime = "HIGH_VOLATILITY"
        confidence = min(conf_cfg.get("max", 0.98), 0.5 + (latest_atr_pct - atr_thresh) / (atr_thresh * 2 + 1e-9))
    else:
        if latest_adx > adx_thresh:
            if latest_close > latest_sma200 and latest_ema21 > latest_sma50:
                regime = "TRENDING_BULL"
            elif latest_close < latest_sma200 and latest_ema21 < latest_sma50:
                regime = "TRENDING_BEAR"
            else:
                regime = "RANGING"
        else:
            regime = "RANGING"

        # confidence
        base = float(conf_cfg.get("base", 0.2))
        adx_weight = float(conf_cfg.get("adx_weight", 0.5))
        trend_weight = float(conf_cfg.get("trend_weight", 0.3))
        max_conf = float(conf_cfg.get("max", 0.98))
        adx_component = max(0.0, (latest_adx - adx_thresh) / max(1.0, adx_thresh))
        trend_align = 1.0 if ((regime == "TRENDING_BULL" and latest_ema21 > latest_sma50) or (regime == "TRENDING_BEAR" and latest_ema21 < latest_sma50)) else 0.0
        confidence = base + adx_weight * adx_component + trend_weight * trend_align
        confidence = float(min(max_conf, max(0.0, confidence)))

    return {"regime": regime, "confidence": round(float(confidence), 3), "adx": round(float(latest_adx), 2), "atr_pct": round(float(latest_atr_pct), 3)}


def save_json(d: Dict, path: str):
    with open(path, "w") as f:
        json.dump(d, f, indent=2)


def _load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # require time sorting
    if "timestamp" in df.columns:
        df = df.sort_values("timestamp")
    elif "time" in df.columns:
        df = df.sort_values("time")
    return df


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="data/april_BTC_1h.csv", help="candles CSV path")
    p.add_argument("--out", default="logs/market_regime_latest.json", help="output json path")
    args = p.parse_args()

    df = _load_csv(args.csv)
    info = detect_regime(df)
    print(json.dumps(info, indent=2))
    save_json(info, args.out)


if __name__ == "__main__":
    main()
