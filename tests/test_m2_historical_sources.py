"""
tests/test_m2_historical_sources.py
Milestone M2 Expansion: Comprehensive Test Suite for Historical Data Sources,
PIT Contracts, Microsecond Normalization, Checksum Integrity, and As-Of Joining.
"""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import pytest

from btc_scraper.research.historical_sources.contracts import (
    CandleRecord,
    DatasetType,
    MacroYieldRecord,
    PITClassification,
    SentimentRecord,
    SharedMetadataRecord,
    normalize_timestamp_to_iso,
)
from btc_scraper.research.historical_sources.binance_archive import (
    parse_klines_zip,
)
from btc_scraper.research.historical_sources.treasury_macro import (
    fetch_and_parse_treasury_yields,
)


# ── 1. Timestamp Normalization & Precision Auto-Detection ─────────────────────

def test_1_timestamp_normalization_auto_detect():
    """Validates accurate conversion across seconds, milliseconds, microseconds, and nanoseconds."""
    # Seconds (10 digits)
    assert normalize_timestamp_to_iso(1685577600) == "2023-06-01T00:00:00Z"

    # Milliseconds (13 digits - Binance standard 2017-2024)
    assert normalize_timestamp_to_iso(1685577600000) == "2023-06-01T00:00:00Z"

    # Microseconds (16 digits - Binance Spot standard 2025+)
    # 1738368000000000 = 2025-02-01 00:00:00 UTC
    assert normalize_timestamp_to_iso(1738368000000000) == "2025-02-01T00:00:00Z"

    # Nanoseconds (19 digits)
    assert normalize_timestamp_to_iso(1738368000000000000) == "2025-02-01T00:00:00Z"

    # String numeric
    assert normalize_timestamp_to_iso("1738368000000000") == "2025-02-01T00:00:00Z"

    # String ISO with space
    assert normalize_timestamp_to_iso("2023-06-01 00:00:00") == "2023-06-01T00:00:00Z"


# ── 2. Shared Metadata Temporal Invariants ────────────────────────────────────

def test_2_shared_metadata_temporal_invariants():
    """Available-at timestamp cannot precede event-time."""
    with pytest.raises(ValueError, match="Temporal invariant violation"):
        SharedMetadataRecord(
            source_id="test_source",
            dataset_type=DatasetType.SPOT_CANDLE.value,
            record_id="rec_1",
            instrument_id="BTCUSDT",
            event_time="2023-06-01T01:00:00Z",
            published_at="2023-06-01T00:00:00Z",
            available_at="2023-06-01T00:30:00Z",  # Earlier than event_time -> VIOLATION
            ingested_at="2023-06-01T02:00:00Z",
        )

    # VERIFIED_PIT requires non-null available_at
    with pytest.raises(ValueError, match="VERIFIED_PIT record must have an authoritative"):
        SharedMetadataRecord(
            source_id="test_source",
            dataset_type=DatasetType.SPOT_CANDLE.value,
            record_id="rec_2",
            instrument_id="BTCUSDT",
            event_time="2023-06-01T01:00:00Z",
            published_at="2023-06-01T02:00:00Z",
            available_at=None,
            ingested_at="2023-06-01T02:00:00Z",
            availability_quality=PITClassification.VERIFIED_PIT.value,
        )


# ── 3. OHLC Invariant Enforcement ─────────────────────────────────────────────

