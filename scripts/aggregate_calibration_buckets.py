"""
Aggregate high-confidence calibration buckets to increase sample counts.
Loads `logs/meta_model.json`, merges specified buckets (default: 0.7-0.8 + 0.8-1.0 -> 0.7-1.0),
recomputes combined counts/wins/predicted_wr/calibration_error and writes
`logs/meta_model_agg_calibration.json`.

Run: python scripts/aggregate_calibration_buckets.py
"""
from __future__ import annotations
import os
import sys
import json
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(__file__))
LOGS = os.path.join(ROOT, "logs")
METRIC_PATH = os.path.join(LOGS, "meta_model.json")
OUT = os.path.join(LOGS, "meta_model_agg_calibration.json")

if not os.path.exists(METRIC_PATH):
    print(f"Missing metrics file: {METRIC_PATH}")
    sys.exit(1)

with open(METRIC_PATH, "r", encoding="utf-8") as f:
    metrics = json.load(f)

buckets = metrics.get("calibration_buckets") or {}
if not buckets:
    print("No calibration_buckets found in metrics.")
    sys.exit(1)

# Buckets to merge (configurable)
merge_groups = [("0.7-0.8", "0.8-1.0")]
agg_result = {"generated_at": datetime.utcnow().isoformat(), "original": buckets, "merged": {}}

for a, b in merge_groups:
    ba = buckets.get(a, {})
    bb = buckets.get(b, {})
    ca = ba.get("count", 0) or 0
    cb = bb.get("count", 0) or 0
    wa = ba.get("wins") if ba.get("wins") is not None else None
    wb = bb.get("wins") if bb.get("wins") is not None else None

    combined_count = ca + cb
    combined_wins = None
    if wa is not None and wb is not None:
        combined_wins = int(wa) + int(wb)

    # merged predicted_wr: use merged range lo-hi
    try:
        lo = float(a.split('-')[0])
        hi = float(b.split('-')[1])
        predicted_wr = (lo + hi) / 2 * 100
    except Exception:
        predicted_wr = None

    actual_wr = None
    calibration_error = None
    calibrated = None
    if combined_wins is not None and combined_count > 0:
        actual_wr = round(combined_wins / combined_count * 100, 1)
        if predicted_wr is not None:
            calibration_error = round(actual_wr - predicted_wr, 1)
            calibrated = abs(calibration_error) <= 10.0

    merged_key = f"{a.split('-')[0]}-{b.split('-')[1]}"
    agg_result["merged"][merged_key] = {
        "count": int(combined_count),
        "wins": int(combined_wins) if combined_wins is not None else None,
        "actual_wr": actual_wr,
        "predicted_wr": round(predicted_wr, 1) if predicted_wr is not None else None,
        "calibration_error": calibration_error,
        "calibrated": calibrated,
    }

# Save
os.makedirs(LOGS, exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(agg_result, f, ensure_ascii=False, indent=2)

print(f"Wrote aggregated calibration report to {OUT}")
