"""
neural_trading/models/horizon_policy.py

Horizon-Aware Multi-Asset Neural Portfolio Policy (N0.3).
Decouples 1-hour market observation frequency from multi-hour execution cadence.
Directly optimizes target allocation across Cash and Risky Assets with exact
train/evaluation parity and zero soft-gating relaxation collapse.
"""
from __future__ import annotations

from typing import Tuple
import torch
import torch.nn as nn
import torch.nn.functional as F

from neural_trading.models.tcn_policy import CausalConv1dBlock


class HorizonAwarePolicy(nn.Module):
    """
    Causal neural policy that observes 1-hour multi-asset price dynamics
    and predicts optimal multi-hour horizon target allocations on the simplex Delta^(N+1).
    Index 0 is explicitly designated for Cash.
    """

    def __init__(
        self,
        num_assets: int = 5,
        lookback_window: int = 48,
        num_channels: int = 4,
        hidden_dim: int = 32,
        dilations: Tuple[int, ...] = (1, 2, 4, 8),
        kernel_size: int = 3,
        decision_horizon_hours: int = 12,
    ):
        super().__init__()
        self.num_assets = num_assets
        self.lookback_window = lookback_window
        self.num_channels = num_channels
        self.hidden_dim = hidden_dim
        self.decision_horizon_hours = decision_horizon_hours

        # 1. Asset-level Causal TCN Feature Extractor
        self.input_proj = nn.Conv1d(num_channels, hidden_dim, kernel_size=1)
        self.tcn = nn.Sequential(*[
            CausalConv1dBlock(
                in_channels=hidden_dim,
                out_channels=hidden_dim,
                kernel_size=kernel_size,
                dilation=d,
                dropout=0.10,
            )
            for d in dilations
        ])

        # 2. Cross-Asset Context & Allocation Heads
        # Concatenate asset feature with pooled market feature: hidden_dim * 2
        self.asset_head = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, 1),
        )

        # Explicit Learnable Cash Preference Parameter
        self.cash_bias = nn.Parameter(torch.tensor([0.5], dtype=torch.float32))

        # Horizon Return Conviction Head (predicts expected horizon Sharpe/return)
        self.conviction_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.GELU(),
            nn.Linear(hidden_dim // 2, 1),
        )

    def forward(
        self,
        market_x: torch.Tensor,  # (Batch, NumAssets, Lookback, Channels)
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Returns:
            target_weights: (Batch, NumAssets + 1) on simplex
            conviction: (Batch, 1) expected regime signal
        """
        B, N, T, F_dim = market_x.shape

        # Reshape to (B * N, F_dim, T) for parallel 1D causal convolutions
        x_reshaped = market_x.permute(0, 1, 3, 2).reshape(B * N, F_dim, T)
        h = self.input_proj(x_reshaped)
        h = self.tcn(h)

        # Extract last time step: (B * N, hidden_dim) -> (B, N, hidden_dim)
        h_last = h[:, :, -1].reshape(B, N, self.hidden_dim)

        # Market-wide pooled context: (B, hidden_dim)
        market_context = torch.mean(h_last, dim=1)
        market_ctx_exp = market_context.unsqueeze(1).expand(-1, N, -1)

        # Combine asset-specific representation with market context: (B, N, hidden_dim * 2)
        combined = torch.cat([h_last, market_ctx_exp], dim=-1)

        # Asset preference logits: (B, N)
        asset_logits = self.asset_head(combined).squeeze(-1)

        # Prepend Cash preference logit: (B, N + 1)
        cash_logit = self.cash_bias.unsqueeze(0).expand(B, 1)
        all_logits = torch.cat([cash_logit, asset_logits], dim=-1)

        target_weights = F.softmax(all_logits, dim=-1)
        conviction = self.conviction_head(market_context)

        return target_weights, conviction
