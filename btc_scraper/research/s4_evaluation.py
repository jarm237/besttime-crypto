"""S4-P1C Evaluation Engine: Frozen Artifact Loader, Paired Inference, and Preregistered Metrics.

Frozen specification: research/s4_forecast_information_screening/s4_p0_executable_preregistration.md
Frozen commit: 7b5a97becbd6da1249a484ed588133761cc57bd0
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import joblib
import numpy as np
import pandas as pd
import torch

from btc_scraper.research.s4_dataset_audit import (
    AUDIT_END,
    AUDIT_START,
    UNIVERSE,
    sha256_file,
)
from btc_scraper.research.s4_forecast import (
    INPUT_ASSETS,
    INPUT_FEATURES,
    INPUT_HOURS,
    LAST_SCREEN_DECISION,
    MAX_TRAINABLE_PARAMETERS,
    S4_PREREGISTRATION_COMMIT,
    CausalSigmaNormalizer,
    ChronologicalSplitter,
    FeatureScaler,
    ForecastError,
    ProtocolViolationError,
    RidgeBaseline,
    UnifiedNeuralForecaster,
    build_causal_partitions,
    build_neural_forecaster,
)

EXPECTED_FROZEN_HASHES = {
    "neural_forecaster.pt": "9eb90134e9bec5b2c2cede72cebf3d815a4cfc088d48d5d51bad16c9c352280a",
    "ridge_baseline.joblib": "647f718d2b6d2bf3b56faf0dfdd430a488f228ded7c7ffe4bf931e2afe371fe1",
    "feature_scaler.json": "97066d059fee3b50bffdbd8629fd2f7a7d2b0a025907ef040041edb9adec0c09",
    "sigma_floors.json": "d001797d07d3738592ab47f877ba5c892d37a69cab6fbed5936a79e29394d697",
}

EXPECTED_NEURAL_PARAMS = 2289
EXPECTED_RIDGE_ALPHA = 10000.0
SPREAD_THRESHOLD_BPS = 0.0024  # 24 bps


@dataclass(frozen=True)
class FrozenModels:
    neural_model: UnifiedNeuralForecaster
    ridge_model: RidgeBaseline
    scaler: FeatureScaler
    sigma_floors: dict[str, float]
    artifact_hashes: dict[str, str]


def verify_and_load_frozen_artifacts(evidence_dir: Path) -> FrozenModels:
    """Verify SHA-256 hashes of all frozen artifacts before loading.

    Fails closed on any mismatch or parameter drift.
    """
    actual_hashes: dict[str, str] = {}
    for filename, expected_hash in EXPECTED_FROZEN_HASHES.items():
        artifact_path = evidence_dir / filename
        if not artifact_path.is_file():
            raise ProtocolViolationError(f"Missing frozen artifact: {artifact_path}")
        actual_hash = sha256_file(artifact_path)
        if actual_hash != expected_hash:
            raise ProtocolViolationError(
                f"Frozen artifact SHA-256 mismatch for {filename}:\n"
                f"  Expected: {expected_hash}\n"
                f"  Actual:   {actual_hash}"
            )
        actual_hashes[filename] = actual_hash

    # Load FeatureScaler
    scaler_data = json.loads((evidence_dir / "feature_scaler.json").read_text(encoding="utf-8"))
    scaler = FeatureScaler.from_dict(scaler_data)

    # Load Sigma Floors
    floors_data = json.loads((evidence_dir / "sigma_floors.json").read_text(encoding="utf-8"))
    sigma_floors = {k: float(v) for k, v in floors_data.items()}

    # Load Ridge
    raw_ridge = joblib.load(evidence_dir / "ridge_baseline.joblib")
    if getattr(raw_ridge, "alpha", None) != EXPECTED_RIDGE_ALPHA:
        raise ProtocolViolationError(
            f"Ridge alpha mismatch: expected {EXPECTED_RIDGE_ALPHA}, got {getattr(raw_ridge, 'alpha', None)}"
        )
    ridge_baseline = RidgeBaseline(alpha=EXPECTED_RIDGE_ALPHA)
    ridge_baseline.model = raw_ridge

    # Load Neural Forecaster
    neural_model = build_neural_forecaster(seed=42)
    state_dict = torch.load(evidence_dir / "neural_forecaster.pt", map_location="cpu", weights_only=True)
    neural_model.load_state_dict(state_dict)
    neural_model.eval()

    param_count = neural_model.count_parameters()
    if param_count != EXPECTED_NEURAL_PARAMS:
        raise ProtocolViolationError(
            f"Neural parameter count mismatch: expected {EXPECTED_NEURAL_PARAMS}, got {param_count}"
        )

    return FrozenModels(
        neural_model=neural_model,
        ridge_model=ridge_baseline,
        scaler=scaler,
        sigma_floors=sigma_floors,
        artifact_hashes=actual_hashes,
    )


def compute_pearson_ic(pred: np.ndarray, target: np.ndarray) -> float:
    """Compute Pearson correlation between 1D predicted and realized target series."""
    if len(pred) != len(target):
        raise ForecastError(f"Length mismatch: {len(pred)} != {len(target)}")
    if len(pred) < 3:
        raise ForecastError(f"Insufficient samples for correlation: {len(pred)}")
    p_dev = pred - np.mean(pred)
    t_dev = target - np.mean(target)
    p_var = np.sum(p_dev ** 2)
    t_var = np.sum(t_dev ** 2)
    if p_var <= 1e-14 or t_var <= 1e-14:
        raise ForecastError("Zero variance encountered in correlation series")
    r = float(np.sum(p_dev * t_dev) / np.sqrt(p_var * t_var))
    return float(np.clip(r, -1.0, 1.0))


def fisher_z_aggregate(ics: Sequence[float]) -> float:
    """Aggregate per-asset correlations using Fisher-z transformation: tanh(mean(atanh(IC_i)))."""
    if len(ics) == 0:
        raise ForecastError("Empty IC list for Fisher-z aggregation")
    # Clip IC slightly within (-1, 1) to avoid inf in atanh
    clipped_ics = [np.clip(float(ic), -0.999999, 0.999999) for ic in ics]
    z_vals = [math.atanh(ic) for ic in clipped_ics]
    return float(math.tanh(sum(z_vals) / len(z_vals)))


@dataclass(frozen=True)
class PrimaryStatistics:
    per_asset_neural_ic: dict[str, float]
    per_asset_ridge_ic: dict[str, float]
    s_neural: float
    s_ridge: float
    delta_s: float


def compute_primary_statistics(
    realized_z: np.ndarray,  # [N, 4] raw unclipped standardized target
    neural_zhat: np.ndarray,  # [N, 4]
    ridge_zhat: np.ndarray,  # [N, 4]
    universe: Sequence[str] = UNIVERSE,
) -> PrimaryStatistics:
    """Compute per-asset ICs, Fisher-z S(Neural), S(Ridge), and Delta_S."""
    if realized_z.shape != neural_zhat.shape or realized_z.shape != ridge_zhat.shape:
        raise ForecastError("Shape mismatch in primary statistics arrays")
    num_assets = len(universe)

    neural_ics = {}
    ridge_ics = {}
    for i, symbol in enumerate(universe):
        neural_ics[symbol] = compute_pearson_ic(neural_zhat[:, i], realized_z[:, i])
        ridge_ics[symbol] = compute_pearson_ic(ridge_zhat[:, i], realized_z[:, i])

    s_neural = fisher_z_aggregate(list(neural_ics.values()))
    s_ridge = fisher_z_aggregate(list(ridge_ics.values()))
    delta_s = s_neural - s_ridge

    return PrimaryStatistics(
        per_asset_neural_ic=neural_ics,
        per_asset_ridge_ic=ridge_ics,
        s_neural=s_neural,
        s_ridge=s_ridge,
        delta_s=delta_s,
    )


@dataclass(frozen=True)
class BootstrapResult:
    block_length: float
    n_draws: int
    seed: int
    valid_draws_count: int
    invalid_draws_count: int
    mean_delta_s: float
    std_delta_s: float
    ci_lower_95: float
    ci_upper_95: float


def paired_stationary_bootstrap(
    realized_z: np.ndarray,  # [N, 4]
    neural_zhat: np.ndarray,  # [N, 4]
    ridge_zhat: np.ndarray,  # [N, 4]
    block_length: float = 14.0,
    n_draws: int = 2000,
    seed: int = 42,
) -> BootstrapResult:
    """Paired stationary bootstrap (Politis-Romano 1994) with circular date indexing.

    Resamples joint date vector preserving contemporaneous cross-asset and model dependence.
    Reports two-sided 95% percentile confidence interval.
    """
    n_obs = len(realized_z)
    if n_obs < 30:
        raise ForecastError(f"Insufficient samples for bootstrap: {n_obs}")

    p = 1.0 / float(block_length)
    rng = np.random.default_rng(seed)

    deltas: list[float] = []
    invalid_count = 0

    for _ in range(n_draws):
        idx = np.empty(n_obs, dtype=int)
        idx[0] = rng.integers(0, n_obs)
        rands = rng.random(n_obs - 1)
        new_starts = rng.integers(0, n_obs, size=n_obs - 1)
        for i in range(1, n_obs):
            idx[i] = new_starts[i - 1] if rands[i - 1] < p else (idx[i - 1] + 1) % n_obs

        y_b = realized_z[idx]
        zn_b = neural_zhat[idx]
        zr_b = ridge_zhat[idx]

        # Check for zero variance
        y_dev = y_b - y_b.mean(axis=0)
        zn_dev = zn_b - zn_b.mean(axis=0)
        zr_dev = zr_b - zr_b.mean(axis=0)

        y_var = np.sum(y_dev ** 2, axis=0)
        zn_var = np.sum(zn_dev ** 2, axis=0)
        zr_var = np.sum(zr_dev ** 2, axis=0)

        if (y_var <= 1e-14).any() or (zn_var <= 1e-14).any() or (zr_var <= 1e-14).any():
            invalid_count += 1
            continue

        ic_n = np.sum(zn_dev * y_dev, axis=0) / np.sqrt(zn_var * y_var)
        ic_r = np.sum(zr_dev * y_dev, axis=0) / np.sqrt(zr_var * y_var)

        if not np.isfinite(ic_n).all() or not np.isfinite(ic_r).all():
            invalid_count += 1
            continue

        s_n = np.tanh(np.mean(np.arctanh(np.clip(ic_n, -0.999999, 0.999999))))
        s_r = np.tanh(np.mean(np.arctanh(np.clip(ic_r, -0.999999, 0.999999))))
        deltas.append(float(s_n - s_r))

    if len(deltas) < 0.99 * n_draws:
        raise ForecastError(f"Too many invalid bootstrap draws: {invalid_count} / {n_draws} (>1%)")

    deltas_arr = np.array(deltas, dtype=float)
    ci_lower, ci_upper = np.percentile(deltas_arr, [2.5, 97.5])

    return BootstrapResult(
        block_length=block_length,
        n_draws=n_draws,
        seed=seed,
        valid_draws_count=len(deltas),
        invalid_draws_count=invalid_count,
        mean_delta_s=float(np.mean(deltas_arr)),
        std_delta_s=float(np.std(deltas_arr, ddof=1)),
        ci_lower_95=float(ci_lower),
        ci_upper_95=float(ci_upper),
    )


def decompose_common_and_relative(
    realized_z: np.ndarray,  # [N, 4]
    neural_zhat: np.ndarray,  # [N, 4]
    ridge_zhat: np.ndarray,  # [N, 4]
    universe: Sequence[str] = UNIVERSE,
) -> dict[str, object]:
    """Common-market vs relative signal decomposition:

    1. Common market correlation: time-series correlation of contemporaneous cross-asset means.
    2. Relative signal IC: subtract contemporaneous cross-asset mean per date, compute asset ICs and Fisher-z aggregate.
    """
    # Cross-asset means per date [N]
    z_bar = realized_z.mean(axis=1)
    zn_bar = neural_zhat.mean(axis=1)
    zr_bar = ridge_zhat.mean(axis=1)

    common_ic_neural = compute_pearson_ic(zn_bar, z_bar)
    common_ic_ridge = compute_pearson_ic(zr_bar, z_bar)

    # Relative signals [N, 4]
    z_rel = realized_z - z_bar[:, None]
    zn_rel = neural_zhat - zn_bar[:, None]
    zr_rel = ridge_zhat - zr_bar[:, None]

    rel_ic_neural = {}
    rel_ic_ridge = {}
    for i, symbol in enumerate(universe):
        rel_ic_neural[symbol] = compute_pearson_ic(zn_rel[:, i], z_rel[:, i])
        rel_ic_ridge[symbol] = compute_pearson_ic(zr_rel[:, i], z_rel[:, i])

    rel_s_neural = fisher_z_aggregate(list(rel_ic_neural.values()))
    rel_s_ridge = fisher_z_aggregate(list(rel_ic_ridge.values()))
    rel_delta_s = rel_s_neural - rel_s_ridge

    return {
        "common_market_ic_neural": common_ic_neural,
        "common_market_ic_ridge": common_ic_ridge,
        "common_market_delta_ic": common_ic_neural - common_ic_ridge,
        "per_asset_relative_ic_neural": rel_ic_neural,
        "per_asset_relative_ic_ridge": rel_ic_ridge,
        "relative_s_neural": rel_s_neural,
        "relative_s_ridge": rel_s_ridge,
        "relative_delta_s": rel_delta_s,
    }


def mincer_zarnowitz_calibration(
    realized_y: np.ndarray,  # [N, 4] unclipped return scale
    pred_y: np.ndarray,  # [N, 4] unclipped return scale (zhat * sigma)
    universe: Sequence[str] = UNIVERSE,
) -> dict[str, dict[str, float]]:
    """Mincer-Zarnowitz OLS regression per asset: y = alpha + beta * yhat + error on unclipped return scale."""
    n_obs = len(realized_y)
    results = {}
    for i, symbol in enumerate(universe):
        x = pred_y[:, i]
        y = realized_y[:, i]

        x_bar = float(np.mean(x))
        y_bar = float(np.mean(y))

        x_dev = x - x_bar
        y_dev = y - y_bar

        var_x = float(np.sum(x_dev ** 2))
        cov_xy = float(np.sum(x_dev * y_dev))

        if var_x <= 1e-14:
            raise ForecastError(f"Zero variance in Mincer-Zarnowitz forecast for {symbol}")

        beta = cov_xy / var_x
        alpha = y_bar - beta * x_bar

        residuals = y - (alpha + beta * x)
        ss_res = float(np.sum(residuals ** 2))
        ss_tot = float(np.sum(y_dev ** 2))

        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-14 else 0.0
        s_err = math.sqrt(ss_res / max(n_obs - 2, 1))
        se_beta = s_err / math.sqrt(var_x)

        results[symbol] = {
            "alpha": alpha,
            "beta": beta,
            "se_beta": se_beta,
            "r_squared": r_squared,
            "mean_y_bps": y_bar * 10000.0,
            "std_y_bps": float(np.std(y, ddof=1)) * 10000.0,
            "mean_yhat_bps": x_bar * 10000.0,
            "std_yhat_bps": float(np.std(x, ddof=1)) * 10000.0,
        }
    return results


def btc_relative_spread_diagnostics(
    realized_y: np.ndarray,  # [N, 4] (BTC=0, ETH=1, SOL=2, BNB=3)
    neural_yhat: np.ndarray,  # [N, 4]
    ridge_yhat: np.ndarray,  # [N, 4]
    universe: Sequence[str] = UNIVERSE,
    threshold: float = SPREAD_THRESHOLD_BPS,
) -> dict[str, dict[str, object]]:
    """BTC-relative spread sign accuracy for ETH-BTC, SOL-BTC, BNB-BTC.

    Evaluated strictly on dates where |predicted spread| > threshold (0.0024 = 24 bps).
    """
    btc_idx = universe.index("BTCUSDT")
    results = {}

    for i, symbol in enumerate(universe):
        if symbol == "BTCUSDT":
            continue
        pair_name = f"{symbol.replace('USDT', '')}-BTC"

        # Realized spread
        actual_spread = realized_y[:, i] - realized_y[:, btc_idx]
        neural_spread = neural_yhat[:, i] - neural_yhat[:, btc_idx]
        ridge_spread = ridge_yhat[:, i] - ridge_yhat[:, btc_idx]

        # Neural evaluation
        neural_eligible = np.abs(neural_spread) > threshold
        n_neural_eligible = int(np.sum(neural_eligible))
        if n_neural_eligible > 0:
            neural_correct = (np.sign(neural_spread[neural_eligible]) == np.sign(actual_spread[neural_eligible])).sum()
            neural_acc = float(neural_correct / n_neural_eligible)
        else:
            neural_acc = float("nan")

        # Ridge evaluation
        ridge_eligible = np.abs(ridge_spread) > threshold
        n_ridge_eligible = int(np.sum(ridge_eligible))
        if n_ridge_eligible > 0:
            ridge_correct = (np.sign(ridge_spread[ridge_eligible]) == np.sign(actual_spread[ridge_eligible])).sum()
            ridge_acc = float(ridge_correct / n_ridge_eligible)
        else:
            ridge_acc = float("nan")

        results[pair_name] = {
            "threshold_bps": threshold * 10000.0,
            "total_dates": len(realized_y),
            "neural": {
                "eligible_dates": n_neural_eligible,
                "coverage_pct": float(n_neural_eligible / len(realized_y) * 100.0),
                "sign_accuracy_pct": float(neural_acc * 100.0) if np.isfinite(neural_acc) else None,
            },
            "ridge": {
                "eligible_dates": n_ridge_eligible,
                "coverage_pct": float(n_ridge_eligible / len(realized_y) * 100.0),
                "sign_accuracy_pct": float(ridge_acc * 100.0) if np.isfinite(ridge_acc) else None,
            },
        }
    return results


def extreme_day_sensitivity(
    decisions: Sequence[pd.Timestamp],
    realized_y: np.ndarray,  # [N, 4] raw log returns
    realized_z: np.ndarray,  # [N, 4] raw unclipped z
    neural_zhat: np.ndarray,  # [N, 4]
    ridge_zhat: np.ndarray,  # [N, 4]
    drop_pct: float = 0.05,
) -> dict[str, object]:
    """Drop exactly ceil(0.05 * N) days with largest absolute equal-weight average raw log return.

    Ties broken by ascending UTC date. Recomputes S and Delta_S.
    """
    n_obs = len(decisions)
    n_drop = math.ceil(drop_pct * n_obs)

    # Equal-weight average of raw execution returns
    mean_y = np.mean(realized_y, axis=1)
    abs_mean_y = np.abs(mean_y)

    # Create sort records: (-abs_return, date)
    sort_keys = [(-abs_mean_y[i], pd.Timestamp(decisions[i])) for i in range(n_obs)]
    sorted_indices = sorted(range(n_obs), key=lambda i: sort_keys[i])

    dropped_indices = set(sorted_indices[:n_drop])
    kept_indices = [i for i in range(n_obs) if i not in dropped_indices]

    kept_realized_z = realized_z[kept_indices]
    kept_neural_zhat = neural_zhat[kept_indices]
    kept_ridge_zhat = ridge_zhat[kept_indices]

    stats = compute_primary_statistics(kept_realized_z, kept_neural_zhat, kept_ridge_zhat)

    return {
        "dropped_count": n_drop,
        "kept_count": len(kept_indices),
        "dropped_dates": [decisions[i].isoformat() for i in sorted(dropped_indices)],
        "s_neural": stats.s_neural,
        "s_ridge": stats.s_ridge,
        "delta_s": stats.delta_s,
    }


def evaluate_scientific_verdict(
    n_common: int,
    s_neural: float,
    ci_lower_14d: float,
    ci_upper_14d: float,
    mz_slopes: Sequence[float],
    extreme_excluded_delta_s: float,
    protocol_valid: bool = True,
) -> tuple[str, dict[str, bool]]:
    """Apply the frozen precommitted three-state scientific decision logic.

    SUPPORTED requires ALL:
      (a) n_common >= 300
      (b) s_neural > 0
      (c) primary 14-day 95% CI lower bound for Delta_S strictly > 0
      (d) finite per-asset MZ slopes, at least 3 of 4 positive AND median positive
      (e) extreme-day-excluded Delta_S > 0
      (f) protocol_valid is True

    NOT_SUPPORTED if protocol_valid and (s_neural <= 0 or ci_upper_14d <= 0).

    INCONCLUSIVE for all other valid screen cases.
    INVALID_PROTOCOL if protocol_valid is False.
    """
    if not protocol_valid:
        return "INVALID_PROTOCOL", {}

    checks = {
        "n_common_gte_300": bool(n_common >= 300),
        "s_neural_gt_zero": bool(s_neural > 0.0),
        "ci_lower_14d_gt_zero": bool(ci_lower_14d > 0.0),
        "mz_slopes_corroborated": bool(
            sum(1 for s in mz_slopes if s > 0.0) >= 3 and float(np.median(mz_slopes)) > 0.0
        ),
        "extreme_excluded_delta_s_gt_zero": bool(extreme_excluded_delta_s > 0.0),
        "protocol_integrity_valid": bool(protocol_valid),
    }

    if all(checks.values()):
        verdict = "STAGE1_SIGNAL_SUPPORTED"
    elif s_neural <= 0.0 or ci_upper_14d <= 0.0:
        verdict = "STAGE1_SIGNAL_NOT_SUPPORTED"
    else:
        verdict = "STAGE1_SIGNAL_INCONCLUSIVE"

    return verdict, checks
