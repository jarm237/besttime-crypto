"""S3-P1: Unified Neural Portfolio Allocation Policy Train-Only Pilot.

Implements the pre-registered research blueprint S3-P0.1:
  - Asset Universe: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT + USDT Cash.
  - Timeline: Train 2022-01-01 to 2023-12-31 (with late 2021 warmup).
  - Causal Invariants: Decision at 00:05 UTC (closed bars up to 00:00:00 UTC),
    Execution at 01:00 UTC Open price (55-minute operational lag).
  - Neural Architecture: Shared GRU + Cross-Asset Attention + Scale-Invariant State Fusion +
    Factored Allocation Simplex & Exact HOLD Gate.
  - Accounting: Exact self-consistent fixed-point transaction fee equation.
  - Controls: 100% Cash, BTC B&H, EW4 B&H, Static 50/50 (monthly), Monthly EW4, Causal MVO-L1.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf
import torch
import torch.nn as nn
import torch.optim as optim

from btc_scraper.research.historical_data_loader import HistoricalDataLoader, DEFAULT_STORAGE_DIR
from btc_scraper.research.portfolio_accounting import (
    compute_standardized_metrics,
    execute_self_consistent_rebalance_step,
)

logger = logging.getLogger("s3_p1_train_only")

CANONICAL_UNIVERSE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]


# ==============================================================================
# 1. UNIFIED NEURAL ARCHITECTURE
# ==============================================================================

class S3UnifiedNeuralPolicy(nn.Module):
    """Unified Portfolio-Aware Cost-Aware Neural Allocation Policy with Exact Inaction Gate.

    Tensor Contract:
      - market_seq: [B, T=168, N=4, F=6] (sequence of closed hourly bars)
      - port_state: [B, F_portfolio=7] (decision-observable portfolio state at 00:05 UTC)
          port_state[:, 0:N]: observable asset weights w_obs_assets [B, N]
          port_state[:, N]: observable cash weight w_obs_cash [B, 1]
          port_state[:, N+1]: max drift relative to last executed allocation [B, 1]
          port_state[:, N+2]: friction ratio [B, 1]
      - proposed_weights: [B, N+1=5] (simplex over 4 assets + cash)
      - trade_gate_logit: [B, 1] (binary authorization gate logit)
    """

    def __init__(
        self,
        num_assets: int = 4,
        in_features: int = 6,
        gru_hidden: int = 32,
        num_heads: int = 2,
        port_features: int = 7,
    ) -> None:
        super().__init__()
        self.num_assets = num_assets
        self.in_features = in_features
        self.gru_hidden = gru_hidden
        self.port_features = port_features

        # 1. Shared Temporal Encoder across assets (processes T steps independently per asset)
        self.temporal_encoder = nn.GRU(
            input_size=in_features,
            hidden_size=gru_hidden,
            num_layers=1,
            batch_first=True,
        )

        # 2. Cross-Asset Relational Multi-Head Attention
        self.cross_asset_attn = nn.MultiheadAttention(
            embed_dim=gru_hidden,
            num_heads=num_heads,
            batch_first=True,
        )
        self.layer_norm = nn.LayerNorm(gru_hidden)

        # 3. Direct Per-Asset Allocation Head (Shared across all N assets for permutation equivariance)
        # Input: contextual_asset_emb_i (gru_hidden) + global_market_context (gru_hidden) + w_obs_i (1) = 2*gru_hidden + 1
        asset_in_dim = 2 * gru_hidden + 1
        self.shared_asset_head = nn.Sequential(
            nn.Linear(asset_in_dim, gru_hidden),
            nn.GELU(),
            nn.Linear(gru_hidden, 1),
        )

        # 4. Cash Allocation Head
        # Input: global_market_context (gru_hidden) + global_port_state (3: cash_w, drift, friction_ratio)
        global_port_dim = port_features - num_assets  # 7 - 4 = 3
        cash_in_dim = gru_hidden + global_port_dim
        self.cash_head = nn.Sequential(
            nn.Linear(cash_in_dim, gru_hidden),
            nn.GELU(),
            nn.Linear(gru_hidden, 1),
        )

        # 5. Exact Inaction Gate Head (Binary Trade Authorization)
        # Input: global_market_context (gru_hidden) + global_port_state (3)
        self.gate_head = nn.Sequential(
            nn.Linear(cash_in_dim, gru_hidden),
            nn.GELU(),
            nn.Linear(gru_hidden, 1),
        )

    def forward(
        self,
        market_seq: torch.Tensor,
        port_state: torch.Tensor,
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """Forward pass emitting proposed allocation weights and gate logit."""
        B, T, N, F = market_seq.shape
        assert N == self.num_assets, f"Expected {self.num_assets} assets, got {N}"

        # 1. Temporal encoding: [B * N, T, F] -> [B, N, gru_hidden]
        x_reshaped = market_seq.permute(0, 2, 1, 3).reshape(B * N, T, F)
        _, h_last = self.temporal_encoder(x_reshaped)
        h_assets = h_last.squeeze(0).view(B, N, self.gru_hidden)  # [B, N, gru_hidden]

        # 2. Cross-asset attention across N crypto assets
        attn_out, _ = self.cross_asset_attn(h_assets, h_assets, h_assets)
        contextual_assets = self.layer_norm(h_assets + attn_out)  # [B, N, gru_hidden]

        # 3. Global market context (mean pool of contextual embeddings)
        h_global = contextual_assets.mean(dim=1)  # [B, gru_hidden]

        # Global portfolio features: [w_obs_cash, drift, friction_ratio]
        global_port_state = port_state[:, self.num_assets:]  # [B, 3]
        global_context = torch.cat([h_global, global_port_state], dim=-1)  # [B, gru_hidden + 3]

        # 4. Direct Per-Asset Allocation Logits
        asset_logits_list: List[torch.Tensor] = []
        for i in range(N):
            asset_i_feat = torch.cat([
                contextual_assets[:, i, :],      # [B, gru_hidden]
                h_global,                        # [B, gru_hidden]
                port_state[:, i:i+1],            # [B, 1] (w_obs_i)
            ], dim=-1)                           # [B, 2*gru_hidden + 1]
            logit_i = self.shared_asset_head(asset_i_feat)  # [B, 1]
            asset_logits_list.append(logit_i)

        asset_logits = torch.cat(asset_logits_list, dim=-1)  # [B, N]

        # 5. Cash logit and joint softmax
        cash_logit = self.cash_head(global_context)  # [B, 1]
        all_logits = torch.cat([asset_logits, cash_logit], dim=-1)  # [B, N+1]
        proposed_weights = torch.softmax(all_logits, dim=-1)  # [B, N+1]

        # 6. Inaction Gate Logit
        gate_logit = self.gate_head(global_context)  # [B, 1]

        return proposed_weights, gate_logit

    def get_parameter_count(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


# ==============================================================================
# 2. FEATURE EXTRACTION & CAUSAL TIMELINE
# ==============================================================================

@dataclass
class DailyDecisionSample:
    """A point-in-time daily decision sample with strictly causal information boundary."""
    decision_idx: int
    decision_time_utc: pd.Timestamp       # 00:05:00 UTC
    feature_cutoff_utc: pd.Timestamp      # 00:00:00 UTC (latest closed candle)
    execution_time_utc: pd.Timestamp      # 01:00:00 UTC (orders execute at Open)
    next_execution_time_utc: pd.Timestamp # Next day 01:00:00 UTC (holding period end)
    market_seq: np.ndarray                # [T=168, N=4, F=6] (true calendar hourly bars)
    obs_prices: np.ndarray                # [N=4] Close price of 23:00-00:00 bar
    exec_prices: np.ndarray               # [N=4] Open price of 01:00-02:00 bar
    next_exec_prices: np.ndarray          # [N=4] Open price of next day 01:00-02:00 bar
    bench_return: float                   # EW4 B&H simple holding return from exec to next_exec
    bench_log_return: float               # EW4 B&H log holding return from exec to next_exec
    rolling_168h_returns: np.ndarray      # [N=4] for MVO-L1 expected return estimation
    rolling_720h_cov: np.ndarray          # [N=4, N=4] Ledoit-Wolf shrunk daily covariance for MVO-L1
    is_month_start: bool                  # True if this day is the 1st of calendar month


class S3CausalDataset:
    """Prepares strictly causal daily decision samples for Train (2022-2023)."""

    def __init__(
        self,
        universe: Sequence[str] = CANONICAL_UNIVERSE,
        lookback_seq_hours: int = 168,
        mvo_cov_lookback_hours: int = 720,
    ) -> None:
        self.universe = list(universe)
        self.lookback_seq_hours = lookback_seq_hours
        self.mvo_cov_lookback_hours = mvo_cov_lookback_hours

    def build_train_dataset(
        self,
        loader: HistoricalDataLoader,
        train_start: datetime = datetime(2022, 1, 1, 0, 0, tzinfo=timezone.utc),
        train_end: datetime = datetime(2023, 12, 31, 23, 59, tzinfo=timezone.utc),
        warmup_start: datetime = datetime(2021, 11, 1, 0, 0, tzinfo=timezone.utc),
    ) -> Tuple[List[DailyDecisionSample], Dict[str, Any]]:
        """Load and align data from warmup to train_end, constructing causal daily decision samples."""
        aligned = loader.load_aligned_universe(warmup_start, train_end)

        piv_close_raw = aligned.piv_close
        piv_open_raw = aligned.piv_open
        piv_volume_raw = aligned.piv_volume
        raw_timestamps = piv_close_raw.index
        N = len(self.universe)

        # Build contiguous 1-hour UTC calendar index across entire range
        full_cal_index = pd.date_range(start=raw_timestamps[0], end=raw_timestamps[-1], freq="1h")

        # Reindex across true calendar hours: missing hours become NaN (no synthetic candles, no bfill/ffill)
        piv_close = piv_close_raw.reindex(full_cal_index)
        piv_open = piv_open_raw.reindex(full_cal_index)
        piv_volume = piv_volume_raw.reindex(full_cal_index)
        timestamps = full_cal_index

        # Hourly log returns on true calendar hours
        hourly_log_rets = np.log(piv_close / piv_close.shift(1))

        # True calendar lookback features
        ret_24h = (piv_close / piv_close.shift(24) - 1.0)[self.universe].fillna(0.0).to_numpy(dtype=np.float32)
        ret_72h = (piv_close / piv_close.shift(72) - 1.0)[self.universe].fillna(0.0).to_numpy(dtype=np.float32)
        ret_168h = (piv_close / piv_close.shift(168) - 1.0)[self.universe].fillna(0.0).to_numpy(dtype=np.float32)

        # Realized volatility over 168 calendar hours
        vol_168h = (hourly_log_rets.rolling(168, min_periods=72).std() * np.sqrt(8760.0))[self.universe].fillna(0.0).to_numpy(dtype=np.float32)

        # Volume ratio over 168 calendar hours
        vol_ratio = (piv_volume / np.maximum(piv_volume.rolling(168, min_periods=72).mean(), 1e-6))[self.universe].fillna(1.0).to_numpy(dtype=np.float32)

        # Availability mask (1.0 for valid observed bar, 0.0 for exchange halt/gap)
        mask = (~piv_close.isna())[self.universe].astype(np.float32).to_numpy()

        piv_close_arr = piv_close[self.universe].fillna(0.0).to_numpy(dtype=np.float64)
        piv_open_arr = piv_open[self.universe].fillna(0.0).to_numpy(dtype=np.float64)
        log_rets_arr = hourly_log_rets[self.universe].fillna(0.0).to_numpy(dtype=np.float64)

        # Stack features: [Total_bars, N, 6]
        mkt_all = np.stack([ret_24h, ret_72h, ret_168h, vol_168h, vol_ratio, mask], axis=-1)

        ts_to_idx = {ts: i for i, ts in enumerate(timestamps)}
        raw_samples: List[Dict[str, Any]] = []
        lw = LedoitWolf()

        current_date = train_start.date()
        end_date = train_end.date()

        while current_date <= end_date:
            cutoff_ts = pd.Timestamp(datetime(current_date.year, current_date.month, current_date.day, 0, 0, tzinfo=timezone.utc))
            decision_ts = cutoff_ts + pd.Timedelta(minutes=5)
            last_closed_ts = cutoff_ts - pd.Timedelta(hours=1)
            exec_ts = cutoff_ts + pd.Timedelta(hours=1)
            next_exec_ts = exec_ts + pd.Timedelta(days=1)

            # Ensure holding period finishes within Train (no execution leaking past train_end)
            if next_exec_ts <= train_end + pd.Timedelta(hours=1):
                if last_closed_ts in ts_to_idx and exec_ts in ts_to_idx and next_exec_ts in ts_to_idx:
                    end_idx = ts_to_idx[last_closed_ts] + 1
                    start_idx = end_idx - self.lookback_seq_hours
                    cov_start_idx = end_idx - self.mvo_cov_lookback_hours

                    if start_idx >= 0 and cov_start_idx >= 0:
                        obs_prices = piv_close_arr[end_idx - 1]
                        exec_prices = piv_open_arr[ts_to_idx[exec_ts]]
                        next_exec_prices = piv_open_arr[ts_to_idx[next_exec_ts]]

                        # Ensure valid prices at execution points (fail closed if missing)
                        if np.all(exec_prices > 0.0) and np.all(next_exec_prices > 0.0) and np.all(obs_prices > 0.0):
                            mkt_slice = mkt_all[start_idx:end_idx]

                            r168 = ret_168h[end_idx - 1]
                            mvo_mu_24h = (1.0 + r168) ** (24.0 / 168.0) - 1.0

                            cov_slice = log_rets_arr[cov_start_idx:end_idx]
                            cov_daily = lw.fit(cov_slice).covariance_ * 24.0
                            is_month_start = (current_date.day == 1)

                            raw_samples.append({
                                "decision_time_utc": decision_ts,
                                "feature_cutoff_utc": cutoff_ts,
                                "execution_time_utc": exec_ts,
                                "next_execution_time_utc": next_exec_ts,
                                "market_seq": mkt_slice,
                                "obs_prices": obs_prices,
                                "exec_prices": exec_prices,
                                "next_exec_prices": next_exec_prices,
                                "rolling_168h_returns": mvo_mu_24h,
                                "rolling_720h_cov": cov_daily,
                                "is_month_start": is_month_start,
                            })

            current_date += timedelta(days=1)

        # Precompute canonical EW4 Buy & Hold holding trajectory
        # Initial $10,000 allocated equally 25% into 4 crypto assets at sample 0 execution Open
        base_fee_rate = 12.0 / 10000.0
        initial_cap = 10000.0
        fee_init = initial_cap * base_fee_rate
        cap_after_fee = initial_cap - fee_init
        p0_exec = raw_samples[0]["exec_prices"]
        q_ew4_bench = (0.25 * cap_after_fee) / p0_exec  # frozen physical coin quantities

        samples: List[DailyDecisionSample] = []
        for idx, r in enumerate(raw_samples):
            p_t = r["exec_prices"]
            p_next = r["next_exec_prices"]
            if idx == 0:
                v_pre = initial_cap
                v_next = float(np.sum(q_ew4_bench * p_next))
            else:
                v_pre = float(np.sum(q_ew4_bench * p_t))
                v_next = float(np.sum(q_ew4_bench * p_next))

            bench_log_ret = float(np.log(max(v_next / max(v_pre, 1e-4), 1e-4)))
            bench_ret = float(np.exp(bench_log_ret) - 1.0)

            sample = DailyDecisionSample(
                decision_idx=idx,
                decision_time_utc=r["decision_time_utc"],
                feature_cutoff_utc=r["feature_cutoff_utc"],
                execution_time_utc=r["execution_time_utc"],
                next_execution_time_utc=r["next_execution_time_utc"],
                market_seq=r["market_seq"],
                obs_prices=r["obs_prices"],
                exec_prices=r["exec_prices"],
                next_exec_prices=r["next_exec_prices"],
                bench_return=bench_ret,
                bench_log_return=bench_log_ret,
                rolling_168h_returns=r["rolling_168h_returns"],
                rolling_720h_cov=r["rolling_720h_cov"],
                is_month_start=r["is_month_start"],
            )
            samples.append(sample)

        manifest = {
            "train_start_utc": train_start.isoformat(),
            "train_end_utc": train_end.isoformat(),
            "warmup_start_utc": warmup_start.isoformat(),
            "universe": self.universe,
            "total_aligned_hours": len(timestamps),
            "total_decision_samples": len(samples),
            "first_decision_utc": samples[0].decision_time_utc.isoformat() if samples else "",
            "last_decision_utc": samples[-1].decision_time_utc.isoformat() if samples else "",
            "last_execution_utc": samples[-1].execution_time_utc.isoformat() if samples else "",
            "last_holding_end_utc": samples[-1].next_execution_time_utc.isoformat() if samples else "",
            "calendar_gap_count": len(aligned.alignment_audit.get("market_wide_calendar_gaps", [])),
        }

        return samples, manifest


# ==============================================================================
# 3. CAUSAL MVO-L1 OPTIMIZER
# ==============================================================================

class CausalMVOL1Optimizer:
    """Solves the convex quadratic program for Cost-Aware MVO-L1 at 00:05 UTC.

    Objective:
      w* = argmax_{w in Delta^{N+1}} [ mu^T w - gamma * w^T Sigma w - c_hat * ||w_assets - w_assets_obs||_1 ]

    Strict Parity:
      - Uses strictly observable weights w_assets_obs valued at 00:00:00 Close.
      - Zero lookahead to 01:00 execution prices.
      - Cash carries 0 return, 0 variance, and 0 rebalance fee.
    """

    def __init__(self, gamma: float = 2.0, fee_bps: float = 12.0) -> None:
        self.gamma = gamma
        self.fee_rate = fee_bps / 10000.0

    def optimize(
        self,
        mu_24h: np.ndarray,
        sigma_24h: np.ndarray,
        obs_asset_weights: np.ndarray,
    ) -> np.ndarray:
        """Solve for optimal simplex vector [w_1, ..., w_N, w_cash]."""
        N = len(mu_24h)
        c_hat = self.fee_rate
        gamma = self.gamma

        def neg_utility(x: np.ndarray) -> float:
            w_assets = x[:N]
            ret = float(np.dot(mu_24h, w_assets))
            risk = gamma * float(np.dot(w_assets, np.dot(sigma_24h, w_assets)))
            cost = c_hat * float(np.sum(np.abs(w_assets - obs_asset_weights)))
            return -(ret - risk - cost)

        bounds = [(0.0, 1.0) for _ in range(N + 1)]
        constraints = [{"type": "eq", "fun": lambda x: np.sum(x) - 1.0}]

        # Initial point: current observed weights with residual in cash
        w0_assets = np.clip(obs_asset_weights, 0.0, 1.0)
        cash0 = max(0.0, 1.0 - float(np.sum(w0_assets)))
        x0 = np.append(w0_assets, cash0)
        x0 = x0 / np.sum(x0)

        res = minimize(neg_utility, x0, method="SLSQP", bounds=bounds, constraints=constraints, tol=1e-6)
        if res.success:
            w_opt = np.clip(res.x, 0.0, 1.0)
            return w_opt / np.sum(w_opt)
        else:
            return x0  # fallback to current weights (HOLD)


# ==============================================================================
# 4. DIFFERENTIABLE NEURAL TRAINING PIPELINE
# ==============================================================================

class DifferentiableS3Trainer:
    """Trains the unified neural policy with Straight-Through discrete gating and net-of-cost objective."""

    def __init__(
        self,
        model: S3UnifiedNeuralPolicy,
        lr: float = 1e-3,
        lambda_abs: float = 5.0,
        lambda_act: float = 2.0,
        fee_rate: float = 0.0012,
        seed: int = 42,
    ) -> None:
        torch.manual_seed(seed)
        np.random.seed(seed)
        self.model = model
        self.optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
        self.lambda_abs = lambda_abs
        self.lambda_act = lambda_act
        self.fee_rate = fee_rate

    def train_epoch(
        self,
        samples: List[DailyDecisionSample],
        tau: float = 0.5,
        device: torch.device = torch.device("cpu"),
    ) -> Dict[str, float]:
        """Runs a sequential differentiable training pass maintaining portfolio equity state."""
        self.model.train()
        self.model.to(device)

        N = len(CANONICAL_UNIVERSE)
        current_holdings = torch.zeros(N, device=device)
        current_cash = torch.tensor(10000.0, device=device)
        last_executed_weights = torch.zeros(N, device=device)

        log_returns: List[torch.Tensor] = []
        bench_returns: List[float] = []
        gate_decisions: List[float] = []
        turnovers: List[float] = []

        self.optimizer.zero_grad()

        for s in samples:
            # 1. Build Decision-Observable Portfolio State [F_portfolio=7]
            obs_prices_t = torch.tensor(s.obs_prices, dtype=torch.float32, device=device)
            asset_vals_obs = current_holdings * obs_prices_t
            V_obs = current_cash + torch.sum(asset_vals_obs)
            denom = torch.clamp(V_obs, min=1e-4)

            w_obs_assets = (asset_vals_obs / denom).view(-1)
            w_obs_cash = (current_cash / denom).view(-1)
            # Drift relative to LAST EXECUTED weights (causal and consistent with unexecuted HOLDs)
            drift = torch.max(torch.abs(w_obs_assets - last_executed_weights)).view(-1)
            friction_ratio = torch.tensor([self.fee_rate / max(float(s.market_seq[:, 0, 3].mean()), 1e-4)], device=device).view(-1)

            port_state = torch.cat([w_obs_assets, w_obs_cash, drift, friction_ratio]).unsqueeze(0)  # [1, 7]
            mkt_seq = torch.tensor(s.market_seq, dtype=torch.float32, device=device).unsqueeze(0)  # [1, 168, 4, 6]

            # 2. Model forward pass
            proposed_w, gate_logit = self.model(mkt_seq, port_state)
            target_asset_w = proposed_w[0, :N]
            target_cash_w = proposed_w[0, -1]

            # 3. Deterministic Straight-Through Estimator (STE) Gate
            # Forward action is discrete and exactly identical to inference: gate = 1 if gate_logit > 0.0 else 0
            gate_soft = torch.sigmoid(gate_logit / tau)
            gate_hard = (gate_logit > 0.0).to(gate_soft.dtype)
            gate = gate_hard - gate_soft.detach() + gate_soft

            gate_decisions.append(gate_hard.item())

            # 4. Valuation at execution time
            exec_prices_t = torch.tensor(s.exec_prices, dtype=torch.float32, device=device)
            next_exec_prices_t = torch.tensor(s.next_exec_prices, dtype=torch.float32, device=device)

            asset_vals_pre = current_holdings * exec_prices_t
            V_pre = current_cash + torch.sum(asset_vals_pre)

            # Differentiable 2-step fixed-point fee iteration
            fee = self.fee_rate * torch.sum(torch.abs(V_pre * target_asset_w - asset_vals_pre))
            V_post = torch.clamp(V_pre - fee, min=1.0)
            fee = self.fee_rate * torch.sum(torch.abs(V_post * target_asset_w - asset_vals_pre))
            V_post = torch.clamp(V_pre - fee, min=1.0)

            # Post-trade physical holdings under trade
            q_trade = (V_post * target_asset_w) / exec_prices_t
            C_trade = V_post * target_cash_w

            # Exact HOLD vs Trade blend
            g_val = gate.squeeze()
            q_after = (1.0 - g_val) * current_holdings + g_val * q_trade
            C_after = (1.0 - g_val) * current_cash + g_val * C_trade

            # Next period pre-trade valuation
            V_next_pre = C_after + torch.sum(q_after * next_exec_prices_t)
            ret_step = torch.log(torch.clamp(V_next_pre / torch.clamp(V_pre, min=1.0), min=1e-4))

            log_returns.append(ret_step)
            bench_returns.append(s.bench_log_return)

            # State advance (detach for truncated BPTT segment to ensure numerical stability)
            current_holdings = q_after.detach().view(-1)
            current_cash = C_after.detach().squeeze()

            # Update last_executed_weights ONLY when gate_hard == 1
            w_post_trade = (q_trade.detach().view(-1) * exec_prices_t) / torch.clamp(V_post.detach(), min=1e-4)
            last_executed_weights = (1.0 - gate_hard.detach().squeeze()) * last_executed_weights + gate_hard.detach().squeeze() * w_post_trade

        # 5. Dual Downside Regularized Objective
        rets_tensor = torch.stack(log_returns)
        mean_log_ret = torch.mean(rets_tensor)

        # Absolute downside penalty
        abs_downside = torch.mean(torch.clamp(-rets_tensor, min=0.0) ** 2)

        # Active downside penalty vs EW4 Buy & Hold
        bench_tensor = torch.tensor(bench_returns, dtype=torch.float32, device=device)
        act_downside = torch.mean(torch.clamp(bench_tensor - rets_tensor, min=0.0) ** 2)

        total_loss = -(mean_log_ret - self.lambda_abs * abs_downside - self.lambda_act * act_downside)

        total_loss.backward()

        # Gradient clipping
        grad_norm = torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
        self.optimizer.step()

        return {
            "loss": float(total_loss.item()),
            "mean_log_ret": float(mean_log_ret.item()),
            "abs_downside": float(abs_downside.item()),
            "act_downside": float(act_downside.item()),
            "grad_norm": float(grad_norm.item() if hasattr(grad_norm, "item") else grad_norm),
            "rebalance_rate": float(np.mean(gate_decisions)),
            "hold_rate": float(1.0 - np.mean(gate_decisions)),
        }


# ==============================================================================
# 5. CANONICAL EXECUTION REPLAY ENGINE
# ==============================================================================

@dataclass
class DecisionLedgerRecord:
    decision_idx: int
    decision_time_utc: str
    feature_cutoff_utc: str
    execution_time_utc: str
    portfolio_equity_before: float
    observed_asset_weights: List[float]
    observed_cash_weight: float
    proposed_asset_weights: List[float]
    proposed_cash_weight: float
    gate_decision: int
    executed_orders_count: int
    traded_notional: float
    transaction_fee: float
    portfolio_equity_post_fee: float
    cash_after: float
    holdings_after: List[float]
    execution_reason: str


class CanonicalReplayEngine:
    """Executes deterministic canonical portfolio replay for all policies on Train (2022-2023)."""

    def __init__(
        self,
        samples: List[DailyDecisionSample],
        initial_capital: float = 10000.0,
        fee_bps: float = 12.0,
        min_notional: float = 0.0,
    ) -> None:
        self.samples = samples
        self.initial_capital = initial_capital
        self.fee_bps = fee_bps
        self.min_notional = min_notional
        self.N = len(CANONICAL_UNIVERSE)

    def replay_policy(
        self,
        policy_name: str,
        policy_type: str,
        neural_model: Optional[S3UnifiedNeuralPolicy] = None,
        mvo_optimizer: Optional[CausalMVOL1Optimizer] = None,
    ) -> Tuple[Dict[str, Any], List[DecisionLedgerRecord], pd.Series]:
        """Replay a specific policy through the canonical causal timeline."""
        holdings = np.zeros(self.N, dtype=np.float64)
        cash = float(self.initial_capital)
        last_executed_weights = np.zeros(self.N, dtype=np.float64)

        equity_curve: List[float] = [cash]
        equity_dates: List[pd.Timestamp] = [self.samples[0].execution_time_utc]
        ledger: List[DecisionLedgerRecord] = []

        total_traded_notional = 0.0
        total_fees = 0.0
        rebalance_count = 0
        gross_turnover = 0.0
        one_way_turnover = 0.0
        cash_weights: List[float] = []

        for s in self.samples:
            # 1. Decision-observable portfolio state at 00:05 UTC (Close of 23:00-00:00)
            asset_vals_obs = holdings * s.obs_prices
            equity_obs = cash + float(np.sum(asset_vals_obs))
            w_obs_assets = asset_vals_obs / max(equity_obs, 1e-4)
            w_obs_cash = cash / max(equity_obs, 1e-4)
            # Drift relative to LAST EXECUTED weights
            drift = float(np.max(np.abs(w_obs_assets - last_executed_weights)))

            # 2. Determine target allocation and gate based on policy type
            if policy_type == "CASH":
                target_asset_w = np.zeros(self.N)
                target_cash_w = 1.0
                gate = 0

            elif policy_type == "BTC_BNH":
                target_asset_w = np.array([1.0, 0.0, 0.0, 0.0])
                target_cash_w = 0.0
                gate = 1 if s.decision_idx == 0 else 0  # initial entry only

            elif policy_type == "EW4_BNH":
                target_asset_w = np.array([0.25, 0.25, 0.25, 0.25])
                target_cash_w = 0.0
                gate = 1 if s.decision_idx == 0 else 0  # initial entry only

            elif policy_type == "STATIC_50_50":
                target_asset_w = np.array([0.125, 0.125, 0.125, 0.125])
                target_cash_w = 0.50
                gate = 1 if (s.decision_idx == 0 or s.is_month_start) else 0

            elif policy_type == "MONTHLY_EW4":
                target_asset_w = np.array([0.25, 0.25, 0.25, 0.25])
                target_cash_w = 0.0
                gate = 1 if (s.decision_idx == 0 or s.is_month_start) else 0

            elif policy_type == "MVO_L1":
                assert mvo_optimizer is not None
                w_opt = mvo_optimizer.optimize(
                    mu_24h=s.rolling_168h_returns,
                    sigma_24h=s.rolling_720h_cov,
                    obs_asset_weights=w_obs_assets,
                )
                target_asset_w = w_opt[:self.N]
                target_cash_w = float(w_opt[-1])
                # MVO-L1 with fixed 1% execution deadband
                gate = 1 if float(np.sum(np.abs(target_asset_w - w_obs_assets))) > 0.01 else 0

            elif policy_type == "NEURAL":
                assert neural_model is not None
                neural_model.eval()
                with torch.no_grad():
                    # Format inputs
                    model_device = next(neural_model.parameters()).device
                    f_ratio = (self.fee_bps / 10000.0) / max(float(s.market_seq[:, 0, 3].mean()), 1e-4)
                    p_state = np.append(w_obs_assets, [w_obs_cash, drift, f_ratio]).astype(np.float32)

                    p_tensor = torch.tensor(p_state, device=model_device).unsqueeze(0)
                    m_tensor = torch.tensor(s.market_seq, dtype=torch.float32, device=model_device).unsqueeze(0)

                    w_prop, g_logit = neural_model(m_tensor, p_tensor)
                    target_asset_w = w_prop[0, :self.N].cpu().numpy().astype(np.float64)
                    target_cash_w = float(w_prop[0, -1].cpu().item())
                    # Deterministic inference parity: gate = 1 if g_logit > 0.0 else 0
                    gate = 1 if g_logit.item() > 0.0 else 0

            else:
                raise ValueError(f"Unknown policy type: {policy_type}")

            # 3. Execution at 01:00 UTC Open
            pre_vals = holdings * s.exec_prices
            equity_pre = cash + float(np.sum(pre_vals))

            (
                new_holdings,
                new_cash,
                traded_notional,
                fee_paid,
                to_1way,
                to_gross,
                orders_count,
            ) = execute_self_consistent_rebalance_step(
                current_holdings=holdings,
                current_cash=cash,
                open_prices=s.exec_prices,
                target_weights=target_asset_w,
                target_cash_w=target_cash_w,
                action_gate=gate,
                fee_bps=self.fee_bps,
                min_notional=self.min_notional,
            )

            holdings = new_holdings
            cash = new_cash
            total_traded_notional += traded_notional
            total_fees += fee_paid
            gross_turnover += to_gross
            one_way_turnover += to_1way
            post_equity = cash + float(np.sum(holdings * s.exec_prices))

            if orders_count > 0:
                rebalance_count += 1
                last_executed_weights = (holdings * s.exec_prices) / max(post_equity, 1e-4)

            post_equity = cash + float(np.sum(holdings * s.exec_prices))
            cash_w = cash / max(post_equity, 1e-4)
            cash_weights.append(cash_w)

            # Reason description
            if gate == 0:
                reason = "EXACT_HOLD"
            elif orders_count == 0 and gate == 1:
                reason = "NO_EXECUTION_DUE_TO_MIN_NOTIONAL"
            else:
                reason = "REBALANCED_EXECUTED"

            record = DecisionLedgerRecord(
                decision_idx=s.decision_idx,
                decision_time_utc=s.decision_time_utc.isoformat(),
                feature_cutoff_utc=s.feature_cutoff_utc.isoformat(),
                execution_time_utc=s.execution_time_utc.isoformat(),
                portfolio_equity_before=round(equity_pre, 2),
                observed_asset_weights=[round(float(x), 4) for x in w_obs_assets],
                observed_cash_weight=round(float(w_obs_cash), 4),
                proposed_asset_weights=[round(float(x), 4) for x in target_asset_w],
                proposed_cash_weight=round(float(target_cash_w), 4),
                gate_decision=int(gate),
                executed_orders_count=orders_count,
                traded_notional=round(traded_notional, 2),
                transaction_fee=round(fee_paid, 2),
                portfolio_equity_post_fee=round(post_equity, 2),
                cash_after=round(cash, 2),
                holdings_after=[round(float(x), 6) for x in holdings],
                execution_reason=reason,
            )
            ledger.append(record)

            # Advance mark-to-market equity to holding period end (next execution time)
            next_eq = cash + float(np.sum(holdings * s.next_exec_prices))
            equity_curve.append(next_eq)
            equity_dates.append(s.next_execution_time_utc)

        eq_series = pd.Series(equity_curve, index=equity_dates)
        metrics = compute_standardized_metrics(
            portfolio_name=policy_name,
            equity_series=eq_series,
            initial_capital_usd=self.initial_capital,
            total_fees_usd=total_fees,
            one_way_turnover=one_way_turnover,
            gross_asset_turnover=gross_turnover,
            total_traded_notional_usd=total_traded_notional,
            rebalance_count=rebalance_count,
            mean_cash_weight=float(np.mean(cash_weights)),
            periods_per_year=365.0,  # daily decision steps
        )

        return metrics, ledger, eq_series
