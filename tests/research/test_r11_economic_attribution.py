"""Unit tests for R11 Economic Attribution & Execution Fidelity Audit."""

import json
from pathlib import Path
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "research" / "predictive_discovery"


def test_scorecard_and_ledger_schema_completeness():
    """Verify that R11 economic attribution scorecard and delayed ledger exist and have complete schema."""
    sc_path = OUTPUT_DIR / "r11_economic_attribution_scorecard.json"
    ledger_path = OUTPUT_DIR / "r11_causal_delayed_ledger.json"
    report_path = OUTPUT_DIR / "r11_economic_attribution_report.md"

    assert sc_path.exists(), f"Missing {sc_path}"
    assert ledger_path.exists(), f"Missing {ledger_path}"
    assert report_path.exists(), f"Missing {report_path}"

    with open(sc_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "metadata" in data
    assert "phase_a_execution_fidelity" in data
    assert "phase_b_cost_parity_audit" in data
    assert "phase_c_pnl_attribution" in data
    assert "phase_d_seed_diagnostics" in data
    assert "phase_e_verdicts" in data

    verdicts = data["phase_e_verdicts"]
    assert verdicts["TRAIN_RETURN_CONCENTRATION_OBSERVED"] is True
    assert verdicts["ASSET_SELECTION_INCREMENTAL_VALUE"] == "NOT_SUPPORTED"
    assert verdicts["CASH_TIMING_HISTORICAL_CONTRIBUTION_OBSERVED"] is True
    assert verdicts["CASH_TIMING_PREDICTIVE_GENERALIZATION"] == "NOT_ESTABLISHED"
    assert verdicts["UNIFIED_NEURAL_ALPHA"] == "NOT_ESTABLISHED"
    assert verdicts["R11_FACTORISATION"] == "COMPLETED_EXPLORATORY"
    assert verdicts["PRODUCTION_PROMOTION"] == "NOT_AUTHORIZED"
    assert verdicts["GENERALIZATION_NOT_ESTABLISHED"] is True


def test_causal_pending_order_delay_zero_replication():
    """Verify that causal pending-order execution replicates baseline R11 results within 0.05% tolerance."""
    with open(OUTPUT_DIR / "r11_economic_attribution_scorecard.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    p_a0 = data["phase_a_execution_fidelity"]["baseline_delay_0h_replication"]
    assert p_a0["replication_status"] == "EXACT_PARITY_VERIFIED"
    assert abs(p_a0["numerical_delta_pct"]) < 0.05
    assert abs(p_a0["reproduced_sharpe"] - p_a0["published_r11_sharpe"]) < 0.01


def test_causal_delayed_ledger_properties():
    """Verify that causal delayed ledger correctly tracks execution timestamps and trades."""
    with open(OUTPUT_DIR / "r11_causal_delayed_ledger.json", "r", encoding="utf-8") as f:
        ledger = json.load(f)

    assert len(ledger) == 253
    for entry in ledger:
        assert entry["execution_delay_hours"] == 1
        dec_time = entry["decision_time"]
        fill_time = entry["order_fill_time"]
        assert fill_time > dec_time
        assert entry["per_decision_fee"] >= 0.0
        assert entry["per_decision_traded_notional"] >= 0.0


def test_cost_parity_surrogate_understatement():
    """Verify that the training loss surrogate understated spot fees by over 30%."""
    with open(OUTPUT_DIR / "r11_economic_attribution_scorecard.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    p_b = data["phase_b_cost_parity_audit"]
    assert p_b["total_actual_fees_usd"] > p_b["total_surrogate_fees_usd"]
    assert p_b["total_fee_understatement_usd"] > 4000.0
    assert p_b["mean_fee_understatement_pct"] > 30.0
    assert p_b["gross_to_one_way_ratio"] > 1.5


def test_pnl_concentration_top_5_weeks():
    """Verify that top 5 weeks generated over 70% of total Train gross PnL."""
    with open(OUTPUT_DIR / "r11_economic_attribution_scorecard.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    p_c = data["phase_c_pnl_attribution"]
    conc = p_c["train_pnl_concentration"]

    assert conc["top_5_weeks_share_pct"] > 70.0
    assert conc["top_10_weeks_share_pct"] > 80.0

    # SOL was the undisputed top gross earner in 2023
    pnl_2023 = p_c["year_2023_coin_gross_pnl_usd"]
    top_coin_2023 = list(pnl_2023.keys())[0]
    assert top_coin_2023 == "SOLUSDT"
    assert pnl_2023["SOLUSDT"] > 30000.0


def test_counterfactual_selection_vs_btc():
    """Verify that Counterfactual D (neural selection at fixed exp) underperformed Counterfactual E in Holdout."""
    with open(OUTPUT_DIR / "r11_economic_attribution_scorecard.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    cf = data["phase_c_pnl_attribution"]["counterfactual_comparison"]
    sub = cf["subperiod_returns"]

    # In Holdout (2025-2026), neural selection underperformed static BTC
    assert sub["D_r11_selection_fixed_train_exp"]["holdout"] < sub["E_static_btc_fixed_train_exp"]["holdout"]
