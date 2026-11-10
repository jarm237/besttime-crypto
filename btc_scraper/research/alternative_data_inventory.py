"""
btc_scraper/research/alternative_data_inventory.py
Phase M2-F: Alternative & Derivatives Data Provenance & Eligibility Registry.

Formally inventories and audits alternative data sources:
1. Funding Rates: Genuine Binance Futures 8h observations (Eligible for cost model).
2. IV Skew: Reconstructed synthetic proxy with Gaussian noise (REJECTED for production ML training).
3. Premium Index: Genuine Binance 15m premium index (Candidate).
4. Feature Store Rejections: 15 features rejected due to PSI drift and collinearity.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional


@dataclass(frozen=True)
class AlternativeSourceMetadata:
    source_id: str
    nature: str             # "GENUINE_OBSERVATION", "RECONSTRUCTED_PROXY", "DERIVED_INDICATOR"
    provider: str
    file_path: str
    symbol_coverage: tuple[str, ...]
    time_range: tuple[str, str]
    cadence: str
    eligibility_status: str  # "ELIGIBLE_FOR_COST_MODEL", "REJECTED_FOR_PRODUCTION_TRAINING", "CANDIDATE"
    audit_notes: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


ALTERNATIVE_DATA_REGISTRY: Dict[str, AlternativeSourceMetadata] = {
    "binance_funding_rates": AlternativeSourceMetadata(
        source_id="binance_funding_rates",
        nature="GENUINE_OBSERVATION",
        provider="Binance Futures API",
        file_path="data/historical_funding_rates.parquet",
        symbol_coverage=("BTC", "ETH", "BNB"),
        time_range=("2023-01-01T00:00:00Z", "2024-12-31T16:00:00Z"),
        cadence="8h",
        eligibility_status="ELIGIBLE_FOR_COST_MODEL",
        audit_notes="Actual historical Binance 8-hour settled funding rates. Validated for friction cost modeling.",
    ),
    "deribit_iv_skew_proxy": AlternativeSourceMetadata(
        source_id="deribit_iv_skew_proxy",
        nature="RECONSTRUCTED_PROXY",
        provider="Internal Simulation (scripts/reconstruct_iv_skew_history.py)",
        file_path="data/historical_iv_skew.parquet",
        symbol_coverage=("BTC", "ETH", "BNB"),
        time_range=("2023-01-01T00:00:00Z", "2024-12-31T23:45:00Z"),
        cadence="15m (sampled hourly)",
        eligibility_status="REJECTED_FOR_PRODUCTION_TRAINING",
        audit_notes=(
            "CRITICAL: Reconstructed synthetic series generated via Gaussian noise and return/volatility "
            "coefficients. BNB has no Deribit options market. MUST NOT be labeled genuine Deribit IV Skew "
            "or promoted to production ML training."
        ),
    ),
    "binance_premium_index": AlternativeSourceMetadata(
        source_id="binance_premium_index",
        nature="GENUINE_OBSERVATION",
        provider="Binance Futures Premium Index Klines",
        file_path="data/raw/binance_premium_index/",
        symbol_coverage=("BTC", "ETH", "BNB"),
        time_range=("2023-01-01T00:00:00Z", "2025-06-30T23:45:00Z"),
        cadence="15m",
        eligibility_status="CANDIDATE",
        audit_notes="Genuine exchange premium index klines with open/close timestamps.",
    ),
}


REJECTED_FEATURE_STORE_INDICATORS = {
    "ema_distance_pct": "High correlation with trend features",
    "fear_greed": "High Population Stability Index (PSI) drift between train and test",
    "fracdiff_d_0_00": "High PSI drift",
    "fracdiff_d_0_20": "High collinearity",
    "fracdiff_d_0_40": "High collinearity",
    "fracdiff_d_0_60": "High collinearity",
    "fracdiff_d_0_80": "High PSI drift",
    "fracdiff_price": "High PSI drift",
}


def get_alternative_source_status(source_id: str) -> Optional[AlternativeSourceMetadata]:
    """Returns governance metadata and eligibility for an alternative data source."""
    return ALTERNATIVE_DATA_REGISTRY.get(source_id)


def is_source_eligible_for_training(source_id: str) -> bool:
    """Strict gate preventing unverified or synthetic alternative data from entering ML models."""
    src = ALTERNATIVE_DATA_REGISTRY.get(source_id)
    if not src:
        return False
    return src.eligibility_status == "ELIGIBLE_FOR_PRODUCTION_TRAINING"
