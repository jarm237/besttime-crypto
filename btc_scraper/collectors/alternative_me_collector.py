"""Alternative.me collector for Fear & Greed index."""
from __future__ import annotations
import copy
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from btc_scraper.collectors.collector_base import CollectorBase
from btc_scraper.core.fear_greed import normalize_fear_greed
import logging

_logger = logging.getLogger(__name__)
_CACHE_LOCK = threading.Lock()
_CACHE_VALUE: Optional[Dict[str, Any]] = None
_CACHE_FETCHED_AT = 0.0

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
        global _CACHE_FETCHED_AT, _CACHE_VALUE
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

        try:
            cache_ttl = max(0.0, float(os.getenv("ALTERNATIVE_ME_CACHE_TTL_SECONDS", "21600")))
        except ValueError:
            cache_ttl = 21600.0
        with _CACHE_LOCK:
            if not force and _CACHE_VALUE is not None and time.time() - _CACHE_FETCHED_AT < cache_ttl:
                result = copy.deepcopy(_CACHE_VALUE)
                result["cache_hit"] = True
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
                if not records:
                    raise ValueError("Alternative.me returned no Fear & Greed observations")
                record = records[0]
                if record.get("value") is None:
                    raise ValueError("Alternative.me observation is missing value")
                raw_value = float(record["value"])
                score = normalize_fear_greed(raw_value)
                regime = record.get("value_classification")
                observed_at = None
                if record.get("timestamp") is not None:
                    observed_at = datetime.fromtimestamp(int(record["timestamp"]), tz=timezone.utc).isoformat()
                result = {
                    "source": self.name,
                    "status": "success",
                    "reason": None,
                    "timestamp": timestamp,
                    "data": {
                        "fear_greed_raw": raw_value,
                        "fear_greed_score": score,
                        "fear_greed_regime": regime,
                        "fear_greed_observed_at": observed_at,
                    },
                    "fear_greed_raw": raw_value,
                    "fear_greed_score": score,
                    "fear_greed_regime": regime,
                    "fear_greed_observed_at": observed_at,
                    "stale": False,
                    "cache_hit": False,
                }
                with _CACHE_LOCK:
                    _CACHE_VALUE = copy.deepcopy(result)
                    _CACHE_FETCHED_AT = time.time()
            else:
                raise ValueError("Alternative.me returned a non-object payload")
        except Exception as e:
            _logger.exception("AlternativeMeCollector failed")
            with _CACHE_LOCK:
                cached = copy.deepcopy(_CACHE_VALUE)
            if cached is not None:
                result = cached
                result.update({
                    "status": "stale",
                    "reason": repr(e),
                    "stale": True,
                    "cache_hit": True,
                })
            else:
                result = {
                    "source": self.name,
                    "status": "unavailable",
                    "reason": repr(e),
                    "timestamp": timestamp,
                    "data": None,
                    "stale": False,
                    "cache_hit": False,
                }

        if self.output_path is not None:
            self._write_json(result, self.output_path)
        return result
