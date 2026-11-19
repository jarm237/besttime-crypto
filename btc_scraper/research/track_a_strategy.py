"""Track A v1: Profit-First Multi-Horizon Trend Following Strategy & Replay Engine.

Specification:
- Trading Universe: BTCUSDT (Binance Spot) + CASH (USDT nominal, 0% yield).
- Lookback Horizons: 20, 55, 90 daily candles.
- Daily Donchian Channel: upper = max(high[j-N:j]), lower = min(low[j-N:j]), strictly excluding candle j.
- State Transition: 1 if close[j] > upper, 0 if close[j] < lower, else previous_state.
- Raw Exposure: sum(states) / 3.0 (0%, 33.33%, 66.67%, 100%).
- Two-Day Confirmation: target approved only if raw exposure matches across 2 consecutive completed daily candles.
- No-Trade Buffer: 20 percentage points (0.20) deviation threshold vs drifted pre-trade BTC weight.
- Execution Clock: Decision at 00:00 UTC (cutoff D-1), Execution at 01:00 UTC at hourly open.
- Realistic Fee Accounting: Reuses solve_post_fee_equity from S5 economic replay.
"""
from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from btc_scraper.research.s4_dataset_audit import BINANCE_COLUMNS, UNIVERSE
from btc_scraper.research.s5_economic_replay import (
    PRIMARY_INITIAL_CAPITAL,
    ReplayError,
    compute_market_trend_168h,
    solve_post_fee_equity,
)

LOOKBACK_HORIZONS = (20, 55, 90)
TRACK_A_NO_TRADE_BAND = 0.20
S5_NO_TRADE_BAND = 0.05


@dataclass
class DailySignalRecord:
    decision_dt: pd.Timestamp
    candle_dt: pd.Timestamp
    close_price: float
    state_20: int
    state_55: int
    state_90: int
    raw_exposure: float
    approved_exposure: float
    confirmed: bool


@dataclass
class StrategyMetrics:
    net_pnl: float
    cagr: float
    cum_return: float
    max_drawdown: float
    calmar: float
    sharpe: float
    annualized_turnover: float
    total_traded_notional: float
    total_fees: float
    avg_btc_exposure: float
    avg_cash_exposure: float
    num_trades: int
    worst_month_net_return: float
    final_equity: float


@dataclass
class TrackAReplayResult:
    policy_name: str
    fee_bps: float
    no_trade_band: float
    start_dt: pd.Timestamp
    end_dt: pd.Timestamp
    timestamps: list[pd.Timestamp]
    equities: np.ndarray
    cash_history: np.ndarray
    btc_holdings_history: np.ndarray
    btc_weights_history: np.ndarray
    turnovers: np.ndarray
    fees: np.ndarray
    trade_events: list[dict[str, Any]]
    metrics: StrategyMetrics
    decision_ledger: list[dict[str, Any]]


def normalize_candle_row(r: Sequence[str]) -> list[Any]:
    raw_ts = int(r[0])
    scale = 1000 if raw_ts > 3e14 else 1
    ts_ms = raw_ts // scale
    raw_close_ts = int(r[6])
    close_ts_ms = raw_close_ts // scale
    return [
        ts_ms,
        float(r[1]),
        float(r[2]),
        float(r[3]),
        float(r[4]),
        float(r[5]),
        close_ts_ms,
        float(r[7]),
        int(r[8]),
        float(r[9]),
        float(r[10]),
        int(r[11]) if len(r) > 11 else 0,
    ]


