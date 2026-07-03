"""Binance collector for funding rate and open interest."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from btc_scraper.collectors.collector_base import CollectorBase
import logging

_logger = logging.getLogger(__name__)

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


def _fetch_json(url: str) -> Any:
    if requests is None:
        raise RuntimeError("requests is not installed")
    try:
        response = requests.get(url, timeout=10)
        # Some Binance endpoints may be removed/renamed and return 404.
        # Treat 404 as a non-fatal condition and return None so callers
        # can attempt fallbacks instead of raising an exception.
        if response.status_code == 404:
            _logger.warning("%s returned 404 Not Found", url)
            return None
        response.raise_for_status()
        return response.json()
    except Exception:
        # Bubble up for non-HTTP errors; caller will handle logging.
        raise


class BinanceCollector(CollectorBase):
    name = "binance"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        self.enabled = os.getenv("ENABLE_BINANCE", "true").strip().lower() == "true"

    def collect(self, force: bool = False) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "source": self.name,
            "status": "success",
            "reason": None,
            "timestamp": timestamp,
            "data": {"funding_rate": 0.0, "open_interest": 0.0},
            "funding_rate": 0.0,
            "open_interest": 0.0,
        }

        if not self.enabled:
            payload["status"] = "skipped"
            payload["reason"] = "disabled_by_env"
            payload["data"] = None
            if self.output_path is not None:
                self._write_json(payload, self.output_path)
            return payload

        try:
            # Prefer the stable REST endpoints for funding rate and open interest
            # Funding endpoint moved to /fapi/v1/fundingRate (use symbol if needed)
            try:
                funding_data = _fetch_json("https://fapi.binance.com/fapi/v1/fundingRate?limit=1")
            except Exception:
                # fallback to symbol-specific query if the generic one fails
                funding_data = _fetch_json("https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1")

            # Open interest history endpoint — prefer `symbol=` parameter.
            # Some Binance deployments expect `symbol` while older examples
            # used `pair`. Try `symbol` first and fall back to `pair`.
            oi_data = None
            try:
                oi_data = _fetch_json("https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=5m&limit=1")
            except Exception:
                try:
                    oi_data = _fetch_json("https://fapi.binance.com/futures/data/openInterestHist?pair=BTCUSDT&period=5m&limit=1")
                except Exception:
                    oi_data = None
            if isinstance(funding_data, list) and funding_data:
                funding_rate = None
                for item in funding_data:
                    if isinstance(item, dict):
                        funding_rate = item.get("fundingRate")
                        if funding_rate is not None:
                            break
                if funding_rate is not None:
                    payload["funding_rate"] = float(funding_rate)
                    payload["data"]["funding_rate"] = float(funding_rate)
            if isinstance(oi_data, list) and oi_data:
                open_interest = None
                for item in oi_data:
                    if isinstance(item, dict):
                        open_interest = item.get("openInterest")
                        if open_interest is not None:
                            break
                if open_interest is not None:
                    payload["open_interest"] = float(open_interest)
                    payload["data"]["open_interest"] = float(open_interest)
        except Exception as e:
            _logger.exception("BinanceCollector failed")
            payload = {
                "source": self.name,
                "status": "error",
                "reason": repr(e),
                "timestamp": timestamp,
                "data": None,
                "funding_rate": 0.0,
                "open_interest": 0.0,
            }

        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
