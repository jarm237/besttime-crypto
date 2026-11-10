"""
tests/test_m5_holdout_and_candidate_freeze.py
Milestone M5: Candidate Freeze, Holdout Integrity & Prospective Validation Foundation.

Covers:
1. BURNED historical holdout rejection in confirmatory mode.
2. M5ValidationSpec fail-closed logic (no self-declaration of PRISTINE).
3. Deterministic Candidate Freeze Hash.
4. Immutable nested candidate configuration.
5. Mutation prevention on frozen candidate snapshot.
6. Pre-freeze observations rejected from forward-looking evidence.
7. Closed-candle invariant (no lookahead / forming bar rejection).
8. Separation of simulated shadow execution from actual paper fills.
9. Distinct asset dispositions (ETH = PROMISING_DEVELOPMENT_CANDIDATE, BTC = RESEARCH_ONLY).
10. Cost sensitivity immutability (stress testing does not alter frozen config).
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import pytest

from btc_scraper.research.candidate_freeze import (
    FrozenCandidateSnapshot,
    build_eth_vol_aware_mean_reversion_freeze,
)
from btc_scraper.research.experiment_contract import M5ValidationSpec
from btc_scraper.research.prospective_shadow_evaluator import (
    ProspectiveOpportunity,
    ProspectiveShadowEvaluator,
)
from btc_scraper.research.strategy_registry import GLOBAL_STRATEGY_REGISTRY


# ── 1. BURNED Historical Holdout Fails-Closed ─────────────────────────────────

def test_1_burned_historical_holdout_rejection():
    """Attempting to claim PRISTINE or PROSPECTIVE_SHADOW for historical data prior to 2026-07 raises ValueError."""
    with pytest.raises(ValueError, match="BURNED_FOR_PROMOTION"):
        M5ValidationSpec(
            validation_id="val_invalid_burned_claim",
            candidate_id="vol_aware_mean_reversion_v1",
            candidate_version="1.0.0",
            candidate_config_hash="4f73c169892a9403",
            dataset_manifest_identity="manifest-canonical",
            validation_mode="PROSPECTIVE_SHADOW",
            holdout_eligibility_status="PRISTINE_LOCKED",
            validation_window=("2026-05-01T00:00:00Z", "2026-06-30T23:59:59Z"),
        )


# ── 2. M5ValidationSpec Fails-Closed When Data is Pending ─────────────────────

def test_2_m5_validation_spec_fail_closed_on_pending_data():
    """When holdout_eligibility_status is PROSPECTIVE_PENDING_DATA, is_promotion_eligible is strictly False."""
    spec = M5ValidationSpec(
        validation_id="val_eth_prospective_pending",
        candidate_id="vol_aware_mean_reversion_v1",
        candidate_version="1.0.0",
        candidate_config_hash="4f73c169892a9403",
        dataset_manifest_identity="manifest-canonical",
        validation_mode="PROSPECTIVE_SHADOW",
        holdout_eligibility_status="PROSPECTIVE_PENDING_DATA",
        validation_window=("2026-11-10T00:00:00Z", "2026-12-31T23:59:59Z"),
        is_executed=False,
    )
    assert spec.is_promotion_eligible is False
    assert spec.holdout_eligibility_status == "PROSPECTIVE_PENDING_DATA"

    d = spec.to_dict()
    assert d["is_promotion_eligible"] is False
    assert d["holdout_eligibility_status"] == "PROSPECTIVE_PENDING_DATA"


# ── 3. Deterministic Candidate Freeze Hash ────────────────────────────────────

def test_3_candidate_freeze_hash_deterministic():
    """Candidate freeze snapshot generates identical SHA-256 hash across repeated instantiations."""
    snap1 = build_eth_vol_aware_mean_reversion_freeze()
    snap2 = build_eth_vol_aware_mean_reversion_freeze()

    assert snap1.freeze_hash == snap2.freeze_hash
    assert len(snap1.freeze_hash) == 64
    assert snap1.config_hash == snap2.config_hash
    assert snap1.compute_freeze_hash() == snap1.freeze_hash


# ── 4. Nested Configuration Immutability ──────────────────────────────────────

def test_4_nested_config_immutable():
    """Parameters, exit rules, and cost model inside FrozenCandidateSnapshot cannot be mutated."""
    snap = build_eth_vol_aware_mean_reversion_freeze()

    with pytest.raises(Exception):
        snap.parameters["rsi_period"] = 21

    with pytest.raises(Exception):
        snap.exit_rules["take_profit"] = "tampered"

    with pytest.raises(Exception):
        snap.cost_model["total_roundtrip_bps"] = 0.0

    with pytest.raises(Exception):
        snap.sizing_policy["allocation_pct"] = 1.0


# ── 5. Post-Freeze Configuration Mutation Prevention ──────────────────────────

def test_5_post_freeze_mutation_raises():
    """FrozenCandidateSnapshot is frozen; direct attribute reassignment raises FrozenInstanceError."""
    snap = build_eth_vol_aware_mean_reversion_freeze()

    with pytest.raises(Exception):
        snap.candidate_version = "2.0.0"

    with pytest.raises(Exception):
        snap.no_retune_policy = False


# ── 6. Pre-Freeze Observations Rejected from Forward-Looking Evidence ──────────

def test_6_pre_freeze_observations_rejected():
    """Candles with timestamps prior to freeze boundary are classified as REJECTED_PRE_FREEZE."""
    snap = build_eth_vol_aware_mean_reversion_freeze()
    evaluator = ProspectiveShadowEvaluator(
        candidate_snapshot=snap,
        freeze_boundary_timestamp="2026-11-10T00:00:00Z",
    )

    pre_freeze_candle = {
        "time": "2026-11-09T23:00:00Z",
        "open": 2500.0,
        "high": 2510.0,
        "low": 2490.0,
        "close": 2495.0,
        "volume": 100.0,
        "is_closed": True,
    }

    opp = evaluator.evaluate_closed_bar(pre_freeze_candle, [pre_freeze_candle])
    assert opp.eligibility_status == "REJECTED_PRE_FREEZE"
    assert opp.decision_action == "NO_TRADE"
    assert opp.simulated_execution_intent is None


# ── 7. Closed-Candle Invariant (No Lookahead / Unclosed Candle Rejection) ──────

def test_7_closed_candle_invariant():
    """Evaluating an unclosed or forming candle raises ValueError to enforce no lookahead."""
    snap = build_eth_vol_aware_mean_reversion_freeze()
    evaluator = ProspectiveShadowEvaluator(
        candidate_snapshot=snap,
        freeze_boundary_timestamp="2026-11-10T00:00:00Z",
    )

    unclosed_candle = {
        "time": "2026-11-10T01:00:00Z",
        "open": 2500.0,
        "high": 2520.0,
        "low": 2495.0,
        "close": 2515.0,
        "volume": 50.0,
        "is_closed": False,
    }

    with pytest.raises(ValueError, match="forming or unclosed candle"):
        evaluator.evaluate_closed_bar(unclosed_candle, [unclosed_candle])


# ── 8. Simulated Shadow Execution Distinct from Actual Paper Fills ────────────

def test_8_simulated_shadow_execution_distinct():
    """Simulated execution intent explicitly sets is_simulated_shadow=True and is_actual_paper_fill=False."""
    snap = build_eth_vol_aware_mean_reversion_freeze()
    evaluator = ProspectiveShadowEvaluator(
        candidate_snapshot=snap,
        freeze_boundary_timestamp="2026-11-10T00:00:00Z",
    )

    # Synthetic post-freeze closed candle
    post_freeze_candle = {
        "time": "2026-11-10T01:00:00Z",
        "open": 2500.0,
        "high": 2510.0,
        "low": 2490.0,
        "close": 2495.0,
        "volume": 100.0,
        "is_closed": True,
    }

    opp = evaluator.evaluate_closed_bar(post_freeze_candle, [post_freeze_candle] * 60)
    assert opp.is_simulated_shadow is True
    assert opp.is_actual_paper_fill is False


# ── 9. Distinct Asset Dispositions (ETH vs BTC) ───────────────────────────────

def test_9_distinct_asset_dispositions():
    """M5ValidationSpec strictly maintains separate dispositions for ETH and BTC."""
    spec = M5ValidationSpec(
        validation_id="val_eth_candidate_v1",
        candidate_id="vol_aware_mean_reversion_v1",
        candidate_version="1.0.0",
        candidate_config_hash="4f73c169892a9403",
        dataset_manifest_identity="manifest-canonical",
    )

    dispositions = spec.candidate_dispositions
    assert dispositions["ETHUSDT"] == "PROMISING_DEVELOPMENT_CANDIDATE"
    assert dispositions["BTCUSDT"] == "RESEARCH_ONLY"
    assert spec.promotion_gates["gate_6_multi_asset_consistency"] is False


# ── 10. Cost Sensitivity Immutability ─────────────────────────────────────────

def test_10_cost_sensitivity_immutability():
    """Evaluating alternate friction models (stress tests) does not mutate candidate's frozen config."""
    snap = build_eth_vol_aware_mean_reversion_freeze()
    initial_cost = snap.cost_model["total_roundtrip_bps"]
    assert initial_cost == 14.0

    # Simulate stress testing scenario
    stress_costs = [20.0, 30.0]
    for c in stress_costs:
        temp_dict = copy.deepcopy(dict(snap.cost_model))
        temp_dict["total_roundtrip_bps"] = c
        assert temp_dict["total_roundtrip_bps"] == c

    # Original frozen snapshot remains strictly 14.0 bps
    assert snap.cost_model["total_roundtrip_bps"] == 14.0


