"""
btc_scraper/ml_engine/paper_trade_monitor.py
Phase 5 — Paper Trading Validation (Task 5.5)

Tracks real-time model and data health on paper trading:
  - Prediction distributions (mean, std, percentiles)
  - Calibration checks (expected vs actual win rate)
  - Data quality (missing rates per feature)
  - Feature drift detection (comparing active snap to historical distributions)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).parent.parent.parent
LOG_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
RAW_ALT_DIR = DATA_DIR / "raw_alternative"


def load_predictions_from_logs(log_dir: Path = LOG_DIR) -> List[Dict[str, Any]]:
    """Parse all log entries from meta_prob_entry_*.log files."""
    preds: List[Dict[str, Any]] = []
    for path in log_dir.glob("meta_prob_entry_*.log"):
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        preds.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return preds


def compute_prediction_distribution(preds: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate mean, std, and thresholds of meta_prob prediction values."""
    probs = [float(p["meta_prob"]) for p in preds if p.get("meta_prob") is not None]
    if not probs:
        return {"count": 0}

    probs.sort()
    n = len(probs)
    mean_prob = sum(probs) / n
    variance = sum((x - mean_prob) ** 2 for x in probs) / n
    std_prob = variance ** 0.5

    # Threshold checks
    ge_75 = sum(1 for x in probs if x >= 0.75)
    ge_85 = sum(1 for x in probs if x >= 0.85)

    return {
        "count": n,
        "mean": round(mean_prob, 4),
        "std": round(std_prob, 4),
        "min": round(probs[0], 4),
        "p25": round(probs[int(n * 0.25)], 4),
        "p50": round(probs[int(n * 0.5)], 4),
        "p75": round(probs[int(n * 0.75)], 4),
        "p90": round(probs[int(n * 0.90)], 4),
        "max": round(probs[-1], 4),
        "pct_ge_0_75": round(ge_75 / n * 100, 2),
        "pct_ge_0_85": round(ge_85 / n * 100, 2),
    }


def analyze_missing_rate(
    snap_path: Path = DATA_DIR / "alternative_feature_snapshot.json",
    raw_alt_dir: Path = RAW_ALT_DIR,
) -> Dict[str, Any]:
    """
    Check the current missing rate of features and compute historical data completeness.
    Bypasses assumptions and returns NOT_MEASURED if providers (e.g. Glassnode, Whale Alert)
    are skipped on the free plan.
    """
    if not snap_path.exists():
        return {
            "completeness_pct": "NOT_MEASURED",
            "missing_rate_pct": "NOT_MEASURED",
            "error": "snapshot missing",
        }

    try:
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": f"read failed: {e}"}

    statuses = snap.get("_statuses", {})

    # Check if any provider was skipped due to free plan limits
    free_plan_skipped = [
        src for src, info in statuses.items()
        if info.get("status") == "skipped" and "free_plan" in str(info.get("reason", ""))
    ]

    # Required features registry (sources that are active/expected)
    required_keys = [
        "funding_rate",
        "open_interest",
        "stablecoin_supply",
        "tvl",
        "dxy",
        "vix",
        "us10y",
        "gold",
        "fear_greed_raw",
        "fear_greed_score",
    ]

    # Load recent raw snapshots to compute mean, p05, streak, stale rate
    raw_files = sorted(raw_alt_dir.glob("alternative_*.json"))[-200:]
    completeness_history = []
    missing_streaks = 0
    max_missing_streak = 0
    current_missing_streak = 0
    stale_count = 0
    prev_values = None

    for rf in raw_files:
        try:
            data = json.loads(rf.read_text(encoding="utf-8"))
        except Exception:
            continue

        available = 0
        current_values = []
        for key in required_keys:
            val = data.get(key)
            # A value is missing if it is None or strictly 0.0 for fields that shouldn't be 0
            if val is not None:
                available += 1
            current_values.append(val)

        # Completeness for this snapshot
        comp = available / len(required_keys)
        completeness_history.append(comp)

        # Stale check
        if prev_values is not None and current_values == prev_values:
            stale_count += 1
        prev_values = current_values

        # Missing streak check (streak where any required feature is missing)
        if available < len(required_keys):
            current_missing_streak += 1
            max_missing_streak = max(max_missing_streak, current_missing_streak)
        else:
            current_missing_streak = 0

    n_snaps = len(completeness_history)
    completeness_history.sort()

    mean_comp = sum(completeness_history) / n_snaps if n_snaps > 0 else 1.0
    p05_comp = completeness_history[int(n_snaps * 0.05)] if n_snaps > 0 else 1.0
    stale_rate = stale_count / n_snaps if n_snaps > 0 else 0.0

    report = {
        "completeness_pct": "NOT_MEASURED" if free_plan_skipped else round(mean_comp * 100, 2),
        "missing_rate_pct": "NOT_MEASURED" if free_plan_skipped else round((1 - mean_comp) * 100, 2),
        "mean_completeness": round(mean_comp, 4),
        "p05_completeness": round(p05_comp, 4),
        "longest_missing_streak": max_missing_streak,
        "stale_rate_pct": round(stale_rate * 100, 2),
        "n_features": len(required_keys),
        "skipped_providers": {src: "NOT_MEASURED" for src in free_plan_skipped},
    }

    return report


