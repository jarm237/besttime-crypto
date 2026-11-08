"""Macro data collector for causal world-model runtime integration."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional

try:
    import yfinance as yf
except Exception:  # pragma: no cover - optional dependency
    yf = None

from btc_scraper.core.paths import build_data_path

_logger = logging.getLogger(__name__)

def _macro_data_file() -> Path:
    return build_data_path("macro_state.json")


MACRO_TICKERS = {
    "DXY": "DX-Y.NYB",
    "VIX": "^VIX",
    "BondYield": "^TNX",
}


def _fetch_ticker_rest(ticker: str) -> Optional[float]:
    try:
        import requests
    except ImportError:
        return None
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        res_json = response.json()
        result_list = res_json.get("chart", {}).get("result", [])
        if result_list:
            meta = result_list[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            if price is None:
                quotes = result_list[0].get("indicators", {}).get("quote", [])
                if quotes and quotes[0].get("close"):
                    closes = [c for c in quotes[0]["close"] if c is not None]
                    if closes:
                        price = closes[-1]
            if price is not None:
                return float(price)
    except Exception:
        pass
    return None


def fetch_and_save_macro() -> Dict[str, float | str]:
    """Fetch macro market data from yfinance (or REST fallback) and persist it to disk."""
    mode = os.getenv("ALTERNATIVE_DATA_STARTUP_MODE", "").lower()
    data_file = _macro_data_file()
    max_age = int(os.getenv("MACRO_MAX_AGE_SECONDS", "3600"))

    if mode == "cache":
        if data_file.exists():
            if is_macro_state_fresh(data_file, max_age_seconds=max_age):
                existing = load_macro_state()
                if existing and existing.get("timestamp"):
                    existing.setdefault("stale", False)
                    return existing
            else:
                # File exists but exceeds TTL — degrade explicitly
                existing = load_macro_state()
                if existing:
                    existing["stale"] = True
                    return existing

        result = {
            "DXY": 100.0,
            "VIX": 20.0,
            "BondYield": 4.5,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "stale": True,
        }
        _write_macro_state(result)
        return result

    result: Dict[str, float | str] = {}
    had_fetch_failure = False
    for name, ticker in MACRO_TICKERS.items():
        if yf is not None:
            try:
                hist = yf.Ticker(ticker).history(period="2d")
                if hist is not None and not hist.empty:
                    result[name] = float(hist["Close"].iloc[-1])
                    continue
            except Exception as exc:
                _logger.warning(
                    "[macro_collector] yfinance fetch failed for %s: %s — trying REST fallback",
                    name,
                    exc,
                )

        val = _fetch_ticker_rest(ticker)
        if val is not None:
            result[name] = val
        else:
            had_fetch_failure = True
            _logger.warning("[macro_collector] all fetch methods failed for %s — using default", name)
            result[name] = {"DXY": 100.0, "VIX": 20.0, "BondYield": 4.5}.get(name, 0.0)

    result.setdefault("DXY", 100.0)
    result.setdefault("VIX", 20.0)
    result.setdefault("BondYield", 4.5)
    result["timestamp"] = dt.datetime.now(dt.timezone.utc).isoformat()
    result["stale"] = had_fetch_failure
    _write_macro_state(result)
    return result


def load_macro_state() -> Dict[str, float | str]:
    """Load macro data from disk if present; otherwise return safe defaults."""
    data_file = _macro_data_file()
    try:
        if data_file.exists():
            with open(data_file, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict):
                    return data
    except Exception as _load_err:
        import logging as _log
        _log.getLogger(__name__).warning("[macro_collector] load_macro_state failed: %s — using defaults", _load_err)

    return {"DXY": 100.0, "VIX": 20.0, "BondYield": 4.5, "stale": True}


def is_macro_state_fresh(
    path: str | os.PathLike[str] | None = None,
    max_age_seconds: int = 3600,
    max_future_skew_seconds: float = 60.0,
    now: Optional[float] = None,
) -> bool:
    """
    Return True when the macro state file exists and its content timestamp (or file mtime fallback)
    is fresh and not skewed into the future.
    """
    target = Path(path) if path is not None else _macro_data_file()
    if not target.exists():
        return False

    ref_time = now if now is not None else time.time()

    # Parse payload timestamp first
    ts = None
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict) and data.get("timestamp"):
                iso_ts = str(data["timestamp"])
                dt_val = dt.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
                ts = dt_val.timestamp()
    except Exception:
        ts = None

    try:
        mtime = target.stat().st_mtime
    except OSError:
        return False

    # Check payload timestamp if present
    if ts is not None:
        if (ref_time - ts) > max_age_seconds:
            return False
        if (ts - ref_time) > max_future_skew_seconds:
            return False

    # Also check filesystem mtime
    if (ref_time - mtime) > max_age_seconds:
        return False
    if (mtime - ref_time) > max_future_skew_seconds:
        return False

    return True


def _write_macro_state(payload: Dict[str, float | str]) -> None:
    data_file = _macro_data_file()
    os.makedirs(data_file.parent, exist_ok=True)
    with open(data_file, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
