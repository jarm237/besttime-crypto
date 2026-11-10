"""
btc_scraper/research/historical_sources/__init__.py
M2 Expansion: Historical Data Source Adapters, Contracts, and Point-in-Time Ingestion.
"""
from btc_scraper.research.historical_sources.contracts import (
    AggTradeRecord,
    CandleRecord,
    DatasetType,
    FilingRecord,
    FundingRecord,
    FuturesMetricRecord,
    MacroYieldRecord,
    PITClassification,
    SentimentRecord,
    SharedMetadataRecord,
    StablecoinRecord,
    normalize_timestamp_to_iso,
)

__all__ = [
    "AggTradeRecord",
    "CandleRecord",
    "DatasetType",
    "FilingRecord",
    "FundingRecord",
    "FuturesMetricRecord",
    "MacroYieldRecord",
    "PITClassification",
    "SentimentRecord",
    "SharedMetadataRecord",
    "StablecoinRecord",
    "normalize_timestamp_to_iso",
]
