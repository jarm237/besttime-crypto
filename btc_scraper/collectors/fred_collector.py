"""FRED collector for macro series such as US10Y."""

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


class FredCollector(CollectorBase):
    name = "fred"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)

    def collect(self, force: bool = False) -> Dict[str, Any]:
        payload = {"us10y": 0.0, "gold": 0.0}
        try:
            data = _fetch_json("https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key=demo&file_type=json")
            observations = data.get("observations", []) if isinstance(data, dict) else []
            if observations:
                last_value = observations[-1].get("value", "0")
                payload["us10y"] = float(last_value) if last_value not in {"", "None", None} else 0.0
        except Exception:
            payload = {"us10y": 0.0, "gold": 0.0}

        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
