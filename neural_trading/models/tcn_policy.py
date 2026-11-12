"""
neural_trading/models/tcn_policy.py

Temporal Convolutional Network with Causal Dilated Convolutions and
Differentiable Portfolio Allocation (TCN-DPA).
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from neural_trading.models.base import BaseNeuralPolicy


class CausalConv1dBlock(nn.Module):
    """
    1D Causal Dilated Convolution Block with residual skip connection.
    Guarantees that output at step t depends strictly on inputs at or before step t.
    """

    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_size: int = 3,
        dilation: int = 1,
        dropout: float = 0.20,
    ):
        super().__init__()
        self.kernel_size = kernel_size
        self.dilation = dilation
        self.padding = (kernel_size - 1) * dilation

        self.conv1 = nn.Conv1d(
            in_channels,
            out_channels,
            kernel_size=kernel_size,
            dilation=dilation,
            padding=0,  # Manual causal padding applied in forward
        )
        self.norm1 = nn.BatchNorm1d(out_channels)
        self.relu1 = nn.ReLU()
        self.drop1 = nn.Dropout(dropout)

        self.conv2 = nn.Conv1d(
            out_channels,
            out_channels,
            kernel_size=kernel_size,
            dilation=dilation,
            padding=0,
        )
        self.norm2 = nn.BatchNorm1d(out_channels)
        self.relu2 = nn.ReLU()
        self.drop2 = nn.Dropout(dropout)

        # Residual projection if channel dimensions differ
        self.downsample = nn.Conv1d(in_channels, out_channels, 1) if in_channels != out_channels else None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x shape: (Batch * N, Channels, Time)
        res = x if self.downsample is None else self.downsample(x)

        # Causal padding: pad left by `padding`, right by 0
        x_pad1 = F.pad(x, (self.padding, 0))
        out = self.conv1(x_pad1)
        out = self.norm1(out)
        out = self.relu1(out)
        out = self.drop1(out)

        x_pad2 = F.pad(out, (self.padding, 0))
        out = self.conv2(x_pad2)
        out = self.norm2(out)
        out = self.relu2(out)
        out = self.drop2(out)

        return out + res


class TcnPortfolioPolicy(BaseNeuralPolicy):
    """
    Unified Multi-Asset TCN Policy.
    Encodes temporal dynamics per asset via causal dilated convolutions,
    shares cross-asset market beta context, and maps into portfolio weights.
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
        temperature: float = 1.0,
    ):
        super().__init__(num_assets, lookback_window, num_channels)
        self.hidden_dim = hidden_dim
        self.temperature = temperature

        # 1. Feature Projection
        self.input_proj = nn.Conv1d(num_channels, hidden_dim, kernel_size=1)

        # 2. Stack of Causal Dilated Convolutional Blocks
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
        self.tcn_blocks = nn.ModuleList(blocks)

        # 3. Cross-Asset Interaction Layer
        # Combines individual asset latent state with market-wide average latent state
        self.cross_asset_dense = nn.Linear(hidden_dim * 2, hidden_dim)

        # 4. Allocation Scoring Head
        self.score_head = nn.Linear(hidden_dim, 1)

        # Learnable cash bias parameter (controls default risk aversion)
        self.cash_bias = nn.Parameter(torch.tensor(0.5, dtype=torch.float32))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: Tensor of shape (Batch, num_assets, lookback_window, num_channels)
        Returns:
            weights: Tensor of shape (Batch, num_assets + 1)
                     Index 0 = Cash, Indices 1..N = Risky Assets
        """
        B, N, T, F_dim = x.shape

        # Reshape to process all assets through shared TCN: (B * N, F_dim, T)
        x_reshaped = x.permute(0, 1, 3, 2).reshape(B * N, F_dim, T)

        h = self.input_proj(x_reshaped)
        for block in self.tcn_blocks:
            h = block(h)

        # Extract latest time step latent representation: h[:, :, -1] -> (B * N, hidden_dim)
        h_last = h[:, :, -1].reshape(B, N, self.hidden_dim)

        # Cross-asset pooling: compute market average latent vector across all N assets
        h_market = h_last.mean(dim=1, keepdim=True).expand(B, N, self.hidden_dim)

        # Combine asset latent state with market latent context
        h_combined = torch.cat([h_last, h_market], dim=-1)  # (B, N, hidden_dim * 2)
        h_interact = F.relu(self.cross_asset_dense(h_combined))

        # Asset scores: (B, N, 1) -> (B, N)
        asset_scores = self.score_head(h_interact).squeeze(-1)

        # Cash score: (B, 1)
        cash_score = self.cash_bias.expand(B, 1)

        # Full score vector: [cash_score, asset_1, ..., asset_N] -> (B, N + 1)
        full_scores = torch.cat([cash_score, asset_scores], dim=-1)

        # Softmax allocation over the simplex
        weights = F.softmax(full_scores / self.temperature, dim=-1)
        return weights
