"""Learned Policy v1 — Unified Neural Portfolio Policy with Chronological Splits.

Research Track: Profit-First Multi-Horizon Learned Policy.
Universe: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT (Spot, Long-Only, Cash/BTC).
Data Splits:
- Warmup:      2021 (Feature initialization)
- Train:       2022-01-01 -> 2023-12-31 (Model fitting)
- Validation:  2024-01-01 -> 2024-12-31 (Model selection)
- Reused Test: 2025-01-01 -> 2026-11-18 (Final historical diagnostic)
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.optim import AdamW

from btc_scraper.research.s5_economic_replay import solve_post_fee_equity
from btc_scraper.research.track_a_strategy import (
    PRIMARY_INITIAL_CAPITAL,
    TrackAReplayResult,
    compute_performance_metrics,
    compute_track_a_signals,
    load_universe_panels,
    run_btc_buy_and_hold_replay,
    run_s5_daily_trend_replay,
    run_track_a_replay,
)

logger = logging.getLogger("learned_policy_v1")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = REPO_ROOT / "research/track_a/learned_v1"

SPLIT_WINDOWS = {
    "WARMUP": ("2021-01-01", "2021-12-31"),
    "TRAIN": ("2022-01-01", "2023-12-31"),
    "VALIDATION": ("2024-01-01", "2024-12-31"),
    "REUSED_TEST": ("2025-01-01", "2026-11-18"),
    "FULL": ("2022-01-01", "2026-11-18"),
}


def build_daily_candles(hourly_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1h candles into complete UTC daily candles."""
    daily = hourly_df.resample("1D").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "open_time_ms": "count",
    }).rename(columns={"open_time_ms": "hour_count"})
    return daily[daily["hour_count"] > 0]


