"""Blockchain.com collector for hashrate."""
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


def _fetch_json(url: str, timeout: int = 20):
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "besttime-crypto/1.0"},
        )

        if response.status_code == 404:
            return {
                "status": "skipped",
                "reason": "endpoint_not_found",
                "url": url,
                "data": None,
            }

        response.raise_for_status()

        return {
            "status": "success",
            "reason": None,
            "url": response.url,
            "data": response.json(),
        }

    except Exception as e:
        return {
            "status": "error",
            "reason": str(e),
            "url": url,
            "data": None,
        }

def extract_latest_chart_value(payload):
    if not isinstance(payload, dict):
        return None

    values = payload.get("values")
    if not isinstance(values, list) or not values:
        return None

    latest = values[-1]
    if not isinstance(latest, dict):
        return None

    return latest.get("y")

class BlockchainCollector(CollectorBase):
    name = "blockchain"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        self.enabled = os.getenv("ENABLE_BLOCKCHAIN_COM", "true").strip().lower() == "true"

    def collect(self, force: bool = False) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()

        if not self.enabled:
            payload = {
                "source": self.name,
                "status": "skipped",
                "reason": "disabled_by_env",
                "timestamp": now,
                "data": None,
            }
            if self.output_path is not None:
                self._write_json(payload, self.output_path)
            return payload

        urls = {
            "hashrate": "https://api.blockchain.info/charts/hash-rate?timespan=30days&rollingAverage=8hours&format=json",
            "difficulty": "https://api.blockchain.info/charts/difficulty?timespan=30days&format=json",
            "tx_count": "https://api.blockchain.info/charts/n-transactions?timespan=30days&format=json",
        }

        data = {}
        errors = {}

        for key, url in urls.items():
            result = _fetch_json(url)

            if result["status"] != "success":
                errors[key] = result
                data[key] = None
                continue

            data[key] = extract_latest_chart_value(result["data"])

        payload = {
            "source": self.name,
            "status": "success" if any(v is not None for v in data.values()) else "skipped",
            "reason": None if any(v is not None for v in data.values()) else "no_chart_data",
            "timestamp": now,
            "data": data,
            "errors": errors,
        }
        
        # Backward compatibility with existing pipeline
        payload["hashrate"] = data.get("hashrate")

        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
