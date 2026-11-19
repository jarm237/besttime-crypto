"""Track B1 — Regime-Conditioned Capital Allocation.

Implements:
1. Causal Point-in-Time feature extraction for Track B1:
   - base_weight: Frozen Track A approved exposure
   - trend_90d: BTC 90-day log return
   - downside_risk_30d: BTC 30-day realized downside volatility (semi-deviation)
   - breadth_30d: Multi-asset breadth (fraction of ETH, SOL, BNB with positive 30d returns)
2. Normalization scaler fit strictly on Train (2022-2023).
3. Monotonic RegimeConditionedAllocationHead:
   risk_gate = sigmoid(bias + c_trend*trend - c_risk*risk + c_breadth*breadth)
   capital_multiplier = 0.5 + risk_gate in [0.5, 1.5]
   target_btc_weight = clip(base_weight * capital_multiplier, 0.0, 1.0)
4. Bounded training with strict boundary label purging (no lookahead into next split).
5. Exact hourly economic replay with solve_post_fee_equity and 5% deadband.
6. Constant-multiplier Track A benchmark with multiplier derived strictly from Train.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import AdamW

from btc_scraper.research.learned_policy_v1 import (
    SPLIT_WINDOWS,
    compute_holding_period_returns,
    verify_trade_events_accounting,
)
from btc_scraper.research.track_a_strategy import (
    PRIMARY_INITIAL_CAPITAL,
    DailySignalRecord,
    TrackAReplayResult,
    compute_performance_metrics,
    solve_post_fee_equity,
)

TRACK_B_OUTPUT_DIR = Path("research/track_b/conditional_allocation_v1")


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


def extract_track_b1_features(
    panels: Mapping[str, pd.DataFrame],
    track_a_signals: Mapping[pd.Timestamp, DailySignalRecord],
) -> pd.DataFrame:
    """Extract Point-in-Time causal features for Track B1 decision on Day D at 00:00 UTC.

    Decision on Day D (00:00 UTC) ONLY observes closed daily candles up to Day D-1 (23:59:59 UTC).

    Features:
    - base_weight: Frozen Track A v1 approved exposure at Day D 00:00 UTC
    - trend_90d: BTC 90-day log return: ln(close_{D-1} / close_{D-91})
    - downside_risk_30d: BTC 30-day downside volatility (semi-deviation of negative log returns)
    - breadth_30d: Fraction of [ETH, SOL, BNB] with positive 30-day return at Day D-1
    """
    daily_panels = {s: build_daily_candles(panels[s]) for s in panels}
    btc = daily_panels["BTCUSDT"]
    eth = daily_panels["ETHUSDT"]
    sol = daily_panels["SOLUSDT"]
    bnb = daily_panels["BNBUSDT"]

    common_idx = btc.index.intersection(eth.index).intersection(sol.index).intersection(bnb.index)
    btc = btc.loc[common_idx]
    eth = eth.loc[common_idx]
    sol = sol.loc[common_idx]
    bnb = bnb.loc[common_idx]

    df = pd.DataFrame(index=common_idx)

    # 1. Base weight from Track A v1
    # track_a_signals is indexed by decision_dt (Day D 00:00 UTC)
    base_weights = []
    for dt in common_idx:
        sig = track_a_signals.get(dt)
        base_weights.append(sig.approved_exposure if sig is not None else 0.0)
    df["base_weight"] = base_weights

    # 2. BTC 90-day log return: ln(close_{D-1} / close_{D-91})
    # Shift by 1 so Day D observes Day D-1
    btc_close = btc["close"]
    btc_log_ret_90 = np.log(btc_close / btc_close.shift(90))
    df["trend_90d"] = btc_log_ret_90.shift(1)

    # 3. BTC 30-day downside volatility: semi-deviation of negative daily log returns
    btc_daily_log_ret = np.log(btc_close / btc_close.shift(1))
    neg_daily_log_ret = btc_daily_log_ret.clip(upper=0.0)
    # 30-day rolling root-mean-square of negative returns
    downside_vol_30d = np.sqrt((neg_daily_log_ret ** 2).rolling(30).mean())
    df["downside_risk_30d"] = downside_vol_30d.shift(1)

    # 4. Multi-asset breadth: fraction of altcoins with positive 30d return
    eth_ret_30 = (eth["close"] / eth["close"].shift(30) - 1.0).shift(1)
    sol_ret_30 = (sol["close"] / sol["close"].shift(30) - 1.0).shift(1)
    bnb_ret_30 = (bnb["close"] / bnb["close"].shift(30) - 1.0).shift(1)

    breadth_30d = (
        (eth_ret_30 > 0.0).astype(float)
        + (sol_ret_30 > 0.0).astype(float)
        + (bnb_ret_30 > 0.0).astype(float)
    ) / 3.0
    df["breadth_30d"] = breadth_30d

    # Drop early warmup rows containing NaN from lookbacks
    df = df.dropna()
    return df


class TrackB1Scaler:
    """Scaler fitted strictly on Train slice (2022-2023) for regime features."""

    FEATURE_COLS = ["trend_90d", "downside_risk_30d", "breadth_30d"]

    def __init__(self):
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None

    def fit(self, train_df: pd.DataFrame) -> TrackB1Scaler:
        X = train_df[self.FEATURE_COLS].to_numpy(dtype=np.float32)
        self.mean_ = np.nanmean(X, axis=0)
        std = np.nanstd(X, axis=0)
        self.scale_ = np.where(std > 1e-6, std, 1.0)
        return self

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        if self.mean_ is None or self.scale_ is None:
            raise RuntimeError("TrackB1Scaler must be fit before transform.")
        X = df[self.FEATURE_COLS].to_numpy(dtype=np.float32)
        return (X - self.mean_) / self.scale_

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_names": self.FEATURE_COLS,
            "mean": self.mean_.tolist() if self.mean_ is not None else [],
            "scale": self.scale_.tolist() if self.scale_ is not None else [],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrackB1Scaler:
        scaler = cls()
        scaler.mean_ = np.array(data["mean"], dtype=np.float32)
        scaler.scale_ = np.array(data["scale"], dtype=np.float32)
        return scaler


class RegimeConditionedAllocationHead(nn.Module):
    """Conditional allocation head enforcing monotonic domain relations.

    risk_gate = sigmoid(
        bias
        + positive_trend_coef * norm_trend
        - positive_risk_coef * norm_downside_risk
        + positive_breadth_coef * norm_breadth
    )
    capital_multiplier = 0.5 + risk_gate  # ranges in (0.5, 1.5)
    target_btc_weight = clip(base_weight * capital_multiplier, 0.0, 1.0)
    """

    def __init__(self):
        super().__init__()
        self.bias = nn.Parameter(torch.tensor(0.0, dtype=torch.float32))
        # Initial raw parameters so that softplus(raw) ~ 1.0 (raw = 0.54132485)
        init_raw = 0.54132485
        self.raw_trend_coef = nn.Parameter(torch.tensor(init_raw, dtype=torch.float32))
        self.raw_risk_coef = nn.Parameter(torch.tensor(init_raw, dtype=torch.float32))
        self.raw_breadth_coef = nn.Parameter(torch.tensor(init_raw, dtype=torch.float32))

    @property
    def positive_trend_coef(self) -> torch.Tensor:
        return F.softplus(self.raw_trend_coef)

    @property
    def positive_risk_coef(self) -> torch.Tensor:
        return F.softplus(self.raw_risk_coef)

    @property
    def positive_breadth_coef(self) -> torch.Tensor:
        return F.softplus(self.raw_breadth_coef)

    def forward(
        self,
        norm_trend: torch.Tensor,
        norm_risk: torch.Tensor,
        norm_breadth: torch.Tensor,
        base_weight: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Compute target_btc_weight, risk_gate, and capital_multiplier.

        Tensors can be shaped (N, 1) or (N,).
        """
        logit = (
            self.bias
            + self.positive_trend_coef * norm_trend
            - self.positive_risk_coef * norm_risk
            + self.positive_breadth_coef * norm_breadth
        )
        risk_gate = torch.sigmoid(logit)
        capital_multiplier = 0.5 + risk_gate
        target_btc_weight = torch.clamp(base_weight * capital_multiplier, 0.0, 1.0)
        return target_btc_weight, risk_gate, capital_multiplier


