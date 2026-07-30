"""
Simple Market Regime detector.

Outputs a backward-compatible JSON dict plus a canonical ``regime_snapshot``.

Usage (from repo root):
    python -m btc_scraper.regime.market_regime --csv data/april_BTC_1h.csv --out logs/market_regime.json

This implementation uses pure pandas/numpy (no extra TA libs).
"""
from __future__ import annotations

import argparse
import json
import math
from typing import Dict

import numpy as np
import pandas as pd
from btc_scraper.core.io import smart_read_csv
from pathlib import Path

from .config import compute_regime_config_sha256, load_runtime_regime_config
from .contract import snapshot_from_legacy

SUPPORTED_TIMEFRAMES = {
    "unknown", "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h",
    "6h", "8h", "12h", "1d",
}


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

    # Preserve the caller's index. A fresh RangeIndex here makes pandas align
    # disjoint labels against a DatetimeIndex and silently produces all-NaN ADX.
    plus_dm_smooth = pd.Series(plus_dm, index=df.index).rolling(window=window, min_periods=1).mean()
    minus_dm_smooth = pd.Series(minus_dm, index=df.index).rolling(window=window, min_periods=1).mean()

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
    _REGIME_CONFIG_CACHE = load_runtime_regime_config()
    return _REGIME_CONFIG_CACHE


def reset_regime_config_cache() -> None:
    global _REGIME_CONFIG_CACHE
    _REGIME_CONFIG_CACHE = None


def _threshold_confidence(value: float, threshold: float, cfg: Dict, *, base: float | None = None) -> float:
    conf_cfg = cfg.get("confidence", {})
    floor = float(base if base is not None else conf_cfg.get("base", 0.35))
    cap = float(conf_cfg.get("max", 0.98))
    distance = abs(float(value) - float(threshold)) / max(abs(float(threshold)), 1e-9)
    return round(min(cap, floor + 0.5 * min(distance, 1.0)), 3)


def _classify_regime(close: float, sma200: float, ema21: float, sma50: float, adx: float, atr_pct: float, cfg: Dict) -> Dict[str, object]:
    close = float(close)
    sma200 = float(sma200)
    ema21 = float(ema21)
    sma50 = float(sma50)
    adx = float(adx)
    atr_pct = float(atr_pct)

    values = (close, sma200, ema21, sma50, adx, atr_pct)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Regime inputs must be finite")
    if close <= 0 or sma200 <= 0 or ema21 <= 0 or sma50 <= 0:
        raise ValueError("Regime price inputs must be > 0")
    if adx < 0 or atr_pct < 0:
        raise ValueError("ADX and ATR percent must be >= 0")

    adx_thresh = float(cfg.get("adx_threshold", 25.0))
    strong_adx = float(cfg.get("strong_adx_threshold", 35.0))
    atr_reference = float(cfg.get("atr_pct_threshold", 0.65))
    compression_max = float(cfg.get("atr_pct_compression_max", atr_reference * 0.75))
    mean_reversion_min = float(cfg.get("atr_pct_mean_reversion_min", atr_reference))
    breakout_min = float(cfg.get("atr_pct_breakout_min", atr_reference * 1.5))
    extreme_min = float(cfg.get("atr_pct_extreme_min", atr_reference * 2.0))

    bull_aligned = close > sma200 and ema21 > sma50
    bear_aligned = close < sma200 and ema21 < sma50

    if atr_pct >= extreme_min and bear_aligned and adx >= adx_thresh:
        regime = "PANIC_SELL"
        confidence = _threshold_confidence(atr_pct, extreme_min, cfg, base=0.7)
    elif atr_pct >= extreme_min and bull_aligned:
        regime = "PUMP_RISK"
        confidence = _threshold_confidence(atr_pct, extreme_min, cfg, base=0.65)
    elif atr_pct <= compression_max and adx < 20:
        regime = "COMPRESSION"
        confidence = _threshold_confidence(atr_pct, compression_max, cfg)
    elif atr_pct >= breakout_min and adx >= adx_thresh and bull_aligned:
        regime = "BREAKOUT_BULL"
        confidence = _threshold_confidence(atr_pct, breakout_min, cfg, base=0.6)
    elif atr_pct >= breakout_min and adx >= adx_thresh and bear_aligned:
        regime = "BREAKOUT_BEAR"
        confidence = _threshold_confidence(atr_pct, breakout_min, cfg, base=0.6)
    elif atr_pct >= mean_reversion_min and adx < adx_thresh:
        regime = "MEAN_REVERSION"
        confidence = _threshold_confidence(atr_pct, mean_reversion_min, cfg, base=0.5)
    elif adx >= strong_adx:
        if bull_aligned:
            regime = "STRONG_TREND_BULL"
        elif bear_aligned:
            regime = "STRONG_TREND_BEAR"
        else:
            regime = "STRONG_TREND"
        confidence = _threshold_confidence(adx, strong_adx, cfg, base=0.65)
    elif adx > adx_thresh:
        if bull_aligned:
            regime = "WEAK_TREND_BULL"
        elif bear_aligned:
            regime = "WEAK_TREND_BEAR"
        else:
            regime = "WEAK_TREND"
        confidence = _threshold_confidence(adx, adx_thresh, cfg, base=0.5)
    elif atr_pct >= breakout_min:
        regime = "HIGH_VOLATILITY"
        confidence = _threshold_confidence(atr_pct, breakout_min, cfg, base=0.5)
    else:
        regime = "RANGING"
        distance = min(abs(adx - adx_thresh) / adx_thresh, abs(atr_pct - compression_max) / compression_max)
        confidence = round(min(float(cfg.get("confidence", {}).get("max", 0.98)), 0.35 + 0.4 * distance), 3)

    return {
        "regime": regime,
        "confidence": round(float(confidence), 3),
        "confidence_method": "threshold_distance_v1",
    }


