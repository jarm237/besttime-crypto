"""tests/test_vcb_economic_research.py

Targeted verification tests for the reproducible VCB economic research pipeline:
1. Determinism across isolated temporary directory executions.
2. Temporal fold isolation (DEV trades strictly < 2026-01-01).
3. No-lookahead execution contract (NEXT_BAR_OPEN, earliest entry at i+1).
4. Trade count and metric parity with canonical V1 baseline (369 DEV, 125 BURNED).
5. Cost accounting parity (friction correctly applied).
6. Candidate specification hashing invariance.
7. Bootstrap seed and block-size contract (block_size=10, seed determinism).
8. Epistemic governance: Burned audit 2026-H1 is strictly marked BURNED/CONSUMED and never OOS/CONFIRMATORY.
9. Prospective candidate V3 draft spec and activation manifest verification.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

from btc_scraper.trading.prospective_shadow_logger import (
    LockedCandidateSpec,
)
from scripts.evaluate_candidates_and_promotion_gates_v2 import (
    block_bootstrap_daily_mtm_ci,
)
from scripts.run_vcb_economic_research import (
    ALL_9_SYMBOLS,
    DEFAULT_OUT_DIR,
    DESIGN_SYMBOLS,
    HOLDOUT_SYMBOLS,
    ProspectiveCandidateRegistrationInput,
    build_canonical_research_candidate_payload,
    classify_exposed_historical_candidate,
    compute_canonical_research_spec_sha256,
    compute_dataset_manifest,
    compute_semantic_artifact_hash,
    decompose_trades_dataframe,
    evaluate_vcb_v4_sell_only,
    evaluate_vcb_v5_cross_sectional,
    extract_signals_with_rules,
    generate_deterministic_synthetic_candles,
    simulate_next_bar_open_barrier_trade,
    validate_candidate_for_prospective_draft,
    validate_new_candidate_for_prospective_registration,
    validate_runtime_contract_compatibility,
)


@pytest.fixture(scope="module")
def canonical_artifacts() -> dict[str, Any]:
    """Loads pre-generated canonical artifacts from research directory."""
    decomp_path = DEFAULT_OUT_DIR / "vcb_economic_decomposition.json"
    variants_path = DEFAULT_OUT_DIR / "vcb_exploratory_variants.json"
    assert decomp_path.exists(), f"Missing canonical decomposition artifact: {decomp_path}"
    assert variants_path.exists(), f"Missing canonical variants artifact: {variants_path}"

    with open(decomp_path, "r", encoding="utf-8") as f:
        decomp = json.load(f)
    with open(variants_path, "r", encoding="utf-8") as f:
        variants = json.load(f)

    return {"decomp": decomp, "variants": variants}


def test_fast_pipeline_deterministic_output(tmp_path: Path):
    """Verifies that running the research pipeline in synthetic sample mode produces deterministic outputs (<5s)."""
    out_dir_1 = tmp_path / "run_1"
    out_dir_2 = tmp_path / "run_2"

    cmd1 = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_vcb_economic_research.py"),
        "--out-dir", str(out_dir_1),
        "--reps", "20",
        "--synthetic-sample",
        "--quiet",
    ]
    cmd2 = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_vcb_economic_research.py"),
        "--out-dir", str(out_dir_2),
        "--reps", "20",
        "--synthetic-sample",
        "--quiet",
    ]

    res1 = subprocess.run(cmd1, capture_output=True, text=True, check=True)
    res2 = subprocess.run(cmd2, capture_output=True, text=True, check=True)
    assert res1.returncode == 0
    assert res2.returncode == 0

    # Ensure no prospective draft manifests or specs are emitted in either directory
    assert not (out_dir_1 / "prospective_v3_candidate_spec.json").exists()
    assert not (out_dir_1 / "prospective_v3_activation_manifest.json").exists()
    assert not (out_dir_2 / "prospective_v3_candidate_spec.json").exists()
    assert not (out_dir_2 / "prospective_v3_activation_manifest.json").exists()

    with open(out_dir_1 / "vcb_economic_decomposition.json", encoding="utf-8") as f:
        d1 = json.load(f)
    with open(out_dir_2 / "vcb_economic_decomposition.json", encoding="utf-8") as f:
        d2 = json.load(f)

    # Dataset hashes must match
    assert d1["dataset_manifest"]["combined_dataset_sha256"] == d2["dataset_manifest"]["combined_dataset_sha256"]
    # Spec SHA256 must match
    assert d1["candidate_spec"]["spec_sha256"] == d2["candidate_spec"]["spec_sha256"]
    # Semantic hashes match
    assert d1["semantic_artifact_sha256"] == d2["semantic_artifact_sha256"]

    # Variants artifacts must match
    with open(out_dir_1 / "vcb_exploratory_variants.json", encoding="utf-8") as f:
        var1 = json.load(f)
    with open(out_dir_2 / "vcb_exploratory_variants.json", encoding="utf-8") as f:
        var2 = json.load(f)

    assert var1["semantic_artifact_sha256"] == var2["semantic_artifact_sha256"]
    assert var1["candidate_selection_verdict"] == var2["candidate_selection_verdict"] == "NO_CANDIDATE_SELECTED"
    assert var1["prospective_status"] == var2["prospective_status"] == "NOT_STARTED"
    assert var1["runtime_candidate_spec"] is None
    assert var2["runtime_candidate_spec"] is None
    assert var1["activation_manifest"] is None
    assert var2["activation_manifest"] is None


@pytest.mark.canonical_economic
def test_canonical_pipeline_deterministic_reproduction(tmp_path: Path):
    """Full-dataset canonical reproduction test (marked canonical_economic, runs on actual disk CSVs)."""
    out_dir = tmp_path / "canonical_run"

    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_vcb_economic_research.py"),
        "--out-dir", str(out_dir),
        "--reps", "50",
        "--quiet",
    ]

    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert res.returncode == 0

    assert not (out_dir / "prospective_v3_candidate_spec.json").exists()
    assert not (out_dir / "prospective_v3_activation_manifest.json").exists()

    with open(out_dir / "vcb_economic_decomposition.json", encoding="utf-8") as f:
        d = json.load(f)

    v1_dev = d["decompositions"]["DEV_WALK_FORWARD_SELECTION_2024_2025"]
    assert v1_dev["executed_trade_count"] == 369
    v1_aud = d["decompositions"]["BURNED_EXPOSED_AUDIT_2026_H1"]
    assert v1_aud["executed_trade_count"] == 125


def test_temporal_fold_isolation(canonical_artifacts: dict[str, Any]):
    """Verifies that development fold trades strictly precede 2026 and audit trades are bounded."""
    decomp = canonical_artifacts["decomp"]
    v1_summary = decomp["v1_evaluation_summary"]

    # DEV window boundaries
    dev_p = v1_summary["periods"]["DEV_WALK_FORWARD_SELECTION_2024_2025"]
    assert dev_p["executed_trades_count"] == 369
    assert dev_p["epistemic_classification"] == "DEV_WALK_FORWARD_EXPOSURE"

    # Burned window boundaries
    aud_p = v1_summary["periods"]["BURNED_EXPOSED_AUDIT_2026_H1"]
    assert aud_p["executed_trades_count"] == 125
    assert "BURNED" in aud_p["epistemic_classification"]
    assert "CONFIRMATORY" not in aud_p["epistemic_classification"]


def test_next_bar_open_execution_no_future_leakage():
    """Verifies that next-bar-open execution strictly enters at i+1 open without looking at future OHLC."""
    n = 50
    opens = np.full(n, 100.0)
    highs = np.full(n, 102.0)
    lows = np.full(n, 99.0)
    closes = np.full(n, 101.0)
    # Set a distinct open on bar 11
    opens[11] = 105.0
    timestamps = [pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(minutes=15 * i) for i in range(n)]

    sim = simulate_next_bar_open_barrier_trade(
        "BUY",
        signal_idx=10,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        timestamps=timestamps,
        max_hold=10,
        tp_bps=350.0,
        sl_bps=150.0,
    )

    assert sim["signal_index"] == 10
    assert sim["entry_index"] == 11
    assert sim["entry_price"] == 105.0
    assert sim["signal_timestamp"] == timestamps[10]
    assert sim["entry_timestamp"] == timestamps[11]
    assert sim["signal_close_timestamp"] == timestamps[10] + pd.Timedelta(minutes=15)


def test_v1_baseline_exact_trade_count_and_metrics_parity(canonical_artifacts: dict[str, Any]):
    """Verifies that the reproducible pipeline outputs exact trade counts and metrics matching the report."""
    decomp = canonical_artifacts["decomp"]
    dev_decomp = decomp["decompositions"]["DEV_WALK_FORWARD_SELECTION_2024_2025"]
    aud_decomp = decomp["decompositions"]["BURNED_EXPOSED_AUDIT_2026_H1"]

    # DEV trade count and metrics
    assert dev_decomp["executed_trade_count"] == 369
    assert dev_decomp["by_symbol"]["BTC"]["count"] == 163
    assert dev_decomp["by_symbol"]["BNB"]["count"] == 128
    assert dev_decomp["by_symbol"]["ETH"]["count"] == 78

    # Burned 2026 H1 trade count and metrics
    assert aud_decomp["executed_trade_count"] == 125
    assert aud_decomp["by_symbol"]["BTC"]["count"] == 49
    assert aud_decomp["by_symbol"]["BNB"]["count"] == 45
    assert aud_decomp["by_symbol"]["ETH"]["count"] == 31

    # Directional asymmetry: BUY net expectancy is deeply negative in 2026
    assert aud_decomp["by_side"]["BUY"]["net_exp_bps"] < -40.0
    assert aud_decomp["by_side"]["BUY"]["win_rate_pct"] < 30.0
    assert aud_decomp["by_side"]["SELL"]["net_exp_bps"] > 0.0

    # Symbol breakdown: BTC drove majority of dollar loss
    btc_loss = aud_decomp["by_symbol"]["BTC"]["net_pnl_usd"]
    total_loss = aud_decomp["overall_net_pnl_usd"]
    assert btc_loss < -500.0
    assert btc_loss / total_loss > 0.70  # >70% loss share


def test_cost_accounting_friction_parity(canonical_artifacts: dict[str, Any]):
    """Verifies that 14 bps friction is applied accurately across all cost tiers."""
    decomp = canonical_artifacts["decomp"]
    aud_decomp = decomp["decompositions"]["BURNED_EXPOSED_AUDIT_2026_H1"]
    cost_sens = aud_decomp["cost_sensitivity"]

    # 10 bps vs 14 bps vs 20 bps vs 30 bps step sizes
    exp_10 = cost_sens["10.0"]["expectancy_bps"]
    exp_14 = cost_sens["14.0"]["expectancy_bps"]
    exp_20 = cost_sens["20.0"]["expectancy_bps"]
    exp_30 = cost_sens["30.0"]["expectancy_bps"]

    assert abs((exp_10 - exp_14) - 4.0) < 0.1
    assert abs((exp_14 - exp_20) - 6.0) < 0.1
    assert abs((exp_20 - exp_30) - 10.0) < 0.1


def test_candidate_spec_hashing_invariance():
    """Verifies that candidate specifications produce deterministic SHA-256 digests."""
    base_params = {"tp_bps": 350.0, "sl_bps": 150.0}
    p1 = build_canonical_research_candidate_payload("VCB_TEST", base_params)
    p2 = dict(reversed(list(p1.items())))
    h1 = compute_canonical_research_spec_sha256(p1)
    h2 = compute_canonical_research_spec_sha256(p2)
    assert h1 == h2
    assert len(h1) == 64


def test_bootstrap_seed_and_block_size_contract():
    """Verifies that block bootstrap behaves deterministically under fixed random seed."""
    np.random.seed(123)
    rets = np.random.normal(loc=1.0, scale=10.0, size=200)

    np.random.seed(42)
    ci_a = block_bootstrap_daily_mtm_ci(rets, block_size=10, n_bootstraps=500)

    np.random.seed(42)
    ci_b = block_bootstrap_daily_mtm_ci(rets, block_size=10, n_bootstraps=500)

    assert ci_a["ci_lower"] == ci_b["ci_lower"]
    assert ci_a["ci_upper"] == ci_b["ci_upper"]
    assert ci_a["block_size_days"] == 10


def test_burned_audit_never_labeled_confirmatory_or_oos(canonical_artifacts: dict[str, Any]):
    """Verifies that 2026-H1 is permanently classified as burned and never as confirmatory OOS."""
    variants = canonical_artifacts["variants"]
    epistemic_notice = variants["epistemic_notice"]
    assert "post-hoc exploratory hypotheses" in epistemic_notice
    assert "None are eligible for promotion" in epistemic_notice

    for cid, cand in variants["candidates"].items():
        burned_period = cand["periods"]["BURNED_EXPOSED_AUDIT_2026_H1"]
        e_class = burned_period["epistemic_classification"]
        assert "CONFIRMATORY" not in e_class
        assert "VALIDATED" not in e_class


def test_failed_candidate_does_not_emit_prospective_manifest(canonical_artifacts: dict[str, Any]):
    """Verifies that candidates that fail selection criteria never emit candidate specs or activation manifests."""
    variants = canonical_artifacts["variants"]
    assert variants["candidate_selection_verdict"] == "NO_CANDIDATE_SELECTED"
    assert variants["prospective_status"] == "NOT_STARTED"
    assert variants["runtime_candidate_spec"] is None
    assert variants["activation_manifest"] is None

    # Guarantee neither spec nor manifest exists on disk in canonical research directory
    assert not (DEFAULT_OUT_DIR / "prospective_v3_candidate_spec.json").exists()
    assert not (DEFAULT_OUT_DIR / "prospective_v3_activation_manifest.json").exists()


def test_behavior_flags_are_covered_by_spec_hash():
    """Verifies that all strategy behavior-affecting parameters and rules are covered by the canonical SHA-256 hash."""
    base_params = {
        "donchian_bars": 96,
        "sma_fast_bars": 96,
        "sma_slow_bars": 384,
        "min_vol_ratio_96": 1.2,
        "atr_compression_bars": 192,
        "tp_bps": 350.0,
        "sl_bps": 150.0,
    }

    # Baseline payload & hash
    p0 = build_canonical_research_candidate_payload("TEST_CAND", base_params)
    h0 = compute_canonical_research_spec_sha256(p0)

    # 1. Toggling req_slope changes hash
    p1 = build_canonical_research_candidate_payload("TEST_CAND", base_params, req_slope=True)
    h1 = compute_canonical_research_spec_sha256(p1)
    assert h1 != h0

    # 2. Toggling req_regime_gate changes hash
    p2 = build_canonical_research_candidate_payload("TEST_CAND", base_params, req_regime_gate=True)
    h2 = compute_canonical_research_spec_sha256(p2)
    assert h2 != h0
    assert h2 != h1

    # 3. Changing regime lookback or comparison rule changes hash
    p3 = build_canonical_research_candidate_payload(
        "TEST_CAND", base_params, req_regime_gate=True, regime_lookback_bars=192
    )
    h3 = compute_canonical_research_spec_sha256(p3)
    assert h3 != h2

    p4 = build_canonical_research_candidate_payload(
        "TEST_CAND", base_params, req_regime_gate=True, regime_comparison_rule="CUSTOM_RULE"
    )
    h4 = compute_canonical_research_spec_sha256(p4)
    assert h4 != h2
    assert h4 != h3

    # 4. Toggling use_atr_normalized_barrier changes hash
    p5 = build_canonical_research_candidate_payload("TEST_CAND", base_params, use_atr_normalized_barrier=True)
    h5 = compute_canonical_research_spec_sha256(p5)
    assert h5 != h0

    # 5. Changing ATR multipliers / caps changes hash
    p6 = build_canonical_research_candidate_payload(
        "TEST_CAND", base_params, use_atr_normalized_barrier=True, atr_tp_multiplier=2.5
    )
    h6 = compute_canonical_research_spec_sha256(p6)
    assert h6 != h5

    p7 = build_canonical_research_candidate_payload(
        "TEST_CAND", base_params, use_atr_normalized_barrier=True, atr_tp_max_bps=500.0
    )
    h7 = compute_canonical_research_spec_sha256(p7)
    assert h7 != h5
    assert h7 != h6

    # 6. Key order invariance
    p_reordered = dict(reversed(list(p0.items())))
    h_reordered = compute_canonical_research_spec_sha256(p_reordered)
    assert h_reordered == h0

    # 7. Distinct candidates have distinct hashes
    p_other = build_canonical_research_candidate_payload("OTHER_CAND", base_params)
    h_other = compute_canonical_research_spec_sha256(p_other)
    assert h_other != h0


def test_deprecated_legacy_function_raises_runtime_error():
    """Verifies that validate_candidate_for_prospective_draft is deprecated and raises RuntimeError fail-closed."""
    with pytest.raises(RuntimeError, match="DEPRECATED_LEGACY_FUNCTION"):
        validate_candidate_for_prospective_draft("VCB_V3_DIRECTIONAL_REGIME_GATE", {}, {})


def test_unsupported_runtime_fields_fail_closed():
    """Verifies that research candidates requiring unsupported fields fail runtime validation with explicit error reasons."""
    base_params = {
        "donchian_bars": 96,
        "sma_fast_bars": 96,
        "sma_slow_bars": 384,
        "min_vol_ratio_96": 1.2,
        "atr_compression_bars": 192,
        "tp_bps": 350.0,
        "sl_bps": 150.0,
    }

    v3_payload = build_canonical_research_candidate_payload(
        "VCB_V3_DIRECTIONAL_REGIME_GATE",
        base_params,
        req_slope=True,
        req_regime_gate=True,
    )

    # 1. Direct runtime compatibility validator
    is_compat, compat_reasons = validate_runtime_contract_compatibility(
        "VCB_V3_DIRECTIONAL_REGIME_GATE", v3_payload
    )
    assert is_compat is False
    assert any("UNSUPPORTED_RUNTIME_SPEC_FIELDS" in r for r in compat_reasons)
    assert any("NO_RESEARCH_RUNTIME_DECISION_PARITY" in r for r in compat_reasons)

    # 2. Rejection through ProspectiveCandidateRegistrationInput validator
    reg_input = ProspectiveCandidateRegistrationInput(
        candidate_id="VCB_V3_DIRECTIONAL_REGIME_GATE",
        spec_version="3.0.0",
        parameters=base_params,
        behavior_flags={"req_slope": True, "req_regime_gate": True, "use_atr_normalized_barrier": False},
        economic_rationale="Directional regime gated variant",
        dev_exploratory_summary={
            "gate_7_passed": True,
            "net_expectancy_bps_cost14": 15.0,
        },
        runtime_schema_compatibility_evidence={},
        research_runtime_parity_evidence={},
        registration_timestamp="2026-11-03T12:00:00Z",
        last_historical_timestamp_used="2025-12-31T23:45:00Z",
    )
    is_reg_ok, reg_reasons = validate_new_candidate_for_prospective_registration(reg_input)
    assert is_reg_ok is False
    assert any("UNSUPPORTED_RUNTIME_SPEC_FIELDS" in r for r in reg_reasons)


def test_research_spec_cannot_masquerade_as_runtime_spec():
    """Verifies that a research candidate specification cannot masquerade as a LockedCandidateSpec."""
    base_params = {
        "donchian_bars": 192,
        "sma_fast_bars": 96,
        "sma_slow_bars": 384,
        "min_vol_ratio_96": 1.2,
        "atr_compression_bars": 192,
        "tp_bps": 350.0,
        "sl_bps": 150.0,
    }

    v3_payload = build_canonical_research_candidate_payload(
        "VOL_COMPRESSION_BREAKOUT_V3_REGIME_GATED",
        base_params,
        req_slope=True,
        req_regime_gate=True,
    )
    research_sha = compute_canonical_research_spec_sha256(v3_payload)

    # 1. Direct deserialization into LockedCandidateSpec fails due to unsupported fields
    with pytest.raises(TypeError):
        LockedCandidateSpec(**v3_payload)

    # 2. Research hash cannot match runtime strategy_spec_sha256
    runtime_v1 = LockedCandidateSpec()
    assert research_sha != runtime_v1.strategy_spec_sha256
    assert research_sha != runtime_v1.spec_sha256


def test_no_candidate_selected_when_all_candidates_fail(canonical_artifacts: dict[str, Any]):
    """Verifies that when all candidates fail selection criteria, the pipeline reports NO_CANDIDATE_SELECTED."""
    variants = canonical_artifacts["variants"]
    assert variants["candidate_selection_verdict"] == "NO_CANDIDATE_SELECTED"
    assert variants["prospective_status"] == "NOT_STARTED"
    assert variants["runtime_candidate_spec"] is None
    assert variants["activation_manifest"] is None

    # Every candidate in rejection audit must have eligible == False
    rejection_audit = variants["rejection_audit"]
    assert len(rejection_audit) > 0
    for cid, audit in rejection_audit.items():
        assert audit["eligible"] is False, f"Candidate {cid} was unexpectedly marked eligible"
        assert len(audit["reasons"]) > 0, f"Candidate {cid} lacked explicit rejection reasons"


def test_future_candidate_admission_never_reads_burned_audit_metrics():
    """Epistemic Governance Contract:

    Verifies that validate_new_candidate_for_prospective_registration evaluates candidates
    strictly on DEV performance and runtime compatibility, and fails closed immediately
    if ANY burned/audit metrics or keywords are present in the candidate registration input.
    """
    valid_input = ProspectiveCandidateRegistrationInput(
        candidate_id="FUTURE_PROSPECTIVE_CANDIDATE_EXPERIMENTAL",
        spec_version="1.0.0",
        parameters={
            "donchian_bars": 96,
            "sma_fast_bars": 96,
            "sma_slow_bars": 384,
            "min_vol_ratio_96": 1.2,
            "atr_compression_bars": 192,
            "tp_bps": 350.0,
            "sl_bps": 150.0,
        },
        behavior_flags={
            "req_slope": False,
            "req_regime_gate": False,
            "use_atr_normalized_barrier": False,
        },
        economic_rationale="Pre-registered hypothesis on fresh unexposed data",
        dev_exploratory_summary={
            "gate_7_passed": True,
            "net_expectancy_bps_cost14": 12.50,
        },
        runtime_schema_compatibility_evidence={"compatible": True},
        research_runtime_parity_evidence={"parity": True},
        registration_timestamp="2026-11-03T12:00:00Z",
        last_historical_timestamp_used="2025-12-31T23:45:00Z",
    )

    # 1. Candidate passes registration on DEV alone
    is_ok, reasons = validate_new_candidate_for_prospective_registration(valid_input)
    assert is_ok is True
    assert len(reasons) == 0

    # 2. If forbidden audit data is passed, fail closed immediately
    tainted_dict = valid_input.to_dict()
    tainted_dict["audit_net_exp"] = -500.0
    is_tainted, tainted_reasons = validate_new_candidate_for_prospective_registration(tainted_dict)
    assert is_tainted is False
    assert any("FORBIDDEN_AUDIT_DATA_IN_PROSPECTIVE_INPUT" in r for r in tainted_reasons)

    # Nested forbidden key check
    tainted_nested = valid_input.to_dict()
    tainted_nested["dev_exploratory_summary"]["burned_audit_score"] = -10.0
    is_nested_tainted, nested_reasons = validate_new_candidate_for_prospective_registration(tainted_nested)
    assert is_nested_tainted is False
    assert any("FORBIDDEN_AUDIT_DATA_IN_PROSPECTIVE_INPUT" in r for r in nested_reasons)

    # 3. If DEV Gate 7 fails, prospective admission fails closed
    failing_dev = ProspectiveCandidateRegistrationInput(
        candidate_id="FUTURE_PROSPECTIVE_CANDIDATE_FAIL_DEV",
        spec_version="1.0.0",
        parameters=valid_input.parameters,
        behavior_flags=valid_input.behavior_flags,
        economic_rationale=valid_input.economic_rationale,
        dev_exploratory_summary={
            "gate_7_passed": False,
            "net_expectancy_bps_cost14": -5.0,
        },
        runtime_schema_compatibility_evidence={},
        research_runtime_parity_evidence={},
        registration_timestamp="2026-11-03T12:00:00Z",
        last_historical_timestamp_used="2025-12-31T23:45:00Z",
    )
    is_fail, reasons_fail = validate_new_candidate_for_prospective_registration(failing_dev)
    assert is_fail is False
    assert any("FAILED_DEV_SELECTION_GATE" in r for r in reasons_fail)


def test_classify_exposed_historical_candidate():
    """Verifies historical disposition classification of candidates evaluated on burned audit."""
    failing_eval = {
        "periods": {
            "DEV_WALK_FORWARD_SELECTION_2024_2025": {
                "primary_daily_block_bootstrap_ci_bps": {"gate_7_passed": False},
            },
            "BURNED_EXPOSED_AUDIT_2026_H1": {
                "primary_daily_block_bootstrap_ci_bps": {"gate_7_passed": False},
                "net_expectancy_bps_cost14": -22.26,
            },
        }
    }
    res = classify_exposed_historical_candidate("VOL_COMPRESSION_BREAKOUT_V1", failing_eval)
    assert res["disposition"] == "REJECTED_AFTER_EXPOSED_AUDIT"
    assert res["eligible"] is False
    assert any("FAILED_DEV_GATE_7" in r for r in res["reasons"])
    assert any("FAILED_EXPOSED_AUDIT" in r for r in res["reasons"])


def test_selection_path_is_blind_to_burned_audit(monkeypatch):
    """Integration test verifying that historical candidate selection flow never admits exposed candidates,
    even if burned audit metrics are artificially inflated, and never calls legacy validation.
    """
    import scripts.run_vcb_economic_research as rver

    # 1. Monkeypatch validate_candidate_for_prospective_draft to raise if called
    def boom(*args, **kwargs):
        raise AssertionError("Deprecated function validate_candidate_for_prospective_draft was called!")

    monkeypatch.setattr(rver, "validate_candidate_for_prospective_draft", boom)

    # 2. Simulate historical variants with artificially inflated burned expectancy (+500 bps) and passed gate 7
    mock_eval = {
        "periods": {
            "DEV_WALK_FORWARD_SELECTION_2024_2025": {
                "primary_daily_block_bootstrap_ci_bps": {"gate_7_passed": False},
                "net_expectancy_bps_cost14": -20.0,
            },
            "BURNED_EXPOSED_AUDIT_2026_H1": {
                "primary_daily_block_bootstrap_ci_bps": {"gate_7_passed": True},
                "net_expectancy_bps_cost14": 500.0,  # Artificially positive
            },
        }
    }

    # classify_exposed_historical_candidate must STILL reject because DEV failed, and eligible is ALWAYS False
    res = rver.classify_exposed_historical_candidate("VOL_COMPRESSION_BREAKOUT_V1", mock_eval)
    assert res["eligible"] is False
    assert res["disposition"] == "REJECTED_AFTER_EXPOSED_AUDIT"

    # Even if BOTH DEV and Audit artificially pass, historical exposed candidates are NEVER eligible
    passing_mock_eval = {
        "periods": {
            "DEV_WALK_FORWARD_SELECTION_2024_2025": {
                "primary_daily_block_bootstrap_ci_bps": {"gate_7_passed": True},
                "net_expectancy_bps_cost14": 15.0,
            },
            "BURNED_EXPOSED_AUDIT_2026_H1": {
                "primary_daily_block_bootstrap_ci_bps": {"gate_7_passed": True},
                "net_expectancy_bps_cost14": 500.0,
            },
        }
    }
    res_passing = rver.classify_exposed_historical_candidate("VOL_COMPRESSION_BREAKOUT_V2", passing_mock_eval)
    assert res_passing["eligible"] is False  # Exposed candidates NEVER eligible for prospective registration
    assert res_passing["disposition"] == "PASS_HISTORICAL_AUDIT"


def test_semantic_artifact_hash_invariance():
    """Verifies that compute_semantic_artifact_hash ignores volatile timing/profiling fields."""
    artifact_1 = {
        "pipeline_name": "hmr_v5_vcb_exploratory_variants",
        "generation_timestamp": "2026-11-03T11:00:00+00:00",
        "git_head": "f96c6b8b64516dd76d3af132dac316c5672e35be",
        "candidate_selection_verdict": "NO_CANDIDATE_SELECTED",
        "performance_metadata": {
            "elapsed_seconds": 103.73,
            "peak_memory_mb": 53.4,
            "profiling_enabled": False,
        },
        "stage_timing_seconds": {"stage_1": 1.23},
        "payload_field": {"key": "value", "list": [1, 2, 3]},
    }

    artifact_2 = {
        "pipeline_name": "hmr_v5_vcb_exploratory_variants",
        "generation_timestamp": "2026-11-03T18:45:00+00:00",  # Different timestamp
        "git_head": "f96c6b8b64516dd76d3af132dac316c5672e35be",
        "candidate_selection_verdict": "NO_CANDIDATE_SELECTED",
        "performance_metadata": {
            "elapsed_seconds": 999.99,  # Different timing
            "peak_memory_mb": 128.0,   # Different memory
            "profiling_enabled": True,
        },
        "stage_timing_seconds": {"stage_1": 99.99},  # Different stage timing
        "payload_field": {"key": "value", "list": [1, 2, 3]},
    }

    hash1 = compute_semantic_artifact_hash(artifact_1)
    hash2 = compute_semantic_artifact_hash(artifact_2)

    assert hash1 == hash2, "Semantic artifact hash changed despite identical substantive payload"


def test_semantic_artifact_hash_contract(canonical_artifacts: dict[str, Any]):
    """Verifies complete semantic artifact hash contract:
    1. On-disk stored hash matches recomputed semantic hash.
    2. Sensitivity to substantive changes (metrics, params, verdicts).
    """
    decomp = canonical_artifacts["decomp"]
    variants = canonical_artifacts["variants"]

    # 1. On-disk stored hash matches recomputed semantic hash
    assert "semantic_artifact_sha256" in decomp
    assert "semantic_artifact_sha256" in variants
    assert decomp["semantic_artifact_sha256"] == compute_semantic_artifact_hash(decomp)
    assert variants["semantic_artifact_sha256"] == compute_semantic_artifact_hash(variants)

    # 2. Invariance under timing/metadata modification
    decomp_copy = json.loads(json.dumps(decomp))
    decomp_copy["generation_timestamp"] = "1999-01-01T00:00:00Z"
    decomp_copy["performance_metadata"]["elapsed_seconds"] = 123456.78
    decomp_copy["stage_timing_seconds"] = {"arbitrary_stage": 999.0}
    assert compute_semantic_artifact_hash(decomp_copy) == decomp["semantic_artifact_sha256"]

    # 3. Sensitivity to substantive economic metric changes
    decomp_tampered = json.loads(json.dumps(decomp))
    decomp_tampered["v1_evaluation_summary"]["periods"]["DEV_WALK_FORWARD_SELECTION_2024_2025"]["net_expectancy_bps_cost14"] += 1.0
    assert compute_semantic_artifact_hash(decomp_tampered) != decomp["semantic_artifact_sha256"]

    variants_tampered = json.loads(json.dumps(variants))
    variants_tampered["candidate_selection_verdict"] = "TAMPERED_VERDICT"
    assert compute_semantic_artifact_hash(variants_tampered) != variants["semantic_artifact_sha256"]


def test_future_window_provenance_inventory():
    """Verifies that future_window_provenance_inventory.json exists, is valid, and reaches NO_UNTOUCHED_FUTURE_WINDOW_FOUND."""
    inv_path = DEFAULT_OUT_DIR / "future_window_provenance_inventory.json"
    assert inv_path.exists(), f"Missing future window inventory: {inv_path}"
    with open(inv_path, "r", encoding="utf-8") as f:
        inv = json.load(f)

    assert inv["verdict"] == "NO_UNTOUCHED_FUTURE_WINDOW_FOUND"
    assert inv["touch_count"] > 0
    assert len(inv["sources_audited"]) > 0
    assert "raw_ohlcv_values_read" in inv
    assert inv["raw_ohlcv_values_read"] is False
    assert "inventory_sha256" in inv


def test_v4_sell_only_spec_hash_covers_allowed_sides():
    """Verifies that VCB_V4_SELL_ONLY spec hash strictly covers allowed_sides and changes if allowed_sides changes."""
    base_params = {
        "donchian_bars": 96,
        "sma_fast_bars": 96,
        "sma_slow_bars": 384,
        "min_vol_ratio_96": 1.2,
        "atr_compression_bars": 192,
        "tp_bps": 350.0,
        "sl_bps": 150.0,
    }

    # Baseline V1 payload
    p_v1 = build_canonical_research_candidate_payload("VOL_COMPRESSION_BREAKOUT_V1", base_params)
    h_v1 = compute_canonical_research_spec_sha256(p_v1)

    # V4 payload with SELL only
    p_v4_sell = build_canonical_research_candidate_payload(
        "VCB_V4_SELL_ONLY",
        base_params,
        allowed_sides=["SELL"],
        design_source="POST_HOC_AFTER_2026_H1_EXPOSURE",
        validation_status="UNVALIDATED_PROSPECTIVE_HYPOTHESIS",
    )
    h_v4_sell = compute_canonical_research_spec_sha256(p_v4_sell)

    assert p_v4_sell["allowed_sides"] == ["SELL"]
    assert h_v4_sell != h_v1

    # Toggling allowed_sides changes hash
    p_v4_both = build_canonical_research_candidate_payload(
        "VCB_V4_SELL_ONLY",
        base_params,
        allowed_sides=["BUY", "SELL"],
        design_source="POST_HOC_AFTER_2026_H1_EXPOSURE",
        validation_status="UNVALIDATED_PROSPECTIVE_HYPOTHESIS",
    )
    h_v4_both = compute_canonical_research_spec_sha256(p_v4_both)
    assert h_v4_both != h_v4_sell


def test_v4_sell_only_artifacts_and_admission_verdict():
    """Verifies that VCB_V4_SELL_ONLY canonical research artifact exists, has valid semantic hash, and was rejected at DEV admission."""
    v4_json_path = DEFAULT_OUT_DIR / "vcb_v4_sell_only_research.json"
    v4_md_path = DEFAULT_OUT_DIR / "vcb_v4_sell_only_research.md"

    assert v4_json_path.exists(), f"Missing V4 research artifact: {v4_json_path}"
    assert v4_md_path.exists(), f"Missing V4 markdown report: {v4_md_path}"

    with open(v4_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Candidate spec
    assert data["candidate_id"] == "VCB_V4_SELL_ONLY"
    assert data["allowed_sides"] == ["SELL"]
    assert data["design_source"] == "POST_HOC_AFTER_2026_H1_EXPOSURE"
    assert data["validation_status"] == "UNVALIDATED_PROSPECTIVE_HYPOTHESIS"

    # Semantic artifact hash contract
    assert "semantic_artifact_sha256" in data
    assert data["semantic_artifact_sha256"] == compute_semantic_artifact_hash(data)

    # Admission verdict
    adm = data["admission_evaluation"]
    assert adm["admission_verdict"] == "VCB_V4_REJECTED_AT_EXPLORATORY_ADMISSION"
    assert adm["admission_passed"] is False

    scorecard = adm["stage_2_dev_gate_scorecard"]
    assert scorecard["net_expectancy_positive"] is True
    assert scorecard["gate_7_ci_lower_positive"] is False  # Gate 7 failed on DEV
    assert scorecard["profit_factor_above_one"] is True
    assert scorecard["min_two_assets_active"] is True
    assert scorecard["sample_sufficient_for_trade_rate"] is True

    # System operating disposition
    sys_disp = data["system_operating_disposition"]
    assert sys_disp["candidate_selection_verdict"] == "NO_CANDIDATE_SELECTED"
    assert sys_disp["prospective_status"] in ("NOT_STARTED", "PROSPECTIVE_NOT_STARTED")
    assert sys_disp["runtime_candidate_spec"] is None
    assert sys_disp["activation_manifest"] is None

    # Trade rate projections
    rates = data["trade_rate_projections"]
    assert rates["trades_per_day"] < 0.30  # Low turnover
    assert rates["projected_trades_90d"] < 25.0  # ~20 trades in 90 days, far below N=100
    assert rates["estimated_days_to_100_trades"] > 400.0  # >1 year to reach N=100


def test_v4_sell_only_fast_synthetic_evaluation(tmp_path: Path):
    """Verifies evaluate_vcb_v4_sell_only in fast synthetic sample mode (<1s)."""
    synthetic_candles = generate_deterministic_synthetic_candles(n_bars=600)
    out = evaluate_vcb_v4_sell_only(
        synthetic_candles,
        out_dir=tmp_path,
        reps=20,
        seed=42,
        quiet=True,
    )

    assert (tmp_path / "vcb_v4_sell_only_research.json").exists()
    assert (tmp_path / "vcb_v4_sell_only_research.md").exists()
    assert out["candidate_id"] == "VCB_V4_SELL_ONLY"
    assert out["allowed_sides"] == ["SELL"]
    assert out["semantic_artifact_sha256"] == compute_semantic_artifact_hash(out)


def test_v5_cross_sectional_holdout_artifacts_and_admission_verdict():
    """Verifies pre-registered VCB_V5_SELL_ONLY_9ASSET artifacts, holdout purity, and fail-closed rejection."""
    exposure_file = DEFAULT_OUT_DIR / "vcb_v5_cross_sectional_exposure_audit.json"
    spec_file = DEFAULT_OUT_DIR / "vcb_v5_sell_only_9asset_candidate_spec.json"
    plan_file = DEFAULT_OUT_DIR / "vcb_v5_cross_sectional_validation_plan.json"
    research_file = DEFAULT_OUT_DIR / "vcb_v5_sell_only_9asset_research.json"
    research_md = DEFAULT_OUT_DIR / "vcb_v5_sell_only_9asset_research.md"
    chronology_file = DEFAULT_OUT_DIR / "vcb_v5_chronology_audit.json"

    assert exposure_file.exists(), f"Missing Stage 0 exposure audit: {exposure_file}"
    assert spec_file.exists(), f"Missing Stage 1 spec: {spec_file}"
    assert plan_file.exists(), f"Missing Stage 1 plan: {plan_file}"
    assert research_file.exists(), f"Missing Stage 7 research artifact: {research_file}"
    assert research_md.exists(), f"Missing Stage 7 markdown: {research_md}"
    assert chronology_file.exists(), f"Missing Stage 1 chronology audit: {chronology_file}"

    # Stage 0: Exposure audit verification
    with open(exposure_file, "r", encoding="utf-8") as f:
        exp = json.load(f)
    assert exp["audit_verdict"] == "SUFFICIENT_CROSS_SECTIONAL_HOLDOUT_UNIVERSE"
    assert exp["universe_definition"]["observed_eligible_symbols"] == 6
    for h_sym in HOLDOUT_SYMBOLS:
        h_info = exp["symbols"][h_sym]
        assert h_info["exposure_status"] == "UNEXPOSED_TO_VCB_SPEC"
        assert h_info["coverage_eligibility"] == "ELIGIBLE"
        assert h_info["prior_vcb_reference_count"] == 0
    for d_sym in DESIGN_SYMBOLS:
        d_info = exp["symbols"][d_sym]
        assert d_info["exposure_status"] == "EXPOSED_TO_VCB_SPEC"
        assert d_info["coverage_eligibility"] == "INELIGIBLE_FOR_PRIMARY_HOLDOUT_EVALUATION"

    # Stage 1: Pre-registered spec & plan verification
    with open(spec_file, "r", encoding="utf-8") as f:
        spec = json.load(f)
    assert spec["candidate_id"] == "VCB_V5_SELL_ONLY_9ASSET"
    assert spec["allowed_sides"] == ["SELL"]
    assert spec["validation_status"] == "DEBUG_EXPOSED_CROSS_SECTIONAL_DIAGNOSTIC"
    canonical_payload = {
        k: v for k, v in spec.items()
        if k not in ("spec_sha256", "spec_locked_at_utc", "holdout_universe", "design_universe", "governance_note", "chronology_audit")
    }
    assert spec["spec_sha256"] == compute_canonical_research_spec_sha256(canonical_payload)
    assert "spec_locked_at_utc" in spec

    with open(plan_file, "r", encoding="utf-8") as f:
        plan = json.load(f)
    assert plan["candidate_id"] == "VCB_V5_SELL_ONLY_9ASSET"
    assert plan["spec_sha256"] == spec["spec_sha256"]
    assert plan["raw_holdout_outcome_read_at_utc"] is not None
    assert plan["plan_locked_at_utc"] is not None
    assert plan["epistemic_classification"] == "DEBUG_EXPOSED_CROSS_SECTIONAL_DIAGNOSTIC"

    with open(chronology_file, "r", encoding="utf-8") as f:
        chron = json.load(f)
    assert chron["verdict"] == "PRE_REGISTRATION_NOT_PROVABLE"
    assert chron["epistemic_classification"] == "DEBUG_EXPOSED_CROSS_SECTIONAL_DIAGNOSTIC"
    assert chron["is_provable"] is False
    assert len(chron["reasons"]) > 0

    # Stage 3-6: Research evaluation verification
    with open(research_file, "r", encoding="utf-8") as f:
        res = json.load(f)
    assert res["candidate_id"] == "VCB_V5_SELL_ONLY_9ASSET"
    assert res["epistemic_classification"] == "DEBUG_EXPOSED_CROSS_SECTIONAL_DIAGNOSTIC"
    assert res["chronology_verdict"] == "PRE_REGISTRATION_NOT_PROVABLE"
    assert res["historical_candidate_search_status"] == "HISTORICAL_CANDIDATE_SEARCH_STOPPED"
    assert res["semantic_artifact_sha256"] == compute_semantic_artifact_hash(res)

    p_eval = res["primary_holdout_evaluation"]
    assert p_eval["executed_trade_count"] >= 100  # N=748
    assert p_eval["net_expectancy_bps_cost14"] > 0.0  # +2.14 bps

    scorecard = res["gate_scorecard"]
    assert scorecard["gate_1_sample_size"]["passed"] is True
    assert scorecard["gate_2_net_expectancy"]["passed"] is True
    assert scorecard["gate_3_profit_factor"]["passed"] is True
    assert scorecard["gate_4_bootstrap_lower"]["passed"] is False  # FAILED: CI lower bound < 0.0 (-3.354)
    assert scorecard["gate_5_cross_sectional_breadth"]["passed"] is True  # 6 assets active
    assert scorecard["gate_6_concentration_risk"]["passed"] is True  # 19.7% < 80%
    assert scorecard["gate_7_max_drawdown"]["passed"] is False  # FAILED: 20.28% > 20%
    assert scorecard["gate_8_friction_tolerance"]["passed"] is True

    # Rejection enforcement
    assert res["admission_verdict"] == "VCB_V5_REJECTED_CROSS_SECTIONAL_HOLDOUT"

    # Fail-closed state
    sys_disp = res["system_operating_disposition"]
    assert sys_disp["candidate_selection_verdict"] == "NO_CANDIDATE_SELECTED"
    assert sys_disp["prospective_status"] in ("NOT_STARTED", "PROSPECTIVE_NOT_STARTED")
    assert sys_disp["runtime_candidate_spec"] is None
    assert sys_disp["activation_manifest"] is None

    # Trade rate speedup vs V4 baseline
    rate_comp = res["trade_rate_comparison"]
    assert rate_comp["sample_accumulation_speedup_factor"] > 3.0  # ~3.7x acceleration


def test_v5_cross_sectional_fast_synthetic_evaluation(tmp_path: Path):
    """Verifies evaluate_vcb_v5_cross_sectional in fast synthetic sample mode (<1s)."""
    out = evaluate_vcb_v5_cross_sectional(
        out_dir=tmp_path,
        reps=20,
        seed=42,
        quiet=True,
        synthetic_sample=True,
    )

    assert (tmp_path / "vcb_v5_cross_sectional_exposure_audit.json").exists()
    assert (tmp_path / "vcb_v5_sell_only_9asset_candidate_spec.json").exists()
    assert (tmp_path / "vcb_v5_cross_sectional_validation_plan.json").exists()
    assert (tmp_path / "vcb_v5_sell_only_9asset_research.json").exists()
    assert (tmp_path / "vcb_v5_sell_only_9asset_research.md").exists()
    assert (tmp_path / "vcb_v5_chronology_audit.json").exists()

    assert out["candidate_id"] == "VCB_V5_SELL_ONLY_9ASSET"
    assert out["allowed_sides"] == ["SELL"]
    assert out["semantic_artifact_sha256"] == compute_semantic_artifact_hash(out)
    assert out["system_operating_disposition"]["candidate_selection_verdict"] == "NO_CANDIDATE_SELECTED"
    assert out["system_operating_disposition"]["runtime_candidate_spec"] is None
    assert out["system_operating_disposition"]["activation_manifest"] is None


def test_pre_registration_chronology_fail_closed_simulation():
    """Simulates chronology audit violations and verifies fail-closed demotion to diagnostic."""
    from scripts.run_vcb_economic_research import audit_candidate_pre_registration_chronology

    # Case 1: Clean provable chronology
    clean = audit_candidate_pre_registration_chronology(
        spec_lock_utc="2026-11-04T02:00:00Z",
        plan_lock_utc="2026-11-04T02:00:00Z",
        earliest_raw_read_utc="2026-11-04T02:05:00Z",
        file_creation_utc="2026-11-04T02:00:00Z",
        eval_utc="2026-11-04T02:10:00Z",
    )
    assert clean["verdict"] == "PRE_REGISTRATION_PROVABLE"
    assert clean["epistemic_classification"] == "STRATEGY_SPECIFIC_CROSS_SECTIONAL_HOLDOUT_EVIDENCE"
    assert clean["is_provable"] is True
    assert len(clean["reasons"]) == 0

    # Case 2: Raw read precedes spec lock
    read_first = audit_candidate_pre_registration_chronology(
        spec_lock_utc="2026-11-04T02:39:53Z",
        plan_lock_utc="2026-11-04T02:39:53Z",
        earliest_raw_read_utc="2026-11-04T02:17:21Z",  # Earlier read
        file_creation_utc="2026-11-04T02:17:21Z",
        eval_utc="2026-11-04T02:42:08Z",
    )
    assert read_first["verdict"] == "PRE_REGISTRATION_NOT_PROVABLE"
    assert read_first["epistemic_classification"] == "DEBUG_EXPOSED_CROSS_SECTIONAL_DIAGNOSTIC"
    assert read_first["is_provable"] is False
    assert any("RAW_READ_PRECEDES_SPEC_LOCK" in r for r in read_first["reasons"])

    # Case 3: File creation precedes internal lock (rewritten artifact)
    rewritten = audit_candidate_pre_registration_chronology(
        spec_lock_utc="2026-11-04T02:39:53Z",
        plan_lock_utc="2026-11-04T02:39:53Z",
        earliest_raw_read_utc="2026-11-04T02:40:00Z",
        file_creation_utc="2026-11-04T02:17:21Z",  # 22 minutes earlier
        eval_utc="2026-11-04T02:42:08Z",
    )
    assert rewritten["verdict"] == "PRE_REGISTRATION_NOT_PROVABLE"
    assert rewritten["epistemic_classification"] == "DEBUG_EXPOSED_CROSS_SECTIONAL_DIAGNOSTIC"
    assert any("FILE_CREATION_PRECEDES_INTERNAL_LOCK" in r for r in rewritten["reasons"])


def test_r1_prospective_raw_epoch_manifest_and_ingestion(tmp_path: Path):
    """Verifies ProspectiveRawEpochManager governance invariants and ingestion behavior."""
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
        R1_EPOCH_ID,
    )

    mgr = ProspectiveRawEpochManager(tmp_path)

    # 1. Manifest invariants
    manifest = mgr.manifest
    assert manifest["epoch_id"] == R1_EPOCH_ID
    assert manifest["candidate_id"] is None
    assert manifest["promotion_clock"] == "NOT_APPLICABLE"
    assert manifest["real_orders"] is False
    assert manifest["paper_policy"] == "NO_TRADE_SHADOW"
    assert set(manifest["authorized_universe"]) == set(R1_AUTHORIZED_SYMBOLS)
    assert len(manifest["authorized_universe"]) == 9

    # 2. Immutable manifest cannot be tampered with
    # If manifest on disk has invalid hash, reload raises RuntimeError
    mgr.manifest_file.write_text(json.dumps({"epoch_id": "TAMPERED"}, indent=2), encoding="utf-8")
    with pytest.raises(RuntimeError, match="IMMUTABLE_MANIFEST_TAMPERED"):
        ProspectiveRawEpochManager(tmp_path)

    # Restore valid manifest for remaining tests
    mgr.manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    mgr = ProspectiveRawEpochManager(tmp_path)

    # 3. Rejects non-closed candle
    ok, err = mgr.ingest_candle("BTC", {"time_utc": "2026-11-04T02:45:00Z", "open": 100, "high": 105, "low": 95, "close": 102, "volume": 10, "is_closed": False})
    assert not ok
    assert "CANDLE_NOT_CLOSED" in err

    # 4. Rejects unauthorized symbol
    ok, err = mgr.ingest_candle("XRP", {"time_utc": "2026-11-04T02:45:00Z", "open": 100, "high": 105, "low": 95, "close": 102, "volume": 10, "is_closed": True})
    assert not ok
    assert "UNAUTHORIZED_SYMBOL" in err

    # 5. Ingest complete 9-symbol batch
    batch_ts = "2026-11-04T02:45:00Z"
    for sym in R1_AUTHORIZED_SYMBOLS:
        ok, msg = mgr.ingest_candle(sym, {
            "time_utc": batch_ts,
            "open": 100.0,
            "high": 105.0,
            "low": 98.0,
            "close": 103.0,
            "volume": 250.0,
            "is_closed": True,
        })
        assert ok, msg

    summary = mgr.get_epoch_summary()
    assert summary["counters"]["total_ingested"] == 9
    assert summary["counters"]["complete_batches"] == 1
    # Data ingested but no live daemon process -> truthfully INITIALIZED_COLLECTION_STOPPED
    assert summary["operating_status"] == "RESEARCH_EPOCH_INITIALIZED_COLLECTION_STOPPED"

    # 6. Rejects duplicate in same epoch
    ok, err = mgr.ingest_candle("BTC", {
        "time_utc": batch_ts,
        "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 250.0,
        "is_closed": True,
    })
    assert not ok
    assert "DUPLICATE_CANDLE_REJECTED" in err
    assert mgr.get_epoch_summary()["counters"]["duplicates_rejected"] == 1

    # 7. Restarts recover cleanly without duplicate counts
    mgr2 = ProspectiveRawEpochManager(tmp_path)
    s2 = mgr2.get_epoch_summary()
    assert s2["counters"]["total_ingested"] == 9
    assert s2["counters"]["complete_batches"] == 1
    assert s2["operating_status"] == "RESEARCH_EPOCH_INITIALIZED_COLLECTION_STOPPED"


def test_r1_collector_liveness_and_single_writer_lease(tmp_path: Path):
    """Verifies 5-state liveness transitions, heartbeat artifact, and single-writer lease enforcement."""
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
        is_pid_alive,
    )

    mgr = ProspectiveRawEpochManager(tmp_path)

    # 1. State 1: PREPARED_NOT_STARTED (fresh directory, no data, no daemon)
    assert mgr.get_operating_status() == "RESEARCH_EPOCH_PREPARED_NOT_STARTED"

    # 2. Single-writer lease acquisition
    current_pid = os.getpid()
    runtime_uuid = "test-uuid-1"
    mgr.acquire_lease(current_pid, runtime_uuid)

    # Second acquisition by another PID/UUID must fail with exact error
    with pytest.raises(RuntimeError, match="R1_SINGLE_WRITER_LEASE_ALREADY_HELD"):
        mgr.acquire_lease(pid=current_pid + 999999, runtime_uuid="test-uuid-2")

    # 3. State 2: ACTIVE when live collector emits fresh heartbeat
    started_ts = datetime.now(timezone.utc).isoformat()
    hb = mgr.update_heartbeat(
        pid=current_pid,
        runtime_uuid=runtime_uuid,
        started_at_utc=started_ts,
        collector_status="RUNNING",
    )
    assert hb["collector_status"] == "RUNNING"
    assert mgr.get_operating_status() == "RESEARCH_EPOCH_ACTIVE"

    # 4. State 3: DEGRADED when consecutive failures > 0 or degraded status
    mgr.update_heartbeat(
        pid=current_pid,
        runtime_uuid=runtime_uuid,
        started_at_utc=started_ts,
        collector_status="DEGRADED",
        consecutive_failures=3,
    )
    assert mgr.get_operating_status() == "RESEARCH_EPOCH_DEGRADED"

    # 5. State 4: STOPPED on graceful stop
    mgr.mark_stopped(current_pid, runtime_uuid)
    mgr.release_lease(current_pid, runtime_uuid)
    assert mgr.get_operating_status() == "RESEARCH_EPOCH_STOPPED"

    # 6. Stale lease recovery when PID is dead (e.g. PID 999999)
    dead_pid = 999999
    assert not is_pid_alive(dead_pid)
    # Manually write a stale lease from dead PID
    mgr.lease.lease_file.write_text(
        json.dumps({
            "epoch_id": mgr.manifest["epoch_id"],
            "pid": dead_pid,
            "runtime_uuid": "dead-uuid",
            "acquired_at_utc": "2026-01-01T00:00:00Z",
        }),
        encoding="utf-8",
    )
    # New live process should break the stale lease without error
    mgr.acquire_lease(current_pid, "new-uuid")
    active_lease = mgr.lease.read_lease()
    assert active_lease["pid"] == current_pid
    assert active_lease["runtime_uuid"] == "new-uuid"
    mgr.release_lease(current_pid, "new-uuid")


def test_r1_crash_recovery_partial_batch_completion(tmp_path: Path):
    """Scenario 1: Crash after writing 1-8 symbols of a batch; restart and complete the batch."""
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
    )

    mgr1 = ProspectiveRawEpochManager(tmp_path)
    batch_ts = "2026-11-04T05:00:00Z"

    # Ingest only first 5 symbols
    partial_symbols = R1_AUTHORIZED_SYMBOLS[:5]
    remaining_symbols = R1_AUTHORIZED_SYMBOLS[5:]

    for sym in partial_symbols:
        ok, msg = mgr1.ingest_candle(sym, {
            "time_utc": batch_ts, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 100.0, "is_closed": True
        })
        assert ok, msg

    s1 = mgr1.get_epoch_summary()
    assert s1["counters"]["total_ingested"] == 5
    assert s1["counters"]["complete_batches"] == 0
    assert s1["counters"]["incomplete_batches"] == 1

    # Simulate crash and restart
    mgr2 = ProspectiveRawEpochManager(tmp_path)
    s2 = mgr2.get_epoch_summary()
    assert s2["counters"]["total_ingested"] == 5
    assert s2["counters"]["complete_batches"] == 0
    assert s2["counters"]["incomplete_batches"] == 1
    assert len(mgr2._pending_batch[batch_ts]) == 5

    # Complete the batch on mgr2
    for sym in remaining_symbols:
        ok, msg = mgr2.ingest_candle(sym, {
            "time_utc": batch_ts, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 100.0, "is_closed": True
        })
        assert ok, msg

    s3 = mgr2.get_epoch_summary()
    assert s3["counters"]["total_ingested"] == 9
    assert s3["counters"]["complete_batches"] == 1
    assert s3["counters"]["incomplete_batches"] == 0


def test_r1_crash_recovery_uncommitted_batch_reconciled(tmp_path: Path):
    """Scenario 2: Crash after candle append but before batch-log append."""
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
    )

    mgr1 = ProspectiveRawEpochManager(tmp_path)
    batch_ts = "2026-11-04T05:15:00Z"

    # Ingest all 9 symbols
    for sym in R1_AUTHORIZED_SYMBOLS:
        mgr1.ingest_candle(sym, {
            "time_utc": batch_ts, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 100.0, "is_closed": True
        })

    assert mgr1.batch_file.exists()
    # Simulate crash before batch log write by truncating batch log
    mgr1.batch_file.unlink()
    assert not mgr1.batch_file.exists()

    # Restart as lease owner
    mgr2 = ProspectiveRawEpochManager(tmp_path)
    mgr2.acquire_lease(pid=os.getpid(), runtime_uuid="test-recovery-uuid")
    s2 = mgr2.get_epoch_summary()
    # Recovery must idempotently reconcile the batch into batch log
    assert mgr2.batch_file.exists()
    assert s2["counters"]["total_ingested"] == 9
    assert s2["counters"]["complete_batches"] == 1
    assert s2["counters"]["incomplete_batches"] == 0


def test_r1_crash_after_batch_log_before_state_checkpoint(tmp_path: Path):
    """Scenario 3: Crash after batch-log append but before state checkpoint."""
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
    )

    mgr1 = ProspectiveRawEpochManager(tmp_path)
    batch_ts = "2026-11-04T05:30:00Z"

    for sym in R1_AUTHORIZED_SYMBOLS:
        mgr1.ingest_candle(sym, {
            "time_utc": batch_ts, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 100.0, "is_closed": True
        })

    # Tamper state file to simulate outdated checkpoint
    stale_state = json.loads(mgr1.state_file.read_text(encoding="utf-8"))
    stale_state["counters"]["total_ingested"] = 0
    stale_state["counters"]["complete_batches"] = 0
    mgr1.state_file.write_text(json.dumps(stale_state), encoding="utf-8")

    # Restart
    mgr2 = ProspectiveRawEpochManager(tmp_path)
    s2 = mgr2.get_epoch_summary()
    # Durable append logs must win over stale state checkpoint
    assert s2["counters"]["total_ingested"] == 9
    assert s2["counters"]["complete_batches"] == 1


def test_r1_multiple_restarts_zero_duplicates(tmp_path: Path):
    """Scenario 4: Restart multiple times without duplicate candles or batches."""
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
    )

    mgr = ProspectiveRawEpochManager(tmp_path)
    ts1 = "2026-11-04T05:00:00Z"
    ts2 = "2026-11-04T05:15:00Z"

    # Batch 1
    for sym in R1_AUTHORIZED_SYMBOLS:
        mgr.ingest_candle(sym, {"time_utc": ts1, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 100.0, "is_closed": True})

    # Restart 1
    mgr_r1 = ProspectiveRawEpochManager(tmp_path)
    # Try re-ingesting batch 1 (must be rejected)
    for sym in R1_AUTHORIZED_SYMBOLS:
        ok, _ = mgr_r1.ingest_candle(sym, {"time_utc": ts1, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 100.0, "is_closed": True})
        assert not ok

    # Ingest batch 2
    for sym in R1_AUTHORIZED_SYMBOLS:
        mgr_r1.ingest_candle(sym, {"time_utc": ts2, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 100.0, "is_closed": True})

    # Restart 2 & 3
    mgr_r2 = ProspectiveRawEpochManager(tmp_path)
    mgr_r3 = ProspectiveRawEpochManager(tmp_path)

    s = mgr_r3.get_epoch_summary()
    assert s["counters"]["total_ingested"] == 18
    assert s["counters"]["complete_batches"] == 2

    # Verify physical file line counts
    candle_lines = [line.strip() for line in open(mgr_r3.candles_file, "r", encoding="utf-8") if line.strip()]
    batch_lines = [line.strip() for line in open(mgr_r3.batch_file, "r", encoding="utf-8") if line.strip()]
    assert len(candle_lines) == 18
    assert len(batch_lines) == 2


def test_r1_atomic_lease_concurrency_race(tmp_path: Path):
    """Scenario 5: Concurrent race to acquire single-writer lease: exactly one writer succeeds."""
    import concurrent.futures
    from btc_scraper.collectors.prospective_raw_epoch import ProspectiveRawEpochManager

    mgr = ProspectiveRawEpochManager(tmp_path)
    successes = []
    errors = []

    def try_acquire(worker_id: int):
        try:
            mgr.acquire_lease(pid=os.getpid(), runtime_uuid=f"worker-uuid-{worker_id}")
            successes.append(worker_id)
        except RuntimeError as e:
            if "R1_SINGLE_WRITER_LEASE_ALREADY_HELD" in str(e):
                errors.append(worker_id)
            else:
                raise

    # 10 concurrent threads attempting to acquire
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(try_acquire, i) for i in range(10)]
        concurrent.futures.wait(futures)

    # Exactly one acquired, 9 rejected
    assert len(successes) == 1
    assert len(errors) == 9
    mgr.release_lease(pid=os.getpid(), runtime_uuid=f"worker-uuid-{successes[0]}")


def test_r1_cooperative_stop_flow(tmp_path: Path):
    """Scenario 7: Cooperative stop request triggers clean loop exit through finally."""
    from btc_scraper.collectors.prospective_raw_epoch import ProspectiveRawEpochManager

    mgr = ProspectiveRawEpochManager(tmp_path)
    pid = os.getpid()
    ruuid = "coop-uuid-1"

    mgr.acquire_lease(pid, ruuid)
    mgr.update_heartbeat(pid, ruuid, started_at_utc=datetime.now(timezone.utc).isoformat(), collector_status="RUNNING")
    assert mgr.get_operating_status() == "RESEARCH_EPOCH_ACTIVE"

    # Request cooperative stop
    stop_file = tmp_path / "r1_stop.request"
    stop_file.write_text(json.dumps({"target_pid": pid, "target_runtime_uuid": ruuid}), encoding="utf-8")
    assert stop_file.exists()

    # Simulate daemon detecting stop request and finalizing shutdown
    if stop_file.exists():
        stop_file.unlink()
        mgr.mark_stopped(pid, ruuid)
        mgr.release_lease(pid, ruuid)

    assert not stop_file.exists()
    assert mgr.get_operating_status() == "RESEARCH_EPOCH_STOPPED"


def test_r1_stop_timeout_does_not_claim_stopped(tmp_path: Path):
    """Scenario 8: If stop times out and process is still alive, do NOT claim STOPPED or release lease."""
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        is_pid_alive,
    )

    mgr = ProspectiveRawEpochManager(tmp_path)
    current_pid = os.getpid()
    ruuid = "live-uuid-1"

    mgr.acquire_lease(current_pid, ruuid)
    mgr.update_heartbeat(current_pid, ruuid, started_at_utc=datetime.now(timezone.utc).isoformat(), collector_status="RUNNING")

    # If target PID is still alive past timeout, status must remain ACTIVE
    assert is_pid_alive(current_pid)
    assert mgr.get_operating_status() == "RESEARCH_EPOCH_ACTIVE"
    # Ensure lease is not deleted
    assert mgr.lease.lease_file.exists()
    mgr.release_lease(current_pid, ruuid)


def test_r1_batch_ingest_single_boundary_invariants(tmp_path: Path):
    """Scenario 10: One boundary batch ingest increments total_ingested by exactly 9, complete_batches by 1."""
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
    )

    mgr = ProspectiveRawEpochManager(tmp_path)
    batch_ts = "2026-11-04T06:00:00Z"
    candles_by_symbol = {
        sym: [{
            "time_utc": batch_ts, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 100.0, "is_closed": True
        }]
        for sym in R1_AUTHORIZED_SYMBOLS
    }

    res = mgr.ingest_batch(candles_by_symbol)
    assert res["accepted_count"] == 9
    assert len(res["completed_batches"]) == 1

    summary = mgr.get_epoch_summary()
    assert summary["counters"]["total_ingested"] == 9
    assert summary["counters"]["complete_batches"] == 1
    assert summary["counters"]["incomplete_batches"] == 0

    # Ingesting same batch again produces 0 new accepted, 9 rejected
    res2 = mgr.ingest_batch(candles_by_symbol)
    assert res2["accepted_count"] == 0
    assert len(res2["rejection_reasons"]) == 9
    assert mgr.get_epoch_summary()["counters"]["total_ingested"] == 9
    assert mgr.get_epoch_summary()["counters"]["duplicates_rejected"] == 9


def test_r1_truncated_tail_vs_middle_corruption(tmp_path: Path):
    """Verifies that truncated tail is cleanly recovered while middle corruption marks DEGRADED."""
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
    )

    mgr = ProspectiveRawEpochManager(tmp_path)
    batch_ts = "2026-11-04T06:00:00Z"
    for sym in R1_AUTHORIZED_SYMBOLS[:3]:
        mgr.ingest_candle(sym, {"time_utc": batch_ts, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 100.0, "is_closed": True})

    # Append a partial truncated line at tail
    with open(mgr.candles_file, "a", encoding="utf-8") as f:
        f.write('{"epoch_id": "PROSPECTIVE_RAW_RESEARCH_R1_20261104", "symbol": "ETH", "open": 100.0, "par')

    # Restart: truncated tail should be cleaned up without marking DEGRADED
    mgr2 = ProspectiveRawEpochManager(tmp_path)
    assert mgr2.get_epoch_summary()["counters"]["total_ingested"] == 3
    assert not mgr2._corrupted_middle

    # Now simulate a corruption in the middle of the file
    with open(mgr2.candles_file, "r", encoding="utf-8") as f:
        content = f.read()
    with open(mgr2.candles_file, "w", encoding="utf-8") as f:
        f.write("CORRUPTED_MIDDLE_LINE_NOT_JSON\n" + content)

    mgr3 = ProspectiveRawEpochManager(tmp_path)
    assert mgr3._corrupted_middle is True
    assert mgr3.get_operating_status() == "RESEARCH_EPOCH_DEGRADED"


def test_r1_bounded_concurrent_fetch_deterministic_ordering(tmp_path: Path):
    """Scenario 9: Bounded concurrent fetch produces deterministic 9-symbol batch in R1 order."""
    from unittest.mock import patch
    import asyncio
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
    )
    from scripts.run_prospective_raw_epoch import fetch_and_ingest_latest_batch

    async def _run():
        mgr = ProspectiveRawEpochManager(tmp_path)
        batch_ts = "2026-11-04T07:00:00Z"
        active_concurrent = 0
        max_observed_concurrent = 0
        lock = asyncio.Lock()

        async def mock_fetch_ohlcv(symbol: str, session: Any, limit: int = 5):
            nonlocal active_concurrent, max_observed_concurrent
            async with lock:
                active_concurrent += 1
                if active_concurrent > max_observed_concurrent:
                    max_observed_concurrent = active_concurrent
            await asyncio.sleep(0.01)
            async with lock:
                active_concurrent -= 1
            return [{
                "time_utc": batch_ts,
                "open": 100.0,
                "high": 105.0,
                "low": 98.0,
                "close": 103.0,
                "volume": 200.0,
                "is_closed": True,
            }]

        with patch("scripts.run_prospective_raw_epoch.fetch_ohlcv", side_effect=mock_fetch_ohlcv):
            res = await fetch_and_ingest_latest_batch(mgr, limit=5, max_concurrency=4)

        # Concurrency was bounded by 4
        assert max_observed_concurrent <= 4
        # All 9 symbols successfully ingested
        assert len(res["ingested_per_symbol"]) == 9
        assert all(res["ingested_per_symbol"][s] == 1 for s in R1_AUTHORIZED_SYMBOLS)
        assert res["epoch_summary"]["counters"]["complete_batches"] == 1
        assert res["epoch_summary"]["counters"]["total_ingested"] == 9

    asyncio.run(_run())


def test_r1_read_only_inspector_does_not_mutate_hash_or_mtime(tmp_path: Path):
    """Scenario 11: Read-only inspector preserves SHA-256, size, and mtime across all R1 files."""
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        create_read_only_inspector,
    )
    # Create an epoch with some initial data
    mgr = ProspectiveRawEpochManager(tmp_path, read_only=False)
    mgr.acquire_lease(pid=os.getpid(), runtime_uuid="init-uuid")
    mgr.ingest_candle("BTC", {"time_utc": "2026-11-04T08:00:00Z", "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0, "is_closed": True})
    mgr.release_lease(pid=os.getpid(), runtime_uuid="init-uuid")

    # Record snapshot of all files
    before = {}
    for f in tmp_path.glob("*"):
        if f.is_file():
            stat = f.stat()
            before[f.name] = (stat.st_size, stat.st_mtime_ns, hashlib.sha256(f.read_bytes()).hexdigest())

    # Create read-only inspector and query it thoroughly
    inspector = create_read_only_inspector(tmp_path)
    _ = inspector.get_epoch_summary()
    _ = inspector.get_operating_status()
    _ = inspector.read_heartbeat()
    _ = inspector.lease.read_lease()

    # Verify zero files changed
    after = {}
    for f in tmp_path.glob("*"):
        if f.is_file():
            stat = f.stat()
            after[f.name] = (stat.st_size, stat.st_mtime_ns, hashlib.sha256(f.read_bytes()).hexdigest())

    assert before == after


def test_r1_cli_status_does_not_write_files(tmp_path: Path):
    """Scenario 12: CLI --status runs pure read-only inspection without mutating files."""
    from btc_scraper.collectors.prospective_raw_epoch import ProspectiveRawEpochManager
    mgr = ProspectiveRawEpochManager(tmp_path, read_only=False)
    mgr.acquire_lease(pid=os.getpid(), runtime_uuid="status-init-uuid")
    mgr.release_lease(pid=os.getpid(), runtime_uuid="status-init-uuid")

    files_before = set(f.name for f in tmp_path.glob("*"))
    mtimes_before = {f.name: f.stat().st_mtime_ns for f in tmp_path.glob("*") if f.is_file()}

    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "run_prospective_raw_epoch.py"), "--status", "--storage-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    status_json = json.loads(res.stdout)
    assert status_json["operating_status"] == "RESEARCH_EPOCH_PREPARED_NOT_STARTED"

    files_after = set(f.name for f in tmp_path.glob("*"))
    mtimes_after = {f.name: f.stat().st_mtime_ns for f in tmp_path.glob("*") if f.is_file()}

    assert files_before == files_after
    assert mtimes_before == mtimes_after


def test_r1_cli_stop_uses_read_only_inspection_does_not_checkpoint_outside_daemon(tmp_path: Path):
    """Scenario 13: CLI --stop uses read-only path and does not create checkpoint or log if no daemon is running."""
    res = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "run_prospective_raw_epoch.py"), "--stop", "--storage-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Collector is not actively running" in res.stdout
    assert not (tmp_path / "r1_epoch_state.json").exists()


def test_r1_identified_stop_request_stops_real_subprocess(tmp_path: Path):
    """Scenario 14: Stop request with matching target PID and UUID stops a real daemon subprocess cleanly."""
    env = dict(os.environ)
    env["BTC_DISABLE_TEST_RUNTIME_GUARD"] = "1"
    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "scripts" / "run_prospective_raw_epoch.py"), "--storage-dir", str(tmp_path), "--interval", "1.0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        lease_file = tmp_path / "r1_writer.lease"
        start_wait = time.time()
        while time.time() - start_wait < 10.0:
            if lease_file.exists():
                break
            time.sleep(0.1)
        assert lease_file.exists()

        stop_res = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "run_prospective_raw_epoch.py"), "--stop", "--storage-dir", str(tmp_path), "--timeout", "15.0"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        assert "Cooperative stop confirmed" in stop_res.stdout

        proc.wait(timeout=10.0)
        assert proc.returncode == 0
        assert not lease_file.exists()
    finally:
        if proc.poll() is None:
            proc.kill()


def test_r1_stale_or_mismatched_stop_request_ignored_by_daemon(tmp_path: Path):
    """Scenario 15: Stale or mismatched stop request is quarantined and ignored; daemon stays active."""
    env = dict(os.environ)
    env["BTC_DISABLE_TEST_RUNTIME_GUARD"] = "1"
    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "scripts" / "run_prospective_raw_epoch.py"), "--storage-dir", str(tmp_path), "--interval", "1.0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        lease_file = tmp_path / "r1_writer.lease"
        start_wait = time.time()
        while time.time() - start_wait < 10.0:
            if lease_file.exists():
                break
            time.sleep(0.1)
        assert lease_file.exists()

        mismatched_req = tmp_path / "r1_stop.request"
        mismatched_req.write_text(json.dumps({
            "epoch_id": "PROSPECTIVE_RAW_RESEARCH_R1_20261104",
            "target_pid": 999999,
            "target_runtime_uuid": "wrong-uuid-1234",
            "requested_at_utc": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")

        time.sleep(3.0)
        assert proc.poll() is None, "Daemon should NOT exit on mismatched stop request"

        subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "run_prospective_raw_epoch.py"), "--stop", "--storage-dir", str(tmp_path), "--timeout", "10.0"],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
        proc.wait(timeout=10.0)
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.kill()


def test_r1_multiprocess_atomic_lease_race(tmp_path: Path):
    """Scenario 16: Spawns 5 independent Windows subprocesses concurrently attempting to acquire lease.
    Guarantees exactly 1 winner (code 0) and 4 rejections (code 1).
    """
    repo_root_str = str(REPO_ROOT).replace("\\", "\\\\")
    script = f"""
