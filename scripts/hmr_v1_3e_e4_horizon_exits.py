#!/usr/bin/env python3
"""HMR-V1.3E-E4: Horizon Exit Experiment.

Reads e1_candidates.parquet. With the Top 5% SELL cohort (by raw_model_score),
compares economic outcomes under multiple exit strategies:

  EXIT_1BAR    ← exit at close of bar +1
  EXIT_4BAR    ← exit after 4 bars (1h)
  EXIT_8BAR    ← exit after 8 bars (2h)
  EXIT_16BAR   ← exit after 16 bars (4h)
  EXIT_24BAR   ← exit after 24 bars (6h)
  EXIT_32BAR   ← exit after 32 bars (8h)
  EXIT_48BAR   ← exit after 48 bars (12h)
  CURRENT_TPSL ← existing 3.13/2.38 ATR contract (lifecycle_gross_return from E1)

Key question:
  - If EXIT_4BAR net > 0 but CURRENT_TPSL net < 0 → exit contract is destroying edge
  - If all fixed horizons also negative after cost → ranking edge not monetizable

Boundary:
  RESEARCH_ONLY
  NO_THRESHOLD_OPTIMIZATION
  NO_MODEL_PROMOTION
"""

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Approximate flat cost (consistent with D1/D2 / E3)
COST_BPS = 15.0
COST_FRAC = COST_BPS / 10_000.0

HORIZON_MAP = {
    "EXIT_1BAR":  "return_1bar",
    "EXIT_4BAR":  "return_4bars",
    "EXIT_8BAR":  "return_8bars",
    "EXIT_16BAR": "return_16bars",
    "EXIT_24BAR": "return_24bars",
    "EXIT_32BAR": "return_32bars",
    "EXIT_48BAR": "return_48bars",
}


def compute_stats(returns: pd.Series, label: str) -> Dict[str, Any]:
    """Compute win_rate, gross expectancy, net expectancy, profit factor for a returns series."""
    valid = returns.dropna()
    if valid.empty:
        return {
            "exit": label, "n": 0,
            "win_rate": float("nan"),
            "gross_expectancy": float("nan"),
            "net_expectancy": float("nan"),
            "profit_factor": float("nan"),
            "mean_return_bps": float("nan"),
            "net_return_bps": float("nan"),
        }

    n = len(valid)
    wins = int((valid > 0).sum())
    gross_mean = float(valid.mean())
    net_mean = gross_mean - COST_FRAC

    pos = valid[valid > 0].sum()
    neg = abs(valid[valid < 0].sum())
    pf = pos / neg if neg > 0 else (999.0 if pos > 0 else 1.0)

    return {
        "exit": label,
        "n": n,
        "win_rate": wins / n,
        "gross_expectancy": gross_mean,
        "net_expectancy": net_mean,
        "profit_factor": float(pf),
        "mean_return_bps": gross_mean * 10_000,
        "net_return_bps": net_mean * 10_000,
    }


