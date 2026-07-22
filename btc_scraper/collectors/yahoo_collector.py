"""Yahoo Finance collector for DXY, VIX, and Gold."""

from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from btc_scraper.collectors.collector_base import CollectorBase

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


def _latest_close(hist: Any) -> float:
    """Extract and validate the most recent close from a Yahoo history payload."""
    closes = hist.get("Close") if hasattr(hist, "get") else None
    if closes is None:
        raise ValueError("history payload has no Close series")

    if hasattr(closes, "iloc"):
        if len(closes) == 0:
            raise ValueError("Close series is empty")
        value = closes.iloc[-1]
    elif isinstance(closes, (list, tuple)):
        values = [value for value in closes if value is not None]
        if not values:
            raise ValueError("Close series is empty")
        value = values[-1]
    elif isinstance(closes, (int, float)):
        value = closes
    else:
        raise ValueError("unsupported Close series type")

    close = float(value)
    if not math.isfinite(close) or close <= 0:
        raise ValueError(f"invalid close value: {close!r}")
    return close


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
            "data": {"dxy": None, "vix": None, "gold": None},
            "dxy": None,
            "vix": None,
            "gold": None,
        }

        if not self.enabled:
            payload["status"] = "skipped"
            payload["reason"] = "disabled_by_env"
            payload["data"] = None
            if self.output_path is not None:
                self._write_json(payload, self.output_path)
            return payload

        series = {
            "dxy": "DX-Y.NYB",
            "vix": "^VIX",
            "gold": "GC=F",
        }
        failures = []
        for key, ticker in series.items():
            last_error: Optional[Exception] = None
            for attempt in range(self.retries + 1):
                try:
                    value = _latest_close(_fetch_history(ticker, period="2d"))
                    payload[key] = value
                    payload["data"][key] = value
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < self.retries:
                        time.sleep(self.delay_seconds * (2 ** attempt))
            else:
                failures.append(f"{key} ({ticker}): {last_error}")

        if failures:
            payload["status"] = "error"
            payload["reason"] = "failed_series: " + "; ".join(failures)
            _logger.error("YahooCollector failed to collect required series: %s", payload["reason"])

        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
