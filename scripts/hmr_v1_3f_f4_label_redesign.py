#!/usr/bin/env python3
"""HMR-V1.3F-F4: Economic Label Redesign Probe.

Reads f0_candidates.parquet. Probes alternative objective label definitions on
the frozen candidate dataset across horizons: 32, 48, 96, 192 bars.

Targets evaluated:
  - y_gross_gt_20bps   ← binary: gross return > 20 bps
  - y_net_gt_0bps      ← binary: gross return > 15 bps (covers 15 bps flat cost)
  - y_gross_return     ← regression: raw gross return of the trade
  - y_net_return       ← regression: raw net return (gross - 15 bps cost)

For each target and horizon, reports:
  - Class balance / positive class ratio (for binary targets)
  - Mean, Std, Median (for regression targets)
  - ROC-AUC / PR-AUC of current raw_model_score against binary targets
  - Spearman correlation of raw_model_score against regression targets

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

HORIZONS = [32, 48, 96, 192]
COST_BPS = 15.0
COST_FRAC = COST_BPS / 10_000.0


def run_f4_label_redesign(args) -> int:
    parquet_path = Path(args.parquet)
    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found. Run F0 first.")
        return 1

    print("F4: Economic Label Redesign Probe")
    print(f"  Input: {parquet_path}")
    print(f"  Cost assumption: {COST_BPS:.1f} bps flat")
    print()

    df = pd.read_parquet(parquet_path)
    sell_df = df[df["side"] == "SELL"].copy().reset_index(drop=True)
    buy_df = df[df["side"] == "BUY"].copy().reset_index(drop=True)

    print(f"  Candidates: SELL={len(sell_df)}, BUY={len(buy_df)}")
    print()

    for side, sub_df in [("SELL", sell_df), ("BUY", buy_df)]:
        if sub_df.empty:
            continue
        
        print(f"=== {side} SIDE ALTERNATIVE TARGET PROBE ===")
        print()
        
        results: List[Dict[str, Any]] = []
        
        for h in HORIZONS:
            col = f"return_{h}bars"
            if col not in sub_df.columns:
                continue
            
            valid_df = sub_df[["raw_model_score", col]].dropna().copy()
            if valid_df.empty or len(valid_df) < 10:
                continue
                
            returns = valid_df[col]
            scores = valid_df["raw_model_score"]
            
            # --- Target 1: Gross Return > 20 bps ---
            y_gross_20 = (returns > 0.0020).astype(int)
            pos_ratio_20 = float(y_gross_20.mean())
            if len(y_gross_20.unique()) > 1:
                auc_gross_20 = roc_auc_score(y_gross_20, scores)
            else:
                auc_gross_20 = float("nan")
                
            # --- Target 2: Net Return > 0 bps (Gross > 15 bps) ---
            y_net_0 = (returns > COST_FRAC).astype(int)
            pos_ratio_net = float(y_net_0.mean())
            if len(y_net_0.unique()) > 1:
                auc_net_0 = roc_auc_score(y_net_0, scores)
            else:
                auc_net_0 = float("nan")
                
            # --- Target 3: Regression Target (Gross Return) ---
            mean_ret = float(returns.mean()) * 10_000.0
            std_ret = float(returns.std()) * 10_000.0
            median_ret = float(returns.median()) * 10_000.0
            corr, _ = spearmanr(scores, returns)
            
            results.append({
                "horizon_bars": h,
                "n": len(valid_df),
                # y_gross_gt_20bps
                "y_gross_gt_20bps_ratio": pos_ratio_20,
                "y_gross_gt_20bps_auc": auc_gross_20,
                # y_net_gt_0bps
                "y_net_gt_0bps_ratio": pos_ratio_net,
                "y_net_gt_0bps_auc": auc_net_0,
                # Continuous return
                "mean_return_bps": mean_ret,
                "std_return_bps": std_ret,
                "median_return_bps": median_ret,
                "spearman_corr": float(corr)
            })
            
        # Print side report
        print(f"  Horizon | n | Gross > 20bps Ratio | AUC | Net > 0bps Ratio | AUC | Mean Gross (bps) | Spearman Corr")
        print(f"  {'-'*105}")
        for r in results:
            print(
                f"  {r['horizon_bars']:>3} bars | {r['n']:>3} | {r['y_gross_gt_20bps_ratio']:>19.1%} | {r['y_gross_gt_20bps_auc']:>5.3f} | "
                f"{r['y_net_gt_0bps_ratio']:>17.1%} | {r['y_net_gt_0bps_auc']:>5.3f} | {r['mean_return_bps']:>16.2f} | {r['spearman_corr']:>+13.4f}"
            )
        print()
        
        # Save side outputs
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        json_path = output_dir / f"f4_label_redesign_{side.lower()}.json"
        with open(json_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"  ✓ Saved JSON: {json_path}")
        
        # Build markdown report
        md_lines = [
            f"# HMR-V1.3F-F4: Economic Label Redesign Probe ({side} Side)\n",
            f"Input: `{parquet_path}` — Total candidates: {len(sub_df)}\n",
            f"Friction assumption: **{COST_BPS:.1f} bps** flat\n",
            "| Horizon | n | Pos Ratio (Gross > 20bps) | AUC vs Score | Pos Ratio (Net > 0bps) | AUC vs Score | Mean Gross (bps) | Std Return (bps) | Spearman Corr |",
            "|:--------|--:|--------------------------:|-------------:|-----------------------:|-------------:|-----------------:|-----------------:|--------------:|",
        ]
        for r in results:
            md_lines.append(
                f"| {r['horizon_bars']} bars | {r['n']} | {r['y_gross_gt_20bps_ratio']:.1%} | {r['y_gross_gt_20bps_auc']:.3f} | "
                f"{r['y_net_gt_0bps_ratio']:.1%} | {r['y_net_gt_0bps_auc']:.3f} | {r['mean_return_bps']:.2f} | {r['std_return_bps']:.2f} | "
                f"{r['spearman_corr']:+.4f} |"
            )
            
        md_path = output_dir / f"f4_label_redesign_{side.lower()}.md"
        md_path.write_text("\n".join(md_lines), encoding="utf-8")
        print(f"  ✓ Saved MD:   {md_path}")
        print()

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V1.3F-F4: Economic Label Redesign Probe")
    p.add_argument(
        "--parquet",
        default="research/historical_market_replay_v1/v1_3f/f0_candidates.parquet",
    )
    p.add_argument("--output-dir", default="research/historical_market_replay_v1/v1_3f")
    return p


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    sys.exit(run_f4_label_redesign(args))
