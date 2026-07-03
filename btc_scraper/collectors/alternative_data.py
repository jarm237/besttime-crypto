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
from btc_scraper.collectors.alternative_me_collector import AlternativeMeCollector

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
        payload.setdefault("_errors", {})
        payload.setdefault("_statuses", {})

        try:
            binance_payload = BinanceCollector().collect(force=force)
            payload["_statuses"]["binance"] = {
                "status": binance_payload.get("status", "success"),
                "reason": binance_payload.get("reason"),
            }
            payload.update({"funding_rate": binance_payload.get("funding_rate", 0.0), "open_interest": binance_payload.get("open_interest", 0.0)})
            if isinstance(binance_payload, dict) and binance_payload.get("error"):
                payload["_errors"]["binance"] = binance_payload.get("error")
        except Exception as e:
            payload.update({"funding_rate": 0.0, "open_interest": 0.0})
            payload["_errors"]["binance"] = repr(e)
            payload["_statuses"]["binance"] = {"status": "error", "reason": str(e)}

        try:
            defillama_payload = DefiLlamaCollector().collect(force=force)
            payload["_statuses"]["defillama"] = {
                "status": defillama_payload.get("status", "success"),
                "reason": defillama_payload.get("reason"),
            }
            payload.update({
                "stablecoin_supply": defillama_payload.get("stablecoin_supply", 0.0),
                "stablecoin_supply_total": defillama_payload.get("stablecoin_supply_total", 0.0),
                "tvl": defillama_payload.get("tvl", 0.0),
                "chain_tvl": defillama_payload.get("chain_tvl", 0.0),
                "protocol_tvl": defillama_payload.get("protocol_tvl", 0.0),
            })
            if isinstance(defillama_payload, dict) and defillama_payload.get("error"):
                payload["_errors"]["defillama"] = defillama_payload.get("error")
        except Exception as e:
            payload.update({"stablecoin_supply": 0.0, "stablecoin_supply_total": 0.0, "tvl": 0.0, "chain_tvl": 0.0})
            payload["_errors"]["defillama"] = repr(e)
            payload["_statuses"]["defillama"] = {"status": "error", "reason": str(e)}

        try:
            fred_payload = FredCollector().collect(force=force)
            payload.update({"us10y": fred_payload.get("us10y", 0.0), "gold": fred_payload.get("gold", 0.0)})
            if isinstance(fred_payload, dict) and fred_payload.get("error"):
                payload["_errors"]["fred"] = fred_payload.get("error")
        except Exception as e:
            payload.update({"us10y": 0.0, "gold": 0.0})
            payload["_errors"]["fred"] = repr(e)

        try:
            yahoo_payload = YahooCollector().collect(force=force)
            payload.update({"dxy": yahoo_payload.get("dxy", 0.0), "vix": yahoo_payload.get("vix", 0.0), "gold": yahoo_payload.get("gold", 0.0)})
            if isinstance(yahoo_payload, dict) and yahoo_payload.get("error"):
                payload["_errors"]["yahoo"] = yahoo_payload.get("error")
        except Exception as e:
            payload.update({"dxy": 0.0, "vix": 0.0, "gold": 0.0})
            payload["_errors"]["yahoo"] = repr(e)

        try:
            altme_payload = AlternativeMeCollector().collect(force=force)
            status = altme_payload.get("status")
            payload["_statuses"]["alternative_me"] = {"status": status, "reason": altme_payload.get("reason")}
            if status == "success" and isinstance(altme_payload.get("data"), dict):
                payload.update({
                    "fear_greed_raw": altme_payload["data"].get("fear_greed_raw", 50.0),
                    "fear_greed_score": altme_payload["data"].get("fear_greed_score", 0.5),
                    "fear_greed_regime": altme_payload["data"].get("fear_greed_regime"),
                })
            elif status == "error":
                payload["_errors"]["alternative_me"] = altme_payload.get("reason")
        except Exception as e:
            payload.update({"fear_greed_raw": 50.0, "fear_greed_score": 0.5, "fear_greed_regime": None})
            payload["_errors"]["alternative_me"] = repr(e)

        try:
            glassnode_payload = GlassnodeCollector().collect(force=force)
            status = glassnode_payload.get("status")
            payload["_statuses"]["glassnode"] = {"status": status, "reason": glassnode_payload.get("reason")}
            if status == "success" and isinstance(glassnode_payload.get("data"), dict):
                payload.update({"active_addresses": glassnode_payload["data"].get("active_addresses", 0.0)})
            elif status == "error":
                payload["_errors"]["glassnode"] = glassnode_payload.get("reason")
        except Exception as e:
            payload.update({"active_addresses": 0.0})
            payload["_errors"]["glassnode"] = repr(e)

        try:
            blockchain_payload = BlockchainCollector().collect(force=force)
            payload.update({"hashrate": blockchain_payload.get("hashrate", 0.0)})
            if isinstance(blockchain_payload, dict) and blockchain_payload.get("error"):
                payload["_errors"]["blockchain"] = blockchain_payload.get("error")
        except Exception as e:
            payload.update({"hashrate": 0.0})
            payload["_errors"]["blockchain"] = repr(e)

        try:
            blockchair_payload = BlockchairCollector().collect(force=force)
            payload.update({"exchange_netflow": blockchair_payload.get("exchange_netflow", 0.0)})
            if isinstance(blockchair_payload, dict) and blockchair_payload.get("error"):
                payload["_errors"]["blockchair"] = blockchair_payload.get("error")
        except Exception as e:
            payload.update({"exchange_netflow": 0.0})
            payload["_errors"]["blockchair"] = repr(e)

        try:
            whale_payload = WhaleAlertCollector().collect(force=force)
            status = whale_payload.get("status")
            payload["_statuses"]["whale_alert"] = {"status": status, "reason": whale_payload.get("reason")}
            if status == "success" and isinstance(whale_payload.get("data"), dict):
                payload.update({"whale_score": whale_payload["data"].get("whale_score", 0.0)})
            elif status == "error":
                payload["_errors"]["whale_alert"] = whale_payload.get("reason")
        except Exception as e:
            payload.update({"whale_score": 0.0})
            payload["_errors"]["whale_alert"] = repr(e)

        try:
            deribit_payload = DeribitCollector().collect(force=force)
            payload.update({"options_iv": deribit_payload.get("options_iv", 0.0), "iv_skew": deribit_payload.get("iv_skew", 0.0)})
            if isinstance(deribit_payload, dict) and deribit_payload.get("error"):
                payload["_errors"]["deribit"] = deribit_payload.get("error")
        except Exception as e:
            payload.update({"options_iv": 0.0, "iv_skew": 0.0})
            payload["_errors"]["deribit"] = repr(e)

        try:
            etf_payload = ETFCollector().collect(force=force)
            payload.update({"etf_flow": etf_payload.get("etf_flow", 0.0)})
            if isinstance(etf_payload, dict) and etf_payload.get("error"):
                payload["_errors"]["etf"] = etf_payload.get("error")
        except Exception as e:
            payload.update({"etf_flow": 0.0})
            payload["_errors"]["etf"] = repr(e)

        try:
            google_payload = GoogleTrendsCollector().collect(force=force)
            payload.update({"sentiment_score": google_payload.get("sentiment_score", 0.0)})
            if isinstance(google_payload, dict) and google_payload.get("error"):
                payload["_errors"]["google_trends"] = google_payload.get("error")
        except Exception as e:
            payload.update({"sentiment_score": 0.0})
            payload["_errors"]["google_trends"] = repr(e)

        try:
            reddit_payload = RedditCollector().collect(force=force)
            payload.update({"social_sentiment": reddit_payload.get("sentiment_score", 0.0)})
            if isinstance(reddit_payload, dict) and reddit_payload.get("error"):
                payload["_errors"]["reddit"] = reddit_payload.get("error")
        except Exception as e:
            payload.update({"social_sentiment": 0.0})
            payload["_errors"]["reddit"] = repr(e)

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
    validate_startup: bool = True,
) -> Dict[str, Any]:
    """Collect and persist alternative-data payload."""
    if validate_startup:
        validate_collectors_on_startup()
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
        # === Raw Alternative Data ===
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
        "sentiment_score": 0.0,
        "social_sentiment": 0.0,
        "fear_greed_raw": 50.0,
        "fear_greed_score": 0.5,
        "fear_greed_regime": None,
        "active_addresses": 0.0,
        "hashrate": 0.0,
        "chain_tvl": 0.0,
        "defi_liquidity_score": 0.0,
        "orderbook_imbalance": 0.0,
        "liquidity_pressure": 0.0,
        "macro_pressure": 0.0,
        "macro_risk_score": 0.0,
        "funding_pressure": 0.0,
        "open_interest_pressure": 0.0,
        "large_tx_proxy_score": 0.0,
        "stablecoin_supply_total": 0.0,
        # === Derived Metrics ===
        "stablecoin_momentum": 0.0,
        "etf_momentum": 0.0,
        "etf_flow": 0.0,
        "etf_flow_confidence": 0.0,
        "etf_flow_source": "none",
        "etf_flow_scope": "us_spot_btc_etf",
        "risk_on_score": 0.0,
        # === Confidence Scores (Sprint 9.6) ===
        "confidence_metadata": {
            "dxy": 0.95,  # Official source, high confidence
            "vix": 0.95,
            "us10y": 0.90,
            "gold": 0.90,
            "funding_rate": 0.90,
            "open_interest": 0.90,
            "exchange_netflow": 0.75,
            "stablecoin_supply": 0.70,  # DefiLlama, may have endpoint issues
            "tvl": 0.65,
            "hashrate": 0.85,
            "active_addresses": 0.70,  # Glassnode, limited free tier
            "etf_flow": 0.0,  # Depends on provider (see etf_flow_confidence)
            "fear_greed_raw": 0.60,  # Alternative.me, reasonable reliability
            "sentiment_score": 0.35,  # Google Trends, unofficial, rate-limited
            "social_sentiment": 0.40,  # Reddit OAuth, depends on volume
            "whale_score": 0.50,  # WhaleAlert, API key dependent
        },
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
    
    # === Sprint 9.6: Apply confidence weighting ===
    confidence_meta = normalized.get("confidence_metadata", {})
    
    # Weight stablecoin_momentum by confidence
    stablecoin_confidence = confidence_meta.get("stablecoin_supply", 0.70)
    weighted_stablecoin_momentum = normalized.get("stablecoin_momentum", 0.0) * stablecoin_confidence
    
    # Weight etf_momentum by etf_flow_confidence (which varies by provider)
    etf_flow_conf = normalized.get("etf_flow_confidence", 0.0)
    weighted_etf_momentum = normalized.get("etf_momentum", 0.0) * max(etf_flow_conf, confidence_meta.get("etf_flow", 0.0))
    
    # Update risk_on_score with confidence-weighted components
    risk_on_score = 0.0
    if weighted_stablecoin_momentum > 0:
        risk_on_score += 0.35 * (stablecoin_confidence)
    if weighted_etf_momentum > 0:
        risk_on_score += 0.35 * max(etf_flow_conf, confidence_meta.get("etf_flow", 0.0))
    
    funding_pressure_conf = confidence_meta.get("funding_rate", 0.90)
    if normalized.get("funding_pressure", 0.0) > 0:
        risk_on_score += 0.3 * funding_pressure_conf
    
    normalized["risk_on_score"] = max(0.0, min(1.0, risk_on_score))
    
    # Store effective weighted scores for causal engine
    normalized["effective_stablecoin_momentum"] = weighted_stablecoin_momentum
    normalized["effective_etf_momentum"] = weighted_etf_momentum
    normalized["effective_risk_on_score"] = normalized["risk_on_score"]

    return normalized


