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


def _safe_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
        return parsed if parsed >= 0 else None
    except (TypeError, ValueError):
        return None


def _sum_numeric_items(items: Any, keys: tuple[str, ...]) -> Optional[float]:
    if not isinstance(items, list):
        return None
    total = 0.0
    samples = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in keys:
            if key in item:
                value = _safe_float(item.get(key))
                if value is not None:
                    total += value
                    samples += 1
                    break
    return total if samples else None


def _pegged_usd(value: Any) -> Optional[float]:
    """Extract a DefiLlama pegged-asset amount without treating absence as zero."""
    if isinstance(value, (int, float, str)):
        return _safe_float(value)
    if not isinstance(value, dict):
        return None
    for key in ("peggedUSD", "usd", "value"):
        parsed = _safe_float(value.get(key))
        if parsed is not None:
            return parsed
    return None


def _parse_stablecoin_supply(data: Any) -> tuple[Optional[float], int]:
    """Parse both /stablecoins and /stablecoincharts/all response schemas."""
    if isinstance(data, dict):
        direct = _safe_float(data.get("total"))
        if direct is not None and direct > 0:
            return direct, 1

        legacy = _pegged_usd(data.get("data", {}).get("totalStablecoins"))
        if legacy is not None and legacy > 0:
            return legacy, 1

        assets = data.get("peggedAssets")
        if not isinstance(assets, list):
            assets = data.get("data", {}).get("coins")
        if isinstance(assets, list):
            values = [
                _pegged_usd(asset.get("circulating") or asset.get("circulatingPrevDay"))
                for asset in assets if isinstance(asset, dict)
            ]
            values = [value for value in values if value is not None]
            return (sum(values), len(values)) if values else (None, 0)

    if isinstance(data, list) and data:
        # Chart rows are historical totals; summing them would multiply supply
        # by the number of days. Use the latest parseable observation.
        for row in reversed(data):
            if not isinstance(row, dict):
                continue
            value = _pegged_usd(
                row.get("totalCirculating")
                or row.get("totalCirculatingUSD")
                or row.get("circulating")
            )
            if value is not None and value > 0:
                return value, 1
        total = _sum_numeric_items(
            data,
            ("marketCap", "market_cap", "marketCapUsd", "market_cap_usd", "totalSupply", "total_supply"),
        )
        return (total, len(data)) if total is not None and total > 0 else (None, 0)
    return None, 0


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
                "stablecoin_supply": None,
                "stablecoin_supply_total": None,
                "tvl": None,
                "chain_tvl": None,
                "protocol_tvl": None,
            },
            "stablecoin_supply": None,
            "stablecoin_supply_total": None,
            "tvl": None,
            "chain_tvl": None,
            "protocol_tvl": None,
            "field_statuses": {},
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
            stablecoins, stablecoin_samples = _parse_stablecoin_supply(stable_data)

            chain_tvl = None
            chain_data = _fetch_json(DEFILLAMA_ENDPOINTS.get("chains"))
            if isinstance(chain_data, list) and chain_data:
                chain_tvl = _sum_numeric_items(chain_data, ("tvl", "tvlUsd", "tvl_usd"))

            protocol_tvl = None
            protocol_data = _fetch_json(DEFILLAMA_ENDPOINTS.get("protocols"))
            if isinstance(protocol_data, list) and protocol_data:
                protocol_tvl = _sum_numeric_items(protocol_data, ("tvl", "tvlUsd", "tvl_usd"))

            tvl_values = [value for value in (chain_tvl, protocol_tvl) if value is not None and value > 0]
            tvl = max(tvl_values) if tvl_values else None

            for field, value in {
                "stablecoin_supply": stablecoins,
                "stablecoin_supply_total": stablecoins,
                "tvl": tvl,
                "chain_tvl": chain_tvl,
                "protocol_tvl": protocol_tvl,
            }.items():
                payload[field] = value
                payload["data"][field] = value
                if value is None or value <= 0:
                    payload["field_statuses"][field] = {
                        "status": "invalid",
                        "reason": "zero_or_missing_" + field,
                    }
            payload["stablecoin_sample_count"] = stablecoin_samples
            payload["raw_stablecoin_supply"] = stablecoins
        except Exception as e:
            _logger.exception("DefiLlamaCollector failed")
            payload = {
                "source": self.name,
                "status": "error",
                "reason": repr(e),
                "timestamp": timestamp,
                "data": None,
                "stablecoin_supply": None,
                "stablecoin_supply_total": None,
                "tvl": None,
                "chain_tvl": None,
                "protocol_tvl": None,
                "field_statuses": {
                    field: {"status": "error", "reason": repr(e)}
                    for field in ("stablecoin_supply", "stablecoin_supply_total", "tvl", "chain_tvl", "protocol_tvl")
                },
            }

        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
