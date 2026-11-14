"""Tests for first-principles information discovery and hypothesis screening.

Verifies:
1. Strict test isolation (tmp_path injection, no overwriting canonical artifacts).
2. SFRP-MR economic screening (funding rates vs retail round-trip friction).
3. CARP-CS cross-sectional screening (correlation vs turnover friction).
4. AVRS-TG downside tail risk screening (payoff-to-friction ratio).
5. Canonical artifact preservation.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from scripts.run_information_discovery_screening import (
    evaluate_sfrp_funding_feasibility,
    evaluate_carp_momentum_feasibility,
    evaluate_avrs_tail_gating_feasibility,
    build_information_hypotheses_screening_report,
    ROOT,
)


@pytest.fixture(scope="module")
def sample_panels():
    panel_path = ROOT / "data" / "neural_n1_5" / "n1_5_enriched_coinm_panel.parquet"
    fund_path = ROOT / "data" / "historical_funding_rates.parquet"
    df_panel = pd.read_parquet(panel_path) if panel_path.exists() else None
    df_fund = pd.read_parquet(fund_path) if fund_path.exists() else None
    return df_panel, df_fund


def test_sfrp_funding_feasibility_empirical_rejection(sample_panels):
    """Verify that empirical funding rates do not cover retail friction."""
    _, df_fund = sample_panels
    if df_fund is None:
        pytest.skip("Funding data not found")

    res = evaluate_sfrp_funding_feasibility(df_fund)
    assert res["hypothesis_id"] == "SFRP_MR_SPOT_PERPETUAL_FUNDING_DISLOCATION"
    assert res["economic_feasibility_verdict"] == "REJECTED_AFTER_COSTS"
    assert res["roundtrip_retail_friction_bps"] == 38.0
    # Breakeven should exceed 20 days given small mean funding rate (~0.45 bps/8h)
    assert res["breakeven_holding_days_at_mean"] > 20.0
    assert res["expected_net_payoff_10d_bps"] < 0.0


def test_carp_momentum_feasibility_rejection(sample_panels):
    """Verify that cross-sectional momentum signal is destroyed by turnover friction."""
    df_panel, _ = sample_panels
    if df_panel is None:
        pytest.skip("Panel data not found")

    res = evaluate_carp_momentum_feasibility(df_panel)
    assert res["hypothesis_id"] == "CARP_CS_CROSS_ASSET_RELATIVE_MOMENTUM"
    assert res["economic_feasibility_verdict"] == "REJECTED_AFTER_COSTS"
    assert res["annual_turnover_friction_drag_bps"] >= 1000.0
    assert abs(res["cross_sectional_correlation_24h"]) < 0.1
    assert abs(res["cross_sectional_correlation_168h"]) < 0.1


def test_avrs_tail_gating_feasibility_selection(sample_panels):
    """Verify that downside tail gating provides sufficient payoff-to-friction ratio."""
    df_panel, _ = sample_panels
    if df_panel is None:
        pytest.skip("Panel data not found")

    res = evaluate_avrs_tail_gating_feasibility(df_panel)
    assert res["hypothesis_id"] == "AVRS_TG_ASYMMETRIC_VOLATILITY_REGIME_SWITCHING"
    assert res["economic_feasibility_verdict"] == "SELECTED_FOR_NEXT_BOUNDED_EXPERIMENT"
    assert res["payoff_to_friction_ratio"] > 3.0
    assert res["annualized_return_tail_risk_regime_pct"] < -50.0


def test_screening_artifact_isolation(tmp_path: Path):
    """Verify that passing an output directory preserves canonical files and isolates test outputs."""
    canonical_dir = ROOT / "research" / "information_discovery"
    canonical_file = canonical_dir / "information_hypotheses_screening.json"
    
    canonical_mtime = canonical_file.stat().st_mtime if canonical_file.exists() else None

    # Run screening with temporary output directory
    report = build_information_hypotheses_screening_report(output_dir=tmp_path)
    
    isolated_file = tmp_path / "information_hypotheses_screening.json"
    assert isolated_file.exists()
    
    with open(isolated_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["phase_6_research_disposition"]["SFRP_MR"] == "INITIAL_SCREEN_UNFAVORABLE"
    assert data["phase_6_research_disposition"]["CARP_CS"] == "INITIAL_SCREEN_UNFAVORABLE"
    assert data["phase_6_research_disposition"]["AVRS_DESCRIPTIVE_REGIME_EVIDENCE"] == "AVAILABLE"
    assert data["phase_6_research_disposition"]["AVRS_CAUSAL_PREDICTIVE_VALUE"] == "NOT_EVALUATED"
    assert data["phase_6_research_disposition"]["AVRS_EXECUTABLE_ECONOMIC_VALUE"] == "NOT_EVALUATED"
    assert data["phase_6_research_disposition"]["AVRS_NEURAL_PILOT"] == "NOT_AUTHORIZED"
    assert data["phase_1_competing_hypotheses_screened"]["CATR_LRP"]["screening_disposition"] == "NON_NEURAL_EDGE_ONLY"
    
    # Ensure canonical file was NOT touched during the test
    if canonical_mtime is not None:
        assert canonical_file.stat().st_mtime == canonical_mtime
