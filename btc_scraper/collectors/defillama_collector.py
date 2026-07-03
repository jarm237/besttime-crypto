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


DEFILLAMA_ENDPOINTS = {
    # Primary stablecoins endpoint (corrected from api.llama.fi to stablecoins.llama.fi)
    "stablecoins": "https://stablecoins.llama.fi/stablecoins",
    "stablecoin_charts": "https://stablecoins.llama.fi/stablecoincharts/all",
    # Fallback chains/protocols endpoints
    "chains": "https://api.llama.fi/v2/chains",
    "protocols": "https://api.llama.fi/protocols",
    "fees": "https://api.llama.fi/overview/fees",
    "dexs": "https://api.llama.fi/overview/dexs",
}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _sum_numeric_items(items: Any, keys: tuple[str, ...]) -> float:
    if not isinstance(items, list):
        return 0.0
    total = 0.0
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in keys:
            if key in item:
                total += _safe_float(item.get(key))
                break
    return total


def _fetch_json(url: str) -> Any:
    if requests is None:
        raise RuntimeError("requests is not installed")
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 404:
            _logger.warning("%s returned 404 Not Found", url)
            return None
        response.raise_for_status()
        return response.json()
    except Exception as e:
        _logger.warning("Failed to fetch %s: %s", url, e)
        return None


def _fetch_with_fallbacks(urls: list[str]) -> Any:
    """Try multiple URLs in sequence until one succeeds."""
    for url in urls:
        try:
            result = _fetch_json(url)
            if result is not None:
                _logger.debug("Successfully fetched from %s", url)
                return result
        except Exception:
            continue
    _logger.warning("All fallback URLs failed for stablecoin data")
    return None


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
            "data": {
                "stablecoin_supply": 0.0,
                "stablecoin_supply_total": 0.0,
                "tvl": 0.0,
                "chain_tvl": 0.0,
                "protocol_tvl": 0.0,
            },
            "stablecoin_supply": 0.0,
            "stablecoin_supply_total": 0.0,
            "tvl": 0.0,
            "chain_tvl": 0.0,
            "protocol_tvl": 0.0,
        }

        if not self.enabled:
            payload["status"] = "skipped"
            payload["reason"] = "disabled_by_env"
            payload["data"] = None
            if self.output_path is not None:
                self._write_json(payload, self.output_path)
            return payload

        try:
            # Stablecoin supply can arrive as a dict summary or a list of currencies.
            # Try fallback chain: primary stablecoins endpoint → stablecoincharts → fallback
            stable_data = _fetch_with_fallbacks([
                DEFILLAMA_ENDPOINTS.get("stablecoins"),
                DEFILLAMA_ENDPOINTS.get("stablecoin_charts"),
            ])
            stablecoins = 0.0
            if isinstance(stable_data, dict):
                if stable_data.get("total") is not None:
                    stablecoins = _safe_float(stable_data.get("total"))
                else:
                    stablecoins = _safe_float(
                        stable_data.get("data", {}).get("totalStablecoins", {}).get("value")
                    )
                    if stablecoins == 0.0 and isinstance(stable_data.get("data", {}).get("coins"), list):
                        stablecoins = _sum_numeric_items(
                            stable_data.get("data", {}).get("coins", []),
                            ("marketCap", "market_cap", "marketCapUsd", "market_cap_usd", "totalSupply", "total_supply"),
                        )
            elif isinstance(stable_data, list):
                stablecoins = _sum_numeric_items(
                    stable_data,
                    ("marketCap", "market_cap", "marketCapUsd", "market_cap_usd", "totalSupply", "total_supply"),
                )

            chain_tvl = 0.0
            chain_data = _fetch_json(DEFILLAMA_ENDPOINTS.get("chains"))
            if isinstance(chain_data, list) and chain_data:
                chain_tvl = _sum_numeric_items(chain_data, ("tvl", "tvlUsd", "tvl_usd"))

            protocol_tvl = 0.0
            protocol_data = _fetch_json(DEFILLAMA_ENDPOINTS.get("protocols"))
            if isinstance(protocol_data, list) and protocol_data:
                protocol_tvl = _sum_numeric_items(protocol_data, ("tvl", "tvlUsd", "tvl_usd"))

            tvl = max(chain_tvl, protocol_tvl)
            if tvl == 0.0 and isinstance(chain_data, list) and chain_data:
                tvl = chain_tvl
            elif tvl == 0.0 and isinstance(protocol_data, list) and protocol_data:
                tvl = protocol_tvl

            payload["stablecoin_supply"] = float(stablecoins or 0.0)
            payload["stablecoin_supply_total"] = float(stablecoins or 0.0)
            payload["tvl"] = float(tvl or 0.0)
            payload["chain_tvl"] = float(chain_tvl or 0.0)
            payload["protocol_tvl"] = float(protocol_tvl or 0.0)
            payload["data"]["stablecoin_supply"] = float(stablecoins or 0.0)
            payload["data"]["stablecoin_supply_total"] = float(stablecoins or 0.0)
            payload["data"]["tvl"] = float(tvl or 0.0)
            payload["data"]["chain_tvl"] = float(chain_tvl or 0.0)
            payload["data"]["protocol_tvl"] = float(protocol_tvl or 0.0)
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
