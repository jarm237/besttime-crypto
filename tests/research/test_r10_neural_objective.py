"""Unit tests for R10 Unified Neural Objective & Seed-Stability Experiment."""

import json
from pathlib import Path

import numpy as np
import pytest
import torch

from scripts.run_r8_unified_neural_pilot import SmallUnifiedPolicy
from scripts.run_r10_neural_objective_experiment import compute_risk_budgeted_loss

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "research" / "predictive_discovery"


def test_risk_budgeted_loss_zero_penalty_within_budget():
    """Verify that portfolio with risk below or equal to budget incurs ZERO risk penalty."""
    weights = torch.zeros(10, 9)
    weights[:, -1] = 1.0  # 100% cash
    forward_returns = torch.randn(10, 8) * 0.05

    loss, log_g, down_d, exc_d, to = compute_risk_budgeted_loss(
        weights, forward_returns, downside_budget=0.025, lambda_risk=5.0
    )
    # 100% cash has zero downside deviation -> below budget
    assert exc_d.item() == 0.0
    assert pytest.approx(loss.item(), abs=1e-5) == (-log_g.item() + 0.002 * to.item())


def test_risk_budgeted_loss_active_penalty_above_budget():
    """Verify that excessive downside deviation triggers quadratic penalty."""
    weights = torch.zeros(10, 9)
    weights[:, 0] = 1.0  # 100% asset 0
    # Create large negative returns
    forward_returns = torch.full((10, 8), -0.10)

    loss, log_g, down_d, exc_d, to = compute_risk_budgeted_loss(
        weights, forward_returns, downside_budget=0.025, lambda_risk=5.0
    )
    assert down_d.item() > 0.025
    assert exc_d.item() > 0.0
    expected_penalty = 5.0 * (exc_d.item() ** 2)
    assert pytest.approx(loss.item(), abs=1e-4) == (-log_g.item() + expected_penalty + 0.002 * to.item())


def test_r10_model_checkpoint_and_simplex_validity():
    """Verify r10_selected_model.pt loads and satisfies simplex constraints."""
    ckpt_path = OUTPUT_DIR / "r10_selected_model.pt"
    assert ckpt_path.exists(), f"Missing checkpoint: {ckpt_path}"

    state_dict = torch.load(ckpt_path, map_location="cpu", weights_only=True)
    model = SmallUnifiedPolicy(num_assets=8, in_features=13, hidden_dim=16)
    model.load_state_dict(state_dict)
    model.eval()

    dummy_x = torch.randn(5, 8, 13)
    with torch.no_grad():
        out = model(dummy_x)

    assert out.shape == (5, 9)
    sums = out.sum(dim=-1).numpy()
    np.testing.assert_allclose(sums, np.ones(5), atol=1e-5)
    assert (out.numpy() >= 0.0).all()


def test_r10_falsification_scorecard():
    """Verify falsification null distributions and p-values."""
    fals_path = OUTPUT_DIR / "r10_falsification_scorecard.json"
    assert fals_path.exists(), f"Missing falsification scorecard: {fals_path}"

    with open(fals_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "temporal_permutation_null_distribution" in data
    assert "circular_shift_null_distribution" in data

    perm = data["temporal_permutation_null_distribution"]
    assert perm["n_permutations"] == 500
    assert 0.0 <= perm["empirical_p_value_return"] <= 1.0
    assert 0.0 <= perm["percentile_rank_return"] <= 100.0

    circ = data["circular_shift_null_distribution"]
    assert circ["n_shifts"] == 252
    assert 0.0 <= circ["empirical_p_value_return"] <= 1.0


def test_r10_objective_scorecard_and_stability():
    """Verify scorecard records seed stability and evaluation metrics."""
    sc_path = OUTPUT_DIR / "r10_objective_scorecard.json"
    assert sc_path.exists(), f"Missing scorecard: {sc_path}"

    with open(sc_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "stability_comparison" in data
    assert "r10_seed_evaluations_base_12bps" in data
    assert "scorecard" in data

    stab = data["stability_comparison"]
    assert stab["cash_variance_reduced"] is True
    assert stab["r10_seed_mean_cash_pct"]["std_dev"] < stab["r8_seed_mean_cash_pct"]["std_dev"]


def test_r10_decision_ledger():
    """Verify decision ledger structure and step accounting."""
    ledger_path = OUTPUT_DIR / "r10_decision_ledger.json"
    assert ledger_path.exists(), f"Missing ledger: {ledger_path}"

    with open(ledger_path, "r", encoding="utf-8") as f:
        ledger = json.load(f)

    assert len(ledger) == 253
    for entry in ledger[:5]:
        assert "per_decision_traded_notional" in entry
        assert "per_decision_fee" in entry
        assert entry["per_decision_fee"] >= 0.0
        assert 0.0 <= entry["model_cash_weight"] <= 1.0


def test_corrected_r9_report_exists():
    """Verify r9_attribution_report_corrected.md was created."""
    corrected_path = OUTPUT_DIR / "r9_attribution_report_corrected.md"
    assert corrected_path.exists(), f"Missing corrected report: {corrected_path}"
    with open(corrected_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Train-Matched Fixed Exposure" in content
    assert "20.44x" in content