def validate_collectors_on_startup() -> None:
    """
    Print startup validation for disabled collectors and their requirements.
    
    This function helps identify which collectors are disabled and why,
    enabling operators to make informed decisions about data quality and
    coverage.
    """
    import logging
    
    logger = logging.getLogger(__name__)
    disabled_collectors = []
    
    # Check ETF collector
    etf_enabled = os.getenv("ENABLE_ETF", "false").strip().lower() == "true"
    if not etf_enabled:
        disabled_collectors.append({
            "name": "ETFCollector",
            "reason": "Placeholder endpoint (https://api.example.com/etf/flow) requires implementation",
            "requires": "Farside API / Parse.bot implementation + ENABLE_ETF=true",
            "impact": "ETF flow features unavailable (etf_flow, etf_momentum)",
        })
    
    # Check Reddit collector
    reddit_enabled = os.getenv("ENABLE_REDDIT", "false").strip().lower() == "true"
    if not reddit_enabled:
        disabled_collectors.append({
            "name": "RedditCollector",
            "reason": "Placeholder endpoint (https://api.example.com/reddit/sentiment) requires implementation",
            "requires": "Reddit OAuth implementation + REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT + ENABLE_REDDIT=true",
            "impact": "Social sentiment features unavailable (social_sentiment)",
        })
    
    if disabled_collectors:
        logger.warning(
            "\n" + "=" * 80 + "\n"
            "[Sprint 9.1] DISABLED COLLECTORS ON STARTUP\n"
            + "=" * 80
        )
        for collector in disabled_collectors:
            logger.warning(
                f"\n  ❌ {collector['name']}"
                f"\n     Reason: {collector['reason']}"
                f"\n     To enable: {collector['requires']}"
                f"\n     Impact: {collector['impact']}"
            )
        logger.warning(
            "\n" + "=" * 80
            + "\nFor more details, see Phase7_Alternative_Data_Implementation_Plan_UPDATED.md (Sprint 9.2-9.4)"
            + "\n" + "=" * 80 + "\n"
        )
