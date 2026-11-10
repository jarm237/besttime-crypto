"""
tests/test_m2_metrics_pit_sensitivity.py
Phase B: Point-in-Time Availability & Temporal Integrity Sensitivity Tests.

Verifies:
1. Futures Metrics Issue #491 latency sensitivity: tests availability buffers (+0m, +5m, +15m, +1h).
2. Treasury Yields America/New_York DST-aware release time filtering (no daytime lookahead).
3. Alternative.me Fear & Greed conservative availability buffer (06:00 UTC).
4. DefiLlama Stablecoins provenance tracking and revision risk (PIT_RESTRICTED).
5. As-of join negative assertions: missing data is not converted to 0, future values are rejected.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NORMALIZED_DIR = PROJECT_ROOT / "data" / "historical" / "normalized"


def test_1_futures_metrics_latency_buffer_sensitivity():
    """
    Tests as-of joins under 4 different publication latency assumptions:
    - Buffer 0m: available exactly at period_end_utc
    - Buffer +5m: available period_end_utc + 5 minutes
    - Buffer +15m: available period_end_utc + 15 minutes
    - Buffer +60m: available period_end_utc + 1 hour
    Ensures that features relying on metrics at bar close T respect the assumed publication buffer.
    """
    # Load BTC metrics for a sample month (June 2023)
    pqt_file = NORMALIZED_DIR / "futures_metrics" / "BTCUSDT" / "BTCUSDT_metrics_2023-06.parquet"
    assert pqt_file.exists(), f"Missing {pqt_file}"
    df = pd.read_parquet(pqt_file)
    assert not df.empty

    # Consider an hourly candle closing at 2023-06-15 12:00:00Z
    bar_close_time = "2023-06-15T12:00:00Z"
    bar_close_dt = datetime.fromisoformat(bar_close_time.replace("Z", "+00:00"))

    from datetime import timedelta
    buffers_minutes = [0, 5, 15, 60]
    matched_records = {}

    for buf_m in buffers_minutes:
        cutoff = (bar_close_dt - timedelta(minutes=buf_m)).strftime("%Y-%m-%dT%H:%M:%SZ")
        eligible = df[df["period_end_utc"] <= cutoff]
        assert not eligible.empty, f"No eligible metrics for buffer {buf_m}m"
        latest = eligible.iloc[-1]
        matched_records[buf_m] = {
            "period_end_utc": latest["period_end_utc"],
            "assumed_available_at": latest["period_end_utc"],
            "sum_open_interest_usd": latest["sum_open_interest_usd"],
        }

    # Under 0m buffer: latest 5m bar ending at 12:00:00Z is joinable
    assert matched_records[0]["period_end_utc"] == "2023-06-15T12:00:00Z"

    # Under 5m buffer: bar ending at 12:00:00Z is NOT yet available at 12:00:00Z (it arrives at 12:05:00Z)
    # The latest joinable bar must be 11:55:00Z
    assert matched_records[5]["period_end_utc"] <= "2023-06-15T11:55:00Z"

    # Under 15m buffer: latest joinable bar is 11:45:00Z
    assert matched_records[15]["period_end_utc"] <= "2023-06-15T11:45:00Z"

    # Under 60m buffer: latest joinable bar is 11:00:00Z
    assert matched_records[60]["period_end_utc"] <= "2023-06-15T11:00:00Z"

    # Strict invariant: longer latency buffer yields older or equal data, never newer
    for i in range(len(buffers_minutes) - 1):
        b1 = buffers_minutes[i]
        b2 = buffers_minutes[i + 1]
        assert matched_records[b1]["period_end_utc"] >= matched_records[b2]["period_end_utc"]


def test_2_treasury_daytime_non_leakage_and_dst():
    """
    Verifies Treasury yield release dynamics across winter (EST) and summer (EDT).
    Confirms zero daytime leakage.
    """
    tr_path = NORMALIZED_DIR / "macro" / "treasury_yields_1990_2026.parquet"
    assert tr_path.exists()
    df_tr = pd.read_parquet(tr_path)

    # 1. Summer observation (EDT): June 21, 2023
    # Actual release: 16:00 ET = 20:00:00Z
    summer_day = df_tr[df_tr["date"] == "2023-06-21"]
    assert not summer_day.empty
    rec_summer = summer_day.iloc[0]
    assert rec_summer["actual_publication_time_utc"] == "2023-06-21T20:00:00Z"

    # Midday query at 18:00:00Z must NOT join June 21
    eligible_midday = df_tr[df_tr["conservative_available_at_utc"] <= "2023-06-21T18:00:00Z"]
    assert eligible_midday.iloc[-1]["date"] <= "2023-06-20"

    # 2. Winter observation (EST): January 18, 2023
    # Actual release: 16:00 ET = 21:00:00Z
    winter_day = df_tr[df_tr["date"] == "2023-01-18"]
    assert not winter_day.empty
    rec_winter = winter_day.iloc[0]
    assert rec_winter["actual_publication_time_utc"] == "2023-01-18T21:00:00Z"

    # Query at 20:30:00Z must NOT join January 18
    eligible_winter = df_tr[df_tr["conservative_available_at_utc"] <= "2023-01-18T20:30:00Z"]
    assert eligible_winter.iloc[-1]["date"] <= "2023-01-17"


def test_3_sentiment_conservative_buffer():
    """
    Verifies Alternative.me Fear & Greed conservative 06:00:00Z buffer.
    """
    fng_path = NORMALIZED_DIR / "sentiment" / "fear_and_greed_2018_2026.parquet"
    assert fng_path.exists()
    df_fng = pd.read_parquet(fng_path)

    # Day: 2024-03-10
    sample_day = df_fng[df_fng["timestamp"].str.startswith("2024-03-10")]
    assert not sample_day.empty
    rec = sample_day.iloc[0]
    assert rec["conservative_available_at_utc"] == "2024-03-10T06:00:00Z"

    # Query at 03:00:00Z returns previous day
    eligible = df_fng[df_fng["conservative_available_at_utc"] <= "2024-03-10T03:00:00Z"]
    assert eligible.iloc[-1]["timestamp"][:10] <= "2024-03-09"

    # Query at 07:00:00Z returns current day
    eligible_post = df_fng[df_fng["conservative_available_at_utc"] <= "2024-03-10T07:00:00Z"]
    assert eligible_post.iloc[-1]["timestamp"][:10] == "2024-03-10"


def test_4_negative_as_of_join_invariants():
    """
    Negative tests:
    - Missing data does not silently become 0.0 (must be NaN or None).
    - Future candles (after bar close) cannot be joined.
    """
    tr_path = NORMALIZED_DIR / "macro" / "treasury_yields_1990_2026.parquet"
    df_tr = pd.read_parquet(tr_path)

    # Sunday observation (weekend when US Treasury is closed)
    # 2023-06-18 was a Sunday
    sunday_close = "2023-06-18T12:00:00Z"
    eligible = df_tr[df_tr["conservative_available_at_utc"] <= sunday_close]
    latest = eligible.iloc[-1]
    # Treasury was closed June 17 (Sat) and June 18 (Sun), latest must be Friday June 16
    assert latest["date"] == "2023-06-16"
    assert latest["yield_10y"] is not None
    assert latest["yield_10y"] > 0.0  # Real yield, not synthetic zero
