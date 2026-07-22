"""Alternative-data collection layer for Phase 7.

This module provides a lightweight, dependency-light implementation that
produces a normalized payload for downstream feature building and world-state
integration.
"""

from __future__ import annotations

import json
import math
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
from btc_scraper.collectors.feature_source_registry import FEATURE_SOURCE_REGISTRY, feature_source_registry

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
        payload.setdefault("_field_statuses", {})

        try:
            binance_payload = BinanceCollector().collect(force=force)
            payload["_statuses"]["binance"] = {
                "status": binance_payload.get("status", "success"),
                "reason": binance_payload.get("reason"),
                "observed_at": binance_payload.get("timestamp"),
            }
            payload.update({
                "funding_rate": binance_payload.get("funding_rate"),
                "open_interest": binance_payload.get("open_interest"),
                "orderbook_imbalance": binance_payload.get("orderbook_imbalance"),
                "raw_open_interest": binance_payload.get("raw_open_interest"),
                "orderbook_imbalance_sample_count": binance_payload.get("orderbook_sample_count"),
            })
            payload["_field_statuses"].update(binance_payload.get("field_statuses", {}))
            if isinstance(binance_payload, dict) and binance_payload.get("error"):
                payload["_errors"]["binance"] = binance_payload.get("error")
        except Exception as e:
            payload.update({"funding_rate": None, "open_interest": None})
            payload["_errors"]["binance"] = repr(e)
            payload["_statuses"]["binance"] = {"status": "error", "reason": str(e)}

        try:
            defillama_payload = DefiLlamaCollector().collect(force=force)
            payload["_statuses"]["defillama"] = {
                "status": defillama_payload.get("status", "success"),
                "reason": defillama_payload.get("reason"),
                "observed_at": defillama_payload.get("timestamp"),
            }
            payload.update({
                "stablecoin_supply": defillama_payload.get("stablecoin_supply"),
                "stablecoin_supply_total": defillama_payload.get("stablecoin_supply_total"),
                "tvl": defillama_payload.get("tvl"),
                "chain_tvl": defillama_payload.get("chain_tvl"),
                "protocol_tvl": defillama_payload.get("protocol_tvl"),
                "raw_stablecoin_supply": defillama_payload.get("raw_stablecoin_supply"),
                "stablecoin_supply_sample_count": defillama_payload.get("stablecoin_sample_count"),
                "stablecoin_supply_total_sample_count": defillama_payload.get("stablecoin_sample_count"),
            })
            payload["_field_statuses"].update(defillama_payload.get("field_statuses", {}))
            if isinstance(defillama_payload, dict) and defillama_payload.get("error"):
                payload["_errors"]["defillama"] = defillama_payload.get("error")
        except Exception as e:
            payload.update({"stablecoin_supply": None, "stablecoin_supply_total": None, "tvl": None, "chain_tvl": None, "protocol_tvl": None})
            payload["_errors"]["defillama"] = repr(e)
            payload["_statuses"]["defillama"] = {"status": "error", "reason": str(e)}

        try:
            fred_payload = FredCollector().collect(force=force)
            payload["_statuses"]["fred"] = {"status": fred_payload.get("status", "success"), "reason": fred_payload.get("reason"), "observed_at": fred_payload.get("timestamp")}
            payload.update({"us10y": fred_payload.get("us10y"), "gold": fred_payload.get("gold")})
            if isinstance(fred_payload, dict) and fred_payload.get("error"):
                payload["_errors"]["fred"] = fred_payload.get("error")
        except Exception as e:
            payload.update({"us10y": None, "gold": None})
            payload["_errors"]["fred"] = repr(e)

        try:
            yahoo_payload = YahooCollector().collect(force=force)
            payload["_statuses"]["yahoo"] = {"status": yahoo_payload.get("status", "success"), "reason": yahoo_payload.get("reason"), "observed_at": yahoo_payload.get("timestamp")}
            payload.update({"dxy": yahoo_payload.get("dxy"), "vix": yahoo_payload.get("vix"), "gold": yahoo_payload.get("gold")})
            if yahoo_payload.get("status") == "error":
                payload["_errors"]["yahoo"] = yahoo_payload.get("reason") or "Yahoo collector reported an error"
            elif yahoo_payload.get("error"):
                payload["_errors"]["yahoo"] = yahoo_payload.get("error")
        except Exception as e:
            payload.update({"dxy": None, "vix": None, "gold": None})
            payload["_errors"]["yahoo"] = repr(e)

        try:
            altme_payload = AlternativeMeCollector().collect(force=force)
            status = altme_payload.get("status")
            payload["_statuses"]["alternative_me"] = {"status": status, "reason": altme_payload.get("reason"), "observed_at": altme_payload.get("timestamp")}
            if status in ("success", "stale") and isinstance(altme_payload.get("data"), dict):
                payload.update({
                    "fear_greed_raw": altme_payload["data"].get("fear_greed_raw"),
                    "fear_greed_score": altme_payload["data"].get("fear_greed_score"),
                    "fear_greed_regime": altme_payload["data"].get("fear_greed_regime"),
                    "fear_greed_observed_at": altme_payload["data"].get("fear_greed_observed_at"),
                })
            elif status == "error":
                payload["_errors"]["alternative_me"] = altme_payload.get("reason")
        except Exception as e:
            payload.update({"fear_greed_raw": None, "fear_greed_score": None, "fear_greed_regime": None})
            payload["_errors"]["alternative_me"] = repr(e)

        try:
            glassnode_payload = GlassnodeCollector().collect(force=force)
            status = glassnode_payload.get("status")
            payload["_statuses"]["glassnode"] = {"status": status, "reason": glassnode_payload.get("reason")}
            if status == "success" and isinstance(glassnode_payload.get("data"), dict):
                payload.update({"active_addresses": glassnode_payload["data"].get("active_addresses")})
            elif status == "error":
                payload["_errors"]["glassnode"] = glassnode_payload.get("reason")
        except Exception as e:
            payload.update({"active_addresses": None})
            payload["_errors"]["glassnode"] = repr(e)

        try:
            blockchain_payload = BlockchainCollector().collect(force=force)
            payload.update({"hashrate": blockchain_payload.get("hashrate")})
            if isinstance(blockchain_payload, dict) and blockchain_payload.get("error"):
                payload["_errors"]["blockchain"] = blockchain_payload.get("error")
        except Exception as e:
            payload.update({"hashrate": None})
            payload["_errors"]["blockchain"] = repr(e)

        try:
            blockchair_payload = BlockchairCollector().collect(force=force)
            payload.update({"exchange_netflow": blockchair_payload.get("exchange_netflow")})
            if isinstance(blockchair_payload, dict) and blockchair_payload.get("error"):
                payload["_errors"]["blockchair"] = blockchair_payload.get("error")
        except Exception as e:
            payload.update({"exchange_netflow": None})
            payload["_errors"]["blockchair"] = repr(e)

        try:
            whale_payload = WhaleAlertCollector().collect(force=force)
            status = whale_payload.get("status")
            payload["_statuses"]["whale_alert"] = {"status": status, "reason": whale_payload.get("reason")}
            if status == "success" and isinstance(whale_payload.get("data"), dict):
                payload.update({"whale_score": whale_payload["data"].get("whale_score")})
            elif status == "error":
                payload["_errors"]["whale_alert"] = whale_payload.get("reason")
        except Exception as e:
            payload.update({"whale_score": None})
            payload["_errors"]["whale_alert"] = repr(e)

        try:
            deribit_payload = DeribitCollector().collect(force=force)
            payload["_statuses"]["deribit"] = {
                "status": deribit_payload.get("status", "success"),
                "reason": deribit_payload.get("reason"),
                "observed_at": deribit_payload.get("timestamp"),
            }
            payload.update({
                "options_iv": deribit_payload.get("options_iv"),
                "iv_skew": deribit_payload.get("iv_skew"),
                "raw_options_iv": deribit_payload.get("raw_options_iv"),
                "options_iv_unit": deribit_payload.get("options_iv_unit"),
                "options_iv_sample_count": deribit_payload.get("options_iv_sample_count"),
                "iv_skew_sample_count": deribit_payload.get("iv_skew_sample_count"),
            })
            payload["_field_statuses"].update(deribit_payload.get("field_statuses", {}))
            if isinstance(deribit_payload, dict) and deribit_payload.get("error"):
                payload["_errors"]["deribit"] = deribit_payload.get("error")
        except Exception as e:
            payload.update({"options_iv": None, "iv_skew": None})
            payload["_errors"]["deribit"] = repr(e)

        try:
            etf_payload = ETFCollector().collect(force=force)
            etf_status = etf_payload.get("status", "success")
            payload["_statuses"]["etf"] = {
                "status": etf_status,
                "reason": etf_payload.get("reason"),
                "observed_at": etf_payload.get("timestamp"),
            }
            payload.update({
                "etf_flow": etf_payload.get("etf_flow"),
                "etf_flow_confidence": etf_payload.get("etf_flow_confidence", 0.0),
                "etf_flow_source": etf_payload.get("etf_flow_source", "none"),
                "etf_flow_scope": etf_payload.get("etf_flow_scope", "us_spot_btc_etf"),
            })
            if etf_status in {"error", "failed"}:
                payload["_errors"]["etf"] = etf_payload.get("reason") or etf_status
        except Exception as e:
            payload.update({"etf_flow": None})
            payload["_errors"]["etf"] = repr(e)
            payload["_statuses"]["etf"] = {"status": "error", "reason": str(e)}

        try:
            google_payload = GoogleTrendsCollector().collect(force=force)
            payload["_statuses"]["google_trends"] = {
                "status": google_payload.get("status", "success"),
                "reason": google_payload.get("reason"),
                "observed_at": google_payload.get("timestamp"),
            }
            payload.update({
                "sentiment_score": google_payload.get("sentiment_score"),
                "sentiment_score_sample_count": google_payload.get("sample_count"),
                "raw_sentiment_score": google_payload.get("raw_sentiment_score"),
            })
            payload["_field_statuses"].update(google_payload.get("field_statuses", {}))
            if isinstance(google_payload, dict) and google_payload.get("error"):
                payload["_errors"]["google_trends"] = google_payload.get("error")
        except Exception as e:
            payload.update({"sentiment_score": None})
            payload["_errors"]["google_trends"] = repr(e)

        try:
            reddit_payload = RedditCollector().collect(force=force)
            payload["_statuses"]["reddit"] = {
                "status": reddit_payload.get("status", "success"),
                "reason": reddit_payload.get("reason"),
                "observed_at": reddit_payload.get("timestamp"),
            }
            payload.update({
                "social_sentiment": reddit_payload.get("sentiment_score"),
                "social_sentiment_sample_count": reddit_payload.get("sentiment_volume"),
                "raw_social_sentiment": reddit_payload.get("sentiment_score"),
            })
            payload["_field_statuses"].update(reddit_payload.get("field_statuses", {}))
            if isinstance(reddit_payload, dict) and reddit_payload.get("error"):
                payload["_errors"]["reddit"] = reddit_payload.get("error")
        except Exception as e:
            payload.update({"social_sentiment": None})
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
        "exchange_netflow": None,
        "whale_score": None,
        "stablecoin_supply": None,
        "tvl": None,
        "funding_rate": None,
        "open_interest": None,
        "dxy": None,
        "vix": None,
        "us10y": None,
        "gold": None,
        "sentiment_score": None,
        "social_sentiment": None,
        "fear_greed_raw": None,
        "fear_greed_score": None,
        "fear_greed_regime": None,
        "active_addresses": None,
        "hashrate": None,
        "chain_tvl": None,
        "defi_liquidity_score": None,
        "orderbook_imbalance": None,
        "liquidity_pressure": None,
        "macro_pressure": None,
        "macro_risk_score": None,
        "funding_pressure": None,
        "open_interest_pressure": None,
        "large_tx_proxy_score": None,
        "stablecoin_supply_total": None,
        # === Derived Metrics ===
        "stablecoin_momentum": None,
        "etf_momentum": None,
        "etf_flow": None,
        "etf_flow_confidence": 0.0,
        "etf_flow_source": "none",
        "etf_flow_scope": "us_spot_btc_etf",
        "risk_on_score": None,
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


