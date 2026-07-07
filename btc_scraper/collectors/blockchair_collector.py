"""Blockchair collector for network statistics."""
from __future__ import annotations
import os
import requests
from typing import Any, Dict, Optional
from btc_scraper.collectors.collector_base import CollectorBase
import logging
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

def safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None

def latest_record(records):
    if records is None:
        return None

    if isinstance(records, list):
        return records[-1] if records else None

    if isinstance(records, dict):
        if not records:
            return None
        try:
            last_key = sorted(records.keys())[-1]
            return records[last_key]
        except Exception:
            return None

    return None

class BlockchairCollector(CollectorBase):
    name = "blockchair"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        self.enabled = os.getenv("ENABLE_BLOCKCHAIR", "true").strip().lower() == "true"

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

        url = "https://api.blockchair.com/bitcoin/stats"

        try:
            response = requests.get(
                url,
                timeout=20,
                headers={"User-Agent": "besttime-crypto/1.0"},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            ret = {
                "source": "blockchair",
                "status": "error",
                "reason": str(e),
                "timestamp": now,
                "data": None,
            }
            if self.output_path is not None:
                self._write_json(ret, self.output_path)
            return ret

        data = payload.get("data", {})
        if not isinstance(data, dict):
            ret = {
                "source": "blockchair",
                "status": "skipped",
                "reason": "unexpected_payload_shape",
                "timestamp": now,
                "data": None,
            }
            if self.output_path is not None:
                self._write_json(ret, self.output_path)
            return ret

        ret = {
            "source": "blockchair",
            "status": "success",
            "reason": None,
            "timestamp": now,
            "data": {
                "tx_count_24h": safe_float(data.get("transactions_24h")),
                "market_price_usd": safe_float(data.get("market_price_usd")),
                "hashrate_24h": safe_float(data.get("hashrate_24h")),
                "difficulty": safe_float(data.get("difficulty")),
                "large_tx_proxy_score": None,
                "exchange_netflow": None,
                "exchange_netflow_status": "unsupported_free_source",
            },
            "exchange_netflow": None,
        }
        
        if self.output_path is not None:
            self._write_json(ret, self.output_path)
        return ret