def test_3_candle_record_ohlc_invariants():
    """CandleRecord strictly checks High/Low boundary invariants and non-negative volume."""
    meta = SharedMetadataRecord(
        source_id="binance",
        dataset_type=DatasetType.SPOT_CANDLE.value,
        record_id="c1",
        instrument_id="BTCUSDT",
        event_time="2023-06-01T00:00:00Z",
        published_at="2023-06-01T01:00:00Z",
        available_at="2023-06-01T01:00:00Z",
        ingested_at="2023-06-01T01:05:00Z",
    )

    # Valid candle
    c_valid = CandleRecord(
        open_time="2023-06-01T00:00:00Z",
        close_time="2023-06-01T01:00:00Z",
        open=27000.0,
        high=27200.0,
        low=26900.0,
        close=27100.0,
        volume=100.0,
        quote_volume=2710000.0,
        trades_count=1000,
        taker_buy_volume=50.0,
        taker_buy_quote_volume=1355000.0,
        is_closed=True,
        metadata=meta,
    )
    assert c_valid.close == 27100.0

    # High lower than open -> invalid
    with pytest.raises(ValueError, match="Candle high .* is lower"):
        CandleRecord(
            open_time="2023-06-01T00:00:00Z",
            close_time="2023-06-01T01:00:00Z",
            open=27000.0,
            high=26950.0,  # Below open
            low=26900.0,
            close=26920.0,
            volume=10.0,
            quote_volume=270000.0,
            trades_count=10,
            taker_buy_volume=5.0,
            taker_buy_quote_volume=135000.0,
            is_closed=True,
            metadata=meta,
        )

    # Low higher than close -> invalid
    with pytest.raises(ValueError, match="Candle low .* is higher"):
        CandleRecord(
            open_time="2023-06-01T00:00:00Z",
            close_time="2023-06-01T01:00:00Z",
            open=27000.0,
            high=27200.0,
            low=27150.0,  # Above close
            close=27100.0,
            volume=10.0,
            quote_volume=270000.0,
            trades_count=10,
            taker_buy_volume=5.0,
            taker_buy_quote_volume=135000.0,
            is_closed=True,
            metadata=meta,
        )

    # Negative volume -> invalid
    with pytest.raises(ValueError, match="volume .* cannot be negative"):
        CandleRecord(
            open_time="2023-06-01T00:00:00Z",
            close_time="2023-06-01T01:00:00Z",
            open=27000.0,
            high=27200.0,
            low=26900.0,
            close=27100.0,
            volume=-5.0,
            quote_volume=270000.0,
            trades_count=10,
            taker_buy_volume=5.0,
            taker_buy_quote_volume=135000.0,
            is_closed=True,
            metadata=meta,
        )


# ── 4. Binance Archive Parsing with Microsecond Auto-Detection ────────────────

def test_4_binance_klines_parser_microsecond_support(tmp_path):
    """Synthetic Binance 2025 CSV with microsecond timestamps is accurately normalized."""
    csv_content = (
        "1738368000000000,102429.56,102575.06,102213.07,102494.94,538.12,1738371599999999,55128773.92,97185,325.69,33367519.04,0\n"
        "1738371600000000,102494.94,102780.27,102460.33,102566.00,501.44,1738375199999999,51469699.82,91532,280.68,28812124.66,0\n"
    )
    zip_path = tmp_path / "BTCUSDT-1h-2025-02-01.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("BTCUSDT-1h-2025-02-01.csv", csv_content)

    records = parse_klines_zip(zip_path, "BTCUSDT", "BINANCE_SPOT")
    assert len(records) == 2
    assert records[0].open_time == "2025-02-01T00:00:00Z"
    assert records[0].close_time == "2025-02-01T00:59:59Z"
    assert records[1].open_time == "2025-02-01T01:00:00Z"
    assert "MICROSECOND_TIMESTAMP_NORMALIZED" in records[0].metadata.quality_flags
    assert records[0].metadata.availability_quality == "VERIFIED_PIT"


# ── 5. Treasury Macro PIT Availability Rule & As-Of Join Test ─────────────────