def safe_float(value):
    try:
        if value is None:
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except Exception:
        return None

def clamp(x, lo=-1.0, hi=1.0):
    if x is None:
        return None
    return max(lo, min(hi, x))

def normalize_pct(x, scale):
    if x is None:
        return None
    return clamp(x / scale)

def normalize_alternative_payload(
    payload: Dict[str, Any],
    previous_payload: Optional[Dict[str, Any]] = None,
    raw_store_dir: Optional[str | os.PathLike[str]] = DEFAULT_RAW_STORE_DIR,
) -> Dict[str, Any]:
    """Normalize a payload while preserving missing values as ``None``.

    This boundary is the missing-data contract: NaN is never persisted and a
    zero survives only when the feature permits zero and collector evidence is
    present. Model-only imputation belongs downstream.
    """
    normalized = _merge_default_payload(payload)
    _apply_missing_data_contract(normalized)

    prev = previous_payload or {}
    prev = dict(prev)
    
    # Safely extract floats
    stablecoin_supply = safe_float(normalized.get("stablecoin_supply"))
    previous_stablecoin_supply = safe_float(prev.get("stablecoin_supply"))
    etf_flow = safe_float(normalized.get("etf_flow"))
    previous_etf_flow = safe_float(prev.get("etf_flow"))
    funding_rate = safe_float(normalized.get("funding_rate"))
    previous_funding_rate = safe_float(prev.get("funding_rate"))
    open_interest = safe_float(normalized.get("open_interest"))
    previous_open_interest = safe_float(prev.get("open_interest"))
    exchange_netflow = safe_float(normalized.get("exchange_netflow"))
    previous_exchange_netflow = safe_float(prev.get("exchange_netflow"))

    dxy = safe_float(normalized.get("dxy"))
    vix = safe_float(normalized.get("vix"))
    us10y = safe_float(normalized.get("us10y"))
    fear_greed_raw = safe_float(normalized.get("fear_greed_raw"))

    normalized["stablecoin_momentum"] = None
    if stablecoin_supply is not None and previous_stablecoin_supply is not None:
        normalized["stablecoin_momentum"] = clamp((stablecoin_supply - previous_stablecoin_supply) / max(abs(previous_stablecoin_supply), 1.0))

    normalized["etf_momentum"] = None
    if etf_flow is not None and previous_etf_flow is not None:
        normalized["etf_momentum"] = clamp((etf_flow - previous_etf_flow) / max(abs(previous_etf_flow), 1.0))

    funding_pressure = clamp(funding_rate / 0.001) if funding_rate is not None else None
    normalized["funding_pressure"] = funding_pressure

    normalized["open_interest_pressure"] = None
    if open_interest is not None and previous_open_interest is not None:
        if previous_open_interest > 0:
            normalized["open_interest_pressure"] = clamp(
                (open_interest - previous_open_interest) / previous_open_interest
            )

    normalized["liquidity_pressure"] = None
    if exchange_netflow is not None and previous_exchange_netflow is not None:
        normalized["liquidity_pressure"] = max(0.0, min(1.0, abs(exchange_netflow - previous_exchange_netflow) / 1_000_000.0))

    macro_risk_score = None
    if dxy is not None and vix is not None and us10y is not None:
        dxy_pressure = clamp((dxy - 100) / 5, 0.0, 1.0)
        vix_pressure = clamp((vix - 15) / 20, 0.0, 1.0)
        yield_pressure = clamp((us10y - 4.0) / 2, 0.0, 1.0)
        macro_risk_score = 0.35 * dxy_pressure + 0.35 * vix_pressure + 0.30 * yield_pressure

    normalized["macro_risk_score"] = macro_risk_score
    normalized["macro_pressure"] = macro_risk_score

    fear_greed_score = clamp((fear_greed_raw - 50) / 50) if fear_greed_raw is not None else None
    normalized["fear_greed_score"] = fear_greed_score

    defi_liquidity_score = None # Need change 1d/7d
    normalized["defi_liquidity_score"] = defi_liquidity_score

    # calc risk_on_score
    components = []
    if macro_risk_score is not None:
        components.append(-macro_risk_score)
    if funding_pressure is not None:
        components.append(funding_pressure)
    if fear_greed_score is not None:
        components.append(fear_greed_score)
    if defi_liquidity_score is not None:
        components.append(defi_liquidity_score)
        
    risk_on_score = sum(components) / len(components) if components else None
    normalized["risk_on_score"] = risk_on_score

    # === Confidence Rule Update ===
    confidence_meta = normalized.get("confidence_metadata", {})
    def get_conf(field: str, val: Any) -> float:
        if val is None:
            return 0.0
        # If val == 0.0 and source is not OK could be added here,
        # but val is None already captures missing fields since we changed default
        return confidence_meta.get(field, 0.0)

    # Reassign confidence meta with new rules
    for k in list(confidence_meta.keys()):
        if k in normalized:
            confidence_meta[k] = get_conf(k, normalized[k])
    normalized["confidence_metadata"] = confidence_meta
    
    # Weight stablecoin_momentum by confidence
    stablecoin_confidence = confidence_meta.get("stablecoin_supply", 0.0)
    weighted_stablecoin_momentum = (normalized.get("stablecoin_momentum") or 0.0) * stablecoin_confidence
    
    # Weight etf_momentum by etf_flow_confidence (which varies by provider)
    etf_flow_conf = normalized.get("etf_flow_confidence", 0.0)
    weighted_etf_momentum = (normalized.get("etf_momentum") or 0.0) * max(etf_flow_conf, confidence_meta.get("etf_flow", 0.0))
    
    # Store effective weighted scores for causal engine
    normalized["effective_stablecoin_momentum"] = weighted_stablecoin_momentum
    normalized["effective_etf_momentum"] = weighted_etf_momentum
    normalized["effective_risk_on_score"] = normalized["risk_on_score"] if normalized["risk_on_score"] is not None else 0.0

    _sanitize_registered_values(normalized)
    normalized["feature_metadata"] = _build_feature_metadata(normalized)
    normalized["feature_source_registry"] = feature_source_registry()
    if raw_store_dir is not None:
        target_dir = Path(raw_store_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = normalized.get("timestamp", datetime.now(timezone.utc).isoformat())
        raw_store_path = target_dir / f"alternative_{timestamp.replace(':', '_')}.json"
        with open(raw_store_path, "w", encoding="utf-8") as handle:
            json.dump(normalized, handle, indent=2, ensure_ascii=False, allow_nan=False)
    return normalized


def _sanitize_registered_values(payload: Dict[str, Any]) -> None:
    """Convert non-finite values to missing before JSON persistence."""
    for field in FEATURE_SOURCE_REGISTRY:
        value = payload.get(field)
        if isinstance(value, float) and not math.isfinite(value):
            payload[field] = None


def _apply_missing_data_contract(payload: Dict[str, Any]) -> None:
    """Reject impossible zeros and unevidenced neutral values at the boundary."""
    field_statuses = payload.setdefault("_field_statuses", {})
    strictly_positive = {
        "open_interest": "zero_or_missing_open_interest",
        "stablecoin_supply": "zero_or_missing_stablecoin_supply",
        "stablecoin_supply_total": "zero_or_missing_stablecoin_supply_total",
        "options_iv": "zero_or_missing_dvol",
    }
    for field, reason in strictly_positive.items():
        value = safe_float(payload.get(field))
        if value is not None and value <= 0:
            payload[field] = None
            field_statuses[field] = {"status": "invalid", "reason": reason}

    # Exact zero is possible for these features, but it is only an observation
    # when the collector provides evidence that samples were actually parsed.
    evidence_required_for_zero = {
        "iv_skew",
        "sentiment_score",
        "social_sentiment",
        "orderbook_imbalance",
    }
    for field in evidence_required_for_zero:
        if safe_float(payload.get(field)) != 0.0:
            continue
        sample_count = safe_float(payload.get(field + "_sample_count"))
        if sample_count is None or sample_count <= 0:
            payload[field] = None
            field_statuses[field] = {
                "status": "missing",
                "reason": "collector_disabled_or_no_samples",
            }


def _build_feature_metadata(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Attach per-feature availability, provenance and freshness metadata."""
    statuses = payload.get("_statuses", {})
    field_statuses = payload.get("_field_statuses", {})
    metadata: Dict[str, Dict[str, Any]] = {}
    for field, spec in FEATURE_SOURCE_REGISTRY.items():
        value = payload.get(field)
        source_state = statuses.get(spec.source, {})
        source_status = source_state.get("status")
        field_state = field_statuses.get(field, {})
        field_status = field_state.get("status")
        # Collector timestamps are the source-observation time.  Aggregate
        # payload time is only a fallback for legacy collectors.
        observed_at = source_state.get("observed_at") or payload.get("timestamp")
        age_seconds = None
        if observed_at:
            try:
                observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=timezone.utc)
                age_seconds = max(0.0, (datetime.now(timezone.utc) - observed).total_seconds())
            except (TypeError, ValueError):
                observed_at = None
        unavailable_statuses = {"error", "skipped", "missing", "invalid", "fallback", "rate_limited"}
        available = (
            value is not None
            and source_status not in unavailable_statuses
            and field_status not in unavailable_statuses
        )
        if available:
            status = "available"
        elif field_status:
            status = field_status
        elif source_status == "error":
            status = "source_error"
        else:
            status = "missing"
        stale = bool(source_state.get("is_stale")) or source_status == "stale" or (
            age_seconds is not None and age_seconds > spec.max_age_seconds
        )
        metadata[field] = {
            "available": available,
            "status": "stale" if available and stale else status,
            "source": spec.source,
            "confidence": spec.confidence if available and not stale else (spec.confidence * 0.5 if available else 0.0),
            "observed_at": observed_at if available else None,
            "age_seconds": age_seconds,
            "is_stale": bool(stale),
            "reason": field_state.get("reason") or (source_state.get("reason") if not available else None),
            "raw_value": payload.get("raw_" + field),
            "sample_count": payload.get(field + "_sample_count"),
        }
    return metadata


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