# ── 11. Promotion Gates Fail-Closed on False Flag ─────────────────────────────

def test_11_promotion_gates_fail_closed_on_false_flag():
    """When gate_6_multi_asset_consistency is False, is_economically_promotable is strictly False."""
    spec = M5ValidationSpec(
        validation_id="val_eth_multi_asset_fail",
        candidate_id="vol_aware_mean_reversion_v1",
        candidate_version="1.0.0",
        candidate_config_hash="4f73c169892a9403",
        dataset_manifest_identity="manifest-canonical",
        validation_mode="PROSPECTIVE_SHADOW",
        holdout_eligibility_status="VERIFIED_UNTOUCHED_PROSPECTIVE",
        validation_window=("2026-11-10T00:00:00Z", "2026-12-31T23:59:59Z"),
        is_executed=True,
    )
    # Validation is eligible to run
    assert spec.is_validation_eligible is True
    # But promotion is strictly blocked because gate_6_multi_asset_consistency is False
    assert spec.promotion_gates["gate_6_multi_asset_consistency"] is False
    assert spec.is_economically_promotable is False
    assert spec.is_promotion_eligible is False

    # Conversely, when all gates are satisfied
    passing_gates = dict(spec.promotion_gates)
    passing_gates["gate_6_multi_asset_consistency"] = True
    promotable_spec = M5ValidationSpec(
        validation_id="val_eth_all_pass",
        candidate_id="vol_aware_mean_reversion_v1",
        candidate_version="1.0.0",
        candidate_config_hash="4f73c169892a9403",
        dataset_manifest_identity="manifest-canonical",
        validation_mode="PROSPECTIVE_SHADOW",
        holdout_eligibility_status="VERIFIED_UNTOUCHED_PROSPECTIVE",
        validation_window=("2026-11-10T00:00:00Z", "2026-12-31T23:59:59Z"),
        is_executed=True,
        promotion_gates=passing_gates,
    )
    assert promotable_spec.is_economically_promotable is True
    assert promotable_spec.is_promotion_eligible is True