def _input_end_time(df: pd.DataFrame) -> str | None:
    for column in ("timestamp", "time", "entry_time"):
        if column in df.columns:
            parsed = pd.to_datetime(df[column].iloc[-1], utc=True, errors="coerce")
            return None if pd.isna(parsed) else parsed.isoformat()
    if isinstance(df.index, pd.DatetimeIndex):
        parsed = pd.to_datetime(df.index[-1], utc=True, errors="coerce")
        return None if pd.isna(parsed) else parsed.isoformat()
    return None


def stabilize_regime_sequence(candidates: list[str], minimum_duration_bars: int = 3) -> list[str]:
    """Confirm a new regime only after it persists for the configured duration."""
    if not candidates:
        return []
    minimum_duration = max(1, int(minimum_duration_bars))
    current = str(candidates[0])
    pending: str | None = None
    pending_count = 0
    stabilized = [current]
    for candidate_raw in candidates[1:]:
        candidate = str(candidate_raw)
        if candidate == current:
            pending = None
            pending_count = 0
        else:
            if candidate == pending:
                pending_count += 1
            else:
                pending = candidate
                pending_count = 1
            if pending_count >= minimum_duration:
                current = candidate
                pending = None
                pending_count = 0
        stabilized.append(current)
    return stabilized


def _validate_detector_input(df: pd.DataFrame, source_timeframe: str) -> None:
    if source_timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"UNSUPPORTED_TIMEFRAME: {source_timeframe}")
    close = _get_col(df, "Close", "CLOSE", "close")
    high = _get_col(df, "High", "HIGH", "high")
    low = _get_col(df, "Low", "LOW", "low")
    numeric = pd.DataFrame({"close": close, "high": high, "low": low}).apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("INVALID_OHLC_VALUES")
    if (numeric <= 0).any().any():
        raise ValueError("NON_POSITIVE_OHLC")
    if (numeric["high"] < numeric["low"]).any():
        raise ValueError("INVALID_HIGH_LOW")

    time_values: pd.Series | pd.DatetimeIndex | None = None
    for column in ("timestamp", "time", "entry_time"):
        if column in df.columns:
            parsed = pd.to_datetime(df[column], utc=True, errors="coerce")
            if parsed.isna().any():
                raise ValueError("INVALID_TIMESTAMP")
            time_values = parsed
            break
    if time_values is None and isinstance(df.index, pd.DatetimeIndex):
        time_values = df.index
    if time_values is not None:
        if time_values.duplicated().any():
            raise ValueError("DUPLICATED_TIMESTAMP")
        if not time_values.is_monotonic_increasing:
            raise ValueError("NON_MONOTONIC_TIME")