def b1_differentiable_rollout(
    model: RegimeConditionedAllocationHead,
    norm_trend: torch.Tensor,
    norm_risk: torch.Tensor,
    norm_breadth: torch.Tensor,
    base_weights: torch.Tensor,
    forward_returns: torch.Tensor,
    fee_rate: float = 0.0030,
    downside_lambda: float = 2.0,
    turnover_lambda: float = 0.05,
) -> tuple[torch.Tensor, dict[str, float]]:
    """Differentiable causal rollout of conditional allocation head."""
    T = len(base_weights)
    prev_w = torch.tensor(0.0, dtype=torch.float32, device=base_weights.device)

    log_returns = []
    turnovers = []
    downside_penalties = []
    multipliers = []

    for t in range(T):
        target_w, risk_gate, cap_mult = model(
            norm_trend[t], norm_risk[t], norm_breadth[t], base_weights[t]
        )
        multipliers.append(cap_mult)

        turnover = torch.abs(target_w - prev_w)
        turnovers.append(turnover)

        fwd_ret = forward_returns[t]
        net_ret = target_w * fwd_ret - fee_rate * turnover

        net_ret_safe = torch.clamp(net_ret, min=-0.95)
        log_ret = torch.log(1.0 + net_ret_safe)
        log_returns.append(log_ret)

        downside = torch.relu(-net_ret) ** 2
        downside_penalties.append(downside)

        prev_w = target_w.detach()

    total_growth = torch.sum(torch.stack(log_returns))
    total_downside = torch.sum(torch.stack(downside_penalties))
    total_turnover = torch.sum(torch.stack(turnovers))

    loss = -(total_growth - downside_lambda * total_downside - turnover_lambda * total_turnover)

    metrics = {
        "loss": float(loss.item()),
        "total_growth": float(total_growth.item()),
        "total_downside": float(total_downside.item()),
        "total_turnover": float(total_turnover.item()),
        "mean_multiplier": float(torch.mean(torch.stack(multipliers)).item()),
    }
    return loss, metrics


