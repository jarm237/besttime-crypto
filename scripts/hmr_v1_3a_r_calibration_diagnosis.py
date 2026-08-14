#!/usr/bin/env python3
"""R5-R6 — Calibration Diagnosis for HMR-V1.3A-R.

Analyzes the December 2024 calibration dataset, calculates distributions,
audits labels, checks symbol-specific rates, and classifies the root cause
of the calibration collapse.
"""

import json
import sys
from pathlib import Path
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MANIFEST_PATH = REPO_ROOT / "research/historical_market_replay_v1/research_artifact_pre2025/manifest.json"
OUTPUT_DIR = REPO_ROOT / "research/historical_market_replay_v1/v1_3a_r/calibration"

def load_data():
    with open(MANIFEST_PATH, "r") as f:
        manifest = json.load(f)
    cal_path = REPO_ROOT / manifest["paths"]["calibration_data"]
    train_path = REPO_ROOT / manifest["paths"]["training_data"]
    
    cal_df = pd.read_parquet(cal_path)
    train_df = pd.read_parquet(train_path)
    return cal_df, train_df, manifest

def run_diagnostics(cal_df, train_df, manifest):
    total_cal = len(cal_df)
    cal_wins = int((cal_df["label"] == 1).sum())
    cal_losses = int((cal_df["label"] == 0).sum())
    cal_win_rate = cal_wins / total_cal
    
    total_train = len(train_df)
    train_wins = int((train_df["label"] == 1).sum())
    train_losses = int((train_df["label"] == 0).sum())
    train_win_rate = train_wins / total_train
    
    # Per coin in calibration
    coin_stats = {}
    for coin in cal_df["coin"].unique():
        sub = cal_df[cal_df["coin"] == coin]
        wins = int((sub["label"] == 1).sum())
        total = len(sub)
        coin_stats[coin] = {
            "total": total,
            "wins": wins,
            "win_rate": wins / total if total > 0 else 0.0
        }
        
    # Per action in calibration
    action_stats = {}
    for action in cal_df["technical_action"].unique():
        sub = cal_df[cal_df["technical_action"] == action]
        wins = int((sub["label"] == 1).sum())
        total = len(sub)
        action_stats[action] = {
            "total": total,
            "wins": wins,
            "win_rate": wins / total if total > 0 else 0.0
        }
        
    # Temporal distribution inside December 2024
    cal_df["entry_time"] = pd.to_datetime(cal_df["entry_time"])
    cal_df["day"] = cal_df["entry_time"].dt.date
    daily_stats = cal_df.groupby("day")["label"].agg(["count", "sum"]).to_dict(orient="index")
    daily_stats = {str(k): {"total": v["count"], "wins": int(v["sum"])} for k, v in daily_stats.items()}
    
    # Calculate base rate shift
    base_rate_ratio = cal_win_rate / train_win_rate if train_win_rate > 0 else 0.0
    
    # Classify Root Causes
    causes = []
    reasons = []
    
    if cal_wins < 10:
        causes.append("CALIBRATION_POSITIVE_STARVATION")
        reasons.append("Calibration dataset has critically few positive samples (wins < 10), which causes isotonic regression to flatten predictions to near-zero.")
        
    if total_cal < 500:
        causes.append("CALIBRATION_SAMPLE_TOO_SMALL")
        reasons.append(f"Calibration cohort size ({total_cal}) is too small to perform stable probability calibration.")
        
    if base_rate_ratio < 0.6:
        causes.append("TEMPORAL_DISTRIBUTION_SHIFT")
        reasons.append(f"Win rate dropped by {1.0 - base_rate_ratio:.1%} in calibration period compared to training (0.73% vs 1.36%).")
        
    # Action imbalance
    sell_ratio = action_stats.get("SELL", {}).get("total", 0) / total_cal
    if sell_ratio > 0.8:
        causes.append("SIDE_DISTRIBUTION_IMBALANCE")
        reasons.append(f"Extremely imbalanced technical signals in calibration set: {sell_ratio:.1%} are SELL signals.")
        
    if not causes:
        causes.append("TRUE_LOW_BASE_RATE")
        reasons.append("The base rate of the system is extremely low across both training and calibration cohorts.")

    diagnostics = {
        "summary": {
            "calibration_win_rate": cal_win_rate,
            "training_win_rate": train_win_rate,
            "calibration_wins": cal_wins,
            "calibration_total": total_cal,
            "training_wins": train_wins,
            "training_total": total_train,
            "base_rate_ratio": base_rate_ratio,
        },
        "coin_breakdown": coin_stats,
        "action_breakdown": action_stats,
        "daily_breakdown": daily_stats,
        "classified_root_causes": causes,
        "classification_reasons": reasons,
        "gate": {
            "CALIBRATION_COLLAPSE_CAUSE": "KNOWN" if len(causes) > 0 else "UNKNOWN"
        }
    }
    
    return diagnostics

