"""Macro data collector for causal world-model runtime integration."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Dict, Optional

try:
    import yfinance as yf
except Exception:  # pragma: no cover - optional dependency
    yf = None

from btc_scraper.core.paths import build_data_path

DATA_FILE = str(build_data_path("macro_state.json"))

MACRO_TICKERS = {
    "DXY": "DX-Y.NYB",
    "VIX": "^VIX",
    "BondYield": "^TNX",
}


def fetch_and_save_macro() -> Dict[str, float | str]:
    """Fetch macro market data from yfinance and persist it to disk."""
    result: Dict[str, float | str] = {}

    if yf is None:
        result.update({"DXY": 100.0, "VIX": 20.0, "BondYield": 4.5})
        result["timestamp"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _write_macro_state(result)
        return result

    for name, ticker in MACRO_TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period="2d")
            if hist is not None and not hist.empty:
                result[name] = float(hist["Close"].iloc[-1])
        except Exception:
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
    except Exception:
        pass

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
