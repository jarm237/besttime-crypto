"""Targeted unit tests for H-1 corrected economic revalidation, historical coverage, and R2 parity.

Guarantees:
1. Strict test isolation: output directory is injected using pytest `tmp_path`.
2. Canonical research files are never touched or modified during test execution.
3. Assertions verify economic reconciliation, invariant preservation, and deterministic accounting,
   NOT predetermined profitability amounts (economic failure is a valid research outcome).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.run_h1_corrected_economic_revalidation import (
    audit_r2_accounting_parity,
    audit_source_backed_historical_coverage,
    run_corrected_h1_revalidation,
)

ROOT = Path(__file__).resolve().parents[1]


def test_source_backed_historical_coverage_inspection():
    """Verify source-backed coverage audit from actual panel data."""
    panel_path = ROOT / "data" / "neural_n1_5" / "n1_5_enriched_coinm_panel.parquet"
    assert panel_path.exists(), f"Enriched panel must exist at {panel_path}"

    df = pd.read_parquet(panel_path)
    res = audit_source_backed_historical_coverage(df)

    data_avail = res["data_availability"]
    assert data_avail["panel_total_rows"] == 280144
    assert data_avail["covered_symbols_count"] == 8
    assert data_avail["aggregate_spot_availability_pct"] == 100.0  # Zero missing spot bars
    assert data_avail["total_unique_quarterly_contracts_observed"] == 120
    assert data_avail["aggregate_settlement_events_count"] == 115
    assert data_avail["aggregate_settlement_twap_matched_pct"] == 100.0  # All 115 matched 30m TWAPs

    # Verify per-symbol listing differences are captured
    per_sym = res["per_symbol_data_availability"]
    assert per_sym["BTCUSDT"]["missing_f1_bars"] < 200
    assert per_sym["SOLUSDT"]["missing_f1_bars"] > 20000  # SOL quarterly launched in mid-2024

    # Verify execution fidelity separation
    exec_fid = res["execution_fidelity"]
    assert exec_fid["aggregate_execution_precision"] == "EXECUTION_APPROXIMATE_MODELLED_B"
    assert "fidelity_level_a_authentic" in exec_fid
    assert "fidelity_level_b_modelled" in exec_fid
    assert "fidelity_level_c_insufficient" in exec_fid


def test_r2_accounting_parity_audit():
    """Verify accounting parity mapping between N1.5 simulator and R2 specifications."""
    parity_res = audit_r2_accounting_parity()
    summary = parity_res["parity_summary"]

    assert summary["total_core_invariants_audited"] == 9
    assert summary["verified_shared_invariants_count"] == 7
    assert summary["partial_modelled_invariants_count"] == 2
    assert summary["accounting_parity_status"] == "PARTIAL_SHARED_SUBSET"
    assert summary["historical_simulator_attribution"] == "N1_5_REEXECUTION_WITH_MODELLED_EXECUTION"

    # Invariants that must be verified as identical
    inv = parity_res["invariant_details"]
    assert inv["inverse_futures_pnl"]["parity_status"] == "VERIFIED_SHARED"
    assert inv["physical_discrete_contract_sizing"]["parity_status"] == "VERIFIED_SHARED"
    assert inv["entry_and_exit_fee_bridge"]["parity_status"] == "VERIFIED_SHARED"
    assert inv["account_equity_conservation"]["parity_status"] == "VERIFIED_SHARED"
    assert inv["exactly_once_economic_closure"]["parity_status"] == "VERIFIED_SHARED"

    # Lifecycle comparisons must be present and labeled SOURCE_REVIEWED_NOT_NUMERICALLY_VERIFIED
    assert parity_res["parity_summary"]["numerical_lifecycle_parity_status"] == "SOURCE_REVIEWED_NOT_NUMERICALLY_VERIFIED"
    num_comps = parity_res["representative_lifecycle_numerical_comparisons"]
    assert len(num_comps) >= 2
    for comp in num_comps:
        assert comp["parity_status"] == "SOURCE_REVIEWED_NOT_NUMERICALLY_VERIFIED"
        assert comp["r2_7_term_bridge_formula_net_pnl_usd"] is not None


def test_revalidation_evidence_integrity_and_injection(tmp_path: Path):
    """Verify that revalidation respects injected output_dir and preserves canonical research files."""
    canonical_file = ROOT / "research" / "revalidation" / "h1_corrected_economic_revalidation.json"
    canonical_mtime_before = canonical_file.stat().st_mtime if canonical_file.exists() else None

    # Run revalidation targeting the temporary directory (fast run without neural retrain)
    report = run_corrected_h1_revalidation(output_dir=tmp_path, run_neural=False)

    # 1. Output must be saved in tmp_path
    injected_output_file = tmp_path / "h1_corrected_economic_revalidation.json"
    assert injected_output_file.exists(), "Output file must be written to injected tmp_path"

    # 2. Canonical file must NOT have been modified
    if canonical_mtime_before is not None:
        assert canonical_file.stat().st_mtime == canonical_mtime_before, "Canonical research file must not be modified during test"

    # 3. Assert economic reconciliation invariants (NOT hardcoded profits)
    discrete = report["task_3_h1_physical_discrete_execution"]
    # Ledger reconciliation residual must be zero / within roundoff tolerance (< 5 cents across 4 years)
    assert abs(discrete["ledger_reconciliation_residual_usd"]) < 0.05

    # Exactly-once closure & valid turnover
    assert discrete["total_closed_positions"] > 0
    assert discrete["annualized_turnover"] > 0.0

    # Dynamic dispositions must be derived from metrics
    disp = report["task_7_research_dispositions"]
    expected_h1_disp = "SUPPORTED" if discrete["realized_net_pnl_usd"] > 0.0 else "NOT_SUPPORTED"
    assert disp["H1_HISTORICAL_ECONOMIC_MECHANISM"] == expected_h1_disp
    assert disp["H1_R2_ACCOUNTING_PARITY"] == "PARTIAL_SHARED_SUBSET"
    assert disp["UNIFIED_NEURAL_ARCHITECTURE"] == "PROPOSED_ADR_001"
    assert disp["NEURAL_INCREMENTAL_VALUE"] == "NOT_EVALUATED"
