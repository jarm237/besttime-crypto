"""Deribit collector for options IV and skew."""
from __future__ import annotations
import os
from typing import Any, Dict, Optional
from btc_scraper.collectors.collector_base import CollectorBase
import logging
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


def _fetch_json(url: str) -> Any:
    if requests is None:
        raise RuntimeError("requests is not installed")
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


class DeribitCollector(CollectorBase):
    name = "deribit"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        self.enabled = os.getenv("ENABLE_DERIBIT", "true").strip().lower() == "true"

    def collect(self, force: bool = False) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "source": self.name,
            "status": "success",
            "reason": None,
            "timestamp": timestamp,
            "data": {"options_iv": 0.0, "iv_skew": 0.0},
            "options_iv": 0.0,
            "iv_skew": 0.0,
        }

        if not self.enabled:
            payload["status"] = "skipped"
            payload["reason"] = "disabled_by_env"
            payload["data"] = None
            if self.output_path is not None:
                self._write_json(payload, self.output_path)
            return payload

        try:
            data = _fetch_json("https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC")
            if isinstance(data, dict):
                result = data.get("result", [])
                if result:
                    entry = result[-1]
                    iv = entry.get("mark_iv", 0.0)
                    ask = entry.get("best_ask_iv", iv)
                    bid = entry.get("best_bid_iv", iv)
                    payload["options_iv"] = float(iv)
                    payload["iv_skew"] = round(float(ask - bid), 10)
                    payload["data"]["options_iv"] = payload["options_iv"]
                    payload["data"]["iv_skew"] = payload["iv_skew"]
        except Exception as e:
            _logger.exception("DeribitCollector failed")
            payload = {
                "source": self.name,
                "status": "error",
                "reason": repr(e),
                "timestamp": timestamp,
                "data": None,
                "options_iv": 0.0,
                "iv_skew": 0.0,
            }
        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