def _unknown_result(
    cfg: Dict,
    *,
    reason: str,
    observed_at: str | None,
    source_timeframe: str,
) -> Dict:
    config_hash = compute_regime_config_sha256(cfg)
    snapshot = snapshot_from_legacy(
        "UNKNOWN",
        confidence=0.0,
        observed_at=observed_at,
        input_end_time=observed_at,
        source_timeframe=source_timeframe,
        config_sha256=config_hash,
        detector_version=str(cfg["detector_version"]),
        taxonomy_version=str(cfg["taxonomy_version"]),
        warmup_complete=False,
        confidence_method="unavailable",
        reason=reason,
    )
    return {
        "regime": "UNKNOWN",
        "confidence": 0.0,
        "confidence_method": "unavailable",
        "warmup_complete": False,
        "reason": reason,
        "config_sha256": config_hash,
        "regime_snapshot": snapshot.to_dict(),
    }


def detect_regime(df: pd.DataFrame, *, source_timeframe: str = "unknown") -> Dict:
    cfg = _load_config()
    if df.empty:
        return _unknown_result(cfg, reason="INSUFFICIENT_HISTORY", observed_at=None, source_timeframe=source_timeframe)
    _validate_detector_input(df, source_timeframe)
    input_end_time = _input_end_time(df)
    minimum_bars = int(cfg.get("minimum_bars", 200))
    if len(df) < minimum_bars:
        return _unknown_result(
            cfg,
            reason="INSUFFICIENT_HISTORY",
            observed_at=input_end_time,
            source_timeframe=source_timeframe,
        )

    close = _get_col(df, "Close", "CLOSE", "close")
    high = _get_col(df, "High", "HIGH", "high")
    low = _get_col(df, "Low", "LOW", "low")
    tail = (close.iloc[-1], high.iloc[-1], low.iloc[-1])
    if not all(pd.notna(value) and math.isfinite(float(value)) and float(value) > 0 for value in tail):
        raise ValueError("INVALID_OHLC_TAIL")

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
    if pd.isna(adx.iloc[-1]) or pd.isna(atr_pct.iloc[-1]):
        raise ValueError("INVALID_INDICATOR_TAIL")
    latest_adx = float(adx.iloc[-1])
    latest_atr_pct = float(atr_pct.iloc[-1])
    if not 0.0 <= latest_adx <= 100.0:
        raise ValueError("INVALID_ADX_TAIL")
    if not 0.0 <= latest_atr_pct <= float(cfg.get("atr_pct_max_valid", 25.0)):
        raise ValueError("INVALID_ATR_PERCENT_TAIL")

    raw_infos = [
        _classify_regime(
            float(close.iloc[index]),
            float(sma200.iloc[index]),
            float(ema21.iloc[index]),
            float(sma50.iloc[index]),
            float(adx.iloc[index]),
            float(atr_pct.iloc[index]),
            cfg,
        )
        for index in range(minimum_bars - 1, len(df))
    ]
    stable_labels = stabilize_regime_sequence(
        [str(info["regime"]) for info in raw_infos],
        int(cfg.get("minimum_duration_bars", 3)),
    )
    regime_info = raw_infos[-1]
    raw_regime = str(regime_info["regime"])
    regime = stable_labels[-1]
    if regime != raw_regime:
        previous = next((item for item in reversed(raw_infos[:-1]) if item["regime"] == regime), None)
        confidence = round(float(previous["confidence"]) * 0.9, 3) if previous else 0.35
        confidence_method = "threshold_distance_v1_hysteresis_decay"
    else:
        confidence = regime_info["confidence"]
        confidence_method = str(regime_info["confidence_method"])

    config_hash = compute_regime_config_sha256(cfg)
    snapshot = snapshot_from_legacy(
        regime,
        confidence=confidence,
        observed_at=input_end_time,
        input_end_time=input_end_time,
        source_timeframe=source_timeframe,
        config_sha256=config_hash,
        detector_version=str(cfg["detector_version"]),
        taxonomy_version=str(cfg["taxonomy_version"]),
        confidence_method=confidence_method,
    )
    result = {
        "regime": regime,
        "confidence": round(float(confidence), 3),
        "confidence_method": confidence_method,
        "raw_regime": raw_regime,
        "hysteresis_applied": regime != raw_regime,
        "minimum_duration_bars": int(cfg.get("minimum_duration_bars", 3)),
        "adx": round(float(latest_adx), 2),
        "atr_pct": round(float(latest_atr_pct), 3),
        "atr_percent": round(float(latest_atr_pct), 3),
        "sma200": round(float(latest_sma200), 6),
        "ema21": round(float(latest_ema21), 6),
        "sma50": round(float(latest_sma50), 6),
        "warmup_complete": True,
        "config_sha256": config_hash,
        "regime_snapshot": snapshot.to_dict(),
    }

    return result


