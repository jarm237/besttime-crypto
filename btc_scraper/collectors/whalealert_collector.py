"""Whale Alert collector for whale score."""
from __future__ import annotations
import os
from datetime import datetime, timezone
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
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


class WhaleAlertCollector(CollectorBase):
    name = "whale_alert"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        self.enabled = os.getenv("ENABLE_WHALE_ALERT", "false").strip().lower() == "true"
        self.api_key = os.getenv("WHALE_ALERT_API_KEY", "").strip()

    def collect(self, force: bool = False) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        if not self.enabled:
            result = {
                "source": self.name,
                "status": "skipped",
                "reason": "disabled_free_plan_not_supported",
                "timestamp": timestamp,
                "data": None,
            }
            if self.output_path is not None:
                self._write_json(result, self.output_path)
            return result

        if not self.api_key:
            result = {
                "source": self.name,
                "status": "skipped",
                "reason": "missing_or_disabled_api_key",
                "timestamp": timestamp,
                "data": None,
            }
            if self.output_path is not None:
                self._write_json(result, self.output_path)
            return result

        try:
            data = _fetch_json(f"https://api.whale-alert.io/v1/transactions?limit=1&api_key={self.api_key}")
            if isinstance(data, dict):
                records = data.get("data", [])
                if records:
                    amount = records[-1].get("amount_usd", 0.0)
                    whale_score = min(100.0, max(0.0, float(amount) / 1_000_000.0))
                    result = {
                        "source": self.name,
                        "status": "success",
                        "reason": None,
                        "timestamp": timestamp,
                        "data": {"whale_score": whale_score},
                        "whale_score": whale_score,
                    }
                    if self.output_path is not None:
                        self._write_json(result, self.output_path)
                    return result
        except Exception as e:
            _logger.exception("WhaleAlertCollector failed")
            result = {
                "source": self.name,
                "status": "error",
                "reason": repr(e),
                "timestamp": timestamp,
                "data": None,
            }
            if self.output_path is not None:
                self._write_json(result, self.output_path)
            return result

        result = {
            "source": self.name,
            "status": "error",
            "reason": "invalid_response",
            "timestamp": timestamp,
            "data": None,
        }
        if self.output_path is not None:
            self._write_json(result, self.output_path)
        return result
