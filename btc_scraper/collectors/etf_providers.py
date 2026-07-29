"""ETF flow data providers for Phase 7 Sprint 9.2.

Implements a provider chain pattern for ETF flow collection:
  1. Parse.bot Farside wrapper (primary, JSON, limited free quota)
  2. Farside HTML scraper (fallback, web scraping)
  3. Issuer-derived flow (optional, computed from NAV + shares)

Each provider is independent and can fail gracefully.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from btc_scraper.collectors.parsebot_key_rotation import (
    ParsebotKeyManager,
    get_parsebot_key_manager,
    is_parsebot_key_exhaustion_error,
    load_parsebot_api_keys,
)

_logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    requests = None


@dataclass
class ETFFlowResult:
    """Result from an ETF provider."""

    provider_name: str
    etf_flow: float
    etf_flow_confidence: float
    etf_flow_source: str
    etf_flow_scope: str = "us_spot_btc_etf"
    success: bool = True
    error: Optional[str] = None
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class ETFProvider(ABC):
    """Abstract base for ETF flow providers."""

    name: str = "etf_provider"

    @abstractmethod
    def fetch(self) -> Optional[ETFFlowResult]:
        """
        Fetch ETF flow data.

        Returns:
            ETFFlowResult if successful, None if provider fails.
        """
        pass
class ParseBotFarsideProvider(ETFProvider):
    """
    Parse.bot Farside wrapper for US spot BTC/ETH ETF flows.

    API: https://api.parse.bot/scraper/e9735bc0-4fc2-4b16-b510-66b77907c48e/get_bitcoin_etf_flows_recent
    Confidence: 0.65 (official API, but third-party aggregation)
    Scope: US spot BTC/ETH/SOL ETF daily flows
    """

    name = "parsebot_farside"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 10.0) -> None:
        import os
        self.api_keys = [api_key.strip()] if api_key and api_key.strip() else load_parsebot_api_keys()
        self.api_key = self.api_keys[0] if self.api_keys else None
        self._key_manager = (
            ParsebotKeyManager(self.api_keys)
            if api_key
            else get_parsebot_key_manager(self.api_keys)
        )
        self.timeout = timeout
        base = os.getenv("PARSEBOT_BASE_URL", "https://api.parse.bot/scraper/e9735bc0-4fc2-4b16-b510-66b77907c48e")
        self.base_url = base.strip().rstrip("/")

    def fetch(self) -> Optional[ETFFlowResult]:
        """Fetch BTC ETF flow from Parse.bot Farside API."""
        if requests is None:
            _logger.warning("%s: requests library not available", self.name)
            return None

        if not self.api_keys:
            _logger.warning("%s: API key not configured", self.name)
            return None

        import os
        endpoint = os.getenv("PARSEBOT_ENDPOINT_BTC_RECENT", "get_bitcoin_etf_flows_recent")
        url = f"{self.base_url}/{endpoint}"
        while self._key_manager.available:
            api_key = self._key_manager.next_key()
            if api_key is None:
                break
            key_label = f"...{api_key[-6:]}"
            from btc_scraper.collectors.parsebot_farside_collector import _reserve_parsebot_request

            allowed, request_count, request_limit = _reserve_parsebot_request(api_key=api_key)
            if not allowed:
                self._key_manager.mark_exhausted(api_key)
                _logger.warning(
                    "%s: key %s monthly guard exhausted (%d/%d); rotating",
                    self.name,
                    key_label,
                    request_count,
                    request_limit,
                )
                continue
            headers = {
                "X-API-Key": api_key,
                "Accept": "application/json",
            }

            try:
                response = requests.get(url, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
                self._key_manager.reset_key(api_key)

                records = []
                if isinstance(data, list):
                    records = data
                elif isinstance(data, dict):
                    if isinstance(data.get("data"), list):
                        records = data["data"]
                    else:
                        records = [data]

                if records:
                    latest = records[-1]
                    if isinstance(latest, dict):
                        flow_val = None
                        for key in ("total_flow", "total_flow_usd_m", "net_flow", "flow", "total", "net"):
                            v = latest.get(key)
                            if v is not None:
                                try:
                                    flow_val = float(v)
                                    break
                                except (TypeError, ValueError):
                                    continue

                        if flow_val is not None:
                            return ETFFlowResult(
                                provider_name=self.name,
                                etf_flow=flow_val,
                                etf_flow_confidence=0.65,
                                etf_flow_source="parsebot_farside",
                                etf_flow_scope="us_spot_btc_etf",
                                success=True,
                            )

                _logger.debug("%s: No valid ETF flow data in response", self.name)
                return None

            except requests.exceptions.Timeout:
                _logger.warning("%s: Request timed out after %.1fs", self.name, self.timeout)
                return None
            except requests.exceptions.HTTPError as exc:
                status_code = getattr(exc.response, "status_code", None)
                if is_parsebot_key_exhaustion_error(exc):
                    self._key_manager.mark_exhausted(api_key)
                    _logger.warning("%s: key %s exhausted; rotating", self.name, key_label)
                    continue
                if status_code == 404:
                    _logger.debug("%s: Endpoint not found (404)", self.name)
                else:
                    _logger.warning("%s: HTTP error %s", self.name, status_code or "unknown")
                return None
            except Exception as exc:
                if is_parsebot_key_exhaustion_error(exc):
                    self._key_manager.mark_exhausted(api_key)
                    _logger.warning("%s: key %s exhausted; rotating", self.name, key_label)
                    continue
                _logger.warning("%s: Failed to fetch: %s", self.name, exc)
                return None

        _logger.warning(
            "%s: all %d API keys exhausted; paused until %s",
            self.name,
            self._key_manager.key_count,
            self._key_manager.pause_info,
        )
        return None


class FarsideHtmlProvider(ETFProvider):
    """
    Farside public page scraper for US spot BTC/ETH ETF flows.

    URL: https://www.farside.co.uk/
    Confidence: 0.50 (unofficial scraper, rate-limited)
    Scope: US spot BTC/ETH/SOL ETF daily flows
    """

    name = "farside_html"

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self.url = "https://www.farside.co.uk/"

    def fetch(self) -> Optional[ETFFlowResult]:
        """
        Fetch ETF flow from Farside HTML page (scraper fallback).

        This is a placeholder for actual HTML scraping logic.
        A real implementation would parse the Farside table.
        """
        if requests is None:
            _logger.warning("%s: requests library not available", self.name)
            return None

        try:
            response = requests.get(self.url, timeout=self.timeout)
            response.raise_for_status()

            # TODO: Implement actual HTML parsing
            # For now, return None to indicate not implemented
            _logger.debug("%s: HTML scraper not fully implemented, falling back", self.name)
            return None

        except requests.exceptions.Timeout:
            _logger.warning("%s: Request timed out after %.1fs", self.name, self.timeout)
            return None
        except Exception as e:
            _logger.debug("%s: Failed to fetch: %s", self.name, e)
            return None


class IssuerDerivedFlowProvider(ETFProvider):
    """
    Estimate ETF flow from issuer data (NAV + shares outstanding).

    Uses public issuer pages or SEC filings to estimate daily flows.
    Confidence: 0.40 (derived metric, not official daily flow)
    Scope: Estimated US spot BTC ETF flows
    """

    name = "issuer_derived"

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def fetch(self) -> Optional[ETFFlowResult]:
        """
        Fetch ETF flow from issuer-derived calculation.

        This is a placeholder for actual issuer-data collection logic.
        A real implementation would fetch NAV and shares outstanding.
        """
        _logger.debug("%s: Issuer-derived flow provider not fully implemented", self.name)
        return None


class ETFProviderChain:
    """
    Try multiple ETF providers in sequence until one succeeds.

    Implements graceful degradation: if a provider fails, try the next one.
    """

    def __init__(self, providers: Optional[list[ETFProvider]] = None) -> None:
        """
        Initialize the provider chain.

        Args:
            providers: List of ETFProvider instances in priority order.
                      Defaults to [ParseBotFarsideProvider, FarsideHtmlProvider].
        """
        self.providers = providers or [
            ParseBotFarsideProvider(),
            FarsideHtmlProvider(),
        ]

    def fetch(self) -> Optional[ETFFlowResult]:
        """
        Try providers in order until one returns a successful result.

        Returns:
            ETFFlowResult from the first successful provider, or None if all fail.
        """
        for provider in self.providers:
            try:
                result = provider.fetch()
                if result is not None and result.success:
                    _logger.debug(
                        "ETF flow obtained from %s: flow=%.2f, confidence=%.2f",
                        result.etf_flow_source,
                        result.etf_flow,
                        result.etf_flow_confidence,
                    )
                    return result
            except Exception as e:
                _logger.warning("Provider %s raised exception: %s", provider.name, e)
                continue

        _logger.debug("All ETF providers failed; using last-known value or default")
        return None
