"""
btc_scraper/research/ml_payoff_sizing/payoff_regressors.py

Implements Purged Walk-Forward training for Ridge and Huber regressors
predicting continuous net payoff (in bps) with strict inner-CV hyperparameter selection.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import numpy as np
from scipy import stats
from sklearn.linear_model import HuberRegressor, Ridge
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.preprocessing import StandardScaler

from btc_scraper.research.ml_trade_quality.feature_contract import FEATURE_NAMES
from btc_scraper.research.walk_forward_lab import WalkForwardFold


def select_inner_alpha(
    X_train: np.ndarray,
    y_train: np.ndarray,
    model_type: str = "ridge",
    candidate_alphas: Sequence[float] = (1.0, 10.0, 100.0, 500.0),
    n_splits: int = 3,
) -> float:
    """Selects regularization alpha using strictly inner time-series splits of the training fold."""
    n = len(y_train)
    if n < 30:
        return 100.0

    split_size = n // (n_splits + 1)
    errors = {a: [] for a in candidate_alphas}

    for s in range(1, n_splits + 1):
        idx_train = slice(0, s * split_size)
        idx_val = slice(s * split_size, (s + 1) * split_size)

        X_tr, y_tr = X_train[idx_train], y_train[idx_train]
        X_va, y_va = X_train[idx_val], y_train[idx_val]

        sc = StandardScaler()
        X_tr_sc = sc.fit_transform(X_tr)
        X_va_sc = sc.transform(X_va)

        for a in candidate_alphas:
            if model_type == "ridge":
                reg = Ridge(alpha=a, random_state=42)
            else:
                reg = HuberRegressor(alpha=a, epsilon=1.35, max_iter=1000)

            try:
                reg.fit(X_tr_sc, y_tr)
                preds = reg.predict(X_va_sc)
                mae = float(mean_absolute_error(y_va, preds))
                errors[a].append(mae)
            except Exception:
                errors[a].append(float("inf"))

    best_a = 100.0
    min_err = float("inf")
    for a in candidate_alphas:
        avg_err = float(np.mean(errors[a])) if errors[a] else float("inf")
        if avg_err < min_err:
            min_err = avg_err
            best_a = a

    return float(best_a)


class PurgedWalkForwardPayoffTrainer:
    """Trains Ridge and Huber regressors predicting continuous trade payoff (in bps)."""

    def __init__(self, folds: Sequence[WalkForwardFold]):
        self.folds = list(folds)
        self.trained_models: Dict[int, Dict[str, Any]] = {}
        self.oof_predictions: Dict[str, List[Dict[str, Any]]] = {"ridge": [], "huber": []}

    def train_and_evaluate(self, trade_dataset: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        fold_results = []
        oof_ridge = []
        oof_huber = []

        for fold in self.folds:
            fid = fold.fold_id
            t_train_start = fold.train_start
            t_train_end = fold.train_end
            t_val_start = fold.val_start
            t_val_end = fold.val_end

            # Purged training set (resolved before cutoff)
            train_trades = [
                t for t in trade_dataset
                if t["entry_time"] >= t_train_start and t["exit_time"] <= t_train_end
            ]

            # Validation set
            val_trades = [
                t for t in trade_dataset
                if t_val_start <= t["signal_time"] <= t_val_end
            ]

            if len(train_trades) < 20 or len(val_trades) == 0:
                continue

            X_train = np.array([[float(t["features"][f]) for f in FEATURE_NAMES] for t in train_trades])
            y_train = np.array([float(t["target_net_return_bps"]) for t in train_trades])

            X_val = np.array([[float(t["features"][f]) for f in FEATURE_NAMES] for t in val_trades])
            y_val = np.array([float(t["target_net_return_bps"]) for t in val_trades])

            scaler = StandardScaler()
            X_tr_sc = scaler.fit_transform(X_train)
            X_va_sc = scaler.transform(X_val)

            # Fit Ridge
            alpha_ridge = select_inner_alpha(X_train, y_train, model_type="ridge")
            ridge = Ridge(alpha=alpha_ridge, random_state=42)
            ridge.fit(X_tr_sc, y_train)
            pred_ridge_val = ridge.predict(X_va_sc)

            # Fit Huber
            alpha_huber = select_inner_alpha(X_train, y_train, model_type="huber")
            huber = HuberRegressor(alpha=alpha_huber, epsilon=1.35, max_iter=1000)
            huber.fit(X_tr_sc, y_train)
            pred_huber_val = huber.predict(X_va_sc)

            # Training fold quantiles for sizing calibration
            train_quantiles = {
                "mean": float(np.mean(y_train)),
                "std": float(np.std(y_train, ddof=1)) if len(y_train) > 1 else 1.0,
                "median": float(np.median(y_train)),
                "p10": float(np.percentile(y_train, 10.0)),
                "p25": float(np.percentile(y_train, 25.0)),
                "p75": float(np.percentile(y_train, 75.0)),
                "p90": float(np.percentile(y_train, 90.0)),
            }

            # Diagnostics for this fold
            sp_r, _ = stats.spearmanr(pred_ridge_val, y_val)
            sp_h, _ = stats.spearmanr(pred_huber_val, y_val)
            pe_r, _ = stats.pearsonr(pred_ridge_val, y_val)
            pe_h, _ = stats.pearsonr(pred_huber_val, y_val)

            mae_r = float(mean_absolute_error(y_val, pred_ridge_val))
            mae_h = float(mean_absolute_error(y_val, pred_huber_val))
            rmse_r = float(root_mean_squared_error(y_val, pred_ridge_val))
            rmse_h = float(root_mean_squared_error(y_val, pred_huber_val))

            bias_r = float(np.mean(pred_ridge_val) - np.mean(y_val))
            bias_h = float(np.mean(pred_huber_val) - np.mean(y_val))

            # Tail capture: top 10% predicted vs bottom 10% predicted
            k_tail = max(1, int(len(y_val) * 0.10))
            top_ridge_idx = np.argsort(pred_ridge_val)[-k_tail:]
            bot_ridge_idx = np.argsort(pred_ridge_val)[:k_tail]
            top_huber_idx = np.argsort(pred_huber_val)[-k_tail:]
            bot_huber_idx = np.argsort(pred_huber_val)[:k_tail]

            top_ridge_mean = float(np.mean(y_val[top_ridge_idx]))
            bot_ridge_mean = float(np.mean(y_val[bot_ridge_idx]))
            top_huber_mean = float(np.mean(y_val[top_huber_idx]))
            bot_huber_mean = float(np.mean(y_val[bot_huber_idx]))

            fold_info = {
                "fold_id": fid,
                "train_sample_size": len(train_trades),
                "val_sample_size": len(val_trades),
                "ridge": {
                    "selected_alpha": alpha_ridge,
                    "spearman_rho": round(sp_r, 4),
                    "pearson_r": round(pe_r, 4),
                    "mae_bps": round(mae_r, 2),
                    "rmse_bps": round(rmse_r, 2),
                    "mean_bias_bps": round(bias_r, 2),
                    "top_decile_realized_bps": round(top_ridge_mean, 2),
                    "bot_decile_realized_bps": round(bot_ridge_mean, 2),
                    "coefficients": {feat: round(float(c), 4) for feat, c in zip(FEATURE_NAMES, ridge.coef_)},
                },
                "huber": {
                    "selected_alpha": alpha_huber,
                    "spearman_rho": round(sp_h, 4),
                    "pearson_r": round(pe_h, 4),
                    "mae_bps": round(mae_h, 2),
                    "rmse_bps": round(rmse_h, 2),
                    "mean_bias_bps": round(bias_h, 2),
                    "top_decile_realized_bps": round(top_huber_mean, 2),
                    "bot_decile_realized_bps": round(bot_huber_mean, 2),
                    "coefficients": {feat: round(float(c), 4) for feat, c in zip(FEATURE_NAMES, huber.coef_)},
                },
            }
            fold_results.append(fold_info)

            # Record predictions for each validation trade
            for i, tr in enumerate(val_trades):
                base_info = {
                    "trade_id": tr["trade_id"],
                    "symbol": tr["symbol"],
                    "fold_id": fid,
                    "signal_time": tr["signal_time"],
                    "entry_time": tr["entry_time"],
                    "exit_time": tr["exit_time"],
                    "hold_bars": tr["hold_bars"],
                    "invested_notional": tr["invested_notional"],
                    "realized_net_pnl": tr["net_pnl_14bps"],
                    "realized_return_bps": tr["target_net_return_bps"],
                }
                oof_ridge.append({
                    **base_info,
                    "pred_payoff_bps": round(float(pred_ridge_val[i]), 2),
                })
                oof_huber.append({
                    **base_info,
                    "pred_payoff_bps": round(float(pred_huber_val[i]), 2),
                })

            # Store pack for backtesting
            self.trained_models[fid] = {
                "scaler": scaler,
                "ridge": ridge,
                "huber": huber,
                "train_quantiles": train_quantiles,
                "feature_names": FEATURE_NAMES,
            }

        self.oof_predictions["ridge"] = oof_ridge
        self.oof_predictions["huber"] = oof_huber

        return {
            "folds": fold_results,
            "predictions": self.oof_predictions,
        }
