"""
tests/test_neural_trading_n0.py

Targeted unit and invariant tests for Greenfield Neural Trading (Phase N0):
1. Causal Conv1d zero-lookahead invariance (future tampering does not affect past outputs).
2. Portfolio simplex constraint validation (sum == 1.0, non-negative).
3. Deterministic Hard-Risk Barrier enforcement (minimum cash, max single-asset cap, NaN recovery).
4. Differentiable Sharpe Loss gradient flow (non-zero autograd gradients to all parameters).
5. Portfolio simulator cash conservation & accounting reconciliation.
"""
from __future__ import annotations

import numpy as np
import pytest
import torch

from neural_trading.engine.hard_risk import DeterministicHardRiskBarrier
from neural_trading.engine.portfolio_simulator import NeuralPortfolioSimulator
from neural_trading.models.tcn_policy import CausalConv1dBlock, TcnPortfolioPolicy
from neural_trading.objectives.differentiable_economic_loss import DifferentiableSharpeLoss


def test_causal_conv1d_zero_lookahead_invariance():
    """Verify modifying future time steps does not change past outputs in CausalConv1dBlock."""
    torch.manual_seed(42)
    block = CausalConv1dBlock(in_channels=4, out_channels=8, kernel_size=3, dilation=2, dropout=0.0)
    block.eval()

    # Input: (Batch, Channels, Time)
    x1 = torch.randn(2, 4, 30)
    x2 = x1.clone()

    # Tamper with future bars (indices 20 to 29)
    x2[:, :, 20:] += 1000.0

    with torch.no_grad():
        out1 = block(x1)
        out2 = block(x2)

    # Output at or before index 19 must be mathematically identical
    diff = torch.max(torch.abs(out1[:, :, :20] - out2[:, :, :20])).item()
    assert diff < 1e-6, f"Causal violation: tampering future bars changed past output (diff={diff})"


def test_portfolio_simplex_constraints():
    """Verify TCN policy outputs valid probability distribution on simplex (sum == 1.0, >= 0)."""
    torch.manual_seed(42)
    model = TcnPortfolioPolicy(num_assets=5, lookback_window=24, num_channels=4, hidden_dim=16)
    model.eval()

    # Input: (Batch=4, Assets=5, Time=24, Channels=4)
    x = torch.randn(4, 5, 24, 4)
    with torch.no_grad():
        w = model(x)

    assert w.shape == (4, 6), f"Expected shape (4, 6), got {w.shape}"
    # Sum to 1.0
    sums = torch.sum(w, dim=-1)
    assert torch.allclose(sums, torch.ones(4), atol=1e-5), f"Simplex violation: sums = {sums}"
    # Non-negative
    assert (w >= 0.0).all(), "Negative weight detected in portfolio policy output"


def test_hard_risk_barrier_enforcement():
    """Verify hard risk barrier guarantees minimum cash slack, asset caps, and handles NaNs."""
    barrier = DeterministicHardRiskBarrier(min_cash_pct=0.10, max_asset_pct=0.30)

    # Case 1: Proposed weight violates single-asset cap (asset 1 has 80%)
    raw_w = np.array([0.0, 0.80, 0.10, 0.05, 0.05])
    projected = barrier.enforce_numpy(raw_w)

    assert projected[0] >= 0.10 - 1e-5, f"Cash slack violated: {projected[0]}"
    for i in range(1, len(projected)):
        assert projected[i] <= 0.30 + 1e-5, f"Asset cap violated on asset {i}: {projected[i]}"
    assert abs(np.sum(projected) - 1.0) < 1e-5

    # Case 2: NaN emergency override -> must revert to 100% Cash
    nan_w = np.array([0.20, np.nan, 0.30, 0.20, 0.30])
    safe_w = barrier.enforce_numpy(nan_w)
    assert safe_w[0] == 1.0
    assert np.sum(safe_w[1:]) == 0.0


def test_differentiable_sharpe_gradient_flow():
    """Verify autograd computes non-zero gradients to all model parameters through economic loss."""
    torch.manual_seed(42)
    model = TcnPortfolioPolicy(num_assets=3, lookback_window=16, num_channels=2, hidden_dim=8)
    loss_fn = DifferentiableSharpeLoss(friction_rate=0.0014)

    # Rollout of length K=10
    x_seq = torch.randn(10, 3, 16, 2)
    # Price relatives for 3 assets + Cash: (10, 4)
    y_seq = torch.tensor([[1.0, 1.01, 0.99, 1.02]] * 10, dtype=torch.float32)

    weights = model(x_seq)
    loss, diag = loss_fn(weights, y_seq)

    loss.backward()

    # Verify every trainable parameter receives valid, finite gradient
    for name, param in model.named_parameters():
        if param.requires_grad:
            assert param.grad is not None, f"Parameter {name} has no gradient"
            assert not torch.isnan(param.grad).any(), f"Parameter {name} has NaN gradient"
            assert torch.sum(torch.abs(param.grad)).item() > 0.0, f"Parameter {name} has zero gradient"


def test_portfolio_simulator_conservation_of_capital():
    """Verify simulator cashflow accounting and friction deduction."""
    simulator = NeuralPortfolioSimulator(
        symbols=["BTCUSDT", "ETHUSDT"],
        initial_capital=10_000.0,
        fee_bps=10.0,
        slippage_bps=0.0,
        typical_spread_bps=0.0,
    )

    # 3 steps, 2 assets + cash
    # Step 0: 100% Cash -> Step 1: 50% Asset 1, 50% Asset 2 -> 100% turnover
    weights_seq = np.array([
        [1.0, 0.0, 0.0],
        [0.0, 0.5, 0.5],
        [0.0, 0.5, 0.5],
    ])
    # Flat prices (y = 1.0) -> purely tests friction deduction
    price_relatives = np.array([
        [1.0, 1.0],
        [1.0, 1.0],
        [1.0, 1.0],
    ])
    timestamps = ["2025-01-01 00:00", "2025-01-01 01:00", "2025-01-01 02:00"]

    res = simulator.simulate(weights_seq, price_relatives, timestamps)
    # Friction cost should be positive and final equity should be less than initial
    assert res["total_friction_usd"] > 0.0
    assert res["final_equity"] < 10_000.0
    assert abs(res["final_equity"] - (10_000.0 - res["total_friction_usd"])) < 1.0
