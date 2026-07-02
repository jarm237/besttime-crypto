"""Yahoo Finance collector for DXY, VIX, and Gold."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from btc_scraper.collectors.collector_base import CollectorBase

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None


def _fetch_history(ticker: str, period: str = "2d") -> Any:
    if yf is None:
        raise RuntimeError("yfinance is not installed")
    hist = yf.Ticker(ticker).history(period=period)
    if hist is None or hist.empty:
        raise RuntimeError("No history returned")
    return hist


class YahooCollector(CollectorBase):
    name = "yahoo"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)

    def collect(self, force: bool = False) -> Dict[str, Any]:
        payload = {"dxy": 0.0, "vix": 0.0, "gold": 0.0}
        try:
            series = {
                "DXY": "DX-Y.NYB",
                "VIX": "^VIX",
                "Gold": "GC=F",
            }
            for key, ticker in series.items():
                hist = None
                for candidate in (ticker, key, key.lower(), key.upper()):
                    try:
                        hist = _fetch_history(candidate, period="2d")
                        break
                    except Exception:
                        continue
                if hist is None:
                    continue

                closes = None
                if isinstance(hist, dict):
                    closes = hist.get("Close")
                    if closes is None and key.lower() in hist:
                        nested = hist.get(key.lower())
                        if isinstance(nested, dict):
                            closes = nested.get("Close")
                elif hasattr(hist, "get"):
                    closes = hist.get("Close")

                if closes is None:
                    continue
                if hasattr(closes, "iloc") and len(closes) > 0:
                    payload[key.lower()] = float(closes.iloc[-1])
                elif isinstance(closes, list) and closes:
                    payload[key.lower()] = float(closes[-1])
                elif isinstance(closes, (int, float)):
                    payload[key.lower()] = float(closes)
        except Exception:
            payload = {"dxy": 0.0, "vix": 0.0, "gold": 0.0}

        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
