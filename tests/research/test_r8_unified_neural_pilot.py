"""Targeted tests for R8 Small Unified Multi-Asset Risk-Aware Neural Pilot."""

import numpy as np
import pytest
import torch

from scripts.run_r8_unified_neural_pilot import (
    SmallUnifiedPolicy,
    compute_cost_aware_downside_loss,
)


def test_small_unified_policy_simplex_constraints():
    """Verify that SmallUnifiedPolicy strictly outputs valid portfolio simplex weights."""
    batch_size = 4
    num_assets = 8
    in_features = 13
    hidden_dim = 16

    model = SmallUnifiedPolicy(num_assets=num_assets, in_features=in_features, hidden_dim=hidden_dim)
    model.eval()

    x = torch.randn(batch_size, num_assets, in_features)
    weights = model(x)

    # 1. Shape must be [B, N + 1]
    assert weights.shape == (batch_size, num_assets + 1)

    # 2. Non-negativity (long-only)
    assert (weights >= 0.0).all()

    # 3. Sum of weights (assets + cash) equals 1.0
    weight_sums = weights.sum(dim=-1)
    for s in weight_sums:
        assert pytest.approx(float(s), abs=1e-5) == 1.0


def test_cost_aware_loss_turnover_and_downside_penalties():
    """Verify that cost-aware loss penalizes higher turnover and downside variance."""
    W = 10
    N = 8

    # Case A: Zero turnover (constant weights)
    w_const = torch.zeros(W, N + 1)
    w_const[:, 0] = 0.5
    w_const[:, -1] = 0.5  # 50% asset 0, 50% cash

    # Case B: Maximum alternating turnover (flapping between 100% cash and 100% asset 0)
    w_flapping = torch.zeros(W, N + 1)
    for i in range(W):
        if i % 2 == 0:
            w_flapping[i, 0] = 1.0
        else:
            w_flapping[i, -1] = 1.0

    # Constant positive return
    fwd_ret = torch.full((W, N), 0.05)

    loss_const, net_c, _, to_c = compute_cost_aware_downside_loss(
        w_const, fwd_ret, fee_bps=12.0, lambda_downside=1.0, lambda_turnover=0.01
    )
    loss_flap, net_f, _, to_f = compute_cost_aware_downside_loss(
        w_flapping, fwd_ret, fee_bps=12.0, lambda_downside=1.0, lambda_turnover=0.01
    )

    # Flapping strategy incurs higher turnover
    assert float(to_f) > float(to_c)

    # Consequently, flapping strategy suffers higher loss
    assert float(loss_flap) > float(loss_const)
