"""
neural_trading/objectives/stateful_loss.py

Differentiable economic loss function for sequential stateful rollout training.
Penalizes risky turnover, unnecessary rebalance gating, and downside volatility.
"""
from __future__ import annotations

from typing import Dict, Tuple
import torch
import torch.nn as nn


class StatefulDifferentiableLoss(nn.Module):
    """
    Simulates sequential rollout dynamics for stateful policies with explicit HOLD/REBALANCE gating.
    Computes end-to-end differentiable net Sharpe, turnover penalty, and churn regularizer.
    """

    def __init__(
        self,
        friction_rate: float = 0.0007,       # 7 bps per leg (14 bps round-trip)
        lambda_turnover: float = 0.50,       # Turnover penalty
        lambda_churn: float = 0.30,          # Penalize rebalance frequency (reward HOLD)
        lambda_downside: float = 2.00,       # Downside risk penalty
        annualization_factor: float = 93.59, # sqrt(24 * 365)
        eps: float = 1e-6,
    ):
        super().__init__()
        self.friction_rate = friction_rate
        self.lambda_turnover = lambda_turnover
        self.lambda_churn = lambda_churn
        self.lambda_downside = lambda_downside
        self.annualization_factor = annualization_factor
        self.eps = eps

    def forward(
        self,
        model: nn.Module,
        market_seq: torch.Tensor,            # (Rollout, N, T, F)
        price_relatives_seq: torch.Tensor,   # (Rollout, N + 1)
        initial_weights: Optional[torch.Tensor] = None,
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """
        Executes a causal multi-step rollout through the stateful neural policy.
        """
        L, N, T, F_dim = market_seq.shape
        device = market_seq.device

        curr_drifted_w = initial_weights if initial_weights is not None else torch.zeros(N + 1, device=device)
        if initial_weights is None:
            curr_drifted_w[0] = 1.0  # 100% Cash

        net_returns = []
        turnovers = []
        gates = []

        for t in range(L):
            x_t = market_seq[t].unsqueeze(0)             # (1, N, T, F)
            w_input = curr_drifted_w.unsqueeze(0)        # (1, N + 1)
            y_t = price_relatives_seq[t]                 # (N + 1,)

            # Policy forward pass (soft relaxation mode)
            eff_w, cand_w, g_t = model(x_t, w_input, deterministic=False)
            eff_w = eff_w.squeeze(0)
            cand_w = cand_w.squeeze(0)
            g_t = g_t.squeeze()

            # Risky turnover: only on assets (1..N)
            risky_turnover_t = g_t * torch.sum(torch.abs(cand_w[1:] - curr_drifted_w[1:]))
            cost_t = self.friction_rate * risky_turnover_t

            gross_return_t = torch.sum(eff_w * y_t) - 1.0
            net_return_t = gross_return_t - cost_t

            net_returns.append(net_return_t)
            turnovers.append(risky_turnover_t)
            gates.append(g_t)

            # Drift to next time step
            gross_factor = torch.sum(eff_w * y_t) + self.eps
            curr_drifted_w = (eff_w * y_t) / gross_factor

        net_returns_tensor = torch.stack(net_returns)
        turnovers_tensor = torch.stack(turnovers)
        gates_tensor = torch.stack(gates)

        mean_r = torch.mean(net_returns_tensor)
        var_r = torch.mean((net_returns_tensor - mean_r) ** 2)
        std_r = torch.sqrt(var_r + self.eps)

        annualized_sharpe = (mean_r / std_r) * self.annualization_factor
        downside_diff = torch.relu(-net_returns_tensor)
        downside_penalty = torch.mean(downside_diff ** 2) * 100.0

        mean_turnover = torch.mean(turnovers_tensor)
        mean_gate = torch.mean(gates_tensor)

        loss = (
            -annualized_sharpe
            + (self.lambda_turnover * mean_turnover * 100.0)
            + (self.lambda_churn * mean_gate * 10.0)
            + (self.lambda_downside * downside_penalty)
        )

        diagnostics = {
            "loss": float(loss.item()),
            "annualized_sharpe": float(annualized_sharpe.item()),
            "mean_net_return_bps": float(mean_r.item() * 10000.0),
            "mean_turnover": float(mean_turnover.item()),
            "rebalance_rate": float(mean_gate.item()),
            "downside_penalty": float(downside_penalty.item()),
        }

        return loss, diagnostics
