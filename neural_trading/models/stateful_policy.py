"""
neural_trading/models/stateful_policy.py

Stateful Cost-Aware Neural Portfolio Policy with Explicit HOLD/REBALANCE Gating.
Observes current drifted holdings, transaction costs, and market history to learn
when holding outperforms rebalancing.
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple
import torch
import torch.nn as nn
import torch.nn.functional as F

from neural_trading.models.tcn_policy import CausalConv1dBlock


class StatefulCostAwarePolicy(nn.Module):
    """
    Stateful Neural Policy with explicit HOLD action and cost-aware rebalancing gate.
    Takes market history X_t and current drifted portfolio weights w_t^drifted.
    Outputs:
        - gating probability g_t in [0, 1] (0 = HOLD, 1 = REBALANCE)
        - candidate target weights w_t^* in Simplex^{N+1}
        - effective weights w_t
    """

    def __init__(
        self,
        num_assets: int,
        lookback_window: int = 48,
        num_channels: int = 4,
        hidden_dim: int = 32,
        dilations: Sequence[int] = (1, 2, 4, 8),
        kernel_size: int = 3,
        dropout: float = 0.20,
        rebalance_threshold: float = 0.50,
    ):
        super().__init__()
        self.num_assets = num_assets
        self.lookback_window = lookback_window
        self.num_channels = num_channels
        self.hidden_dim = hidden_dim
        self.rebalance_threshold = rebalance_threshold

        # 1. Market Feature Encoder (Causal Dilated Convolutions)
        self.input_proj = nn.Conv1d(num_channels, hidden_dim, kernel_size=1)
        blocks = []
        for d in dilations:
            blocks.append(
                CausalConv1dBlock(
                    in_channels=hidden_dim,
                    out_channels=hidden_dim,
                    kernel_size=kernel_size,
                    dilation=d,
                    dropout=dropout,
                )
            )
        self.tcn = nn.Sequential(*blocks)

        # 2. Portfolio State Encoder: encodes current drifted weights (N+1)
        self.port_encoder = nn.Sequential(
            nn.Linear(num_assets + 1, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim // 2),
        )

        # 3. Cross-Asset Market Aggregator
        self.cross_asset_dense = nn.Linear(hidden_dim * 2 + (hidden_dim // 2), hidden_dim)

        # 4. Target Allocation Score Head
        self.target_score_head = nn.Linear(hidden_dim, 1)
        self.cash_bias = nn.Parameter(torch.tensor(0.5, dtype=torch.float32))

        # 5. Stateful Gating Head (HOLD vs REBALANCE Decision)
        # Evaluates combined market state, current weights, and potential turnover cost
        self.gating_head = nn.Sequential(
            nn.Linear(hidden_dim + num_assets + 1, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, 1),
        )
        # Initialize gate bias to favor HOLD initially (negative logit)
        with torch.no_grad():
            self.gating_head[-1].bias.fill_(-0.5)

    def forward(
        self,
        market_x: torch.Tensor,               # (Batch, N, Lookback, Channels)
        current_weights: torch.Tensor,        # (Batch, N + 1)
        deterministic: bool = False,
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Args:
            market_x: Market features tensor (B, N, T, F)
            current_weights: Drifted portfolio weights before rebalancing (B, N + 1)
            deterministic: If True, uses hard threshold for HOLD (inference mode)
        Returns:
            effective_weights: (B, N + 1)
            candidate_weights: (B, N + 1)
            gating_prob: (B, 1)
        """
        B, N, T, F_dim = market_x.shape
        device = market_x.device

        # Reshape for parallel asset convolution: (B * N, F_dim, T)
        x_reshaped = market_x.permute(0, 1, 3, 2).reshape(B * N, F_dim, T)
        h = self.input_proj(x_reshaped)
        h = self.tcn(h)

        # Take last time step: (B * N, hidden_dim)
        h_last = h[:, :, -1].reshape(B, N, self.hidden_dim)

        # Cross-asset pooled market context: (B, hidden_dim)
        market_context = torch.mean(h_last, dim=1)

        # Portfolio state encoding: (B, hidden_dim // 2)
        port_context = self.port_encoder(current_weights)

        # Expanded context for each asset: (B, N, hidden_dim * 2 + hidden_dim // 2)
        market_ctx_exp = market_context.unsqueeze(1).expand(-1, N, -1)
        port_ctx_exp = port_context.unsqueeze(1).expand(-1, N, -1)
        asset_combined = torch.cat([h_last, market_ctx_exp, port_ctx_exp], dim=-1)

        # Candidate Target Allocation
        h_asset = F.relu(self.cross_asset_dense(asset_combined))
        asset_scores = self.target_score_head(h_asset).squeeze(-1) # (B, N)

        # Append learnable cash score: (B, N + 1)
        cash_score = self.cash_bias.unsqueeze(0).expand(B, 1)
        all_scores = torch.cat([cash_score, asset_scores], dim=-1)
        candidate_weights = F.softmax(all_scores, dim=-1)

        # Gating Decision: HOLD vs REBALANCE
        # Input to gate: pooled market representation + current drifted weights
        gate_input = torch.cat([market_context, current_weights], dim=-1)
        gate_logit = self.gating_head(gate_input)
        gating_prob = torch.sigmoid(gate_logit) # (B, 1)

        if deterministic:
            # Discrete decision for exact inference/simulation:
            # If gating_prob < threshold: HOLD (effective = current drifted weights)
            # If gating_prob >= threshold: REBALANCE (effective = candidate_weights)
            is_rebal = (gating_prob >= self.rebalance_threshold).float()
            effective_weights = (1.0 - is_rebal) * current_weights + is_rebal * candidate_weights
        else:
            # Differentiable soft relaxation during rollout training
            effective_weights = (1.0 - gating_prob) * current_weights + gating_prob * candidate_weights

        return effective_weights, candidate_weights, gating_prob
