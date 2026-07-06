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
            # Check if PARSEBOT_ENABLED is true
            parsebot_enabled = os.getenv("PARSEBOT_ENABLED", "false").strip().lower() == "true"
            allow_fake = os.getenv("ETF_FLOW_ALLOW_DEFAULT_FAKE_DATA", "false").strip().lower() == "true"

            if parsebot_enabled:
                from btc_scraper.collectors.parsebot_farside_collector import get_etf_feature_for_scoring
                feature = get_etf_feature_for_scoring("BTC", mode="recent")
                status = feature["etf_flow_status"]
                
                if status == "ok":
                    payload["etf_flow"] = feature["total_flow_usd_m"]
                    payload["etf_flow_confidence"] = 0.65
                    payload["etf_flow_source"] = "parsebot_farside"
                    payload["data"]["etf_flow"] = feature["total_flow_usd_m"]
                    payload["status"] = "success"
                    _logger.info(
                        "ETF flow collected from Parse.bot cache: flow=%.2f, source=%s",
                        payload["etf_flow"],
                        payload["etf_flow_source"],
                    )
                else:
                    payload["status"] = "failed" if status == "failed" else status
                    payload["reason"] = f"parsebot_cache_{status}"
                    payload["etf_flow"] = 0.0 if allow_fake else None
                    payload["etf_flow_confidence"] = 0.0
                    payload["etf_flow_source"] = "parsebot_farside"
                    if "etf_flow" in payload["data"]:
                        payload["data"]["etf_flow"] = 0.0 if allow_fake else None
                    _logger.warning("Parse.bot ETF cache not usable: status=%s, allow_fake=%s", status, allow_fake)
            else:
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
                        "ETF flow collected from provider chain: flow=%.2f, confidence=%.2f, source=%s",
                        result.etf_flow,
                        result.etf_flow_confidence,
                        result.etf_flow_source,
                    )
                else:
                    payload["status"] = "fallback" if allow_fake else "failed"
                    payload["reason"] = "all_providers_failed"
                    payload["etf_flow"] = 0.0 if allow_fake else None
                    payload["etf_flow_confidence"] = 0.0
                    if "etf_flow" in payload["data"]:
                        payload["data"]["etf_flow"] = 0.0 if allow_fake else None
                    _logger.warning("All ETF providers failed; allow_fake=%s", allow_fake)

        except Exception as e:
            _logger.exception("ETFCollector failed")
            allow_fake = os.getenv("ETF_FLOW_ALLOW_DEFAULT_FAKE_DATA", "false").strip().lower() == "true"
            payload = {
                "source": self.name,
                "status": "error",
                "reason": repr(e),
                "timestamp": timestamp,
                "data": {"etf_flow": 0.0 if allow_fake else None},
                "etf_flow": 0.0 if allow_fake else None,
                "etf_flow_confidence": 0.0,
                "etf_flow_source": "none",
                "etf_flow_scope": "us_spot_btc_etf",
            }
        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload
