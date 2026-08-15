#!/usr/bin/env python3
"""HMR-V1.3E-E3: TP/SL Counterfactual Surface.

Reads e1_candidates.parquet. With the Top 5% SELL cohort (by raw_model_score),
sweeps a 5×5 grid of ATR-based TP/SL multipliers and reports economic outcomes:

  TP × ATR: [0.5, 1.0, 1.5, 2.0, 3.0]
  SL × ATR: [0.5, 1.0, 1.5, 2.0, 2.5]
  → 25 combinations

Per combination:
  n_trades
  win_rate
  gross_expectancy (mean)
  net_expectancy (gross - cost)
  profit_factor
  max_drawdown (sequential)
  MFE capture ratio (mean gross / mean MFE)

Key question: Is there ANY combination where net_expectancy > 0?

Boundary:
  RESEARCH_ONLY — this is a diagnostic surface, NOT a final TP/SL selection.
  NO_THRESHOLD_OPTIMIZATION
  NO_MODEL_PROMOTION
"""

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ──────────────────────────────────────────────────────────────────────
# Grid definition
# ──────────────────────────────────────────────────────────────────────

TP_MULTS = [0.5, 1.0, 1.5, 2.0, 3.0]
SL_MULTS = [0.5, 1.0, 1.5, 2.0, 2.5]
TIMEOUT_BARS = 48

# Approximate flat cost assumption (consistent with D1/D2 cost model ~15 bps)
COST_BPS = 15.0
COST_FRAC = COST_BPS / 10_000.0


# ──────────────────────────────────────────────────────────────────────
# Per-combination simulation
# ──────────────────────────────────────────────────────────────────────

