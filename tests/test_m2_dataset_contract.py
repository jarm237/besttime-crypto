"""
tests/test_m2_dataset_contract.py
Phase M2: Canonical Historical Dataset & Point-in-Time Ingestion Contract Tests.

Verifies:
1. CanonicalDatasetManifest immutability, partition hashes, and content hash determinism.
2. HistoricalDatasetProvider integrity checks, deduplication of monthly overlaps.
3. Point-in-time timestamp semantics: candle open vs close vs available_at.
4. Multi-timeframe (MTF) alignment: zero partial candle leakage.
5. Symbol late listing classification (NOT_LISTED vs MISSING_DATA).
6. Alternative data provenance: IV skew correctly identified as RECONSTRUCTED_PROXY.
7. Research Pilot: End-to-end integration with M1 ExperimentRunner on verified real market data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pytest

from btc_scraper.research.dataset_manifest import (
    CanonicalDatasetManifest,
    PartitionMetadata,
)
from btc_scraper.research.dataset_provider import (
    HistoricalDatasetProvider,
    PartitionIntegrityError,
    SymbolNotListedError,
)
from btc_scraper.research.alternative_data_inventory import (
    get_alternative_source_status,
    is_source_eligible_for_training,
)
from btc_scraper.research.experiment_contract import (
    ExperimentSpec,
    build_seven_layer_proxy_spec,
)
from btc_scraper.research.baseline_runner import (
    AlwaysFlatStrategy,
    ExperimentRunner,
    PassiveBuyAndHoldStrategy,
    SevenLayerProxyStrategy,
    SimpleMovingAverageCrossoverStrategy,
)

MANIFEST_PATH = Path("data/dataset_manifests/canonical_binance_2023_2026_manifest.json")
BASE_DATA_DIR = Path("data/fresh_training_data_2023_2026")


@pytest.fixture(scope="module")
def canonical_manifest() -> CanonicalDatasetManifest:
    assert MANIFEST_PATH.exists(), f"Canonical manifest missing at {MANIFEST_PATH}"
    return CanonicalDatasetManifest.load(MANIFEST_PATH)


@pytest.fixture(scope="module")
def dataset_provider(canonical_manifest) -> HistoricalDatasetProvider:
    return HistoricalDatasetProvider(canonical_manifest, BASE_DATA_DIR, verify_checksums=True)


# ── 1. Manifest Immutability & Content Hash Invariance ────────────────────────

def test_1_manifest_immutability_and_hashing(canonical_manifest):
    """Manifest computes a deterministic SHA-256 digest covering all 3,008 partitions."""
    assert len(canonical_manifest.manifest_content_hash) == 64
    assert len(canonical_manifest.partitions) >= 3000
    assert "BTC" in canonical_manifest.symbols
    assert "ETH" in canonical_manifest.symbols
    assert canonical_manifest.market_type == "binance_spot_klines"

    # Known exchange gaps are strictly scoped to Binance Spot
    btc_gaps = canonical_manifest.known_exchange_gaps.get("BTC", [])
    assert len(btc_gaps) >= 1
    assert btc_gaps[0]["exchange"] == "Binance"
    assert btc_gaps[0]["market_type"] == "spot"
    assert btc_gaps[0]["nature"] == "EXCHANGE_OUTAGE"
    assert "spot" in btc_gaps[0]["evidence_source"].lower()

    # Re-computed hash matches exactly
    recomputed = canonical_manifest.compute_manifest_hash()
    assert recomputed == canonical_manifest.manifest_content_hash

    # Frozen dataclass cannot be mutated
    with pytest.raises(Exception):
        canonical_manifest.global_start_time = "2020-01-01T00:00:00Z"


# ── 2. Data Provider Loading & SHA-256 Verification ───────────────────────────

def test_2_provider_loading_and_integrity(dataset_provider):
    """Provider verifies partition SHA-256 and streams normalized candles."""
    candles = dataset_provider.load_candles(
        symbol="BTCUSDT",
        timeframe="1h",
        start_time="2026-04-01T00:00:00Z",
        end_time="2026-04-03T23:00:00Z",
        include_warmup=False,
    )
    assert len(candles) == 72  # 3 days * 24 hours
    assert candles[0]["symbol"] == "BTCUSDT"
    assert candles[0]["time"] == "2026-04-01T00:00:00Z"
    assert candles[-1]["time"] == "2026-04-03T23:00:00Z"

    # All OHLC values are valid
    for c in candles:
        assert c["high"] >= max(c["open"], c["close"])
        assert c["low"] <= min(c["open"], c["close"])
        assert c["volume"] >= 0.0


# ── 3. Tamper Detection Guard ─────────────────────────────────────────────────

def test_3_tamper_detection_guard(canonical_manifest, tmp_path):
    """If partition file on disk has been modified or corrupted, provider raises PartitionIntegrityError."""
    # Create a corrupted partition file in a temporary copy directory
    corrupt_dir = tmp_path / "corrupt_data"
    corrupt_file = corrupt_dir / "BTC/1h/BTC_1h_2026-04.csv"
    corrupt_file.parent.mkdir(parents=True, exist_ok=True)
    corrupt_file.write_text("time,open,high,low,close,volume,is_warmup\n2026-04-01 00:00,1,1,1,1,1,0\n")

    provider = HistoricalDatasetProvider(canonical_manifest, corrupt_dir, verify_checksums=True)
    with pytest.raises(PartitionIntegrityError):
        provider.load_candles(
            symbol="BTCUSDT",
            timeframe="1h",
            start_time="2026-04-01T00:00:00Z",
            end_time="2026-04-02T00:00:00Z",
        )


# ── 4. Point-in-Time Timestamp Semantics ──────────────────────────────────────

def test_4_point_in_time_timestamp_semantics(dataset_provider):
    """Candle labeled time T (open) closes at T + interval; available_at is strictly close_time."""
    candles = dataset_provider.load_candles(
        symbol="BTCUSDT",
        timeframe="1h",
        start_time="2026-04-01T00:00:00Z",
        end_time="2026-04-01T05:00:00Z",
    )
    c0 = candles[0]
    # Candle open is 00:00:00Z
    assert c0["open_time"] == "2026-04-01T00:00:00Z"
    # Candle close is 01:00:00Z
    assert c0["close_time"] == "2026-04-01T01:00:00Z"
    # Candle is only available for decision at 01:00:00Z
    assert c0["available_at"] == "2026-04-01T01:00:00Z"

    # 15m test
    candles_15m = dataset_provider.load_candles(
        symbol="BTCUSDT",
        timeframe="15m",
        start_time="2026-04-01T00:00:00Z",
        end_time="2026-04-01T01:00:00Z",
    )
    c_15m = candles_15m[0]
    assert c_15m["open_time"] == "2026-04-01T00:00:00Z"
    assert c_15m["close_time"] == "2026-04-01T00:15:00Z"
    assert c_15m["available_at"] == "2026-04-01T00:15:00Z"


# ── 5. Multi-Timeframe Alignment: Zero Partial Candle Leakage ─────────────────

def test_5_mtf_alignment_zero_future_leakage(dataset_provider):
    """At 00:45:00Z, the 1h candle opening at 00:00:00Z has not closed yet and MUST NOT be leaked."""
    # At timestamp 2026-04-01T00:45:00Z:
    # 1h candle [00:00, 01:00] closes at 01:00, which is > 00:45!
    # Therefore, the latest fully closed 1h candle is the one that closed at or before 00:00 (i.e. [23:00, 00:00]).
    mtf = dataset_provider.get_mtf_context(
        symbol="BTCUSDT",
        current_timestamp="2026-04-01T00:45:00Z",
        higher_timeframes=["1h", "4h"],
    )
    h1 = mtf["1h"]
    assert h1 is not None
    assert h1["close_time"] <= "2026-04-01T00:45:00Z"
    assert h1["open_time"] == "2026-03-31T23:00:00Z"
    assert h1["close_time"] == "2026-04-01T00:00:00Z"

    # Exactly at 01:00:00Z: now the 1h candle [00:00, 01:00] is closed and eligible!
    mtf_after = dataset_provider.get_mtf_context(
        symbol="BTCUSDT",
        current_timestamp="2026-04-01T01:00:00Z",
        higher_timeframes=["1h"],
    )
    h1_after = mtf_after["1h"]
    assert h1_after is not None
    assert h1_after["open_time"] == "2026-04-01T00:00:00Z"
    assert h1_after["close_time"] == "2026-04-01T01:00:00Z"


# ── 6. Symbol Late Listing Classification ─────────────────────────────────────

def test_6_late_listing_classification(dataset_provider, canonical_manifest):
    """WLD listed in 2023-07: requesting prior dates with strict_listing=True raises SymbolNotListedError."""
    wld_meta = canonical_manifest.symbol_listing_metadata.get("WLD", {})
    assert wld_meta.get("listing_status") == "LATE_LISTING"
    assert wld_meta.get("first_available_month") == "2023-07"
    assert wld_meta.get("first_observed_data_date").startswith("2023-07-24")
    assert wld_meta.get("verified_listing_date") == "2023-07-24T00:00:00Z"
    assert wld_meta.get("pre_listing_classification") == "NOT_LISTED"

    # Full history symbol has verified historical listing
    btc_meta = canonical_manifest.symbol_listing_metadata.get("BTC", {})
    assert btc_meta.get("listing_status") == "FULL_HISTORY"
    assert btc_meta.get("verified_listing_date") == "2017-08-17T00:00:00Z"

    # With strict_listing=True: raises SymbolNotListedError
    with pytest.raises(SymbolNotListedError):
        dataset_provider.load_candles(
            symbol="WLDUSDT",
            timeframe="1h",
            start_time="2023-01-01T00:00:00Z",
            end_time="2023-03-01T00:00:00Z",
            strict_listing=True,
        )

    # With strict_listing=False: returns empty without fabricating missing data
    res = dataset_provider.load_candles(
        symbol="WLDUSDT",
        timeframe="1h",
        start_time="2023-01-01T00:00:00Z",
        end_time="2023-03-01T00:00:00Z",
        strict_listing=False,
    )
    assert len(res) == 0


# ── 7. Deduplication of Monthly Warmup Overlaps ────────────────────────────────

def test_7_monthly_warmup_overlap_deduplication(dataset_provider):
    """Boundary transition between 2026-03 and 2026-04 contains 0 duplicate timestamps."""
    candles = dataset_provider.load_candles(
        symbol="BTCUSDT",
        timeframe="1h",
        start_time="2026-03-30T00:00:00Z",
        end_time="2026-04-02T00:00:00Z",
        include_warmup=False,
    )
    times = [c["time"] for c in candles]
    assert len(times) == len(set(times)), "Duplicate timestamps detected across monthly boundary!"
    # Strictly monotonically increasing
    for i in range(1, len(times)):
        assert times[i] > times[i - 1]


# ── 8. Alternative Data Governance & Eligibility ──────────────────────────────

def test_8_alternative_data_governance():
    """IV Skew is formally identified as RECONSTRUCTED_PROXY and barred from production training."""
    iv_status = get_alternative_source_status("deribit_iv_skew_proxy")
    assert iv_status is not None
    assert iv_status.nature == "RECONSTRUCTED_PROXY"
    assert iv_status.eligibility_status == "REJECTED_FOR_PRODUCTION_TRAINING"
    assert is_source_eligible_for_training("deribit_iv_skew_proxy") is False

    # Funding rates are genuine and eligible for cost model
    fr_status = get_alternative_source_status("binance_funding_rates")
    assert fr_status is not None
    assert fr_status.nature == "GENUINE_OBSERVATION"
    assert fr_status.eligibility_status == "ELIGIBLE_FOR_COST_MODEL"


# ── 9. Research Pilot: Verified Ingestion & M1 Baseline Execution ──────────────

def test_9_research_pilot_verified_ingestion(dataset_provider, canonical_manifest):
    """End-to-end pilot: loads real BTC 1h data via provider and executes all 4 M1 baselines."""
    start_t = "2026-04-01T00:00:00Z"
    end_t = "2026-04-10T00:00:00Z"

    candles = dataset_provider.load_candles(
        symbol="BTCUSDT",
        timeframe="1h",
        start_time=start_t,
        end_time=end_t,
        include_warmup=False,
    )
    assert len(candles) == 217  # 9 days * 24 + 1 bar
    dataset = {"BTCUSDT": candles}

    spec = ExperimentSpec(
        experiment_id="pilot-m2-verified-ingestion",
        strategy_id="multi_eval_m2",
        strategy_version="1.0",
        strategy_tier="BENCHMARK",
        dataset_manifest_identity=canonical_manifest.manifest_id,
        dataset_content_hash=canonical_manifest.manifest_content_hash,
        feature_set_version="raw-ohlcv-v1",
        symbol_universe=("BTCUSDT",),
        timeframe="1h",
        oos_window=(start_t, end_t),
        initial_capital=10_000.0,
        allocation_pct=0.10,
    )

    runner = ExperimentRunner(spec, liquidate_at_end=True)
    strategies = [
        AlwaysFlatStrategy(),
        PassiveBuyAndHoldStrategy(),
        SimpleMovingAverageCrossoverStrategy(fast_period=5, slow_period=15),
        SevenLayerProxyStrategy(r_multiple=2.0),
    ]

    for strat in strategies:
        res = runner.run(strat, dataset)
        # Cost reconciliation: Gross - Fees == Net within rounding cent
        assert abs((res.gross_pnl - res.total_fees) - res.net_pnl) <= 0.02
        # Equity reconciliation: Initial + Net == Final Equity within rounding cent
        assert abs((res.initial_capital + res.net_pnl) - res.final_equity) <= 0.02
        assert res.reconciliation_error < 0.01

        # Clean profit factor verification: no sentinel 999.0
        assert res.profit_factor != 999.0
        assert res.profit_factor_status in ("DEFINED", "ALL_WINS_INFINITE", "ALL_LOSSES_ZERO", "BREAKEVEN_ONLY", "NO_TRADES_UNDEFINED")
