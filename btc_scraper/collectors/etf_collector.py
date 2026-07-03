"""ETF collector for net flow."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from btc_scraper.collectors.collector_base import CollectorBase
from btc_scraper.collectors.etf_providers import ETFProviderChain
import logging

_logger = logging.getLogger(__name__)


class ETFCollector(CollectorBase):
    name = "etf"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        # Disabled by default: placeholder endpoint requires Farside/Parse provider implementation
        self.enabled = os.getenv("ENABLE_ETF", "false").strip().lower() == "true"
        if not self.enabled:
            _logger.info(
                "ETFCollector is disabled by default. "
                "Set ENABLE_ETF=true and implement ETF provider chain (Farside/Parse.bot) before enabling."
            )

    def collect(self, force: bool = False) -> Dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "source": self.name,
            "status": "success",
            "reason": None,
            "timestamp": timestamp,
            "data": {"etf_flow": 0.0},
            "etf_flow": 0.0,
            "etf_flow_confidence": 0.0,
            "etf_flow_source": "none",
            "etf_flow_scope": "us_spot_btc_etf",
        }

        if not self.enabled:
            payload["status"] = "skipped"
            payload["reason"] = "disabled_by_env"
            payload["data"] = None
            if self.output_path is not None:
                self._write_json(payload, self.output_path)
            return payload

        try:
            # Use provider chain for ETF flow collection
            provider_chain = ETFProviderChain()
            result = provider_chain.fetch()

            if result is not None:
                payload["etf_flow"] = result.etf_flow
                payload["etf_flow_confidence"] = result.etf_flow_confidence
                payload["etf_flow_source"] = result.etf_flow_source
                payload["etf_flow_scope"] = result.etf_flow_scope
                payload["data"]["etf_flow"] = result.etf_flow
                payload["status"] = "success"
                _logger.info(
                    "ETF flow collected: flow=%.2f, confidence=%.2f, source=%s",
                    result.etf_flow,
                    result.etf_flow_confidence,
                    result.etf_flow_source,
                )
            else:
                # All providers failed; use last-known value or default
                payload["status"] = "fallback"
                payload["reason"] = "all_providers_failed"
                payload["etf_flow"] = 0.0
                payload["etf_flow_confidence"] = 0.0
                _logger.warning("All ETF providers failed; using default")

        except Exception as e:
            _logger.exception("ETFCollector failed")
            payload = {
                "source": self.name,
                "status": "error",
                "reason": repr(e),
                "timestamp": timestamp,
                "data": None,
                "etf_flow": 0.0,
                "etf_flow_confidence": 0.0,
                "etf_flow_source": "none",
                "etf_flow_scope": "us_spot_btc_etf",
            }
        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
