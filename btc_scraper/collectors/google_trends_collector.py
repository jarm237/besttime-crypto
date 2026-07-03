"""Google Trends collector for search interest sentiment proxy."""
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


class GoogleTrendsCollector(CollectorBase):
    name = "google_trends"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        self.enabled = os.getenv("ENABLE_GOOGLE_TRENDS", "true").strip().lower() == "true"

    def collect(self, force: bool = False) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "source": self.name,
            "status": "success",
            "reason": None,
            "timestamp": timestamp,
            "data": {"sentiment_score": 0.0},
            "sentiment_score": 0.0,
        }

        if not self.enabled:
            payload["status"] = "skipped"
            payload["reason"] = "disabled_by_env"
            payload["data"] = None
            if self.output_path is not None:
                self._write_json(payload, self.output_path)
            return payload

        try:
            data = _fetch_json("https://trends.google.com/trends/api/widgetdata/multiline?hl=en-US&tz=0&tz=0&req={\"time\":\"now 7-d\",\"keyword\":\"bitcoin\",\"granularities\":\"daily\"}")
            if isinstance(data, dict):
                timeline = data.get("default", {}).get("timelineData", [])
                if timeline:
                    values = timeline[-1].get("value", [])
                    if values:
                        payload["sentiment_score"] = float(values[-1])
                        payload["data"]["sentiment_score"] = float(values[-1])
        except Exception as e:
            _logger.exception("GoogleTrendsCollector failed")
            payload = {
                "source": self.name,
                "status": "error",
                "reason": repr(e),
                "timestamp": timestamp,
                "data": None,
                "sentiment_score": 0.0,
            }
        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
