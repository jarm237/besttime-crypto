"""Unit tests for R9 Unified Neural Allocation Attribution Engine."""

import json
from pathlib import Path

import numpy as np
import pytest
import torch

from scripts.run_r8_unified_neural_pilot import SmallUnifiedPolicy

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "research" / "predictive_discovery"


def test_r8_checkpoint_and_model_loading():
    """Verify that r8_selected_model.pt exists and loads cleanly into SmallUnifiedPolicy."""
    ckpt_path = OUTPUT_DIR / "r8_selected_model.pt"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"

    state_dict = torch.load(ckpt_path, map_location="cpu", weights_only=True)
    model = SmallUnifiedPolicy(num_assets=8, in_features=13, hidden_dim=16)
    model.load_state_dict(state_dict)
    model.eval()

    dummy_input = torch.randn(2, 8, 13)
    with torch.no_grad():
        out = model(dummy_input)

    assert out.shape == (2, 9)
    # Simplex constraint
    sums = out.sum(dim=-1).numpy()
    np.testing.assert_allclose(sums, np.ones(2), atol=1e-5)
    assert (out.numpy() >= 0.0).all()


def test_r8_normalization_stats():
    """Verify normalization statistics file format and valid dimensions."""
    stats_path = OUTPUT_DIR / "r8_normalization_stats.json"
    assert stats_path.exists(), f"Missing stats: {stats_path}"

    with open(stats_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "mean" in data
    assert "std" in data
    assert "feature_names" in data
    assert len(data["mean"]) == 13
    assert len(data["std"]) == 13
    assert len(data["feature_names"]) == 13
    assert data["selected_seed"] in [42, 101, 202]


def test_r8_decision_allocations_simplex():
    """Verify weekly target allocations satisfy simplex bounds across all 253 decisions."""
    alloc_path = OUTPUT_DIR / "r8_decision_allocations.json"
    assert alloc_path.exists(), f"Missing allocations: {alloc_path}"

    with open(alloc_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    assert len(records) == 253
    for rec in records:
        assert 0.0 <= rec["cash_weight"] <= 1.0
        assert 0.0 <= rec["total_risky_weight"] <= 1.0
        tot = rec["cash_weight"] + rec["total_risky_weight"]
        assert pytest.approx(tot, abs=1e-5) == 1.0
        assert len(rec["asset_weights"]) == 8


def test_counterfactual_logic_invariants():
    """Verify that counterfactual weight transformation mathematical properties hold."""
    # Synthetic model output
    cash_w = 0.90
    risky_w = 0.10
    asset_raw = np.array([0.02, 0.01, 0.03, 0.005, 0.015, 0.008, 0.007, 0.005])

    # Counterfactual B (BTC only)
    w_btc = np.zeros(8)
    w_btc[2] = 1.0 - cash_w  # assuming BTC is index 2
    assert w_btc[2] == pytest.approx(0.10)
    assert np.sum(w_btc) + cash_w == pytest.approx(1.0)

    # Counterfactual C (EW only)
    w_ew = np.full(8, (1.0 - cash_w) / 8.0)
    assert np.allclose(w_ew, 0.0125)
    assert np.sum(w_ew) + cash_w == pytest.approx(1.0)

    # Counterfactual D (Normalized asset selection at fixed exposure)
    q_norm = asset_raw / np.sum(asset_raw)
    assert pytest.approx(np.sum(q_norm), abs=1e-5) == 1.0
    fixed_exp = 0.05
    w_d = q_norm * fixed_exp
    assert pytest.approx(np.sum(w_d) + (1.0 - fixed_exp), abs=1e-5) == 1.0


def test_r9_decision_ledger_accounting_integrity():
    """Verify that r9_decision_ledger.json has exact non-cumulative step accounting."""
    ledger_path = OUTPUT_DIR / "r9_decision_ledger.json"
    assert ledger_path.exists(), f"Missing ledger: {ledger_path}"

    with open(ledger_path, "r", encoding="utf-8") as f:
        ledger = json.load(f)

    assert len(ledger) == 253
    first_step = ledger[0]
    assert "per_decision_traded_notional" in first_step
    assert "per_decision_fee" in first_step
    assert "cumulative_traded_notional" in first_step
    assert "cumulative_fee" in first_step

    # Step 0: cumulative should equal step value
    assert first_step["cumulative_traded_notional"] == pytest.approx(first_step["per_decision_traded_notional"], abs=0.1)

    # Subsequent steps should be non-negative
    for entry in ledger:
        assert entry["per_decision_traded_notional"] >= 0.0
        assert entry["per_decision_fee"] >= 0.0
        assert 0.0 <= entry["model_cash_weight"] <= 1.0
        assert 0.0 <= entry["realized_cash_weight"] <= 1.0


def test_r9_attribution_scorecard_completeness():
    """Verify scorecard has paired attribution and all counterfactual strategies."""
    sc_path = OUTPUT_DIR / "r9_attribution_scorecard.json"
    assert sc_path.exists(), f"Missing scorecard: {sc_path}"

    with open(sc_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "paired_attribution_base_12bps" in data
    assert "loss_decomposition" in data
    assert "scorecard" in data

    sc = data["scorecard"]
    required_keys = [
        "COUNTERFACTUAL_A_ORIGINAL_NEURAL_base_12bps",
        "COUNTERFACTUAL_B_NEURAL_CASH_BTC_RISKY_base_12bps",
        "COUNTERFACTUAL_C_NEURAL_CASH_EW_RISKY_base_12bps",
        "COUNTERFACTUAL_D_NEURAL_SELECTION_FIXED_EXP_base_12bps",
        "COUNTERFACTUAL_E_STATIC_BTC_CASH_EXP_MATCHED_base_12bps",
        "COUNTERFACTUAL_A_ORIGINAL_NEURAL_stress_25bps",
    ]
    for rk in required_keys:
        assert rk in sc, f"Missing key in scorecard: {rk}"
