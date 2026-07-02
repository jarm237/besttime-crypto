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

from btc_scraper.core.paths import build_data_path

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

DEFAULT_OUTPUT_PATH = str(build_data_path("alternative_data.json"))
DEFAULT_RAW_STORE_DIR = str(build_data_path("raw_alternative"))
DEFAULT_FEATURE_SNAPSHOT_PATH = str(build_data_path("alternative_feature_snapshot.json"))


class AlternativeDataCollector(CollectorBase):
    """Collect free / public alternative data proxies and normalize them."""

    name = "alternative_data"

    def __init__(
        self,
        output_path: Optional[str | os.PathLike[str]] = DEFAULT_OUTPUT_PATH,
        retries: int = 2,
        delay_seconds: float = 1.0,
        raw_store_dir: Optional[str | os.PathLike[str]] = DEFAULT_RAW_STORE_DIR,
        feature_snapshot_path: Optional[str | os.PathLike[str]] = DEFAULT_FEATURE_SNAPSHOT_PATH,
    ) -> None:
        super().__init__(output_path=output_path, retries=retries, delay_seconds=delay_seconds)
        self.raw_store_dir = Path(raw_store_dir) if raw_store_dir is not None else None
        self.feature_snapshot_path = Path(feature_snapshot_path) if feature_snapshot_path is not None else None

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

        previous_payload = load_alternative_data(self.output_path) if self.output_path is not None else None
        normalized_payload = normalize_alternative_payload(
            payload,
            previous_payload=previous_payload,
            raw_store_dir=self.raw_store_dir,
        )

        if self.output_path is not None:
            self._write_json(normalized_payload, self.output_path)
        if self.feature_snapshot_path is not None:
            self._write_json(normalized_payload, self.feature_snapshot_path)
        return normalized_payload


def collect_alternative_data(
    output_path: Optional[str] = DEFAULT_OUTPUT_PATH,
    force: bool = False,
    raw_store_dir: Optional[str] = DEFAULT_RAW_STORE_DIR,
    feature_snapshot_path: Optional[str] = DEFAULT_FEATURE_SNAPSHOT_PATH,
) -> Dict[str, Any]:
    """Collect and persist alternative-data payload."""
    collector = AlternativeDataCollector(
        output_path=output_path,
        raw_store_dir=raw_store_dir,
        feature_snapshot_path=feature_snapshot_path,
    )
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
        "orderbook_imbalance": 0.0,
        "liquidity_pressure": 0.0,
        "macro_pressure": 0.0,
        "funding_pressure": 0.0,
        "stablecoin_momentum": 0.0,
        "etf_momentum": 0.0,
        "risk_on_score": 0.0,
    }


def _merge_default_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    merged = _default_payload()
    merged.update(payload)
    return merged


def normalize_alternative_payload(
    payload: Dict[str, Any],
    previous_payload: Optional[Dict[str, Any]] = None,
    raw_store_dir: Optional[str | os.PathLike[str]] = DEFAULT_RAW_STORE_DIR,
) -> Dict[str, Any]:
    """Normalize and derive alternative-data features with safe defaults."""
    normalized = _merge_default_payload(payload)

    if raw_store_dir is not None:
        target_dir = Path(raw_store_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = normalized.get("timestamp", datetime.now(timezone.utc).isoformat())
        raw_store_path = target_dir / f"alternative_{timestamp.replace(':', '_')}.json"
        with open(raw_store_path, "w", encoding="utf-8") as handle:
            json.dump(normalized, handle, indent=2, ensure_ascii=False)

    prev = previous_payload or {}
    prev = dict(prev)
    stablecoin_supply = float(normalized.get("stablecoin_supply", 0.0) or 0.0)
    previous_stablecoin_supply = float(prev.get("stablecoin_supply", stablecoin_supply) or 0.0)
    etf_flow = float(normalized.get("etf_flow", 0.0) or 0.0)
    previous_etf_flow = float(prev.get("etf_flow", etf_flow) or 0.0)
    funding_rate = float(normalized.get("funding_rate", 0.0) or 0.0)
    previous_funding_rate = float(prev.get("funding_rate", funding_rate) or 0.0)
    open_interest = float(normalized.get("open_interest", 0.0) or 0.0)
    previous_open_interest = float(prev.get("open_interest", open_interest) or 0.0)
    exchange_netflow = float(normalized.get("exchange_netflow", 0.0) or 0.0)
    previous_exchange_netflow = float(prev.get("exchange_netflow", exchange_netflow) or 0.0)

    normalized["stablecoin_momentum"] = max(
        -1.0,
        min(1.0, (stablecoin_supply - previous_stablecoin_supply) / max(abs(previous_stablecoin_supply), 1.0)),
    )
    normalized["etf_momentum"] = max(
        -1.0,
        min(1.0, (etf_flow - previous_etf_flow) / max(abs(previous_etf_flow), 1.0)),
    )
    normalized["funding_pressure"] = abs(funding_rate - previous_funding_rate)
    normalized["orderbook_imbalance"] = max(-1.0, min(1.0, (open_interest - previous_open_interest) / max(abs(previous_open_interest), 1.0)))
    normalized["liquidity_pressure"] = max(0.0, min(1.0, abs(exchange_netflow - previous_exchange_netflow) / 1_000_000.0))

    macro_pressure = 0.0
    if normalized.get("dxy", 0.0):
        macro_pressure += min(1.0, float(normalized.get("dxy", 0.0)) / 110.0)
    if normalized.get("vix", 0.0):
        macro_pressure += min(1.0, float(normalized.get("vix", 0.0)) / 40.0)
    if normalized.get("us10y", 0.0):
        macro_pressure += min(1.0, float(normalized.get("us10y", 0.0)) / 6.0)
    normalized["macro_pressure"] = macro_pressure / 3.0

    risk_on_score = 0.0
    if normalized.get("stablecoin_momentum", 0.0) > 0:
        risk_on_score += 0.35
    if normalized.get("etf_momentum", 0.0) > 0:
        risk_on_score += 0.35
    if normalized.get("funding_pressure", 0.0) > 0:
        risk_on_score += 0.3
    normalized["risk_on_score"] = risk_on_score

    return normalized
