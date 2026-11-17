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
        allow_cash: bool = True,
    ) -> None:
        super().__init__()
        self.num_assets = num_assets
        self.in_features = in_features
        self.hidden_dim = hidden_dim
        self.allow_cash = allow_cash

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

        # 3. Dedicated Cash Allocation Head (optional)
        if allow_cash:
            self.cash_head = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim // 2),
                nn.Tanh(),
                nn.Linear(hidden_dim // 2, 1),
            )
        else:
            self.cash_head = None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        Args:
            x: Input tensor of shape [batch_size, num_assets, in_features]

        Returns:
            weights: If allow_cash=True: [batch_size, num_assets + 1],
                     where weights[:, :N] are asset weights and weights[:, -1] is cash weight.
                     If allow_cash=False: [batch_size, num_assets] fully-invested risky sleeve weights.
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

        if self.allow_cash and self.cash_head is not None:
            cash_logit = self.cash_head(m.squeeze(1))  # [B, 1]
            joint_logits = torch.cat([asset_logits, cash_logit], dim=-1)  # [B, N+1]
            weights = torch.softmax(joint_logits, dim=-1)  # [B, N+1]
        else:
            weights = torch.softmax(asset_logits, dim=-1)  # [B, N]

        return weights


@dataclass
class SampleMetadata:
    """Detailed temporal and split metadata for each weekly portfolio decision."""
    decision_index: int
    decision_time: pd.Timestamp
    feature_cutoff_time: pd.Timestamp
    execution_time: pd.Timestamp
    label_end_time: pd.Timestamp
    split: str = "unassigned"  # "train", "val", "holdout", "purged"
    is_purged: bool = False
    purge_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_index": self.decision_index,
            "decision_time": self.decision_time.isoformat(),
            "feature_cutoff_time": self.feature_cutoff_time.isoformat(),
            "execution_time": self.execution_time.isoformat(),
            "label_end_time": self.label_end_time.isoformat(),
            "split": self.split,
            "is_purged": self.is_purged,
            "purge_reason": self.purge_reason,
        }


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
    all_metadata: List[SampleMetadata]
    purged_metadata: List[SampleMetadata]
    all_x_unnormalized: np.ndarray
    all_y: np.ndarray
    all_dates: List[pd.Timestamp]
    all_x_normalized: torch.Tensor