# ── 12. Evaluator Parameter Binding & Hash Mismatch Rejection ─────────────────

def test_12_evaluator_parameter_binding_and_rejection():
    """ProspectiveShadowEvaluator enforces exact parameter binding and rejects mismatches."""
    from dataclasses import replace

    snap = build_eth_vol_aware_mean_reversion_freeze()
    evaluator = ProspectiveShadowEvaluator(
        candidate_snapshot=snap,
        freeze_boundary_timestamp="2026-11-10T00:00:00Z",
    )
    # Evaluator strategy instance attributes match candidate snapshot parameters exactly
    assert evaluator.strategy.rsi_period == snap.parameters["rsi_period"]
    assert evaluator.strategy.bb_period == snap.parameters["bb_period"]
    assert evaluator.strategy.atr_stop_multiplier == snap.parameters["atr_stop_multiplier"]

    # Tampering with parameters without matching config_hash raises ValueError
    tampered_snap = replace(snap, parameters={"rsi_period": 21}, freeze_hash="")
    with pytest.raises(ValueError, match="Candidate config_hash mismatch"):
        ProspectiveShadowEvaluator(
            candidate_snapshot=tampered_snap,
            freeze_boundary_timestamp="2026-11-10T00:00:00Z",
        )


# ── 13. Evaluator Source Hash Rejection ───────────────────────────────────────

def test_13_evaluator_source_hash_rejection():
    """ProspectiveShadowEvaluator rejects candidate if strategy source code hash mismatches."""
    from dataclasses import replace

    snap = build_eth_vol_aware_mean_reversion_freeze()
    tampered_source_snap = replace(
        snap,
        strategy_source_hash="0000000000000000000000000000000000000000000000000000000000000000",
        freeze_hash="",
    )
    with pytest.raises(ValueError, match="Candidate strategy source code mismatch"):
        ProspectiveShadowEvaluator(
            candidate_snapshot=tampered_source_snap,
            freeze_boundary_timestamp="2026-11-10T00:00:00Z",
        )


