"""
tests/test_stateful_policy.py

Targeted tests for StatefulCostAwarePolicy and StatefulDifferentiableLoss.
"""
import pytest
import torch
import numpy as np
from neural_trading.models.stateful_policy import StatefulCostAwarePolicy
from neural_trading.objectives.stateful_loss import StatefulDifferentiableLoss


def test_stateful_policy_forward_shape():
    batch_size = 2
    num_assets = 5
    lookback = 48
    num_channels = 4

    policy = StatefulCostAwarePolicy(
        num_assets=num_assets,
        lookback_window=lookback,
        num_channels=num_channels,
        hidden_dim=16,
        dilations=(1, 2, 4),
    )

    x = torch.randn(batch_size, num_assets, lookback, num_channels)
    prev_w = torch.zeros(batch_size, num_assets + 1)
    prev_w[:, 0] = 1.0  # 100% Cash

    # Soft relaxation forward
    eff_w, cand_w, gate_p = policy(x, prev_w, deterministic=False)
    assert eff_w.shape == (batch_size, num_assets + 1)
    assert cand_w.shape == (batch_size, num_assets + 1)
    assert gate_p.shape == (batch_size, 1)

    # Simplex sum to 1
    assert torch.allclose(torch.sum(eff_w, dim=-1), torch.ones(batch_size), atol=1e-5)
    assert torch.allclose(torch.sum(cand_w, dim=-1), torch.ones(batch_size), atol=1e-5)
    assert (gate_p >= 0.0).all() and (gate_p <= 1.0).all()


def test_stateful_loss_backward():
    num_assets = 5
    lookback = 48
    rollout_len = 8

    policy = StatefulCostAwarePolicy(
        num_assets=num_assets,
        lookback_window=lookback,
        num_channels=4,
        hidden_dim=16,
        dilations=(1, 2),
    )
    loss_fn = StatefulDifferentiableLoss(
        friction_rate=0.0007,
        lambda_turnover=0.5,
        lambda_churn=0.2,
        lambda_downside=1.0,
    )

    x_seq = torch.randn(rollout_len, num_assets, lookback, 4)
    y_seq = torch.ones(rollout_len, num_assets + 1) + torch.randn(rollout_len, num_assets + 1) * 0.01

    loss, diag = loss_fn(policy, x_seq, y_seq)
    assert isinstance(loss, torch.Tensor)
    assert not torch.isnan(loss)
    assert "annualized_sharpe" in diag
    assert "mean_turnover" in diag
    assert "rebalance_rate" in diag

    loss.backward()
    for param in policy.parameters():
        if param.requires_grad:
            assert param.grad is not None