def extract_point_in_time_features(
    piv_close: pd.DataFrame,
    piv_open: pd.DataFrame,
    include_regime: bool = False,
    causal_delay_bars: int = 2,
    rebalance_interval_hours: int = 168,
    btc_symbol: str = "BTCUSDT",
) -> Tuple[np.ndarray, np.ndarray, List[pd.Timestamp], List[str], List[SampleMetadata]]:
    """Extract causal multi-asset features and forward holding returns at Sunday 00:00 UTC decisions.

    Temporal and Economic Fidelity Guarantees:
      - decision_time: Sunday 00:00:00 UTC.
      - feature_cutoff_time: decision_time - causal_delay_bars (Saturday 22:00:00 UTC).
      - execution_time: decision_time (Sunday 00:00:00 UTC, executed at next-bar open).
      - label_end_time: decision_time + rebalance_interval_hours (next Sunday 00:00:00 UTC).
      - Forward return matches holding period: open[t + 168] / open[t] - 1.0 (exact execution parity).
      - Feature lookbacks use calendar Timedelta, preserving exact calendar distance across market-wide gaps.

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
        Y: Forward returns [W, N] from open[t] to open[t+rebalance_interval_hours]
        decision_timestamps: List of Sunday 00:00 UTC timestamps
        feature_names: List of feature names
        sample_metadata: Detailed metadata list per decision sample
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

    for t in range(min_warmup, T):
        ts = timestamps[t]
        if ts.weekday() == 6 and ts.hour == 0:
            ts_next = ts + pd.Timedelta(hours=rebalance_interval_hours)
            # Require at least one bar available for next execution
            if ts_next in piv_open.index or (t + rebalance_interval_hours < T):
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
    sample_metadata: List[SampleMetadata] = []

    for w, t in enumerate(decision_indices):
        ts = timestamps[t]
        decision_timestamps.append(ts)

        t_decision = ts
        t_cutoff = ts - pd.Timedelta(hours=causal_delay_bars)
        t_execution = ts
        t_label_end = ts + pd.Timedelta(hours=rebalance_interval_hours)

        # Realized forward holding return: execution open[t] to next execution open[t + 168h]
        p_open_t = piv_open.loc[ts].to_numpy()
        if t_label_end in piv_open.index:
            p_open_fwd = piv_open.loc[t_label_end].to_numpy()
        else:
            p_open_fwd = piv_open.asof(t_label_end).to_numpy()

        Y[w] = (p_open_fwd / p_open_t) - 1.0

        # Calendar-verified lookbacks up to t_cutoff
        ts_24 = t_cutoff - pd.Timedelta(hours=24)
        ts_72 = t_cutoff - pd.Timedelta(hours=72)
        ts_168 = t_cutoff - pd.Timedelta(hours=168)

        close_cutoff = piv_close.asof(t_cutoff).to_numpy()
        close_24 = piv_close.asof(ts_24).to_numpy()
        close_72 = piv_close.asof(ts_72).to_numpy()
        close_168 = piv_close.asof(ts_168).to_numpy()

        r24 = (close_cutoff / close_24) - 1.0
        r72 = (close_cutoff / close_72) - 1.0
        r168 = (close_cutoff / close_168) - 1.0

        sub_rets_24 = hourly_rets.loc[(hourly_rets.index > ts_24) & (hourly_rets.index <= t_cutoff)]
        vol24 = (sub_rets_24.std().to_numpy() * np.sqrt(8760.0))

        sub_rets_168 = hourly_rets.loc[(hourly_rets.index > ts_168) & (hourly_rets.index <= t_cutoff)]
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
                btc_sma168 = float(piv_close[btc_symbol].loc[(piv_close.index > ts_168) & (piv_close.index <= t_cutoff)].mean())
                btc_dist_sma = (close_cutoff[btc_idx] / btc_sma168) - 1.0
                btc_v168 = vol168[btc_idx]
                feat_vec.extend([btc_dist_sma, btc_v168])

            X[w, i] = np.array(feat_vec, dtype=np.float32)

        sample_metadata.append(
            SampleMetadata(
                decision_index=w,
                decision_time=t_decision,
                feature_cutoff_time=t_cutoff,
                execution_time=t_execution,
                label_end_time=t_label_end,
            )
        )

    return X, Y, decision_timestamps, feature_names, sample_metadata


def prepare_dataset_splits(
    X: np.ndarray,
    Y: np.ndarray,
    dates: List[pd.Timestamp],
    symbols: List[str],
    feature_names: List[str],
    sample_metadata: Optional[List[SampleMetadata]] = None,
    train_end: pd.Timestamp = pd.Timestamp("2023-12-31 23:59:59+00:00"),
    val_end: pd.Timestamp = pd.Timestamp("2024-12-31 23:59:59+00:00"),
) -> DatasetSplits:
    """Chronologically split features with strict zero-leakage purge and embargo.

    Purge/Embargo Guarantees:
      - Any sample where label_end_time > train_end is purged from Train to prevent leakage into Validation.
      - Any sample where label_end_time > val_end is purged from Validation to prevent leakage into Holdout.
      - Normalization parameters (mean, std) are computed exclusively on the unpurged Train split.
    """
    W, N, F = X.shape

    if sample_metadata is None:
        sample_metadata = [
            SampleMetadata(
                decision_index=w,
                decision_time=dates[w],
                feature_cutoff_time=dates[w] - pd.Timedelta(hours=2),
                execution_time=dates[w],
                label_end_time=dates[w] + pd.Timedelta(hours=168),
            )
            for w in range(W)
        ]

    train_mask = np.zeros(W, dtype=bool)
    val_mask = np.zeros(W, dtype=bool)
    holdout_mask = np.zeros(W, dtype=bool)
    purged_metadata: List[SampleMetadata] = []

    for w in range(W):
        meta = sample_metadata[w]
        d_time = meta.decision_time
        l_end = meta.label_end_time

        if d_time <= train_end:
            if l_end <= train_end:
                train_mask[w] = True
                meta.split = "train"
                meta.is_purged = False
            else:
                meta.split = "purged"
                meta.is_purged = True
                meta.purge_reason = (
                    f"Train label overflow: label_end ({l_end}) > train_end ({train_end})"
                )
                purged_metadata.append(meta)
                logger.info("Purged Train boundary sample %d at %s: %s", w, d_time, meta.purge_reason)
        elif d_time <= val_end:
            if l_end <= val_end:
                val_mask[w] = True
                meta.split = "val"
                meta.is_purged = False
            else:
                meta.split = "purged"
                meta.is_purged = True
                meta.purge_reason = (
                    f"Validation label overflow: label_end ({l_end}) > val_end ({val_end})"
                )
                purged_metadata.append(meta)
                logger.info("Purged Validation boundary sample %d at %s: %s", w, d_time, meta.purge_reason)
        else:
            holdout_mask[w] = True
            meta.split = "holdout"
            meta.is_purged = False

    # Compute mean and std strictly on unpurged train split across [W_train * N, F]
    train_x_raw = X[train_mask]
    train_flat = train_x_raw.reshape(-1, F)
    mean_f = np.nanmean(train_flat, axis=0)
    std_f = np.nanstd(train_flat, axis=0)
    std_f[std_f < 1e-6] = 1.0

    # Standardize splits using train parameters
    train_x = np.nan_to_num((X[train_mask] - mean_f) / std_f, nan=0.0)
    val_x = np.nan_to_num((X[val_mask] - mean_f) / std_f, nan=0.0)
    holdout_x = np.nan_to_num((X[holdout_mask] - mean_f) / std_f, nan=0.0)
    all_x_norm = np.nan_to_num((X - mean_f) / std_f, nan=0.0)

    dates_arr = np.array(dates)

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
        all_metadata=sample_metadata,
        purged_metadata=purged_metadata,
        all_x_unnormalized=X,
        all_y=Y,
        all_dates=dates,
        all_x_normalized=torch.tensor(all_x_norm, dtype=torch.float32),
    )


def compute_cost_aware_loss(
    weights: torch.Tensor,
    forward_returns: torch.Tensor,
    fee_bps: float = 12.0,
    lambda_downside: float = 1.0,
    lambda_turnover: float = 0.002,
    use_drift: bool = True,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Calculate cost-aware portfolio objective with exact pre-trade drift accounting.

    Loss = - mean(net_returns) + lambda_downside * sqrt(mean(min(0, net_returns)^2)) + lambda_turnover * mean(turnover)

    Accounting Fidelity:
      - When use_drift=True: computes exact pre-trade drifted weight turnover between consecutive rebalances:
          w_drift,i = w_i * (1 + r_i) / (1 + R_port)
          turnover_t = 0.5 * (sum |w_i,t - w_drift,i,t-1| + |w_cash,t - w_drift,cash,t-1|)
      - When use_drift=False: computes surrogate turnover 0.5 * sum |w_t - w_{t-1}|.

    Args:
        weights: [W, N+1] portfolio weights (first N are assets, last is cash)
        forward_returns: [W, N] forward asset returns over holding period
        fee_bps: Transaction fee in basis points
        lambda_downside: Weight for downside semi-deviation penalty
        lambda_turnover: Weight for turnover penalty
        use_drift: Whether to account for pre-trade holding drift
    """
    fee_rate = fee_bps / 10000.0
    W, N = forward_returns.shape

    asset_w = weights[:, :N]  # [W, N]
    cash_w = weights[:, -1:]  # [W, 1]

    # Gross period return: sum(w_i * r_i) (cash return is 0)
    gross_period_returns = torch.sum(asset_w * forward_returns, dim=-1)  # [W]

    if use_drift and W > 1:
        # Pre-trade drifted weights at end of period t (before rebalance t+1):
        # portfolio gross growth factor = 1 + gross_period_returns
        denom = torch.clamp(1.0 + gross_period_returns[:-1, None], min=1e-4)  # [W-1, 1]
        drifted_asset_w = (asset_w[:-1] * (1.0 + forward_returns[:-1])) / denom  # [W-1, N]
        drifted_cash_w = cash_w[:-1] / denom  # [W-1, 1]

        # Turnover at rebalances 1..W-1:
        delta_assets = torch.sum(torch.abs(asset_w[1:] - drifted_asset_w), dim=-1)  # [W-1]
        delta_cash = torch.abs(cash_w[1:, 0] - drifted_cash_w[:, 0])  # [W-1]
        turnover_steps = 0.5 * (delta_assets + delta_cash)  # [W-1]

        # Inception turnover at step 0 (from 100% cash to target weights):
        delta_assets_0 = torch.sum(asset_w[0])
        delta_cash_0 = torch.abs(cash_w[0, 0] - 1.0)
        turnover_0 = 0.5 * (delta_assets_0 + delta_cash_0)

        turnover = torch.cat([turnover_0.unsqueeze(0), turnover_steps], dim=0)  # [W]
    else:
        # Surrogate turnover without drift
        w_all = weights  # [W, N+1]
        w_prev = torch.cat(
            [
                torch.cat(
                    [
                        torch.zeros(1, N, device=weights.device),
                        torch.ones(1, 1, device=weights.device),
                    ],
                    dim=-1,
                ),
                w_all[:-1],
            ],
            dim=0,
        )
        turnover = 0.5 * torch.sum(torch.abs(w_all - w_prev), dim=-1)

    net_period_returns = gross_period_returns - (turnover * fee_rate)

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
    epochs: int = 50,
    seed: int = 42,
    fee_bps: float = 12.0,
    lambda_downside: float = 1.0,
    lambda_turnover: float = 0.002,
    use_drift: bool = True,
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
            use_drift=use_drift,
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
                use_drift=use_drift,
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