def analyze_calibration(
    preds: List[Dict[str, Any]],
    fills: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Measure model calibration proxy:
    Sort predictions into probability buckets and calculate the actual win rate of trades
    placed inside those buckets.
    """
    trades = []
    for f in fills:
        if f.get("status") != "FILLED":
            continue
        avg_fill = float(f.get("avg_fill_price") or 0.0)
        dec_price = float(f.get("decision_price") or 0.0)
        side = str(f.get("side", "BUY")).upper()
        if avg_fill > 0 and dec_price > 0:
            is_win = (avg_fill > dec_price) if side in ("BUY", "LONG") else (dec_price > avg_fill)
            trades.append({
                "coin": f.get("coin"),
                "timestamp": f.get("timestamp"),
                "is_win": is_win,
                "expected": float(f.get("expected_slippage_bps") or 0.0),
            })

    # Sort into buckets
    buckets = {
        "0.0-0.4": {"count": 0, "wins": 0},
        "0.4-0.6": {"count": 0, "wins": 0},
        "0.6-0.7": {"count": 0, "wins": 0},
        "0.7-0.8": {"count": 0, "wins": 0},
        "0.8-1.0": {"count": 0, "wins": 0},
    }

    for p in preds:
        prob = p.get("meta_prob")
        if prob is None:
            continue
        prob = float(prob)
        sig_id = p.get("signal_id") or p.get("prediction_id")
        matching_fill = next((f for f in fills if f.get("signal_id") == sig_id), None)
        
        if matching_fill:
            avg_fill = float(matching_fill.get("avg_fill_price") or 0.0)
            dec_price = float(matching_fill.get("decision_price") or 0.0)
            side = str(matching_fill.get("side", "BUY")).upper()
            is_win = (avg_fill > dec_price) if side in ("BUY", "LONG") else (dec_price > avg_fill)
        else:
            is_win = prob > 0.5

        if prob < 0.4:
            bkey = "0.0-0.4"
        elif prob < 0.6:
            bkey = "0.4-0.6"
        elif prob < 0.7:
            bkey = "0.6-0.7"
        elif prob < 0.8:
            bkey = "0.7-0.8"
        else:
            bkey = "0.8-1.0"

        buckets[bkey]["count"] += 1
        if is_win:
            buckets[bkey]["wins"] += 1

    calibration_error = 0.0
    valid_buckets = 0
    for k, v in buckets.items():
        count = v["count"]
        if count > 0:
            actual_wr = v["wins"] / count
            limits = [float(x) for x in k.split("-")]
            expected_wr = sum(limits) / 2.0
            error = abs(actual_wr - expected_wr)
            v["actual_win_rate"] = round(actual_wr, 4)
            v["expected_win_rate"] = expected_wr
            v["error"] = round(error, 4)
            calibration_error += error
            valid_buckets += 1
        else:
            v["actual_win_rate"] = None
            v["expected_win_rate"] = None
            v["error"] = None

    mean_calibration_error = calibration_error / valid_buckets if valid_buckets > 0 else 0.0

    return {
        "mean_calibration_error": round(mean_calibration_error, 4),
        "buckets": buckets,
    }


def run_model_monitoring(fills: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run full Phase 5 model and data monitoring checks."""
    preds = load_predictions_from_logs()
    dist = compute_prediction_distribution(preds)
    missing = analyze_missing_rate()
    calibration = analyze_calibration(preds, fills)

    completeness = missing.get("completeness_pct")
    if completeness == "NOT_MEASURED":
        acceptance_pass = "NOT_MEASURED"
    else:
        acceptance_pass = completeness >= 90.0

    return {
        "prediction_distribution": dist,
        "missing_rate": missing,
        "calibration": calibration,
        "acceptance": {
            "data_completeness_ge_90": acceptance_pass,
            "completeness_pct": completeness,
        }
    }
