"""Check model metrics against thresholds.

Validates:
- Global metrics from `logs/meta_model_eval_results.json`
- By-coin metrics (recomputed from model + dataset)
- By-time-slice metrics (monthly, from entry timestamp)

Exits non-zero if any required threshold fails.
Writes `logs/metrics_check_result.json` with details.
"""
import json
from datetime import datetime
from pathlib import Path

LOGS = Path(__file__).resolve().parent.parent / "logs"
BASE = Path(__file__).resolve().parent.parent
EVAL = LOGS / "meta_model_eval_results.json"
OUT = LOGS / "metrics_check_result.json"
MODEL_PATH = LOGS / "meta_model.joblib"
INPUT = LOGS / "adaptive_signals_v2.json"

GLOBAL_THRESHOLDS = {
    "roc_auc": 0.70,
    "pr_auc": 0.60,
    "brier": 0.25,
}

SLICE_FLOORS = {
    "roc_auc": 0.62,
    "pr_auc": 0.52,
    "brier": 0.28,
}

ROLLING_WINDOW = 3
ROLLING_MARGIN = {
    "roc_auc": 0.03,
    "pr_auc": 0.03,
    "brier": 0.03,
}

ROLLING_GRACE = {
    "roc_auc": 0.01,
    "pr_auc": 0.01,
    "brier": 0.01,
}

MIN_COIN_SAMPLES = 250
MIN_TIME_SLICE_SAMPLES = 400


def _check_metric(metric: str, value: float | None, threshold: float, grace: float = 0.0) -> tuple[bool, dict]:
    if value is None:
        return False, {"status": "missing", "value": None, "threshold": threshold}
    if metric == "brier":
        ok = value <= threshold + grace
    else:
        ok = value + grace >= threshold
    if ok:
        return True, {
            "status": "pass",
            "value": value,
            "threshold": threshold,
            "grace": grace,
        }
    return False, {
        "status": "fail",
        "value": value,
        "threshold": threshold,
        "grace": grace,
    }


def _rolling_threshold(metric: str, baseline: float) -> float:
    margin = ROLLING_MARGIN[metric]
    if metric == "brier":
        return min(SLICE_FLOORS[metric], baseline + margin)
    return max(SLICE_FLOORS[metric], baseline - margin)


def _parse_time_slice(rec: dict) -> str | None:
    ts = rec.get("entry_time") or rec.get("timestamp") or rec.get("time")
    if not ts:
        return None
    if isinstance(ts, (int, float)):
        try:
            dt = datetime.utcfromtimestamp(float(ts))
            return dt.strftime("%Y-%m")
        except Exception:
            return None
    s = str(ts).strip()
    if not s:
        return None
    s_norm = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s_norm)
        return dt.strftime("%Y-%m")
    except Exception:
        pass
    # Fallback for common "YYYY-MM-DD HH:MM:SS" style.
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m")
        except Exception:
            continue
    return None


def _segment_metrics(records: list[dict]) -> tuple[dict, dict]:
    try:
        import joblib
        import numpy as np
        from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
    except Exception as e:
        raise RuntimeError(f"Missing dependency: {e}") from e

    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"Model not found: {MODEL_PATH}")

    import sys
    sys.path.insert(0, str(BASE))
    from btc_scraper.ml_engine.feature_extractor import records_to_dataset

    bundle = joblib.load(MODEL_PATH)
    model = bundle.get("model") if isinstance(bundle, dict) else bundle
    selected_features = bundle.get("features") if isinstance(bundle, dict) else None

    X_list, y_list, feature_names = records_to_dataset(records)
    if not X_list or not y_list:
        raise RuntimeError("No dataset extracted from records")

    X = np.array(X_list)
    y = np.array(y_list)

    if selected_features:
        try:
            idxs = [feature_names.index(f) for f in selected_features]
            X_used = X[:, idxs]
        except Exception:
            X_used = X
    else:
        X_used = X

    probs = model.predict_proba(X_used)
    if probs.ndim == 1:
        probs = np.column_stack([1.0 - probs, probs])
    prob_pos = probs[:, 1]

    def calc(indices: list[int]) -> dict:
        if len(indices) < 2:
            return {"n_samples": len(indices), "status": "insufficient_samples"}
        y_s = y[indices]
        if len(set(y_s.tolist())) < 2:
            return {"n_samples": len(indices), "status": "single_class"}
        p_s = prob_pos[indices]
        return {
            "n_samples": len(indices),
            "status": "ok",
            "roc_auc": float(roc_auc_score(y_s, p_s)),
            "pr_auc": float(average_precision_score(y_s, p_s)),
            "brier": float(brier_score_loss(y_s, p_s)),
        }

    by_coin_idx: dict[str, list[int]] = {}
    by_slice_idx: dict[str, list[int]] = {}

    for i, rec in enumerate(records):
        coin = str(rec.get("coin") or "UNKNOWN").upper()
        by_coin_idx.setdefault(coin, []).append(i)
        month = _parse_time_slice(rec)
        if month:
            by_slice_idx.setdefault(month, []).append(i)

    by_coin = {coin: calc(idxs) for coin, idxs in sorted(by_coin_idx.items())}
    by_time_slice = {m: calc(idxs) for m, idxs in sorted(by_slice_idx.items())}
    return by_coin, by_time_slice