def regime_from_values(
    close: float,
    sma200: float,
    ema21: float,
    sma50: float,
    adx: float,
    atr_pct: float,
    cfg: Dict | None = None,
    *,
    observed_at: str | None = None,
    source_timeframe: str = "unknown",
    warmup_complete: bool = True,
) -> Dict:
    """Determine regime and confidence from raw indicator values.

    Returns dict: {regime, confidence, adx, atr_pct}
    """
    if cfg is None:
        cfg = _load_config()
    if not warmup_complete:
        return _unknown_result(
            cfg,
            reason="INSUFFICIENT_HISTORY",
            observed_at=observed_at,
            source_timeframe=source_timeframe,
        )
    raw_values = (close, sma200, ema21, sma50, adx, atr_pct)
    if not all(math.isfinite(float(value)) for value in raw_values):
        raise ValueError("Regime inputs must be finite")
    if float(close) <= 0:
        raise ValueError("Close price must be > 0")
    if any(float(value) <= 0 for value in (sma200, ema21, sma50)):
        return _unknown_result(
            cfg,
            reason="INSUFFICIENT_HISTORY",
            observed_at=observed_at,
            source_timeframe=source_timeframe,
        )

    regime_info = _classify_regime(close, sma200, ema21, sma50, adx, atr_pct, cfg)
    latest_adx = float(adx)
    latest_atr_pct = float(atr_pct)
    config_hash = compute_regime_config_sha256(cfg)
    snapshot = snapshot_from_legacy(
        regime_info["regime"],
        confidence=regime_info["confidence"],
        observed_at=observed_at,
        input_end_time=observed_at,
        source_timeframe=source_timeframe,
        config_sha256=config_hash,
        detector_version=str(cfg["detector_version"]),
        taxonomy_version=str(cfg["taxonomy_version"]),
        confidence_method=str(regime_info["confidence_method"]),
    )
    return {
        "regime": regime_info["regime"],
        "confidence": regime_info["confidence"],
        "confidence_method": regime_info["confidence_method"],
        "adx": round(float(latest_adx), 2),
        "atr_pct": round(float(latest_atr_pct), 3),
        "atr_percent": round(float(latest_atr_pct), 3),
        "warmup_complete": True,
        "config_sha256": config_hash,
        "regime_snapshot": snapshot.to_dict(),
    }


def save_json(d: Dict, path: str):
    with open(path, "w") as f:
        json.dump(d, f, indent=2)


def _load_csv(path: str) -> pd.DataFrame:
    df = smart_read_csv(path)
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
