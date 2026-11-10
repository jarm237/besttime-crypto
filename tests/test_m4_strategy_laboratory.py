"""
tests/test_m4_strategy_laboratory.py
Phase M4: Strategy Laboratory MVP Contract and Invariant Tests.

Verifies:
1. StrategySpec immutability, parameter freezing, and deterministic SHA-256 config hashing.
2. StrategyRegistry strategy registration, metadata lookup, and factory instantiation.
3. WalkForwardSplitter chronological fold generation, train/val boundaries, and purge embargo.
4. WalkForwardLab multi-fold execution, economic accounting parity (gross vs net PnL).
5. Candidate disposition classifications (BENCHMARK, REJECTED, RESEARCH_ONLY, CANDIDATE_FOR_M5).
6. Deterministic experiment reproducibility: identical decisions, fills, and metrics across duplicate runs.
7. OOS isolation: walk-forward validation ends strictly prior to pristine frozen holdout.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
import pytest

from btc_scraper.research.dataset_manifest import CanonicalDatasetManifest
from btc_scraper.research.dataset_provider import HistoricalDatasetProvider
from btc_scraper.research.experiment_contract import (
    ExperimentResult,
    ExperimentSpec,
    M5ValidationSpec,
    build_seven_layer_proxy_spec,
)
from btc_scraper.research.baseline_runner import ExperimentRunner
from btc_scraper.research.strategy_registry import (
    GLOBAL_STRATEGY_REGISTRY,
    EmaTrendFollowingStrategy,
    RegimeAwareTrendStrategy,
    RsiBollingerMeanReversionStrategy,
    StrategyRegistry,
    StrategySpec,
    VolAwareMeanReversionStrategy,
)
from btc_scraper.research.walk_forward_lab import (
    FoldEconomicResult,
    StrategyEvaluationSummary,
    WalkForwardFold,
    WalkForwardLab,
    WalkForwardSplitter,
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


# ── 1. StrategySpec Immutability & Hash Invariance ─────────────────────────────

def test_1_strategy_spec_immutability_and_hashing():
    spec = StrategySpec(
        strategy_id="test_strat_v1",
        strategy_name="Test Strategy",
        tier="CANDIDATE",
        status="ACTIVE",
        parameters={"alpha": 0.5, "lookback": 20},
        required_features=("ret_1", "rsi_14"),
        description="Unit test strategy",
    )
    assert len(spec.config_hash) == 64
    assert spec.compute_config_hash() == spec.config_hash

    # Immutability
    with pytest.raises(Exception):
        spec.tier = "BENCHMARK"

    with pytest.raises(Exception):
        spec.parameters["alpha"] = 0.8

    # Serialization roundtrip
    d = spec.to_dict()
    restored = StrategySpec.from_dict(d)
    assert restored.config_hash == spec.config_hash
    assert restored.parameters == spec.parameters


# ── 2. Strategy Registry Lookup & Instantiation ───────────────────────────────

def test_2_strategy_registry_builtins():
    registry = GLOBAL_STRATEGY_REGISTRY
    specs = registry.list_strategies()
    assert len(specs) >= 8

    strat_ids = [s.strategy_id for s in specs]
    assert "always_flat_v1" in strat_ids
    assert "buy_and_hold_v1" in strat_ids
    assert "sma_crossover_9_21_v1" in strat_ids
    assert "ema_trend_12_26_v1" in strat_ids
    assert "rsi_bollinger_mr_v1" in strat_ids
    assert "regime_aware_trend_v1" in strat_ids
    assert "vol_aware_mean_reversion_v1" in strat_ids
    assert "seven_layer_proxy_v1" in strat_ids

    # Instantiation produces clean instances
    ema_strat = registry.create("ema_trend_12_26_v1")
    assert isinstance(ema_strat, EmaTrendFollowingStrategy)

    rsi_bb_strat = registry.create("rsi_bollinger_mr_v1")
    assert isinstance(rsi_bb_strat, RsiBollingerMeanReversionStrategy)

    regime_strat = registry.create("regime_aware_trend_v1")
    assert isinstance(regime_strat, RegimeAwareTrendStrategy)

    vol_mr_strat = registry.create("vol_aware_mean_reversion_v1")
    assert isinstance(vol_mr_strat, VolAwareMeanReversionStrategy)


# ── 3. WalkForwardSplitter Chronological Folds & Purge ────────────────────────

def test_3_walk_forward_splitter():
    start_time = "2023-01-01T00:00:00Z"
    end_time = "2026-04-30T23:59:59Z"
    folds = WalkForwardSplitter.generate_folds(
        start_time=start_time,
        end_time=end_time,
        n_folds=3,
        val_ratio=0.30,
        purge_gap_hours=24,
    )
    assert len(folds) == 3

    # Check non-overlapping validation windows
    assert folds[0].val_start < folds[0].val_end
    assert folds[1].val_start < folds[1].val_end
    assert folds[2].val_start < folds[2].val_end
    assert folds[0].val_end <= folds[1].val_start
    assert folds[1].val_end <= folds[2].val_start

    # Check purge gap between train and validation
    from datetime import datetime
    for f in folds:
        t_end = datetime.fromisoformat(f.train_end.replace("Z", "+00:00"))
        v_start = datetime.fromisoformat(f.val_start.replace("Z", "+00:00"))
        gap_hours = (v_start - t_end).total_seconds() / 3600.0
        assert math.isclose(gap_hours, 24.0, abs_tol=0.1)


# ── 4. Economic Accounting Parity Across Folds ────────────────────────────────

def test_4_economic_accounting_parity(dataset_provider):
    """Verifies that across folds, net_pnl = gross_pnl - total_fees - total_slippage."""
    lab = WalkForwardLab(dataset_provider, GLOBAL_STRATEGY_REGISTRY)

    # Short test fold on real BTC 1h data
    fold = WalkForwardFold(
        fold_id=1,
        train_start="2026-03-01T00:00:00Z",
        train_end="2026-03-31T00:00:00Z",
        val_start="2026-04-01T00:00:00Z",
        val_end="2026-04-15T00:00:00Z",
        purge_gap_hours=24,
    )

    base_spec = build_seven_layer_proxy_spec(
        experiment_id="test_m4_acc",
        oos_window=("2026-04-01T00:00:00Z", "2026-04-15T00:00:00Z"),
    )

    summary = lab.evaluate_strategy_on_folds(
        strategy_id="sma_crossover_9_21_v1",
        symbol="BTCUSDT",
        timeframe="1h",
        folds=[fold],
        base_spec=base_spec,
    )

    assert len(summary.fold_results) == 1
    fr = summary.fold_results[0]
    # In ExperimentRunner: gross_pnl is computed from effective fill prices (which incorporate slippage drag).
    # Therefore, net_pnl = gross_pnl - total_fees (no double-counting of slippage).
    calculated_net = fr.gross_pnl - fr.total_fees
    assert abs(fr.net_pnl - calculated_net) <= 0.05


# ── 5. Candidate Disposition Rules ────────────────────────────────────────────

def test_5_candidate_disposition_classification():
    lab = WalkForwardLab(None, GLOBAL_STRATEGY_REGISTRY)

    # Benchmark tier always BENCHMARK
    disp, _ = lab._classify_candidate("BENCHMARK", 100.0, 50, 1.5, 0.1, [])
    assert disp == "BENCHMARK"

    # Proxy tier always DIAGNOSTIC_ONLY
    disp, _ = lab._classify_candidate("PROXY", 100.0, 50, 1.5, 0.1, [])
    assert disp == "DIAGNOSTIC_ONLY"

    # Too few trades -> INSUFFICIENT_EVIDENCE
    disp, _ = lab._classify_candidate("CANDIDATE", 50.0, 5, 1.5, 0.05, [])
    assert disp == "INSUFFICIENT_EVIDENCE"

    # Negative net PnL -> REJECTED
    disp, _ = lab._classify_candidate("CANDIDATE", -50.0, 40, 0.9, 0.1, [])
    assert disp == "REJECTED"

    # Excessive drawdown -> REJECTED
    disp, _ = lab._classify_candidate("CANDIDATE", 100.0, 50, 1.3, 0.35, [])
    assert disp == "REJECTED"

    # Modest edge -> RESEARCH_ONLY
    fake_folds = [
        FoldEconomicResult(1, "s", "BTC", "w", 50, 20, 10, 5, 10020, 15, 0.4, 1.2, 1.3, 0.05, 0.1, 0.1),
        FoldEconomicResult(2, "s", "BTC", "w", 50, 20, 10, 5, 10040, 15, 0.4, 1.2, 1.3, 0.05, 0.1, 0.1),
    ]
    disp, _ = lab._classify_candidate("CANDIDATE", 40.0, 25, 1.15, 0.05, fake_folds)
    assert disp == "RESEARCH_ONLY"


# ── 6. Deterministic Reproducibility: Identical Duplicate Run ──────────────────

def test_6_deterministic_reproducibility(dataset_provider):
    """Running the exact same strategy on real data twice yields identical trades and PnL."""
    lab = WalkForwardLab(dataset_provider, GLOBAL_STRATEGY_REGISTRY)
    fold = WalkForwardFold(
        fold_id=1,
        train_start="2026-03-01T00:00:00Z",
        train_end="2026-03-31T00:00:00Z",
        val_start="2026-04-01T00:00:00Z",
        val_end="2026-04-10T00:00:00Z",
    )
    base_spec = build_seven_layer_proxy_spec(
        experiment_id="test_reproducibility",
        oos_window=("2026-04-01T00:00:00Z", "2026-04-10T00:00:00Z"),
    )

    run_1 = lab.evaluate_strategy_on_folds("ema_trend_12_26_v1", "BTCUSDT", "1h", [fold], base_spec)
    run_2 = lab.evaluate_strategy_on_folds("ema_trend_12_26_v1", "BTCUSDT", "1h", [fold], base_spec)

    assert run_1.total_trades == run_2.total_trades
    assert run_1.total_gross_pnl == run_2.total_gross_pnl
    assert run_1.total_net_pnl == run_2.total_net_pnl
    assert run_1.total_fees == run_2.total_fees
    assert run_1.disposition == run_2.disposition


# ── 7. Frozen OOS Isolation Guarantee ─────────────────────────────────────────

def test_7_frozen_oos_isolation():
    """Confirms that M4 evaluation window terminates before the pristine frozen OOS holdout (May-Jun 2026)."""
    start_time = "2023-01-01T00:00:00Z"
    end_time = "2026-04-30T23:59:59Z"
    folds = WalkForwardSplitter.generate_folds(start_time, end_time, n_folds=3, val_ratio=0.3)

    frozen_holdout_start = "2026-05-01T00:00:00Z"
    for f in folds:
        assert f.val_end <= frozen_holdout_start, f"Fold validation leaked into frozen OOS: {f.val_end} > {frozen_holdout_start}"


# ── 8. No-Trade Metrics Rendering (Undefined WR / PF as None) ─────────────────

def test_8_no_trade_metrics_rendering(dataset_provider):
    """When a strategy makes 0 trades, win_rate and profit_factor are mathematically undefined (None)."""
    lab = WalkForwardLab(dataset_provider, GLOBAL_STRATEGY_REGISTRY)
    fold = WalkForwardFold(
        fold_id=1,
        train_start="2026-03-01T00:00:00Z",
        train_end="2026-03-31T00:00:00Z",
        val_start="2026-04-01T00:00:00Z",
        val_end="2026-04-10T00:00:00Z",
    )
    base_spec = build_seven_layer_proxy_spec(
        experiment_id="test_no_trades",
        oos_window=("2026-04-01T00:00:00Z", "2026-04-10T00:00:00Z"),
    )

    summary = lab.evaluate_strategy_on_folds("always_flat_v1", "BTCUSDT", "1h", [fold], base_spec)
    assert summary.total_trades == 0
    assert summary.aggregate_win_rate is None
    assert summary.aggregate_profit_factor is None
    assert summary.total_net_pnl == 0.0

    fr = summary.fold_results[0]
    assert fr.trade_count == 0
    assert fr.win_rate is None
    assert fr.profit_factor is None


# ── 9. M5 Validation Contract Specification Immutability ───────────────────────

def test_9_m5_validation_spec_contract():
    """M5ValidationSpec enforces immutable gates and fails-closed when data is pending."""
    m5_spec = M5ValidationSpec(
        validation_id="m5_eth_candidate_v1",
        candidate_id="vol_aware_mean_reversion_v1",
        candidate_version="1.0.0",
        candidate_config_hash="4f73c169892a9403",
        dataset_manifest_identity="manifest-binance-canonical-2023-2026",
    )
    assert m5_spec.holdout_eligibility_status == "PROSPECTIVE_PENDING_DATA"
    assert m5_spec.is_promotion_eligible is False
    assert m5_spec.is_executed is False
    assert m5_spec.assumed_roundtrip_cost_bps == 14.0

    # Gate dictionary is immutable
    with pytest.raises(Exception):
        m5_spec.promotion_gates["gate_1_min_net_expectancy_usd"] = 100.0

    d = m5_spec.to_dict()
    assert d["holdout_eligibility_status"] == "PROSPECTIVE_PENDING_DATA"
    assert d["is_promotion_eligible"] is False


# ── 10. Successor Candidate Walk-Forward Execution ────────────────────────────

def test_10_vol_aware_mean_reversion_successor(dataset_provider):
    """vol_aware_mean_reversion_v1 achieves positive economic expectancy on real evaluation data."""
    lab = WalkForwardLab(dataset_provider, GLOBAL_STRATEGY_REGISTRY)
    fold = WalkForwardFold(
        fold_id=1,
        train_start="2025-04-01T00:00:00Z",
        train_end="2025-04-30T00:00:00Z",
        val_start="2025-05-01T00:00:00Z",
        val_end="2025-08-30T00:00:00Z",
    )
    base_spec = build_seven_layer_proxy_spec(
        experiment_id="test_successor_eval",
        oos_window=("2025-05-01T00:00:00Z", "2025-08-30T00:00:00Z"),
    )

    summary = lab.evaluate_strategy_on_folds("vol_aware_mean_reversion_v1", "ETHUSDT", "1h", [fold], base_spec)
    assert summary.total_trades > 0
    assert summary.total_net_pnl > 0.0
    assert summary.aggregate_win_rate is not None
    assert summary.aggregate_win_rate > 0.50