def _ordered_time_slice_metrics(by_time_slice: dict[str, dict]) -> list[tuple[str, dict]]:
    ordered = []
    for month, metrics in by_time_slice.items():
        try:
            ordered.append((month, metrics))
        except Exception:
            continue
    ordered.sort(key=lambda item: item[0])
    return ordered


def main():
    if not EVAL.exists():
        print("Evaluation results not found:", EVAL)
        return 2
    if not INPUT.exists():
        print("Input records not found:", INPUT)
        return 2

    data = json.loads(EVAL.read_text(encoding="utf-8"))
    records = json.loads(INPUT.read_text(encoding="utf-8"))

    failures = {}
    checks = {"global": {}, "by_coin": {}, "by_time_slice": {}}

    # Global checks from eval artifact
    for metric, threshold in GLOBAL_THRESHOLDS.items():
        ok, detail = _check_metric(metric, data.get(metric), threshold)
        checks["global"][metric] = detail
        if not ok:
            failures[f"global.{metric}"] = detail

    # Recompute segmented metrics from latest records + model
    try:
        by_coin, by_time_slice = _segment_metrics(records)
    except Exception as e:
        err = {"status": "error", "message": str(e)}
        failures["segment_metrics"] = err
        result = {
            "ok": False,
            "failures": failures,
            "metrics": data,
            "checks": checks,
            "segmentation_error": err,
        }
        OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1

    # Coin-level checks
    for coin, m in by_coin.items():
        if m.get("n_samples", 0) < MIN_COIN_SAMPLES:
            checks["by_coin"][coin] = {
                "status": "skipped_insufficient_samples",
                "n_samples": m.get("n_samples", 0),
                "min_samples": MIN_COIN_SAMPLES,
            }
            continue
        if m.get("status") != "ok":
            checks["by_coin"][coin] = {
                "status": "skipped",
                "reason": m.get("status", "unknown"),
                "n_samples": m.get("n_samples", 0),
            }
            continue

        metric_details = {"status": "pass", "n_samples": m["n_samples"], "metrics": {}}
        coin_failed = False
        for metric, threshold in SLICE_FLOORS.items():
            ok, detail = _check_metric(metric, m.get(metric), threshold)
            metric_details["metrics"][metric] = detail
            if not ok:
                coin_failed = True
        if coin_failed:
            metric_details["status"] = "fail"
            failures[f"coin.{coin}"] = metric_details
        checks["by_coin"][coin] = metric_details

    # Time-slice checks (monthly, rolling baseline)
    ordered_time_slices = _ordered_time_slice_metrics(by_time_slice)
    baseline_history: list[dict] = []

    for month, m in ordered_time_slices:
        if m.get("n_samples", 0) < MIN_TIME_SLICE_SAMPLES:
            checks["by_time_slice"][month] = {
                "status": "skipped_insufficient_samples",
                "n_samples": m.get("n_samples", 0),
                "min_samples": MIN_TIME_SLICE_SAMPLES,
            }
            continue
        if m.get("status") != "ok":
            checks["by_time_slice"][month] = {
                "status": "skipped",
                "reason": m.get("status", "unknown"),
                "n_samples": m.get("n_samples", 0),
            }
            continue

        baseline_window = baseline_history[-ROLLING_WINDOW:]
        if len(baseline_window) < ROLLING_WINDOW:
            checks["by_time_slice"][month] = {
                "status": "warmup",
                "n_samples": m["n_samples"],
                "baseline_window": len(baseline_window),
                "required_window": ROLLING_WINDOW,
                "metrics": {
                    metric: {"status": "pass", "value": m.get(metric), "threshold": SLICE_FLOORS[metric], "grace": ROLLING_GRACE[metric]}
                    for metric in SLICE_FLOORS
                },
            }
            baseline_history.append(m)
            continue

        baselines = {
            metric: sum(item.get(metric, 0.0) for item in baseline_window) / len(baseline_window)
            for metric in SLICE_FLOORS
        }
        thresholds = {
            metric: _rolling_threshold(metric, baselines[metric])
            for metric in SLICE_FLOORS
        }

        metric_details = {
            "status": "pass",
            "n_samples": m["n_samples"],
            "baseline_window": [item.get("month") for item in baseline_window],
            "baselines": baselines,
            "thresholds": thresholds,
            "metrics": {},
        }
        month_failed = False
        for metric, threshold in thresholds.items():
            ok, detail = _check_metric(metric, m.get(metric), threshold, ROLLING_GRACE[metric])
            metric_details["metrics"][metric] = detail
            if not ok:
                month_failed = True
        if month_failed:
            metric_details["status"] = "fail"
            failures[f"time_slice.{month}"] = metric_details
        checks["by_time_slice"][month] = metric_details
        baseline_history.append({**m, "month": month})

    result = {
        "ok": len(failures) == 0,
        "failures": failures,
        "metrics": data,
        "checks": checks,
        "segmented_summary": {
            "coin_count": len(by_coin),
            "time_slice_count": len(by_time_slice),
            "coin_min_samples": MIN_COIN_SAMPLES,
            "time_slice_min_samples": MIN_TIME_SLICE_SAMPLES,
            "time_slice_rolling_window": ROLLING_WINDOW,
            "time_slice_margin": ROLLING_MARGIN,
        },
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
