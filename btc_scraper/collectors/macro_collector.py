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

DATA_FILE = str(build_data_path("macro_state.json"))

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
    result: Dict[str, float | str] = {}

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
            _logger.warning("[macro_collector] all fetch methods failed for %s — using default", name)
            result[name] = {"DXY": 100.0, "VIX": 20.0, "BondYield": 4.5}.get(name, 0.0)

    result.setdefault("DXY", 100.0)
    result.setdefault("VIX", 20.0)
    result.setdefault("BondYield", 4.5)
    result["timestamp"] = dt.datetime.now(dt.timezone.utc).isoformat()
    _write_macro_state(result)
    return result


def load_macro_state() -> Dict[str, float | str]:
    """Load macro data from disk if present; otherwise return safe defaults."""
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            if isinstance(data, dict):
                return data
    except Exception as _load_err:
        import logging as _log
        _log.getLogger(__name__).warning("[macro_collector] load_macro_state failed: %s — using defaults", _load_err)

    return {"DXY": 100.0, "VIX": 20.0, "BondYield": 4.5}


def is_macro_state_fresh(path: str | os.PathLike[str] | None = None, max_age_seconds: int = 3600) -> bool:
    """Return True when the macro state file exists and was updated recently."""
    target = Path(path or DATA_FILE)
    if not target.exists():
        return False

    try:
        age_seconds = time.time() - target.stat().st_mtime
    except OSError:
        return False
    return age_seconds <= max_age_seconds


def _write_macro_state(payload: Dict[str, float | str]) -> None:
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
