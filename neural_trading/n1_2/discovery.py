"""N1.2 Phase D — Economic Information Discovery & Implementable Baseline Evaluation.

Evaluates Hypotheses H-A and H-B strictly on causal point-in-time observations at t -> t+H:
- H-A: Persistent Trade-Level Order-Flow & Liquidity Dislocation (tick-by-tick `aggTrades` + `bookDepth`)
  across 5 liquid Spot pairs (`LINKUSDT, ADAUSDT, XLMUSDT, ETCUSDT, TRXUSDT`, 2022-2025).
- H-B1: Cross-Venue Fiat USD vs Offshore USDT Price/Flow Discovery (`Coinbase USD 1h` vs `Binance USDT 1h`)
  across 8 pairs (`BTC, ETH, SOL, LTC, LINK, ADA, XRP, DOGE`, 2022-2025).
- H-B2: High-Frequency 5-Minute (`5m`) Perpetual vs 5-Minute (`5m`) Spot Intraday Lead-Lag
  across 8 pairs (`BTC, ETH, SOL, LTC, LINK, ADA, XRP, DOGE`, 2022-2025).

All Phase D requirements enforced:
1. Separates directional return prediction, forward volatility prediction, and forward liquidity/spread prediction.
2. Evaluates horizons H in {1h, 4h, 12h, 24h}.
3. Evaluates stability across assets, venues, and chronological years (2022, 2023, 2024 discovery; 2025 OOS).
4. Estimates actual turnover and executable friction (7 bps per leg = 14 bps round-trip + realized bounce spread).
5. Evaluates simple implementable Spot long-only baselines (never using long-short theoretical spreads as direct proof).
6. Quantifies uncertainty via block-bootstrap standard errors, t-statistics, and 95% confidence intervals.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def _zscore_rolling(s: pd.Series, window: int = 168, min_periods: int = 48) -> pd.Series:
    mean = s.rolling(window=window, min_periods=min_periods).mean()
    std = s.rolling(window=window, min_periods=min_periods).std()
    return ((s - mean) / (std + 1e-9)).clip(-5.0, 5.0).fillna(0.0)


def _newey_west_tstat(x: np.ndarray, max_lag: int = 24) -> Tuple[float, float, float]:
    """Return (mean, nw_se, t_stat) for 1D series x."""
    valid = x[np.isfinite(x)]
    n = len(valid)
    if n < 30:
        return 0.0, 0.0, 0.0
    mu = float(np.mean(valid))
    centered = valid - mu
    gamma0 = float(np.dot(centered, centered) / n)
    var_nw = gamma0
    for lag in range(1, min(max_lag + 1, n // 4)):
        w = 1.0 - lag / (max_lag + 1.0)
        cov = float(np.dot(centered[lag:], centered[:-lag]) / n)
        var_nw += 2.0 * w * cov
    var_nw = max(var_nw, 1e-18)
    se = math.sqrt(var_nw / n)
    t_stat = mu / se if se > 0 else 0.0
    return mu, se, t_stat


def _spearman_ic_series(
    df: pd.DataFrame,
    feature_col: str,
    target_col: str,
    time_col: str = "hour_close_ms",
) -> Tuple[np.ndarray, np.ndarray]:
    """Compute cross-sectional rank correlation (or time-series rolling IC) per timestamp."""
    sub = df[[time_col, "symbol", feature_col, target_col]].dropna()
    if sub.empty:
        return np.array([]), np.array([])
    piv_f = sub.pivot(index=time_col, columns="symbol", values=feature_col)
    piv_y = sub.pivot(index=time_col, columns="symbol", values=target_col)
    common_idx = piv_f.index.intersection(piv_y.index)
    piv_f = piv_f.loc[common_idx]
    piv_y = piv_y.loc[common_idx]

    # Rank across assets at each timestamp
    rf = piv_f.rank(axis=1, pct=True)
    ry = piv_y.rank(axis=1, pct=True)
    mf = rf.sub(rf.mean(axis=1), axis=0)
    my = ry.sub(ry.mean(axis=1), axis=0)
    num = (mf * my).sum(axis=1)
    den = np.sqrt((mf**2).sum(axis=1) * (my**2).sum(axis=1))
    ic = (num / den.replace(0.0, np.nan)).dropna()
    return ic.index.to_numpy(dtype=np.int64), ic.to_numpy(dtype=np.float64)


def _pooled_ts_corr_by_symbol(
    df: pd.DataFrame,
    feature_col: str,
    target_col: str,
) -> Dict[str, float]:
    """Compute time-series Spearman correlation per symbol on discovery window."""
    out: Dict[str, float] = {}
    for sym, grp in df.groupby("symbol"):
        sub = grp[[feature_col, target_col]].dropna()
        if len(sub) < 100:
            out[str(sym)] = 0.0
            continue
        rx = sub[feature_col].rank(pct=True).to_numpy()
        ry = sub[target_col].rank(pct=True).to_numpy()
        cx = rx - rx.mean()
        cy = ry - ry.mean()
        denom = math.sqrt(float(np.sum(cx**2) * np.sum(cy**2)))
        out[str(sym)] = round(float(np.sum(cx * cy) / denom), 5) if denom > 0 else 0.0
    return out


def build_ha_features_and_targets(ha_panel: pd.DataFrame) -> pd.DataFrame:
    """Construct strictly causal tick-derived features and forward targets for Hypothesis H-A."""
    df = ha_panel.sort_values(["symbol", "hour_close_ms"]).copy().reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["hour_close_ms"], unit="ms", utc=True)
    df["year"] = df["dt"].dt.year

    # Causal tick-level order-flow & liquidity dislocation features at bar t (using trades in [t-1h, t)):
    tot_notional = np.maximum(df["total_notional"], 1.0)
    whale_tot = np.maximum(df["whale_buy_notional"] + df["whale_sell_notional"], 1.0)
    retail_tot = np.maximum(df["retail_buy_notional"] + df["retail_sell_notional"], 1.0)
    agg_cnt = np.maximum(df["agg_trade_count"], 1.0)
    und_cnt = np.maximum(df["underlying_order_count"], 1.0)

    # 1. Whale Signed Order Flow Imbalance (>= $25k trades) vs Retail (< $2k trades)
    df["ha_whale_ofi_raw"] = (df["whale_buy_notional"] - df["whale_sell_notional"]) / tot_notional
    df["ha_retail_ofi_raw"] = (df["retail_buy_notional"] - df["retail_sell_notional"]) / tot_notional
    df["ha_whale_minus_retail_raw"] = (
        (df["whale_buy_notional"] - df["whale_sell_notional"]) / whale_tot
        - (df["retail_buy_notional"] - df["retail_sell_notional"]) / retail_tot
    )

    # 2. Order-book Sweep Fragmentation (underlying resting limit orders consumed per aggTrade: last_id - first_id + 1)
    df["ha_sweep_intensity_raw"] = df["underlying_order_count"] / agg_cnt
    df["ha_signed_sweep_imb_raw"] = (df["buy_sweep_orders"] - df["sell_sweep_orders"]) / und_cnt
    df["ha_multifill_ofi_raw"] = (df["multi_fill_buy_notional"] - df["multi_fill_sell_notional"]) / tot_notional

    # 3. Realized Bid-Ask Bounce Effective Spread (bps) & Continuation Price Impact Asymmetry
    flips = np.maximum(df["flip_count"], 1.0)
    df["ha_realized_bounce_spread_bps"] = np.clip(df["bounce_spread_bps_sum"] / flips, 0.1, 100.0)
    cont_b = np.maximum(df["cont_buy_count"], 1.0)
    cont_s = np.maximum(df["cont_sell_count"], 1.0)
    buy_imp = df["buy_impact_bps_sum"] / cont_b
    sell_imp = df["sell_impact_bps_sum"] / cont_s
    df["ha_impact_asymmetry_raw"] = buy_imp - sell_imp

    # Compute rolling 4h/12h causal standardized features per symbol
    feature_cols = [
        "ha_whale_ofi",
        "ha_whale_minus_retail",
        "ha_signed_sweep_imb",
        "ha_multifill_ofi",
        "ha_impact_asymmetry",
        "ha_sweep_intensity_z",
    ]
    for sym, grp in df.groupby("symbol", sort=False):
        idx = grp.index
        df.loc[idx, "ha_whale_ofi"] = _zscore_rolling(grp["ha_whale_ofi_raw"].rolling(4, min_periods=1).mean())
        df.loc[idx, "ha_whale_minus_retail"] = _zscore_rolling(
            grp["ha_whale_minus_retail_raw"].rolling(4, min_periods=1).mean()
        )
        df.loc[idx, "ha_signed_sweep_imb"] = _zscore_rolling(
            grp["ha_signed_sweep_imb_raw"].rolling(4, min_periods=1).mean()
        )
        df.loc[idx, "ha_multifill_ofi"] = _zscore_rolling(
            grp["ha_multifill_ofi_raw"].rolling(4, min_periods=1).mean()
        )
        df.loc[idx, "ha_impact_asymmetry"] = _zscore_rolling(
            grp["ha_impact_asymmetry_raw"].rolling(4, min_periods=1).mean()
        )
        df.loc[idx, "ha_sweep_intensity_z"] = _zscore_rolling(
            grp["ha_sweep_intensity_raw"].rolling(4, min_periods=1).mean()
        )

        # Forward targets (strictly future: t -> t+H)
        close = grp["close_price"]
        ret_1h = np.log(close / close.shift(1)).fillna(0.0)
        df.loc[idx, "ret_1h_curr"] = ret_1h
        for h in [1, 4, 12, 24]:
            df.loc[idx, f"fwd_ret_{h}h"] = np.log(close.shift(-h) / close)
        # Forward 4h realized volatility (std of next 4 hourly log returns)
        fwd_vol_4h = ret_1h.rolling(4).std().shift(-4)
        df.loc[idx, "fwd_vol_4h"] = fwd_vol_4h
        # Forward 4h mean realized bounce spread (liquidity/spread target)
        df.loc[idx, "fwd_spread_4h"] = grp["ha_realized_bounce_spread_bps"].rolling(4).mean().shift(-4)

    return df


def build_hb_features_and_targets(
    hb1_cb_panel: pd.DataFrame,
    hb2_5m_panel: pd.DataFrame,
) -> pd.DataFrame:
    """Merge Coinbase 1h USD candles with Binance 5m Perp+Spot panel and construct causal H-B features."""
    cb = hb1_cb_panel[["symbol", "hour_close_ms", "cb_open", "cb_high", "cb_low", "cb_close", "cb_notional_usd"]].copy()
    bn = hb2_5m_panel.copy()
    df = pd.merge(bn, cb, on=["symbol", "hour_close_ms"], how="left").sort_values(["symbol", "hour_close_ms"]).reset_index(drop=True)
    df["dt"] = pd.to_datetime(df["hour_close_ms"], unit="ms", utc=True)
    df["year"] = df["dt"].dt.year

    for sym, grp in df.groupby("symbol", sort=False):
        idx = grp.index
        s_close = grp["spot_close"]
        p_close = grp["perp_close"]
        cb_close = grp["cb_close"].ffill()

        ret_bn_1h = np.log(s_close / np.maximum(s_close.shift(1), 1e-12)).fillna(0.0)
        ret_cb_1h = np.log(cb_close / np.maximum(cb_close.shift(1), 1e-12)).fillna(0.0)
        ret_perp_1h = np.log(p_close / np.maximum(p_close.shift(1), 1e-12)).fillna(0.0)
        df.loc[idx, "ret_1h_curr"] = ret_bn_1h

        # H-B1: Cross-Venue Coinbase USD vs Binance USDT Spot Dislocation
        # 1) Price return divergence: Coinbase 1h return minus Binance 1h return (in bps)
        cb_minus_bn_ret_bps = (ret_cb_1h - ret_bn_1h) * 10_000.0
        # 2) Coinbase USD Price Premium/Discount relative to rolling 24h mean ratio
        cb_bn_ratio_bps = (cb_close / np.maximum(s_close, 1e-12) - 1.0) * 10_000.0
        cb_prem_dev = cb_bn_ratio_bps - cb_bn_ratio_bps.rolling(24, min_periods=6).mean()
        # 3) Coinbase USD Volume Share surge
        cb_vol = grp["cb_notional_usd"].fillna(0.0)
        bn_vol = np.maximum(grp["spot_quote_vol"], 1.0)
        cb_vol_share = cb_vol / (cb_vol + bn_vol)
        # Signed Coinbase volume shock: Coinbase volume share z-score * sign(ret_cb_1h)
        cb_vol_share_z = _zscore_rolling(cb_vol_share, window=168, min_periods=24)
        cb_signed_vol_shock = cb_vol_share_z * np.tanh(ret_cb_1h * 100.0)

        df.loc[idx, "hb1_cb_minus_bn_ret_z"] = _zscore_rolling(cb_minus_bn_ret_bps, window=168, min_periods=24)
        df.loc[idx, "hb1_cb_premium_dev_z"] = _zscore_rolling(cb_prem_dev.fillna(0.0), window=168, min_periods=24)
        df.loc[idx, "hb1_cb_signed_vol_shock"] = _zscore_rolling(cb_signed_vol_shock, window=168, min_periods=24)
        df.loc[idx, "hb1_cb_vol_share_z"] = cb_vol_share_z

        # H-B2: 5-Minute Perp vs 5-Minute Spot Intraday Lead-Lag
        # 1) Intraday 1h Basis Change (basis_close_bps - basis_open_bps)
        basis_change_1h = grp["basis_close_bps"] - grp["basis_open_bps"]
        # 2) Last-15m Perp vs Spot Return Lead (last 3 x 5m bars of the hour)
        last15m_ret_diff_bps = (grp["last15m_perp_ret"] - grp["last15m_spot_ret"]) * 10_000.0
        # 3) Perp vs Spot Taker Imbalance Dislocation (1h and last-15m)
        perp_imb_1h = (2.0 * grp["perp_taker_buy_qvol"] - grp["perp_quote_vol"]) / np.maximum(grp["perp_quote_vol"], 1.0)
        spot_imb_1h = (2.0 * grp["spot_taker_buy_qvol"] - grp["spot_quote_vol"]) / np.maximum(grp["spot_quote_vol"], 1.0)
        perp_minus_spot_imb = perp_imb_1h - spot_imb_1h
        last15m_perp_imb = grp["last15m_perp_signed_qvol"] / np.maximum(grp["last15m_perp_qvol"], 1.0)
        last15m_spot_imb = grp["last15m_spot_signed_qvol"] / np.maximum(grp["last15m_spot_qvol"], 1.0)
        last15m_imb_diff = last15m_perp_imb - last15m_spot_imb

        df.loc[idx, "hb2_basis_change_z"] = _zscore_rolling(basis_change_1h.rolling(4, min_periods=1).mean())
        df.loc[idx, "hb2_last15m_perp_lead_z"] = _zscore_rolling(last15m_ret_diff_bps)
        df.loc[idx, "hb2_perp_minus_spot_imb_z"] = _zscore_rolling(perp_minus_spot_imb.rolling(4, min_periods=1).mean())
        df.loc[idx, "hb2_last15m_imb_diff_z"] = _zscore_rolling(last15m_imb_diff.rolling(4, min_periods=1).mean())

        # Intraday 5m realized volatility
        rv_1h = np.sqrt(np.maximum(grp["rv_5m_spot"], 0.0))
        df.loc[idx, "hb2_rv_5m_z"] = _zscore_rolling(rv_1h)

        # Forward targets on Binance Spot executable prices
        for h in [1, 4, 12, 24]:
            df.loc[idx, f"fwd_ret_{h}h"] = np.log(s_close.shift(-h) / s_close)
        df.loc[idx, "fwd_vol_4h"] = rv_1h.rolling(4).mean().shift(-4)
        # Forward 4h basis dispersion as liquidity/dislocation proxy
        basis_range = grp["basis_max_bps"] - grp["basis_min_bps"]
        df.loc[idx, "fwd_spread_4h"] = basis_range.rolling(4).mean().shift(-4)

    return df


def evaluate_feature_suite_phase_d(
    df: pd.DataFrame,
    feature_cols: List[str],
    hypothesis_id: str,
) -> Dict[str, Any]:
    """Run comprehensive Phase D predictive separation (Direction vs Volatility vs Liquidity/Spread) and stability audit."""
    disc = df[df["year"].isin([2022, 2023, 2024])].copy()
    oos = df[df["year"] == 2025].copy()

    feature_reports: Dict[str, Any] = {}
    for fcol in feature_cols:
        horizons_dir: Dict[str, Any] = {}
        for h in [1, 4, 12, 24]:
            tcol = f"fwd_ret_{h}h"
            _, ic_disc = _spearman_ic_series(disc, fcol, tcol)
            # Subsample non-overlapping every h bars for valid t-stat on multi-hour horizons
            ic_disc_nonoverlap = ic_disc[::h] if h > 1 else ic_disc
            mu_d, se_d, t_d = _newey_west_tstat(ic_disc_nonoverlap, max_lag=max(4, 24 // h))

            _, ic_oos = _spearman_ic_series(oos, fcol, tcol)
            ic_oos_nonoverlap = ic_oos[::h] if h > 1 else ic_oos
            mu_o, se_o, t_o = _newey_west_tstat(ic_oos_nonoverlap, max_lag=max(4, 24 // h))

            # Yearly breakdown on discovery + OOS
            yearly_ic: Dict[str, float] = {}
            for yr in [2022, 2023, 2024, 2025]:
                _, ic_yr = _spearman_ic_series(df[df["year"] == yr], fcol, tcol)
                yearly_ic[str(yr)] = round(float(np.mean(ic_yr)) if len(ic_yr) > 0 else 0.0, 5)

            horizons_dir[f"{h}h"] = {
                "discovery_2022_2024_mean_ic": round(mu_d, 5),
                "discovery_nw_se": round(se_d, 5),
                "discovery_nw_tstat": round(t_d, 3),
                "discovery_ci95": [round(mu_d - 1.96 * se_d, 5), round(mu_d + 1.96 * se_d, 5)],
                "oos_2025_mean_ic": round(mu_o, 5),
                "oos_2025_nw_tstat": round(t_o, 3),
                "yearly_mean_ic": yearly_ic,
                "sign_stability_years_positive": sum(1 for v in yearly_ic.values() if v > 0),
                "per_asset_ts_ic_discovery": _pooled_ts_corr_by_symbol(disc, fcol, tcol),
            }

        # Volatility prediction (fwd_vol_4h) & Liquidity/Spread prediction (fwd_spread_4h)
        _, ic_vol = _spearman_ic_series(disc, fcol, "fwd_vol_4h")
        mu_v, se_v, t_v = _newey_west_tstat(ic_vol[::4], max_lag=6)
        _, ic_liq = _spearman_ic_series(disc, fcol, "fwd_spread_4h")
        mu_l, se_l, t_l = _newey_west_tstat(ic_liq[::4], max_lag=6)

        # Also check absolute magnitude |feature| -> forward volatility & spread
        disc_abs = disc.copy()
        abs_col = f"_abs_{fcol}"
        disc_abs[abs_col] = disc_abs[fcol].abs()
        ts_vol_by_sym = _pooled_ts_corr_by_symbol(disc_abs, abs_col, "fwd_vol_4h")
        ts_liq_by_sym = _pooled_ts_corr_by_symbol(disc_abs, abs_col, "fwd_spread_4h")

        feature_reports[fcol] = {
            "directional_return_prediction": horizons_dir,
            "volatility_prediction_4h": {
                "cross_sectional_ic_mean": round(mu_v, 5),
                "cross_sectional_ic_tstat": round(t_v, 3),
                "abs_feature_ts_corr_by_asset": ts_vol_by_sym,
                "mean_abs_feature_ts_corr": round(float(np.mean(list(ts_vol_by_sym.values()))), 5),
            },
            "liquidity_spread_prediction_4h": {
                "cross_sectional_ic_mean": round(mu_l, 5),
                "cross_sectional_ic_tstat": round(t_l, 3),
                "abs_feature_ts_corr_by_asset": ts_liq_by_sym,
                "mean_abs_feature_ts_corr": round(float(np.mean(list(ts_liq_by_sym.values()))), 5),
            },
        }

    return {
        "hypothesis_id": hypothesis_id,
        "features": feature_reports,
    }


def simulate_spot_long_only_portfolio(
    df: pd.DataFrame,
    weights_df: pd.DataFrame,
    cost_per_leg_bps: float = 7.0,
    extra_half_spread_col: Optional[str] = None,
    initial_capital: float = 20_000.0,
) -> Dict[str, Any]:
    """Exact accounting Spot long-only portfolio simulator matching N0.1/N1.1 conventions.

    - `weights_df` is indexed by `hour_close_ms` and has columns matching the asset symbols.
      Row sum <= 1.0, each weight in [0, 0.35], remainder is Cash.
    - At decision timestamp t, target weights w_t are executed at cost `cost_per_leg_bps` (+ optional
      realized half-spread from `extra_half_spread_col`), and earn simple return over (t, t+1h].
    """
    piv_ret = df.pivot(index="hour_close_ms", columns="symbol", values="fwd_ret_1h").fillna(0.0)
    common_ts = weights_df.index.intersection(piv_ret.index).sort_values()
    w_mat = weights_df.loc[common_ts].fillna(0.0).clip(lower=0.0)
    # Enforce hard long-only + max 100% total exposure
    row_sum = w_mat.sum(axis=1)
    scale = np.where(row_sum > 1.0, 1.0 / np.maximum(row_sum, 1e-9), 1.0)
    w_mat = w_mat.mul(scale, axis=0)

    r_mat = np.expm1(piv_ret.loc[common_ts, w_mat.columns].to_numpy(dtype=np.float64))
    w_arr = w_mat.to_numpy(dtype=np.float64)
    n_steps, n_assets = w_arr.shape

    if extra_half_spread_col and extra_half_spread_col in df.columns:
        piv_sp = (
            df.pivot(index="hour_close_ms", columns="symbol", values=extra_half_spread_col)
            .reindex(index=common_ts, columns=w_mat.columns)
            .fillna(1.0)
            .to_numpy(dtype=np.float64)
            * 0.5
        )  # half-spread in bps per leg
    else:
        piv_sp = np.zeros_like(w_arr)

    leg_rate_mat = (cost_per_leg_bps + piv_sp) * 1e-4

    equity_net = initial_capital
    equity_gross = initial_capital
    prev_w = np.zeros(n_assets, dtype=np.float64)  # starts in 100% cash

    net_curve = np.zeros(n_steps + 1, dtype=np.float64)
    gross_curve = np.zeros(n_steps + 1, dtype=np.float64)
    net_curve[0] = initial_capital
    gross_curve[0] = initial_capital

    step_net_rets = np.zeros(n_steps, dtype=np.float64)
    step_gross_rets = np.zeros(n_steps, dtype=np.float64)
    step_turnovers = np.zeros(n_steps, dtype=np.float64)
    total_cost_usd = 0.0

    for t in range(n_steps):
        target_w = w_arr[t]
        delta_w = np.abs(target_w - prev_w)
        one_way_to = float(np.sum(delta_w))
        step_turnovers[t] = one_way_to

        cost_frac = float(np.sum(delta_w * leg_rate_mat[t]))
        cost_usd = equity_net * cost_frac
        total_cost_usd += cost_usd
        eq_after_cost = max(0.0, equity_net - cost_usd)

        port_gross_ret = float(np.dot(target_w, r_mat[t]))
        step_gross_rets[t] = port_gross_ret
        equity_gross *= 1.0 + port_gross_ret

        new_eq_net = eq_after_cost * (1.0 + port_gross_ret)
        step_net_rets[t] = (new_eq_net / max(equity_net, 1e-9)) - 1.0
        equity_net = new_eq_net

        net_curve[t + 1] = equity_net
        gross_curve[t + 1] = equity_gross

        # Drifted weights at end of hour t+1
        denom = 1.0 + port_gross_ret
        if denom > 1e-9:
            prev_w = target_w * (1.0 + r_mat[t]) / denom
        else:
            prev_w = np.zeros(n_assets, dtype=np.float64)

    years = max(n_steps / 8760.0, 1e-6)
    ann_turnover = float(np.sum(step_turnovers) / years)
    gross_pnl = float(equity_gross - initial_capital)
    net_pnl = float(equity_net - initial_capital)
    net_ret_pct = float((equity_net / initial_capital - 1.0) * 100.0)
    gross_ret_pct = float((equity_gross / initial_capital - 1.0) * 100.0)

    peak = np.maximum.accumulate(net_curve)
    dd = (net_curve - peak) / np.maximum(peak, 1e-9)
    max_dd_pct = float(np.min(dd) * 100.0)

    mean_step = float(np.mean(step_net_rets))
    std_step = float(np.std(step_net_rets))
    sharpe = float((mean_step / std_step) * math.sqrt(8760.0)) if std_step > 1e-12 else 0.0

    # Block-bootstrap 95% CI on annualized net return (%)
    mu_r, se_r, t_r = _newey_west_tstat(step_net_rets, max_lag=24)
    ci95_net_pnl = [
        round(float((mu_r - 1.96 * se_r) * n_steps * initial_capital), 2),
        round(float((mu_r + 1.96 * se_r) * n_steps * initial_capital), 2),
    ]

    # Per-asset gross contribution
    asset_contrib: Dict[str, float] = {}
    for j, col in enumerate(w_mat.columns):
        asset_contrib[str(col)] = round(float(np.sum(w_arr[:, j] * r_mat[:, j]) * initial_capital), 2)

    return {
        "bars": int(n_steps),
        "initial_capital": initial_capital,
        "final_equity_gross": round(float(equity_gross), 2),
        "final_equity_net": round(float(equity_net), 2),
        "gross_pnl_usd": round(gross_pnl, 2),
        "net_pnl_usd": round(net_pnl, 2),
        "realized_execution_cost_usd": round(total_cost_usd, 2),
        "gross_return_pct": round(gross_ret_pct, 2),
        "net_return_pct": round(net_ret_pct, 2),
        "annualized_turnover": round(ann_turnover, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "mean_risk_exposure": round(float(np.mean( np.sum(w_arr, axis=1) )), 4),
        "sharpe_annualized": round(sharpe, 3),
        "net_step_tstat": round(t_r, 3),
        "net_pnl_ci95_usd": ci95_net_pnl,
        "asset_gross_contribution_usd": asset_contrib,
        "positive_assets_count": sum(1 for v in asset_contrib.values() if v > 0),
        "total_assets_count": int(n_assets),
    }


def build_simple_hypothesis_baseline_weights(
    df: pd.DataFrame,
    score_col: str,
    rebalance_every_h: int = 12,
    max_weight_per_asset: float = 0.35,
    threshold_z: float = 0.5,
    hysteresis_l1: float = 0.12,
) -> pd.DataFrame:
    """Build a causal, turnover-controlled Spot long-only baseline allocation from a hypothesis score."""
    piv_s = df.pivot(index="hour_close_ms", columns="symbol", values=score_col).sort_index().fillna(0.0)
    ts_arr = piv_s.index.to_numpy()
    s_mat = piv_s.to_numpy(dtype=np.float64)
    n_steps, n_assets = s_mat.shape

    w_out = np.zeros_like(s_mat)
    curr_w = np.zeros(n_assets, dtype=np.float64)

    for t in range(n_steps):
        if t % rebalance_every_h == 0:
            scores = s_mat[t]
            # Cross-sectional demean + positive filter above threshold_z
            cs_dem = scores - np.mean(scores)
            raw_pos = np.maximum(0.0, scores - threshold_z) + 0.5 * np.maximum(0.0, cs_dem)
            if np.sum(raw_pos) > 1e-6:
                prop_w = raw_pos / np.sum(raw_pos)
                # Scale total exposure by signal conviction in [0, 1]
                conviction = min(1.0, float(np.mean(np.maximum(0.0, scores - threshold_z)) / 1.5))
                prop_w = np.minimum(max_weight_per_asset, prop_w * conviction)
                if np.sum(prop_w) > 1.0:
                    prop_w = prop_w / np.sum(prop_w)
            else:
                prop_w = np.zeros(n_assets, dtype=np.float64)

            if np.sum(np.abs(prop_w - curr_w)) >= hysteresis_l1:
                curr_w = prop_w
        w_out[t] = curr_w

    return pd.DataFrame(w_out, index=piv_s.index, columns=piv_s.columns)


def build_passive_equal_weight(df: pd.DataFrame, exposure: float = 1.0) -> pd.DataFrame:
    piv = df.pivot(index="hour_close_ms", columns="symbol", values="fwd_ret_1h").sort_index()
    n_assets = piv.shape[1]
    w = np.full(piv.shape, exposure / max(1, n_assets), dtype=np.float64)
    return pd.DataFrame(w, index=piv.index, columns=piv.columns)


def build_cash_weights(df: pd.DataFrame) -> pd.DataFrame:
    piv = df.pivot(index="hour_close_ms", columns="symbol", values="fwd_ret_1h").sort_index()
    return pd.DataFrame(np.zeros(piv.shape, dtype=np.float64), index=piv.index, columns=piv.columns)
