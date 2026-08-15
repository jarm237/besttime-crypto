#!/usr/bin/env python3
"""HMR-V1.3F-F1: Cost-Floor Sensitivity Sweep.

Reads f0_candidates.parquet. Sweeps flat transaction costs:
  15 bps, 12 bps, 10 bps, 8 bps, 6 bps, 4 bps, 2 bps

Calculates Net expectancy (EV), Profit Factor (PF), and Net PnL on the Top 5%
SELL cohort using the production TP/SL exits (lifecycle_gross_return).

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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Cost levels to sweep (in bps)
COST_SCENARIOS = [15.0, 12.0, 10.0, 8.0, 6.0, 4.0, 2.0]


def run_f1_cost_sweep(args) -> int:
    parquet_path = Path(args.parquet)
    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found. Run F0 first.")
        return 1

    print("F1: Cost-Floor Sensitivity Sweep")
    print(f"  Input: {parquet_path}")
    print(f"  Cohort: Top {args.top_pct*100:.0f}% SELL by raw_model_score")
    print()

    df = pd.read_parquet(parquet_path)
    sell_df = df[df["side"] == "SELL"].copy().sort_values("raw_model_score", ascending=False).reset_index(drop=True)
    top_k = max(1, int(round(args.top_pct * len(sell_df))))
    cohort = sell_df.head(top_k).copy()

    print(f"  Total SELL candidates: {len(sell_df)}")
    print(f"  Top {args.top_pct*100:.0f}% cohort size: n={len(cohort)}")
    print()

    gross_returns = cohort["lifecycle_gross_return"].dropna()
    if gross_returns.empty:
        print("ERROR: No gross returns found in cohort.")
        return 1

    results: List[Dict[str, Any]] = []

    for cost_bps in COST_SCENARIOS:
        cost_frac = cost_bps / 10_000.0
        # Calculate net returns for each trade under this cost model
        net_returns = gross_returns - cost_frac
        
        n = len(net_returns)
        wins = int((net_returns > 0).sum())
        wr = wins / n if n > 0 else 0.0
        
        mean_net_bps = float(net_returns.mean()) * 10_000.0
        
        pos_sum = net_returns[net_returns > 0].sum()
        neg_sum = abs(net_returns[net_returns < 0].sum())
        pf = pos_sum / neg_sum if neg_sum > 0 else (999.0 if pos_sum > 0 else 1.0)
        
        # PnL in bps (sum of net returns * 10_000)
        net_pnl_bps = float(net_returns.sum()) * 10_000.0

        results.append({
            "cost_bps": cost_bps,
            "n": n,
            "win_rate": wr,
            "net_ev_bps": mean_net_bps,
            "profit_factor": float(pf),
            "net_pnl_bps": net_pnl_bps
        })

    # Print report
    print(f"  {'Cost (bps)':<12} {'n':>6} {'Win Rate':>10} {'Net EV (bps)':>14} {'Profit Factor':>15} {'Net PnL (bps)':>16}")
    print(f"  {'-'*12} {'-'*6} {'-'*10} {'-'*14} {'-'*15} {'-'*16}")
    for r in results:
        net_ev = r["net_ev_bps"]
        pnl = r["net_pnl_bps"]
        flag = " 🟢" if net_ev > 0 else ""
        print(
            f"  {r['cost_bps']:<12.1f} {r['n']:>6} {r['win_rate']:>10.1%} "
            f"{net_ev:>+13.2f}{flag} {r['profit_factor']:>14.3f} {pnl:>+15.1f}"
        )
    print()

    # Save outputs
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "f1_cost_sensitivity.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  ✓ Saved JSON: {json_path}")

    md_lines = [
        "# HMR-V1.3F-F1: Cost-Floor Sensitivity Sweep\n",
        f"Input: `{parquet_path}` — Top {args.top_pct*100:.0f}% SELL cohort (n={len(cohort)})\n",
        "| Cost | n | Win Rate | Net EV (bps) | Profit Factor | Net PnL (bps) |",
        "|:-----|--:|---------:|-------------:|--------------:|--------------:|",
    ]
    for r in results:
        flag = " 🟢" if r["net_ev_bps"] > 0 else ""
        md_lines.append(
            f"| {r['cost_bps']:.1f} bps | {r['n']} | {r['win_rate']:.1%} | "
            f"{r['net_ev_bps']:+.2f}{flag} | {r['profit_factor']:.3f} | {r['net_pnl_bps']:+.1f} |"
        )

    md_path = output_dir / "f1_cost_sensitivity.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"  ✓ Saved MD:   {md_path}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V1.3F-F1: Cost-Floor Sensitivity Sweep")
    p.add_argument(
        "--parquet",
        default="research/historical_market_replay_v1/v1_3f/f0_candidates.parquet",
    )
    p.add_argument("--output-dir", default="research/historical_market_replay_v1/v1_3f")
    p.add_argument("--top-pct", type=float, default=0.05,
                   help="Top cohort fraction by raw_model_score (0.05 = Top 5%%)")
    return p


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    sys.exit(run_f1_cost_sweep(args))
