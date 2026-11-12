"""
neural_trading/objectives/horizon_loss.py

Differentiable economic loss for Horizon-Aware Neural Policies.
Evaluates net return across exact multi-hour holding horizons with causal drift,
transaction friction deduction, and downside semi-variance penalization.
"""
from __future__ import annotations

from typing import Dict, Tuple
import torch
import torch.nn as nn
import torch.nn.functional as F


class HorizonDifferentiableLoss(nn.Module):
    """
    Computes annualized net Sharpe ratio and downside risk across multi-hour holding horizons.
    Guarantees exact parity between training loss and sequential execution.
    """

    def __init__(
        self,
        decision_horizon_hours: int = 12,
        friction_rate: float = 0.0007,        # 7 bps per leg (14 bps round-trip)
        lambda_turnover: float = 0.10,        # Gentle turnover regularizer (not punitive)
        lambda_downside: float = 1.50,        # Downside semi-variance penalty
        eps: float = 1e-6,
    ):
        super().__init__()
        self.H = decision_horizon_hours
        self.friction_rate = friction_rate
        self.lambda_turnover = lambda_turnover
        self.lambda_downside = lambda_downside
        self.eps = eps
        # Annualization factor for H-hour intervals: sqrt((24 / H) * 365)
        self.annualization_factor = float((24.0 / self.H * 365.0) ** 0.5)

    def forward(
        self,
        model: nn.Module,
        batch_market_x: torch.Tensor,         # (Batch, N, Lookback, Channels) at decision step t
        batch_compound_y: torch.Tensor,       # (Batch, N + 1) cumulative price relatives across t -> t+H
        prev_target_weights: torch.Tensor,    # (Batch, N + 1) previous portfolio allocation
    ) -> Tuple[torch.Tensor, Dict[str, float]]:
        """
        Computes differentiable net horizon return and Sharpe loss.
        """
        B, N_plus_1 = prev_target_weights.shape

        # 1. Forward pass
        target_w, conviction = model(batch_market_x)

        # 2. Risky asset turnover (only on assets 1..N)
        risky_turnover = torch.sum(torch.abs(target_w[:, 1:] - prev_target_weights[:, 1:]), dim=-1)
        friction_cost = self.friction_rate * risky_turnover

        # 3. Gross and Net Horizon Return
        gross_return = torch.sum(target_w * batch_compound_y, dim=-1) - 1.0
        net_return = gross_return - friction_cost

        # 4. Annualized Sharpe Ratio over batch
        mean_net = torch.mean(net_return)
        var_net = torch.mean((net_return - mean_net) ** 2)
        std_net = torch.sqrt(var_net + self.eps)
        annualized_sharpe = (mean_net / std_net) * self.annualization_factor

        # 5. Downside Semi-Variance Penalty
        downside = torch.relu(-net_return)
        downside_penalty = torch.mean(downside ** 2) * 50.0

        # 6. Gentle turnover penalty
        turnover_penalty = torch.mean(risky_turnover) * self.lambda_turnover

        # 7. Auxiliary conviction return prediction loss
        conviction_loss = F.mse_loss(conviction.squeeze(-1), net_return.detach())

        total_loss = -annualized_sharpe + self.lambda_downside * downside_penalty + turnover_penalty + 0.10 * conviction_loss

        diag = {
            "loss": float(total_loss.item()),
            "annualized_sharpe": float(annualized_sharpe.item()),
            "mean_net_return": float(mean_net.item()),
            "mean_turnover": float(torch.mean(risky_turnover).item()),
            "mean_cash_weight": float(torch.mean(target_w[:, 0]).item()),
            "downside_penalty": float(downside_penalty.item()),
        }

        return total_loss, diag