def test_5_treasury_macro_pit_availability_and_as_of_join():
    """
    Validates the official U.S. Treasury daily yield release rule:
    - Yield on date D is officially published at market close ~21:00 UTC.
    - Market candle at 14:00 UTC on date D MUST NOT see date D yield (lookahead prevention).
    - Market candle at 22:00 UTC on date D CAN legally observe date D yield.
    """
    meta_d1 = SharedMetadataRecord(
        source_id="us_treasury",
        dataset_type=DatasetType.MACRO_YIELD.value,
        record_id="YIELD_2023_06_01",
        instrument_id="US_YIELD_CURVE",
        event_time="2023-06-01T20:30:00Z",
        published_at="2023-06-01T21:00:00Z",
        available_at="2023-06-01T21:00:00Z",
        ingested_at="2023-06-02T01:00:00Z",
        availability_quality=PITClassification.VERIFIED_PIT.value,
    )
    yield_rec_d1 = MacroYieldRecord(
        date="2023-06-01",
        yield_1m=5.0,
        yield_3m=5.2,
        yield_6m=5.4,
        yield_1y=5.3,
        yield_2y=4.5,
        yield_5y=4.0,
        yield_10y=3.8,
        yield_30y=3.9,
        metadata=meta_d1,
    )

    # 1. Daytime trade at 14:00 UTC: Cannot observe today's yield
    query_daytime = "2023-06-01T14:00:00Z"
    assert yield_rec_d1.metadata.is_joinable_as_of(query_daytime) is False

    # 2. Nighttime trade at 22:00 UTC: Can legally observe today's yield
    query_nighttime = "2023-06-01T22:00:00Z"
    assert yield_rec_d1.metadata.is_joinable_as_of(query_nighttime) is True

    # 3. Next day trade: Can legally observe
    query_next_day = "2023-06-02T08:00:00Z"
    assert yield_rec_d1.metadata.is_joinable_as_of(query_next_day) is True


# ── 6. Alternative.me Fear & Greed PIT Rule ───────────────────────────────────

def test_6_alternative_me_fear_and_greed_pit_rule():
    """Fear & Greed index is calculated at 00:00 UTC and available by 00:05 UTC."""
    meta = SharedMetadataRecord(
        source_id="alternative_me",
        dataset_type=DatasetType.MARKET_SENTIMENT.value,
        record_id="FNG_2023_06_01",
        instrument_id="CRYPTO_FNG",
        event_time="2023-06-01T00:00:00Z",
        published_at="2023-06-01T00:05:00Z",
        available_at="2023-06-01T00:05:00Z",
        ingested_at="2023-06-01T01:00:00Z",
        availability_quality=PITClassification.VERIFIED_PIT.value,
    )
    rec = SentimentRecord(
        timestamp="2023-06-01T00:00:00Z",
        value=50,
        classification="Neutral",
        metadata=meta,
    )

    # 00:02 UTC: not yet published -> reject
    assert rec.metadata.is_joinable_as_of("2023-06-01T00:02:00Z") is False

    # 00:06 UTC: legally available -> accept
    assert rec.metadata.is_joinable_as_of("2023-06-01T00:06:00Z") is True


# ── 7. PIT As-Of Join Engine Implementation ───────────────────────────────────

