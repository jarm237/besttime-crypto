"""Targeted unit tests for H-1 corrected economic revalidation and unified neural evaluation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_h1_corrected_economic_revalidation import (
    build_historical_execution_coverage_matrix,
    run_corrected_h1_revalidation,
)


def test_historical_execution_coverage_matrix():
    """Verify classification of A, B, C execution tiers across 2022-2025 and 2026 holdout."""
    matrix_res = build_historical_execution_coverage_matrix()
    summary = matrix_res["coverage_summary_2022_2025"]

    # 8 symbols * 4 years * 5 lifecycle events = 160 cells
    assert summary["total_event_cells"] == 160

    # Events in Tier A: MARK_TO_MARKET_HOLDING and DELIVERY_SETTLEMENT = 2 events * 8 symbols * 4 years = 64
    assert summary["tier_a_cells"] == 64
    assert summary["tier_a_pct"] == 40.0

    # Events in Tier B: ENTRY_EXECUTION, EARLY_COMPRESSION_CLOSE, DIRECT_ROLL_OVER = 3 events * 8 symbols * 4 years = 96
    assert summary["tier_b_cells"] == 96
    assert summary["tier_b_pct"] == 60.0

    # Tier C in active 2022-2025 is 0
    assert summary["tier_c_cells"] == 0

    # 2026 holdout is 100% Tier C (sealed)
    assert matrix_res["coverage_summary_2026_holdout"]["tier_c_sealed_holdout_pct"] == 100.0


def test_revalidation_execution_and_disposition(tmp_path: Path):
    """Test full economic revalidation output structure, accounting consistency, and disposition."""
    reval_res = run_corrected_h1_revalidation()

    # Verify physical discrete execution under standard retail taker (39.0 bps)
    discrete_res = reval_res["phase_b_h1_physical_discrete_execution"]["standard_retail_taker_39bps"]
    assert discrete_res["gross_economic_pnl_usd"] > 6000.0
    assert discrete_res["realized_net_pnl_usd"] > 5000.0
    assert discrete_res["net_return_on_committed_pct"] > 25.0
    assert discrete_res["annualized_turnover"] < 20.0  # Discrete contracts reduce turnover vs 21.8x continuous
    assert discrete_res["total_closed_positions"] > 80

    # Verify annual positive net PnL across all years (2022, 2023, 2024, 2025)
    annual = discrete_res["annual_breakdown"]
    for yr in ["2022", "2023", "2024", "2025"]:
        assert annual[yr]["net_pnl_usd"] > 0.0

    # Verify neural vs simple comparison in 2024
    comp_2024 = reval_res["phase_b_common_continuous_environment_comparison"]["validation_2024"]["at_39bps_corrected_cost"]
    # In 2024, simple carry beat neural policy due to neural exposure conservatism
    assert comp_2024["simple_carry_baseline_net_pnl_usd"] > comp_2024["neural_policy_net_pnl_usd"]
    assert comp_2024["neural_incremental_value_vs_simple_usd"] < 0.0

    # Verify disposition
    disp = reval_res["phase_e_research_disposition"]
    assert disp["overall_disposition"] == "A_SIMPLE_H1_EDGE_ONLY"
    assert disp["neural_incremental_value_disposition"] == "NEURAL_INCREMENTAL_VALUE_NOT_SUPPORTED"
    assert disp["h1_economic_disposition"] == "EXPLORATORY_NET_EDGE_SUPPORTED"
