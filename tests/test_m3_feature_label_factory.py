"""
tests/test_m3_feature_label_factory.py
Phase M3: Feature & Label Factory Contract and Invariant Tests.

Verifies:
1. FeatureSetSpec immutability, schema hash determinism, and serializability.
2. Technical feature computation accuracy (returns, ATR, RSI, MACD, SMA).
3. Strict Point-in-Time MTF alignment: no future candle leakage.
4. Batch vs Replay feature parity (< 10^-6 numerical tolerance).
5. Triple-barrier label resolution: clean TP, clean SL, vertical barrier.
6. Conservative collision policy: SL executed first on simultaneous TP/SL hit.
7. Economic cost accounting: gross vs net return with fees and slippage.
8. Purging/embargo metadata validity.
9. No future leakage verification under future truncation/mutation.
10. End-to-end research pilot on verified BTC/ETH historical dataset.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
import pytest
import numpy as np

from btc_scraper.research.dataset_manifest import CanonicalDatasetManifest
from btc_scraper.research.dataset_provider import HistoricalDatasetProvider
from btc_scraper.research.feature_contract import (
    FeatureSetSpec,
    M3_STANDARD_FEATURE_NAMES,
    build_m3_standard_feature_spec,
)
from btc_scraper.research.feature_factory import FeatureFactory
from btc_scraper.research.label_factory import (
    TripleBarrierLabel,
    TripleBarrierLabelFactory,
    TripleBarrierSpec,
)
from btc_scraper.research.dataset_factory import (
    AlignedDataset,
    ResearchDatasetFactory,
)

MANIFEST_PATH = Path("data/dataset_manifests/canonical_binance_2023_2026_manifest.json")
BASE_DATA_DIR = Path("data/fresh_training_data_2023_2026")


@pytest.fixture(scope="module")
def canonical_manifest() -> CanonicalDatasetManifest:
    assert MANIFEST_PATH.exists()
    return CanonicalDatasetManifest.load(MANIFEST_PATH)


@pytest.fixture(scope="module")
def dataset_provider(canonical_manifest) -> HistoricalDatasetProvider:
    return HistoricalDatasetProvider(canonical_manifest, BASE_DATA_DIR, verify_checksums=False)


# ── Helper for Synthetic Candles ──────────────────────────────────────────────

def create_synthetic_candle(
    time_str: str,
    open_p: float,
    high_p: float,
    low_p: float,
    close_p: float,
    volume: float = 100.0,
    interval_minutes: int = 15,
) -> dict:
    from datetime import datetime, timedelta, timezone
    dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
    close_dt = dt + timedelta(minutes=interval_minutes)
    return {
        "symbol": "BTCUSDT",
        "time": time_str,
        "open_time": time_str,
        "close_time": close_dt.isoformat().replace("+00:00", "Z"),
        "open": open_p,
        "high": high_p,
        "low": low_p,
        "close": close_p,
        "volume": volume,
    }


# ── 1. FeatureSetSpec Immutability & Hash Invariance ──────────────────────────

def test_1_feature_set_spec_immutability_and_hashing():
    spec = build_m3_standard_feature_spec(
        dataset_manifest_hash="test_manifest_hash_12345",
        feature_set_id="test_spec_v1",
    )
    assert len(spec.feature_schema_hash) == 64
    assert spec.compute_schema_hash() == spec.feature_schema_hash

    # Immutability check: cannot modify attributes
    with pytest.raises(Exception):
        spec.base_timeframe = "1h"

    # Immutability check: cannot modify nested parameters
    with pytest.raises(Exception):
        spec.feature_parameters["rsi_period"] = 21

    # Roundtrip serialization
    d = spec.to_dict()
    restored = FeatureSetSpec.from_dict(d)
    assert restored.feature_schema_hash == spec.feature_schema_hash
    assert restored.feature_names == spec.feature_names


# ── 2. Technical Feature Computation Accuracy ─────────────────────────────────

def test_2_technical_feature_computation():
    from datetime import datetime, timedelta, timezone
    spec = build_m3_standard_feature_spec("dummy_hash")
    factory = FeatureFactory(spec)

    candles = []
    base_dt = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    # Build 30 synthetic candles with steady prices and a jump
    for i in range(30):
        t = (base_dt + timedelta(hours=i)).isoformat().replace("+00:00", "Z")
        p = 100.0 + i
        candles.append(create_synthetic_candle(t, p, p + 2.0, p - 1.0, p + 0.5, volume=10.0 + i))

    features = factory.compute_batch_features(candles)
    assert len(features) == 30

    # Candle 1 return
    c0_close = candles[0]["close"]
    c1_close = candles[1]["close"]
    expected_ret_1 = (c1_close - c0_close) / c0_close
    assert math.isclose(features[1]["ret_1"], expected_ret_1, rel_tol=1e-6)

    # RSI bounded in [0, 100]
    for row in features:
        assert 0.0 <= row["rsi_14"] <= 100.0

    # MACD histogram = macd_line - macd_signal
    for row in features:
        assert math.isclose(row["macd_hist"], row["macd_line"] - row["macd_signal"], abs_tol=1e-8)


# ── 3. Multi-Timeframe Point-in-Time Alignment ────────────────────────────────

def test_3_mtf_point_in_time_alignment():
    """At 00:30 (close 00:45), the 1h candle [00:00-01:00] is NOT available. Only [23:00-00:00] is seen."""
    spec = build_m3_standard_feature_spec("dummy_hash")
    factory = FeatureFactory(spec)

    base_candles = [
        create_synthetic_candle("2026-04-01T00:00:00Z", 100, 101, 99, 100, interval_minutes=15),
        create_synthetic_candle("2026-04-01T00:15:00Z", 100, 102, 99, 101, interval_minutes=15),
        create_synthetic_candle("2026-04-01T00:30:00Z", 101, 103, 100, 102, interval_minutes=15),
        create_synthetic_candle("2026-04-01T00:45:00Z", 102, 104, 101, 103, interval_minutes=15),
        create_synthetic_candle("2026-04-01T01:00:00Z", 103, 105, 102, 104, interval_minutes=15),
    ]

    htf_1h = [
        create_synthetic_candle("2026-03-31T23:00:00Z", 95, 96, 94, 95, interval_minutes=60),  # closes 00:00:00Z
        create_synthetic_candle("2026-04-01T00:00:00Z", 95, 110, 95, 105, interval_minutes=60), # closes 01:00:00Z
    ]

    features = factory.compute_batch_features(base_candles, {"1h": htf_1h})

    # At base candle 2 (00:30:00Z, close_time 00:45:00Z):
    # 1h candle closing at 01:00:00Z is in the future (> 00:45:00Z).
    # Thus, the HTF candle seen must be the 23:00-00:00 one!
    # Expected return of the 23:00-00:00 candle (first one) is 0.0.
    assert features[2]["mtf_1h_ret_1"] == 0.0

    # At base candle 3 (00:45:00Z, close_time 01:00:00Z):
    # Now close_time is 01:00:00Z, which equals the 1h candle's close_time 01:00:00Z!
    # Thus, the 00:00-01:00 candle is now fully closed and eligible.
    # Its return is (105 - 95) / 95 = 10 / 95
    expected_htf_ret = (105.0 - 95.0) / 95.0
    assert math.isclose(features[3]["mtf_1h_ret_1"], expected_htf_ret, rel_tol=1e-6)


# ── 4. Batch vs Replay Feature Parity ─────────────────────────────────────────

def test_4_batch_vs_replay_feature_parity():
    """Vectorized batch and step-by-step replay inference match within 10^-6 tolerance."""
    spec = build_m3_standard_feature_spec("dummy_hash")
    factory = FeatureFactory(spec)

    # 60 synthetic candles
    from datetime import datetime, timedelta, timezone
    base_dt = datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc)
    candles = []
    p = 50000.0
    for i in range(60):
        t = (base_dt + timedelta(minutes=i * 15)).isoformat().replace("+00:00", "Z")
        p += math.sin(i * 0.3) * 50.0
        candles.append(create_synthetic_candle(t, p, p + 30.0, p - 30.0, p + 10.0, volume=500.0 + i * 10))

    batch_features = factory.compute_batch_features(candles)

    # Check parity across multiple trailing steps
    for step in (30, 45, 59):
        history_slice = candles[: step + 1]
        replay_feat = factory.compute_replay_features(history_slice)
        batch_feat = batch_features[step]

        for fname in M3_STANDARD_FEATURE_NAMES:
            b_val = batch_feat[fname]
            r_val = replay_feat[fname]
            assert abs(b_val - r_val) < 1e-6, f"Parity mismatch at step {step} for feature '{fname}': batch={b_val}, replay={r_val}"


# ── 5. Triple Barrier: Take Profit, Stop Loss, and Timeout ────────────────────

def test_5_triple_barrier_clean_outcomes():
    label_spec = TripleBarrierSpec(take_profit_pct=0.02, stop_loss_pct=0.01, max_holding_bars=4)
    label_factory = TripleBarrierLabelFactory(label_spec)

    # Base candle at index 0 (decision)
    c0 = create_synthetic_candle("2026-04-01T00:00:00Z", 100, 101, 99, 100)
    # Entry candle at index 1: opens at 100.0. TP = 102.0, SL = 99.0
    c1_tp = create_synthetic_candle("2026-04-01T00:15:00Z", 100, 103, 99.5, 102.5)  # Hits TP (high 103 >= 102)
    labels_tp = label_factory.compute_labels([c0, c1_tp])
    lbl = labels_tp[0]
    assert lbl is not None
    assert lbl.exit_reason == "TAKE_PROFIT"
    assert lbl.exit_price == 102.0
    assert lbl.label_class == 1

    # Scenario: Clean SL hit
    c1_sl = create_synthetic_candle("2026-04-01T00:15:00Z", 100, 100.5, 98.0, 98.5)  # Hits SL (low 98 <= 99)
    labels_sl = label_factory.compute_labels([c0, c1_sl])
    lbl_sl = labels_sl[0]
    assert lbl_sl is not None
    assert lbl_sl.exit_reason == "STOP_LOSS"
    assert lbl_sl.exit_price == 99.0
    assert lbl_sl.label_class == -1


# ── 6. Conservative Collision Policy: SL First ────────────────────────────────

def test_6_conservative_collision_sl_first():
    """When both TP and SL are hit in the same bar, conservative policy triggers SL first."""
    label_spec = TripleBarrierSpec(take_profit_pct=0.02, stop_loss_pct=0.01, intrabar_policy="CONSERVATIVE_SL_FIRST")
    label_factory = TripleBarrierLabelFactory(label_spec)

    c0 = create_synthetic_candle("2026-04-01T00:00:00Z", 100, 101, 99, 100)
    # Wide bar: high touches TP (102.5 >= 102.0), low touches SL (98.0 <= 99.0)
    c1_collision = create_synthetic_candle("2026-04-01T00:15:00Z", 100, 102.5, 98.0, 101.0)

    labels = label_factory.compute_labels([c0, c1_collision])
    lbl = labels[0]
    assert lbl is not None
    assert lbl.exit_reason == "STOP_LOSS"
    assert lbl.exit_price == 99.0
    assert lbl.label_class == -1


# ── 7. Triple Barrier Vertical Barrier Timeout ────────────────────────────────

def test_7_vertical_barrier_timeout():
    label_spec = TripleBarrierSpec(take_profit_pct=0.05, stop_loss_pct=0.05, max_holding_bars=3)
    label_factory = TripleBarrierLabelFactory(label_spec)

    # 5 quiet candles where price stays around 100
    candles = [
        create_synthetic_candle("2026-04-01T00:00:00Z", 100, 101, 99, 100),
        create_synthetic_candle("2026-04-01T00:15:00Z", 100, 100.5, 99.5, 100.2), # Entry
        create_synthetic_candle("2026-04-01T00:30:00Z", 100.2, 100.8, 99.8, 100.4), # Bar 2
        create_synthetic_candle("2026-04-01T00:45:00Z", 100.4, 100.9, 99.9, 100.5), # Bar 3 (terminal)
    ]
    labels = label_factory.compute_labels(candles)
    lbl = labels[0]
    assert lbl is not None
    assert lbl.exit_reason == "VERTICAL_BARRIER"
    assert lbl.exit_price == 100.5
    assert lbl.holding_bars == 3


# ── 8. Economic Realism: Fee & Slippage Subtraction ───────────────────────────

def test_8_economic_realism_fees():
    fee_rate = 0.0005     # 5 bps
    slippage_rate = 0.0002 # 2 bps
    # Roundtrip cost = 2 * (0.0005 + 0.0002) = 0.0014 (14 bps)
    label_spec = TripleBarrierSpec(
        take_profit_pct=0.02,
        stop_loss_pct=0.01,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
    )
    label_factory = TripleBarrierLabelFactory(label_spec)

    c0 = create_synthetic_candle("2026-04-01T00:00:00Z", 100, 101, 99, 100)
    c1 = create_synthetic_candle("2026-04-01T00:15:00Z", 100, 102.5, 99.5, 102.0)  # Hits TP at 102.0
    labels = label_factory.compute_labels([c0, c1])
    lbl = labels[0]
    assert lbl is not None
    assert lbl.gross_return == 0.02
    assert math.isclose(lbl.total_cost, 0.0014, rel_tol=1e-6)
    expected_net = 0.02 - 0.0014
    assert math.isclose(lbl.net_return, expected_net, rel_tol=1e-6)


# ── 9. Purging Metadata & Zero Future Leakage ─────────────────────────────────

def test_9_purging_metadata_and_leakage_invariance():
    label_spec = TripleBarrierSpec(take_profit_pct=0.02, stop_loss_pct=0.02, max_holding_bars=2)
    label_factory = TripleBarrierLabelFactory(label_spec)

    candles = [
        create_synthetic_candle("2026-04-01T00:00:00Z", 100, 101, 99, 100),
        create_synthetic_candle("2026-04-01T00:15:00Z", 100, 101, 99, 100),
        create_synthetic_candle("2026-04-01T00:30:00Z", 100, 103, 99, 102),  # Hits TP
    ]
    labels = label_factory.compute_labels(candles)
    lbl = labels[0]
    assert lbl is not None
    # Purge window covers from entry bar open to exit bar close
    assert lbl.label_start_time == "2026-04-01T00:15:00Z"
    assert lbl.label_end_time == "2026-04-01T00:45:00Z"

    # Leakage test on features:
    spec = build_m3_standard_feature_spec("dummy_hash")
    factory = FeatureFactory(spec)

    f_orig = factory.compute_batch_features(candles[:2])
    # Add an extreme future candle at t=2
    candles_mutated = list(candles[:2]) + [create_synthetic_candle("2026-04-01T00:30:00Z", 999999, 999999, 1, 999999)]
    f_mutated = factory.compute_batch_features(candles_mutated)

    # Features at t=0 and t=1 must remain 100% IDENTICAL despite catastrophic future mutation
    for t_idx in (0, 1):
        for fname in M3_STANDARD_FEATURE_NAMES:
            assert f_orig[t_idx][fname] == f_mutated[t_idx][fname]


# ── 10. Research Pilot: Aligned Dataset on Real BTC/ETH Data ───────────────────

def test_10_research_pilot_verified_dataset(dataset_provider, canonical_manifest):
    """Generates an aligned research dataset on real historical BTC 15m data with HTF 1h context."""
    feature_spec = build_m3_standard_feature_spec(
        dataset_manifest_hash=canonical_manifest.manifest_content_hash,
        feature_set_id="m3_pilot_btc_v1",
        symbol_universe=["BTC"],
        base_timeframe="15m",
        higher_timeframes=["1h"],
    )
    label_spec = TripleBarrierSpec(
        take_profit_pct=0.015,
        stop_loss_pct=0.010,
        max_holding_bars=16,
    )

    # Ingest 7 days of 15m BTC data (2026-04-01 to 2026-04-07)
    aligned_ds = ResearchDatasetFactory.build_aligned_dataset(
        provider=dataset_provider,
        feature_spec=feature_spec,
        label_spec=label_spec,
        symbol="BTCUSDT",
        start_time="2026-04-01T00:00:00Z",
        end_time="2026-04-07T23:59:59Z",
        min_warmup_bars=60,
    )

    assert len(aligned_ds) > 500
    assert aligned_ds.funnel is not None
    assert aligned_ds.funnel.final_research_samples == len(aligned_ds)
    assert aligned_ds.funnel.invalid_feature_rows == 0
    assert aligned_ds.funnel.unresolved_labels_dropped == 0
    X, y, net_returns = aligned_ds.to_numpy()

    # Dimension checks
    assert X.shape[0] == len(aligned_ds)
    assert X.shape[1] == len(feature_spec.feature_names)
    assert len(y) == len(aligned_ds)
    assert len(net_returns) == len(aligned_ds)

    # Zero NaNs, zero Infs
    assert not np.isnan(X).any(), "NaN values detected in feature matrix!"
    assert not np.isinf(X).any(), "Infinite values detected in feature matrix!"
    assert not np.isnan(net_returns).any(), "NaN values detected in returns!"

    # Label distribution sanity
    classes = set(y)
    assert len(classes) >= 2, f"Expected active label classes, got {classes}"
    for c in (-1, 0, 1):
        count = int(np.sum(y == c))
        print(f"Class {c:2d}: {count:4d} samples ({count / len(y) * 100:.1f}%)")

    # Purge intervals sanity
    for start_p, end_p in aligned_ds.purge_intervals:
        assert start_p < end_p
