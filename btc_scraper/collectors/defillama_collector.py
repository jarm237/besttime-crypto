"""DefiLlama collector for TVL and stablecoin supply."""

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


class DefiLlamaCollector(CollectorBase):
    name = "defillama"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        self.enabled = os.getenv("ENABLE_DEFILLAMA", "true").strip().lower() == "true"

    def collect(self, force: bool = False) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "source": self.name,
            "status": "success",
            "reason": None,
            "timestamp": timestamp,
            "data": {"stablecoin_supply": 0.0, "tvl": 0.0},
            "stablecoin_supply": 0.0,
            "tvl": 0.0,
        }

        if not self.enabled:
            payload["status"] = "skipped"
            payload["reason"] = "disabled_by_env"
            payload["data"] = None
            if self.output_path is not None:
                self._write_json(payload, self.output_path)
            return payload

        try:
            data = _fetch_json("https://api.llama.fi/v2/summary")
            if isinstance(data, dict):
                stablecoins = data.get("data", {}).get("totalStablecoins", {}).get("value", 0)
                tvl = data.get("data", {}).get("tvl", {}).get("value", 0)
                payload["stablecoin_supply"] = float(stablecoins)
                payload["tvl"] = float(tvl)
                payload["data"]["stablecoin_supply"] = float(stablecoins)
                payload["data"]["tvl"] = float(tvl)
        except Exception as e:
            _logger.exception("DefiLlamaCollector failed")
            payload = {
                "source": self.name,
                "status": "error",
                "reason": repr(e),
                "timestamp": timestamp,
                "data": None,
                "stablecoin_supply": 0.0,
                "tvl": 0.0,
            }

        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
