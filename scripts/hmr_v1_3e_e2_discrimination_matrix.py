#!/usr/bin/env python3
"""HMR-V1.3E-E2: Discrimination Matrix.

Reads e1_candidates.parquet. Computes raw_model_score discrimination
against every possible outcome definition:

  current_label            - training label as-is
  profitable_1bar          - return_1bar > 0
  profitable_4bar          - return_4bar > 0
  profitable_8bar          - return_8bar > 0
  profitable_16bar         - return_16bar > 0
  tp_before_sl_1pct        - TP hit before SL under 1%/1% symmetric contract
  lifecycle_profitable_gross - lifecycle_gross_return > 0
  lifecycle_profitable_net   - lifecycle_net_return > 0

Per target, reports:
  ROC-AUC
  PR-AUC
  Spearman rank correlation (score vs return where applicable)
  Top-quintile mean gross return
  Top-quintile win rate

Key diagnostic:
  If current_label AUC ~0.74 but lifecycle AUC ~0.50
  → MODEL_OBJECTIVE_MISALIGNED (training target != trading target)

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
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.hmr_v1_3b_b0_model_ranking import (
    compute_roc_auc,
    compute_pr_auc,
    compute_rank_correlation,
)


# ──────────────────────────────────────────────────────────────────────
# Target definitions
# ──────────────────────────────────────────────────────────────────────

def build_targets(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """Return dict of target_name -> {labels, returns, description}."""
    targets = {}

    # current_label (training label)
    if "current_label" in df.columns and df["current_label"].notna().any():
        targets["current_label"] = {
            "labels": df["current_label"].fillna(0).astype(int).values,
            "returns": None,
            "description": "Training label (WIN as defined by model training contract)",
        }

    # Fixed-horizon binary profitability
    for h in [1, 4, 8, 16]:
        col = f"return_{h}bar" if h == 1 else f"return_{h}bars"
        if col in df.columns:
            valid = df[col].notna()
            labels = (df[col] > 0).astype(int).values.copy()
            labels[~valid.values] = 0
            targets[f"profitable_{h}bar"] = {
                "labels": labels,
                "returns": df[col].values,
                "description": f"Return at bar +{h} > 0 (fixed horizon exit)",
            }

    # TP before SL under 1%/1%
    if "tp_before_sl_1pct" in df.columns:
        targets["tp_before_sl_1pct"] = {
            "labels": df["tp_before_sl_1pct"].astype(int).values,
            "returns": None,
            "description": "TP hit before SL under 1%/1% symmetric contract",
        }

    # Lifecycle gross/net profitable
    if "lifecycle_gross_return" in df.columns:
        targets["lifecycle_profitable_gross"] = {
            "labels": (df["lifecycle_gross_return"] > 0).astype(int).values,
            "returns": df["lifecycle_gross_return"].values,
            "description": "Lifecycle gross return > 0 (current ATR-based TP/SL contract)",
        }

    if "lifecycle_net_return" in df.columns:
        targets["lifecycle_profitable_net"] = {
            "labels": (df["lifecycle_net_return"] > 0).astype(int).values,
            "returns": df["lifecycle_net_return"].values,
            "description": "Lifecycle net return > 0 (after all-in costs)",
        }

    return targets


def top_quintile_stats(
    scores: np.ndarray,
    labels: np.ndarray,
    returns: Optional[np.ndarray],
) -> Dict[str, float]:
    """Return stats for the top 20% by score."""
    if len(scores) < 5:
        return {"top_quintile_n": 0, "top_quintile_wr": float("nan"), "top_quintile_mean_return": float("nan")}

    cutoff_idx = max(1, int(len(scores) * 0.20))
    sorted_idx = np.argsort(-scores)
    top_idx = sorted_idx[:cutoff_idx]

    top_labels = labels[top_idx]
    wr = float(top_labels.mean()) if len(top_labels) > 0 else float("nan")

    if returns is not None:
        top_returns = returns[top_idx]
        mean_ret = float(np.nanmean(top_returns))
    else:
        mean_ret = float("nan")

    return {
        "top_quintile_n": int(len(top_idx)),
        "top_quintile_wr": wr,
        "top_quintile_mean_return": mean_ret,
    }


def analyze_side(
    df_side: pd.DataFrame,
    side: str,
) -> List[Dict[str, Any]]:
    if df_side.empty:
        return []

    scores = df_side["raw_model_score"].values
    targets = build_targets(df_side)

    rows = []
    for target_name, tgt in targets.items():
        labels = tgt["labels"]
        returns = tgt["returns"]

        roc = compute_roc_auc(labels, scores)
        pr  = compute_pr_auc(labels, scores)

        spearman = float("nan")
        if returns is not None:
            spearman = compute_rank_correlation(scores, returns)

        tq = top_quintile_stats(scores, labels, returns)

        rows.append({
            "side": side,
            "target": target_name,
            "description": tgt["description"],
            "n_total": len(df_side),
            "n_positive": int(labels.sum()),
            "base_rate": float(labels.mean()),
            "roc_auc": roc,
            "pr_auc": pr,
            "spearman_score_vs_return": spearman,
            **tq,
        })

    return rows


def run_e2(args) -> int:
    parquet_path = Path(args.parquet)
    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found. Run E1 first.")
        return 1

    print("E2: Discrimination Matrix")
    print(f"  Input: {parquet_path}")
    print()

    df = pd.read_parquet(parquet_path)
    print(f"  Loaded {len(df)} candidates  ({df['side'].value_counts().to_dict()})")
    print()

    all_rows: List[Dict[str, Any]] = []
    for side in ["SELL", "BUY"]:
        side_df = df[df["side"] == side].copy().reset_index(drop=True)
        rows = analyze_side(side_df, side)
        all_rows.extend(rows)

    result_df = pd.DataFrame(all_rows)

    # ── Print report ──────────────────────────────────────────────────
    for side in ["SELL", "BUY"]:
        sdf = result_df[result_df["side"] == side]
        if sdf.empty:
            continue
        n_total = df[df["side"] == side].shape[0]
        print(f"{'='*72}")
        print(f"  {side} (n={n_total})")
        print(f"{'='*72}")
        print(f"  {'Target':<35} {'ROC-AUC':>8} {'PR-AUC':>8} {'Spearman':>10} {'TopQ-WR':>9} {'TopQ-Ret%':>10}")
        print(f"  {'-'*35} {'-'*8} {'-'*8} {'-'*10} {'-'*9} {'-'*10}")
        for _, row in sdf.iterrows():
            sp = f"{row['spearman_score_vs_return']:+.3f}" if not np.isnan(row['spearman_score_vs_return']) else "   n/a "
            tq_ret = f"{row['top_quintile_mean_return']*100:+.4f}%" if not np.isnan(row['top_quintile_mean_return']) else "     n/a"
            tq_wr = f"{row['top_quintile_wr']:.1%}" if not np.isnan(row['top_quintile_wr']) else "   n/a"
            roc = f"{row['roc_auc']:.4f}" if not np.isnan(row['roc_auc']) else "   n/a"
            pr  = f"{row['pr_auc']:.4f}" if not np.isnan(row['pr_auc']) else "   n/a"
            print(f"  {row['target']:<35} {roc:>8} {pr:>8} {sp:>10} {tq_wr:>9} {tq_ret:>10}")
        print()

    # ── Key diagnostic summary ────────────────────────────────────────
    print("="*72)
    print("  KEY DIAGNOSTIC: current_label vs lifecycle AUC gap (SELL)")
    print("="*72)
    sell_res = result_df[result_df["side"] == "SELL"]
    for target in ["current_label", "tp_before_sl_1pct", "lifecycle_profitable_gross", "lifecycle_profitable_net"]:
        row = sell_res[sell_res["target"] == target]
        if row.empty:
            continue
        roc = row.iloc[0]["roc_auc"]
        print(f"  {target:<35} ROC-AUC = {roc:.4f}")

    print()
    sell_cl = sell_res[sell_res["target"] == "current_label"]["roc_auc"]
    sell_lc = sell_res[sell_res["target"] == "lifecycle_profitable_gross"]["roc_auc"]
    if not sell_cl.empty and not sell_lc.empty:
        gap = float(sell_cl.values[0]) - float(sell_lc.values[0])
        print(f"  AUC gap (current_label - lifecycle_gross): {gap:+.4f}")
        if gap > 0.10:
            print("  → CASE C: MODEL_OBJECTIVE_MISALIGNED — training target != trading target")
        elif gap < 0.05 and float(sell_lc.values[0]) > 0.55:
            print("  → Lifecycle AUC meaningful — investigate E3 execution surface")
        else:
            print("  → Inconclusive — examine full matrix above")
    print()

    # ── Write outputs ─────────────────────────────────────────────────
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "e2_discrimination_matrix.json"
    with open(json_path, "w") as f:
        json.dump(result_df.to_dict(orient="records"), f, indent=2, default=str)
    print(f"  ✓ Saved JSON: {json_path}")

    # Markdown
    md_lines = [
        "# HMR-V1.3E-E2: Discrimination Matrix\n",
        f"Input: `{parquet_path}` — {len(df)} candidates\n",
        "",
    ]
    for side in ["SELL", "BUY"]:
        sdf = result_df[result_df["side"] == side]
        if sdf.empty:
            continue
        n_total = df[df["side"] == side].shape[0]
        md_lines.append(f"## {side} (n={n_total})\n")
        md_lines.append("| Target | ROC-AUC | PR-AUC | Spearman | TopQ WR | TopQ Return |")
        md_lines.append("|--------|--------:|-------:|---------:|--------:|------------:|")
        for _, row in sdf.iterrows():
            roc = f"{row['roc_auc']:.4f}" if not np.isnan(row['roc_auc']) else "n/a"
            pr  = f"{row['pr_auc']:.4f}" if not np.isnan(row['pr_auc']) else "n/a"
            sp  = f"{row['spearman_score_vs_return']:+.3f}" if not np.isnan(row['spearman_score_vs_return']) else "n/a"
            tq_wr  = f"{row['top_quintile_wr']:.1%}" if not np.isnan(row['top_quintile_wr']) else "n/a"
            tq_ret = f"{row['top_quintile_mean_return']*100:+.4f}%" if not np.isnan(row['top_quintile_mean_return']) else "n/a"
            md_lines.append(f"| {row['target']} | {roc} | {pr} | {sp} | {tq_wr} | {tq_ret} |")
        md_lines.append("")

    md_path = output_dir / "e2_discrimination_matrix.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"  ✓ Saved MD:   {md_path}")

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="HMR-V1.3E-E2: Discrimination Matrix")
    p.add_argument(
        "--parquet",
        default="research/historical_market_replay_v1/v1_3e/e1_candidates.parquet",
    )
    p.add_argument(
        "--output-dir",
        default="research/historical_market_replay_v1/v1_3e",
    )
    return p


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    sys.exit(run_e2(args))
