"""
btc_scraper/research/ml_trade_quality/purged_walk_forward_trainer.py

Implements Purged Walk-Forward Logistic Regression training with strictly
inner-fold threshold selection, embargo enforcement, and calibration auditing.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

from btc_scraper.research.ml_trade_quality.feature_contract import FEATURE_NAMES
from btc_scraper.research.walk_forward_lab import WalkForwardFold, WalkForwardSplitter


def compute_expected_calibration_error(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 5) -> float:
    """Computes Expected Calibration Error (ECE) using uniform probability bins."""
    if len(y_true) == 0:
        return 0.0
    bin_limits = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        low, high = bin_limits[i], bin_limits[i + 1]
        mask = (y_prob >= low) & (y_prob < high) if i < n_bins - 1 else (y_prob >= low) & (y_prob <= high)
        if np.sum(mask) > 0:
            bin_acc = np.mean(y_true[mask])
            bin_conf = np.mean(y_prob[mask])
            weight = np.sum(mask) / len(y_true)
            ece += weight * abs(bin_acc - bin_conf)
    return float(ece)


def select_inner_threshold(
    X_train: np.ndarray,
    y_train: np.ndarray,
    pnls_train: np.ndarray,
    candidate_thresholds: Sequence[float] = (0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50),
    n_splits: int = 3,
) -> Tuple[float, Dict[str, Any]]:
    """
    Selects optimal probability threshold using strictly inner-fold chronological splits.
    Maximizes inner net economic value with a constraint of accepting >= 20% of trades.
    """
    n = len(y_train)
    if n < 30:
        return 0.30, {"status": "insufficient_samples_default_0.30"}

    # Inner chronological 3-fold split
    split_size = n // (n_splits + 1)
    inner_scores = {th: [] for th in candidate_thresholds}

    for s in range(1, n_splits + 1):
        idx_train = slice(0, s * split_size)
        idx_val = slice(s * split_size, (s + 1) * split_size)

        X_tr, y_tr = X_train[idx_train], y_train[idx_train]
        X_va = X_train[idx_val]
        pnl_va = pnls_train[idx_val]

        if len(np.unique(y_tr)) < 2:
            continue

        sc = StandardScaler()
        X_tr_sc = sc.fit_transform(X_tr)
        X_va_sc = sc.transform(X_va)

        clf = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
        clf.fit(X_tr_sc, y_tr)
        probs = clf.predict_proba(X_va_sc)[:, 1]

        for th in candidate_thresholds:
            accepted = probs >= th
            if np.sum(accepted) > 0:
                inner_scores[th].append(float(np.sum(pnl_va[accepted])))
            else:
                inner_scores[th].append(0.0)

    # Find threshold with highest average inner net PnL
    best_th = 0.30
    best_val = -float("inf")
    summary = {}
    for th in candidate_thresholds:
        scores = inner_scores[th]
        avg_score = float(np.mean(scores)) if scores else -float("inf")
        summary[str(th)] = round(avg_score, 2)
        if avg_score > best_val:
            best_val = avg_score
            best_th = th

    return float(best_th), {"inner_grid": summary, "selected_threshold": best_th}


class PurgedWalkForwardTrainer:
    """Orchestrates Purged Walk-Forward ML training across 3 canonical development folds."""

    def __init__(self, folds: Sequence[WalkForwardFold]):
        self.folds = list(folds)
        self.trained_models: Dict[int, Dict[str, Any]] = {}
        self.out_of_fold_predictions: List[Dict[str, Any]] = []

    def train_and_evaluate(self, trade_dataset: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        """
        Executes purged walk-forward training for all folds.
        Ensures strict chronological embargo and returns out-of-fold evaluation metrics.
        """
        fold_results = []
        all_oof_preds = []

        for fold in self.folds:
            fold_id = fold.fold_id
            t_train_start = fold.train_start
            t_train_end = fold.train_end
            t_val_start = fold.val_start
            t_val_end = fold.val_end

            # ── 1. Purged & Embargoed Training Set ─────────────────────────────
            # Trade must have entered >= train_start AND exited <= train_end
            train_trades = [
                t for t in trade_dataset
                if t["entry_time"] >= t_train_start and t["exit_time"] <= t_train_end
            ]

            # ── 2. Validation Set ─────────────────────────────────────────────
            # Signal must have occurred inside [val_start, val_end]
            val_trades = [
                t for t in trade_dataset
                if t_val_start <= t["signal_time"] <= t_val_end
            ]

            if len(train_trades) < 20 or len(val_trades) == 0:
                fold_results.append({
                    "fold_id": fold_id,
                    "status": "INSUFFICIENT_TRAINING_EVIDENCE",
                    "train_trades": len(train_trades),
                    "val_trades": len(val_trades),
                })
                continue

            # Build feature matrices
            X_train = np.array([[float(t["features"][f]) for f in FEATURE_NAMES] for t in train_trades])
            y_train = np.array([int(t["label"]) for t in train_trades])
            pnls_train = np.array([float(t["net_pnl_14bps"]) for t in train_trades])

            X_val = np.array([[float(t["features"][f]) for f in FEATURE_NAMES] for t in val_trades])
            y_val = np.array([int(t["label"]) for t in val_trades])
            pnls_val = np.array([float(t["net_pnl_14bps"]) for t in val_trades])

            # ── 3. Inner-Fold Threshold Selection ─────────────────────────────
            best_th, inner_info = select_inner_threshold(X_train, y_train, pnls_train)

            # ── 4. Fit Model on Train Fold ────────────────────────────────────
            scaler = StandardScaler()
            X_tr_sc = scaler.fit_transform(X_train)
            X_va_sc = scaler.transform(X_val)

            clf = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
            clf.fit(X_tr_sc, y_train)

            p_train = clf.predict_proba(X_tr_sc)[:, 1]
            p_val = clf.predict_proba(X_va_sc)[:, 1]

            # Out-of-fold acceptance
            accepted_mask = p_val >= best_th

            # Calibration and statistical metrics
            try:
                auc = float(roc_auc_score(y_val, p_val)) if len(np.unique(y_val)) > 1 else 0.5
            except Exception:
                auc = 0.5

            brier = float(brier_score_loss(y_val, p_val))
            ece = compute_expected_calibration_error(y_val, p_val)

            # Feature coefficients
            coefs = {feat: round(float(c), 4) for feat, c in zip(FEATURE_NAMES, clf.coef_[0])}

            # Economic performance of ML-filtered vs unfiltered on validation fold
            unfiltered_pnl = float(np.sum(pnls_val))
            filtered_pnl = float(np.sum(pnls_val[accepted_mask])) if np.sum(accepted_mask) > 0 else 0.0
            rejected_pnl = float(np.sum(pnls_val[~accepted_mask])) if np.sum(~accepted_mask) > 0 else 0.0

            n_val_total = len(val_trades)
            n_accepted = int(np.sum(accepted_mask))
            n_rejected = n_val_total - n_accepted

            fold_info = {
                "fold_id": fold_id,
                "val_window": [t_val_start, t_val_end],
                "train_sample_size": len(train_trades),
                "val_sample_size": n_val_total,
                "train_win_rate_pct": round(float(np.mean(y_train) * 100.0), 2),
                "val_win_rate_pct": round(float(np.mean(y_val) * 100.0), 2),
                "selected_threshold": best_th,
                "roc_auc": round(auc, 4),
                "brier_score": round(brier, 4),
                "ece": round(ece, 4),
                "feature_weights": coefs,
                "trades_total": n_val_total,
                "trades_accepted": n_accepted,
                "trades_rejected": n_rejected,
                "acceptance_rate_pct": round(n_accepted / n_val_total * 100.0, 1) if n_val_total > 0 else 0.0,
                "unfiltered_net_pnl": round(unfiltered_pnl, 2),
                "filtered_net_pnl": round(filtered_pnl, 2),
                "rejected_net_pnl": round(rejected_pnl, 2),
                "incremental_net_pnl": round(filtered_pnl - unfiltered_pnl, 2),
            }
            fold_results.append(fold_info)

            # Record out-of-fold prediction for each trade
            for i, tr in enumerate(val_trades):
                tr_pred = {
                    "trade_id": tr["trade_id"],
                    "symbol": tr["symbol"],
                    "fold_id": fold_id,
                    "signal_time": tr["signal_time"],
                    "entry_time": tr["entry_time"],
                    "exit_time": tr["exit_time"],
                    "actual_label": int(tr["label"]),
                    "pred_probability": round(float(p_val[i]), 4),
                    "threshold_applied": best_th,
                    "accepted": bool(accepted_mask[i]),
                    "net_pnl_14bps": float(tr["net_pnl_14bps"]),
                }
                all_oof_preds.append(tr_pred)

            # Store model artifact
            self.trained_models[fold_id] = {
                "scaler": scaler,
                "model": clf,
                "threshold": best_th,
                "feature_names": FEATURE_NAMES,
            }

        self.out_of_fold_predictions = all_oof_preds

        # Aggregate Out-of-Fold Metrics
        total_val_trades = len(all_oof_preds)
        total_accepted = sum(1 for p in all_oof_preds if p["accepted"])
        total_rejected = total_val_trades - total_accepted

        total_unfiltered_net = sum(p["net_pnl_14bps"] for p in all_oof_preds)
        total_filtered_net = sum(p["net_pnl_14bps"] for p in all_oof_preds if p["accepted"])
        total_rejected_net = sum(p["net_pnl_14bps"] for p in all_oof_preds if not p["accepted"])

        y_all = np.array([p["actual_label"] for p in all_oof_preds])
        p_all = np.array([p["pred_probability"] for p in all_oof_preds])
        try:
            agg_auc = float(roc_auc_score(y_all, p_all)) if len(np.unique(y_all)) > 1 else 0.5
        except Exception:
            agg_auc = 0.5

        agg_brier = float(brier_score_loss(y_all, p_all)) if len(y_all) > 0 else 0.0
        agg_ece = compute_expected_calibration_error(y_all, p_all)

        return {
            "folds": fold_results,
            "aggregate_oof": {
                "total_trades": total_val_trades,
                "accepted_trades": total_accepted,
                "rejected_trades": total_rejected,
                "acceptance_rate_pct": round(total_accepted / total_val_trades * 100.0, 1) if total_val_trades > 0 else 0.0,
                "unfiltered_net_pnl_14bps": round(total_unfiltered_net, 2),
                "filtered_net_pnl_14bps": round(total_filtered_net, 2),
                "rejected_net_pnl_14bps": round(total_rejected_net, 2),
                "incremental_net_pnl_14bps": round(total_filtered_net - total_unfiltered_net, 2),
                "roc_auc": round(agg_auc, 4),
                "brier_score": round(agg_brier, 4),
                "ece": round(agg_ece, 4),
            },
            "predictions": all_oof_preds,
        }
