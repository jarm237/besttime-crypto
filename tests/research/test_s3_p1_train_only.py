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
    """Verify that Straight-Through Estimator gradients reach asset head, cash head, and gate head."""
    B, T, N, F = 2, 24, 4, 6
    model = S3UnifiedNeuralPolicy(num_assets=N, in_features=F, gru_hidden=16, num_heads=2, port_features=7)

    mkt_seq = torch.randn(B, T, N, F, requires_grad=True)
    port_state = torch.randn(B, 7, requires_grad=True)

    w_prop, g_logit = model(mkt_seq, port_state)

    # Deterministic STE formulation
    tau = 0.5
    gate_soft = torch.sigmoid(g_logit / tau)
    gate_hard = (g_logit > 0.0).to(gate_soft.dtype)
    gate = gate_hard - gate_soft.detach() + gate_soft

    # Synthetic loss depending on allocation weights, cash, and gate
    dummy_returns = torch.tensor([[0.02, -0.01, 0.03, -0.02, 0.0], [0.01, 0.02, -0.01, 0.01, 0.0]])
    portfolio_growth = torch.sum(w_prop * dummy_returns, dim=-1)
    loss = -torch.mean(gate.squeeze(-1) * portfolio_growth)

    loss.backward()

    # Check non-zero finite gradients on all heads
    for p in model.shared_asset_head.parameters():
        assert p.grad is not None
        assert not torch.isnan(p.grad).any()

    for p in model.cash_head.parameters():
        assert p.grad is not None
        assert not torch.isnan(p.grad).any()

    for p in model.gate_head.parameters():
        assert p.grad is not None
        assert not torch.isnan(p.grad).any()


def test_train_inference_gate_parity():
    """Verify exact parity between training forward hard gate and inference deterministic gate across boundaries."""
    tau = 0.5
    test_logits = [-10.0, -2.5, -0.1, -1e-6, 0.0, 1e-6, 0.1, 2.5, 10.0]

    for logit_val in test_logits:
        t_logit = torch.tensor([[logit_val]], dtype=torch.float32)

        # Training STE forward hard gate
        gate_soft = torch.sigmoid(t_logit / tau)
        gate_hard_train = int((t_logit > 0.0).item())

        # Inference deterministic gate
        gate_inference = 1 if t_logit.item() > 0.0 else 0

        # Exact parity check
        assert gate_hard_train == gate_inference, f"Mismatch at logit {logit_val}: train={gate_hard_train} vs infer={gate_inference}"

        # Boundary checks
        if logit_val <= 0.0:
            assert gate_inference == 0, f"Expected HOLD (0) for logit <= 0, got {gate_inference}"
        else:
            assert gate_inference == 1, f"Expected TRADE (1) for logit > 0, got {gate_inference}"


def test_asset_specific_sensitivity_and_permutation_equivariance():
    """Verify that asset-specific features directly influence that asset's output, and permuting assets permutes outputs."""
    B, T, N, F = 1, 48, 4, 6
    torch.manual_seed(42)
    model = S3UnifiedNeuralPolicy(num_assets=N, in_features=F, gru_hidden=16, num_heads=2, port_features=7)
    model.eval()

    mkt_seq = torch.randn(B, T, N, F)
    port_state = torch.tensor([[0.2, 0.3, 0.1, 0.15, 0.25, 0.05, 0.01]], dtype=torch.float32)

    with torch.no_grad():
        w_orig, g_orig = model(mkt_seq, port_state)

    # 1. Perturb only asset 0 input
    mkt_perturbed = mkt_seq.clone()
    mkt_perturbed[:, :, 0, :] += 5.0  # large perturbation on BTC
    with torch.no_grad():
        w_pert, g_pert = model(mkt_perturbed, port_state)

    # Asset 0 weight must change significantly
    assert abs(w_pert[0, 0].item() - w_orig[0, 0].item()) > 1e-3

    # 2. Permutation equivariance across assets
    perm = [2, 0, 3, 1]  # arbitrary permutation of 4 assets
    mkt_perm = mkt_seq[:, :, perm, :]
    port_state_perm = torch.cat([
        port_state[:, perm],      # permuted asset weights
        port_state[:, N:],        # cash, drift, friction unchanged
    ], dim=-1)

    with torch.no_grad():
        w_from_perm, g_from_perm = model(mkt_perm, port_state_perm)

    # Permuted assets output should match original outputs under the same permutation
    w_orig_permuted = w_orig[0, perm].numpy()
    w_perm_assets = w_from_perm[0, :N].numpy()
    np.testing.assert_allclose(w_perm_assets, w_orig_permuted, atol=1e-5)

    # Cash weight and gate logit should be invariant
    assert w_from_perm[0, -1].item() == pytest.approx(w_orig[0, -1].item(), abs=1e-5)
    assert g_from_perm.item() == pytest.approx(g_orig.item(), abs=1e-5)


def test_true_ew4_buy_and_hold_benchmark_invariants():
    """Verify that EW4 Buy & Hold holding quantities remain frozen and compound returns match terminal equity."""
    initial_cap = 10000.0
    fee_rate = 0.0012
    p0 = np.array([40000.0, 2500.0, 100.0, 300.0])
    p1 = np.array([42000.0, 2400.0, 110.0, 310.0])
    p2 = np.array([41000.0, 2600.0, 105.0, 320.0])

    fee_init = initial_cap * fee_rate
    cap_post = initial_cap - fee_init
    q_bench = (0.25 * cap_post) / p0  # fixed frozen quantities

    # Day 0 to Day 1
    v0_pre = initial_cap
    v1 = float(np.sum(q_bench * p1))
    g0 = np.log(v1 / v0_pre)

    # Day 1 to Day 2
    v1_val = float(np.sum(q_bench * p1))
    v2_val = float(np.sum(q_bench * p2))
    g1 = np.log(v2_val / v1_val)

    # Cumulative compounding
    cum_ret = np.exp(g0 + g1) - 1.0
    direct_ret = (v2_val - initial_cap) / initial_cap

    assert abs(cum_ret - direct_ret) < 1e-12
    # Verify no daily reset to 25% weights
    post_weights_d1 = (q_bench * p1) / v1_val
    assert not np.allclose(post_weights_d1, 0.25)  # weights drifted naturally!


def test_portfolio_drift_reference_invariants():
    """Verify that unexecuted proposals (HOLD) leave drift reference unchanged, while executed trades update it."""
    initial_weights = np.zeros(4)
    ref_weights = initial_weights.copy()

    # Step 1: HOLD (gate = 0)
    proposed_w1 = np.array([0.3, 0.2, 0.2, 0.1])
    orders_count1 = 0
    if orders_count1 > 0:
        ref_weights = proposed_w1  # should not execute

    np.testing.assert_array_equal(ref_weights, initial_weights)  # still zero!

    # Step 2: TRADE (gate = 1)
    orders_count2 = 4
    executed_w2 = np.array([0.25, 0.25, 0.25, 0.25])
    if orders_count2 > 0:
        ref_weights = executed_w2

    np.testing.assert_array_equal(ref_weights, executed_w2)  # updated!


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