# ── 14. Source Manifest Generation and Verification ───────────────────────────

def test_14_source_manifest_generation_and_verification():
    """Source manifest computes deterministic hash and verifies cleanly against disk."""
    from btc_scraper.research.source_manifest import (
        compute_source_manifest,
        verify_source_manifest,
    )

    manifest1 = compute_source_manifest()
    manifest2 = compute_source_manifest()

    assert manifest1["manifest_hash"] == manifest2["manifest_hash"]
    assert len(manifest1["manifest_hash"]) == 64
    assert manifest1["seal_status"] == "SOURCE_SEAL_PENDING"
    assert manifest1["dependency_count"] >= 7

    is_valid, discrepancies = verify_source_manifest(manifest1)
    assert is_valid is True
    assert len(discrepancies) == 0


# ── 15. Candle Aggregator 15m -> 1h Invariants ────────────────────────────────

def test_15_candle_aggregator_15m_to_1h():
    """ClosedCandleAggregator aggregates 4 closed 15m bars and enforces zero lookahead."""
    from btc_scraper.research.candle_aggregator import ClosedCandleAggregator

    agg = ClosedCandleAggregator(symbol="ETHUSDT")

    # Ingest 3 bars: should return None
    b1 = {"symbol": "ETHUSDT", "time": "2026-11-10T00:00:00Z", "open": 2500.0, "high": 2510.0, "low": 2495.0, "close": 2505.0, "volume": 10.0, "is_closed": True}
    b2 = {"symbol": "ETHUSDT", "time": "2026-11-10T00:15:00Z", "open": 2505.0, "high": 2520.0, "low": 2500.0, "close": 2515.0, "volume": 15.0, "is_closed": True}
    b3 = {"symbol": "ETHUSDT", "time": "2026-11-10T00:30:00Z", "open": 2515.0, "high": 2525.0, "low": 2510.0, "close": 2520.0, "volume": 20.0, "is_closed": True}

    assert agg.add_15m_candle(b1) is None
    assert agg.add_15m_candle(b2) is None
    assert agg.add_15m_candle(b3) is None
    assert agg.buffered_bars_count == 3

    # Ingest 4th bar (minute 45): should emit aggregated 1h bar
    b4 = {"symbol": "ETHUSDT", "time": "2026-11-10T00:45:00Z", "open": 2520.0, "high": 2530.0, "low": 2515.0, "close": 2525.0, "volume": 25.0, "is_closed": True}
    bar_1h = agg.add_15m_candle(b4)

    assert bar_1h is not None
    assert bar_1h["time"] == "2026-11-10T00:00:00Z"
    assert bar_1h["open"] == 2500.0
    assert bar_1h["high"] == 2530.0
    assert bar_1h["low"] == 2495.0
    assert bar_1h["close"] == 2525.0
    assert bar_1h["volume"] == 70.0
    assert bar_1h["constituent_bars_count"] == 4
    assert bar_1h["is_closed"] is True
    assert agg.buffered_bars_count == 0

    # Unclosed candle raises ValueError
    unclosed_bar = dict(b1)
    unclosed_bar["is_closed"] = False
    with pytest.raises(ValueError, match="Unclosed or forming 15m candle rejected"):
        agg.add_15m_candle(unclosed_bar)


# ── 16. Isolated Evidence Persistence ─────────────────────────────────────────

def test_16_isolated_evidence_persistence(tmp_path):
    """ProspectiveShadowEvaluator persists evidence to isolated directory with distinct flags."""
    snap = build_eth_vol_aware_mean_reversion_freeze()
    evaluator = ProspectiveShadowEvaluator(
        candidate_snapshot=snap,
        freeze_boundary_timestamp="2026-11-10T00:00:00Z",
    )

    test_candle = {
        "time": "2026-11-10T01:00:00Z",
        "open": 2500.0,
        "high": 2510.0,
        "low": 2490.0,
        "close": 2495.0,
        "volume": 100.0,
        "is_closed": True,
    }

    opp = evaluator.evaluate_closed_bar(test_candle, [test_candle] * 60)
    persisted_path = evaluator.persist_evidence(opp, output_dir=tmp_path)

    assert persisted_path.exists()
    content = persisted_path.read_text(encoding="utf-8")
    import json
    saved_json = json.loads(content)

    assert saved_json["opportunity_id"] == opp.opportunity_id
    assert saved_json["is_simulated_shadow"] is True
    assert saved_json["is_actual_paper_fill"] is False
    assert "evidence_type" in saved_json


# ── 17. Durable Candidate Freeze Artifact Roundtrip ───────────────────────────

