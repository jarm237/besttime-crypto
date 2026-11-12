"""
tests/test_horizon_policy.py

Targeted tests for HorizonAwarePolicy and HorizonDifferentiableLoss.
"""
import pytest
import torch
import numpy as np
from neural_trading.models.horizon_policy import HorizonAwarePolicy
from neural_trading.objectives.horizon_loss import HorizonDifferentiableLoss


def test_horizon_policy_forward():
    batch_size = 4
    num_assets = 5
    lookback = 48
    num_channels = 4

    policy = HorizonAwarePolicy(
        num_assets=num_assets,
        lookback_window=lookback,
        num_channels=num_channels,
        hidden_dim=16,
        dilations=(1, 2, 4),
        decision_horizon_hours=12,
    )

    x = torch.randn(batch_size, num_assets, lookback, num_channels)
    target_w, conviction = policy(x)

    assert target_w.shape == (batch_size, num_assets + 1)
    assert conviction.shape == (batch_size, 1)

    # Simplex sum to 1.0
    assert torch.allclose(torch.sum(target_w, dim=-1), torch.ones(batch_size), atol=1e-5)
    assert (target_w >= 0.0).all()


def test_horizon_loss_backward():
    batch_size = 4
    num_assets = 5
    lookback = 48

    policy = HorizonAwarePolicy(
        num_assets=num_assets,
        lookback_window=lookback,
        num_channels=4,
        hidden_dim=16,
        dilations=(1, 2),
        decision_horizon_hours=12,
    )
    loss_fn = HorizonDifferentiableLoss(
        decision_horizon_hours=12,
        friction_rate=0.0007,
        lambda_turnover=0.1,
        lambda_downside=1.0,
    )

    x = torch.randn(batch_size, num_assets, lookback, 4)
    compound_y = torch.ones(batch_size, num_assets + 1) + torch.randn(batch_size, num_assets + 1) * 0.02
    prev_w = torch.zeros(batch_size, num_assets + 1)
    prev_w[:, 0] = 1.0  # Cash

    loss, diag = loss_fn(policy, x, compound_y, prev_w)
    assert isinstance(loss, torch.Tensor)
    assert not torch.isnan(loss)
    assert "annualized_sharpe" in diag
    assert "mean_turnover" in diag

    loss.backward()
    for param in policy.parameters():
        if param.requires_grad:
            assert param.grad is not None
