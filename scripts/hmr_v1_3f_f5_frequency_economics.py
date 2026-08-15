#!/usr/bin/env python3
"""HMR-V1.3F-F5: Frequency Economics.

Reads f0_candidates.parquet. For the Top 5% SELL cohort, translates per-trade metrics
into daily portfolio-level metrics across all exit horizons:
  1, 2, 4, 8, 16, 24, 32, 48, 72, 96, 192 bars

Key metrics reported per horizon:
  - holding_time_hours: H * 0.25 hours (since 1 bar = 15 mins)
  - gross_edge_per_trade_bps: mean gross return of cohort
  - trades_per_day: total cohort trades / total days in dataset
  - daily_turnover: trades_per_day (assuming unit size allocation per trade)
  - daily_cost_bps: trades_per_day * 15.0 bps flat cost
  - daily_net_ev_bps: trades_per_day * (gross_edge_per_trade_bps - 15.0)

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

HORIZONS = [1, 2, 4, 8, 16, 24, 32, 48, 72, 96, 192]
COST_BPS = 15.0


def run_f5_frequency_economics(args) -> int:
    parquet_path = Path(args.parquet)
    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found. Run F0 first.")
        return 1

    print("F5: Frequency Economics Analysis")
    print(f"  Input: {parquet_path}")
    print(f"  Cost assumption: {COST_BPS:.1f} bps flat")
    print(f"  Cohort: Top {args.top_pct*100:.0f}% SELL by raw_model_score")
    print()

    df = pd.read_parquet(parquet_path)
    sell_df = df[df["side"] == "SELL"].copy().sort_values("raw_model_score", ascending=False).reset_index(drop=True)
    top_k = max(1, int(round(args.top_pct * len(sell_df))))
    cohort = sell_df.head(top_k).copy()

    # Calculate days in the dataset dynamically
    cohort["timestamp"] = pd.to_datetime(cohort["timestamp"])
    min_time = cohort["timestamp"].min()
    max_time = cohort["timestamp"].max()
    
    if pd.isna(min_time) or pd.isna(max_time) or min_time == max_time:
        # Default to 90 days (Jan-Mar 2025) if time is missing/invalid
        days = 90.0
    else:
        days = (max_time - min_time).total_seconds() / 86400.0
        # Sanity floor to avoid division by zero
        days = max(1.0, days)

    print(f"  Total SELL candidates: {len(sell_df)}")
    print(f"  Cohort size: n={len(cohort)}")
    print(f"  Dataset timespan: {days:.2f} days ({min_time.date()} to {max_time.date()})")
    print()

    results: List[Dict[str, Any]] = []

    for h in HORIZONS:
        col = f"return_{h}bar" if h == 1 else f"return_{h}bars"
        if col not in cohort.columns:
            continue
            
        returns = cohort[col].dropna()
        if returns.empty:
            continue
            
        n_trades = len(returns)
        holding_hours = h * 0.25  # 15 mins = 0.25h
        
        # Per trade metrics
        gross_trade_bps = float(returns.mean()) * 10_000.0
        net_trade_bps = gross_trade_bps - COST_BPS
        
        # Daily metrics
        trades_per_day = n_trades / days
        daily_cost_bps = trades_per_day * COST_BPS
        daily_net_ev_bps = trades_per_day * net_trade_bps

        results.append({
            "horizon_bars": h,
            "holding_time_hours": holding_hours,
            "trades_count": n_trades,
            "gross_trade_bps": gross_trade_bps,
            "net_trade_bps": net_trade_bps,
            "trades_per_day": trades_per_day,
            "daily_cost_bps": daily_cost_bps,
            "daily_net_ev_bps": daily_net_ev_bps
        })

    # Print report
    print(
        f"  {'Horizon':<10} {'Hold (h)':<9} {'Trades':<8} {'Trade Gross':<13} "
        f"{'Trade Net':<11} {'Trades/Day':<12} {'Daily Cost':<12} {'Daily Net EV':<14}"
    )
    print(f"  {'-'*98}")
    for r in results:
        net_ev = r["daily_net_ev_bps"]
        flag = " 🟢" if net_ev > 0 else ""
        print(
            f"  {r['horizon_bars']:>3} bars   {r['holding_time_hours']:>7.2f}h   {r['trades_count']:>6}   "
            f"{r['gross_trade_bps']:>+10.2f} bps  {r['net_trade_bps']:>+8.2f} bps  {r['trades_per_day']:>10.3f}   "
            f"{r['daily_cost_bps']:>9.2f} bps  {r['daily_net_ev_bps']:>+11.2f} bps{flag}"
        )
    print()

    # Save outputs
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "f5_frequency_economics.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  ✓ Saved JSON: {json_path}")

    # Build markdown report
    md_lines = [
        "# HMR-V1.3F-F5: Frequency Economics Report\n",
        f"Input: `{parquet_path}` — Top {args.top_pct*100:.0f}% SELL cohort (n={len(cohort)})\n",
        f"Dataset window spans **{days:.2f} days**  \n",
        f"Cost assumption: **{COST_BPS:.1f} bps** flat per trade\n",
        "| Horizon | Hold Time | n | Gross/Trade | Net/Trade | Trades/Day | Daily Cost | Daily Net EV |",
        "|:--------|:----------|--:|------------:|----------:|-----------:|-----------:|-------------:|",
    ]
    for r in results:
        net_ev = r["daily_net_ev_bps"]
        flag = " 🟢" if net_ev > 0 else ""
        md_lines.append(
            f"| {r['horizon_bars']} bars | {r['holding_time_hours']:.2f} hours | {r['trades_count']} | "
            f"{r['gross_trade_bps']:+.2f} bps | {r['net_trade_bps']:+.2f} bps | {r['trades_per_day']:.3f} | "
            f"{r['daily_cost_bps']:.2f} bps | {r['daily_net_ev_bps']:+.2f} bps{flag} |"
        )

    md_path = output_dir / "f5_frequency_economics.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"  ✓ Saved MD:   {md_path}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V1.3F-F5: Frequency Economics")
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
    sys.exit(run_f5_frequency_economics(args))