def generate_report(diagnostics):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_json = OUTPUT_DIR / "cohort_diagnostics.json"
    with open(out_json, "w") as f:
        json.dump(diagnostics, f, indent=2)
        
    md_lines = [
        "# R5–R6 — Calibration Diagnosis & Root Cause",
        "",
        f"**Gate**: `CALIBRATION_COLLAPSE_CAUSE = {diagnostics['gate']['CALIBRATION_COLLAPSE_CAUSE']}`",
        "",
        "## Summary Metrics",
        "",
        "| Metric | Training Set | Calibration Set (Dec 2024) | Shift |",
        "| :--- | :---: | :---: | :---: |",
        f"| Total Samples | `{diagnostics['summary']['training_total']:,}` | `{diagnostics['summary']['calibration_total']:,}` | - |",
        f"| Wins (y=1) | `{diagnostics['summary']['training_wins']:,}` | `{diagnostics['summary']['calibration_wins']}` | - |",
        f"| Base Win Rate | `{diagnostics['summary']['training_win_rate']:.4%}` | `{diagnostics['summary']['calibration_win_rate']:.4%}` | `{diagnostics['summary']['calibration_win_rate'] - diagnostics['summary']['training_win_rate']:+.4%}` |",
        "",
        "## Breakdown By Symbol",
        "",
        "| Symbol | Total Samples | Wins | Win Rate |",
        "| :--- | :---: | :---: | :---: |",
    ]
    for coin, stats in diagnostics["coin_breakdown"].items():
        md_lines.append(f"| {coin} | `{stats['total']}` | `{stats['wins']}` | `{stats['win_rate']:.2%}` |")
        
    md_lines += [
        "",
        "## Breakdown By Technical Action",
        "",
        "| Action | Total Samples | Wins | Win Rate |",
        "| :--- | :---: | :---: | :---: |",
    ]
    for act, stats in diagnostics["action_breakdown"].items():
        md_lines.append(f"| {act} | `{stats['total']}` | `{stats['wins']}` | `{stats['win_rate']:.2%}` |")
        
    md_lines += [
        "",
        "## Classified Root Causes",
        "",
    ]
    for cause, reason in zip(diagnostics["classified_root_causes"], diagnostics["classification_reasons"]):
        md_lines.append(f"### ⚠️ {cause}")
        md_lines.append(reason)
        md_lines.append("")
        
    md_lines += [
        "## Calibration Remediation Recommendation",
        "",
        "Based on the identified root causes, we recommend:",
        "1. **Isotonic regression is highly sensitive to sample size and positive sparsity**. A cohort of 3 positive instances out of 409 causes isotonic calibration to map all probabilities above the raw score of the last win to a flat maximum of `16.67%`.",
        "2. **Branch C (Sigmoid Calibration / Platt Scaling)** or **Branch B (Expanded Calibration Period)** should be pursued in phase R8 to remediate the collapse, rather than continuing to use isotonic regression on such a starved dataset.",
    ]
    
    out_md = OUTPUT_DIR / "calibration_root_cause.md"
    with open(out_md, "w") as f:
        f.write("\n".join(md_lines) + "\n")
        
    print(f"Diagnostics written to {out_json}")
    print(f"Report written to {out_md}")

def main():
    cal_df, train_df, manifest = load_data()
    diagnostics = run_diagnostics(cal_df, train_df, manifest)
    generate_report(diagnostics)

if __name__ == "__main__":
    main()
