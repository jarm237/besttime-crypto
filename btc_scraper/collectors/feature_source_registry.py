"""Canonical provenance and validation policy for alternative-data features.

The registry is deliberately data-only so collectors, quality checks, and
downstream consumers use the same definition of requiredness and freshness.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class FeatureSourceSpec:
    source: str
    required: bool = False
    confidence: float = 0.5
    max_age_seconds: int = 900
    minimum: float | None = None
    maximum: float | None = None
    missing_policy: str = "preserve"  # preserve; never substitute a neutral value


def _spec(source: str, **kwargs: Any) -> FeatureSourceSpec:
    return FeatureSourceSpec(source=source, **kwargs)


FEATURE_SOURCE_REGISTRY: dict[str, FeatureSourceSpec] = {
    "funding_rate": _spec("binance", required=True, confidence=.90, minimum=-.1, maximum=.1),
    "open_interest": _spec("binance", required=True, confidence=.90, minimum=1e-12),
    "orderbook_imbalance": _spec("binance", confidence=.80, minimum=-1, maximum=1),
    "stablecoin_supply": _spec("defillama", required=True, confidence=.70, minimum=1e-12, max_age_seconds=3600),
    "stablecoin_supply_total": _spec("defillama", confidence=.70, minimum=1e-12, max_age_seconds=3600),
    "tvl": _spec("defillama", required=True, confidence=.65, minimum=0, max_age_seconds=3600),
    "chain_tvl": _spec("defillama", confidence=.65, minimum=0, max_age_seconds=3600),
    "dxy": _spec("yahoo", required=True, confidence=.95, minimum=60, maximum=160, max_age_seconds=3600),
    "vix": _spec("yahoo", required=True, confidence=.95, minimum=5, maximum=200, max_age_seconds=3600),
    "us10y": _spec("fred", required=True, confidence=.90, minimum=0, maximum=20, max_age_seconds=86400),
    "gold": _spec("yahoo", required=True, confidence=.90, minimum=500, maximum=5000, max_age_seconds=3600),
    "fear_greed_raw": _spec("alternative_me", required=True, confidence=.60, minimum=0, maximum=100, max_age_seconds=86400),
    "fear_greed_score": _spec("alternative_me", required=True, confidence=.60, minimum=-1, maximum=1, max_age_seconds=86400),
    "exchange_netflow": _spec("blockchair", confidence=.75),
    "whale_score": _spec("whale_alert", confidence=.50, minimum=0, maximum=1),
    "active_addresses": _spec("glassnode", confidence=.70, minimum=0, max_age_seconds=86400),
    "hashrate": _spec("blockchain", confidence=.85, minimum=0, max_age_seconds=86400),
    "options_iv": _spec("deribit", confidence=.80, minimum=0, maximum=5),
    "iv_skew": _spec("deribit", confidence=.80, minimum=-5, maximum=5),
    "etf_flow": _spec("etf", confidence=.50, max_age_seconds=86400),
    "sentiment_score": _spec("google_trends", confidence=.35, minimum=-1, maximum=1, max_age_seconds=86400),
    "social_sentiment": _spec("reddit", confidence=.40, minimum=-1, maximum=1, max_age_seconds=86400),
}


def feature_source_registry() -> dict[str, dict[str, Any]]:
    """Return a JSON-safe copy for dashboards and the feature store."""
    return {name: asdict(spec) for name, spec in FEATURE_SOURCE_REGISTRY.items()}
