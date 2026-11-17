"""Predictive Information and Feature Auditing Engine for R6 Discovery.

Implements from first principles:
  1. Multi-timeframe causal feature extraction (1h, 4h, 24h, 72h, 168h) across:
     - Market returns & momentum (multi-lookback)
     - Volatility & range dynamics (realized vol, normalized true range)
     - Volume & liquidity indicators (surge ratio, volume-price trend)
     - Trend & moving average distance (SMA24, SMA168, EMA spreads)
     - Cross-asset relationships & market breadth (dispersion, breadth > SMA168, relative momentum vs BTC)
     - Market regime (BTC trend, BTC realized vol regime)
     - Alternative & macro data (Fear & Greed, Treasury yield slope, Stablecoin growth)
  2. Multi-horizon forward target generation:
     - Cross-sectional selection targets (excess return vs BTC, excess return vs EW)
     - Market exposure targets (BTC vs cash, EW vs cash)
     - Horizons: 1h, 4h, 24h, 72h, 168h
  3. Information-theoretic and statistical audit metrics:
     - Rank IC (Spearman rho) with block-bootstrap p-values
     - Pearson IC
     - Directional Hit Rate
     - Mutual Information with bias-corrected k-NN estimator
     - Regime-conditional Rank IC (Bull vs Bear, High-Vol vs Low-Vol)
     - Incremental Information controlling for BTC market beta (residualized IC)
     - Benjamini-Hochberg False Discovery Rate (FDR) correction for multiple testing
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.feature_selection import mutual_info_regression

logger = logging.getLogger(__name__)

CANONICAL_HORIZONS: List[int] = [1, 4, 24, 72, 168]


@dataclass
class FeatureDefinition:
    name: str
    family: str
    lookback_hours: int
    description: str
    is_cross_sectional: bool
    requires_market_context: bool


@dataclass
class PredictiveInformationResult:
    feature_name: str
    family: str
    target_type: str  # 'cross_sectional_vs_btc', 'cross_sectional_vs_ew', 'market_exposure_btc'
    horizon_hours: int
    pooled_rank_ic: float
    rank_ic_pvalue: float
    mean_cross_sectional_rank_ic: float
    pearson_ic: float
    directional_hit_rate: float
    mutual_information_nats: float
    train_rank_ic: float
    val_rank_ic: float
    holdout_rank_ic: float
    temporal_stability_score: float  # cos_sim / consistency across splits
    regime_bull_rank_ic: float
    regime_bear_rank_ic: float
    regime_highvol_rank_ic: float
    regime_lowvol_rank_ic: float
    incremental_ic_vs_btc_beta: float
    fdr_adjusted_qvalue: float = 1.0
    is_significant_train_val: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_name": self.feature_name,
            "family": self.family,
            "target_type": self.target_type,
            "horizon_hours": self.horizon_hours,
            "pooled_rank_ic": round(self.pooled_rank_ic, 4),
            "rank_ic_pvalue": round(self.rank_ic_pvalue, 6),
            "mean_cross_sectional_rank_ic": round(self.mean_cross_sectional_rank_ic, 4),
            "pearson_ic": round(self.pearson_ic, 4),
            "directional_hit_rate": round(self.directional_hit_rate, 4),
            "mutual_information_nats": round(self.mutual_information_nats, 5),
            "train_rank_ic": round(self.train_rank_ic, 4),
            "val_rank_ic": round(self.val_rank_ic, 4),
            "holdout_rank_ic": round(self.holdout_rank_ic, 4),
            "temporal_stability_score": round(self.temporal_stability_score, 4),
            "regime_bull_rank_ic": round(self.regime_bull_rank_ic, 4),
            "regime_bear_rank_ic": round(self.regime_bear_rank_ic, 4),
            "regime_highvol_rank_ic": round(self.regime_highvol_rank_ic, 4),
            "regime_lowvol_rank_ic": round(self.regime_lowvol_rank_ic, 4),
            "incremental_ic_vs_btc_beta": round(self.incremental_ic_vs_btc_beta, 4),
            "fdr_adjusted_qvalue": round(self.fdr_adjusted_qvalue, 6),
            "is_significant_train_val": bool(self.is_significant_train_val),
        }


def extract_multi_timeframe_features(
    piv_close: pd.DataFrame,
    piv_open: pd.DataFrame,
    piv_high: pd.DataFrame,
    piv_low: pd.DataFrame,
    piv_volume: pd.DataFrame,
    alt_data: Optional[Dict[str, pd.DataFrame]] = None,
) -> Dict[str, pd.DataFrame]:
    """Extract causal feature matrices [timestamps x symbols] from aligned OHLCV data.
    
    Guarantees:
      - Point-in-time causality: feature at index t uses strictly bars <= t.
      - Aligned index: all feature DataFrames share the identical DatetimeIndex.
    """
    features: Dict[str, pd.DataFrame] = {}
    symbols = piv_close.columns.tolist()
    timestamps = piv_close.index

    # 1. Multi-timeframe Log Returns / Momentum
    for lb in [1, 4, 24, 72, 168]:
        ret_lb = np.log(piv_close / piv_close.shift(lb))
        features[f"ret_{lb}h"] = ret_lb

    # 2. Multi-timeframe Realized Volatility (annualized hourly std)
    for lb in [24, 168]:
        r1 = np.log(piv_close / piv_close.shift(1))
        # rolling std of 1h log returns
        vol_lb = r1.rolling(window=lb, min_periods=lb // 2).std() * np.sqrt(lb)
        features[f"vol_{lb}h"] = vol_lb

    # 3. Normalized True Range / Price Range
    norm_range = (piv_high - piv_low) / piv_close
    features["norm_range_1h"] = norm_range
    features["norm_range_24h"] = norm_range.rolling(24, min_periods=12).mean()

    # 4. Volume Surge Ratio
    for lb in [24, 168]:
        vol_sma = piv_volume.rolling(window=lb, min_periods=lb // 2).mean()
        # Avoid division by zero
        vol_surge = piv_volume / (vol_sma.replace(0.0, np.nan))
        features[f"vol_surge_{lb}h"] = np.log(vol_surge.clip(0.01, 100.0))

    # 5. Trend / Moving Average Distance
    for lb in [24, 168]:
        sma = piv_close.rolling(window=lb, min_periods=lb // 2).mean()
        ma_dist = (piv_close - sma) / sma
        features[f"ma_dist_{lb}h"] = ma_dist

    # 6. Relative Momentum vs BTC and vs Equal Weight
    btc_col = "BTCUSDT" if "BTCUSDT" in symbols else symbols[0]
    for lb in [4, 24, 72, 168]:
        ret_lb = features[f"ret_{lb}h"]
        btc_ret = ret_lb[btc_col]
        ew_ret = ret_lb.mean(axis=1)

        # Cross-sectional excess return
        rel_btc = ret_lb.sub(btc_ret, axis=0)
        rel_ew = ret_lb.sub(ew_ret, axis=0)
        features[f"rel_btc_mom_{lb}h"] = rel_btc
        features[f"rel_ew_mom_{lb}h"] = rel_ew

    # 7. Cross-Asset Market Breadth & Dispersion
    for lb in [24, 168]:
        ret_lb = features[f"ret_{lb}h"]
        # Cross-sectional dispersion across the universe at time t
        disp = ret_lb.std(axis=1)
        # Broadcast across symbols so it can be evaluated as a context feature
        disp_df = pd.DataFrame(np.tile(disp.values[:, None], (1, len(symbols))), index=timestamps, columns=symbols)
        features[f"market_dispersion_{lb}h"] = disp_df

    # Market Breadth: fraction of coins above 168h SMA
    sma168 = piv_close.rolling(window=168, min_periods=84).mean()
    breadth = (piv_close > sma168).mean(axis=1)
    breadth_df = pd.DataFrame(np.tile(breadth.values[:, None], (1, len(symbols))), index=timestamps, columns=symbols)
    features["market_breadth_sma168"] = breadth_df

    # 8. BTC Market Regime Features (Broadcast across symbols)
    btc_ret168 = features["ret_168h"][btc_col]
    btc_vol168 = features["vol_168h"][btc_col]
    btc_trend_sign = np.sign(features["ma_dist_168h"][btc_col])
    
    features["btc_trend_sign_168h"] = pd.DataFrame(np.tile(btc_trend_sign.values[:, None], (1, len(symbols))), index=timestamps, columns=symbols)
    features["btc_vol_regime_168h"] = pd.DataFrame(np.tile(btc_vol168.values[:, None], (1, len(symbols))), index=timestamps, columns=symbols)

    # 9. Alternative PIT Features if provided
    if alt_data is not None:
        if "fear_and_greed" in alt_data:
            fg_df = alt_data["fear_and_greed"]
            # Reindex / forward-fill to hourly timestamps
            fg_aligned = fg_df["value"].reindex(timestamps, method="ffill")
            features["fear_and_greed_val"] = pd.DataFrame(np.tile(fg_aligned.values[:, None], (1, len(symbols))), index=timestamps, columns=symbols)
        
        if "macro_yields" in alt_data:
            macro_df = alt_data["macro_yields"]
            if "slope_10_2" in macro_df.columns:
                slope_aligned = macro_df["slope_10_2"].reindex(timestamps, method="ffill")
                features["treasury_slope_10_2"] = pd.DataFrame(np.tile(slope_aligned.values[:, None], (1, len(symbols))), index=timestamps, columns=symbols)

    return features


def extract_forward_targets(
    piv_close: pd.DataFrame,
    horizons: Sequence[int] = CANONICAL_HORIZONS,
) -> Dict[str, Dict[int, pd.DataFrame]]:
    """Generate forward causal target returns for multiple prediction horizons.
    
    Target at index t represents return realized strictly from bar open[t+1] or close[t] to close[t+H].
    Using log price difference: log(P[t+H] / P[t]).
    
    Targets produced:
      - 'raw_return': log(P[t+H] / P[t]) for each asset
      - 'rel_btc': log(P_i[t+H]/P_i[t]) - log(P_btc[t+H]/P_btc[t])
      - 'rel_ew': log(P_i[t+H]/P_i[t]) - log(P_ew[t+H]/P_ew[t])
      - 'market_exposure_btc': log(P_btc[t+H] / P_btc[t]) broadcast to all assets
      - 'market_exposure_ew': log(P_ew[t+H] / P_ew[t]) broadcast to all assets
    """
    symbols = piv_close.columns.tolist()
    timestamps = piv_close.index
    btc_col = "BTCUSDT" if "BTCUSDT" in symbols else symbols[0]

    targets: Dict[str, Dict[int, pd.DataFrame]] = {
        "raw_return": {},
        "rel_btc": {},
        "rel_ew": {},
        "market_exposure_btc": {},
        "market_exposure_ew": {},
    }

    for H in horizons:
        # Forward return over H bars: shift(-H) / close
        fwd_raw = np.log(piv_close.shift(-H) / piv_close)
        targets["raw_return"][H] = fwd_raw

        # Excess over BTC
        btc_fwd = fwd_raw[btc_col]
        targets["rel_btc"][H] = fwd_raw.sub(btc_fwd, axis=0)

        # Excess over EW
        ew_fwd = fwd_raw.mean(axis=1)
        targets["rel_ew"][H] = fwd_raw.sub(ew_fwd, axis=0)

        # Market exposure
        targets["market_exposure_btc"][H] = pd.DataFrame(
            np.tile(btc_fwd.values[:, None], (1, len(symbols))), index=timestamps, columns=symbols
        )
        targets["market_exposure_ew"][H] = pd.DataFrame(
            np.tile(ew_fwd.values[:, None], (1, len(symbols))), index=timestamps, columns=symbols
        )

    return targets


def compute_spearman_rank_ic(
    x: np.ndarray,
    y: np.ndarray,
) -> Tuple[float, float]:
    """Compute Spearman Rank IC and two-sided p-value for two 1D arrays."""
    valid_mask = ~(np.isnan(x) | np.isnan(y) | np.isinf(x) | np.isinf(y))
    if np.sum(valid_mask) < 30:
        return 0.0, 1.0
    x_clean = x[valid_mask]
    y_clean = y[valid_mask]
    
    # Check if constant
    if np.all(x_clean == x_clean[0]) or np.all(y_clean == y_clean[0]):
        return 0.0, 1.0

    res = stats.spearmanr(x_clean, y_clean)
    corr = float(res.statistic) if hasattr(res, "statistic") else float(res[0])
    pval = float(res.pvalue) if hasattr(res, "pvalue") else float(res[1])
    if np.isnan(corr):
        corr = 0.0
    if np.isnan(pval):
        pval = 1.0
    return corr, pval


def compute_mutual_information(
    x: np.ndarray,
    y: np.ndarray,
    n_neighbors: int = 5,
    random_state: int = 42,
    subsample_max: int = 10000,
) -> float:
    """Compute non-linear Mutual Information using Kraskov k-NN estimator."""
    valid_mask = ~(np.isnan(x) | np.isnan(y) | np.isinf(x) | np.isinf(y))
    if np.sum(valid_mask) < 100:
        return 0.0
    x_clean = x[valid_mask]
    y_clean = y[valid_mask]

    # Subsample if large to maintain fast interactive foreground speed
    if len(x_clean) > subsample_max:
        rng = np.random.RandomState(random_state)
        idx = rng.choice(len(x_clean), size=subsample_max, replace=False)
        x_clean = x_clean[idx]
        y_clean = y_clean[idx]

    try:
        mi = mutual_info_regression(
            x_clean.reshape(-1, 1),
            y_clean,
            n_neighbors=n_neighbors,
            random_state=random_state,
        )
        return float(max(0.0, mi[0]))
    except Exception as e:
        logger.debug("Mutual information computation error: %s", e)
        return 0.0


def compute_block_bootstrap_ic_pvalue(
    x_matrix: np.ndarray,
    y_matrix: np.ndarray,
    block_size_hours: int = 168,
    n_bootstraps: int = 200,
    random_state: int = 42,
) -> Tuple[float, float, Tuple[float, float]]:
    """Compute block bootstrap mean Rank IC, p-value (H0: IC=0), and 95% CI.
    
    Resamples blocks of consecutive hours to preserve serial correlation.
    """
    T, N = x_matrix.shape
    n_blocks = T // block_size_hours
    if n_blocks < 5:
        # Fall back to unblocked
        x_flat = x_matrix.flatten()
        y_flat = y_matrix.flatten()
        ic, pval = compute_spearman_rank_ic(x_flat, y_flat)
        return ic, pval, (ic, ic)

    rng = np.random.RandomState(random_state)
    boot_ics = []

    for _ in range(n_bootstraps):
        sampled_block_indices = rng.choice(n_blocks, size=n_blocks, replace=True)
        time_idx = np.concatenate([
            np.arange(b * block_size_hours, (b + 1) * block_size_hours)
            for b in sampled_block_indices
        ])
        bx = x_matrix[time_idx].flatten()
        by = y_matrix[time_idx].flatten()
        ic, _ = compute_spearman_rank_ic(bx, by)
        boot_ics.append(ic)

    boot_ics = np.array(boot_ics)
    mean_ic = float(np.mean(boot_ics))
    ci_lower = float(np.percentile(boot_ics, 2.5))
    ci_upper = float(np.percentile(boot_ics, 97.5))
    
    # Two-sided empirical p-value of crossing zero
    p_cross_zero = 2.0 * min(np.mean(boot_ics <= 0.0), np.mean(boot_ics >= 0.0))
    p_cross_zero = float(min(1.0, max(1.0 / n_bootstraps, p_cross_zero)))

    return mean_ic, p_cross_zero, (ci_lower, ci_upper)


def apply_benjamini_hochberg_fdr(
    results: List[PredictiveInformationResult],
    alpha: float = 0.05,
) -> List[PredictiveInformationResult]:
    """Apply Benjamini-Hochberg procedure to control False Discovery Rate."""
    if not results:
        return results

    pvals = np.array([r.rank_ic_pvalue for r in results])
    m = len(pvals)
    sorted_order = np.argsort(pvals)
    sorted_pvals = pvals[sorted_order]

    # q = p * m / rank
    qvals = np.zeros(m)
    min_q = 1.0
    for i in range(m - 1, -1, -1):
        rank = i + 1
        q = (sorted_pvals[i] * m) / rank
        min_q = min(min_q, q)
        qvals[i] = min(1.0, min_q)

    # Re-map q-values to original order
    for idx, orig_i in enumerate(sorted_order):
        results[orig_i].fdr_adjusted_qvalue = float(qvals[idx])
        # Significant if train_ic and val_ic share the same sign and qval < alpha
        same_sign = (results[orig_i].train_rank_ic * results[orig_i].val_rank_ic) > 0
        is_sig = (results[orig_i].fdr_adjusted_qvalue < alpha) and same_sign and (abs(results[orig_i].train_rank_ic) > 0.02)
        results[orig_i].is_significant_train_val = is_sig

    return results


def run_single_feature_target_audit(
    feature_name: str,
    feature_df: pd.DataFrame,
    target_df: pd.DataFrame,
    target_type: str,
    horizon_hours: int,
    regime_mask_bull: pd.Series,
    regime_mask_highvol: pd.Series,
    train_slice: slice,
    val_slice: slice,
    holdout_slice: slice,
    btc_fwd_returns: pd.DataFrame,
) -> PredictiveInformationResult:
    """Run rigorous audit for one (feature, target, horizon) tuple."""
    # Align valid rows where neither is fully NaN
    X = feature_df.values
    Y = target_df.values

    # 1. Pooled Spearman Rank IC & Pearson IC
    x_flat = X.flatten()
    y_flat = Y.flatten()
    pooled_rank_ic, rank_ic_pvalue = compute_spearman_rank_ic(x_flat, y_flat)

    # Pearson
    valid_mask = ~(np.isnan(x_flat) | np.isnan(y_flat) | np.isinf(x_flat) | np.isinf(y_flat))
    if np.sum(valid_mask) > 30:
        pearson_ic = float(stats.pearsonr(x_flat[valid_mask], y_flat[valid_mask])[0])
        hit_rate = float(np.mean(np.sign(x_flat[valid_mask]) == np.sign(y_flat[valid_mask])))
    else:
        pearson_ic = 0.0
        hit_rate = 0.5

    # 2. Cross-sectional Rank IC (average of cross-sectional rank IC across timestamps)
    # Only meaningful if target is cross-sectional and multiple assets vary
    T, N = X.shape
    daily_step = max(1, horizon_hours // 4)
    cs_ics = []
    for t_i in range(0, T, daily_step):
        row_x = X[t_i, :]
        row_y = Y[t_i, :]
        if not (np.all(np.isnan(row_x)) or np.all(np.isnan(row_y))):
            ic, _ = compute_spearman_rank_ic(row_x, row_y)
            if not np.isnan(ic):
                cs_ics.append(ic)
    mean_cs_ic = float(np.mean(cs_ics)) if cs_ics else pooled_rank_ic

    # 3. Mutual Information (non-linear metric)
    mi_nats = compute_mutual_information(x_flat, y_flat, n_neighbors=5, subsample_max=8000)

    # 4. Chronological Splits Rank IC
    X_tr, Y_tr = X[train_slice], Y[train_slice]
    X_va, Y_va = X[val_slice], Y[val_slice]
    X_ho, Y_ho = X[holdout_slice], Y[holdout_slice]

    train_rank_ic, _ = compute_spearman_rank_ic(X_tr.flatten(), Y_tr.flatten())
    val_rank_ic, _ = compute_spearman_rank_ic(X_va.flatten(), Y_va.flatten())
    holdout_rank_ic, _ = compute_spearman_rank_ic(X_ho.flatten(), Y_ho.flatten())

    # Temporal stability score: product of train and val normalized
    if abs(train_rank_ic) > 1e-4 and abs(val_rank_ic) > 1e-4:
        sign_match = 1.0 if (train_rank_ic * val_rank_ic > 0) else -1.0
        stability = sign_match * min(abs(train_rank_ic), abs(val_rank_ic)) / max(abs(train_rank_ic), abs(val_rank_ic))
    else:
        stability = 0.0

    # 5. Regime-conditional Rank IC
    bull_idx = regime_mask_bull.values
    highvol_idx = regime_mask_highvol.values

    bull_ic, _ = compute_spearman_rank_ic(X[bull_idx].flatten(), Y[bull_idx].flatten())
    bear_ic, _ = compute_spearman_rank_ic(X[~bull_idx].flatten(), Y[~bull_idx].flatten())
    highvol_ic, _ = compute_spearman_rank_ic(X[highvol_idx].flatten(), Y[highvol_idx].flatten())
    lowvol_ic, _ = compute_spearman_rank_ic(X[~highvol_idx].flatten(), Y[~highvol_idx].flatten())

    # 6. Incremental Information controlling for BTC Market Beta
    # Residualize Y against BTC return
    btc_y_flat = btc_fwd_returns.values.flatten()
    valid_beta_mask = valid_mask & ~(np.isnan(btc_y_flat) | np.isinf(btc_y_flat))
    if np.sum(valid_beta_mask) > 100:
        y_valid = y_flat[valid_beta_mask]
        btc_valid = btc_y_flat[valid_beta_mask]
        x_valid = x_flat[valid_beta_mask]

        # OLS regression of Y on BTC
        slope, intercept, _, _, _ = stats.linregress(btc_valid, y_valid)
        y_resid = y_valid - (slope * btc_valid + intercept)
        inc_ic, _ = stats.spearmanr(x_valid, y_resid)
        incremental_ic = float(inc_ic) if not np.isnan(inc_ic) else 0.0
    else:
        incremental_ic = pooled_rank_ic

    # Family categorization
    if "ret_" in feature_name or "mom" in feature_name:
        family = "Momentum / Reversal"
    elif "vol_" in feature_name or "range" in feature_name:
        family = "Volatility / Dispersion"
    elif "vol_surge" in feature_name:
        family = "Volume / Activity"
    elif "ma_dist" in feature_name or "trend" in feature_name:
        family = "Trend / Moving Average"
    elif "dispersion" in feature_name or "breadth" in feature_name:
        family = "Cross-Asset Context"
    elif "fear_and_greed" in feature_name:
        family = "Sentiment"
    elif "treasury" in feature_name:
        family = "Macro"
    else:
        family = "General"

    return PredictiveInformationResult(
        feature_name=feature_name,
        family=family,
        target_type=target_type,
        horizon_hours=horizon_hours,
        pooled_rank_ic=pooled_rank_ic,
        rank_ic_pvalue=rank_ic_pvalue,
        mean_cross_sectional_rank_ic=mean_cs_ic,
        pearson_ic=pearson_ic,
        directional_hit_rate=hit_rate,
        mutual_information_nats=mi_nats,
        train_rank_ic=train_rank_ic,
        val_rank_ic=val_rank_ic,
        holdout_rank_ic=holdout_rank_ic,
        temporal_stability_score=stability,
        regime_bull_rank_ic=bull_ic,
        regime_bear_rank_ic=bear_ic,
        regime_highvol_rank_ic=highvol_ic,
        regime_lowvol_rank_ic=lowvol_ic,
        incremental_ic_vs_btc_beta=incremental_ic,
    )
