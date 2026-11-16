"""Unit tests for Unified Neural Pilot and Standardized Portfolio Accounting."""

import pytest
import numpy as np
import pandas as pd
import torch
from datetime import datetime, timezone, timedelta

from btc_scraper.research.portfolio_accounting import compute_standardized_metrics, execute_rebalance_step
from btc_scraper.research.unified_neural_pilot import UnifiedNeuralPolicy, compute_cost_aware_loss


def test_unified_neural_policy_shape_and_constraints():
    """Verify neural policy outputs exactly N+1 non-negative weights summing to 1.0."""
    B, N, F = 4, 8, 8
    model = UnifiedNeuralPolicy(num_assets=N, in_features=F, hidden_dim=16)

    # Random input tensor
    x = torch.randn(B, N, F)
    weights = model(x)

    # Check shape [B, N+1]
    assert weights.shape == (B, N + 1)

    # Check non-negativity
    assert (weights >= 0.0).all().item() is True

    # Check sum to 1.0
    sums = weights.sum(dim=-1)
    for b in range(B):
        assert sums[b].item() == pytest.approx(1.0, abs=1e-5)


def test_standardized_portfolio_accounting_rebalance_step():
    """Verify exact calculation of one-way turnover, gross asset turnover, traded notional and fee."""
    N = 4
    open_prices = np.array([100.0, 200.0, 50.0, 10.0])
    current_holdings = np.array([10.0, 5.0, 20.0, 100.0])  # Total asset value = 1000 + 1000 + 1000 + 1000 = 4000
    current_cash = 1000.0  # Total equity before = 5000.0
    # Current asset weights: [0.2, 0.2, 0.2, 0.2], cash = 0.2

    # Target: 50% in asset 0, 50% in cash (0% in others)
    target_weights = np.array([0.5, 0.0, 0.0, 0.0])
    target_cash_w = 0.5
    fee_bps = 12.0  # 0.0012

    (
        new_holdings,
        new_cash,
        traded_notional,
        fee_paid,
        to_1way,
        to_gross,
    ) = execute_rebalance_step(
        current_holdings=current_holdings,
        current_cash=current_cash,
        open_prices=open_prices,
        target_weights=target_weights,
        target_cash_w=target_cash_w,
        fee_bps=fee_bps,
    )

    # Asset weight changes:
    # Asset 0: |0.5 - 0.2| = 0.3
    # Asset 1: |0.0 - 0.2| = 0.2
    # Asset 2: |0.0 - 0.2| = 0.2
    # Asset 3: |0.0 - 0.2| = 0.2
    # Gross asset turnover = 0.3 + 0.2 + 0.2 + 0.2 = 0.9
    assert to_gross == pytest.approx(0.9)

    # Cash weight change: |0.5 - 0.2| = 0.3
    # One-way turnover = 0.5 * (0.9 + 0.3) = 0.6
    assert to_1way == pytest.approx(0.6)

    # Traded notional = 0.9 * 5000.0 = 4500.0
    assert traded_notional == pytest.approx(4500.0)

    # Fee paid = 4500.0 * 0.0012 = 5.40
    assert fee_paid == pytest.approx(5.40)

    # Total post-fee equity = 5000.0 - 5.40 = 4994.60
    post_fee_equity = 5000.0 - 5.40
    assert new_cash == pytest.approx(post_fee_equity * 0.5)
    assert (new_holdings[0] * open_prices[0]) == pytest.approx(post_fee_equity * 0.5)


def test_cost_aware_loss_gradient_flow():
    """Verify cost-aware loss produces clean gradients back to model parameters."""
    W, N, F = 10, 8, 8
    model = UnifiedNeuralPolicy(num_assets=N, in_features=F, hidden_dim=16)

    x = torch.randn(W, N, F)
    forward_rets = torch.randn(W, N) * 0.05

    weights = model(x)
    loss, mean_ret, downside, turnover = compute_cost_aware_loss(
        weights=weights,
        forward_returns=forward_rets,
        fee_bps=12.0,
    )

    loss.backward()

    # Check all parameter gradients are valid finite numbers
    for name, param in model.named_parameters():
        assert param.grad is not None
        assert not torch.isnan(param.grad).any()
        assert not torch.isinf(param.grad).any()
