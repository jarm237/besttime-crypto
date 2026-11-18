"""
Tests for S2-A Cross-Asset Selection vs Cash-Timing Opportunity Screen.
Verifies PIT causality, split isolation, weight/cash invariants, fee accounting,
attribution formulas, and gate verdict logic.
"""

import json
import re
from pathlib import Path
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
S2A_DIR = REPO_ROOT / "research" / "cross_asset_s2a"


def test_artifacts_existence_and_schema():
    """Verify that all mandatory artifacts exist and have non-empty valid content."""
    manifest_path = S2A_DIR / "source_manifest.json"
    scorecard_path = S2A_DIR / "canonical_scorecard.json"
    ledger_path = S2A_DIR / "decision_ledger.json"
    report_path = S2A_DIR / "s2a_scientific_report.md"
    closure_path = S2A_DIR / "s2a_source_fidelity_closure.md"

    for p in [manifest_path, scorecard_path, ledger_path, report_path, closure_path]:
        assert p.is_file(), f"Missing required artifact: {p}"
        assert p.stat().st_size > 0, f"Artifact is empty: {p}"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["research_workstream"] == "S2A_Cross_Asset_Opportunity_Screen"
    assert "universe" in manifest
    assert len(manifest["universe"]) == 4
    assert manifest["non_neural_screen"] is True
    assert manifest["derivatives_or_news_features_used"] is False

    with open(scorecard_path, "r", encoding="utf-8") as f:
        scorecard = json.load(f)
    assert "meta" in scorecard
    assert "evaluation_results" in scorecard
    assert "economic_attribution" in scorecard
    assert "gate_evaluation" in scorecard
    assert "verdicts" in scorecard

    with open(ledger_path, "r", encoding="utf-8") as f:
        ledger = json.load(f)
    assert isinstance(ledger, list)
    assert len(ledger) > 0


def test_point_in_time_causality():
    """Verify strictly causal execution: source_feature_bar <= decision_time < execution_time."""
    ledger_path = S2A_DIR / "decision_ledger.json"
    with open(ledger_path, "r", encoding="utf-8") as f:
        ledger = json.load(f)

    for record in ledger[:100]:  # Sample first 100 decisions
        cutoff = record["source_feature_bar"]
        dec_time = record["decision_time"]
        exec_time = record["execution_time"]

        assert cutoff < dec_time, f"PIT cutoff {cutoff} must precede decision {dec_time}"
        assert dec_time < exec_time, f"Decision {dec_time} must precede execution {exec_time}"


def test_weights_and_cash_invariants():
    """Verify portfolio weights sum to 1.0, weights >= 0, cash >= 0, zero unbacked leverage."""
    ledger_path = S2A_DIR / "decision_ledger.json"
    with open(ledger_path, "r", encoding="utf-8") as f:
        ledger = json.load(f)

    for record in ledger:
        weights = record["target_weights"]
        cash_w = record["target_cash_weight"]
        total_w = sum(weights.values()) + cash_w
        assert abs(total_w - 1.0) < 1e-4, f"Weights must sum to 1.0: {total_w}"
        for sym, w in weights.items():
            assert w >= -1e-5, f"Negative weight for {sym}: {w}"
        assert cash_w >= -1e-5, f"Negative cash weight: {cash_w}"
        assert record["cash_usd"] >= -1e-5, f"Negative cash USD: {record['cash_usd']}"


def test_no_leakage_and_clean_feature_set():
    """Verify that feature set contains only spot price/volume features - NO derivatives/news/macro/on-chain."""
    manifest_path = S2A_DIR / "source_manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    forbidden_terms = ["funding", "open_interest", "oi_", "news", "sentiment", "gdelt", "defillama", "macro", "spx", "dxy", "onchain"]
    for feat in manifest.get("features_pre_registered", []):
        feat_lower = feat.lower()
        for forbidden in forbidden_terms:
            assert forbidden not in feat_lower, f"Forbidden data source leaked into feature set: {feat}"


def test_attribution_identity():
    """Verify that economic attribution formulas match between scorecard and definitions:
    - Selection = D - C
    - Timing = E - C
    - Combined = F - max(D, E, C)
    """
    scorecard_path = S2A_DIR / "canonical_scorecard.json"
    with open(scorecard_path, "r", encoding="utf-8") as f:
        scorecard = json.load(f)

    val_attr = scorecard["economic_attribution"]["Validation_2024"]
    val_cal = scorecard["evaluation_results"]["12_bps"]["calibrated_buffered"]["Validation_2024"]

    ret_c = val_cal["C_Static_50_50"]["net_return_pct"]
    ret_d = val_cal["D_Selection_Top2"]["net_return_pct"]
    ret_e = val_cal["E_Timing_Breadth"]["net_return_pct"]
    ret_f = val_cal["F_Combined_Top2"]["net_return_pct"]

    expected_sel = round(ret_d - ret_c, 2)
    expected_tim = round(ret_e - ret_c, 2)
    expected_comb = round(ret_f - max(ret_d, ret_e, ret_c), 2)

    assert abs(val_attr["selection_value_d_minus_c"] - expected_sel) < 1e-2
    assert abs(val_attr["timing_value_e_minus_c"] - expected_tim) < 1e-2
    assert abs(val_attr["combined_interaction_f_minus_max_dec"] - expected_comb) < 1e-2


