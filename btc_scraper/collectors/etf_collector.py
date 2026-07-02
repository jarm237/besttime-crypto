"""ETF collector for net flow."""
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


class ETFCollector(CollectorBase):
    name = "etf"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)

    def collect(self, force: bool = False) -> Dict[str, Any]:
        payload = {"etf_flow": 0.0}
        try:
            data = _fetch_json("https://api.example.com/etf/flow")
            if isinstance(data, dict):
                records = data.get("data", [])
                if records:
                    payload["etf_flow"] = float(records[-1].get("net_flow", 0.0))
        except Exception:
            payload = {"etf_flow": 0.0}
        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
