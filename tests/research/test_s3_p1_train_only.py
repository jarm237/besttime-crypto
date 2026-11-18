"""Unit tests for S3-P1 Unified Neural Policy, Causal Timeline, and Exact Accounting."""

import numpy as np
import pytest
import torch

from btc_scraper.research.portfolio_accounting import execute_self_consistent_rebalance_step
from btc_scraper.research.s3_p1_train_only import (
    CausalMVOL1Optimizer,
    S3UnifiedNeuralPolicy,
)


def test_s3_unified_neural_policy_shape_and_simplex():
    """Verify S3 neural policy produces valid simplex allocations and gate logits within parameter budget."""
    B, T, N, F = 2, 168, 4, 6
    port_F = 7
    model = S3UnifiedNeuralPolicy(num_assets=N, in_features=F, gru_hidden=32, num_heads=2, port_features=port_F)

    param_count = model.get_parameter_count()
    assert param_count <= 25000, f"Parameter budget exceeded: {param_count} > 25000"

    market_seq = torch.randn(B, T, N, F)
    port_state = torch.randn(B, port_F)

    w_prop, g_logit = model(market_seq, port_state)

    # Output dimensions
    assert w_prop.shape == (B, N + 1)
    assert g_logit.shape == (B, 1)

    # Simplex constraints: non-negativity and sum to 1.0
    assert (w_prop >= 0.0).all().item() is True
    sums = w_prop.sum(dim=-1)
    for b in range(B):
        assert sums[b].item() == pytest.approx(1.0, abs=1e-5)


def test_exact_hold_invariants():
    """Verify exact HOLD semantics: g=0 produces 0 orders, $0 notional, $0 fees, frozen units."""
    N = 4
    open_prices = np.array([50000.0, 3000.0, 100.0, 400.0])
    current_holdings = np.array([0.1, 1.0, 10.0, 5.0])
    current_cash = 2000.0
    target_weights = np.array([0.4, 0.2, 0.1, 0.1])
    target_cash_w = 0.2

    (
        new_holdings,
        new_cash,
        traded_notional,
        fee_paid,
        to_1way,
        to_gross,
        orders_count,
    ) = execute_self_consistent_rebalance_step(
        current_holdings=current_holdings,
        current_cash=current_cash,
        open_prices=open_prices,
        target_weights=target_weights,
        target_cash_w=target_cash_w,
        action_gate=0,  # EXACT HOLD
        fee_bps=12.0,
    )

    # Physical units and cash must be completely frozen
    np.testing.assert_array_equal(new_holdings, current_holdings)
    assert new_cash == current_cash
    assert traded_notional == 0.0
    assert fee_paid == 0.0
    assert orders_count == 0
    assert to_1way == 0.0
    assert to_gross == 0.0


def test_self_consistent_fixed_point_fee_equation():
    """Verify that fee exactly equals fee_rate * actual executed notional (no approximation error)."""
    open_prices = np.array([100.0, 50.0, 20.0, 10.0])
    current_holdings = np.array([0.0, 0.0, 0.0, 0.0])  # start 100% in cash
    current_cash = 10000.0

    target_weights = np.array([0.25, 0.25, 0.25, 0.25])
    target_cash_w = 0.0
    fee_rate = 0.0012  # 12 bps

    (
        new_holdings,
        new_cash,
        actual_traded_notional,
        fee_paid,
        to_1way,
        to_gross,
        orders_count,
    ) = execute_self_consistent_rebalance_step(
        current_holdings=current_holdings,
        current_cash=current_cash,
        open_prices=open_prices,
        target_weights=target_weights,
        target_cash_w=target_cash_w,
        action_gate=1,
        fee_bps=12.0,
    )

    # Exact reconciliation
    assert abs(fee_paid - fee_rate * actual_traded_notional) < 1e-6
    # Conservation invariant
    equity_before = current_cash + float(np.sum(current_holdings * open_prices))
    equity_post = new_cash + float(np.sum(new_holdings * open_prices))
    assert abs(equity_post - (equity_before - fee_paid)) < 1e-6
    assert new_cash >= 0.0
    assert (new_holdings >= 0.0).all()
    assert orders_count == 4


def test_ste_gradient_flow_to_both_heads():
    """Verify that Straight-Through Estimator gradients reach both allocation and gate heads."""
    B, T, N, F = 2, 24, 4, 6
    model = S3UnifiedNeuralPolicy(num_assets=N, in_features=F, gru_hidden=16, num_heads=2, port_features=7)

    mkt_seq = torch.randn(B, T, N, F, requires_grad=True)
    port_state = torch.randn(B, 7, requires_grad=True)

    w_prop, g_logit = model(mkt_seq, port_state)

    # Set positive gate logit to authorize trade (gate_hard == 1)
    # STE formulation
    tau = 0.5
    gate_soft = torch.sigmoid((g_logit + 3.0) / tau)
    gate_hard = (gate_soft > 0.5).float()
    gate = gate_hard + gate_soft - gate_soft.detach()

    # Synthetic loss depending on both allocation weights and gate
    dummy_returns = torch.tensor([[0.02, -0.01, 0.03, -0.02, 0.0], [0.01, 0.02, -0.01, 0.01, 0.0]])
    portfolio_growth = torch.sum(w_prop * dummy_returns, dim=-1)
    loss = -torch.mean(gate.squeeze(-1) * portfolio_growth)

    loss.backward()

    # Check non-zero finite gradients on both heads
    assert model.alloc_head.weight.grad is not None
    assert model.alloc_head.weight.grad.norm().item() > 0.0
    assert not torch.isnan(model.alloc_head.weight.grad).any()

    assert model.gate_head.weight.grad is not None
    assert model.gate_head.weight.grad.norm().item() > 0.0
    assert not torch.isnan(model.gate_head.weight.grad).any()


def test_causal_mvo_l1_convexity_and_constraints():
    """Verify that Causal MVO-L1 produces feasible simplex weights using decision-observable weights."""
    N = 4
    mu = np.array([0.005, 0.002, -0.001, 0.003])
    sigma = np.array([
        [0.0010, 0.0004, 0.0002, 0.0003],
        [0.0004, 0.0008, 0.0001, 0.0002],
        [0.0002, 0.0001, 0.0012, 0.0001],
        [0.0003, 0.0002, 0.0001, 0.0009],
    ])
    obs_weights = np.array([0.25, 0.25, 0.25, 0.25])

    opt = CausalMVOL1Optimizer(gamma=2.0, fee_bps=12.0)
    w_star = opt.optimize(mu_24h=mu, sigma_24h=sigma, obs_asset_weights=obs_weights)

    assert len(w_star) == N + 1
    assert (w_star >= 0.0).all()
    assert abs(float(np.sum(w_star)) - 1.0) < 1e-5
    # Asset with negative expected return should receive lower allocation
    assert w_star[2] < obs_weights[2]
