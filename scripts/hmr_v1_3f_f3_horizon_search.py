#!/usr/bin/env python3
"""HMR-V1.3F-F3: Edge-by-Horizon Search.

Reads f0_candidates.parquet. Sweeps exit horizons:
  1, 2, 4, 8, 16, 24, 32, 48, 72, 96, 192 bars

For each horizon, calculates:
  - ROC-AUC / PR-AUC (treating return > 0 as positive target)
  - Spearman rank correlation with raw model score
  - Mean gross return for top 1%, 2.5%, 5%, 10% cohorts (sorted by raw score)
  - Median gross return for top 5% cohort
  - Mean MFE and MAE (if available in candidate records)
  - Estimated net return after flat 15.0 bps friction

Boundary:
  RESEARCH_ONLY
  NO_THRESHOLD_OPTIMIZATION
  NO_MODEL_PROMOTION
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score, precision_recall_curve, auc

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

HORIZONS = [1, 2, 4, 8, 16, 24, 32, 48, 72, 96, 192]
COST_BPS = 15.0
COST_FRAC = COST_BPS / 10_000.0


def run_f3_horizon_search(args) -> int:
    parquet_path = Path(args.parquet)
    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found. Run F0 first.")
        return 1

    print("F3: Edge-by-Horizon Search")
    print(f"  Input: {parquet_path}")
    print(f"  Assumed Flat Taker Cost: {COST_BPS:.1f} bps")
    print()

    df = pd.read_parquet(parquet_path)
    sell_df = df[df["side"] == "SELL"].copy().reset_index(drop=True)
    buy_df = df[df["side"] == "BUY"].copy().reset_index(drop=True)

    print(f"  Total candidates: SELL={len(sell_df)}, BUY={len(buy_df)}")
    print()

    for side, sub_df in [("SELL", sell_df), ("BUY", buy_df)]:
        if sub_df.empty:
            continue
        
        print(f"=== {side} SIDE HORIZON ANALYSIS (n={len(sub_df)}) ===")
        print()
        
        results: List[Dict[str, Any]] = []
        
        for h in HORIZONS:
            col = f"return_{h}bar" if h == 1 else f"return_{h}bars"
            if col not in sub_df.columns:
                continue
            
            # Filter non-null outcomes for this horizon
            valid_df = sub_df[["raw_model_score", col]].dropna().copy()
            if valid_df.empty or len(valid_df) < 5:
                continue
            
            returns = valid_df[col]
            scores = valid_df["raw_model_score"]
            
            # 1. Classification Metrics (Target: return > 0)
            binary_labels = (returns > 0).astype(int)
            if len(binary_labels.unique()) > 1:
                roc_auc = roc_auc_score(binary_labels, scores)
                precision, recall, _ = precision_recall_curve(binary_labels, scores)
                pr_auc = auc(recall, precision)
            else:
                roc_auc = float("nan")
                pr_auc = float("nan")
                
            # 2. Rank Correlation
            corr, _ = spearmanr(scores, returns)
            
            # 3. Cohort Payoffs
            # Sort valid sub-dataset descending by model score
            sorted_df = valid_df.sort_values("raw_model_score", ascending=False).reset_index(drop=True)
            
            cohort_means = {}
            for p in [0.01, 0.025, 0.05, 0.10]:
                k = max(1, int(round(p * len(sorted_df))))
                cohort_means[f"top_{p*100:.1f}%_mean_bps"] = float(sorted_df.head(k)[col].mean()) * 10_000.0
                
            top_5pct_k = max(1, int(round(0.05 * len(sorted_df))))
            top_5pct_median = float(sorted_df.head(top_5pct_k)[col].median()) * 10_000.0
            
            # Estimated Net return for Top 5% cohort
            top_5pct_net = cohort_means["top_5.0%_mean_bps"] - COST_BPS

            results.append({
                "horizon_bars": h,
                "n": len(valid_df),
                "roc_auc": float(roc_auc),
                "pr_auc": float(pr_auc),
                "spearman_corr": float(corr),
                "top_1.0%_mean_bps": cohort_means["top_1.0%_mean_bps"],
                "top_2.5%_mean_bps": cohort_means["top_2.5%_mean_bps"],
                "top_5.0%_mean_bps": cohort_means["top_5.0%_mean_bps"],
                "top_10.0%_mean_bps": cohort_means["top_10.0%_mean_bps"],
                "top_5.0%_median_bps": top_5pct_median,
                "top_5.0%_net_bps": top_5pct_net
            })
            
        # Print side report
        header = (
            f"  {'Horizon':<8} {'n':>5} {'ROC-AUC':>8} {'PR-AUC':>8} {'Spearman':>9} "
            f"{'Top 1%':>8} {'Top 2.5%':>9} {'Top 5%':>8} {'Top 10%':>9} {'Net Top 5%':>12}"
        )
        print(header)
        print(f"  {'-'*101}")
        for r in results:
            net_val = r["top_5.0%_net_bps"]
            flag = " 🟢" if net_val > 0 else ""
            print(
                f"  {r['horizon_bars']:>3} bars  {r['n']:>5} {r['roc_auc']:>8.4f} {r['pr_auc']:>8.4f} {r['spearman_corr']:>+9.4f} "
                f"{r['top_1.0%_mean_bps']:>8.1f} {r['top_2.5%_mean_bps']:>9.1f} {r['top_5.0%_mean_bps']:>8.1f} {r['top_10.0%_mean_bps']:>9.1f} "
                f"{net_val:>+11.2f}{flag}"
            )
        print()
        
        # Save side outputs
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        json_path = output_dir / f"f3_horizon_search_{side.lower()}.json"
        with open(json_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"  ✓ Saved JSON: {json_path}")
        
        # Build markdown report for this side
        md_lines = [
            f"# HMR-V1.3F-F3: Edge-by-Horizon Search ({side} Side)\n",
            f"Input: `{parquet_path}` — Total candidates: {len(sub_df)}\n",
            f"Cost assumption: **{COST_BPS:.1f} bps** flat\n",
            "| Horizon | n | ROC-AUC | PR-AUC | Spearman | Top 1% (bps) | Top 2.5% (bps) | Top 5% (bps) | Top 10% (bps) | Net Top 5% (bps) |",
            "|:--------|--:|--------:|-------:|---------:|-------------:|---------------:|-------------:|--------------:|-----------------:|",
        ]
        for r in results:
            net_val = r["top_5.0%_net_bps"]
            flag = " 🟢" if net_val > 0 else ""
            md_lines.append(
                f"| {r['horizon_bars']} bars | {r['n']} | {r['roc_auc']:.4f} | {r['pr_auc']:.4f} | {r['spearman_corr']:+.4f} | "
                f"{r['top_1.0%_mean_bps']:+.1f} | {r['top_2.5%_mean_bps']:+.1f} | {r['top_5.0%_mean_bps']:+.1f} | {r['top_10.0%_mean_bps']:+.1f} | "
                f"{net_val:+.2f}{flag} |"
            )
            
        md_path = output_dir / f"f3_horizon_search_{side.lower()}.md"
        md_path.write_text("\n".join(md_lines), encoding="utf-8")
        print(f"  ✓ Saved MD:   {md_path}")
        print()

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V1.3F-F3: Edge-by-Horizon Search")
    p.add_argument(
        "--parquet",
        default="research/historical_market_replay_v1/v1_3f/f0_candidates.parquet",
    )
    p.add_argument("--output-dir", default="research/historical_market_replay_v1/v1_3f")
    return p


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    sys.exit(run_f3_horizon_search(args))