def run_e4(args) -> int:
    parquet_path = Path(args.parquet)
    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found. Run E1 first.")
        return 1

    print("E4: Horizon Exit Experiment")
    print(f"  Input: {parquet_path}")
    print(f"  Cost assumption: {COST_BPS:.1f} bps ({COST_FRAC*100:.3f}%)")
    print(f"  Cohort: Top {args.top_pct*100:.0f}% SELL by raw_model_score")
    print()

    df = pd.read_parquet(parquet_path)
    sell_df = df[df["side"] == "SELL"].copy().sort_values("raw_model_score", ascending=False).reset_index(drop=True)
    top_k = max(1, int(round(args.top_pct * len(sell_df))))
    cohort = sell_df.head(top_k).copy()

    print(f"  Total SELL candidates: {len(sell_df)}")
    print(f"  Top {args.top_pct*100:.0f}% cohort: n={len(cohort)}")
    print(f"  Score range: [{cohort['raw_model_score'].min():.4f}, {cohort['raw_model_score'].max():.4f}]")
    print()

    # Compute stats for each exit strategy
    results: List[Dict[str, Any]] = []

    for exit_label, ret_col in HORIZON_MAP.items():
        if ret_col not in cohort.columns:
            print(f"  WARNING: Column {ret_col} not found, skipping {exit_label}")
            continue
        stats = compute_stats(cohort[ret_col], exit_label)
        results.append(stats)

    # Current TP/SL contract (lifecycle_gross_return from E1)
    if "lifecycle_gross_return" in cohort.columns:
        stats = compute_stats(cohort["lifecycle_gross_return"], "CURRENT_TPSL")
        results.append(stats)

    if not results:
        print("  ERROR: No exit strategies could be computed.")
        return 1

    result_df = pd.DataFrame(results)

    # ── Print report ──────────────────────────────────────────────────
    print(f"  {'Exit Strategy':<20} {'n':>6} {'Win Rate':>10} {'Gross (bps)':>13} {'Net (bps)':>11} {'Profit Factor':>15}")
    print(f"  {'-'*20} {'-'*6} {'-'*10} {'-'*13} {'-'*11} {'-'*15}")
    for _, row in result_df.iterrows():
        if row["n"] == 0:
            continue
        gross_bps = row["mean_return_bps"]
        net_bps = row["net_return_bps"]
        net_flag = " ✓" if net_bps > 0 else ""
        print(
            f"  {row['exit']:<20} {row['n']:>6} {row['win_rate']:>10.1%} "
            f"{gross_bps:>+12.2f}  {net_bps:>+10.2f}{net_flag}  {row['profit_factor']:>14.3f}"
        )
    print()

    # ── Key diagnostic summary ────────────────────────────────────────
    print("="*72)
    print("  KEY DIAGNOSTIC: Does any exit survive costs?")
    print("="*72)
    net_positive = result_df[result_df["net_return_bps"] > 0]
    tpsl_row = result_df[result_df["exit"] == "CURRENT_TPSL"]
    tpsl_net = float(tpsl_row["net_return_bps"].values[0]) if not tpsl_row.empty else float("nan")

    if net_positive.empty:
        print("  → ALL exits negative after cost.")
        print("  → CASE B or C: edge is not monetizable OR model label is misaligned.")
        print("  → Cross-check with E2 lifecycle AUC to disambiguate.")
    else:
        exits = net_positive["exit"].tolist()
        print(f"  → Net-positive exits: {exits}")
        if "CURRENT_TPSL" not in exits:
            print(f"  → CURRENT_TPSL net = {tpsl_net:+.2f} bps → exit contract is destroying edge.")
            print("  → Candidate finding: fixed-horizon exits preserve more edge than ATR-based TP/SL.")
        else:
            print(f"  → CURRENT_TPSL is also net-positive ({tpsl_net:+.2f} bps). Investigate further.")
    print()

    # ── Write outputs ─────────────────────────────────────────────────
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "e4_horizon_exits.json"
    with open(json_path, "w") as f:
        json.dump(result_df.to_dict(orient="records"), f, indent=2, default=str)
    print(f"  ✓ Saved JSON: {json_path}")

    md_lines = [
        "# HMR-V1.3E-E4: Horizon Exit Experiment\n",
        f"Input: `{parquet_path}` — Top {args.top_pct*100:.0f}% SELL cohort (n={len(cohort)})",
        f"Cost assumption: {COST_BPS:.1f} bps flat\n",
        "| Exit Strategy | n | Win Rate | Gross (bps) | Net (bps) | Profit Factor |",
        "|:--------------|--:|---------:|------------:|----------:|--------------:|",
    ]
    for _, row in result_df.iterrows():
        if row["n"] == 0:
            continue
        net_bps = row["net_return_bps"]
        net_flag = " 🟢" if net_bps > 0 else ""
        md_lines.append(
            f"| {row['exit']} | {row['n']} | {row['win_rate']:.1%} | "
            f"{row['mean_return_bps']:+.2f} | {net_bps:+.2f}{net_flag} | {row['profit_factor']:.3f} |"
        )

    md_path = output_dir / "e4_horizon_exits.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"  ✓ Saved MD:   {md_path}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V1.3E-E4: Horizon Exit Experiment")
    p.add_argument(
        "--parquet",
        default="research/historical_market_replay_v1/v1_3e/e1_candidates.parquet",
    )
    p.add_argument("--output-dir", default="research/historical_market_replay_v1/v1_3e")
    p.add_argument("--top-pct", type=float, default=0.05,
                   help="Top cohort fraction by raw_model_score (0.05 = Top 5%%)")
    return p


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    sys.exit(run_e4(args))
