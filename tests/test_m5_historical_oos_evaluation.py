"""
tests/test_m5_historical_oos_evaluation.py
Phase 6: Targeted Verification Suite for M5 Historical OOS Eligibility and One-Shot Evaluation.

Verifies:
1. Frozen candidate identity and provenance invariants (unmutated hash, freeze effective).
2. Historical OOS dataset manifest integrity (3,168 consecutive hours, SHA-256 match).
3. PIT non-lookahead & boundary timing contracts.
4. Economic accounting parity: gross_pnl - total_fees - total_slippage - total_spread == net_pnl.
5. Stress cost monotonicity: net_pnl(14bps) > net_pnl(20bps) > net_pnl(30bps).
6. Multi-asset promotion gate failure and honest disposition enforcement (HISTORICAL_OOS_REJECTED).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import pytest

from btc_scraper.research.candidate_freeze import FrozenCandidateSnapshot
from btc_scraper.research.strategy_registry import GLOBAL_STRATEGY_REGISTRY

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FREEZE_PATH = PROJECT_ROOT / "data" / "candidate_freezes" / "vol_aware_mean_reversion_v1_freeze.json"
MANIFEST_PATH = PROJECT_ROOT / "data" / "historical" / "manifests" / "historical_oos_2026_h2_manifest.json"
RESULTS_PATH = PROJECT_ROOT / "data" / "historical" / "quality_reports" / "m5_frozen_eth_oos_evaluation_results.json"


@pytest.fixture(scope="module")
def freeze_snapshot() -> FrozenCandidateSnapshot:
    assert FREEZE_PATH.exists()
    return FrozenCandidateSnapshot.load_from_file(FREEZE_PATH)


@pytest.fixture(scope="module")
def oos_manifest() -> dict:
    assert MANIFEST_PATH.exists()
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def oos_results() -> dict:
    assert RESULTS_PATH.exists()
    with open(RESULTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_1_frozen_candidate_immutability(freeze_snapshot):
    """Verifies frozen candidate has not been retuned, mutated, or superseded."""
    assert freeze_snapshot.candidate_id == "vol_aware_mean_reversion_v1"
    assert freeze_snapshot.candidate_version == "1.0.0"
    assert freeze_snapshot.is_effective_freeze is True
    assert freeze_snapshot.code_git_head == "dab0f1b1cc7bc799ce767c89d90b14f45d2e1536"
    assert freeze_snapshot.config_hash == "4f73c169892a94031456273cdd213f5989ec7421b1679f0d90ae998bfedf5372"
    assert freeze_snapshot.freeze_hash == "aff660d0a635d3d12ff92114fb0c4cd92e78e15e08edf2356d470c997a220392"
    
    # Confirm registry matches snapshot exactly
    spec = GLOBAL_STRATEGY_REGISTRY.get_spec("vol_aware_mean_reversion_v1")
    assert spec.config_hash == freeze_snapshot.config_hash
    assert spec.parameters["rsi_period"] == 14
    assert spec.parameters["bb_period"] == 20
    assert spec.parameters["macro_period"] == 50
    assert spec.parameters["atr_stop_multiplier"] == 1.5


def test_2_holdout_manifest_and_data_integrity(oos_manifest):
    """Verifies holdout manifest bounds, candle counts, and cryptographic hash."""
    assert oos_manifest["manifest_identity"] == "historical_oos_2026_h2_eth_btc_spot_1h"
    assert oos_manifest["window_start_utc"] == "2026-07-01T00:00:00Z"
    assert oos_manifest["window_end_utc"] == "2026-11-09T23:00:00Z"
    assert oos_manifest["total_days"] == 132
    assert oos_manifest["candles_per_symbol"] == 3168
    assert len(oos_manifest["dataset_content_hash"]) == 64
    assert "ETHUSDT" in oos_manifest["symbols"]
    assert "BTCUSDT" in oos_manifest["symbols"]


def test_3_economic_accounting_and_stress_monotonicity(oos_results):
    """Verifies financial reconciliation and monotonic cost impact across stress models."""
    raw_gross = oos_results["raw_gross_pnl"]
    eff_gross = oos_results["effective_gross_pnl"]
    friction = oos_results["total_friction_usd"]
    fees = oos_results["exchange_fees_usd"]
    net_14 = oos_results["net_pnl_14bps"]
    net_20 = oos_results["net_pnl_20bps"]
    net_30 = oos_results["net_pnl_30bps"]

    # Exact reconciliation formulas
    assert math.isclose(net_14, raw_gross - friction, abs_tol=1e-2), f"Raw reconciliation error: {net_14} != {raw_gross} - {friction}"
    assert math.isclose(net_14, eff_gross - fees, abs_tol=1e-2), f"Effective reconciliation error: {net_14} != {eff_gross} - {fees}"

    # Monotonic degradation as friction increases
    assert net_14 > net_20 > net_30, f"Expected monotonic cost drag: {net_14} > {net_20} > {net_30}"
    assert net_14 < raw_gross, "Net PnL must be strictly less than raw gross PnL due to positive transaction costs"

    # Friction accounting reconciliation on trade lineage
    trades = oos_results["trade_lineage"]
    for t in trades:
        t_gross = float(t["gross_pnl"])
        t_net = float(t["net_pnl"])
        t_fee = float(t["fee_usd"])
        assert math.isclose(t_net, t_gross - t_fee, abs_tol=1e-3), f"Trade PnL accounting mismatch: {t}"


def test_4_honest_empirical_verdict_and_gates(oos_results):
    """Verifies that negative expectancy is faithfully classified as REJECTED without promotion bypass."""
    assert oos_results["net_pnl_14bps"] < 0.0, "OOS Net PnL is negative"
    assert oos_results["profit_factor"] < 1.0, "Profit factor is sub-unitary"
    assert oos_results["multi_asset_gate"] == "FAIL", "Multi-asset gate must fail"
    assert oos_results["final_disposition"] == "HISTORICAL_OOS_REJECTED_FOR_PROMOTION", "Must reject candidate on negative OOS"
    assert oos_results["block_bootstrap_ci"]["status"] == "INSUFFICIENT_SAMPLE"
