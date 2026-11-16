"""Unified Neural Trading Policy Pilot (Phase R5).

A lightweight, causally verified neural capital allocation policy built from first principles.

Key Architectural Guarantees:
  - Single unified policy: outputs a joint allocation vector [w_1, ..., w_N, w_cash] in [0, 1]^(N+1).
  - Exact capital conservation: sum(w_assets) + w_cash == 1.0, long-only spot, allows up to 100% cash.
  - Shared multi-asset temporal feature encoder + permutation-invariant market context.
  - Cost-aware training objective: directly optimizes net return after fees, penalizes downside risk (semi-deviation), and penalizes turnover.
  - Strict walk-forward integrity: preprocessing parameters (mean, std) learned exclusively on Train (2022-2023).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim

logger = logging.getLogger("unified_neural_pilot")


class UnifiedNeuralPolicy(nn.Module):
    """Small, inspectable neural policy mapping multi-asset features to capital allocation weights."""

    def __init__(
        self,
        num_assets: int = 8,
        in_features: int = 8,
        hidden_dim: int = 32,
    ) -> None:
        super().__init__()
        self.num_assets = num_assets
        self.in_features = in_features
        self.hidden_dim = hidden_dim

        # 1. Shared Per-Asset Temporal/Feature Encoder
        self.asset_encoder = nn.Sequential(
            nn.Linear(in_features, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Tanh(),
        )

        # 2. Cross-Asset Context & Asset Head
        self.asset_head = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, 1),
        )

        # 3. Dedicated Cash Allocation Head
        self.cash_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.Tanh(),
            nn.Linear(hidden_dim // 2, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        Args:
            x: Input tensor of shape [batch_size, num_assets, in_features]

        Returns:
            weights: Normalized weights [batch_size, num_assets + 1],
                     where weights[:, :N] are asset weights and weights[:, -1] is cash weight.
        """
        B, N, F = x.shape
        # Encode each asset
        h = self.asset_encoder(x)  # [B, N, hidden_dim]

        # Market-wide context via permutation-invariant pooling
        m = h.mean(dim=1, keepdim=True)  # [B, 1, hidden_dim]
        m_expanded = m.expand(-1, N, -1)  # [B, N, hidden_dim]

        # Combine asset features with market context
        combined = torch.cat([h, m_expanded], dim=-1)  # [B, N, 2*hidden_dim]
        asset_logits = self.asset_head(combined).squeeze(-1)  # [B, N]

        # Dedicated cash logit driven by market context
        cash_logit = self.cash_head(m.squeeze(1))  # [B, 1]

        # Joint allocation over [w_1, ..., w_N, w_cash]
        joint_logits = torch.cat([asset_logits, cash_logit], dim=-1)  # [B, N+1]
        weights = torch.softmax(joint_logits, dim=-1)  # [B, N+1]

        return weights


@dataclass
class DatasetSplits:
    train_x: torch.Tensor
    train_returns: torch.Tensor
    val_x: torch.Tensor
    val_returns: torch.Tensor
    holdout_x: torch.Tensor
    holdout_returns: torch.Tensor
    feature_names: List[str]
    symbols: List[str]
    train_dates: List[pd.Timestamp]
    val_dates: List[pd.Timestamp]
    holdout_dates: List[pd.Timestamp]
    norm_mean: np.ndarray
    norm_std: np.ndarray