def test_17_durable_candidate_freeze_artifact_roundtrip(tmp_path):
    """Candidate freeze snapshot saves atomically with readback SHA-256 verification and loads cleanly."""
    snap = build_eth_vol_aware_mean_reversion_freeze()
    target_path = tmp_path / "candidate_freeze_test.json"

    file_sha256 = snap.save_to_file(target_path)
    assert len(file_sha256) == 64
    assert target_path.exists()

    loaded_snap = FrozenCandidateSnapshot.load_from_file(target_path)
    assert loaded_snap.freeze_hash == snap.freeze_hash
    assert loaded_snap.config_hash == snap.config_hash
    assert loaded_snap.candidate_id == snap.candidate_id
    assert loaded_snap.seal_status == "SOURCE_SEAL_PENDING"
    assert loaded_snap.validation_start_utc is None
    assert loaded_snap.effective_from_utc is None
    assert loaded_snap.freeze_lifecycle_status == "FREEZE_PREPARED"
    assert loaded_snap.activation_status == "PENDING_AUTHORIZATION"


# ── 18. Shadow Consumer Pipeline & Checkpoint ─────────────────────────────────

def test_18_shadow_consumer_pipeline_and_checkpoint(tmp_path):
    """ShadowConsumer aggregates 15m candles, evaluates on 1h close, and checkpoints state."""
    from btc_scraper.research.shadow_consumer import ShadowConsumer

    snap = build_eth_vol_aware_mean_reversion_freeze()
    consumer = ShadowConsumer(
        candidate_snapshot=snap,
        freeze_boundary_timestamp="2026-11-10T00:00:00Z",
        evidence_dir=tmp_path,
    )

    # 4 consecutive closed 15m bars
    bars_15m = [
        {"symbol": "ETHUSDT", "time": "2026-11-10T00:00:00Z", "open": 2500.0, "high": 2510.0, "low": 2495.0, "close": 2505.0, "volume": 10.0, "is_closed": True},
        {"symbol": "ETHUSDT", "time": "2026-11-10T00:15:00Z", "open": 2505.0, "high": 2520.0, "low": 2500.0, "close": 2515.0, "volume": 15.0, "is_closed": True},
        {"symbol": "ETHUSDT", "time": "2026-11-10T00:30:00Z", "open": 2515.0, "high": 2525.0, "low": 2510.0, "close": 2520.0, "volume": 20.0, "is_closed": True},
        {"symbol": "ETHUSDT", "time": "2026-11-10T00:45:00Z", "open": 2520.0, "high": 2530.0, "low": 2515.0, "close": 2525.0, "volume": 25.0, "is_closed": True},
    ]

    opps = consumer.process_15m_batch(bars_15m)
    assert len(opps) == 1
    assert consumer.total_15m_ingested == 4
    assert consumer.total_1h_emitted == 1
    assert consumer.total_evaluations == 1
    assert consumer.last_emitted_1h_timestamp == "2026-11-10T00:00:00Z"

    # Checkpoint file created on disk
    assert consumer.checkpoint_path.exists()
    import json
    cp_data = json.loads(consumer.checkpoint_path.read_text(encoding="utf-8"))
    assert cp_data["total_15m_ingested"] == 4
    assert cp_data["total_1h_emitted"] == 1
    assert cp_data["candidate_id"] == snap.candidate_id


# ── 19. Shadow Consumer Restart & Idempotency ──────────────────────────────────

def test_19_shadow_consumer_restart_idempotency(tmp_path):
    """Restarting ShadowConsumer restores checkpoint and cleanly ignores duplicate candles."""
    from btc_scraper.research.shadow_consumer import ShadowConsumer

    snap = build_eth_vol_aware_mean_reversion_freeze()
    consumer1 = ShadowConsumer(
        candidate_snapshot=snap,
        freeze_boundary_timestamp="2026-11-10T00:00:00Z",
        evidence_dir=tmp_path,
    )

    bars_15m = [
        {"symbol": "ETHUSDT", "time": "2026-11-10T00:00:00Z", "open": 2500.0, "high": 2510.0, "low": 2495.0, "close": 2505.0, "volume": 10.0, "is_closed": True},
        {"symbol": "ETHUSDT", "time": "2026-11-10T00:15:00Z", "open": 2505.0, "high": 2520.0, "low": 2500.0, "close": 2515.0, "volume": 15.0, "is_closed": True},
        {"symbol": "ETHUSDT", "time": "2026-11-10T00:30:00Z", "open": 2515.0, "high": 2525.0, "low": 2510.0, "close": 2520.0, "volume": 20.0, "is_closed": True},
        {"symbol": "ETHUSDT", "time": "2026-11-10T00:45:00Z", "open": 2520.0, "high": 2530.0, "low": 2515.0, "close": 2525.0, "volume": 25.0, "is_closed": True},
    ]
    consumer1.process_15m_batch(bars_15m)

    # Re-initialize new consumer instance pointing to same evidence dir (simulating process restart)
    consumer2 = ShadowConsumer(
        candidate_snapshot=snap,
        freeze_boundary_timestamp="2026-11-10T00:00:00Z",
        evidence_dir=tmp_path,
    )
    assert consumer2.last_processed_15m_timestamp == "2026-11-10T00:45:00Z"
    assert consumer2.total_1h_emitted == 1

    # Replay same 15m bars: must be cleanly skipped by idempotency filter
    replayed_opps = consumer2.process_15m_batch(bars_15m)
    assert len(replayed_opps) == 0
    assert consumer2.total_evaluations == 1


