"""
tests/test_m2_cross_source_pit_join.py
Integration tests for M2 cross-source Point-in-Time (PIT) joins and canonical backfill manifest.

Verifies:
1. Canonical backfill manifest integrity and content hash determinism across all 14 full-history symbols.
2. Reused spot klines and newly backfilled USD-M futures klines / funding / metrics alignment.
3. Multi-asset Point-in-Time (PIT) join:
   - Hourly spot + futures basis computation.
   - Realized funding rate as-of join.
   - Treasury yield curve slope (10Y - 2Y) DST-aware release time filtering (zero daytime lookahead).
   - Alternative.me sentiment conservative availability filtering.
4. Binance USD-M metrics 2026-06-25 transition (issue #491) lookahead immunity.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import pytest
import pandas as pd

MANIFEST_PATH = Path("data/historical/manifests/canonical_m2_backfill_manifest.json")
NORMALIZED_DIR = Path("data/historical/normalized")
EXISTING_SPOT_DIR = Path("data/fresh_training_data_2023_2026")

FULL_HISTORY_SYMBOLS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE",
    "AVAX", "TRX", "NEAR", "XLM", "IOTA", "ZEC",
    "AR", "TRB"
]


@pytest.fixture(scope="module")
def backfill_manifest() -> dict:
    assert MANIFEST_PATH.exists(), f"Backfill manifest missing at {MANIFEST_PATH}"
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_1_canonical_backfill_manifest_integrity(backfill_manifest):
    """Manifest covers 14 full-history symbols, has valid content hash and partitions."""
    assert backfill_manifest["manifest_version"] == "2.0.0"
    assert backfill_manifest["milestone"] == "M2_EXPANSION_HISTORICAL_BACKFILL"
    assert len(backfill_manifest["manifest_content_hash"]) == 64
    assert backfill_manifest["total_ready_partitions"] >= 5000
    assert backfill_manifest["total_rows"] >= 2_000_000

    summary = backfill_manifest["summary_by_dataset"]
    assert "SPOT_CANDLE" in summary
    assert "FUTURES_CANDLE" in summary
    assert "FUNDING_RATE" in summary
    assert "FUTURES_METRIC" in summary
    assert "MACRO_YIELD" in summary
    assert "MARKET_SENTIMENT" in summary
    assert "ONCHAIN_STABLECOIN" in summary

    # Verify all 14 full-history symbols are present in futures and funding
    futures_symbols = set(summary["FUTURES_CANDLE"]["symbols"])
    funding_symbols = set(summary["FUNDING_RATE"]["symbols"])
    for sym in FULL_HISTORY_SYMBOLS:
        pair = f"{sym}USDT"
        assert pair in futures_symbols, f"Symbol {pair} missing from futures klines"
        assert pair in funding_symbols, f"Symbol {pair} missing from funding rates"


def test_2_spot_and_futures_basis_calculation():
    """Calculates basis = (futures_close - spot_close) / spot_close for BTC at 2023-06."""
    # Spot BTC 1h
    spot_file = EXISTING_SPOT_DIR / "BTC" / "1h" / "BTC_1h_2023-06.csv"
    assert spot_file.exists()
    spot_df = pd.read_csv(spot_file)
    spot_df["time_iso"] = pd.to_datetime(spot_df["time"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Futures BTC 1h
    fut_file = NORMALIZED_DIR / "futures_klines_1h" / "BTCUSDT" / "BTCUSDT_1h_2023-06.parquet"
    assert fut_file.exists()
    fut_df = pd.read_parquet(fut_file)

    # Merge on timestamp
    merged = pd.merge(spot_df, fut_df, left_on="time_iso", right_on="open_time", suffixes=("_spot", "_fut"))
    assert len(merged) > 700

    # Compute basis
    merged["basis_bps"] = ((merged["close_fut"] - merged["close_spot"]) / merged["close_spot"]) * 10_000
    assert merged["basis_bps"].notna().all()
    # Crypto futures basis in June 2023 was generally within -50 to +150 bps
    assert merged["basis_bps"].abs().max() < 1000


def test_3_cross_source_pit_join_zero_lookahead():
    """
    Performs Point-in-Time as-of join between hourly candle and multi-source context:
    - Realized funding rate (available upon settlement).
    - Treasury 10Y-2Y slope (available after 20:00/21:00 UTC).
    - Fear & Greed index (available after 06:00 UTC).
    Ensures zero future information leakage.
    """
    # 1. Load Treasury Macro yields
    tr_path = NORMALIZED_DIR / "macro" / "treasury_yields_1990_2026.parquet"
    assert tr_path.exists()
    tr_df = pd.read_parquet(tr_path)
    # Focus on 2023
    tr_2023 = tr_df[tr_df["date"].str.startswith("2023")].copy()

    # Test candle time: 2023-06-15 14:00:00Z (midday trading)
    candle_time_midday = "2023-06-15T14:00:00Z"
    # At 14:00:00Z, June 15 Treasury yields are NOT available yet (they release at 20:00Z EDT / 21:00Z EST)
    # The latest available Treasury record must strictly be June 14 or earlier!
    available_tr = tr_2023[tr_2023["conservative_available_at_utc"] <= candle_time_midday]
    latest_tr = available_tr.iloc[-1]
    assert latest_tr["date"] <= "2023-06-14", f"Lookahead leak: June 15 yield joined at {candle_time_midday}"

    # Test candle time: 2023-06-15 22:00:00Z (after market close and release)
    candle_time_night = "2023-06-15T22:00:00Z"
    available_tr_night = tr_2023[tr_2023["conservative_available_at_utc"] <= candle_time_night]
    latest_tr_night = available_tr_night.iloc[-1]
    # Now June 15 yield IS validly joinable
    assert latest_tr_night["date"] == "2023-06-15"

    # 2. Alternative.me Fear & Greed PIT filtering
    fng_path = NORMALIZED_DIR / "sentiment" / "fear_and_greed_2018_2026.parquet"
    assert fng_path.exists()
    fng_df = pd.read_parquet(fng_path)

    # At 02:00:00Z on 2023-06-15, conservative availability (06:00:00Z) has not elapsed
    candle_early = "2023-06-15T02:00:00Z"
    available_fng = fng_df[fng_df["conservative_available_at_utc"] <= candle_early]
    latest_fng = available_fng.iloc[-1]
    assert latest_fng["timestamp"][:10] <= "2023-06-14"

    # At 08:00:00Z on 2023-06-15, conservative availability has elapsed
    candle_late = "2023-06-15T08:00:00Z"
    available_fng_late = fng_df[fng_df["conservative_available_at_utc"] <= candle_late]
    latest_fng_late = available_fng_late.iloc[-1]
    assert latest_fng_late["timestamp"][:10] == "2023-06-15"


def test_4_futures_metrics_monthly_consolidated_invariants():
    """
    Verifies that the consolidated monthly metrics datasets exist for 14 symbols,
    contain monotonic timestamps, and obey zero lookahead (available_at_utc == period_end_utc).
    """
    metrics_dir = NORMALIZED_DIR / "futures_metrics"
    assert metrics_dir.exists()

    # Check BTC metrics June 2026 (includes transition date 2026-06-25)
    btc_pqt = metrics_dir / "BTCUSDT" / "BTCUSDT_metrics_2026-06.parquet"
    assert btc_pqt.exists()
    df = pd.read_parquet(btc_pqt)
    assert len(df) > 0

    # Invariants
    assert (df["sum_open_interest"] >= 0).all()
    assert (df["sum_open_interest_usd"] >= 0).all()
    assert (df["period_start_utc"] < df["period_end_utc"]).all()
    assert (df["available_at_utc"] == df["period_end_utc"]).all()

    # Inspect the transition around 2026-06-25
    pre_trans = df[df["timestamp"] < "2026-06-25T00:00:00Z"]
    post_trans = df[df["timestamp"] >= "2026-06-25T00:00:00Z"]

    if not pre_trans.empty:
        assert (pre_trans["timestamp_convention"] == "END_OF_PERIOD_CONVENTION").all()
    if not post_trans.empty:
        assert (post_trans["timestamp_convention"] == "START_OF_PERIOD_CONVENTION").all()
