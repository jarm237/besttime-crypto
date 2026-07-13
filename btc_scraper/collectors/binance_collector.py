"""Binance collector for public futures market data."""

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


def _positive_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _orderbook_imbalance(data: Any) -> Optional[float]:
    """Return (bid volume - ask volume) / total volume for a depth snapshot."""
    if not isinstance(data, dict):
        return None
    try:
        bid_volume = sum(float(level[1]) for level in data.get("bids", []) if len(level) >= 2)
        ask_volume = sum(float(level[1]) for level in data.get("asks", []) if len(level) >= 2)
    except (TypeError, ValueError):
        return None
    total = bid_volume + ask_volume
    return (bid_volume - ask_volume) / total if total > 0 else None


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
            "data": {"funding_rate": None, "open_interest": None, "orderbook_imbalance": None},
            "funding_rate": None,
            "open_interest": None,
            "orderbook_imbalance": None,
            "field_statuses": {},
        }

        if not self.enabled:
            payload["status"] = "skipped"
            payload["reason"] = "disabled_by_env"
            payload["data"] = None
            if self.output_path is not None:
                self._write_json(payload, self.output_path)
            return payload

        try:
            funding_data = _fetch_json(
                "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1"
            )

            # Current OI is a dict with an ``openInterest`` string. Do not
            # use the historical endpoint here: its schema and units differ.
            oi_data = _fetch_json("https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT")
            depth_data = _fetch_json("https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=100")
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
            open_interest = oi_data.get("openInterest") if isinstance(oi_data, dict) else None
            # Retain list support for recorded fixtures from the old endpoint.
            if open_interest is None and isinstance(oi_data, list):
                for item in oi_data:
                    if isinstance(item, dict):
                        open_interest = item.get("openInterest")
                        if open_interest is not None:
                            break
            parsed_oi = _positive_float(open_interest)
            if parsed_oi is not None:
                payload["open_interest"] = parsed_oi
                payload["data"]["open_interest"] = parsed_oi
                payload["raw_open_interest"] = open_interest
            else:
                payload["field_statuses"]["open_interest"] = {
                    "status": "invalid", "reason": "zero_or_missing_open_interest"
                }

            imbalance = _orderbook_imbalance(depth_data)
            if imbalance is not None:
                payload["orderbook_imbalance"] = imbalance
                payload["data"]["orderbook_imbalance"] = imbalance
                payload["orderbook_sample_count"] = len(depth_data.get("bids", [])) + len(depth_data.get("asks", []))
            else:
                payload["field_statuses"]["orderbook_imbalance"] = {
                    "status": "missing", "reason": "missing_or_empty_depth"
                }
        except Exception as e:
            _logger.exception("BinanceCollector failed")
            payload = {
                "source": self.name,
                "status": "error",
                "reason": repr(e),
                "timestamp": timestamp,
                "data": None,
                "funding_rate": None,
                "open_interest": None,
                "orderbook_imbalance": None,
                "field_statuses": {
                    "funding_rate": {"status": "error", "reason": repr(e)},
                    "open_interest": {"status": "error", "reason": repr(e)},
                    "orderbook_imbalance": {"status": "error", "reason": repr(e)},
                },
            }

        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
