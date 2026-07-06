"""FRED collector for macro series such as US10Y."""

from __future__ import annotations

import os
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from btc_scraper.collectors.collector_base import CollectorBase
import logging

_logger = logging.getLogger(__name__)

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


def _fetch_us10y_from_yahoo() -> Optional[float]:
    if requests is None:
        return None
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    url = "https://query2.finance.yahoo.com/v8/finance/chart/^TNX?interval=1d&range=2d"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        res_json = response.json()
        result_list = res_json.get("chart", {}).get("result", [])
        if result_list:
            meta = result_list[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            if price is not None:
                return float(price)
            quotes = result_list[0].get("indicators", {}).get("quote", [])
            if quotes and quotes[0].get("close"):
                closes = [c for c in quotes[0]["close"] if c is not None]
                if closes:
                    return float(closes[-1])
    except Exception as e:
        _logger.warning("FredCollector failed to fetch us10y from Yahoo fallback: %s", e)
    return None


def _fetch_json(url: str) -> Any:
    if requests is None:
        raise RuntimeError("requests is not installed")
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 404:
            _logger.warning("%s returned 404 Not Found", url)
            return None
        response.raise_for_status()
        return response.json()
    except Exception as e:
        _logger.warning("Failed to fetch %s: %s", url, e)
        return None


class FredCollector(CollectorBase):
    name = "fred"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        self.enabled = os.getenv("ENABLE_FRED", "true").strip().lower() == "true"

    def collect(self, force: bool = False) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "source": self.name,
            "status": "success",
            "reason": None,
            "timestamp": timestamp,
            "data": {"us10y": 0.0, "gold": 0.0},
            "us10y": 0.0,
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
            api_key = os.getenv("FRED_API_KEY", "demo")
            if api_key == "demo":
                _logger.info("FRED API key is default ('demo'). Using Yahoo Finance REST API fallback for us10y.")
                val = _fetch_us10y_from_yahoo()
                if val is not None:
                    payload["us10y"] = val
                    payload["data"]["us10y"] = val
                else:
                    raise RuntimeError("Yahoo fallback failed for us10y")
            else:
                url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key={api_key}&file_type=json"
                data = _fetch_json(url)
                if data is None:
                    _logger.warning("FRED API fetch failed. Trying Yahoo Finance REST API fallback.")
                    val = _fetch_us10y_from_yahoo()
                    if val is not None:
                        payload["us10y"] = val
                        payload["data"]["us10y"] = val
                    else:
                        raise RuntimeError("FRED API returned no data and Yahoo fallback failed")
                else:
                    observations = data.get("observations", []) if isinstance(data, dict) else []
                    if observations:
                        last_value = observations[-1].get("value", "0")
                        payload["us10y"] = float(last_value) if last_value not in {"", "None", None} else 0.0
                        payload["data"]["us10y"] = payload["us10y"]
                    else:
                        _logger.warning("FRED API returned empty observations. Trying Yahoo Finance fallback.")
                        val = _fetch_us10y_from_yahoo()
                        if val is not None:
                            payload["us10y"] = val
                            payload["data"]["us10y"] = val
                        else:
                            raise RuntimeError("FRED API observations empty and Yahoo fallback failed")
        except Exception as e:
            _logger.exception("FredCollector failed")
            payload = {
                "source": self.name,
                "status": "error",
                "reason": repr(e),
                "timestamp": timestamp,
                "data": None,
                "us10y": 0.0,
                "gold": 0.0,
            }

        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
