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


def _classify_regime(close: float, sma200: float, ema21: float, sma50: float, adx: float, atr_pct: float, cfg: Dict) -> Dict[str, object]:
    close = float(close)
    sma200 = float(sma200)
    ema21 = float(ema21)
    sma50 = float(sma50)
    adx = float(adx)
    atr_pct = float(atr_pct)

    adx_thresh = float(cfg.get("adx_threshold", 25.0))
    strong_adx = float(cfg.get("strong_adx_threshold", 35.0))
    compression_ratio = float(cfg.get("compression_atr_ratio", 0.75))
    mean_reversion_ratio = float(cfg.get("mean_reversion_atr_ratio", 1.25))
    breakout_ratio = float(cfg.get("breakout_atr_ratio", 1.5))
    pump_risk_ratio = float(cfg.get("pump_risk_atr_ratio", 2.0))
    panic_sell_ratio = float(cfg.get("panic_sell_atr_ratio", 2.0))

    regime = "RANGING"
    confidence = float(cfg.get("confidence", {}).get("base", 0.2))

    if atr_pct >= panic_sell_ratio * adx_thresh and close < sma200 and adx >= adx_thresh:
        regime = "PANIC_SELL"
        confidence = 0.85
    elif atr_pct >= pump_risk_ratio * adx_thresh and close > sma200 and adx < adx_thresh:
        regime = "PUMP_RISK"
        confidence = 0.65
    elif atr_pct <= compression_ratio * adx_thresh and adx < 20:
        regime = "COMPRESSION"
        confidence = 0.45
    elif atr_pct >= breakout_ratio * adx_thresh and adx >= adx_thresh and close > sma200 and ema21 > sma50:
        regime = "BREAKOUT"
        confidence = 0.75
    elif atr_pct >= mean_reversion_ratio * adx_thresh and adx < adx_thresh:
        regime = "MEAN_REVERSION"
        confidence = 0.55
    elif adx >= strong_adx:
        if close > sma200 and ema21 > sma50:
            regime = "STRONG_TREND_BULL"
        elif close < sma200 and ema21 < sma50:
            regime = "STRONG_TREND_BEAR"
        else:
            regime = "STRONG_TREND"
        confidence = 0.9
    elif adx > adx_thresh:
        if close > sma200 and ema21 > sma50:
            regime = "WEAK_TREND_BULL"
        elif close < sma200 and ema21 < sma50:
            regime = "WEAK_TREND_BEAR"
        else:
            regime = "WEAK_TREND"
        confidence = 0.7
    elif atr_pct > adx_thresh:
        regime = "HIGH_VOLATILITY"
        confidence = 0.6
    else:
        regime = "RANGING"
        confidence = 0.4

    return {"regime": regime, "confidence": round(float(confidence), 3)}


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
    regime_info = _classify_regime(latest_close, latest_sma200, latest_ema21, latest_sma50, latest_adx, latest_atr_pct, cfg)
    regime = regime_info["regime"]
    confidence = regime_info["confidence"]

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
        try:
            cfg = _load_config()
        except Exception:
            cfg = {}

    if cfg is None:
        cfg = {}

    regime_info = _classify_regime(close, sma200, ema21, sma50, adx, atr_pct, cfg)
    latest_adx = float(adx)
    latest_atr_pct = float(atr_pct)
    return {
        "regime": regime_info["regime"],
        "confidence": regime_info["confidence"],
        "adx": round(float(latest_adx), 2),
        "atr_pct": round(float(latest_atr_pct), 3),
    }


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
