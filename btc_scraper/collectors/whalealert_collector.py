"""Whale Alert collector for whale score."""
from __future__ import annotations
import os
from typing import Any, Dict, Optional
from btc_scraper.collectors.collector_base import CollectorBase

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
    name = "whalealert"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)

    def collect(self, force: bool = False) -> Dict[str, Any]:
        payload = {"whale_score": 0.0}
        try:
            data = _fetch_json("https://api.whale-alert.io/v1/transactions?limit=1")
            if isinstance(data, dict):
                records = data.get("data", [])
                if records:
                    amount = records[-1].get("amount_usd", 0.0)
                    payload["whale_score"] = min(100.0, max(0.0, float(amount) / 1_000_000.0))
        except Exception:
            payload = {"whale_score": 0.0}
        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
