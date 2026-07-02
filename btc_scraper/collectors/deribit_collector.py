"""Deribit collector for options IV and skew."""
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


class DeribitCollector(CollectorBase):
    name = "deribit"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)

    def collect(self, force: bool = False) -> Dict[str, Any]:
        payload = {"options_iv": 0.0, "iv_skew": 0.0}
        try:
            data = _fetch_json("https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC")
            if isinstance(data, dict):
                result = data.get("result", [])
                if result:
                    entry = result[-1]
                    iv = entry.get("mark_iv", 0.0)
                    ask = entry.get("best_ask_iv", iv)
                    bid = entry.get("best_bid_iv", iv)
                    payload["options_iv"] = float(iv)
                    payload["iv_skew"] = round(float(ask - bid), 10)
        except Exception:
            payload = {"options_iv": 0.0, "iv_skew": 0.0}
        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