def extract_point_in_time_features(
    piv_close: pd.DataFrame,
    piv_open: pd.DataFrame,
    include_regime: bool = False,
    causal_delay_bars: int = 2,
    rebalance_interval_hours: int = 168,
    btc_symbol: str = "BTCUSDT",
) -> Tuple[np.ndarray, np.ndarray, List[pd.Timestamp], List[str]]:
    """Extract causal multi-asset features and forward 168h holding returns at Sunday 00:00 UTC decisions.

    Features per asset (market-only, 8 features):
      1. ret_24h: 24h causal return
      2. ret_72h: 72h causal return
      3. ret_168h: 168h causal return (1-week momentum)
      4. vol_24h: 24h annualized realized hourly volatility
      5. vol_168h: 168h annualized realized hourly volatility
      6. rel_mom_zscore: Cross-sectional z-score of 168h momentum
      7. btc_rel_mom: Relative momentum vs BTC (ret_168h_asset - ret_168h_btc)
      8. market_breadth: Fraction of universe with positive 168h momentum

    Optional regime features (2 features):
      9. btc_dist_sma168: Distance of BTC close to 168h SMA
      10. btc_vol_168h: BTC 168h annualized realized volatility

    Returns:
        X: Feature tensor [W, N, F]
        Y: Forward returns [W, N] from open[t] to close[t+rebalance_interval_hours]
        decision_timestamps: List of Sunday 00:00 UTC timestamps
        feature_names: List of feature names
    """
    symbols = list(piv_close.columns)
    N = len(symbols)
    btc_idx = symbols.index(btc_symbol)

    timestamps = piv_close.index
    T = len(timestamps)

    # Hourly returns
    hourly_rets = piv_close.pct_change()

    # Find Sunday 00:00:00 UTC decision indices with sufficient warmup (>= 170 bars)
    min_warmup = rebalance_interval_hours + causal_delay_bars + 24
    decision_indices: List[int] = []

    for t in range(min_warmup, T - rebalance_interval_hours):
        ts = timestamps[t]
        if ts.weekday() == 6 and ts.hour == 0:
            decision_indices.append(t)

    W = len(decision_indices)
    feature_names = [
        "ret_24h",
        "ret_72h",
        "ret_168h",
        "vol_24h",
        "vol_168h",
        "rel_mom_zscore",
        "btc_rel_mom",
        "market_breadth",
    ]
    if include_regime:
        feature_names.extend(["btc_dist_sma168", "btc_vol_168h"])

    F = len(feature_names)
    X = np.zeros((W, N, F), dtype=np.float32)
    Y = np.zeros((W, N), dtype=np.float32)
    decision_timestamps: List[pd.Timestamp] = []

    for w, t in enumerate(decision_indices):
        ts = timestamps[t]
        decision_timestamps.append(ts)
        t_eval = t - causal_delay_bars

        # Realized forward return from open[t] to close[t + 168]
        p_open_t = piv_open.iloc[t].to_numpy()
        p_close_fwd = piv_close.iloc[t + rebalance_interval_hours].to_numpy()
        Y[w] = (p_close_fwd / p_open_t) - 1.0

        # Causal historical price windows up to t_eval
        close_eval = piv_close.iloc[t_eval].to_numpy()
        close_24 = piv_close.iloc[t_eval - 24].to_numpy()
        close_72 = piv_close.iloc[t_eval - 72].to_numpy()
        close_168 = piv_close.iloc[t_eval - 168].to_numpy()

        r24 = (close_eval / close_24) - 1.0
        r72 = (close_eval / close_72) - 1.0
        r168 = (close_eval / close_168) - 1.0

        sub_rets_24 = hourly_rets.iloc[t_eval - 24 : t_eval]
        vol24 = (sub_rets_24.std().to_numpy() * np.sqrt(8760.0))

        sub_rets_168 = hourly_rets.iloc[t_eval - 168 : t_eval]
        vol168 = (sub_rets_168.std().to_numpy() * np.sqrt(8760.0))

        mean_168 = float(np.mean(r168))
        std_168 = float(np.std(r168))
        z_168 = (r168 - mean_168) / max(std_168, 1e-6)

        btc_r168 = r168[btc_idx]
        btc_rel_mom = r168 - btc_r168

        breadth = float(np.mean(r168 > 0.0))

        for i in range(N):
            feat_vec = [
                r24[i],
                r72[i],
                r168[i],
                vol24[i],
                vol168[i],
                z_168[i],
                btc_rel_mom[i],
                breadth,
            ]
            if include_regime:
                btc_sma168 = float(piv_close[btc_symbol].iloc[t_eval - 168 : t_eval].mean())
                btc_dist_sma = (close_eval[btc_idx] / btc_sma168) - 1.0
                btc_v168 = vol168[btc_idx]
                feat_vec.extend([btc_dist_sma, btc_v168])

            X[w, i] = np.array(feat_vec, dtype=np.float32)

    return X, Y, decision_timestamps, feature_names


def prepare_dataset_splits(
    X: np.ndarray,
    Y: np.ndarray,
    dates: List[pd.Timestamp],
    symbols: List[str],
    feature_names: List[str],
    train_end: pd.Timestamp = pd.Timestamp("2023-12-31 23:00:00+00:00"),
    val_end: pd.Timestamp = pd.Timestamp("2024-12-31 23:00:00+00:00"),
) -> DatasetSplits:
    """Chronologically split features and compute preprocessing strictly on Train split."""
    dates_arr = np.array(dates)

    train_mask = dates_arr <= train_end
    val_mask = (dates_arr > train_end) & (dates_arr <= val_end)
    holdout_mask = dates_arr > val_end

    train_x_raw = X[train_mask]
    val_x_raw = X[val_mask]
    holdout_x_raw = X[holdout_mask]

    # Compute mean and std strictly on train split across [W_train * N, F]
    train_flat = train_x_raw.reshape(-1, train_x_raw.shape[-1])
    mean_f = np.nanmean(train_flat, axis=0)
    std_f = np.nanstd(train_flat, axis=0)
    std_f[std_f < 1e-6] = 1.0

    # Standardize all splits using train parameters
    train_x = (train_x_raw - mean_f) / std_f
    val_x = (val_x_raw - mean_f) / std_f
    holdout_x = (holdout_x_raw - mean_f) / std_f

    # Replace any NaNs
    train_x = np.nan_to_num(train_x, nan=0.0)
    val_x = np.nan_to_num(val_x, nan=0.0)
    holdout_x = np.nan_to_num(holdout_x, nan=0.0)

    return DatasetSplits(
        train_x=torch.tensor(train_x, dtype=torch.float32),
        train_returns=torch.tensor(Y[train_mask], dtype=torch.float32),
        val_x=torch.tensor(val_x, dtype=torch.float32),
        val_returns=torch.tensor(Y[val_mask], dtype=torch.float32),
        holdout_x=torch.tensor(holdout_x, dtype=torch.float32),
        holdout_returns=torch.tensor(Y[holdout_mask], dtype=torch.float32),
        feature_names=feature_names,
        symbols=symbols,
        train_dates=list(dates_arr[train_mask]),
        val_dates=list(dates_arr[val_mask]),
        holdout_dates=list(dates_arr[holdout_mask]),
        norm_mean=mean_f,
        norm_std=std_f,
    )