def extract_causal_features(panels: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Extract Point-in-Time causal features for decision day D at 00:00 UTC.

    Decision on day D (00:00 UTC) can ONLY observe candles up to day D-1 (closed at 23:59:59 UTC).
    """
    daily_panels = {s: build_daily_candles(panels[s]) for s in panels}
    btc = daily_panels["BTCUSDT"]
    eth = daily_panels["ETHUSDT"]
    sol = daily_panels["SOLUSDT"]
    bnb = daily_panels["BNBUSDT"]

    # Align dates
    common_idx = btc.index.intersection(eth.index).intersection(sol.index).intersection(bnb.index)
    btc = btc.loc[common_idx]
    eth = eth.loc[common_idx]
    sol = sol.loc[common_idx]
    bnb = bnb.loc[common_idx]

    features = pd.DataFrame(index=common_idx)

    # 1. Multi-horizon returns for BTC (pct_change based on close of D-1)
    # Note: Shift by 1 bar so feature at day D corresponds to information available up to D-1
    for h in [1, 3, 7, 14, 30]:
        features[f"btc_ret_{h}d"] = btc["close"].pct_change(h).shift(1)

    # 2. Realized volatility of BTC (rolling std of daily returns)
    btc_daily_ret = btc["close"].pct_change()
    for h in [7, 14, 30]:
        features[f"btc_vol_{h}d"] = btc_daily_ret.rolling(h).std().shift(1)

    # 3. Downside volatility (semi-deviation of negative returns)
    neg_ret = btc_daily_ret.clip(upper=0.0)
    for h in [14, 30]:
        features[f"btc_downside_vol_{h}d"] = neg_ret.rolling(h).std().shift(1)

    # 4. Momentum and trend persistence
    features["btc_trend_sma7_30"] = (btc["close"].rolling(7).mean() / btc["close"].rolling(30).mean() - 1.0).shift(1)
    features["btc_trend_sma20_60"] = (btc["close"].rolling(20).mean() / btc["close"].rolling(60).mean() - 1.0).shift(1)
    features["btc_sharpe_proxy_14d"] = (features["btc_ret_14d"] / (features["btc_vol_14d"] + 1e-6))

    # 5. Volume / Liquidity proxy
    features["btc_vol_ratio_7_30"] = (btc["volume"].rolling(7).mean() / (btc["volume"].rolling(30).mean() + 1e-6) - 1.0).shift(1)

    # 6. Cross-asset returns
    for h in [7, 30]:
        features[f"eth_ret_{h}d"] = eth["close"].pct_change(h).shift(1)
        features[f"sol_ret_{h}d"] = sol["close"].pct_change(h).shift(1)
        features[f"bnb_ret_{h}d"] = bnb["close"].pct_change(h).shift(1)

    # 7. Relative strength: BTC return vs Altcoin basket mean
    features["btc_rel_strength_7d"] = features["btc_ret_7d"] - (features["eth_ret_7d"] + features["sol_ret_7d"] + features["bnb_ret_7d"]) / 3.0
    features["btc_rel_strength_30d"] = features["btc_ret_30d"] - (features["eth_ret_30d"] + features["sol_ret_30d"] + features["bnb_ret_30d"]) / 3.0

    # 8. Cross-asset correlation (BTC vs ETH 30d)
    eth_daily_ret = eth["close"].pct_change()
    features["btc_eth_corr_30d"] = btc_daily_ret.rolling(30).corr(eth_daily_ret).shift(1)

    # Drop early warmup rows with NaNs
    features = features.dropna()
    return features


class TrainFittedScaler:
    """Feature scaler strictly fit on the Train period (2022-01-01 -> 2023-12-31)."""

    def __init__(self):
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None
        self.feature_names_: list[str] = []

    def fit(self, df_train: pd.DataFrame) -> TrainFittedScaler:
        self.feature_names_ = list(df_train.columns)
        values = df_train.to_numpy(dtype=np.float32)
        self.mean_ = np.nanmean(values, axis=0)
        std = np.nanstd(values, axis=0)
        self.scale_ = np.where(std < 1e-6, 1.0, std)
        return self

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        values = df[self.feature_names_].to_numpy(dtype=np.float32)
        return (values - self.mean_) / self.scale_

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_names": self.feature_names_,
            "mean": self.mean_.tolist() if self.mean_ is not None else [],
            "scale": self.scale_.tolist() if self.scale_ is not None else [],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrainFittedScaler:
        scaler = cls()
        scaler.feature_names_ = data["feature_names"]
        scaler.mean_ = np.array(data["mean"], dtype=np.float32)
        scaler.scale_ = np.array(data["scale"], dtype=np.float32)
        return scaler


class CompactUnifiedPolicy(nn.Module):
    """Compact Unified Neural Policy mapping Point-in-Time features + current weight -> BTC Target Weight."""

    def __init__(self, in_features: int, hidden_dim: int = 32):
        super().__init__()
        # in_features + 1 (for current portfolio BTC weight state)
        self.net = nn.Sequential(
            nn.Linear(in_features + 1, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.05),
            nn.Linear(hidden_dim, 16),
            nn.ReLU(),
            nn.Linear(16, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor, prev_weight: torch.Tensor) -> torch.Tensor:
        """Forward pass.

        x: (batch, in_features)
        prev_weight: (batch, 1)
        returns: (batch, 1) in [0, 1] representing target BTC weight.
        """
        combined = torch.cat([x, prev_weight], dim=-1)
        return self.net(combined)


def causal_differentiable_rollout(
    policy: CompactUnifiedPolicy,
    features: torch.Tensor,
    forward_btc_returns: torch.Tensor,
    fee_rate: float = 0.0030,
    downside_lambda: float = 2.0,
    turnover_lambda: float = 0.05,
) -> tuple[torch.Tensor, dict[str, float]]:
    """Differentiable causal portfolio rollout over time.

    features: (T, in_features)
    forward_btc_returns: (T,) return of BTC over holding interval from execution to next decision
    """
    T = len(features)
    prev_w = torch.tensor([[0.0]], dtype=torch.float32, device=features.device)

    log_returns = []
    turnovers = []
    downside_penalties = []
    weights = []

    for t in range(T):
        feat_t = features[t:t+1]
        target_w = policy(feat_t, prev_w)
        weights.append(target_w)

        turnover = torch.abs(target_w - prev_w)
        turnovers.append(turnover)

        fwd_ret = forward_btc_returns[t]
        # Net portfolio return = w * ret - fee_rate * turnover
        net_ret = target_w[0, 0] * fwd_ret - fee_rate * turnover[0, 0]

        # Prevent log(<= 0)
        net_ret_safe = torch.clamp(net_ret, min=-0.95)
        log_ret = torch.log(1.0 + net_ret_safe)
        log_returns.append(log_ret)

        # Downside penalty (semi-deviation squared)
        downside = torch.relu(-net_ret) ** 2
        downside_penalties.append(downside)

        prev_w = target_w.detach()

    total_growth = torch.sum(torch.stack(log_returns))
    total_downside = torch.sum(torch.stack(downside_penalties))
    total_turnover = torch.sum(torch.stack(turnovers))

    # Objective: maximize growth - downside penalty - turnover penalty
    # Loss: minimize -objective
    loss = -(total_growth - downside_lambda * total_downside - turnover_lambda * total_turnover)

    metrics = {
        "loss": float(loss.item()),
        "total_growth": float(total_growth.item()),
        "total_downside": float(total_downside.item()),
        "total_turnover": float(total_turnover.item()),
    }
    return loss, metrics


def compute_holding_period_returns(
    btc_hourly: pd.DataFrame,
    daily_dates: Sequence[pd.Timestamp],
    max_boundary_ts: pd.Timestamp | None = None,
) -> pd.Series:
    """Compute exact holding period return from Day D execution (01:00 UTC) to Day D+1 execution (01:00 UTC).

    Strict Causal Integrity Rules:
    1. Fails closed if execution prices at 01:00 UTC are missing within the active timeline.
    2. Drops the terminal dataset date when Day D+1 01:00 UTC does not exist (no synthetic 0.0 padding).
    3. Purges samples where next execution price exceeds max_boundary_ts.
    """
    valid_dates: list[pd.Timestamp] = []
    returns: list[float] = []

    dataset_max_ts = btc_hourly.index.max()

    for i in range(len(daily_dates)):
        dt_curr = daily_dates[i]
        exec_curr_ts = dt_curr + pd.Timedelta(hours=1)
        exec_next_ts = dt_curr + pd.Timedelta(days=1, hours=1)

        # Purge if exceeding explicit boundary
        if max_boundary_ts is not None and exec_next_ts > max_boundary_ts:
            continue

        # Terminal dataset boundary: if next execution does not exist in dataset, drop sample (no synthetic zero)
        if exec_next_ts > dataset_max_ts:
            continue

        # Fail closed on missing execution prices within the series
        if exec_curr_ts not in btc_hourly.index:
            raise ValueError(
                f"Missing execution price at {exec_curr_ts}. Strict execution convention fails closed; "
                "silent fallback to daily close is prohibited."
            )
        if exec_next_ts not in btc_hourly.index:
            raise ValueError(
                f"Missing next execution price at {exec_next_ts}. Strict execution convention fails closed; "
                "silent fallback to daily close is prohibited."
            )

        p_curr = float(btc_hourly.loc[exec_curr_ts, "open"])
        p_next = float(btc_hourly.loc[exec_next_ts, "open"])

        if p_curr <= 0.0 or p_next <= 0.0:
            raise ValueError(f"Non-positive execution price detected: p_curr={p_curr}, p_next={p_next} at {dt_curr}")

        ret = (p_next - p_curr) / p_curr
        valid_dates.append(dt_curr)
        returns.append(ret)

    return pd.Series(returns, index=valid_dates, dtype=float)


def train_learned_policy(
    features_df: pd.DataFrame,
    fwd_returns_s: pd.Series,
    scaler: TrainFittedScaler,
    train_start: str = "2022-01-01",
    train_end: str = "2023-12-31",
    val_start: str = "2024-01-01",
    val_end: str = "2024-12-31",
    seed: int = 42,
    epochs: int = 80,
    lr: float = 1e-3,
) -> tuple[CompactUnifiedPolicy, dict[str, Any]]:
    """Train compact policy with early stopping on validation wealth/Calmar.

    Boundary Purging:
    - Training labels: next execution timestamp must not exceed train_end (2023-12-31 23:59:59 UTC).
      Decisions on 2023-12-31 whose next execution is 2024-01-01 01:00 UTC are strictly purged.
    - Validation selection labels: next execution timestamp must not exceed val_end (2024-12-31 23:59:59 UTC).
      Decisions on 2024-12-31 whose next execution is 2025-01-01 01:00 UTC (reused test) are strictly purged.
    """
    torch.manual_seed(seed)
    np.random.seed(seed)

    # Filter features and forward returns to common valid dates
    common_idx = features_df.index.intersection(fwd_returns_s.index)
    idx_tz = common_idx.tz if hasattr(common_idx, "tz") else None

    def _to_bound(val: str, is_end: bool) -> pd.Timestamp:
        s = f"{val} 23:59:59" if is_end else f"{val} 00:00:00"
        ts = pd.Timestamp(s)
        if idx_tz is not None and ts.tzinfo is None:
            ts = ts.tz_localize(idx_tz)
        elif idx_tz is None and ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        return ts

    train_start_ts = _to_bound(train_start, False)
    train_end_boundary = _to_bound(train_end, True)
    val_start_ts = _to_bound(val_start, False)
    val_end_boundary = _to_bound(val_end, True)

    # Train mask with boundary purge
    train_dates = [
        d for d in common_idx
        if (d >= train_start_ts) and (d <= train_end_boundary) and ((d + pd.Timedelta(days=1, hours=1)) <= train_end_boundary)
    ]

    # Validation selection mask with boundary purge (no reused test prices)
    val_dates = [
        d for d in common_idx
        if (d >= val_start_ts) and (d <= val_end_boundary) and ((d + pd.Timedelta(days=1, hours=1)) <= val_end_boundary)
    ]

    X_train = scaler.transform(features_df.loc[train_dates])
    y_train = fwd_returns_s.loc[train_dates].to_numpy(dtype=np.float32)

    X_val = scaler.transform(features_df.loc[val_dates])
    y_val = fwd_returns_s.loc[val_dates].to_numpy(dtype=np.float32)

    t_X_train = torch.tensor(X_train, dtype=torch.float32)
    t_y_train = torch.tensor(y_train, dtype=torch.float32)

    t_X_val = torch.tensor(X_val, dtype=torch.float32)
    t_y_val = torch.tensor(y_val, dtype=torch.float32)

    policy = CompactUnifiedPolicy(in_features=X_train.shape[1], hidden_dim=32)
    optimizer = AdamW(policy.parameters(), lr=lr, weight_decay=1e-4)

    best_val_growth = -float("inf")
    best_weights: dict[str, Any] | None = None
    best_epoch = 0

    history = []

    for epoch in range(1, epochs + 1):
        policy.train()
        optimizer.zero_grad()
        loss, train_metrics = causal_differentiable_rollout(policy, t_X_train, t_y_train)
        loss.backward()
        optimizer.step()

        policy.eval()
        with torch.no_grad():
            val_loss, val_metrics = causal_differentiable_rollout(policy, t_X_val, t_y_val)

        val_growth = val_metrics["total_growth"]
        history.append({
            "epoch": epoch,
            "train_loss": train_metrics["loss"],
            "train_growth": train_metrics["total_growth"],
            "val_loss": val_metrics["loss"],
            "val_growth": val_metrics["total_growth"],
            "val_turnover": val_metrics["total_turnover"],
        })

        if val_growth > best_val_growth:
            best_val_growth = val_growth
            best_weights = {k: v.clone() for k, v in policy.state_dict().items()}
            best_epoch = epoch

    if best_weights is not None:
        policy.load_state_dict(best_weights)

    policy.eval()
    meta = {
        "best_epoch": best_epoch,
        "best_val_growth": best_val_growth,
        "history": history,
        "seed": seed,
        "train_samples_count": len(train_dates),
        "val_samples_count": len(val_dates),
        "train_last_date": str(train_dates[-1].date()) if train_dates else None,
        "val_last_date": str(val_dates[-1].date()) if val_dates else None,
    }
    return policy, meta


def run_learned_policy_replay(
    btc_hourly: pd.DataFrame,
    features_df: pd.DataFrame,
    scaler: TrainFittedScaler,
    policy: CompactUnifiedPolicy,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    initial_capital: float = PRIMARY_INITIAL_CAPITAL,
    fee_bps: float = 30.0,
    no_trade_band: float = 0.05,
) -> TrackAReplayResult:
    """Run exact hourly stateful economic replay of the learned policy using solve_post_fee_equity."""
    fee_rate = fee_bps / 10000.0
    timeline = btc_hourly.loc[start_dt:end_dt].index
    n_bars = len(timeline)

    equities = np.empty(n_bars, dtype=float)
    cash_hist = np.empty(n_bars, dtype=float)
    holdings_hist = np.empty(n_bars, dtype=float)
    weights_hist = np.empty(n_bars, dtype=float)
    turnovers = np.zeros(n_bars, dtype=float)
    fees = np.zeros(n_bars, dtype=float)

    cash = float(initial_capital)
    holdings = 0.0

    trade_events: list[dict[str, Any]] = []
    decision_ledger: list[dict[str, Any]] = []

    opens_arr = btc_hourly.loc[timeline, "open"].to_numpy(dtype=float)
    closes_arr = btc_hourly.loc[timeline, "close"].to_numpy(dtype=float)

    prev_target_w = 0.0

    # Policy inference cache
    policy.eval()

    for i in range(n_bars):
        ts = timeline[i]
        p_open = opens_arr[i]
        p_close = closes_arr[i]

        # Execution clock: evaluate at 01:00 UTC
        if ts.hour == 1:
            decision_date = ts.floor("D")
            if decision_date in features_df.index:
                feat_vec = scaler.transform(features_df.loc[[decision_date]])
                t_feat = torch.tensor(feat_vec, dtype=torch.float32)
                t_prev_w = torch.tensor([[prev_target_w]], dtype=torch.float32)
                with torch.no_grad():
                    target_w = float(policy(t_feat, t_prev_w).item())
            else:
                target_w = prev_target_w

            # Pre-trade mark to market at execution price (open of 01:00 bar)
            pre_btc_notional = holdings * p_open
            v_pre = cash + pre_btc_notional
            current_w = pre_btc_notional / v_pre if v_pre > 0 else 0.0
            deviation = abs(target_w - current_w)

            action = "HOLD"
            realized_fee = 0.0
            traded_notional = 0.0

            # Execute rebalance if deviation > band
            if deviation > no_trade_band:
                action = "REBALANCE"
                current_notionals = np.array([pre_btc_notional])
                target_weights = np.array([target_w])

                v_post, realized_fee = solve_post_fee_equity(
                    v_pre, current_notionals, target_weights, fee_rate
                )

                target_btc_notional = target_w * v_post
                traded_notional = abs(target_btc_notional - pre_btc_notional)
                holdings = target_btc_notional / p_open
                cash = (1.0 - target_w) * v_post

                turnovers[i] = traded_notional / v_pre if v_pre > 0 else 0.0
                fees[i] = realized_fee

                trade_events.append({
                    "ts": ts,
                    "execution_timestamp": ts.isoformat(),
                    "action": action,
                    "price": p_open,
                    "p_exec": p_open,
                    "trade_notional": traded_notional,
                    "traded_notional": traded_notional,
                    "fee": realized_fee,
                    "pre_cash": cash,
                    "pre_holdings": holdings,
                    "v_pre": v_pre,
                    "post_cash": cash,
                    "post_holdings": holdings,
                    "v_post": v_post,
                })
                prev_target_w = target_w

            decision_ledger.append({
                "ts": ts,
                "execution_timestamp": ts.isoformat(),
                "p_open": p_open,
                "current_w": current_w,
                "target_w": target_w,
                "deviation": deviation,
                "action": action,
                "trade_notional": traded_notional,
                "traded_notional": traded_notional,
                "fee": realized_fee,
                "post_cash": cash,
                "post_holdings": holdings,
                "nav": cash + holdings * p_open,
            })

        # End of hour mark to market at close
        eq = cash + holdings * p_close
        equities[i] = eq
        cash_hist[i] = cash
        holdings_hist[i] = holdings
        weights_hist[i] = (holdings * p_close) / eq if eq > 0 else 0.0

    eq_series = pd.Series(equities, index=timeline)
    cash_s = pd.Series(cash_hist, index=timeline)
    holdings_s = pd.Series(holdings_hist, index=timeline)
    weights_s = pd.Series(weights_hist, index=timeline)
    turnover_s = pd.Series(turnovers, index=timeline)
    fees_s = pd.Series(fees, index=timeline)

    # Compute standardized metrics via canonical compute_performance_metrics
    metrics = compute_performance_metrics(
        equities=equities,
        cash_history=cash_hist,
        turnovers=turnovers,
        fees=fees,
        trade_events=trade_events,
        start_dt=start_dt,
        end_dt=end_dt,
        initial_capital=initial_capital,
        timestamps=list(timeline),
    )

    return TrackAReplayResult(
        policy_name="LEARNED_POLICY_V1",
        fee_bps=fee_bps,
        no_trade_band=no_trade_band,
        start_dt=start_dt,
        end_dt=end_dt,
        timestamps=list(timeline),
        equities=equities,
        cash_history=cash_hist,
        btc_holdings_history=holdings_hist,
        btc_weights_history=weights_hist,
        turnovers=turnovers,
        fees=fees,
        trade_events=trade_events,
        metrics=metrics,
        decision_ledger=decision_ledger,
    )


def verify_trade_events_accounting(
    trade_events: list[dict[str, Any]],
    turnovers: np.ndarray,
    fees: np.ndarray,
    metrics: StrategyMetrics,
    fee_bps: float = 30.0,
    tolerance: float = 1e-4,
) -> dict[str, Any]:
    """Verify total notional, fees, and exact capital conservation from actual trade events."""
    fee_rate = fee_bps / 10000.0
    conservation_errors = []
    fee_errors = []

    total_event_notional = 0.0
    total_event_fees = 0.0

    for idx, event in enumerate(trade_events):
        v_pre = event.get("v_pre", 0.0)
        v_post = event.get("v_post", 0.0)
        fee = event.get("fee", 0.0)
        trade_notional = event.get("trade_notional", event.get("traded_notional", 0.0))
        post_cash = event.get("post_cash", 0.0)

        total_event_notional += trade_notional
        total_event_fees += fee

        # 1. Capital conservation: V_post == V_pre - fee
        diff_conservation = abs(v_post - (v_pre - fee))
        if diff_conservation > tolerance:
            conservation_errors.append(
                f"Event {idx} ({event.get('ts')}): V_post ({v_post:.4f}) != V_pre - fee ({v_pre - fee:.4f}), diff={diff_conservation:.6f}"
            )

        # 2. Fee formula: fee == fee_rate * trade_notional
        expected_fee = trade_notional * fee_rate
        diff_fee = abs(fee - expected_fee)
        if diff_fee > tolerance:
            fee_errors.append(
                f"Event {idx} ({event.get('ts')}): fee ({fee:.4f}) != fee_rate * notional ({expected_fee:.4f}), diff={diff_fee:.6f}"
            )

        # 3. Solvency: post_cash >= -1e-6
        if post_cash < -tolerance:
            conservation_errors.append(f"Event {idx}: negative cash {post_cash}")

    # Check aggregate reconciliation
    sum_fees_arr = float(np.sum(fees))
    diff_total_fees = abs(total_event_fees - sum_fees_arr)
    diff_metrics_fees = abs(metrics.total_fees - total_event_fees)
    diff_metrics_notional = abs(metrics.total_traded_notional - total_event_notional)

    all_passed = bool(
        len(conservation_errors) == 0
        and len(fee_errors) == 0
        and diff_total_fees <= tolerance
        and diff_metrics_fees <= tolerance
        and diff_metrics_notional <= tolerance
    )

    return {
        "passed": all_passed,
        "conservation_errors": conservation_errors,
        "fee_errors": fee_errors,
        "total_event_notional": total_event_notional,
        "metrics_total_traded_notional": metrics.total_traded_notional,
        "total_event_fees": total_event_fees,
        "metrics_total_fees": metrics.total_fees,
    }


def run_static_50_50_replay(
    btc_hourly: pd.DataFrame,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    initial_capital: float = PRIMARY_INITIAL_CAPITAL,
    fee_bps: float = 30.0,
) -> TrackAReplayResult:
    """Run BTC 50% / Cash 50% static benchmark (initial purchase at 01:00 UTC, never rebalanced)."""
    fee_rate = fee_bps / 10000.0
    timeline = btc_hourly.loc[start_dt:end_dt].index
    n_bars = len(timeline)

    equities = np.empty(n_bars, dtype=float)
    cash_hist = np.empty(n_bars, dtype=float)
    holdings_hist = np.empty(n_bars, dtype=float)
    weights_hist = np.empty(n_bars, dtype=float)
    turnovers = np.zeros(n_bars, dtype=float)
    fees = np.zeros(n_bars, dtype=float)

    cash = float(initial_capital)
    holdings = 0.0
    trade_events: list[dict[str, Any]] = []

    opens_arr = btc_hourly.loc[timeline, "open"].to_numpy(dtype=float)
    closes_arr = btc_hourly.loc[timeline, "close"].to_numpy(dtype=float)

    incepted = False

    for i in range(n_bars):
        ts = timeline[i]
        p_open = opens_arr[i]
        p_close = closes_arr[i]

        # Initial allocation at first 01:00 UTC bar
        if not incepted and ts.hour == 1:
            v_pre = cash
            v_post, realized_fee = solve_post_fee_equity(
                v_pre, np.array([0.0]), np.array([0.50]), fee_rate
            )
            target_btc_notional = 0.50 * v_post
            traded_notional = target_btc_notional
            holdings = target_btc_notional / p_open
            cash = 0.50 * v_post

            turnovers[i] = traded_notional / v_pre if v_pre > 0 else 0.0
            fees[i] = realized_fee

            trade_events.append({
                "ts": ts,
                "execution_timestamp": ts.isoformat(),
                "action": "INITIAL_ALLOCATION",
                "price": p_open,
                "p_exec": p_open,
                "trade_notional": traded_notional,
                "traded_notional": traded_notional,
                "fee": realized_fee,
                "v_pre": v_pre,
                "post_cash": cash,
                "post_holdings": holdings,
                "v_post": v_post,
            })
            incepted = True

        eq = cash + holdings * p_close
        equities[i] = eq
        cash_hist[i] = cash
        holdings_hist[i] = holdings
        weights_hist[i] = (holdings * p_close) / eq if eq > 0 else 0.0

    metrics = compute_performance_metrics(
        equities=equities,
        cash_history=cash_hist,
        turnovers=turnovers,
        fees=fees,
        trade_events=trade_events,
        start_dt=start_dt,
        end_dt=end_dt,
        initial_capital=initial_capital,
        timestamps=list(timeline),
    )

    return TrackAReplayResult(
        policy_name="BTC_50_50_STATIC",
        fee_bps=fee_bps,
        no_trade_band=0.0,
        start_dt=start_dt,
        end_dt=end_dt,
        timestamps=list(timeline),
        equities=equities,
        cash_history=cash_hist,
        btc_holdings_history=holdings_hist,
        btc_weights_history=weights_hist,
        turnovers=turnovers,
        fees=fees,
        trade_events=trade_events,
        metrics=metrics,
        decision_ledger=[],
    )


def run_rebalanced_50_50_replay(
    btc_hourly: pd.DataFrame,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    initial_capital: float = PRIMARY_INITIAL_CAPITAL,
    fee_bps: float = 30.0,
    rebalance_band: float = 0.05,
) -> TrackAReplayResult:
    """Run BTC 50% / Cash 50% periodic rebalanced benchmark (rebalance when |w - 0.50| > 0.05 at 01:00 UTC)."""
    fee_rate = fee_bps / 10000.0
    timeline = btc_hourly.loc[start_dt:end_dt].index
    n_bars = len(timeline)

    equities = np.empty(n_bars, dtype=float)
    cash_hist = np.empty(n_bars, dtype=float)
    holdings_hist = np.empty(n_bars, dtype=float)
    weights_hist = np.empty(n_bars, dtype=float)
    turnovers = np.zeros(n_bars, dtype=float)
    fees = np.zeros(n_bars, dtype=float)

    cash = float(initial_capital)
    holdings = 0.0
    trade_events: list[dict[str, Any]] = []

    opens_arr = btc_hourly.loc[timeline, "open"].to_numpy(dtype=float)
    closes_arr = btc_hourly.loc[timeline, "close"].to_numpy(dtype=float)

    incepted = False

    for i in range(n_bars):
        ts = timeline[i]
        p_open = opens_arr[i]
        p_close = closes_arr[i]

        if ts.hour == 1:
            if not incepted:
                # Inception allocation to 50% BTC
                v_pre = cash
                v_post, realized_fee = solve_post_fee_equity(
                    v_pre, np.array([0.0]), np.array([0.50]), fee_rate
                )
                target_btc_notional = 0.50 * v_post
                traded_notional = target_btc_notional
                holdings = target_btc_notional / p_open
                cash = 0.50 * v_post

                turnovers[i] = traded_notional / v_pre if v_pre > 0 else 0.0
                fees[i] = realized_fee

                trade_events.append({
                    "ts": ts,
                    "execution_timestamp": ts.isoformat(),
                    "action": "INITIAL_ALLOCATION",
                    "price": p_open,
                    "p_exec": p_open,
                    "trade_notional": traded_notional,
                    "traded_notional": traded_notional,
                    "fee": realized_fee,
                    "v_pre": v_pre,
                    "post_cash": cash,
                    "post_holdings": holdings,
                    "v_post": v_post,
                })
                incepted = True
            else:
                # Check rebalance condition
                pre_btc_notional = holdings * p_open
                v_pre = cash + pre_btc_notional
                current_w = pre_btc_notional / v_pre if v_pre > 0 else 0.0
                deviation = abs(0.50 - current_w)

                if deviation > rebalance_band:
                    v_post, realized_fee = solve_post_fee_equity(
                        v_pre, np.array([pre_btc_notional]), np.array([0.50]), fee_rate
                    )
                    target_btc_notional = 0.50 * v_post
                    traded_notional = abs(target_btc_notional - pre_btc_notional)
                    holdings = target_btc_notional / p_open
                    cash = 0.50 * v_post

                    turnovers[i] = traded_notional / v_pre if v_pre > 0 else 0.0
                    fees[i] = realized_fee

                    trade_events.append({
                        "ts": ts,
                        "execution_timestamp": ts.isoformat(),
                        "action": "REBALANCE_50_50",
                        "price": p_open,
                        "p_exec": p_open,
                        "trade_notional": traded_notional,
                        "traded_notional": traded_notional,
                        "fee": realized_fee,
                        "v_pre": v_pre,
                        "post_cash": cash,
                        "post_holdings": holdings,
                        "v_post": v_post,
                    })

        eq = cash + holdings * p_close
        equities[i] = eq
        cash_hist[i] = cash
        holdings_hist[i] = holdings
        weights_hist[i] = (holdings * p_close) / eq if eq > 0 else 0.0

    metrics = compute_performance_metrics(
        equities=equities,
        cash_history=cash_hist,
        turnovers=turnovers,
        fees=fees,
        trade_events=trade_events,
        start_dt=start_dt,
        end_dt=end_dt,
        initial_capital=initial_capital,
        timestamps=list(timeline),
    )

    return TrackAReplayResult(
        policy_name="BTC_50_50_REBALANCED",
        fee_bps=fee_bps,
        no_trade_band=rebalance_band,
        start_dt=start_dt,
        end_dt=end_dt,
        timestamps=list(timeline),
        equities=equities,
        cash_history=cash_hist,
        btc_holdings_history=holdings_hist,
        btc_weights_history=weights_hist,
        turnovers=turnovers,
        fees=fees,
        trade_events=trade_events,
        metrics=metrics,
        decision_ledger=[],
    )
