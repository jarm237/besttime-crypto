#!/usr/bin/env python3
"""HMR-V2.3R: Target-Aligned Pool Validation.

Replays the same 60-candidate policy at the economic targets discovered in V2.2:
  - 72-bar horizon for classification (GROSS_GT_30BPS, GROSS_GT_40BPS, NET_GT_0BPS)
  - 8-bar horizon for regression (gross_return_bps)

Compares metrics (mean, median, payoffs, positive/negative rates) between the
V1 and V2 pools. Diagnoses target enrichment and sample support.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

COST_BPS = 15.0
COST_FRAC = COST_BPS / 10_000.0


def run_v2_3r_target_aligned(args) -> int:
    parquet_path = Path(args.parquet)
    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found. Run V2.1 first.")
        return 1

    policy_json_path = REPO_ROOT / "research/historical_market_replay_v2/v2_3_candidate_policy/candidate_policy.json"
    if not policy_json_path.exists():
        print(f"ERROR: {policy_json_path} not found. Run V2.3 first.")
        return 1

    print("HMR-V2.3R: Target-Aligned Pool Validation")
    print(f"  Input candidates: {parquet_path}")
    print(f"  Policy file:      {policy_json_path}")
    print()

    # Load candidates & policy
    df = pd.read_parquet(parquet_path)
    
    with open(policy_json_path, "r") as f:
        policy = json.load(f)
        
    toxic_subgroups = policy.get("blacklisted_toxic_subgroups", [])
    toxic_tuples = set(
        (sg["technical_signal_family"], sg["trend_regime"], sg["volatility_regime"], sg["side"])
        for sg in toxic_subgroups
    )

    # Filter into V1 (all candidates) and V2 (redesigned candidates)
    df["is_filtered"] = df.apply(
        lambda r: (r["technical_signal_family"], r["trend_regime"], r["volatility_regime"], r["side"]) in toxic_tuples,
        axis=1
    )
    
    v1_pool = df.copy()
    v2_pool = df[~df["is_filtered"]].copy()

    # Prepare metrics at 72 bars
    ret_72 = "return_72bars"
    v1_72 = v1_pool[ret_72].dropna()
    v2_72 = v2_pool[ret_72].dropna()

    v1_n = len(v1_pool)
    v2_n = len(v2_pool)

    # 72-bar statistics
    v1_mean_72 = float(v1_72.mean() * 10_000.0) if not v1_72.empty else 0.0
    v2_mean_72 = float(v2_72.mean() * 10_000.0) if not v2_72.empty else 0.0

    v1_med_72 = float(v1_72.median() * 10_000.0) if not v1_72.empty else 0.0
    v2_med_72 = float(v2_72.median() * 10_000.0) if not v2_72.empty else 0.0

    v1_gt_30 = float((v1_72 > 0.0030).mean()) if not v1_72.empty else 0.0
    v2_gt_30 = float((v2_72 > 0.0030).mean()) if not v2_72.empty else 0.0
    v2_count_gt_30 = int((v2_72 > 0.0030).sum()) if not v2_72.empty else 0

    v1_gt_40 = float((v1_72 > 0.0040).mean()) if not v1_72.empty else 0.0
    v2_gt_40 = float((v2_72 > 0.0040).mean()) if not v2_72.empty else 0.0
    v2_count_gt_40 = int((v2_72 > 0.0040).sum()) if not v2_72.empty else 0

    v1_net_pos = float((v1_72 > COST_FRAC).mean()) if not v1_72.empty else 0.0
    v2_net_pos = float((v2_72 > COST_FRAC).mean()) if not v2_72.empty else 0.0

    # Mean positive and negative payoff @ 72 bars
    v1_pos_payoff = float(v1_72[v1_72 > 0.0].mean() * 10_000.0) if not v1_72[v1_72 > 0.0].empty else 0.0
    v2_pos_payoff = float(v2_72[v2_72 > 0.0].mean() * 10_000.0) if not v2_72[v2_72 > 0.0].empty else 0.0

    v1_neg_payoff = float(v1_72[v1_72 <= 0.0].mean() * 10_000.0) if not v1_72[v1_72 <= 0.0].empty else 0.0
    v2_neg_payoff = float(v2_72[v2_72 <= 0.0].mean() * 10_000.0) if not v2_72[v2_72 <= 0.0].empty else 0.0

    # Prepare metrics at 8 bars (for regression)
    ret_8 = "return_8bars"
    v1_8 = v1_pool[ret_8].dropna()
    v2_8 = v2_pool[ret_8].dropna()

    v1_mean_8 = float(v1_8.mean() * 10_000.0) if not v1_8.empty else 0.0
    v2_mean_8 = float(v2_8.mean() * 10_000.0) if not v2_8.empty else 0.0

    v1_med_8 = float(v1_8.median() * 10_000.0) if not v1_8.empty else 0.0
    v2_med_8 = float(v2_8.median() * 10_000.0) if not v2_8.empty else 0.0

    # Spearman rank correlation at 8 bars
    if not v1_pool[["raw_model_score", ret_8]].dropna().empty:
        v1_corr_8, _ = spearmanr(v1_pool["raw_model_score"], v1_pool[ret_8], nan_policy="omit")
    else:
        v1_corr_8 = float("nan")

    if not v2_pool[["raw_model_score", ret_8]].dropna().empty and len(v2_pool.dropna(subset=[ret_8])) >= 2:
        v2_corr_8, _ = spearmanr(v2_pool["raw_model_score"], v2_pool[ret_8], nan_policy="omit")
    else:
        v2_corr_8 = float("nan")

    results = {
        "n_original": v1_n,
        "n_redesigned": v2_n,
        "metrics_72bars": {
            "mean_gross_bps": {"v1": v1_mean_72, "v2": v2_mean_72},
            "median_gross_bps": {"v1": v1_med_72, "v2": v2_med_72},
            "gross_gt_30bps_rate": {"v1": v1_gt_30, "v2": v2_gt_30},
            "gross_gt_30bps_count": {"v1": int((v1_72 > 0.0030).sum()), "v2": v2_count_gt_30},
            "gross_gt_40bps_rate": {"v1": v1_gt_40, "v2": v2_gt_40},
            "gross_gt_40bps_count": {"v1": int((v1_72 > 0.0040).sum()), "v2": v2_count_gt_40},
            "net_positive_rate": {"v1": v1_net_pos, "v2": v2_net_pos},
            "mean_pos_payoff_bps": {"v1": v1_pos_payoff, "v2": v2_pos_payoff},
            "mean_neg_payoff_bps": {"v1": v1_neg_payoff, "v2": v2_neg_payoff}
        },
        "metrics_8bars": {
            "mean_gross_bps": {"v1": v1_mean_8, "v2": v2_mean_8},
            "median_gross_bps": {"v1": v1_med_8, "v2": v2_med_8},
            "spearman_corr": {"v1": float(v1_corr_8), "v2": float(v2_corr_8)}
        }
    }

    # Save JSON results
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "target_aligned_comparison.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  ✓ Saved target-aligned JSON: {json_path}")

    # Build markdown report
    md_lines = [
        "# HMR-V2.3R: Target-Aligned Pool Validation Report\n",
        "This report profiles the filtered V2 candidate pool (n=60) against the original V1 pool (n=1175) ",
        "at the target economic horizons established in Phase V2.2.\n",
        "## 1. Classification Targets Comparison (@72 bars)\n",
        "| Metric | V1 Pool | V2 Pool | Delta | Notes |",
        "|:-------|:-------:|:-------:|:-----:|:------|",
        f"| **Pool Size ($n$)** | `{v1_n}` | `{v2_n}` | `{v2_n - v1_n}` | |",
        f"| **Mean Gross Return** | `{v1_mean_72:+.2f} bps` | `{v2_mean_72:+.2f} bps` | `{v2_mean_72 - v1_mean_72:+.2f} bps` | Aligned with GROSS target |",
        f"| **Median Gross Return** | `{v1_med_72:+.2f} bps` | `{v2_med_72:+.2f} bps` | `{v2_med_72 - v1_med_72:+.2f} bps` | |",
        f"| **Gross > 30bps Rate** | `{v1_gt_30:.1%}` | `{v2_gt_30:.1%}` | `{v2_gt_30 - v1_gt_30:+.1%}` | Target A2 enrichment |",
        f"| **Gross > 40bps Rate** | `{v1_gt_40:.1%}` | `{v2_gt_40:.1%}` | `{v2_gt_40 - v1_gt_40:+.1%}` | Target A1 enrichment |",
        f"| **Net+ Rate** | `{v1_net_pos:.1%}` | `{v2_net_pos:.1%}` | `{v2_net_pos - v1_net_pos:+.1%}` | Target B1 enrichment |",
        f"| **Mean Positive Payoff** | `{v1_pos_payoff:+.2f} bps` | `{v2_pos_payoff:+.2f} bps` | `{v2_pos_payoff - v1_pos_payoff:+.2f} bps` | |",
        f"| **Mean Negative Payoff** | `{v1_neg_payoff:+.2f} bps` | `{v2_neg_payoff:+.2f} bps` | `{v2_neg_payoff - v1_neg_payoff:+.2f} bps` | |",
    ]

    md_lines.append("\n## 2. Regression Target Comparison (@8 bars)\n")
    md_lines.append("| Metric | V1 Pool | V2 Pool | Delta |")
    md_lines.append("|:-------|:-------:|:-------:|:-----:|")
    md_lines.append(f"| **Mean Gross Return** | `{v1_mean_8:+.2f} bps` | `{v2_mean_8:+.2f} bps` | `{v2_mean_8 - v1_mean_8:+.2f} bps` |")
    md_lines.append(f"| **Median Gross Return** | `{v1_med_8:+.2f} bps` | `{v2_med_8:+.2f} bps` | `{v2_med_8 - v1_med_8:+.2f} bps` |")
    md_lines.append(f"| **Spearman Correlation** | `{v1_corr_8:+.4f}` | `{v2_corr_8:+.4f}` | `{v2_corr_8 - v1_corr_8:+.4f}` |")

    md_lines.append("\n## 3. Diagnosis and Validation Gates\n")

    # Diagnosing quality and sample support
    enrichment_gt_30 = (v2_gt_30 / v1_gt_30) if v1_gt_30 > 0 else 1.0
    enrichment_gt_40 = (v2_gt_40 / v1_gt_40) if v1_gt_40 > 0 else 1.0

    md_lines.append(
        "### A. Economic Quality & Target Enrichment\n"
        f"* **Target Enrichment (>30bps @72bars)**: `{enrichment_gt_30:.2f}x` (from `{v1_gt_30:.1%}` to `{v2_gt_30:.1%}`)  \n"
        f"* **Target Enrichment (>40bps @72bars)**: `{enrichment_gt_40:.2f}x` (from `{v1_gt_40:.1%}` to `{v2_gt_40:.1%}`)  \n"
        f"* **Net+ Enrichment (@72bars)**: `{(v2_net_pos / v1_net_pos) if v1_net_pos > 0 else 1.0:.2f}x` (from `{v1_net_pos:.1%}` to `{v2_net_pos:.1%}`)  \n"
    )

    # Sample Sufficiency check
    md_lines.append("### B. Learnability & Sample Support\n")
    md_lines.append(f"* **Total Candidates ($n$)**: `{v2_n}`  \n")
    md_lines.append(f"* **Gross > 30bps expected count**: `{v2_count_gt_30}`  \n")
    md_lines.append(f"* **Gross > 40bps expected count**: `{v2_count_gt_40}`  \n")

    is_starved = v2_count_gt_30 < 30 or v2_count_gt_40 < 30
    starve_status = "⚠️ BLOCKED (Sample Starvation)" if is_starved else "🟢 PASS"

    md_lines.append(
        f"* **Sample Sufficiency Status**: **{starve_status}**  \n"
        "  - Training a robust research classifier requires at least **30 positives** in the validation fold.  \n"
        f"  - The current V2 pool contains only `{v2_count_gt_30}` positives for `Gross>30` and `{v2_count_gt_40}` positives for `Gross>40`.\n"
    )

    md_path = output_dir / "target_aligned_comparison.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"  ✓ Saved MD report: {md_path}")
    print()

    # Console Gate outputs
    print("  === V2.3R Assessment ===")
    print(f"    - Mean gross return @72 bars:   {v2_mean_72:+.2f} bps (V1: {v1_mean_72:+.2f} bps)")
    print(f"    - Gross > 30bps rate @72 bars:   {v2_gt_30:.1%} (Enrichment: {enrichment_gt_30:.2f}x)")
    print(f"    - Positives count (Gross>30):   {v2_count_gt_30} / {v2_n}")
    print(f"    - Sample Sufficiency Gate:      {starve_status}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V2.3R: Target-Aligned Pool Validation")
    p.add_argument(
        "--parquet",
        default="research/historical_market_replay_v2/v2_1_candidate_decomposition/candidates.parquet",
    )
    p.add_argument(
        "--output-dir",
        default="research/historical_market_replay_v2/v2_3r_target_aligned",
    )
    return p


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    sys.exit(run_v2_3r_target_aligned(args))
