"""
btc_scraper/research/historical_sources/contracts.py
Milestone M2 Expansion: Shared Historical Metadata Contracts & Point-in-Time (PIT) Specifications.

Provides:
1. SharedMetadataRecord: Canonical provenance and PIT envelope for all historical dataset types.
2. PITClassification: Categorization of temporal availability trustworthiness:
   - VERIFIED_PIT: Point-in-time publication time proven by source release timestamps.
   - CONSERVATIVE_ESTIMATE: As-of time bounded by end-of-interval or official release schedule.
   - UNVERIFIED: Raw observation period without release provenance (BLOCKED from strict PIT joins).
   - NOT_APPLICABLE: Non-temporal or static reference data.
3. Normalized Record Models:
   - CandleRecord (OHLCV + quote vol + trade counts + taker buy volume)
   - AggTradeRecord (Tick-level aggregated trades)
   - FundingRecord (Perpetual funding rate settlement)
   - FuturesMetricRecord (Open Interest, Long/Short ratios, Taker volume ratios)
   - MacroYieldRecord (U.S. Treasury daily yield curve vintages)
   - SentimentRecord (Daily Fear & Greed index)
   - StablecoinRecord (Daily aggregated stablecoin circulation)
   - FilingRecord (SEC EDGAR regulatory acceptance)
4. Temporal Validation & Integrity Invariants:
   - Zero lookahead: Available-at must be >= Event-time.
   - Rejection of unclosed or forming bars in historical features.
   - Microsecond / millisecond timestamp auto-detection and normalization.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


class PITClassification(str, enum.Enum):
    VERIFIED_PIT = "VERIFIED_PIT"
    CONSERVATIVE_ESTIMATE = "CONSERVATIVE_ESTIMATE"
    UNVERIFIED = "UNVERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class DatasetType(str, enum.Enum):
    SPOT_CANDLE = "SPOT_CANDLE"
    FUTURES_CANDLE = "FUTURES_CANDLE"
    MARK_PRICE_CANDLE = "MARK_PRICE_CANDLE"
    INDEX_PRICE_CANDLE = "INDEX_PRICE_CANDLE"
    AGG_TRADE = "AGG_TRADE"
    FUNDING_RATE = "FUNDING_RATE"
    FUTURES_METRIC = "FUTURES_METRIC"
    MACRO_YIELD = "MACRO_YIELD"
    MARKET_SENTIMENT = "MARKET_SENTIMENT"
    ONCHAIN_STABLECOIN = "ONCHAIN_STABLECOIN"
    REGULATORY_FILING = "REGULATORY_FILING"


@dataclass(frozen=True)
class SharedMetadataRecord:
    """
    Common provenance envelope attached to all normalized records.
    Ensures strict traceability and point-in-time compliance without forcing
    different domains (candles vs trades vs macro) into an unnatural single schema.
    """
    source_id: str                      # e.g. "binance_vision", "okx_rest", "us_treasury", "alternative_me"
    dataset_type: str                   # From DatasetType
    record_id: str                      # Unique row or event ID
    instrument_id: str                  # e.g. "BTCUSDT", "ETHUSDT", "DGS10"
    event_time: Optional[str]           # ISO-8601 UTC event occurrence (e.g. trade execution, candle start)
    published_at: Optional[str]         # ISO-8601 UTC when source released the data
    available_at: Optional[str]         # ISO-8601 UTC when strategy could legally observe the data
    ingested_at: str                    # ISO-8601 UTC when system ingested the raw record
    revised_at: Optional[str] = None    # ISO-8601 UTC when revised (if vintage data)
    source_version: str = "1.0.0"       # Version of adapter / parser
    raw_payload_sha256: str = ""        # Hash of original raw payload
    quality_flags: Tuple[str, ...] = () # e.g. ("OHLC_VALIDATED", "MICROSECOND_NORMALIZED")
    missingness_status: str = "PRESENT" # "PRESENT", "SOURCE_GAP", "MISSING_FIELD"
    availability_quality: str = PITClassification.CONSERVATIVE_ESTIMATE.value

    def __post_init__(self) -> None:
        # Enforce temporal invariant: available_at cannot precede event_time
        if self.available_at and self.event_time:
            avail_dt = _parse_iso(self.available_at)
            event_dt = _parse_iso(self.event_time)
            if avail_dt < event_dt:
                raise ValueError(
                    f"Temporal invariant violation: available_at ({self.available_at}) precedes event_time ({self.event_time})"
                )

        # Enforce PIT classification rule
        if self.availability_quality == PITClassification.VERIFIED_PIT.value and not self.available_at:
            raise ValueError("VERIFIED_PIT record must have an authoritative non-null available_at timestamp.")

    def is_joinable_as_of(self, query_time_utc: str) -> bool:
        """Confirms whether this record is legally observable as-of query_time_utc."""
        if self.availability_quality == PITClassification.UNVERIFIED.value:
            return False
        if not self.available_at:
            return False
        return _parse_iso(self.available_at) <= _parse_iso(query_time_utc)


def _parse_iso(ts_str: str) -> datetime:
    clean = ts_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(clean)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def normalize_timestamp_to_iso(ts_val: Any) -> str:
    """
    Auto-detects integer/float timestamps (seconds, milliseconds, microseconds, nanoseconds)
    or ISO-8601 strings and returns canonical ISO-8601 UTC string (YYYY-MM-DDTHH:MM:SSZ).
    """
    if isinstance(ts_val, str):
        ts_val = ts_val.strip()
        if ts_val.isdigit():
            num = int(ts_val)
            return _int_to_iso(num)
        # Try direct ISO parsing
        clean = ts_val.replace(" ", "T")
        if not clean.endswith("Z") and "+" not in clean and "-" not in clean[-6:]:
            clean += "Z"
        dt = _parse_iso(clean)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    elif isinstance(ts_val, (int, float)):
        return _int_to_iso(int(ts_val))
    else:
        raise ValueError(f"Unsupported timestamp value: {ts_val!r}")


def _int_to_iso(num: int) -> str:
    # Nanoseconds: > 10^17
    if num > 10**17:
        seconds = num / 1_000_000_000
    # Microseconds: 10^14 <= num <= 10^17 (e.g. Binance Spot 2025: 1738368000000000)
    elif num > 10**14:
        seconds = num / 1_000_000
    # Milliseconds: 10^11 <= num <= 10^14 (e.g. Binance 2023: 1685577600000)
    elif num > 10**11:
        seconds = num / 1_000
    # Seconds: <= 10^11
    else:
        seconds = float(num)
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Specialized Record Models ─────────────────────────────────────────────────

@dataclass(frozen=True)
class CandleRecord:
    open_time: str
    close_time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trades_count: int
    taker_buy_volume: float
    taker_buy_quote_volume: float
    is_closed: bool
    metadata: SharedMetadataRecord

    def __post_init__(self) -> None:
        if self.high < max(self.open, self.close, self.low):
            raise ValueError(f"Candle high ({self.high}) is lower than max(open, close, low)")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError(f"Candle low ({self.low}) is higher than min(open, close, high)")
        if self.volume < 0:
            raise ValueError(f"Candle volume ({self.volume}) cannot be negative")


@dataclass(frozen=True)
class AggTradeRecord:
    agg_trade_id: int
    timestamp: str
    price: float
    quantity: float
    first_trade_id: int
    last_trade_id: int
    is_buyer_maker: bool
    is_best_match: bool
    metadata: SharedMetadataRecord


@dataclass(frozen=True)
class FundingRecord:
    timestamp: str
    funding_interval_hours: int
    funding_rate: float
    realized_rate: float
    metadata: SharedMetadataRecord


@dataclass(frozen=True)
class FuturesMetricRecord:
    timestamp: str
    symbol: str
    sum_open_interest: float
    sum_open_interest_usd: float
    toptrader_ls_ratio: float
    long_short_ratio: float
    taker_ls_volume_ratio: float
    metadata: SharedMetadataRecord
    raw_create_time: str = ""
    period_start_utc: str = ""
    period_end_utc: str = ""
    measurement_time_utc: str = ""
    available_at_utc: str = ""
    timestamp_convention: str = "CONSERVATIVE_PERIOD_END"
    source_partition_id: str = ""
    source_record_id: str = ""

    def __post_init__(self) -> None:
        if not self.period_start_utc:
            object.__setattr__(self, "period_start_utc", self.timestamp)
        if not self.period_end_utc:
            dt_start = _parse_iso(self.period_start_utc)
            dt_end = dt_start.timestamp() + 300
            object.__setattr__(self, "period_end_utc", datetime.fromtimestamp(dt_end, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        if not self.available_at_utc:
            object.__setattr__(self, "available_at_utc", self.period_end_utc)
        if not self.raw_create_time:
            object.__setattr__(self, "raw_create_time", self.timestamp)
        if not self.source_record_id:
            object.__setattr__(self, "source_record_id", f"{self.symbol}_{self.raw_create_time}")


@dataclass(frozen=True)
class MacroYieldRecord:
    date: str                           # YYYY-MM-DD
    yield_1m: Optional[float]
    yield_3m: Optional[float]
    yield_6m: Optional[float]
    yield_1y: Optional[float]
    yield_2y: Optional[float]
    yield_5y: Optional[float]
    yield_10y: Optional[float]
    yield_30y: Optional[float]
    metadata: SharedMetadataRecord
    market_quotation_time_utc: Optional[str] = None
    actual_publication_time_utc: Optional[str] = None
    conservative_available_at_utc: str = ""
    timezone_convention: str = "America/New_York (EST/EDT aware)"


@dataclass(frozen=True)
class SentimentRecord:
    timestamp: str
    value: int
    classification: str
    metadata: SharedMetadataRecord
    api_record_timestamp: str = ""
    conservative_available_at_utc: str = ""



@dataclass(frozen=True)
class StablecoinRecord:
    date: str                           # YYYY-MM-DD
    total_circulating_usd: float
    pegged_usd_volume: float
    metadata: SharedMetadataRecord


@dataclass(frozen=True)
class FilingRecord:
    accession_number: str
    filing_date: str
    report_date: str
    acceptance_datetime: str
    form: str
    entity_name: str
    metadata: SharedMetadataRecord