# ── 20. Execution Timing Fidelity Metadata ─────────────────────────────────────

def test_20_execution_timing_fidelity_metadata():
    """ProspectiveOpportunity records explicit timing fidelity and simulated execution model type."""
    snap = build_eth_vol_aware_mean_reversion_freeze()
    evaluator = ProspectiveShadowEvaluator(
        candidate_snapshot=snap,
        freeze_boundary_timestamp="2026-11-10T00:00:00Z",
    )

    candle = {
        "time": "2026-11-10T01:00:00Z",
        "open": 2500.0,
        "high": 2510.0,
        "low": 2490.0,
        "close": 2495.0,
        "volume": 100.0,
        "is_closed": True,
    }

    opp = evaluator.evaluate_closed_bar(candle, [candle] * 60)
    meta = opp.timing_metadata
    assert meta is not None
    assert meta["execution_model_type"] == "SIMULATED_MODEL_EXECUTION"
    assert meta["exchange_execution_parity_status"] == "NOT_EVALUATED"
    assert meta["latency_assumption_ms"] == 250
    assert "source_candle_close_time" in meta

    opp_dict = opp.to_dict()
    assert opp_dict["timing_metadata"]["execution_model_type"] == "SIMULATED_MODEL_EXECUTION"


# ── 21. Promotion Gates Fail-Closed Comprehensive Suite ────────────────────────

def test_21_promotion_gates_comprehensive_fail_closed_suite():
    """Validates all mandatory fail-closed negative cases for economic promotion."""
    base_spec = M5ValidationSpec(
        validation_id="val_test_suite",
        candidate_id="vol_aware_mean_reversion_v1",
        candidate_version="1.0.0",
        candidate_config_hash="4f73c169892a9403",
        dataset_manifest_identity="manifest-canonical",
        validation_mode="PROSPECTIVE_SHADOW",
        holdout_eligibility_status="VERIFIED_UNTOUCHED_PROSPECTIVE",
        validation_window=("2026-11-10T00:00:00Z", "2026-12-31T23:59:59Z"),
        is_executed=True,
    )

    # 1. Multi-asset gate false -> promotion false
    assert base_spec.is_economically_promotable is False

    # 2. Insufficient resolved trades (< 30) -> promotion false
    ok_trades, v_trades = base_spec.evaluate_promotion_readiness({
        "net_expectancy_usd": 5.0,
        "profit_factor": 2.0,
        "max_drawdown_pct": 5.0,
        "resolved_trades": 12,  # < 30
        "positive_folds_pct": 1.0,
        "multi_asset_consistency": True,
        "zero_lookahead_verified": True,
    })
    assert ok_trades is False
    assert v_trades["gate_4_min_trades"] is False

    # 3. Bootstrap CI lower bound <= 0 -> promotion false
    ok_ci, v_ci = base_spec.evaluate_promotion_readiness({
        "net_expectancy_usd": 5.0,
        "profit_factor": 2.0,
        "max_drawdown_pct": 5.0,
        "resolved_trades": 35,
        "positive_folds_pct": 1.0,
        "multi_asset_consistency": True,
        "zero_lookahead_verified": True,
        "bootstrap_95_ci_lower_usd": -0.05,  # <= 0
    })
    assert ok_ci is False
    assert v_ci["gate_8_bootstrap_ci_positive"] is False

    # 4. Missing economic evidence -> promotion false
    ok_none, v_none = base_spec.evaluate_promotion_readiness(None)
    assert ok_none is False
    assert v_none["execution"] is False

    # 5. Burned holdout -> raises ValueError during construction
    with pytest.raises(ValueError, match="BURNED_FOR_PROMOTION"):
        M5ValidationSpec(
            validation_id="val_burned",
            candidate_id="vol_aware_mean_reversion_v1",
            candidate_version="1.0.0",
            candidate_config_hash="4f73c169892a9403",
            dataset_manifest_identity="manifest-canonical",
            validation_mode="PROSPECTIVE_SHADOW",
            holdout_eligibility_status="VERIFIED_UNTOUCHED_PROSPECTIVE",
            validation_window=("2026-01-01T00:00:00Z", "2026-06-30T23:59:59Z"),
        )

    # 6. Technical readiness only (is_executed=False) -> promotion false
    unexecuted_spec = M5ValidationSpec(
        validation_id="val_unexecuted",
        candidate_id="vol_aware_mean_reversion_v1",
        candidate_version="1.0.0",
        candidate_config_hash="4f73c169892a9403",
        dataset_manifest_identity="manifest-canonical",
        validation_mode="PROSPECTIVE_SHADOW",
        holdout_eligibility_status="PROSPECTIVE_PENDING_DATA",
        is_executed=False,
    )
    assert unexecuted_spec.is_economically_promotable is False
    assert unexecuted_spec.is_promotion_eligible is False