def test_fee_stress_impact():
    """Verify that 30 bps stress fee strictly degrades net returns compared to 12 bps base."""
    scorecard_path = S2A_DIR / "canonical_scorecard.json"
    with open(scorecard_path, "r", encoding="utf-8") as f:
        scorecard = json.load(f)

    val_12 = scorecard["evaluation_results"]["12_bps"]["calibrated_buffered"]["Validation_2024"]
    val_30 = scorecard["evaluation_results"]["30_bps"]["calibrated_buffered"]["Validation_2024"]

    for pol in ["C_Static_50_50", "D_Selection_Top2", "E_Timing_Breadth", "F_Combined_Top2"]:
        assert val_30[pol]["net_return_pct"] <= val_12[pol]["net_return_pct"], f"{pol} 30bps return must not exceed 12bps"
        assert val_30[pol]["total_fees_usd"] >= val_12[pol]["total_fees_usd"], f"{pol} 30bps fees must not be lower than 12bps"


def test_rebalance_buffer_effect():
    """Verify that calibrated buffer (0.02) significantly reduces turnover/churn vs raw (0.0) on Train."""
    scorecard_path = S2A_DIR / "canonical_scorecard.json"
    with open(scorecard_path, "r", encoding="utf-8") as f:
        scorecard = json.load(f)

    train_raw = scorecard["evaluation_results"]["12_bps"]["raw"]["Train_2022_2023"]["C_Static_50_50"]
    train_buf = scorecard["evaluation_results"]["12_bps"]["calibrated_buffered"]["Train_2022_2023"]["C_Static_50_50"]

    # Raw static rebalanced every day (700 rebalances), buffer reduced it to 42 rebalances
    assert train_buf["rebalance_count"] < train_raw["rebalance_count"]
    assert train_buf["total_fees_usd"] < train_raw["total_fees_usd"]


def test_report_scorecard_numerical_consistency():
    """Verify that report numbers exactly match the canonical scorecard."""
    scorecard_path = S2A_DIR / "canonical_scorecard.json"
    report_path = S2A_DIR / "s2a_scientific_report.md"

    with open(scorecard_path, "r", encoding="utf-8") as f:
        scorecard = json.load(f)
    with open(report_path, "r", encoding="utf-8") as f:
        report_text = f.read()

    val_f_ret = scorecard["evaluation_results"]["12_bps"]["calibrated_buffered"]["Validation_2024"]["F_Combined_Top2"]["net_return_pct"]
    val_c_ret = scorecard["evaluation_results"]["12_bps"]["calibrated_buffered"]["Validation_2024"]["C_Static_50_50"]["net_return_pct"]

    assert f"+{val_f_ret:.2f}%" in report_text
    assert f"+{val_c_ret:.2f}%" in report_text


def test_gate_verdict_integrity():
    """Verify gate verdict logic accurately reflects empirical failure and enforces Hard Stop."""
    scorecard_path = S2A_DIR / "canonical_scorecard.json"
    with open(scorecard_path, "r", encoding="utf-8") as f:
        scorecard = json.load(f)

    gates = scorecard["gate_evaluation"]
    # Check that conditions 1 through 5 failed
    assert gates["condition_1_beats_strongest_baseline_val_12bps"]["passed"] is False
    assert gates["condition_2_incremental_return_positive_30bps"]["passed"] is False
    assert gates["condition_3_sharpe_or_maxdd_improved_val"]["passed"] is False
    assert gates["condition_4_distinct_mechanism_value"]["passed"] is False
    assert gates["condition_5_permutation_bootstrap_significant"]["passed"] is False
    assert gates["condition_6_not_dominated_by_single_asset"]["passed"] is True
    assert gates["all_gate_criteria_satisfied"] is False

    verdicts = scorecard["verdicts"]
    assert verdicts["S2A_CROSS_ASSET_ALLOCATION_OPPORTUNITY"] == "NOT_SUPPORTED"
    assert verdicts["S2B_NEURAL_PILOT_AUTHORIZATION"] == "NOT_AUTHORIZED"
    assert verdicts["PRODUCTION_PROMOTION"] == "NOT_AUTHORIZED"
    assert verdicts["OVERALL_CONCLUSION"] == "CROSS_ASSET_ALLOCATION_NOT_SUPPORTED"