def train_track_b1_policy(
    features_df: pd.DataFrame,
    fwd_returns_s: pd.Series,
    scaler: TrackB1Scaler,
    train_start: str = "2022-01-01",
    train_end: str = "2023-12-31",
    val_start: str = "2024-01-01",
    val_end: str = "2024-12-31",
    seed: int = 42,
    epochs: int = 80,
    lr: float = 1e-3,
) -> tuple[RegimeConditionedAllocationHead, dict[str, Any]]:
    """Train Track B1 conditional allocation head with strict label boundary purging."""
    torch.manual_seed(seed)
    np.random.seed(seed)

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

    # Train dates purged so next execution does not cross into Validation (last: 2023-12-30)
    train_dates = [
        d for d in common_idx
        if (d >= train_start_ts) and (d <= train_end_boundary) and ((d + pd.Timedelta(days=1, hours=1)) <= train_end_boundary)
    ]

    # Validation selection dates purged so next execution does not cross into Reused Test (last: 2024-12-30)
    val_dates = [
        d for d in common_idx
        if (d >= val_start_ts) and (d <= val_end_boundary) and ((d + pd.Timedelta(days=1, hours=1)) <= val_end_boundary)
    ]

    # Normalized features
    train_norm = scaler.transform(features_df.loc[train_dates])
    val_norm = scaler.transform(features_df.loc[val_dates])

    t_tr_trend = torch.tensor(train_norm[:, 0], dtype=torch.float32)
    t_tr_risk = torch.tensor(train_norm[:, 1], dtype=torch.float32)
    t_tr_breadth = torch.tensor(train_norm[:, 2], dtype=torch.float32)
    t_tr_base = torch.tensor(features_df.loc[train_dates, "base_weight"].to_numpy(dtype=np.float32), dtype=torch.float32)
    t_tr_fwd = torch.tensor(fwd_returns_s.loc[train_dates].to_numpy(dtype=np.float32), dtype=torch.float32)

    t_val_trend = torch.tensor(val_norm[:, 0], dtype=torch.float32)
    t_val_risk = torch.tensor(val_norm[:, 1], dtype=torch.float32)
    t_val_breadth = torch.tensor(val_norm[:, 2], dtype=torch.float32)
    t_val_base = torch.tensor(features_df.loc[val_dates, "base_weight"].to_numpy(dtype=np.float32), dtype=torch.float32)
    t_val_fwd = torch.tensor(fwd_returns_s.loc[val_dates].to_numpy(dtype=np.float32), dtype=torch.float32)

    model = RegimeConditionedAllocationHead()
    optimizer = AdamW(model.parameters(), lr=lr, weight_decay=1e-4)

    best_val_growth = -float("inf")
    best_weights: dict[str, Any] | None = None
    best_epoch = 0

    history = []

    for epoch in range(1, epochs + 1):
        model.train()
        optimizer.zero_grad()
        loss, tr_m = b1_differentiable_rollout(
            model, t_tr_trend, t_tr_risk, t_tr_breadth, t_tr_base, t_tr_fwd
        )
        loss.backward()
        optimizer.step()

        model.eval()
        with torch.no_grad():
            val_loss, val_m = b1_differentiable_rollout(
                model, t_val_trend, t_val_risk, t_val_breadth, t_val_base, t_val_fwd
            )

        val_growth = val_m["total_growth"]
        history.append({
            "epoch": epoch,
            "train_loss": tr_m["loss"],
            "train_growth": tr_m["total_growth"],
            "val_loss": val_m["loss"],
            "val_growth": val_m["total_growth"],
            "val_turnover": val_m["total_turnover"],
            "val_mean_multiplier": val_m["mean_multiplier"],
            "coef_trend": float(model.positive_trend_coef.item()),
            "coef_risk": float(model.positive_risk_coef.item()),
            "coef_breadth": float(model.positive_breadth_coef.item()),
            "bias": float(model.bias.item()),
        })

        if val_growth > best_val_growth:
            best_val_growth = val_growth
            best_weights = {k: v.clone() for k, v in model.state_dict().items()}
            best_epoch = epoch

    if best_weights is not None:
        model.load_state_dict(best_weights)

    model.eval()
    meta = {
        "best_epoch": best_epoch,
        "best_val_growth": best_val_growth,
        "history": history,
        "seed": seed,
        "train_samples_count": len(train_dates),
        "val_samples_count": len(val_dates),
        "train_last_date": str(train_dates[-1].date()) if train_dates else None,
        "val_last_date": str(val_dates[-1].date()) if val_dates else None,
        "learned_bias": float(model.bias.item()),
        "learned_coef_trend": float(model.positive_trend_coef.item()),
        "learned_coef_risk": float(model.positive_risk_coef.item()),
        "learned_coef_breadth": float(model.positive_breadth_coef.item()),
    }
    return model, meta


