"""
Check dataset readiness for calibration split changes.
Loads `logs/adaptive_signals_v2.json`, extracts features via
`btc_scraper.ml_engine.feature_extractor.records_to_dataset`, and reports:
 - n_samples, n_features
 - label distribution
 - time range and samples per month
 - per-coin sample counts
 - missing feature rates
 - signal_score bucket counts (if present)
Saves JSON report to `logs/dataset_check_for_calibration.json`.
"""
import os
import sys
import json
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
INPUT = LOGS / "adaptive_signals_v2.json"
OUT = LOGS / "dataset_check_for_calibration.json"

sys.path.insert(0, str(BASE))


def parse_time(rec):
    t = rec.get("entry_time") or rec.get("timestamp") or rec.get("exit_time")
    if not t:
        return None
    try:
        return datetime.fromisoformat(t)
    except Exception:
        try:
            return datetime.strptime(t, "%Y-%m-%d %H:%M")
        except Exception:
            try:
                return datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None


def main():
    report = {"ok": False}
    if not INPUT.exists():
        report["error"] = f"Missing {INPUT}"
        print(report["error"])
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        return 1

    with open(INPUT, "r", encoding="utf-8") as f:
        recs = json.load(f)

    # Basic stats
    n = len(recs)
    report["n_records"] = n

    # Labels
    labels = Counter(r.get("result") for r in recs)
    report["label_dist"] = dict(labels)

    # Time range
    times = [parse_time(r) for r in recs]
    times = [t for t in times if t is not None]
    if times:
        earliest = min(times)
        latest = max(times)
        report["time_range"] = {"earliest": earliest.isoformat(), "latest": latest.isoformat(), "span_days": (latest-earliest).days}
    else:
        report["time_range"] = None

    # Per-month counts
    per_month = Counter()
    for t in times:
        per_month[t.strftime("%Y-%m")] += 1
    report["per_month"] = dict(per_month)

    # Per-coin counts
    per_coin = Counter(r.get("coin") for r in recs)
    report["per_coin"] = dict(per_coin)

    # Try to extract features via repository helper if available
    report["n_features_sampled"] = 0
    report["feature_names"] = None
    try:
        from btc_scraper.ml_engine.feature_extractor import records_to_dataset
        X_list, y_list, feature_names = records_to_dataset(recs)
        report["n_features_sampled"] = len(feature_names)
        report["feature_names"] = feature_names
    except Exception:
        # Feature map not available in this record format
        feature_missing = defaultdict(int)
        for r in recs:
            feats = r.get("features") or {}
            for k, v in feats.items():
                if v is None:
                    feature_missing[k] += 1
        report["feature_missing_counts"] = dict(feature_missing)
        report["n_features_sampled"] = len(recs[0].get("features") or {}) if recs else 0

    # Signal_score buckets (if present)
    buckets = {"0.0-0.4":0, "0.4-0.6":0, "0.6-0.7":0, "0.7-0.8":0, "0.8-1.0":0}
    score_available = False
    for r in recs:
        ss = r.get("signal_score")
        score = None
        if isinstance(ss, dict):
            score = ss.get("score")
        elif isinstance(ss, (int, float)):
            score = float(ss)
        if score is None:
            continue
        score_available = True
        p = score / 100.0 if score > 1 else score
        if p < 0.4:
            buckets["0.0-0.4"] += 1
        elif p < 0.6:
            buckets["0.4-0.6"] += 1
        elif p < 0.7:
            buckets["0.6-0.7"] += 1
        elif p < 0.8:
            buckets["0.7-0.8"] += 1
        else:
            buckets["0.8-1.0"] += 1
    report["score_buckets"] = buckets if score_available else None

    # Heuristics for split viability
    report["viability"] = {}
    report["viability"]["min_samples_for_training"] = n >= 30
    report["viability"]["min_samples_for_calibration(50)"] = n >= 50
    report["viability"]["recommended_for_calibration(100)"] = n >= 100
    report["viability"]["suggested_splits"] = []
    # Suggest splits based on n
    if n >= 1000:
        report["viability"]["suggested_splits"].append({"train_calib_test":"70/20/10"})
    if n >= 400:
        report["viability"]["suggested_splits"].append({"train_calib_test":"60/20/20"})
    if n < 100:
        report["viability"]["suggested_splits"].append({"note":"Too few samples for reliable calibration — collect more data"})

    report["ok"] = True

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    print(json.dumps({
        "n_records": report["n_records"],
        "label_dist": report["label_dist"],
        "time_range": report["time_range"],
        "n_features_sampled": report["n_features_sampled"],
        "score_buckets": report["score_buckets"],
        "viability": report["viability"],
    }, indent=2, ensure_ascii=False))

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
