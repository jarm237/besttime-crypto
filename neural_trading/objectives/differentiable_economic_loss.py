"""
neural_trading/objectives/differentiable_economic_loss.py

Differentiable economic loss functions for end-to-end neural portfolio optimization.
Directly optimizes net post-friction Sharpe ratio, turnover penalties, and downside risk
using exact executed risky-asset notional.
"""
from __future__ import annotations

from typing import Dict, Tuple
import torch
import torch.nn as nn


class DifferentiableSharpeLoss(nn.Module):
    """
    End-to-End Differentiable Economic Loss Function.
    Simulates sequential portfolio weight drift, risky-asset turnover fees, and net return accumulation,
    returning the negative annualized net Sharpe ratio plus economic regularizers.
    """

    def __init__(
        self,
        friction_rate: float = 0.0014,      # 14 bps baseline roundtrip friction on executed risky notional
        lambda_turnover: float = 0.50,      # Turnover penalty weight
        lambda_downside: float = 2.00,      # Downside risk penalty weight
        annualization_factor: float = 2920.0,
        eps: float = 1e-6,
    ):
        super().__init__()
        self.friction_rate = friction_rate
        self.lambda_turnover = lambda_turnover
        self.lambda_downside = lambda_downside
        self.annualization_factor = (24.0 * 365.0) ** 0.5
        self.eps = eps

    def forward(
        self,
        weights_seq: torch.Tensor,
        price_relatives_seq: torch.Tensor,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """
        Args:
            weights_seq: Tensor of shape (K, N + 1)
                         Portfolio weights for K steps (Index 0 = Cash, 1..N = Assets)
            price_relatives_seq: Tensor of shape (K, N + 1)
                                 Price relatives y_t = p_t / p_{t-1} (Index 0 = 1.0 for Cash)
        Returns:
            loss: Scalar PyTorch tensor for backprop
            diagnostics: Dict of unscaled financial metrics (Sharpe, Net Return, Turnover, Cost)
        """
        K, N_plus_1 = weights_seq.shape
        device = weights_seq.device

        net_returns = []
        turnovers = []

        # Initial weight assumption prior to step 0 is 100% Cash: [1, 0, ..., 0]
        prev_w_drifted = torch.zeros(N_plus_1, device=device)
        prev_w_drifted[0] = 1.0

        for t in range(K):
            w_t = weights_seq[t]              # Target allocation at step t
            y_t = price_relatives_seq[t]      # Price relatives from step t to t+1

            # 1. Turnover at rebalance: L1 distance strictly on RISKY ASSETS (1..N)
            # Cash has no transaction fee
            turnover_risky_t = torch.sum(torch.abs(w_t[1:] - prev_w_drifted[1:]))
            cost_t = self.friction_rate * turnover_risky_t

            # 2. Gross return at step t+1
            gross_return_t = torch.sum(w_t * y_t) - 1.0

            # 3. Net return after friction
            net_return_t = gross_return_t - cost_t

            net_returns.append(net_return_t)
            turnovers.append(turnover_risky_t)

            # 4. Weight drift for next step: w'_i = (w_i * y_i) / (w^T y)
            gross_factor = torch.sum(w_t * y_t) + self.eps
            prev_w_drifted = (w_t * y_t) / gross_factor

        net_returns_tensor = torch.stack(net_returns)
        turnovers_tensor = torch.stack(turnovers)

        # Statistical Moments
        mean_r = torch.mean(net_returns_tensor)
        var_r = torch.mean((net_returns_tensor - mean_r) ** 2)
        std_r = torch.sqrt(var_r + self.eps)

        # Differentiable Annualized Sharpe
        annualized_sharpe = (mean_r / std_r) * self.annualization_factor

        # Downside Semi-Variance Penalty (Loss aversion)
        downside_diff = torch.relu(-net_returns_tensor)
        downside_penalty = torch.mean(downside_diff ** 2) * 100.0

        # Mean Turnover Penalty
        mean_turnover = torch.mean(turnovers_tensor)

        # Total Loss to Minimize
        loss = -annualized_sharpe + (self.lambda_turnover * mean_turnover * 100.0) + (self.lambda_downside * downside_penalty)

        diagnostics = {
            "loss": float(loss.item()),
            "annualized_sharpe": float(annualized_sharpe.item()),
            "mean_net_return_bps": float(mean_r.item() * 10000.0),
            "mean_turnover_pct": float(mean_turnover.item() * 100.0),
            "downside_penalty": float(downside_penalty.item()),
        }

        return loss, diagnostics