def run_track_b1_replay(
    btc_hourly: pd.DataFrame,
    features_df: pd.DataFrame,
    scaler: TrackB1Scaler,
    model: RegimeConditionedAllocationHead,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    initial_capital: float = PRIMARY_INITIAL_CAPITAL,
    fee_bps: float = 30.0,
    no_trade_band: float = 0.05,
) -> TrackAReplayResult:
    """Run exact stateful hourly economic replay of Track B1 policy using solve_post_fee_equity."""
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
    model.eval()

    for i in range(n_bars):
        ts = timeline[i]
        p_open = opens_arr[i]
        p_close = closes_arr[i]

        # Execution clock: evaluate decision at 01:00 UTC (decision cutoff 00:00 UTC)
        if ts.hour == 1:
            decision_date = ts.floor("D")
            if decision_date in features_df.index:
                row = features_df.loc[[decision_date]]
                norm_feat = scaler.transform(row)
                base_w = float(row["base_weight"].iloc[0])

                with torch.no_grad():
                    t_w, r_gate, c_mult = model(
                        torch.tensor(norm_feat[0, 0], dtype=torch.float32),
                        torch.tensor(norm_feat[0, 1], dtype=torch.float32),
                        torch.tensor(norm_feat[0, 2], dtype=torch.float32),
                        torch.tensor(base_w, dtype=torch.float32),
                    )
                    target_w = float(t_w.item())
                    risk_gate = float(r_gate.item())
                    cap_mult = float(c_mult.item())
            else:
                target_w = prev_target_w
                risk_gate = 0.5
                cap_mult = 1.0

            # Pre-trade mark to market at 01:00 UTC bar open
            pre_btc_notional = holdings * p_open
            v_pre = cash + pre_btc_notional
            current_w = (pre_btc_notional / v_pre) if v_pre > 0 else 0.0
            deviation = abs(target_w - current_w)

            action = "HOLD"
            realized_fee = 0.0
            traded_notional = 0.0

            # Execute rebalance if deviation > 5% band
            if deviation > no_trade_band:
                action = "REBALANCE_B1"
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
                    "v_pre": v_pre,
                    "post_cash": cash,
                    "post_holdings": holdings,
                    "v_post": v_post,
                    "capital_multiplier": cap_mult,
                    "risk_gate": risk_gate,
                })
                prev_target_w = target_w

            decision_ledger.append({
                "ts": ts,
                "execution_timestamp": ts.isoformat(),
                "p_open": p_open,
                "base_weight": base_w if decision_date in features_df.index else 0.0,
                "capital_multiplier": cap_mult,
                "risk_gate": risk_gate,
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

        # Mark to market at candle close
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
        policy_name="TRACK_B1_CONDITIONAL",
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


def compute_train_constant_multiplier(
    features_df: pd.DataFrame,
    scaler: TrackB1Scaler,
    model: RegimeConditionedAllocationHead,
    train_start: str = "2022-01-01",
    train_end: str = "2023-12-31",
) -> float:
    """Determine the constant exposure multiplier strictly from Train (2022-2023)."""
    train_mask = (features_df.index >= train_start) & (features_df.index <= train_end)
    train_sub = features_df.loc[train_mask]
    norm_feat = scaler.transform(train_sub)

    model.eval()
    with torch.no_grad():
        _, _, cap_mults = model(
            torch.tensor(norm_feat[:, 0], dtype=torch.float32),
            torch.tensor(norm_feat[:, 1], dtype=torch.float32),
            torch.tensor(norm_feat[:, 2], dtype=torch.float32),
            torch.tensor(train_sub["base_weight"].to_numpy(dtype=np.float32), dtype=torch.float32),
        )
        const_mult = float(torch.mean(cap_mults).item())
    return const_mult


def run_constant_multiplier_track_a_replay(
    btc_hourly: pd.DataFrame,
    track_a_signals: Mapping[pd.Timestamp, DailySignalRecord],
    constant_multiplier: float,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    initial_capital: float = PRIMARY_INITIAL_CAPITAL,
    fee_bps: float = 30.0,
    no_trade_band: float = 0.05,
) -> TrackAReplayResult:
    """Run Track A with constant multiplier derived strictly from Train to isolate exposure timing."""
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

    for i in range(n_bars):
        ts = timeline[i]
        p_open = opens_arr[i]
        p_close = closes_arr[i]

        if ts.hour == 1:
            decision_date = ts.floor("D")
            sig = track_a_signals.get(decision_date)
            base_w = sig.approved_exposure if sig is not None else 0.0
            target_w = float(np.clip(base_w * constant_multiplier, 0.0, 1.0))

            pre_btc_notional = holdings * p_open
            v_pre = cash + pre_btc_notional
            current_w = (pre_btc_notional / v_pre) if v_pre > 0 else 0.0
            deviation = abs(target_w - current_w)

            action = "HOLD"
            realized_fee = 0.0
            traded_notional = 0.0

            if deviation > no_trade_band:
                action = "REBALANCE_CONST_TRACK_A"
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
                    "v_pre": v_pre,
                    "post_cash": cash,
                    "post_holdings": holdings,
                    "v_post": v_post,
                    "constant_multiplier": constant_multiplier,
                })
                prev_target_w = target_w

            decision_ledger.append({
                "ts": ts,
                "execution_timestamp": ts.isoformat(),
                "p_open": p_open,
                "base_weight": base_w,
                "constant_multiplier": constant_multiplier,
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
        policy_name="CONSTANT_MULTIPLIER_TRACK_A",
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
