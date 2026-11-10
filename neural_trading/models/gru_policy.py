"""
neural_trading/models/gru_policy.py

Multi-Asset Recurrent Neural Policy (GRU) benchmark for comparative evaluation.
"""
from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from neural_trading.models.base import BaseNeuralPolicy


class GruPortfolioPolicy(BaseNeuralPolicy):
    """
    Recurrent Gated Recurrent Unit (GRU) Multi-Asset Portfolio Policy.
    Serves as an architectural benchmark against the primary TCN-DPA model.
    """

    def __init__(
        self,
        num_assets: int,
        lookback_window: int = 48,
        num_channels: int = 5,
        hidden_dim: int = 32,
        num_layers: int = 2,
        dropout: float = 0.20,
        temperature: float = 1.0,
    ):
        super().__init__(num_assets, lookback_window, num_channels)
        self.hidden_dim = hidden_dim
        self.temperature = temperature

        self.gru = nn.GRU(
            input_size=num_channels,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )

        self.cross_asset_dense = nn.Linear(hidden_dim * 2, hidden_dim)
        self.score_head = nn.Linear(hidden_dim, 1)
        self.cash_bias = nn.Parameter(torch.tensor(0.5, dtype=torch.float32))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, N, T, F_dim = x.shape
        x_reshaped = x.reshape(B * N, T, F_dim)

        out, _ = self.gru(x_reshaped)
        h_last = out[:, -1, :].reshape(B, N, self.hidden_dim)

        h_market = h_last.mean(dim=1, keepdim=True).expand(B, N, self.hidden_dim)
        h_combined = torch.cat([h_last, h_market], dim=-1)
        h_interact = F.relu(self.cross_asset_dense(h_combined))

        asset_scores = self.score_head(h_interact).squeeze(-1)
        cash_score = self.cash_bias.expand(B, 1)

        full_scores = torch.cat([cash_score, asset_scores], dim=-1)
        weights = F.softmax(full_scores / self.temperature, dim=-1)
        return weights
