"""
neural_trading/models/base.py

Abstract base class for all neural portfolio policy architectures.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import torch
import torch.nn as nn


class BaseNeuralPolicy(nn.Module, ABC):
    """
    Abstract neural policy mapping market state tensor (B, N, T, F)
    into target portfolio allocation weights (B, N + 1) on the simplex.
    Index 0 strictly represents Cash (USDT).
    Indices 1..N represent risky crypto assets.
    """

    def __init__(self, num_assets: int, lookback_window: int, num_channels: int):
        super().__init__()
        self.num_assets = num_assets
        self.lookback_window = lookback_window
        self.num_channels = num_channels

    @abstractmethod
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: Tensor of shape (Batch, num_assets, lookback_window, num_channels)
        Returns:
            weights: Tensor of shape (Batch, num_assets + 1) where sum(dim=-1) == 1.0 and >= 0.0
        """
        raise NotImplementedError