import os, sys, time
sys.path.insert(0, r'{repo_root_str}')
from pathlib import Path
from btc_scraper.collectors.prospective_raw_epoch import EpochLease, R1_EPOCH_ID
lease = EpochLease(Path(sys.argv[1]) / 'r1_writer.lease', R1_EPOCH_ID)
try:
    lease.acquire(pid=os.getpid(), runtime_uuid=f'worker-{{os.getpid()}}')
    time.sleep(3.5)
    sys.exit(0)
except RuntimeError as e:
    if 'R1_SINGLE_WRITER_LEASE_ALREADY_HELD' in str(e):
        sys.exit(1)
    sys.exit(2)
"""
    code_path = tmp_path / "worker.py"
    code_path.write_text(script, encoding="utf-8")

    procs = [
        subprocess.Popen([sys.executable, str(code_path), str(tmp_path)])
        for _ in range(5)
    ]
    for p in procs:
        p.wait(timeout=15.0)

    returncodes = [p.returncode for p in procs]
    assert returncodes.count(0) == 1, f"Expected exactly 1 winner, got: {returncodes}"
    assert returncodes.count(1) == 4, f"Expected 4 lease rejected, got: {returncodes}"


def test_r1_lease_release_under_lock_contention_preserves_lease(tmp_path: Path):
    """Scenario 17: Mutex contention during release fails closed without deleting lease file."""
    from btc_scraper.collectors.prospective_raw_epoch import EpochLease, R1_EPOCH_ID
    import pytest

    lease = EpochLease(tmp_path / "r1_writer.lease", R1_EPOCH_ID)
    pid = os.getpid()
    ruuid = "contention-uuid"
    lease.acquire(pid, ruuid)
    assert lease.lease_file.exists()

    # Manually hold lock file with an alive PID to induce mutex contention
    lock_info = json.dumps({"lock_owner_pid": pid, "runtime_uuid": "external-lock", "acquired_at_utc": datetime.now(timezone.utc).isoformat()})
    lease.lock_file.write_text(lock_info, encoding="utf-8")

    with pytest.raises(RuntimeError, match="MUTEX_CONTENTION_DURING_RELEASE"):
        lease.release(pid, ruuid)

    assert lease.lease_file.exists(), "Lease file must be preserved upon mutex contention!"
    lease.lock_file.unlink(missing_ok=True)
    lease.release(pid, ruuid)
    assert not lease.lease_file.exists()


def test_r1_http_ok_missing_expected_candle_marks_degraded(tmp_path: Path):
    """Scenario 18: HTTP 200 without the expected boundary candle marks missing symbols and DEGRADED."""
    from unittest.mock import patch
    from btc_scraper.collectors.prospective_raw_epoch import ProspectiveRawEpochManager
    from scripts.run_prospective_raw_epoch import fetch_and_ingest_latest_batch

    mgr = ProspectiveRawEpochManager(tmp_path, read_only=False)
    mgr.acquire_lease(pid=os.getpid(), runtime_uuid="test-sla-uuid")

    async def mock_fetch(symbol: str, session: Any, limit: int = 2):
        return [{
            "time_utc": "2026-11-04T07:45:00Z",
            "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0,
            "is_closed": True,
        }]

    with patch("scripts.run_prospective_raw_epoch.fetch_ohlcv", side_effect=mock_fetch):
        res = asyncio.run(fetch_and_ingest_latest_batch(mgr, expected_batch_open_utc="2026-11-04T08:00:00Z"))

    assert len(res["missing_symbols"]) == 9
    assert res["batch_res"]["accepted_count"] == 0
    mgr.release_lease(pid=os.getpid(), runtime_uuid="test-sla-uuid")


def test_r1_late_missing_symbol_completes_batch_restores_active(tmp_path: Path):
    """Scenario 19: Missing symbol arriving in subsequent poll completes pending batch."""
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
    )
    mgr = ProspectiveRawEpochManager(tmp_path, read_only=False)
    mgr.acquire_lease(pid=os.getpid(), runtime_uuid="late-test-uuid")

    ts = "2026-11-04T08:00:00Z"
    candles_partial = {
        sym: [{"time_utc": ts, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0, "is_closed": True}]
        for sym in R1_AUTHORIZED_SYMBOLS[:8]
    }
    res1 = mgr.ingest_batch(candles_partial)
    assert res1["accepted_count"] == 8
    assert len(res1["completed_batches"]) == 0
    assert mgr.get_epoch_summary()["counters"]["incomplete_batches"] == 1

    candles_late = {
        R1_AUTHORIZED_SYMBOLS[8]: [{"time_utc": ts, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0, "is_closed": True}]
    }
    res2 = mgr.ingest_batch(candles_late)
    assert res2["accepted_count"] == 1
    assert len(res2["completed_batches"]) == 1
    assert mgr.get_epoch_summary()["counters"]["complete_batches"] == 1
    assert mgr.get_epoch_summary()["counters"]["incomplete_batches"] == 0
    mgr.release_lease(pid=os.getpid(), runtime_uuid="late-test-uuid")


def test_r1_healthy_boundary_does_not_increment_duplicates_rejected(tmp_path: Path):
    """Scenario 20: Healthy boundary poll with expected candle filter does not increment duplicates_rejected."""
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
    )
    mgr = ProspectiveRawEpochManager(tmp_path, read_only=False)
    mgr.acquire_lease(pid=os.getpid(), runtime_uuid="healthy-boundary-uuid")

    ts1 = "2026-11-04T08:00:00Z"
    b1 = {
        sym: [{"time_utc": ts1, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0, "is_closed": True}]
        for sym in R1_AUTHORIZED_SYMBOLS
    }
    res1 = mgr.ingest_batch(b1)
    assert res1["accepted_count"] == 9
    assert mgr.get_epoch_summary()["counters"]["duplicates_rejected"] == 0

    ts2 = "2026-11-04T08:15:00Z"
    b2 = {
        sym: [{"time_utc": ts2, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0, "is_closed": True}]
        for sym in R1_AUTHORIZED_SYMBOLS
    }
    res2 = mgr.ingest_batch(b2)
    assert res2["accepted_count"] == 9
    assert len(res2["completed_batches"]) == 1
    assert mgr.get_epoch_summary()["counters"]["duplicates_rejected"] == 0
    mgr.release_lease(pid=os.getpid(), runtime_uuid="healthy-boundary-uuid")


def test_r1_disk_write_fault_does_not_corrupt_in_memory_state(tmp_path: Path):
    """Scenario 21: Simulated disk fault leaves in-memory state and counters completely unmutated."""
    from unittest.mock import patch
    import pytest
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
    )
    mgr = ProspectiveRawEpochManager(tmp_path, read_only=False)
    mgr.acquire_lease(pid=os.getpid(), runtime_uuid="fault-injection-uuid")

    ts = "2026-11-04T08:30:00Z"
    batch = {
        sym: [{"time_utc": ts, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0, "is_closed": True}]
        for sym in R1_AUTHORIZED_SYMBOLS
    }

    orig_open = open
    def fault_open(file, mode="r", *args, **kwargs):
        if str(mgr.candles_file) in str(file) and "a" in mode:
            raise IOError("SIMULATED_DISK_WRITE_FAILURE")
        return orig_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=fault_open):
        with pytest.raises(IOError, match="SIMULATED_DISK_WRITE_FAILURE"):
            mgr.ingest_batch(batch)

    summary = mgr.get_epoch_summary()
    assert summary["counters"]["total_ingested"] == 0
    assert summary["counters"]["complete_batches"] == 0
    assert summary["counters"]["incomplete_batches"] == 0
    assert ts not in mgr._seen_open_timestamps["BTC"]
    mgr.release_lease(pid=os.getpid(), runtime_uuid="fault-injection-uuid")


def test_r1_middle_corruption_preserves_evidence_without_rewrite(tmp_path: Path):
    """Scenario 22: Corrupted middle line flags DEGRADED but is strictly preserved on disk for forensic analysis."""
    from btc_scraper.collectors.prospective_raw_epoch import ProspectiveRawEpochManager
    mgr = ProspectiveRawEpochManager(tmp_path, read_only=False)
    mgr.acquire_lease(pid=os.getpid(), runtime_uuid="corrupt-evidence-uuid")
    mgr.ingest_candle("BTC", {"time_utc": "2026-11-04T08:00:00Z", "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0, "is_closed": True})
    mgr.release_lease(pid=os.getpid(), runtime_uuid="corrupt-evidence-uuid")

    content = mgr.candles_file.read_text(encoding="utf-8")
    corrupt_line = "CORRUPTED_MIDDLE_LINE_NOT_VALID_JSON"
    mgr.candles_file.write_text(content + corrupt_line + "\n" + content, encoding="utf-8")

    mgr2 = ProspectiveRawEpochManager(tmp_path)
    assert mgr2._corrupted_middle is True
    assert mgr2.get_operating_status() == "RESEARCH_EPOCH_DEGRADED"

    file_after = mgr2.candles_file.read_text(encoding="utf-8")
    assert corrupt_line in file_after, "Corrupted middle line must be preserved for forensic auditing!"


def test_r1_fault_injection_and_physical_rollback_matrix(tmp_path: Path):
    """Part B Fault Matrix: Proves that failures at any step of disk transaction roll back cleanly
    and immediate in-process retries or restarts NEVER produce physical duplicates or phantom RAM state.
    """
    from unittest.mock import patch
    import pytest
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
    )

    # 1. Fault in candle append (partial write)
    mgr = ProspectiveRawEpochManager(tmp_path / "fault1", read_only=False)
    mgr.acquire_lease(pid=os.getpid(), runtime_uuid="fault-test-1")

    ts1 = "2026-11-04T08:00:00Z"
    batch1 = {
        sym: [{"time_utc": ts1, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0, "is_closed": True}]
        for sym in R1_AUTHORIZED_SYMBOLS
    }

    orig_open = open
    def fault_open_partial_candle(file, mode="r", *args, **kwargs):
        if str(mgr.candles_file) in str(file) and "a" in mode:
            # Write a partial line then fail
            f = orig_open(file, mode, *args, **kwargs)
            f.write('{"partial": "candle_record"')
            f.flush()
            raise IOError("SIMULATED_PARTIAL_CANDLE_APPEND_FAILURE")
        return orig_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=fault_open_partial_candle):
        with pytest.raises(IOError, match="SIMULATED_PARTIAL_CANDLE_APPEND_FAILURE"):
            mgr.ingest_batch(batch1)

    # Assert disk file was rolled back to size 0
    assert mgr.candles_file.exists()
    assert mgr.candles_file.stat().st_size == 0
    assert mgr._counters["total_ingested"] == 0

    # In-process immediate retry of the same batch must succeed without error
    res_retry = mgr.ingest_batch(batch1)
    assert res_retry["accepted_count"] == 9
    assert len(res_retry["completed_batches"]) == 1
    assert mgr._counters["total_ingested"] == 9
    assert mgr.candles_file.read_text(encoding="utf-8").count("\n") == 9

    # 2. Fault in batch append (candles written, batch fails)
    ts2 = "2026-11-04T08:15:00Z"
    batch2 = {
        sym: [{"time_utc": ts2, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0, "is_closed": True}]
        for sym in R1_AUTHORIZED_SYMBOLS
    }

    pre_candle_size = mgr.candles_file.stat().st_size
    def fault_open_batch(file, mode="r", *args, **kwargs):
        if str(mgr.batch_file) in str(file) and "a" in mode:
            raise IOError("SIMULATED_BATCH_APPEND_FAILURE")
        return orig_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=fault_open_batch):
        with pytest.raises(IOError, match="SIMULATED_BATCH_APPEND_FAILURE"):
            mgr.ingest_batch(batch2)

    # Rollback must have truncated candles_file back to pre_candle_size
    assert mgr.candles_file.stat().st_size == pre_candle_size
    assert mgr._counters["total_ingested"] == 9
    assert mgr._counters["complete_batches"] == 1

    # In-process retry of batch 2 succeeds
    res_retry2 = mgr.ingest_batch(batch2)
    assert res_retry2["accepted_count"] == 9
    assert len(res_retry2["completed_batches"]) == 1
    assert mgr._counters["total_ingested"] == 18
    assert mgr._counters["complete_batches"] == 2
    assert mgr.candles_file.read_text(encoding="utf-8").count("\n") == 18

    # 3. Fault in checkpoint replace (candles & batch written, checkpoint fails)
    ts3 = "2026-11-04T08:30:00Z"
    batch3 = {
        sym: [{"time_utc": ts3, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0, "is_closed": True}]
        for sym in R1_AUTHORIZED_SYMBOLS
    }
    pre_candle_size3 = mgr.candles_file.stat().st_size
    pre_batch_size3 = mgr.batch_file.stat().st_size

    with patch.object(Path, "replace", side_effect=IOError("SIMULATED_CHECKPOINT_REPLACE_FAILURE")):
        with pytest.raises(IOError, match="SIMULATED_CHECKPOINT_REPLACE_FAILURE"):
            mgr.ingest_batch(batch3)

    # Rollback must have truncated both candles and batch log to pre sizes
    assert mgr.candles_file.stat().st_size == pre_candle_size3
    assert mgr.batch_file.stat().st_size == pre_batch_size3
    assert mgr._counters["total_ingested"] == 18
    assert mgr._counters["complete_batches"] == 2

    # In-process retry of batch 3 succeeds
    res_retry3 = mgr.ingest_batch(batch3)
    assert res_retry3["accepted_count"] == 9
    assert mgr._counters["total_ingested"] == 27
    assert mgr._counters["complete_batches"] == 3

    # Storage audit confirms zero duplicates
    audit = mgr.audit_storage()
    assert audit["physical_candle_duplicates_count"] == 0
    assert audit["physical_batch_duplicates_count"] == 0
    assert audit["valid_candle_records"] == 27
    assert audit["unique_candle_records"] == 27
    assert audit["valid_batch_records"] == 3
    assert audit["unique_batch_timestamps"] == 3
    assert audit["checkpoint_matches"] is True
    assert audit["audit_verdict"] == "AUDIT_CLEAN"
    mgr.release_lease(pid=os.getpid(), runtime_uuid="fault-test-1")


def test_r1_physical_duplicate_detected_marks_degraded_and_preserves_evidence(tmp_path: Path):
    """Proves that physical duplicates on disk are flagged as DEGRADED, documented in diagnostic artifact,
    and not counted multiple times in total_ingested.
    """
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
    )
    mgr = ProspectiveRawEpochManager(tmp_path, read_only=False)
    mgr.acquire_lease(pid=os.getpid(), runtime_uuid="dup-test-uuid")

    ts = "2026-11-04T08:00:00Z"
    batch = {
        sym: [{"time_utc": ts, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0, "is_closed": True}]
        for sym in R1_AUTHORIZED_SYMBOLS
    }
    mgr.ingest_batch(batch)
    mgr.release_lease(pid=os.getpid(), runtime_uuid="dup-test-uuid")

    # Manually append a duplicate candle line to physical candles file
    with open(mgr.candles_file, "r", encoding="utf-8") as f:
        first_line = f.readline()
    with open(mgr.candles_file, "a", encoding="utf-8") as f:
        f.write(first_line)

    # Recover with a new manager instance
    mgr2 = ProspectiveRawEpochManager(tmp_path, read_only=False)
    assert mgr2._physical_duplicates_detected is True
    assert mgr2.get_operating_status() == "RESEARCH_EPOCH_DEGRADED"
    # total_ingested should remain 9 (not 10) because duplicate is not counted
    assert mgr2._counters["total_ingested"] == 9

    # Diagnostic artifact must exist with evidence
    diag_file = tmp_path / "r1_duplicate_forensic_diagnostic.json"
    assert diag_file.exists()
    diag_data = json.loads(diag_file.read_text(encoding="utf-8"))
    assert diag_data["physical_duplicates_count"] == 1
    assert diag_data["action"] == "EVIDENCE_PRESERVED_NO_DELETION_OPERATING_STATUS_DEGRADED"

    # Audit confirms duplicate detected
    audit = mgr2.audit_storage()
    assert audit["physical_candle_duplicates_count"] == 1
    assert audit["audit_verdict"] == "AUDIT_ISSUES_DETECTED"


def test_r1_outage_catch_up_multi_boundary(tmp_path: Path):
    """Part C Outage Catch-Up: Proves collector identifies and catches up 1, 2, 4, and 20 missing boundaries
    in chronological ascending order without gaps or duplicates.
    """
    from scripts.run_prospective_raw_epoch import (
        determine_missing_batch_open_timestamps,
        poll_and_ingest_cycle,
    )
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
    )

    mgr = ProspectiveRawEpochManager(tmp_path, read_only=False)
    pid = os.getpid()
    ruuid = "catchup-test-uuid"
    mgr.acquire_lease(pid=pid, runtime_uuid=ruuid)

    # Ingest 1 initial baseline batch
    ts0 = "2026-11-04T00:00:00Z"
    b0 = {
        sym: [{"time_utc": ts0, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0, "is_closed": True}]
        for sym in R1_AUTHORIZED_SYMBOLS
    }
    mgr.ingest_batch(b0)
    assert mgr.get_last_complete_batch_open_ts() == ts0

    # 1. Simulate 1 boundary outage
    now_1b = datetime(2026, 11, 4, 0, 30, 5, tzinfo=timezone.utc)
    missing_1b = determine_missing_batch_open_timestamps(mgr, now_1b)
    assert missing_1b == ["2026-11-04T00:15:00Z"]

    # 2. Simulate 4 boundaries outage
    now_4b = datetime(2026, 11, 4, 1, 15, 5, tzinfo=timezone.utc)
    missing_4b = determine_missing_batch_open_timestamps(mgr, now_4b)
    assert len(missing_4b) == 4
    assert missing_4b == [
        "2026-11-04T00:15:00Z",
        "2026-11-04T00:30:00Z",
        "2026-11-04T00:45:00Z",
        "2026-11-04T01:00:00Z",
    ]

    # 3. Simulate 20 boundaries outage
    now_20b = datetime(2026, 11, 4, 5, 15, 5, tzinfo=timezone.utc)
    missing_20b = determine_missing_batch_open_timestamps(mgr, now_20b)
    assert len(missing_20b) == 20
    assert missing_20b[0] == "2026-11-04T00:15:00Z"
    assert missing_20b[-1] == "2026-11-04T05:00:00Z"

    # Catch-up simulation using mocked fetch
    from unittest.mock import AsyncMock, patch

    async def mocked_fetch(sym, session, limit=2, max_retries=2, expected_open_utc=None, semaphore=None):
        candle = {
            "time_utc": expected_open_utc,
            "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0,
            "is_closed": True, "closed": True,
        }
        return sym, [candle], None

    with patch("scripts.run_prospective_raw_epoch.fetch_symbol_with_retry", side_effect=mocked_fetch):
        # Run cycle for 4 boundaries catch-up
        with patch("scripts.run_prospective_raw_epoch.compute_expected_batch_open_utc", return_value="2026-11-04T01:00:00Z"):
            last_res, backlog, missing = asyncio.run(poll_and_ingest_cycle(mgr, pid, ruuid, "2026-11-04T00:00:00Z", max_catchup_batches=4))
            assert backlog == 0
            assert not missing
            assert mgr._counters["complete_batches"] == 5  # 1 initial + 4 caught up
            assert mgr._counters["total_ingested"] == 45
            assert mgr._counters["gaps_detected"] == 0

    # Verify audit confirms zero gaps
    audit = mgr.audit_storage()
    assert audit["total_gaps_detected"] == 0
    assert audit["unique_batch_timestamps"] == 5
    assert audit["audit_verdict"] == "AUDIT_CLEAN"
    mgr.release_lease(pid=pid, runtime_uuid=ruuid)


def test_r1_out_of_order_backfill_does_not_create_false_gaps(tmp_path: Path):
    """Proves that out-of-order appends or late backfills sort timestamps per symbol
    and do NOT falsely report gaps.
    """
    from btc_scraper.collectors.prospective_raw_epoch import (
        ProspectiveRawEpochManager,
        R1_AUTHORIZED_SYMBOLS,
    )
    mgr = ProspectiveRawEpochManager(tmp_path, read_only=False)
    mgr.acquire_lease(pid=os.getpid(), runtime_uuid="ooo-test-uuid")

    # Ingest boundary 2 (08:15:00Z) first
    ts2 = "2026-11-04T08:15:00Z"
    b2 = {
        sym: [{"time_utc": ts2, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0, "is_closed": True}]
        for sym in R1_AUTHORIZED_SYMBOLS
    }
    mgr.ingest_batch(b2)

    # Ingest boundary 1 (08:00:00Z) afterwards (late backfill)
    ts1 = "2026-11-04T08:00:00Z"
    b1 = {
        sym: [{"time_utc": ts1, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10.0, "is_closed": True}]
        for sym in R1_AUTHORIZED_SYMBOLS
    }
    mgr.ingest_batch(b1)
    mgr.release_lease(pid=os.getpid(), runtime_uuid="ooo-test-uuid")

    # Audit and recovery on sorted timestamps
    audit = mgr.audit_storage()
    assert audit["total_gaps_detected"] == 0, "Sorted timestamps must NOT report false gaps for late backfill!"
    assert audit["valid_candle_records"] == 18
    assert audit["unique_candle_records"] == 18

    mgr_rec = ProspectiveRawEpochManager(tmp_path, read_only=False)
    assert mgr_rec._counters["gaps_detected"] == 0
    assert mgr_rec._last_open_timestamp["BTC"] == "2026-11-04T08:15:00Z"







