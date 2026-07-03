"""Alternative.me collector for Fear & Greed index."""
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


class AlternativeMeCollector(CollectorBase):
    name = "alternative_me"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        self.enabled = os.getenv("ENABLE_ALTERNATIVE_ME", "true").strip().lower() == "true"

    def collect(self, force: bool = False) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        if not self.enabled:
            result = {
                "source": self.name,
                "status": "skipped",
                "reason": "disabled_by_env",
                "timestamp": timestamp,
                "data": None,
            }
            if self.output_path is not None:
                self._write_json(result, self.output_path)
            return result

        result: Dict[str, Any] = {
            "source": self.name,
            "status": "error",
            "reason": None,
            "timestamp": timestamp,
            "data": None,
        }

        try:
            data = _fetch_json("https://api.alternative.me/fng/?limit=1")
            if isinstance(data, dict):
                records = data.get("data", [])
                if records:
                    record = records[0]
                    raw_value = float(record.get("value", 0.0)) if record.get("value") is not None else 0.0
                    score = max(0.0, min(1.0, raw_value / 100.0))
                    regime = record.get("value_classification")
                    result = {
                        "source": self.name,
                        "status": "success",
                        "reason": None,
                        "timestamp": timestamp,
                        "data": {
                            "fear_greed_raw": raw_value,
                            "fear_greed_score": score,
                            "fear_greed_regime": regime,
                        },
                        "fear_greed_raw": raw_value,
                        "fear_greed_score": score,
                        "fear_greed_regime": regime,
                    }
        except Exception as e:
            _logger.exception("AlternativeMeCollector failed")
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