def train_shuffled_control(
    splits: DatasetSplits,
    hidden_dim: int = 32,
    lr: float = 1e-3,
    epochs: int = 50,
    seed: int = 42,
    fee_bps: float = 12.0,
    lambda_downside: float = 1.0,
    lambda_turnover: float = 0.002,
    use_drift: bool = True,
) -> Tuple[UnifiedNeuralPolicy, Dict[str, List[float]]]:
    """Train neural policy on permuted features within Train split (falsification control).

    Permutes asset features cross-sectionally at each weekly step on Train only,
    destroying the predictive connection between features and future returns while preserving
    exact feature marginal distributions. Validation and Holdout remain untouched.
    """
    torch.manual_seed(seed)
    np.random.seed(seed)

    train_x_shuffled = splits.train_x.clone()
    W, N, F = train_x_shuffled.shape
    for w in range(W):
        perm = torch.randperm(N)
        train_x_shuffled[w] = train_x_shuffled[w, perm]

    shuffled_splits = DatasetSplits(
        train_x=train_x_shuffled,
        train_returns=splits.train_returns,
        val_x=splits.val_x,
        val_returns=splits.val_returns,
        holdout_x=splits.holdout_x,
        holdout_returns=splits.holdout_returns,
        feature_names=splits.feature_names,
        symbols=splits.symbols,
        train_dates=splits.train_dates,
        val_dates=splits.val_dates,
        holdout_dates=splits.holdout_dates,
        norm_mean=splits.norm_mean,
        norm_std=splits.norm_std,
        all_metadata=splits.all_metadata,
        purged_metadata=splits.purged_metadata,
        all_x_unnormalized=splits.all_x_unnormalized,
        all_y=splits.all_y,
        all_dates=splits.all_dates,
        all_x_normalized=splits.all_x_normalized,
    )

    return train_unified_neural_pilot(
        shuffled_splits,
        hidden_dim=hidden_dim,
        lr=lr,
        epochs=epochs,
        seed=seed,
        fee_bps=fee_bps,
        lambda_downside=lambda_downside,
        lambda_turnover=lambda_turnover,
        use_drift=use_drift,
    )


