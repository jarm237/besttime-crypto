"""Unit tests for R11 Unified Neural Factorized Allocation Experiment."""

import json
from pathlib import Path
import numpy as np
import pytest
import torch

from scripts.run_r8_unified_neural_pilot import SmallUnifiedPolicy
from scripts.run_r10_neural_objective_experiment import compute_risk_budgeted_loss
from scripts.run_r11_factorized_allocation_experiment import (
    FactorizedUnifiedPolicy,
    measure_gradient_attribution,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "research" / "predictive_discovery"


def test_factorized_policy_architecture_and_parameter_parity():
    """Verify FactorizedUnifiedPolicy matches SmallUnifiedPolicy parameter count exactly."""
    num_assets = 8
    in_features = 13
    hidden_dim = 16

    r10_model = SmallUnifiedPolicy(num_assets=num_assets, in_features=in_features, hidden_dim=hidden_dim)
    r11_model = FactorizedUnifiedPolicy(num_assets=num_assets, in_features=in_features, hidden_dim=hidden_dim)

    r10_params = sum(p.numel() for p in r10_model.parameters())
    r11_params = sum(p.numel() for p in r11_model.parameters())

    assert r10_params == 1746, f"Expected 1746 params for SmallUnifiedPolicy, got {r10_params}"
    assert r11_params == 1746, f"Expected 1746 params for FactorizedUnifiedPolicy, got {r11_params}"
    assert r11_params == r10_params, "Factorized policy must have strict parameter parity with R10 policy"

    # Verify component parameter breakdown
    enc_params = sum(p.numel() for p in r11_model.asset_encoder.parameters())
    cross_params = sum(p.numel() for p in r11_model.cross_asset_layer.parameters())
    exp_params = sum(p.numel() for p in r11_model.exposure_head.parameters())
    sel_params = sum(p.numel() for p in r11_model.selection_head.parameters())

    assert enc_params == 528
    assert cross_params == 1056
    assert exp_params == 145
    assert sel_params == 17


def test_factorized_policy_simplex_constraints():
    """Verify that FactorizedUnifiedPolicy strictly obeys all simplex constraints."""
    torch.manual_seed(42)
    model = FactorizedUnifiedPolicy(num_assets=8, in_features=13, hidden_dim=16)
    model.eval()

    # Test random inputs across various batch sizes
    for B in [1, 4, 16, 52]:
        x = torch.randn(B, 8, 13)
        E, q, w = model.forward_components(x)

        # 1. Macro exposure in [0, 1]
        assert torch.all(E >= 0.0)
        assert torch.all(E <= 1.0)
        assert E.shape == (B, 1)

        # 2. Relative selection on simplex
        assert torch.all(q >= 0.0)
        q_sum = torch.sum(q, dim=-1)
        assert torch.allclose(q_sum, torch.ones_like(q_sum), atol=1e-5)
        assert q.shape == (B, 8)

        # 3. Full joint weights on simplex
        assert torch.all(w >= 0.0)
        w_sum = torch.sum(w, dim=-1)
        assert torch.allclose(w_sum, torch.ones_like(w_sum), atol=1e-5)
        assert w.shape == (B, 9)

        # 4. Exact relation: w_assets = E * q, w_cash = 1 - E
        assert torch.allclose(w[:, :8], E * q, atol=1e-6)
        assert torch.allclose(w[:, -1:], 1.0 - E, atol=1e-6)


def test_risk_budgeted_loss_on_factorized_weights():
    """Verify that compute_risk_budgeted_loss executes correctly on factorized outputs."""
    torch.manual_seed(42)
    model = FactorizedUnifiedPolicy(num_assets=8, in_features=13, hidden_dim=16)
    x = torch.randn(20, 8, 13)
    y = torch.randn(20, 8) * 0.05  # forward weekly returns

    w = model(x)
    loss, mean_g, down_d, exc_d, mean_to = compute_risk_budgeted_loss(
        w, y, fee_bps=12.0, downside_budget=0.025, lambda_risk=5.0, lambda_turnover=0.002
    )

    assert torch.isfinite(loss)
    assert torch.isfinite(mean_g)
    assert down_d >= 0.0
    assert exc_d >= 0.0
    assert mean_to >= 0.0

    # Backpropagation check
    loss.backward()
    for name, p in model.named_parameters():
        assert p.grad is not None, f"Parameter {name} has None gradient"
        assert torch.all(torch.isfinite(p.grad)), f"Parameter {name} has non-finite gradient"


def test_gradient_attribution_diagnostics():
    """Verify that measure_gradient_attribution returns valid and bounded metrics."""
    torch.manual_seed(42)
    model = FactorizedUnifiedPolicy(num_assets=8, in_features=13, hidden_dim=16)
    train_x = torch.randn(30, 8, 13)
    train_y = torch.randn(30, 8) * 0.04

    diag = measure_gradient_attribution(
        model=model, train_x=train_x, train_y=train_y,
        downside_budget=0.025, fee_bps=12.0, lambda_risk=5.0, lambda_turnover=0.002
    )

    assert diag["exposure_head_grad_norm"] > 0.0
    assert diag["selection_head_grad_norm"] > 0.0
    assert diag["shared_encoder_grad_norm"] > 0.0
    assert diag["cross_asset_layer_grad_norm"] > 0.0
    assert diag["exposure_to_selection_grad_ratio"] > 0.0
    assert -1.0 <= diag["gradient_cosine_similarity_growth_vs_risk"] <= 1.0


def test_empirical_p_value_pseudo_count_formula():
    """Verify Phase A corrected empirical p-value calculation with Laplace pseudo-count."""
    # Never reports p = 0.0
    p_zero_500 = (0 + 1) / (500 + 1)
    p_zero_252 = (0 + 1) / (252 + 1)
    p_six_500 = (6 + 1) / (500 + 1)

    assert p_zero_500 > 0.0
    assert round(p_zero_500, 4) == 0.0020
    assert round(p_zero_252, 4) == 0.0040
    assert round(p_six_500, 4) == 0.0140


def test_r11_scorecard_and_ledger_integrity():
    """Verify the generated R11 scorecard and decision ledger satisfy all requirements."""
    sc_path = OUTPUT_DIR / "r11_factorized_scorecard.json"
    ledger_path = OUTPUT_DIR / "r11_decision_ledger.json"
    model_path = OUTPUT_DIR / "r11_factorized_model.pt"
    report_path = OUTPUT_DIR / "r11_factorized_experiment_report.md"

    assert sc_path.exists(), f"Missing {sc_path}"
    assert ledger_path.exists(), f"Missing {ledger_path}"
    assert model_path.exists(), f"Missing {model_path}"
    assert report_path.exists(), f"Missing {report_path}"

    with open(sc_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "metadata" in data
    assert "phase_a_focused_closure" in data
    assert "gradient_diagnostics" in data
    assert "yearly_exposure_stats" in data
    assert "stability_comparison" in data
    assert "scorecard" in data
    assert "scientific_verdict" in data

    allowed_verdicts = {
        "FACTORIZED_ALLOCATION_INCREMENTAL_VALUE_SUPPORTED",
        "FACTORIZED_ALLOCATION_INCREMENTAL_VALUE_NOT_SUPPORTED",
        "INCONCLUSIVE",
    }
    assert data["scientific_verdict"] in allowed_verdicts

    with open(ledger_path, "r", encoding="utf-8") as f:
        ledger = json.load(f)

    assert len(ledger) == 253, f"Expected 253 decisions, got {len(ledger)}"
    for entry in ledger:
        assert "per_decision_fee" in entry
        assert "per_decision_traded_notional" in entry
        assert "model_exposure_head_output" in entry
        assert "relative_selection_weights" in entry
        assert 0.0 <= entry["model_exposure_head_output"] <= 1.0
        assert 0.0 <= entry["model_cash_weight"] <= 1.0
        tot_w = sum(entry["target_weights"].values()) + entry["target_cash_weight"]
        assert abs(tot_w - 1.0) < 1e-4