def compute_cost_aware_loss(
    weights: torch.Tensor,
    forward_returns: torch.Tensor,
    fee_bps: float = 12.0,
    lambda_downside: float = 1.0,
    lambda_turnover: float = 0.002,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Calculate cost-aware portfolio objective.

    Loss = - mean(net_returns) + lambda_downside * sqrt(mean(min(0, net_returns)^2)) + lambda_turnover * turnover

    Args:
        weights: [W, N+1] portfolio weights (first N are assets, last is cash)
        forward_returns: [W, N] forward asset returns over 168h holding period
    """
    fee_rate = fee_bps / 10000.0
    W, N = forward_returns.shape

    asset_w = weights[:, :N]  # [W, N]
    # Weekly asset return contribution (cash return is 0)
    gross_period_returns = torch.sum(asset_w * forward_returns, dim=-1)  # [W]

    # Turnover penalty between consecutive weeks
    w_prev = torch.cat([torch.zeros(1, N, device=weights.device), asset_w[:-1]], dim=0)
    turnover = torch.sum(torch.abs(asset_w - w_prev), dim=-1)  # [W]
    turnover[0] = torch.sum(asset_w[0])  # Inception turnover

    # Net returns after fee drag
    net_period_returns = gross_period_returns - (turnover * fee_rate)

    # Downside semi-deviation below 0
    neg_returns = torch.minimum(net_period_returns, torch.zeros_like(net_period_returns))
    downside_dev = torch.sqrt(torch.mean(neg_returns**2) + 1e-8)

    mean_net_return = torch.mean(net_period_returns)
    mean_turnover = torch.mean(turnover)

    loss = -mean_net_return + (lambda_downside * downside_dev) + (lambda_turnover * mean_turnover)

    return loss, mean_net_return, downside_dev, mean_turnover


def train_unified_neural_pilot(
    splits: DatasetSplits,
    hidden_dim: int = 32,
    lr: float = 1e-3,
    epochs: int = 40,
    seed: int = 42,
    fee_bps: float = 12.0,
    lambda_downside: float = 1.0,
    lambda_turnover: float = 0.002,
) -> Tuple[UnifiedNeuralPolicy, Dict[str, List[float]]]:
    """Train a unified neural policy with cost-aware loss and validation selection."""
    torch.manual_seed(seed)
    np.random.seed(seed)

    num_assets = len(splits.symbols)
    in_features = splits.train_x.shape[-1]

    model = UnifiedNeuralPolicy(num_assets=num_assets, in_features=in_features, hidden_dim=hidden_dim)
    optimizer = optim.Adam(model.parameters(), lr=lr)

    history = {
        "train_loss": [],
        "val_loss": [],
        "train_net_ret": [],
        "val_net_ret": [],
    }

    best_val_loss = float("inf")
    best_weights = None

    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()

        # Full sequence forward pass
        train_w = model(splits.train_x)
        loss, train_ret, train_dd, train_to = compute_cost_aware_loss(
            weights=train_w,
            forward_returns=splits.train_returns,
            fee_bps=fee_bps,
            lambda_downside=lambda_downside,
            lambda_turnover=lambda_turnover,
        )

        loss.backward()
        optimizer.step()

        # Validation evaluation
        model.eval()
        with torch.no_grad():
            val_w = model(splits.val_x)
            val_loss, val_ret, val_dd, val_to = compute_cost_aware_loss(
                weights=val_w,
                forward_returns=splits.val_returns,
                fee_bps=fee_bps,
                lambda_downside=lambda_downside,
                lambda_turnover=lambda_turnover,
            )

        history["train_loss"].append(float(loss.item()))
        history["val_loss"].append(float(val_loss.item()))
        history["train_net_ret"].append(float(train_ret.item()))
        history["val_net_ret"].append(float(val_ret.item()))

        if float(val_loss.item()) < best_val_loss:
            best_val_loss = float(val_loss.item())
            best_weights = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    # Load best checkpoint
    if best_weights is not None:
        model.load_state_dict(best_weights)

    return model, history