def test_7_as_of_feature_join_multi_source():
    """
    Demonstrates multi-source as-of feature join uniting:
    - 1h Market Candle (open: 2023-06-01 20:00:00Z, close: 2023-06-01 21:00:00Z)
    - Macro Yields (as-of close time 21:00:00Z)
    - Sentiment (as-of close time 21:00:00Z)
    """
    # Candle closes at 21:00:00Z
    meta_c = SharedMetadataRecord(
        source_id="binance",
        dataset_type=DatasetType.SPOT_CANDLE.value,
        record_id="c_20230601_20",
        instrument_id="BTCUSDT",
        event_time="2023-06-01T20:00:00Z",
        published_at="2023-06-01T21:00:00Z",
        available_at="2023-06-01T21:00:00Z",
        ingested_at="2023-06-01T21:01:00Z",
    )
    candle = CandleRecord(
        open_time="2023-06-01T20:00:00Z",
        close_time="2023-06-01T21:00:00Z",
        open=27000.0,
        high=27100.0,
        low=26950.0,
        close=27050.0,
        volume=120.0,
        quote_volume=3246000.0,
        trades_count=2100,
        taker_buy_volume=65.0,
        taker_buy_quote_volume=1758250.0,
        is_closed=True,
        metadata=meta_c,
    )

    # Treasury yield available exactly at 21:00:00Z
    meta_y = SharedMetadataRecord(
        source_id="us_treasury",
        dataset_type=DatasetType.MACRO_YIELD.value,
        record_id="Y_20230601",
        instrument_id="US_YIELD_CURVE",
        event_time="2023-06-01T20:30:00Z",
        published_at="2023-06-01T21:00:00Z",
        available_at="2023-06-01T21:00:00Z",
        ingested_at="2023-06-01T21:05:00Z",
        availability_quality=PITClassification.VERIFIED_PIT.value,
    )
    y_rec = MacroYieldRecord(
        date="2023-06-01",
        yield_1m=5.0,
        yield_3m=5.2,
        yield_6m=5.4,
        yield_1y=5.3,
        yield_2y=4.5,
        yield_5y=4.0,
        yield_10y=3.8,
        yield_30y=3.9,
        metadata=meta_y,
    )

    decision_time = candle.close_time  # 21:00:00Z
    assert y_rec.metadata.is_joinable_as_of(decision_time) is True

    # Derived feature: spot-basis / curve slope
    slope = y_rec.yield_10y - y_rec.yield_2y
    assert slope == pytest.approx(-0.7, 0.001)


# ── 8. Binance Futures Metrics Convention Transition (Issue #491) ─────────────

def test_8_binance_futures_metrics_convention_transition(tmp_path):
    """
    Validates Binance USD-M metrics labeling convention transition on 2026-06-25:
    - Pre-transition: raw timestamp represents end of period.
    - Post-transition: raw timestamp represents start of period.
    - Both map to exact period_start_utc and period_end_utc with lookahead immunity.
    - Unique source_record_id prevents duplicate collision.
    """
    from btc_scraper.research.historical_sources.binance_archive import parse_futures_metrics_zip

    # 1. Pre-transition (2026-06-24)
    csv_pre = "create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n2026-06-24 00:05:00,BTCUSDT,98745.0,6204317678.0,2.17,1.20,2.09,2.12\n"
    zip_pre = tmp_path / "BTCUSDT-metrics-2026-06-24.zip"
    with zipfile.ZipFile(zip_pre, "w") as z:
        z.writestr("BTCUSDT-metrics-2026-06-24.csv", csv_pre)

    records_pre = parse_futures_metrics_zip(zip_pre, "BTCUSDT")
    assert len(records_pre) == 1
    r_pre = records_pre[0]
    assert r_pre.timestamp_convention == "END_OF_PERIOD_CONVENTION"
    assert r_pre.period_end_utc == "2026-06-24T00:05:00Z"
    assert r_pre.period_start_utc == "2026-06-24T00:00:00Z"
    assert r_pre.available_at_utc == "2026-06-24T00:05:00Z"

    # 2. Post-transition (2026-06-25)
    csv_post = "create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n2026-06-25 00:05:00,BTCUSDT,100849.0,6155462025.0,2.66,1.10,2.57,1.16\n"
    zip_post = tmp_path / "BTCUSDT-metrics-2026-06-25.zip"
    with zipfile.ZipFile(zip_post, "w") as z:
        z.writestr("BTCUSDT-metrics-2026-06-25.csv", csv_post)

    records_post = parse_futures_metrics_zip(zip_post, "BTCUSDT")
    assert len(records_post) == 1
    r_post = records_post[0]
    assert r_post.timestamp_convention == "START_OF_PERIOD_CONVENTION"
    assert r_post.period_start_utc == "2026-06-25T00:05:00Z"
    assert r_post.period_end_utc == "2026-06-25T00:10:00Z"
    assert r_post.available_at_utc == "2026-06-25T00:10:00Z"

    # 3. Disambiguated IDs prevent collision
    assert r_pre.source_record_id != r_post.source_record_id
    assert "END_OF_PERIOD_CONVENTION" in r_pre.source_record_id
    assert "START_OF_PERIOD_CONVENTION" in r_post.source_record_id


