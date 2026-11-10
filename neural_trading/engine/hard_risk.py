"""
neural_trading/engine/hard_risk.py

Deterministic hard-risk barrier and portfolio constraint projection layer.
Ensures neural outputs can never violate capital preservation or concentration invariants.
"""
from __future__ import annotations

import numpy as np
import torch


class DeterministicHardRiskBarrier:
    """
    Guarantees immutable risk constraints on any proposed allocation vector.
    Executes post-neural projection: Pi_C(w).
    """

    def __init__(
        self,
        min_cash_pct: float = 0.05,        # At least 5% retained in Cash
        max_asset_pct: float = 0.35,       # No asset exceeds 35% of total portfolio
        max_turnover_step: float = 0.50,   # Slew rate limit on rebalance step
    ):
        self.min_cash_pct = min_cash_pct
        self.max_asset_pct = max_asset_pct
        self.max_turnover_step = max_turnover_step

    def enforce_numpy(
        self,
        target_weights: np.ndarray,
        current_weights: np.ndarray | None = None,
    ) -> np.ndarray:
        """
        Enforces constraints on a 1D numpy array of weights [cash, asset_1, ..., asset_N].
        """
        # 1. NaN / Inf Emergency Guard
        if np.isnan(target_weights).any() or np.isinf(target_weights).any():
            safe_weights = np.zeros_like(target_weights)
            safe_weights[0] = 1.0  # 100% Cash liquidation
            return safe_weights

        w = target_weights.copy()
        N_plus_1 = len(w)

        # 2. Enforce non-negativity
        w = np.maximum(w, 0.0)

        # 3. Enforce single-asset concentration cap on risky assets
        for i in range(1, N_plus_1):
            w[i] = min(w[i], self.max_asset_pct)

        # 4. Enforce minimum cash reserve
        risky_sum = np.sum(w[1:])
        max_risky = 1.0 - self.min_cash_pct

        if risky_sum > max_risky:
            # Scale down risky assets proportionally
            scale = max_risky / risky_sum
            w[1:] *= scale

        # Cash absorbs the residual to ensure exact sum = 1.0
        w[0] = 1.0 - np.sum(w[1:])
        w[0] = max(w[0], self.min_cash_pct)

        # Final normalization to ensure sum == 1.000000
        w /= np.sum(w)

        # 5. Slew rate turnover clamping (if previous weight provided)
        if current_weights is not None:
            turnover = np.sum(np.abs(w - current_weights))
            if turnover > self.max_turnover_step:
                ratio = self.max_turnover_step / turnover
                w = current_weights + (w - current_weights) * ratio
                w /= np.sum(w)

        return w

    def enforce_torch(
        self,
        target_weights: torch.Tensor,
    ) -> torch.Tensor:
        """
        Differentiable / tensor version for batch tensors (B, N + 1).
        """
        B, N_plus_1 = target_weights.shape
        device = target_weights.device

        # Clamp risky assets
        risky = target_weights[:, 1:]
        risky_clamped = torch.clamp(risky, min=0.0, max=self.max_asset_pct)

        risky_sum = torch.sum(risky_clamped, dim=-1, keepdim=True)
        max_risky = 1.0 - self.min_cash_pct

        scale = torch.where(
            risky_sum > max_risky,
            max_risky / torch.clamp(risky_sum, min=1e-8),
            torch.ones_like(risky_sum),
        )
        risky_scaled = risky_clamped * scale

        cash = 1.0 - torch.sum(risky_scaled, dim=-1, keepdim=True)
        cash = torch.clamp(cash, min=self.min_cash_pct)

        projected = torch.cat([cash, risky_scaled], dim=-1)
        projected = projected / torch.sum(projected, dim=-1, keepdim=True)
        return projected
