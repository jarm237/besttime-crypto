"""
neural_trading/n1/information_tests.py

Phase D: Pre-training information-theoretic and economic-hurdle evaluation for
Hypotheses H1 (Spot cross-sectional market structure & aggressor flow, 13 pairs,
2017-2025) and H2 (USD-M order-book depth asymmetry & liquidity thinning,
BTCUSDT & ETHUSDT, 2023-2025).

Every feature is strictly causal at `available_at` = t. Forward outcomes over
horizon H hours use prices in (t, t + H].
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple
import numpy as np
import pandas as pd


def compute_h1_features(panel: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """
    Computes strictly causal per-asset and market-wide features from the 13-pair
    Spot 1h panel. Indexed by `available_at` (bar close).
    """
    close = panel["close"]
    high = panel["high"]
    low = panel["low"]
    open_ = panel["open"]
    qvol = panel["quote_volume"]
    trades = panel["trades"]
    tb_qvol = panel["taker_buy_quote"]

    # Active mask: asset has valid close & trailing 168h history and positive volume
    r1h = close.pct_change(1, fill_method=None)
    r4h = close.pct_change(4, fill_method=None)
    r12h = close.pct_change(12, fill_method=None)
    r24h = close.pct_change(24, fill_method=None)
    r72h = close.pct_change(72, fill_method=None)
    r168h = close.pct_change(168, fill_method=None)

    active = close.notna() & r168h.notna() & (qvol.rolling(24, min_periods=12).sum() > 0)

    # 1. Spot Taker Buy Imbalance: (2 * taker_buy_quote - quote_vol) / quote_vol in [-1, 1]
    denom_q = qvol.where(qvol > 0, np.nan)
    taker_imb_1h = (2.0 * tb_qvol - qvol) / denom_q
    taker_imb_12h = (2.0 * tb_qvol.rolling(12, min_periods=6).sum() - qvol.rolling(12, min_periods=6).sum()) / (
        qvol.rolling(12, min_periods=6).sum().where( lambda x: x > 0, np.nan)
    )
    taker_imb_24h = (2.0 * tb_qvol.rolling(24, min_periods=12).sum() - qvol.rolling(24, min_periods=12).sum()) / (
        qvol.rolling(24, min_periods=12).sum().where(lambda x: x > 0, np.nan)
    )

    # 2. Trade participation & average trade size shock vs 168h baseline
    avg_trade_usd = qvol / trades.where(trades > 0, np.nan)
    log_avg_trade = np.log(avg_trade_usd.where(avg_trade_usd > 0, np.nan))
    trade_size_z168h = (
        log_avg_trade.rolling(12, min_periods=6).mean()
        - log_avg_trade.rolling(168, min_periods=72).mean()
    ) / log_avg_trade.rolling(168, min_periods=72).std().replace(0.0, np.nan)

    log_qvol = np.log(qvol.where(qvol > 0, np.nan))
    vol_shock_z168h = (
        log_qvol.rolling(12, min_periods=6).mean()
        - log_qvol.rolling(168, min_periods=72).mean()
    ) / log_qvol.rolling(168, min_periods=72).std().replace(0.0, np.nan)

    # 3. Intrabar Range (Parkinson Vol) & Close-Location Shadow Asymmetry
    log_hl = np.log((high / low.where(low > 0, np.nan)).where(lambda x: x > 0, np.nan))
    parkinson_vol_24h = np.sqrt((log_hl ** 2).rolling(24, min_periods=12).mean() / (4.0 * np.log(2.0)))
    hl_span = (high - low).where(lambda x: x > 0, np.nan)
    clv_1h = ((close - low) - (high - close)) / hl_span  # in [-1, +1]
    clv_12h = clv_1h.rolling(12, min_periods=6).mean()

    # 4. Cross-sectional market structure (computed only across active assets at time t)
    r24_act = r24h.where(active)
    mkt_ret_24h = r24_act.mean(axis=1)
    xs_disp_24h = r24_act.std(axis=1)
    xs_breadth_24h = (r24_act > 0).sum(axis=1) / active.sum(axis=1).replace(0, np.nan)
    xs_rel_ret_24h = r24_act.sub(mkt_ret_24h, axis=0)
    xs_rel_imb_24h = taker_imb_24h.where(active).sub(taker_imb_24h.where(active).mean(axis=1), axis=0)

    # Broadcast market-level state across active symbols for uniform evaluation
    mkt_breadth_panel = pd.DataFrame(
        {s: xs_breadth_24h for s in close.columns}, index=close.index
    ).where(active)
    mkt_disp_panel = pd.DataFrame(
        {s: xs_disp_24h for s in close.columns}, index=close.index
    ).where(active)
    mkt_trend_panel = pd.DataFrame(
        {s: r72h.where(active).mean(axis=1) for s in close.columns}, index=close.index
    ).where(active)

    return {
        "active": active,
        "close": close,
        "r1h": r1h.where(active),
        "r12h": r12h.where(active),
        "r24h": r24h.where(active),
        "r72h": r72h.where(active),
        "H1_spot_taker_imb_12h": taker_imb_12h.where(active),
        "H1_spot_taker_imb_24h": taker_imb_24h.where(active),
        "H1_xs_rel_imb_24h": xs_rel_imb_24h.where(active),
        "H1_trade_size_z168h": trade_size_z168h.where(active),
        "H1_vol_shock_z168h": vol_shock_z168h.where(active),
        "H1_parkinson_vol_24h": parkinson_vol_24h.where(active),
        "H1_clv_shadow_12h": clv_12h.where(active),
        "H1_xs_rel_ret_24h": xs_rel_ret_24h.where(active),
        "H1_mkt_breadth_24h": mkt_breadth_panel,
        "H1_mkt_disp_24h": mkt_disp_panel,
        "H1_mkt_trend_72h": mkt_trend_panel,
    }


def _block_bootstrap_ci(
    series: np.ndarray,
    block_len: int = 4,
    n_boot: int = 400,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """Stationary block bootstrap on non-overlapping horizon observations."""
    x = series[np.isfinite(series)]
    n = len(x)
    if n < 20:
        return (float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    n_blocks = max(1, int(np.ceil(n / block_len)))
    starts = rng.integers(0, max(1, n - block_len + 1), size=(n_boot, n_blocks))
    idx = (starts[:, :, None] + np.arange(block_len)[None, None, :]).reshape(n_boot, -1)[:, :n]
    means = x[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    # Two-sided bootstrap p-value against 0
    p_pos = np.mean(means <= 0.0)
    p_neg = np.mean(means >= 0.0)
    p_val = float(min(1.0, 2.0 * min(p_pos, p_neg)))
    return (float(lo), float(hi), p_val)


def evaluate_feature_panel(
    feat: pd.DataFrame,
    close: pd.DataFrame,
    active: pd.DataFrame,
    horizon_h: int,
    segments: Dict[str, Tuple[str, str]],
    cost_rt_bps: float = 14.0,
) -> Dict[str, Any]:
    """
    Evaluates a single feature panel on non-overlapping H-hour steps to avoid
    overlapping-return serial inflation:
      - Q5 - Q1 raw forward return spread (bps per H-hour period)
      - Beta-neutral (market-demeaned) forward return spread (bps)
      - Downside tail risk (CVaR 5% and downside semi-vol in Q5 vs Q1)
      - Forward realized volatility ratio (Q5 / Q1)
      - Implied one-way turnover of a top-quantile signal & net spread after cost
      - Stability across chronological segments and across assets
    """
    # Sample at non-overlapping H-hour cadence
    step_idx = feat.index[::horizon_h]
    f_sub = feat.reindex(step_idx).where(active.reindex(step_idx))
    fwd_ret = (close.shift(-horizon_h) / close - 1.0).reindex(step_idx).where(active.reindex(step_idx))
    fwd_log_ret = np.log((close.shift(-horizon_h) / close).where(lambda x: x > 0, np.nan)).reindex(step_idx).where(active.reindex(step_idx))
    r1h = close.pct_change(1, fill_method=None)
    fwd_vol = r1h.rolling(horizon_h, min_periods=max(2, horizon_h // 2)).std().shift(-horizon_h).reindex(step_idx).where(active.reindex(step_idx))

    mkt_fwd = fwd_ret.mean(axis=1)
    exc_fwd = fwd_ret.sub(mkt_fwd, axis=0)
    mkt_log_fwd = fwd_log_ret.mean(axis=1)
    exc_log_fwd = fwd_log_ret.sub(mkt_log_fwd, axis=0)

    def _slice_stats(t_start: str, t_end: str) -> Dict[str, float]:
        f_w = f_sub.loc[t_start:t_end]
        r_w = fwd_ret.loc[t_start:t_end]
        lr_w = fwd_log_ret.loc[t_start:t_end]
        e_w = exc_fwd.loc[t_start:t_end]
        le_w = exc_log_fwd.loc[t_start:t_end]
        v_w = fwd_vol.loc[t_start:t_end]

        flat_f = f_w.to_numpy().ravel()
        flat_r = r_w.to_numpy().ravel()
        flat_lr = lr_w.to_numpy().ravel()
        flat_e = e_w.to_numpy().ravel()
        flat_le = le_w.to_numpy().ravel()
        flat_v = v_w.to_numpy().ravel()
        valid = np.isfinite(flat_f) & np.isfinite(flat_r) & np.isfinite(flat_lr)
        default_empty = {
            "n_obs": int(valid.sum()), "raw_spread_bps": 0.0, "log_spread_bps": 0.0,
            "beta_adj_spread_bps": 0.0, "beta_adj_log_spread_bps": 0.0, "winsor_spread_bps": 0.0,
            "ci95_lo_bps": 0.0, "ci95_hi_bps": 0.0, "boot_p_value": 1.0,
            "cvar5_q5_bps": 0.0, "cvar5_q1_bps": 0.0, "cvar5_diff_bps": 0.0,
            "fwd_vol_ratio_q5_q1": 1.0, "step_oneway_turnover": 0.0,
            "implied_cost_bps": 0.0, "net_spread_after_cost_bps": 0.0,
            "net_log_spread_after_cost_bps": 0.0, "asset_sign_consistency": 0.0,
        }
        if valid.sum() < 80:
            return default_empty

        fv, rv, lrv, ev, lev, vv = (
            flat_f[valid], flat_r[valid], flat_lr[valid],
            flat_e[valid], flat_le[valid], flat_v[valid],
        )
        q20, q80 = np.quantile(fv, [0.20, 0.80])
        m_q1 = fv <= q20
        m_q5 = fv >= q80
        if m_q1.sum() < 10 or m_q5.sum() < 10:
            return default_empty

        raw_spread_bps = float((rv[m_q5].mean() - rv[m_q1].mean()) * 1e4)
        log_spread_bps = float((lrv[m_q5].mean() - lrv[m_q1].mean()) * 1e4)
        beta_spread_bps = float((ev[m_q5].mean() - ev[m_q1].mean()) * 1e4)
        beta_log_spread_bps = float((lev[m_q5].mean() - lev[m_q1].mean()) * 1e4)

        # 1% Winsorized return spread
        r_lo, r_hi = np.quantile(rv, [0.01, 0.99])
        rv_win = np.clip(rv, r_lo, r_hi)
        winsor_spread_bps = float((rv_win[m_q5].mean() - rv_win[m_q1].mean()) * 1e4)

        # Downside CVaR 5% (bps) in Q5 vs Q1
        cvar5_q5_bps = float(np.mean(rv[m_q5][rv[m_q5] <= np.quantile(rv[m_q5], 0.05)]) * 1e4)
        cvar5_q1_bps = float(np.mean(rv[m_q1][rv[m_q1] <= np.quantile(rv[m_q1], 0.05)]) * 1e4)

        # Forward realized volatility ratio Q5 / Q1
        vol_q5 = float(np.nanmean(vv[m_q5]))
        vol_q1 = float(np.nanmean(vv[m_q1]))
        vol_ratio = vol_q5 / max(vol_q1, 1e-8)

        # Detect whether feature is cross-sectional (varies across columns at fixed t)
        xs_std = float(f_w.std(axis=1).mean())
        is_cross_sectional = (f_w.shape[1] >= 5) and np.isfinite(xs_std) and (xs_std > 1e-6)

        if is_cross_sectional:
            q80_ts = f_w.quantile(0.80, axis=1)
            q20_ts = f_w.quantile(0.20, axis=1)
            top_mask = f_w.ge(q80_ts, axis=0) & f_w.notna()
            bot_mask = f_w.le(q20_ts, axis=0) & f_w.notna()
            w_top = top_mask.div(top_mask.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)
            step_oneway_to = float(0.5 * w_top.diff().abs().sum(axis=1).mean())
            implied_cost_bps = step_oneway_to * cost_rt_bps
            ts_spread = (lr_w.where(top_mask).mean(axis=1) - lr_w.where(bot_mask).mean(axis=1)).dropna().to_numpy() * 1e4
            primary_spread_for_net = beta_log_spread_bps
        else:
            # Time-series or 2-asset feature: evaluate time-series regime exposure signal
            f_mean_ts = f_w.mean(axis=1)
            r_mean_ts = lr_w.mean(axis=1)
            valid_ts = f_mean_ts.notna() & r_mean_ts.notna()
            f_ts = f_mean_ts[valid_ts]
            r_ts = r_mean_ts[valid_ts]
            q20_t, q80_t = np.quantile(f_ts, [0.20, 0.80])
            active_pos = (f_ts >= np.median(f_ts)).astype(float)
            step_oneway_to = float(active_pos.diff().abs().mean())
            implied_cost_bps = step_oneway_to * cost_rt_bps
            # Compare top-quantile regime steps vs bottom-quantile regime steps via demeaned step contributions
            hi_mask = (f_ts >= q80_t).astype(float)
            lo_mask = (f_ts <= q20_t).astype(float)
            p_hi = max(float(hi_mask.mean()), 1e-6)
            p_lo = max(float(lo_mask.mean()), 1e-6)
            ts_spread = ((hi_mask / p_hi - lo_mask / p_lo) * r_ts).to_numpy() * 1e4
            primary_spread_for_net = log_spread_bps

        ci_lo, ci_hi, p_val = _block_bootstrap_ci(ts_spread, block_len=max(2, 48 // horizon_h))

        # Per-asset sign consistency (using log returns)
        asset_spreads = []
        for col in f_w.columns:
            fc = f_w[col].to_numpy()
            rc = lr_w[col].to_numpy()
            ok = np.isfinite(fc) & np.isfinite(rc)
            if ok.sum() >= 50:
                ql, qh = np.quantile(fc[ok], [0.20, 0.80])
                sp = (rc[ok][fc[ok] >= qh].mean() - rc[ok][fc[ok] <= ql].mean()) * 1e4
                if np.isfinite(sp):
                    asset_spreads.append(float(sp))
        sign_ref = 1.0 if primary_spread_for_net >= 0 else -1.0
        asset_consistency = float(np.mean([np.sign(s) == sign_ref for s in asset_spreads])) if asset_spreads else 0.0

        return {
            "n_obs": int(valid.sum()),
            "raw_spread_bps": round(raw_spread_bps, 2),
            "log_spread_bps": round(log_spread_bps, 2),
            "beta_adj_spread_bps": round(beta_spread_bps, 2),
            "beta_adj_log_spread_bps": round(beta_log_spread_bps, 2),
            "winsor_spread_bps": round(winsor_spread_bps, 2),
            "ci95_lo_bps": round(ci_lo, 2),
            "ci95_hi_bps": round(ci_hi, 2),
            "boot_p_value": round(p_val, 4),
            "cvar5_q5_bps": round(cvar5_q5_bps, 1),
            "cvar5_q1_bps": round(cvar5_q1_bps, 1),
            "cvar5_diff_bps": round(cvar5_q5_bps - cvar5_q1_bps, 1),
            "fwd_vol_ratio_q5_q1": round(vol_ratio, 3),
            "step_oneway_turnover": round(step_oneway_to, 3),
            "implied_cost_bps": round(implied_cost_bps, 2),
            "net_spread_after_cost_bps": round(abs(raw_spread_bps) - implied_cost_bps, 2),
            "net_log_spread_after_cost_bps": round(abs(primary_spread_for_net) - implied_cost_bps, 2),
            "asset_sign_consistency": round(asset_consistency, 2),
        }

    dev_start = min(v[0] for v in segments.values())
    dev_end = max(v[1] for v in segments.values())
    overall = _slice_stats(dev_start, dev_end)
    per_seg = {k: _slice_stats(s, e) for k, (s, e) in segments.items()}
    seg_signs = [np.sign(v["raw_spread_bps"]) for v in per_seg.values() if v.get("n_obs", 0) >= 100]
    main_sign = np.sign(overall["raw_spread_bps"])
    seg_stability = float(np.mean([s == main_sign and s != 0 for s in seg_signs])) if seg_signs else 0.0
    overall["segment_sign_stability"] = round(seg_stability, 2)
    return {"overall_dev": overall, "segments": per_seg}