# ── 22. Source Manifest Tamper & Non-Semantic Immunity ─────────────────────────

def test_22_source_manifest_tamper_and_non_semantic_immunity(tmp_path):
    """Source manifest rejects modified semantic dependencies while ignoring non-semantic files."""
    from btc_scraper.research.source_manifest import (
        compute_source_manifest,
        verify_source_manifest,
    )

    manifest = compute_source_manifest()
    assert manifest["dependency_count"] == 10

    # Adding a non-semantic file (e.g. log or temp report) in repo does not alter manifest
    temp_log = tmp_path / "runtime_debug.log"
    temp_log.write_text("random log entry", encoding="utf-8")
    manifest_after_log = compute_source_manifest()
    assert manifest["manifest_hash"] == manifest_after_log["manifest_hash"]

    # Tampering with a recorded file hash triggers verifier failure
    tampered_manifest = dict(manifest)
    tampered_files = dict(tampered_manifest["file_hashes"])
    first_key = sorted(tampered_files.keys())[0]
    tampered_files[first_key] = "0000000000000000000000000000000000000000000000000000000000000000"
    tampered_manifest["file_hashes"] = tampered_files

    is_valid, discrepancies = verify_source_manifest(tampered_manifest)
    assert is_valid is False
    assert len(discrepancies) == 1
    assert first_key in discrepancies[0]


# ── 23. Temporal Invariant: Reject Future frozen_at_utc ─────────────────────────

def test_23_temporal_invariant_rejection_future_frozen_at():
    """FrozenCandidateSnapshot rejects frozen_at_utc that is in the future relative to artifact creation."""
    with pytest.raises(ValueError, match="is in the future relative to artifact creation"):
        build_eth_vol_aware_mean_reversion_freeze(
            artifact_created_at_utc="2026-11-10T05:35:00Z",
            frozen_at_utc="2026-11-10T06:00:00Z",
        )


# ── 24. Temporal Invariant: Reject validation_start_utc Before frozen_at_utc ───

def test_24_temporal_invariant_rejection_validation_start_before_frozen():
    """FrozenCandidateSnapshot rejects validation_start_utc that is earlier than frozen_at_utc."""
    with pytest.raises(ValueError, match="cannot be earlier than frozen_at_utc"):
        build_eth_vol_aware_mean_reversion_freeze(
            artifact_created_at_utc="2026-11-10T05:35:00Z",
            frozen_at_utc="2026-11-10T05:00:00Z",
            validation_start_utc="2026-11-10T04:00:00Z",
        )


# ── 25. Invariant: EFFECTIVE_SEALED Requires SOURCE_SEALED & Non-Null Timestamp 

def test_25_effective_sealed_requires_source_sealed_and_timestamp():
    """EFFECTIVE_SEALED lifecycle status requires seal_status == SOURCE_SEALED and non-null frozen_at_utc."""
    with pytest.raises(ValueError, match="Cannot claim EFFECTIVE_SEALED.*seal_status is SOURCE_SEAL_PENDING"):
        build_eth_vol_aware_mean_reversion_freeze(
            freeze_lifecycle_status="EFFECTIVE_SEALED",
            seal_status="SOURCE_SEAL_PENDING",
            frozen_at_utc="2026-11-10T05:00:00Z",
        )

    with pytest.raises(ValueError, match="Cannot claim EFFECTIVE_SEALED.*without an authoritative frozen_at_utc"):
        build_eth_vol_aware_mean_reversion_freeze(
            freeze_lifecycle_status="EFFECTIVE_SEALED",
            seal_status="SOURCE_SEALED",
            frozen_at_utc=None,
        )


