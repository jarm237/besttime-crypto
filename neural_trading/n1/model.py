"""
neural_trading/n1/model.py

Phase E: Compact Unified Neural Architecture for N1 (`CrossSectionalMarketPolicy`).
Designed around the structure of H1 (cross-sectional Spot market structure,
aggressor imbalance, range/volatility, variable active asset set U_t) and H2
(order-book depth asymmetry and near-touch liquidity thinning).

Key properties:
  1. Masked Cross-Asset Self-Attention over active eligible assets U_t.
  2. Explicit Market-Regime & Liquidity Context conditioning for Cash allocation.
  3. Portfolio-state awareness (takes current drifted weights w_curr).
  4. Exact train/eval parity for HOLD decisions via a deadband threshold on
     one-way risky turnover, with external hard-risk constraints enforced
     outside the model.
"""
from __future__ import annotations

from typing import Tuple
import torch
import torch.nn as nn
import torch.nn.functional as F


class CrossSectionalMarketPolicy(nn.Module):
    def __init__(
        self,
        asset_feat_dim: int = 10,
        market_feat_dim: int = 8,
        embed_dim: int = 24,
        num_heads: int = 4,
        deadband_oneway: float = 0.06,
    ):
        super().__init__()
        self.embed_dim = embed_dim
        self.deadband_oneway = deadband_oneway

        # Per-asset encoder: [asset_features (d_a), current_weight (1), weight_dev (1)]
        self.asset_proj = nn.Sequential(
            nn.Linear(asset_feat_dim + 2, embed_dim),
            nn.LayerNorm(embed_dim),
            nn.GELU(),
        )
        # Cross-asset self-attention over active universe U_t
        self.cross_attn = nn.MultiheadAttention(
            embed_dim=embed_dim,
            num_heads=num_heads,
            dropout=0.10,
            batch_first=True,
        )
        self.attn_norm = nn.LayerNorm(embed_dim)

        # Market & order-book liquidity context encoder: [market_features (d_m), current_cash (1)]
        self.mkt_proj = nn.Sequential(
            nn.Linear(market_feat_dim + 1, embed_dim),
            nn.LayerNorm(embed_dim),
            nn.GELU(),
        )

        # Asset score head: combines attended asset token + global market context
        self.asset_score_head = nn.Sequential(
            nn.Linear(embed_dim * 2, embed_dim),
            nn.GELU(),
            nn.Linear(embed_dim, 1),
        )

        # Cash allocation score head: predicts defensive cash logit from market + pooled cross-section
        self.cash_score_head = nn.Sequential(
            nn.Linear(embed_dim * 2, embed_dim),
            nn.GELU(),
            nn.Linear(embed_dim, 1),
        )

        # Inertia / step-size gate in [0, 1]: how strongly to move from w_curr toward w_cand
        self.step_gate_head = nn.Sequential(
            nn.Linear(embed_dim * 2, embed_dim // 2),
            nn.GELU(),
            nn.Linear(embed_dim // 2, 1),
        )

    def forward(
        self,
        asset_x: torch.Tensor,       # (B, N, d_a)
        market_x: torch.Tensor,      # (B, d_m)
        active_mask: torch.Tensor,   # (B, N) boolean, True if asset is tradable at t
        w_curr: torch.Tensor,        # (B, N + 1) current drifted weights [cash, asset_1..N]
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Returns:
            w_eff: (B, N + 1) post-inertia simplex weights (0 on inactive assets)
            w_cand: (B, N + 1) unconstrained candidate simplex weights
            step_gate: (B, 1) blending coefficient in [0, 1]
        """
        B, N, _ = asset_x.shape
        w_curr_assets = w_curr[:, 1:]  # (B, N)
        n_active = active_mask.float().sum(dim=-1, keepdim=True).clamp(min=1.0)
        mean_eq_w = (1.0 - w_curr[:, :1]) / n_active
        w_dev = (w_curr_assets - mean_eq_w) * active_mask.float()

        a_in = torch.cat([asset_x, w_curr_assets.unsqueeze(-1), w_dev.unsqueeze(-1)], dim=-1)
        a_tok = self.asset_proj(a_in)  # (B, N, E)

        # Key padding mask for MultiheadAttention: True means IGNORE (inactive)
        key_padding_mask = ~active_mask
        # Guard against all-False row
        all_inactive = key_padding_mask.all(dim=-1)
        if all_inactive.any():
            key_padding_mask = key_padding_mask.clone()
            key_padding_mask[all_inactive, 0] = False

        attn_out, _ = self.cross_attn(a_tok, a_tok, a_tok, key_padding_mask=key_padding_mask, need_weights=False)
        a_enc = self.attn_norm(a_tok + attn_out)  # (B, N, E)

        # Masked mean pooling over active assets
        mask_f = active_mask.float().unsqueeze(-1)  # (B, N, 1)
        pooled_assets = (a_enc * mask_f).sum(dim=1) / mask_f.sum(dim=1).clamp(min=1.0)  # (B, E)

        m_in = torch.cat([market_x, w_curr[:, :1]], dim=-1)
        m_enc = self.mkt_proj(m_in)  # (B, E)

        m_exp = m_enc.unsqueeze(1).expand(-1, N, -1)
        asset_logits = self.asset_score_head(torch.cat([a_enc, m_exp], dim=-1)).squeeze(-1)  # (B, N)
        # Mask out inactive assets with large negative logit so softmax weight = 0
        asset_logits = asset_logits.masked_fill(~active_mask, -1e9)

        global_ctx = torch.cat([pooled_assets, m_enc], dim=-1)  # (B, 2E)
        cash_logit = self.cash_score_head(global_ctx)  # (B, 1)

        all_logits = torch.cat([cash_logit, asset_logits], dim=-1)  # (B, N + 1)
        w_cand = F.softmax(all_logits, dim=-1)

        # Re-project w_curr onto currently active set (if an asset just delisted, move its weight to cash)
        inactive_weight = (w_curr[:, 1:] * (~active_mask).float()).sum(dim=-1, keepdim=True)
        w_curr_valid = torch.cat([
            w_curr[:, :1] + inactive_weight,
            w_curr[:, 1:] * active_mask.float(),
        ], dim=-1)
        w_curr_valid = w_curr_valid / w_curr_valid.sum(dim=-1, keepdim=True).clamp(min=1e-8)

        step_gate = torch.sigmoid(self.step_gate_head(global_ctx))  # (B, 1)
        w_blend = (1.0 - step_gate) * w_curr_valid + step_gate * w_cand

        # Differentiable deadband shrinkage (straight-through hard deadband for exact parity)
        oneway_to = 0.5 * torch.sum(torch.abs(w_blend[:, 1:] - w_curr_valid[:, 1:]), dim=-1, keepdim=True)
        do_trade_hard = (oneway_to >= self.deadband_oneway).float()
        do_trade_soft = torch.sigmoid((oneway_to - self.deadband_oneway) * 50.0)
        do_trade = do_trade_hard.detach() - do_trade_soft.detach() + do_trade_soft

        w_eff = (1.0 - do_trade) * w_curr_valid + do_trade * w_blend
        return w_eff, w_cand, step_gate