# ── 9. Futures Metrics Zero Lookahead Rejection ───────────────────────────────

def test_9_futures_metrics_zero_lookahead_rejection(tmp_path):
    """Metrics over interval [T_start, T_end] cannot be legally observed before T_end."""
    from btc_scraper.research.historical_sources.binance_archive import parse_futures_metrics_zip

    csv_data = "create_time,symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio\n2026-06-25 12:00:00,BTCUSDT,100000.0,6000000000.0,2.5,1.1,2.4,1.0\n"
    zip_path = tmp_path / "BTCUSDT-metrics-2026-06-25.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("BTCUSDT-metrics-2026-06-25.csv", csv_data)

    rec = parse_futures_metrics_zip(zip_path, "BTCUSDT")[0]
    # Interval is [12:00:00Z, 12:05:00Z]
    assert rec.period_start_utc == "2026-06-25T12:00:00Z"
    assert rec.period_end_utc == "2026-06-25T12:05:00Z"

    # Query during the interval (e.g. 12:02:00Z) -> MUST BE REJECTED
    assert rec.metadata.is_joinable_as_of("2026-06-25T12:02:00Z") is False

    # Query exactly at close of interval (12:05:00Z) -> ALLOWED
    assert rec.metadata.is_joinable_as_of("2026-06-25T12:05:00Z") is True


# ── 10. Treasury Macro DST Seasonal Shifts (EDT vs EST) ───────────────────────

def test_10_treasury_macro_dst_seasonal_shifts(tmp_path):
    """
    Treasury release timing must follow America/New_York DST:
    - Summer EDT (UTC-4): 16:00 ET = 20:00:00 UTC.
    - Winter EST (UTC-5): 16:00 ET = 21:00:00 UTC.
    """
    from btc_scraper.research.historical_sources.treasury_macro import NY_TZ
    from zoneinfo import ZoneInfo

    # Summer EDT test (July 1)
    dt_summer = datetime(2023, 7, 1, 16, 0, tzinfo=NY_TZ)
    assert dt_summer.tzname() == "EDT"
    assert dt_summer.astimezone(timezone.utc).strftime("%H:%M:%S") == "20:00:00"

    # Winter EST test (January 1)
    dt_winter = datetime(2023, 1, 1, 16, 0, tzinfo=NY_TZ)
    assert dt_winter.tzname() == "EST"
    assert dt_winter.astimezone(timezone.utc).strftime("%H:%M:%S") == "21:00:00"


# ── 11. Alternative.me Conservative Availability Disposition ──────────────────

def test_11_alternative_me_conservative_availability_disposition():
    """Alternative.me sentiment uses CONSERVATIVE_ESTIMATE and 06:00 UTC buffer, not claiming VERIFIED_PIT."""
    meta = SharedMetadataRecord(
        source_id="alternative_me",
        dataset_type=DatasetType.MARKET_SENTIMENT.value,
        record_id="FNG_2023_06_01",
        instrument_id="CRYPTO_FNG",
        event_time="2023-06-01T00:00:00Z",
        published_at="2023-06-01T06:00:00Z",
        available_at="2023-06-01T06:00:00Z",
        ingested_at="2023-06-01T07:00:00Z",
        availability_quality=PITClassification.CONSERVATIVE_ESTIMATE.value,
    )
    rec = SentimentRecord(
        timestamp="2023-06-01T00:00:00Z",
        value=52,
        classification="Neutral",
        metadata=meta,
        api_record_timestamp="2023-06-01T00:00:00Z",
        conservative_available_at_utc="2023-06-01T06:00:00Z",
    )
    assert rec.metadata.availability_quality == "CONSERVATIVE_ESTIMATE"
    assert rec.metadata.is_joinable_as_of("2023-06-01T05:59:59Z") is False
    assert rec.metadata.is_joinable_as_of("2023-06-01T06:00:00Z") is True

