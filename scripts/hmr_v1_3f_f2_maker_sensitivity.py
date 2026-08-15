#!/usr/bin/env python3
"""HMR-V1.3F-F2: Maker Execution Feasibility Sweep.

Reads f0_candidates.parquet. For the Top 5% SELL cohort, sweeps:
  - Maker fill ratios: 100%, 75%, 50%, 25%
  - Adverse selection drag: 0 bp, 1 bp, 2 bps, 3 bps, 4 bps, 5 bps

Under a flat maker cost assumption (default 2.0 bps to cover maker fee + slippage).

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

# Parameters to sweep
FILL_RATIOS = [1.00, 0.75, 0.50, 0.25]
ADVERSE_SELECTIONS = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]  # in bps


def run_f2_maker_sweep(args) -> int:
    parquet_path = Path(args.parquet)
    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found. Run F0 first.")
        return 1

    print("F2: Maker Execution Feasibility Sensitivity Sweep")
    print(f"  Input: {parquet_path}")
    print(f"  Cohort: Top {args.top_pct*100:.0f}% SELL by raw_model_score")
    print(f"  Assumed Flat Maker Cost: {args.maker_cost_bps:.1f} bps")
    print()

    df = pd.read_parquet(parquet_path)
    sell_df = df[df["side"] == "SELL"].copy().sort_values("raw_model_score", ascending=False).reset_index(drop=True)
    top_k = max(1, int(round(args.top_pct * len(sell_df))))
    cohort = sell_df.head(top_k).copy()

    print(f"  Total SELL candidates: {len(sell_df)}")
    print(f"  Cohort size: n={len(cohort)}")
    print()

    gross_returns = cohort["lifecycle_gross_return"].dropna()
    if gross_returns.empty:
        print("ERROR: No gross returns found in cohort.")
        return 1

    maker_cost_frac = args.maker_cost_bps / 10_000.0
    results: List[Dict[str, Any]] = []

    for fill_ratio in FILL_RATIOS:
        for adv_bps in ADVERSE_SELECTIONS:
            adv_frac = adv_bps / 10_000.0
            
            # Net return if trade is filled
            net_filled_returns = gross_returns - adv_frac - maker_cost_frac
            
            # Expected net returns (including fill ratio probability)
            # Missed trades result in 0 return
            expected_net_returns = net_filled_returns * fill_ratio
            
            n = len(expected_net_returns)
            
            # Expected Net EV per proposed trade (in bps)
            mean_net_ev_bps = float(expected_net_returns.mean()) * 10_000.0
            
            # Win Rate is computed over filled trades
            filled_wins = (net_filled_returns > 0).sum()
            win_rate_filled = filled_wins / n if n > 0 else 0.0
            # Effective win rate over all proposed trades
            effective_wr = win_rate_filled * fill_ratio
            
            # Profit Factor (computed on filled trade returns, fill_ratio cancels out)
            pos_sum = net_filled_returns[net_filled_returns > 0].sum()
            neg_sum = abs(net_filled_returns[net_filled_returns < 0].sum())
            pf = pos_sum / neg_sum if neg_sum > 0 else (999.0 if pos_sum > 0 else 1.0)
            
            # Expected Net PnL (summed in bps)
            net_pnl_bps = float(expected_net_returns.sum()) * 10_000.0

            results.append({
                "fill_ratio": fill_ratio,
                "adverse_selection_bps": adv_bps,
                "n": n,
                "win_rate_filled": win_rate_filled,
                "effective_win_rate": effective_wr,
                "net_ev_bps": mean_net_ev_bps,
                "profit_factor": float(pf),
                "net_pnl_bps": net_pnl_bps
            })

    # Print report
    print(f"  {'Fill Ratio':<12} {'Adv Drag':<10} {'Net EV (bps)':>14} {'PF':>10} {'Eff. WR':>10} {'Net PnL (bps)':>14}")
    print(f"  {'-'*12} {'-'*10} {'-'*14} {'-'*10} {'-'*10} {'-'*14}")
    for r in results:
        net_ev = r["net_ev_bps"]
        flag = " 🟢" if net_ev > 0 else ""
        print(
            f"  {r['fill_ratio']:<12.0%} {r['adverse_selection_bps']:>5.1f} bps  "
            f"{net_ev:>13.2f}{flag} {r['profit_factor']:>9.3f} {r['effective_win_rate']:>9.1%} {r['net_pnl_bps']:>13.1f}"
        )
    print()

    # Save outputs
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "f2_maker_sensitivity.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  ✓ Saved JSON: {json_path}")

    # Build markdown grid report
    md_lines = [
        "# HMR-V1.3F-F2: Maker Execution Feasibility Sensitivity Sweep\n",
        f"Input: `{parquet_path}` — Top {args.top_pct*100:.0f}% SELL cohort (n={len(cohort)})\n",
        f"Assumed flat maker cost: **{args.maker_cost_bps:.1f} bps** (covering maker exchange fees and slippage)\n",
        "### Expected Net EV / Trade (bps)\n",
        "| Fill Ratio \\ Adv Drag | 0.0 bps | 1.0 bps | 2.0 bps | 3.0 bps | 4.0 bps | 5.0 bps |",
        "|:----------------------|:-------:|:-------:|:-------:|:-------:|:-------:|:-------:|",
    ]
    
    # Restructure results into grids for markdown tables
    for fill in FILL_RATIOS:
        row_str = f"| **{fill:.0%}** |"
        for adv in ADVERSE_SELECTIONS:
            r = next(item for item in results if np.isclose(item["fill_ratio"], fill) and np.isclose(item["adverse_selection_bps"], adv))
            ev = r["net_ev_bps"]
            flag = "🟢 " if ev > 0 else ""
            row_str += f" {flag}{ev:+.2f} bps |"
        md_lines.append(row_str)
        
    md_lines.append("\n### Profit Factor (PF)\n")
    md_lines.append("| Fill Ratio \\ Adv Drag | 0.0 bps | 1.0 bps | 2.0 bps | 3.0 bps | 4.0 bps | 5.0 bps |")
    md_lines.append("|:----------------------|:-------:|:-------:|:-------:|:-------:|:-------:|:-------:|")
    for fill in FILL_RATIOS:
        row_str = f"| **{fill:.0%}** |"
        for adv in ADVERSE_SELECTIONS:
            r = next(item for item in results if np.isclose(item["fill_ratio"], fill) and np.isclose(item["adverse_selection_bps"], adv))
            row_str += f" {r['profit_factor']:.3f} |"
        md_lines.append(row_str)

    md_lines.append("\n### Net PnL (bps)\n")
    md_lines.append("| Fill Ratio \\ Adv Drag | 0.0 bps | 1.0 bps | 2.0 bps | 3.0 bps | 4.0 bps | 5.0 bps |")
    md_lines.append("|:----------------------|:-------:|:-------:|:-------:|:-------:|:-------:|:-------:|")
    for fill in FILL_RATIOS:
        row_str = f"| **{fill:.0%}** |"
        for adv in ADVERSE_SELECTIONS:
            r = next(item for item in results if np.isclose(item["fill_ratio"], fill) and np.isclose(item["adverse_selection_bps"], adv))
            pnl = r["net_pnl_bps"]
            flag = "🟢 " if pnl > 0 else ""
            row_str += f" {flag}{pnl:+.1f} |"
        md_lines.append(row_str)

    md_path = output_dir / "f2_maker_sensitivity.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"  ✓ Saved MD:   {md_path}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V1.3F-F2: Maker Execution Feasibility Sensitivity Sweep")
    p.add_argument(
        "--parquet",
        default="research/historical_market_replay_v1/v1_3f/f0_candidates.parquet",
    )
    p.add_argument("--output-dir", default="research/historical_market_replay_v1/v1_3f")
    p.add_argument("--top-pct", type=float, default=0.05,
                   help="Top cohort fraction by raw_model_score (0.05 = Top 5%%)")
    p.add_argument("--maker-cost-bps", type=float, default=2.0,
                   help="Assumed maker transaction cost in bps")
    return p


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    sys.exit(run_f2_maker_sweep(args))