def compute_cross_sectional_loss(
    weights: torch.Tensor,
    forward_returns: torch.Tensor,
    benchmark_returns: Optional[torch.Tensor] = None,
    fee_bps: float = 12.0,
    lambda_turnover: float = 0.002,
    lambda_risk: float = 0.5,
    use_drift: bool = True,
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Calculate cross-sectional relative performance objective for fully-invested risky sleeve.

    Objective:
      Maximize net excess return over benchmark after transaction costs,
      penalize downside relative underperformance (semi-deviation below benchmark),
      and penalize turnover.

    Loss = - mean(net_excess_returns) + lambda_risk * sqrt(mean(min(0, net_excess_returns)^2)) + lambda_turnover * mean(turnover)

    Args:
        weights: [W, N] portfolio asset weights (summing to 1.0)
        forward_returns: [W, N] forward asset returns over holding period
        benchmark_returns: [W] benchmark returns (e.g. BTC returns). If None, uses universe Equal-Weight return.
        fee_bps: Transaction fee in basis points
        lambda_turnover: Penalty weight for turnover
        lambda_risk: Penalty weight for relative downside semi-deviation
        use_drift: Whether to compute pre-trade drift-adjusted turnover
    """
    fee_rate = fee_bps / 10000.0
    W, N = forward_returns.shape

    # Gross portfolio return across the N assets
    gross_period_returns = torch.sum(weights * forward_returns, dim=-1)  # [W]

    if benchmark_returns is None:
        benchmark_returns = torch.mean(forward_returns, dim=-1)  # [W] (Equal-Weight)

    if use_drift and W > 1:
        # Pre-trade drifted asset weights: w_drift = w_i * (1 + r_i) / (1 + R_port)
        denom = torch.clamp(1.0 + gross_period_returns[:-1, None], min=1e-4)  # [W-1, 1]
        drifted_w = (weights[:-1] * (1.0 + forward_returns[:-1])) / denom     # [W-1, N]

        # Turnover at rebalances 1..W-1: 0.5 * sum |w_t - w_drift,t-1|
        turnover_steps = 0.5 * torch.sum(torch.abs(weights[1:] - drifted_w), dim=-1)  # [W-1]
        # Inception turnover from equal-weight:
        ew_init = torch.full((N,), 1.0 / N, device=weights.device)
        turnover_0 = 0.5 * torch.sum(torch.abs(weights[0] - ew_init))
        turnover = torch.cat([turnover_0.unsqueeze(0), turnover_steps], dim=0)  # [W]
    else:
        w_prev = torch.cat([torch.full((1, N), 1.0 / N, device=weights.device), weights[:-1]], dim=0)
        turnover = 0.5 * torch.sum(torch.abs(weights - w_prev), dim=-1)

    # Net portfolio return after fee drag
    net_period_returns = gross_period_returns - (turnover * fee_rate)

    # Net excess return over benchmark
    net_excess_returns = net_period_returns - benchmark_returns

    # Downside semi-deviation below benchmark (underperformance penalty)
    neg_excess = torch.minimum(net_excess_returns, torch.zeros_like(net_excess_returns))
    downside_dev = torch.sqrt(torch.mean(neg_excess**2) + 1e-8)

    mean_excess_return = torch.mean(net_excess_returns)
    mean_turnover = torch.mean(turnover)

    loss = -mean_excess_return + (lambda_risk * downside_dev) + (lambda_turnover * mean_turnover)

    return loss, mean_excess_return, downside_dev, mean_turnover


def train_neural_risky_sleeve(
    splits: DatasetSplits,
    btc_idx: int,
    hidden_dim: int = 32,
    lr: float = 1e-3,
    epochs: int = 50,
    seed: int = 42,
    fee_bps: float = 12.0,
    lambda_risk: float = 0.5,
    lambda_turnover: float = 0.002,
    use_drift: bool = True,
    temporal_shuffle: bool = False,
    benchmark_type: str = "btc",  # "btc" or "equal_weight"
) -> Tuple[UnifiedNeuralPolicy, Dict[str, List[float]]]:
    """Train a fully-invested risky sleeve policy optimizing cross-sectional excess return.

    Constraints:
      - allow_cash=False: outputs [W, N] long-only weights summing to 1.0.
      - If temporal_shuffle=True: permutes Train forward returns across weeks, breaking
        the temporal association while preserving exact feature distributions and correlations.
    """
    torch.manual_seed(seed)
    np.random.seed(seed)

    num_assets = len(splits.symbols)
    in_features = splits.train_x.shape[-1]

    model = UnifiedNeuralPolicy(num_assets=num_assets, in_features=in_features, hidden_dim=hidden_dim, allow_cash=False)
    optimizer = optim.Adam(model.parameters(), lr=lr)

    train_returns = splits.train_returns.clone()
    if temporal_shuffle:
        perm = torch.randperm(train_returns.shape[0])
        train_returns = train_returns[perm]

    if benchmark_type == "btc":
        train_bench = train_returns[:, btc_idx]
        val_bench = splits.val_returns[:, btc_idx]
    else:
        train_bench = torch.mean(train_returns, dim=-1)
        val_bench = torch.mean(splits.val_returns, dim=-1)

    history = {
        "train_loss": [],
        "val_loss": [],
        "train_excess": [],
        "val_excess": [],
    }

    best_val_loss = float("inf")
    best_weights = None

    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()

        # Forward pass on train set
        train_w = model(splits.train_x)  # [W_train, N]
        loss, train_excess, train_dd, train_to = compute_cross_sectional_loss(
            weights=train_w,
            forward_returns=train_returns,
            benchmark_returns=train_bench,
            fee_bps=fee_bps,
            lambda_turnover=lambda_turnover,
            lambda_risk=lambda_risk,
            use_drift=use_drift,
        )

        loss.backward()
        optimizer.step()

        # Validation evaluation (unshuffled)
        model.eval()
        with torch.no_grad():
            val_w = model(splits.val_x)  # [W_val, N]
            val_loss, val_excess, val_dd, val_to = compute_cross_sectional_loss(
                weights=val_w,
                forward_returns=splits.val_returns,
                benchmark_returns=val_bench,
                fee_bps=fee_bps,
                lambda_turnover=lambda_turnover,
                lambda_risk=lambda_risk,
                use_drift=use_drift,
            )

        history["train_loss"].append(float(loss.item()))
        history["val_loss"].append(float(val_loss.item()))
        history["train_excess"].append(float(train_excess.item()))
        history["val_excess"].append(float(val_excess.item()))

        if float(val_loss.item()) < best_val_loss:
            best_val_loss = float(val_loss.item())
            best_weights = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    if best_weights is not None:
        model.load_state_dict(best_weights)

    return model, history