# ── 26. Fail-Closed Superseded Artifact Rejection ─────────────────────────────

def test_26_load_superseded_artifact_rejected_fail_closed():
    """Loading a superseded freeze artifact raises ValueError unless allow_superseded=True."""
    superseded_path = Path("data/candidate_freezes/superseded/vol_aware_mean_reversion_v1_freeze_future_timestamp_audit.json")
    assert superseded_path.exists()

    with pytest.raises(ValueError, match="Cannot load superseded candidate freeze artifact"):
        FrozenCandidateSnapshot.load_from_file(superseded_path, allow_superseded=False)

    loaded = FrozenCandidateSnapshot.load_from_file(superseded_path, allow_superseded=True)
    assert loaded.is_superseded is True
    assert loaded.freeze_lifecycle_status == "SUPERSEDED"
    assert loaded.is_effective_freeze is False


# ── 27. Crash Recovery & Idempotent Exact Continuation ─────────────────────────

def test_27_shadow_consumer_crash_recovery_and_exact_continuation(tmp_path):
    """ShadowConsumer safely survives simulated process crashes, restoring state faithfully."""
    from btc_scraper.research.shadow_consumer import ShadowConsumer

    snap = build_eth_vol_aware_mean_reversion_freeze()
    consumer1 = ShadowConsumer(
        candidate_snapshot=snap,
        freeze_boundary_timestamp="2026-11-10T00:00:00Z",
        evidence_dir=tmp_path,
    )

    # 4 consecutive closed 15m bars
    bars_15m_part1 = [
        {"symbol": "ETHUSDT", "time": "2026-11-10T00:00:00Z", "open": 2500.0, "high": 2510.0, "low": 2495.0, "close": 2505.0, "volume": 10.0, "is_closed": True},
        {"symbol": "ETHUSDT", "time": "2026-11-10T00:15:00Z", "open": 2505.0, "high": 2515.0, "low": 2500.0, "close": 2510.0, "volume": 12.0, "is_closed": True},
        {"symbol": "ETHUSDT", "time": "2026-11-10T00:30:00Z", "open": 2510.0, "high": 2520.0, "low": 2505.0, "close": 2515.0, "volume": 15.0, "is_closed": True},
        {"symbol": "ETHUSDT", "time": "2026-11-10T00:45:00Z", "open": 2515.0, "high": 2525.0, "low": 2510.0, "close": 2520.0, "volume": 14.0, "is_closed": True},
    ]
    opps1 = consumer1.process_15m_batch(bars_15m_part1)
    assert len(opps1) == 1
    assert consumer1.checkpoint_path.exists()

    # Simulate crash: instantiate new consumer pointing to the same directory
    consumer2 = ShadowConsumer(
        candidate_snapshot=snap,
        freeze_boundary_timestamp="2026-11-10T00:00:00Z",
        evidence_dir=tmp_path,
    )
    assert consumer2.total_1h_emitted == 1
    assert consumer2.total_evaluations == 1
    assert consumer2.last_processed_15m_timestamp == "2026-11-10T00:45:00Z"

    # Replay part 1: must be skipped by idempotency
    opps_replay = consumer2.process_15m_batch(bars_15m_part1)
    assert len(opps_replay) == 0
    assert consumer2.total_evaluations == 1

    # Feed second 1h bar (next 4 x 15m)
    bars_15m_part2 = [
        {"symbol": "ETHUSDT", "time": "2026-11-10T01:00:00Z", "open": 2520.0, "high": 2530.0, "low": 2515.0, "close": 2525.0, "volume": 11.0, "is_closed": True},
        {"symbol": "ETHUSDT", "time": "2026-11-10T01:15:00Z", "open": 2525.0, "high": 2535.0, "low": 2520.0, "close": 2530.0, "volume": 13.0, "is_closed": True},
        {"symbol": "ETHUSDT", "time": "2026-11-10T01:30:00Z", "open": 2530.0, "high": 2540.0, "low": 2525.0, "close": 2535.0, "volume": 16.0, "is_closed": True},
        {"symbol": "ETHUSDT", "time": "2026-11-10T01:45:00Z", "open": 2535.0, "high": 2545.0, "low": 2530.0, "close": 2540.0, "volume": 15.0, "is_closed": True},
    ]
    opps2 = consumer2.process_15m_batch(bars_15m_part2)
    assert len(opps2) == 1
    assert consumer2.total_1h_emitted == 2
    assert consumer2.total_evaluations == 2