def load_coin_hourly_panel(repo_root: Path, symbol: str) -> pd.DataFrame:
    """Load continuous normalized 1h panel for symbol from 2021 to 2026-11-18."""
    raw_1h_root = repo_root / "data/historical/neural_n1/raw/binance_spot_klines_1h" / symbol
    fresh_root = repo_root / "data/fresh_training_data_2023_2026"
    holdout_root = repo_root / "data/historical/raw/holdout_spot" / symbol
    coin_code = symbol.replace("USDT", "")

    rows: list[list[Any]] = []

    # 1. Raw archives 2021 to 2025
    zips = sorted([
        z for z in raw_1h_root.glob(f"{symbol}-1h-*.zip")
        if re.search(r"-(\d{4})-\d{2}\.zip$", z.name) and int(re.search(r"-(\d{4})-\d{2}\.zip$", z.name).group(1)) >= 2021
    ])
    for z in zips:
        with zipfile.ZipFile(z, "r") as zf:
            cname = [n for n in zf.namelist() if n.endswith(".csv")][0]
            with zf.open(cname) as f:
                rdr = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
                for r in rdr:
                    try:
                        int(r[0])
                        rows.append(normalize_candle_row(r))
                    except ValueError:
                        pass

    # 2. Fresh training data 2026-01 to 2026-06
    fresh_dir = fresh_root / coin_code / "1h"
    if fresh_dir.exists():
        for fp in sorted(fresh_dir.glob(f"{coin_code}_1h_2026-*.csv")):
            df = pd.read_csv(fp)
            df_non_warmup = df[df["is_warmup"] == 0] if "is_warmup" in df.columns else df
            dts = pd.to_datetime(df_non_warmup["time"], utc=True)
            raw_int = dts.astype(np.int64).to_numpy()
            ts_ms = np.where(raw_int > 3e14, raw_int // 1000, raw_int)
            for idx in range(len(df_non_warmup)):
                rows.append([
                    int(ts_ms[idx]),
                    float(df_non_warmup["open"].iloc[idx]),
                    float(df_non_warmup["high"].iloc[idx]),
                    float(df_non_warmup["low"].iloc[idx]),
                    float(df_non_warmup["close"].iloc[idx]),
                    float(df_non_warmup["volume"].iloc[idx]),
                    int(ts_ms[idx] + 3599999),
                    0.0, 0, 0.0, 0.0, 0,
                ])

    # 3. Holdout 2026 H2 (2026-07 to 2026-11-18)
    if holdout_root.exists():
        for z in sorted(holdout_root.glob(f"{symbol}-1h-*.zip")):
            with zipfile.ZipFile(z, "r") as zf:
                cname = [n for n in zf.namelist() if n.endswith(".csv")][0]
                with zf.open(cname) as f:
                    rdr = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
                    for r in rdr:
                        try:
                            int(r[0])
                            rows.append(normalize_candle_row(r))
                        except ValueError:
                            pass

    df = pd.DataFrame(rows, columns=BINANCE_COLUMNS)
    df["open_time_ms"] = df["open_time_ms"].astype(np.int64)
    df = df.drop_duplicates(subset=["open_time_ms"]).sort_values("open_time_ms").reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["open_time_ms"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df.set_index("dt", inplace=True)
    return df


def load_universe_panels(repo_root: Path) -> dict[str, pd.DataFrame]:
    """Load panels for all 4 universe assets."""
    panels = {}
    for sym in UNIVERSE:
        panels[sym] = load_coin_hourly_panel(repo_root, sym)
    return panels


def build_btc_daily_candles(btc_hourly: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1h candles into complete UTC daily candles (00:00 to 23:59)."""
    daily = btc_hourly.resample("1D").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "open_time_ms": "count",
    }).rename(columns={"open_time_ms": "hour_count"})
    return daily[daily["hour_count"] > 0]


def compute_track_a_signals(btc_daily: pd.DataFrame) -> dict[pd.Timestamp, DailySignalRecord]:
    """Compute causal multi-horizon Donchian trend signals with 2-day confirmation.

    At day D (00:00 UTC), candle j = D - 1 has closed.
    Channel N lookback is computed over [j-N : j] (strictly excluding j).
    """
    dates = btc_daily.index.tolist()
    highs = btc_daily["high"].to_numpy()
    lows = btc_daily["low"].to_numpy()
    closes = btc_daily["close"].to_numpy()

    signals: dict[pd.Timestamp, DailySignalRecord] = {}

    state_20 = 0
    state_55 = 0
    state_90 = 0
    prev_raw = 0.0
    approved_exposure = 0.0

    # Start loop once we have at least 90 lookback bars
    for j in range(len(dates)):
        candle_dt = dates[j]
        decision_dt = candle_dt + pd.Timedelta(days=1)  # Next day 00:00 UTC

        if j < max(LOOKBACK_HORIZONS):
            # Warmup period before full 90-day channel can be formed
            # Keep state 0, but record if enough bars for smaller horizons
            if j >= 20:
                up_20 = np.max(highs[j-20:j])
                dn_20 = np.min(lows[j-20:j])
                c = closes[j]
                if c > up_20:
                    state_20 = 1
                elif c < dn_20:
                    state_20 = 0
            if j >= 55:
                up_55 = np.max(highs[j-55:j])
                dn_55 = np.min(lows[j-55:j])
                c = closes[j]
                if c > up_55:
                    state_55 = 1
                elif c < dn_55:
                    state_55 = 0
            signals[decision_dt] = DailySignalRecord(
                decision_dt=decision_dt,
                candle_dt=candle_dt,
                close_price=float(closes[j]),
                state_20=state_20,
                state_55=state_55,
                state_90=state_90,
                raw_exposure=0.0,
                approved_exposure=0.0,
                confirmed=True,
            )
            continue

        c = closes[j]

        # Horizon 20
        up_20 = np.max(highs[j-20:j])
        dn_20 = np.min(lows[j-20:j])
        if c > up_20:
            state_20 = 1
        elif c < dn_20:
            state_20 = 0

        # Horizon 55
        up_55 = np.max(highs[j-55:j])
        dn_55 = np.min(lows[j-55:j])
        if c > up_55:
            state_55 = 1
        elif c < dn_55:
            state_55 = 0

        # Horizon 90
        up_90 = np.max(highs[j-90:j])
        dn_90 = np.min(lows[j-90:j])
        if c > up_90:
            state_90 = 1
        elif c < dn_90:
            state_90 = 0

        raw_exp = (state_20 + state_55 + state_90) / 3.0

        # Two-day confirmation: raw exposure must match across 2 consecutive daily candles
        confirmed = (abs(raw_exp - prev_raw) < 1e-6)
        if confirmed:
            approved_exposure = raw_exp

        signals[decision_dt] = DailySignalRecord(
            decision_dt=decision_dt,
            candle_dt=candle_dt,
            close_price=float(c),
            state_20=state_20,
            state_55=state_55,
            state_90=state_90,
            raw_exposure=raw_exp,
            approved_exposure=approved_exposure,
            confirmed=confirmed,
        )

        prev_raw = raw_exp

    return signals


def compute_performance_metrics(
    equities: np.ndarray,
    cash_history: np.ndarray,
    turnovers: np.ndarray,
    fees: np.ndarray,
    trade_events: list[dict[str, Any]],
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
    initial_capital: float,
    timestamps: list[pd.Timestamp],
) -> StrategyMetrics:
    """Compute standard quantitative and economic performance metrics."""
    final_eq = float(equities[-1])
    net_pnl = final_eq - initial_capital
    cum_ret = (final_eq / initial_capital) - 1.0

    total_days = (end_dt - start_dt).total_seconds() / 86400.0
    years = max(total_days / 365.25, 0.001)

    if final_eq > 0:
        cagr = (final_eq / initial_capital) ** (1.0 / years) - 1.0
    else:
        cagr = -1.0

    # Max Drawdown
    peaks = np.maximum.accumulate(equities)
    dds = (equities - peaks) / np.where(peaks > 0, peaks, 1.0)
    max_dd = float(np.min(dds))  # negative float, e.g. -0.25

    # Hourly Sharpe annualized
    hourly_rets = np.diff(equities) / equities[:-1]
    # filter out nans or 0s
    hourly_rets = hourly_rets[~np.isnan(hourly_rets)]
    mean_h = float(np.mean(hourly_rets)) if len(hourly_rets) > 0 else 0.0
    std_h = float(np.std(hourly_rets, ddof=1)) if len(hourly_rets) > 1 else 0.0
    sharpe = (mean_h / std_h * math.sqrt(8760.0)) if std_h > 1e-12 else 0.0

    # Calmar ratio
    calmar = (cagr / abs(max_dd)) if abs(max_dd) > 1e-6 else 0.0

    # Turnover & Fees
    total_traded_notional = sum(t.get("trade_notional", 0.0) for t in trade_events)
    avg_equity = float(np.mean(equities)) if len(equities) > 0 else initial_capital
    annualized_turnover = (total_traded_notional / avg_equity) / years if avg_equity > 0 else 0.0
    total_fees = float(np.sum(fees))

    # Cash and BTC exposure
    btc_exposures = 1.0 - (cash_history / np.where(equities > 0, equities, 1.0))
    avg_btc_exp = float(np.mean(btc_exposures))
    avg_cash_exp = 1.0 - avg_btc_exp

    # Worst calendar month return
    df_m = pd.DataFrame({"equity": equities}, index=timestamps)
    monthly_eq = df_m["equity"].resample("ME").last()
    monthly_rets = monthly_eq.pct_change().dropna()
    worst_month = float(monthly_rets.min()) if len(monthly_rets) > 0 else 0.0

    return StrategyMetrics(
        net_pnl=net_pnl,
        cagr=cagr,
        cum_return=cum_ret,
        max_drawdown=max_dd,
        calmar=calmar,
        sharpe=sharpe,
        annualized_turnover=annualized_turnover,
        total_traded_notional=total_traded_notional,
        total_fees=total_fees,
        avg_btc_exposure=avg_btc_exp,
        avg_cash_exposure=avg_cash_exp,
        num_trades=len(trade_events),
        worst_month_net_return=worst_month,
        final_equity=final_eq,
    )


def run_track_a_replay(
    btc_hourly: pd.DataFrame,
    signals: dict[pd.Timestamp, DailySignalRecord],
    start_dt: pd.Timestamp = pd.Timestamp("2022-01-01 00:00:00", tz="UTC"),
    end_dt: pd.Timestamp = pd.Timestamp("2026-11-18 23:00:00", tz="UTC"),
    initial_capital: float = PRIMARY_INITIAL_CAPITAL,
    fee_bps: float = 30.0,
    no_trade_band: float = TRACK_A_NO_TRADE_BAND,
) -> TrackAReplayResult:
    """Run stateful fee-aware portfolio replay for Track A v1 Strategy."""
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

    for i in range(n_bars):
        ts = timeline[i]
        p_open = opens_arr[i]
        p_close = closes_arr[i]

        # Execution clock: Rebalance at 01:00 UTC if deviation > band
        if ts.hour == 1:
            decision_ts = ts.floor("D")  # Corresponding decision was at 00:00 UTC
            sig = signals.get(decision_ts)
            target_w = sig.approved_exposure if sig is not None else 0.0

            pre_btc_notional = holdings * p_open
            v_pre = cash + pre_btc_notional
            current_w = (pre_btc_notional / v_pre) if v_pre > 0 else 0.0
            deviation = abs(target_w - current_w)

            action = "HOLD"
            trade_notional = 0.0
            realized_fee = 0.0

            if deviation > no_trade_band:
                action = "REBALANCE"
                # Solve capital conservation: V_post = V_pre - fee_rate * |w*V_post - N_pre|
                current_notionals = np.array([pre_btc_notional])
                target_weights = np.array([target_w])
                v_post, realized_fee = solve_post_fee_equity(v_pre, current_notionals, target_weights, fee_rate)

                target_notional = target_w * v_post
                trade_notional = abs(target_notional - pre_btc_notional)
                holdings = target_notional / p_open
                cash = (1.0 - target_w) * v_post

                turnovers[i] = trade_notional / v_pre if v_pre > 0 else 0.0
                fees[i] = realized_fee

                trade_events.append({
                    "execution_timestamp": ts.isoformat(),
                    "decision_timestamp": decision_ts.isoformat(),
                    "price": p_open,
                    "target_btc_weight": target_w,
                    "pre_btc_weight": current_w,
                    "deviation": deviation,
                    "trade_notional": trade_notional,
                    "fee": realized_fee,
                    "post_equity": v_post,
                    "holdings": holdings,
                    "cash": cash,
                })

            if sig is not None:
                decision_ledger.append({
                    "decision_timestamp": decision_ts.isoformat(),
                    "candle_dt": sig.candle_dt.isoformat(),
                    "close_price": sig.close_price,
                    "state_20": sig.state_20,
                    "state_55": sig.state_55,
                    "state_90": sig.state_90,
                    "raw_exposure": sig.raw_exposure,
                    "approved_exposure": sig.approved_exposure,
                    "confirmed": sig.confirmed,
                    "execution_timestamp": ts.isoformat(),
                    "execution_price": p_open,
                    "pre_trade_btc_weight": current_w,
                    "deviation": deviation,
                    "action": action,
                    "trade_notional": trade_notional,
                    "realized_fee": realized_fee,
                    "post_trade_equity": cash + holdings * p_open,
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
        policy_name="TRACK_A_V1_DONCHIAN_STEP",
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


def run_s5_daily_trend_replay(
    panels: Mapping[str, pd.DataFrame],
    start_dt: pd.Timestamp = pd.Timestamp("2022-01-01 00:00:00", tz="UTC"),
    end_dt: pd.Timestamp = pd.Timestamp("2026-11-18 23:00:00", tz="UTC"),
    initial_capital: float = PRIMARY_INITIAL_CAPITAL,
    fee_bps: float = 30.0,
    no_trade_band: float = S5_NO_TRADE_BAND,
) -> TrackAReplayResult:
    """Run S5 Daily Trend BTC Baseline replay on identical window and cost structure."""
    fee_rate = fee_bps / 10000.0

    timeline = panels["BTCUSDT"].loc[start_dt:end_dt].index
    for s in UNIVERSE:
        timeline = timeline.intersection(panels[s].loc[start_dt:end_dt].index)

    # Precompute 168h market trend across common universe in vectorized form
    full_common = panels["BTCUSDT"].index
    for s in UNIVERSE:
        full_common = full_common.intersection(panels[s].index)
    closes_df = pd.DataFrame({s: panels[s].loc[full_common, "close"] for s in UNIVERSE})
    pct_168 = (closes_df / closes_df.shift(168)) - 1.0
    mkt_168 = pct_168.mean(axis=1)

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

    opens_arr = panels["BTCUSDT"].loc[timeline, "open"].to_numpy(dtype=float)
    closes_arr = panels["BTCUSDT"].loc[timeline, "close"].to_numpy(dtype=float)

    current_target_w = 0.0

    for i in range(n_bars):
        ts = timeline[i]
        p_open = opens_arr[i]
        p_close = closes_arr[i]

        # Daily decision at 00:00 UTC (cutoff t-1h)
        if ts.hour == 0:
            cutoff_ts = ts - pd.Timedelta(hours=1)
            if cutoff_ts in mkt_168.index and not np.isnan(mkt_168.loc[cutoff_ts]):
                current_target_w = 1.0 if float(mkt_168.loc[cutoff_ts]) > 0.0 else 0.0

        # Execution at 01:00 UTC
        if ts.hour == 1:
            pre_btc_notional = holdings * p_open
            v_pre = cash + pre_btc_notional
            current_w = (pre_btc_notional / v_pre) if v_pre > 0 else 0.0
            deviation = abs(current_target_w - current_w)

            action = "HOLD"
            trade_notional = 0.0
            realized_fee = 0.0

            if deviation > no_trade_band:
                action = "REBALANCE"
                current_notionals = np.array([pre_btc_notional])
                target_weights = np.array([current_target_w])
                v_post, realized_fee = solve_post_fee_equity(v_pre, current_notionals, target_weights, fee_rate)

                target_notional = current_target_w * v_post
                trade_notional = abs(target_notional - pre_btc_notional)
                holdings = target_notional / p_open
                cash = (1.0 - current_target_w) * v_post

                turnovers[i] = trade_notional / v_pre if v_pre > 0 else 0.0
                fees[i] = realized_fee

                trade_events.append({
                    "execution_timestamp": ts.isoformat(),
                    "price": p_open,
                    "target_btc_weight": current_target_w,
                    "pre_btc_weight": current_w,
                    "deviation": deviation,
                    "trade_notional": trade_notional,
                    "fee": realized_fee,
                    "post_equity": v_post,
                    "holdings": holdings,
                    "cash": cash,
                })

            decision_ledger.append({
                "decision_timestamp": ts.floor("D").isoformat(),
                "execution_timestamp": ts.isoformat(),
                "target_btc_weight": current_target_w,
                "pre_trade_btc_weight": current_w,
                "deviation": deviation,
                "action": action,
                "trade_notional": trade_notional,
                "realized_fee": realized_fee,
                "post_trade_equity": cash + holdings * p_open,
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
        policy_name="S5_DAILY_TREND_BTC",
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


def run_btc_buy_and_hold_replay(
    btc_hourly: pd.DataFrame,
    start_dt: pd.Timestamp = pd.Timestamp("2022-01-01 00:00:00", tz="UTC"),
    end_dt: pd.Timestamp = pd.Timestamp("2026-11-18 23:00:00", tz="UTC"),
    initial_capital: float = PRIMARY_INITIAL_CAPITAL,
    fee_bps: float = 30.0,
) -> TrackAReplayResult:
    """Run Buy & Hold BTC baseline executed at 01:00 UTC on start_dt."""
    fee_rate = fee_bps / 10000.0
    timeline = btc_hourly.loc[start_dt:end_dt].index
    n_bars = len(timeline)

    equities = np.empty(n_bars, dtype=float)
    cash_hist = np.zeros(n_bars, dtype=float)
    holdings_hist = np.empty(n_bars, dtype=float)
    weights_hist = np.ones(n_bars, dtype=float)
    turnovers = np.zeros(n_bars, dtype=float)
    fees = np.zeros(n_bars, dtype=float)

    # Inception at 01:00 UTC
    p_open_0 = btc_hourly.loc[timeline[1], "open"] if n_bars > 1 else btc_hourly.loc[timeline[0], "open"]
    # Solve post-fee equity for initial purchase: V_post = V_pre - fee_rate * V_post => V_post = V_pre / (1 + fee_rate)
    v_post = initial_capital / (1.0 + fee_rate)
    fee_0 = initial_capital - v_post
    holdings = v_post / p_open_0

    turnovers[1] = 1.0
    fees[1] = fee_0

    trade_events = [{
        "execution_timestamp": timeline[1].isoformat() if n_bars > 1 else timeline[0].isoformat(),
        "price": p_open_0,
        "trade_notional": v_post,
        "fee": fee_0,
        "post_equity": v_post,
        "holdings": holdings,
        "cash": 0.0,
    }]

    closes_arr = btc_hourly.loc[timeline, "close"].to_numpy(dtype=float)
    for i in range(n_bars):
        if i == 0:
            equities[i] = initial_capital
            holdings_hist[i] = 0.0
            cash_hist[i] = initial_capital
            weights_hist[i] = 0.0
        else:
            eq = holdings * closes_arr[i]
            equities[i] = eq
            holdings_hist[i] = holdings
            cash_hist[i] = 0.0
            weights_hist[i] = 1.0

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
        policy_name="BTC_BH",
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
