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


def _fetch_json(url: str) -> Any:
    if requests is None:
        raise RuntimeError("requests is not installed")
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


class BlockchainCollector(CollectorBase):
    name = "blockchain"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        self.enabled = os.getenv("ENABLE_BLOCKCHAIN_COM", "true").strip().lower() == "true"

    def collect(self, force: bool = False) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "source": self.name,
            "status": "success",
            "reason": None,
            "timestamp": timestamp,
            "data": {"hashrate": 0.0},
            "hashrate": 0.0,
        }

        if not self.enabled:
            payload["status"] = "skipped"
            payload["reason"] = "disabled_by_env"
            payload["data"] = None
            if self.output_path is not None:
                self._write_json(payload, self.output_path)
            return payload

        try:
            data = _fetch_json("https://api.blockchain.info/charts/hash-rate?timespan=86400&rollingAverage=8hours&format=json")
            if isinstance(data, dict):
                values = data.get("values", [])
                if values:
                    last_value = values[-1].get("y", values[-1].get("value", 0.0))
                    payload["hashrate"] = float(last_value)
                    payload["data"]["hashrate"] = float(last_value)
                elif data.get("hash_rate") is not None:
                    payload["hashrate"] = float(data.get("hash_rate", 0.0))
                    payload["data"]["hashrate"] = float(data.get("hash_rate", 0.0))
        except Exception as e:
            _logger.exception("BlockchainCollector failed")
            payload = {
                "source": self.name,
                "status": "error",
                "reason": repr(e),
                "timestamp": timestamp,
                "data": None,
                "hashrate": 0.0,
            }
        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
