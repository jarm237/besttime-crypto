"""Yahoo Finance collector for DXY, VIX, and Gold."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from btc_scraper.collectors.collector_base import CollectorBase
import logging

_logger = logging.getLogger(__name__)

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None


def _fetch_history_rest(ticker: str) -> Optional[Dict[str, Any]]:
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
                return {"Close": [float(price)]}
    except Exception as e:
        _logger.warning("YahooCollector REST fallback failed for %s: %s", ticker, e)
    return None


def _fetch_history(ticker: str, period: str = "2d") -> Any:
    if yf is not None:
        try:
            hist = yf.Ticker(ticker).history(period=period)
            if hist is not None and not hist.empty:
                return hist
        except Exception as e:
            _logger.warning("yfinance fetch failed for %s, trying REST fallback: %s", ticker, e)

    rest_res = _fetch_history_rest(ticker)
    if rest_res is not None:
        return rest_res

    raise RuntimeError(f"Failed to fetch history for {ticker} (yfinance missing or failed, and REST fallback failed)")


class YahooCollector(CollectorBase):
    name = "yahoo"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        self.enabled = os.getenv("ENABLE_YAHOO_FINANCE", "true").strip().lower() == "true"

    def collect(self, force: bool = False) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "source": self.name,
            "status": "success",
            "reason": None,
            "timestamp": timestamp,
            "data": {"dxy": 0.0, "vix": 0.0, "gold": 0.0},
            "dxy": 0.0,
            "vix": 0.0,
            "gold": 0.0,
        }

        if not self.enabled:
            payload["status"] = "skipped"
            payload["reason"] = "disabled_by_env"
            payload["data"] = None
            if self.output_path is not None:
                self._write_json(payload, self.output_path)
            return payload

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
                payload["data"][key.lower()] = payload[key.lower()]
        except Exception as e:
            _logger.exception("YahooCollector failed")
            payload = {
                "source": self.name,
                "status": "error",
                "reason": repr(e),
                "timestamp": timestamp,
                "data": None,
                "dxy": 0.0,
                "vix": 0.0,
                "gold": 0.0,
            }

        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
