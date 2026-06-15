"""
Adaptive scoring helpers — log closed trades with signal metadata and provide
basic statistics/training helpers for future adaptive scoring iterations.

This module is intentionally lightweight: it appends records to
`logs/adaptive_signals.json` and provides `compute_score_stats()` and a
`train_adaptive_model()` stub that computes simple score -> win-rate mapping
and writes `logs/adaptive_model.json`.
"""

import json
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional

BASE = os.path.dirname(__file__)
ADAPTIVE_LOG = os.path.join(BASE, "..", "logs", "adaptive_signals.json")
ADAPTIVE_MODEL = os.path.join(BASE, "..", "logs", "adaptive_model.json")


def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _load_log() -> List[Dict[str, Any]]:
    _ensure_dir(ADAPTIVE_LOG)
    if not os.path.exists(ADAPTIVE_LOG):
        return []
    try:
        with open(ADAPTIVE_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_log(data: List[Dict[str, Any]]) -> None:
    _ensure_dir(ADAPTIVE_LOG)
    with open(ADAPTIVE_LOG, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def log_trade_outcome(closed_data: Dict[str, Any]) -> None:
    """Append a normalized record used for adaptive scoring analysis.

    Keeps a compact subset of fields to make downstream analysis simple.
    """
    # Normalize signal_score: prefer explicit dict, fallback to parsing nested raw JSON
    raw_ss = closed_data.get("last_signal_score") or closed_data.get("signal_score")
    signal_score = {}
    try:
        if isinstance(raw_ss, dict) and raw_ss:
            # If the producer serialized inner dict as string under 'raw', try to decode it
            if raw_ss.get("raw") and isinstance(raw_ss.get("raw"), str):
                import json as _json
                try:
                    parsed = _json.loads(raw_ss.get("raw"))
                    signal_score = parsed
                except Exception:
                    signal_score = raw_ss
            else:
                signal_score = raw_ss
        elif isinstance(raw_ss, str) and raw_ss:
            import json as _json
            try:
                signal_score = _json.loads(raw_ss)
            except Exception:
                signal_score = {"raw": raw_ss}
        else:
            # Try to pick up any entry-level fields
            signal_score = closed_data.get("entry_signal_score") or {}
    except Exception:
        signal_score = {}

    rec = {
        "coin": closed_data.get("coin"),
        "id": closed_data.get("id"),
        "entry_price": closed_data.get("entry_price"),
        "sell_price": closed_data.get("sell_price"),
        "pnl_pct": closed_data.get("pnl_pct"),
        "result": closed_data.get("result"),
        "hold_hours": closed_data.get("hold_hours"),
        "exit_time": closed_data.get("exit_time"),
        "signal_raw": closed_data.get("last_signal") or closed_data.get("signal"),
        "signal_score": signal_score,
        # support regime analysis: try to pick regime from closed_data or inner signal_score
        "regime": (closed_data.get("regime") or signal_score.get("regime") if isinstance(signal_score, dict) else None),
    }

    log = _load_log()
    log.append(rec)
    _save_log(log)


def compute_score_stats() -> Dict[str, Any]:
    """Compute simple statistics grouped by rounded score buckets.

    Returns a mapping of bucket -> {count, wins, losses, win_rate, avg_pnl}.
    """
    log = _load_log()
    buckets: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    noscore: List[Dict[str, Any]] = []

    for r in log:
        s = r.get("signal_score") or {}
        score = s.get("score")
        if score is None:
            noscore.append(r)
            continue
        try:
            b = int(score // 10 * 10)
        except Exception:
            noscore.append(r)
            continue
        buckets[b].append(r)

    out: Dict[str, Any] = {}
    for b, items in buckets.items():
        wins = sum(1 for it in items if it.get("result") == "WIN")
        losses = sum(1 for it in items if it.get("result") == "LOSS")
        avg_pnl = sum(it.get("pnl_pct", 0.0) for it in items) / len(items) if items else 0.0
        out[str(b)] = {
            "count": len(items),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(items) * 100, 2) if items else None,
            "avg_pnl": round(avg_pnl, 4),
        }

    out["no_score"] = {"count": len(noscore)}
    return out


def train_adaptive_model(save: bool = True) -> Dict[str, Any]:
    """Train a simple logistic regression model from logged adaptive signals.

    If scikit-learn is available, train and save a joblib model to
    `logs/adaptive_model.joblib`. Otherwise fall back to previous bucketed
    JSON model.
    Returns a summary dict (either model metadata or bucket stats).
    """
    records = _load_log()
    if not records:
        return {"message": "No logged trades to train on."}

    try:
        # Try to use sklearn trainer if available
        from btc_scraper.ml_engine.feature_extractor import records_to_dataset
        import numpy as np
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import StratifiedKFold, cross_val_score
        import joblib

        X, y, feature_names = records_to_dataset(records)
        if not X:
            return {"message": "No features extracted."}

        X = np.array(X)
        y = np.array(y)

        # Cross-validated training to get robust accuracy estimate
        clf = RandomForestClassifier(n_estimators=200, max_depth=6, class_weight='balanced', random_state=42)
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
        try:
            cv_scores = cross_val_score(clf, X, y, cv=cv, scoring='roc_auc')
            cv_mean = float(cv_scores.mean())
        except Exception:
            cv_mean = None

        # Fit on full data
        clf.fit(X, y)

        # Save model and metadata
        model_path = os.path.join(os.path.dirname(__file__), "..", "logs", "adaptive_model.joblib")
        _ensure_dir(model_path)
        joblib.dump({"model": clf, "features": feature_names}, model_path)

        # Return metrics
        preds = clf.predict(X)
        acc = float((preds == y).mean())
        return {"model": "sklearn_random_forest", "accuracy": acc, "cv_auc": cv_mean, "n_samples": len(y), "features": feature_names}
    except Exception:
        # Fallback to bucketed stats JSON
        stats = compute_score_stats()
        model: Dict[str, Any] = {k: {"win_rate": v.get("win_rate"), "adjustment": 0.0} for k, v in stats.items() if k != "no_score"}
        if save:
            _ensure_dir(ADAPTIVE_MODEL)
            try:
                with open(ADAPTIVE_MODEL, "w", encoding="utf-8") as f:
                    json.dump(model, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        return {"model": "bucketed", "stats": stats}


if __name__ == "__main__":
    # Quick CLI for devs: print stats and optionally train
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--train", action="store_true")
    args = p.parse_args()

    stats = compute_score_stats()
    print("Adaptive stats:")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    if args.train:
        m = train_adaptive_model()
        print("Saved model:")
        print(json.dumps(m, indent=2, ensure_ascii=False))