def simulate_tpsl(
    df: pd.DataFrame,
    tp_mult: float,
    sl_mult: float,
    forward_candles_col: str = "_forward_candles",
) -> Dict[str, Any]:
    """Simulate TP/SL exits for all rows in df using pre-loaded forward candles.

    df must have columns: side, entry_price, atr_pct, mfe_pct, and the
    simulation uses the bar-by-bar forward candle data stored in the parquet's
    e1_forward_bars_* columns (if available), or falls back to ATR-based
    approximation.

    Since E1 parquet stores return_Nbar columns (fixed horizons) but not
    individual bar OHLC, we use a fast approximation:
    - MFE_pct proxy for max favorable, MAE_pct proxy for max adverse
    - Derive TP hit probability from MFE >= TP target and SL from MAE >= SL target

    For accurate bar-by-bar re-simulation we would need the raw candles,
    which are not stored in the parquet. This approximation is used here.
    For higher precision, E1 would need to store bar-level data.
    """
    results = []
    for _, row in df.iterrows():
        atr = float(row["atr_pct"])
        mfe = float(row["mfe_pct"])
        mae = float(row["mae_pct"])
        lc_gross = float(row["lifecycle_gross_return"])

        tp_target = atr * tp_mult
        sl_target = atr * sl_mult

        # Fast approximation using excursion envelopes
        # hit_tp iff MFE reaches target before MAE reaches SL
        # (conservative: if both within same bar, assume SL priority)
        tp_hit = mfe >= tp_target
        sl_hit = mae >= sl_target

        if sl_hit and tp_hit:
            # Ambiguous: approximate by MAE/MFE ratio heuristic
            # If MAE threshold is proportionally smaller, SL more likely first
            if (sl_target / atr) <= (tp_target / atr):
                sl_hit = True
                tp_hit = False
            else:
                tp_hit = True
                sl_hit = False

        if tp_hit:
            gross = tp_target
            outcome = "WIN"
        elif sl_hit:
            gross = -sl_target
            outcome = "LOSS"
        else:
            # Timeout: use lifecycle_gross_return (best available approximation)
            gross = lc_gross
            outcome = "TIMEOUT"

        results.append({
            "gross": gross,
            "outcome": outcome,
        })

    if not results:
        return {
            "tp_mult": tp_mult, "sl_mult": sl_mult,
            "n_trades": 0, "win_rate": float("nan"),
            "gross_expectancy": float("nan"), "net_expectancy": float("nan"),
            "profit_factor": float("nan"), "max_drawdown": float("nan"),
            "mfe_capture": float("nan"),
        }

    res_df = pd.DataFrame(results)
    n = len(res_df)
    wins = int((res_df["outcome"] == "WIN").sum())
    gross_mean = float(res_df["gross"].mean())
    net_mean = gross_mean - COST_FRAC

    pos = res_df[res_df["gross"] > 0]["gross"].sum()
    neg = abs(res_df[res_df["gross"] < 0]["gross"].sum())
    pf = pos / neg if neg > 0 else (999.0 if pos > 0 else 1.0)

    # Sequential max drawdown (cumulative pnl trough)
    cum_pnl = res_df["gross"].cumsum()
    running_max = cum_pnl.cummax()
    drawdown = (running_max - cum_pnl).max()

    # MFE capture: fraction of MFE realized as gross
    mfe_mean = float(df["mfe_pct"].mean())
    mfe_capture = gross_mean / mfe_mean if mfe_mean > 0 else float("nan")

    return {
        "tp_mult": tp_mult,
        "sl_mult": sl_mult,
        "n_trades": n,
        "win_rate": wins / n,
        "gross_expectancy": gross_mean,
        "net_expectancy": net_mean,
        "profit_factor": pf,
        "max_drawdown": float(drawdown),
        "mfe_capture": mfe_capture,
    }


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def run_e3(args) -> int:
    parquet_path = Path(args.parquet)
    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found. Run E1 first.")
        return 1

    print("E3: TP/SL Counterfactual Surface")
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

    # Run grid
    grid_results: List[Dict[str, Any]] = []
    for tp_m in TP_MULTS:
        for sl_m in SL_MULTS:
            res = simulate_tpsl(cohort, tp_m, sl_m)
            grid_results.append(res)

    result_df = pd.DataFrame(grid_results)

    # ── Print heatmaps ────────────────────────────────────────────────
    def pivot_heatmap(metric: str, fmt: str = ".4f") -> str:
        piv = result_df.pivot(index="sl_mult", columns="tp_mult", values=metric)
        lines = [f"\n  {metric.upper()} HEATMAP (rows=SL×ATR, cols=TP×ATR)"]
        header = "  SL\\TP  |" + "".join(f"  TP={t:.1f}" for t in TP_MULTS)
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for sl_m in SL_MULTS:
            row_label = f"  SL={sl_m:.1f} |"
            vals = []
            for tp_m in TP_MULTS:
                v = piv.loc[sl_m, tp_m] if sl_m in piv.index and tp_m in piv.columns else float("nan")
                if np.isnan(v):
                    vals.append("    n/a")
                else:
                    vals.append(f"  {v:{fmt}}")
            lines.append(row_label + "".join(vals))
        return "\n".join(lines)

    print(pivot_heatmap("net_expectancy", "+.4f"))
    print(pivot_heatmap("win_rate", ".3f"))
    print(pivot_heatmap("profit_factor", ".3f"))
    print()

    # ── Highlight any net-positive cells ─────────────────────────────
    net_pos = result_df[result_df["net_expectancy"] > 0]
    if net_pos.empty:
        print("  ⚠️  No configuration in grid yields net_expectancy > 0.")
        print("  → CASE B candidate: ranking edge may not be monetizable at current cost level.")
    else:
        print(f"  ✓ {len(net_pos)} configurations with net_expectancy > 0:")
        for _, r in net_pos.iterrows():
            print(f"    TP={r['tp_mult']:.1f}×ATR  SL={r['sl_mult']:.1f}×ATR  "
                  f"net={r['net_expectancy']*10_000:+.1f} bps  WR={r['win_rate']:.1%}")

    # ── Also show current production contract as reference ────────────
    print()
    print(f"  Reference — current execution contract (TP=3.13×ATR, SL=2.39×ATR):")
    ref = simulate_tpsl(cohort, tp_mult=3.1312, sl_mult=2.3897)
    print(f"    WR={ref['win_rate']:.1%}  gross={ref['gross_expectancy']*10_000:+.1f} bps  "
          f"net={ref['net_expectancy']*10_000:+.1f} bps  PF={ref['profit_factor']:.3f}")
    print()

    # ── Write outputs ─────────────────────────────────────────────────
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "e3_tpsl_surface.json"
    with open(json_path, "w") as f:
        json.dump(result_df.to_dict(orient="records"), f, indent=2, default=str)
    print(f"  ✓ Saved JSON: {json_path}")

    md_lines = [
        "# HMR-V1.3E-E3: TP/SL Counterfactual Surface\n",
        f"> [!WARNING]",
        f"> DIAGNOSTIC surface only — NOT a TP/SL selection. Key question: is there ANY net-positive cell?\n",
        f"Input: `{parquet_path}` — Top {args.top_pct*100:.0f}% SELL cohort (n={len(cohort)})",
        f"Cost assumption: {COST_BPS:.1f} bps flat\n",
        "## Net Expectancy (bps)\n",
        "| SL\\TP |" + "|".join(f" TP={t:.1f}×ATR " for t in TP_MULTS) + "|",
        "|-------|" + "|".join(":---------:" for _ in TP_MULTS) + "|",
    ]
    piv_net = result_df.pivot(index="sl_mult", columns="tp_mult", values="net_expectancy")
    for sl_m in SL_MULTS:
        row = [f"**SL={sl_m:.1f}×**"]
        for tp_m in TP_MULTS:
            v = piv_net.loc[sl_m, tp_m]
            bps = v * 10_000
            prefix = "🟢 " if bps > 0 else ""
            row.append(f"{prefix}{bps:+.1f}")
        md_lines.append("| " + " | ".join(row) + " |")

    md_lines.extend([
        "",
        "## Win Rate\n",
        "| SL\\TP |" + "|".join(f" TP={t:.1f}×ATR " for t in TP_MULTS) + "|",
        "|-------|" + "|".join(":---------:" for _ in TP_MULTS) + "|",
    ])
    piv_wr = result_df.pivot(index="sl_mult", columns="tp_mult", values="win_rate")
    for sl_m in SL_MULTS:
        row = [f"**SL={sl_m:.1f}×**"]
        for tp_m in TP_MULTS:
            v = piv_wr.loc[sl_m, tp_m]
            row.append(f"{v:.1%}")
        md_lines.append("| " + " | ".join(row) + " |")

    md_path = output_dir / "e3_tpsl_surface.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"  ✓ Saved MD:   {md_path}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V1.3E-E3: TP/SL Counterfactual Surface")
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
    sys.exit(run_e3(args))
