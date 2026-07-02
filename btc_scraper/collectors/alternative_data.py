"""Alternative-data collection layer for Phase 7.

This module provides a lightweight, dependency-light implementation that
produces a normalized payload for downstream feature building and world-state
integration.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from btc_scraper.collectors.collector_base import CollectorBase, CollectorScheduler
from btc_scraper.collectors.binance_collector import BinanceCollector
from btc_scraper.collectors.defillama_collector import DefiLlamaCollector
from btc_scraper.collectors.fred_collector import FredCollector
from btc_scraper.collectors.yahoo_collector import YahooCollector
from btc_scraper.collectors.glassnode_collector import GlassnodeCollector
from btc_scraper.collectors.blockchain_collector import BlockchainCollector
from btc_scraper.collectors.blockchair_collector import BlockchairCollector
from btc_scraper.collectors.whalealert_collector import WhaleAlertCollector
from btc_scraper.collectors.deribit_collector import DeribitCollector
from btc_scraper.collectors.etf_collector import ETFCollector
from btc_scraper.collectors.google_trends_collector import GoogleTrendsCollector
from btc_scraper.collectors.reddit_collector import RedditCollector
from btc_scraper.core.paths import build_data_path

DEFAULT_OUTPUT_PATH = str(build_data_path("alternative_data.json"))


class AlternativeDataCollector(CollectorBase):
    """Collect free / public alternative data proxies and normalize them."""

    name = "alternative_data"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = DEFAULT_OUTPUT_PATH, retries: int = 2, delay_seconds: float = 1.0) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)

    def collect(self, force: bool = False) -> Dict[str, Any]:
        payload = _default_payload()

        try:
            binance_payload = BinanceCollector().collect(force=force)
            payload.update({"funding_rate": binance_payload.get("funding_rate", 0.0), "open_interest": binance_payload.get("open_interest", 0.0)})
        except Exception:
            payload.update({"funding_rate": 0.0, "open_interest": 0.0})

        try:
            defillama_payload = DefiLlamaCollector().collect(force=force)
            payload.update({"stablecoin_supply": defillama_payload.get("stablecoin_supply", 0.0), "tvl": defillama_payload.get("tvl", 0.0)})
        except Exception:
            payload.update({"stablecoin_supply": 0.0, "tvl": 0.0})

        try:
            fred_payload = FredCollector().collect(force=force)
            payload.update({"us10y": fred_payload.get("us10y", 0.0), "gold": fred_payload.get("gold", 0.0)})
        except Exception:
            payload.update({"us10y": 0.0, "gold": 0.0})

        try:
            yahoo_payload = YahooCollector().collect(force=force)
            payload.update({"dxy": yahoo_payload.get("dxy", 0.0), "vix": yahoo_payload.get("vix", 0.0), "gold": yahoo_payload.get("gold", 0.0)})
        except Exception:
            payload.update({"dxy": 0.0, "vix": 0.0, "gold": 0.0})

        try:
            glassnode_payload = GlassnodeCollector().collect(force=force)
            payload.update({"active_addresses": glassnode_payload.get("active_addresses", 0.0)})
        except Exception:
            payload.update({"active_addresses": 0.0})

        try:
            blockchain_payload = BlockchainCollector().collect(force=force)
            payload.update({"hashrate": blockchain_payload.get("hashrate", 0.0)})
        except Exception:
            payload.update({"hashrate": 0.0})

        try:
            blockchair_payload = BlockchairCollector().collect(force=force)
            payload.update({"exchange_netflow": blockchair_payload.get("exchange_netflow", 0.0)})
        except Exception:
            payload.update({"exchange_netflow": 0.0})

        try:
            whale_payload = WhaleAlertCollector().collect(force=force)
            payload.update({"whale_score": whale_payload.get("whale_score", 0.0)})
        except Exception:
            payload.update({"whale_score": 0.0})

        try:
            deribit_payload = DeribitCollector().collect(force=force)
            payload.update({"options_iv": deribit_payload.get("options_iv", 0.0), "iv_skew": deribit_payload.get("iv_skew", 0.0)})
        except Exception:
            payload.update({"options_iv": 0.0, "iv_skew": 0.0})

        try:
            etf_payload = ETFCollector().collect(force=force)
            payload.update({"etf_flow": etf_payload.get("etf_flow", 0.0)})
        except Exception:
            payload.update({"etf_flow": 0.0})

        try:
            google_payload = GoogleTrendsCollector().collect(force=force)
            payload.update({"sentiment_score": google_payload.get("sentiment_score", 0.0)})
        except Exception:
            payload.update({"sentiment_score": 0.0})

        try:
            reddit_payload = RedditCollector().collect(force=force)
            payload.update({"social_sentiment": reddit_payload.get("sentiment_score", 0.0)})
        except Exception:
            payload.update({"social_sentiment": 0.0})

        payload.update({
            "orderbook_imbalance": 0.0,
            "liquidity_pressure": 0.0,
            "macro_pressure": 0.0,
            "funding_pressure": 0.0,
            "stablecoin_momentum": 0.0,
            "etf_momentum": 0.0,
            "risk_on_score": 0.0,
        })

        if self.output_path is not None:
            self._write_json(payload, self.output_path)
        return payload


def collect_alternative_data(output_path: Optional[str] = DEFAULT_OUTPUT_PATH, force: bool = False) -> Dict[str, Any]:
    """Collect and persist alternative-data payload."""
    collector = AlternativeDataCollector(output_path=output_path)
    scheduler = CollectorScheduler(retries=1, delay_seconds=0.0)
    return scheduler.run(collector, force=force)


def load_alternative_data(path: Optional[str] = DEFAULT_OUTPUT_PATH) -> Dict[str, Any]:
    """Load the alternative-data payload from disk, returning defaults when missing."""
    if path is None:
        path = DEFAULT_OUTPUT_PATH
    target = Path(path)
    if not target.exists():
        return _default_payload()
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return _merge_default_payload(data)
    except Exception:
        return _default_payload()
    return _default_payload()


def _default_payload() -> Dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "exchange_netflow": 0.0,
        "whale_score": 0.0,
        "stablecoin_supply": 0.0,
        "tvl": 0.0,
        "funding_rate": 0.0,
        "open_interest": 0.0,
        "dxy": 0.0,
        "vix": 0.0,
        "us10y": 0.0,
        "gold": 0.0,
        "funding_pressure": 0.0,
        "stablecoin_momentum": 0.0,
        "etf_momentum": 0.0,
        "risk_on_score": 0.0,
    }


def _merge_default_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    merged = _default_payload()
    merged.update(payload)
    return merged
