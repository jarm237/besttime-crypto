#!/usr/bin/env python3
"""HMR-V1.3B-B0: Threshold-Free Model Ranking Diagnostics.

Answers the question: Does the model rank good candidates above bad ones,
regardless of what threshold is used?

For every technical candidate in Jan–Mar 2025:
  1. Record raw probability, calibrated probability
  2. Compute forward return (MFE, MAE, gross return) from actual candle data
  3. Classify outcome as win/loss using TP/SL hit simulation
  4. Compute discrimination metrics: ROC-AUC, PR-AUC, Brier, rank correlation
  5. Bucket by probability quintiles and report win rate + mean return per bucket

Reports BUY and SELL sides separately.

Boundary:
  RESEARCH_ONLY
  NO_THRESHOLD_OPTIMIZATION
  NO_MODEL_PROMOTION
"""

import argparse
import json
import math
import os
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import joblib

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.hmr_v1_baseline import (
    load_closed_candles,
    research_model_override,
    isolated_policy_runtime,
)


# ──────────────────────────────────────────────────────────────────────
# Forward return computation
# ──────────────────────────────────────────────────────────────────────

def compute_forward_excursion(
    coin: str,
    side: str,
    entry_time: pd.Timestamp,
    entry_price: float,
    candles: List[Dict[str, Any]],
    horizon_bars: int = 48,
    tp_pct: float = 0.01,
    sl_pct: float = 0.01,
) -> Dict[str, float]:
    """Compute MFE, MAE, gross return, and win/loss for a hypothetical trade.

    Uses the same TP/SL simulation logic as the backtest engine:
    - LONG: TP hit when high >= entry*(1+tp_pct), SL hit when low <= entry*(1-sl_pct)
    - SHORT: TP hit when low <= entry*(1-tp_pct), SL hit when high >= entry*(1+sl_pct)

    Returns dict with keys:
        mfe, mae, gross_return, hit_tp, hit_sl, exit_bar, exit_price, outcome
    """
    # Find candles starting from entry_time
    forward_candles = []
    found_entry = False
    for c in candles:
        c_time = pd.Timestamp(c["time"])
        if not found_entry:
            if c_time >= entry_time:
                found_entry = True
            else:
                continue
        forward_candles.append(c)
        if len(forward_candles) >= horizon_bars:
            break

    if not forward_candles:
        return {
            "mfe": 0.0, "mae": 0.0, "gross_return": 0.0,
            "hit_tp": False, "hit_sl": False,
            "exit_bar": 0, "exit_price": entry_price,
            "outcome": "NO_DATA",
        }

    is_long = side == "BUY"
    tp_price = entry_price * (1 + tp_pct) if is_long else entry_price * (1 - tp_pct)
    sl_price = entry_price * (1 - sl_pct) if is_long else entry_price * (1 + sl_pct)

    highs = [float(c["high"]) for c in forward_candles]
    lows = [float(c["low"]) for c in forward_candles]
    closes = [float(c["close"]) for c in forward_candles]

    # MFE/MAE
    if is_long:
        max_high = max(highs)
        min_low = min(lows)
        mfe = (max_high - entry_price) / entry_price
        mae = (entry_price - min_low) / entry_price  # positive = adverse
    else:
        min_low = min(lows)
        max_high = max(highs)
        mfe = (entry_price - min_low) / entry_price
        mae = (max_high - entry_price) / entry_price

    # TP/SL hit simulation (bar-by-bar, SL first within same bar)
    hit_tp = False
    hit_sl = False
    exit_bar = len(forward_candles) - 1
    exit_price = closes[-1]

    for i, c in enumerate(forward_candles):
        h = float(c["high"])
        l = float(c["low"])
        if is_long:
            if l <= sl_price:
                hit_sl = True
                exit_bar = i
                exit_price = sl_price
                break
            if h >= tp_price:
                hit_tp = True
                exit_bar = i
                exit_price = tp_price
                break
        else:
            if h >= sl_price:
                hit_sl = True
                exit_bar = i
                exit_price = sl_price
                break
            if l <= tp_price:
                hit_tp = True
                exit_bar = i
                exit_price = tp_price
                break

    if is_long:
        gross_return = (exit_price - entry_price) / entry_price
    else:
        gross_return = (entry_price - exit_price) / entry_price

    if hit_tp:
        outcome = "WIN"
    elif hit_sl:
        outcome = "LOSS"
    else:
        # Expired at horizon — classify by gross return
        outcome = "WIN" if gross_return > 0 else "LOSS"

    return {
        "mfe": mfe,
        "mae": mae,
        "gross_return": gross_return,
        "hit_tp": hit_tp,
        "hit_sl": hit_sl,
        "exit_bar": exit_bar,
        "exit_price": exit_price,
        "outcome": outcome,
    }


# ──────────────────────────────────────────────────────────────────────
# Discrimination metrics
# ──────────────────────────────────────────────────────────────────────

def compute_roc_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    """Manual ROC-AUC (no sklearn dependency)."""
    if len(labels) < 2 or labels.sum() == 0 or labels.sum() == len(labels):
        return float("nan")

    # Sort by score descending
    desc_idx = np.argsort(-scores)
    sorted_labels = labels[desc_idx]

    n_pos = labels.sum()
    n_neg = len(labels) - n_pos

    tp = 0
    fp = 0
    auc = 0.0
    prev_fpr = 0.0
    prev_tpr = 0.0

    for i in range(len(sorted_labels)):
        if sorted_labels[i] == 1:
            tp += 1
        else:
            fp += 1
        tpr = tp / n_pos
        fpr = fp / n_neg
        # Trapezoidal rule
        auc += (fpr - prev_fpr) * (tpr + prev_tpr) / 2
        prev_fpr = fpr
        prev_tpr = tpr

    return float(auc)


def compute_pr_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    """Manual PR-AUC (no sklearn dependency)."""
    if len(labels) < 2 or labels.sum() == 0:
        return float("nan")

    desc_idx = np.argsort(-scores)
    sorted_labels = labels[desc_idx]

    tp = 0
    fp = 0
    auc = 0.0
    prev_recall = 0.0
    n_pos = labels.sum()

    for i in range(len(sorted_labels)):
        if sorted_labels[i] == 1:
            tp += 1
        else:
            fp += 1
        precision = tp / (tp + fp)
        recall = tp / n_pos

        if recall > prev_recall:
            auc += precision * (recall - prev_recall)
            prev_recall = recall

    return float(auc)


def compute_brier(labels: np.ndarray, probs: np.ndarray) -> float:
    """Brier score."""
    if len(labels) == 0:
        return float("nan")
    return float(np.mean((probs - labels) ** 2))


def compute_rank_correlation(scores: np.ndarray, returns: np.ndarray) -> float:
    """Spearman rank correlation between scores and forward returns."""
    if len(scores) < 3:
        return float("nan")

    def _rankdata(x):
        temp = np.argsort(x)
        ranks = np.empty_like(temp, dtype=float)
        ranks[temp] = np.arange(len(x), dtype=float) + 1
        return ranks

    rank_s = _rankdata(scores)
    rank_r = _rankdata(returns)
    n = len(scores)
    d = rank_s - rank_r
    return float(1 - 6 * np.sum(d ** 2) / (n * (n ** 2 - 1)))


# ──────────────────────────────────────────────────────────────────────
# Quintile bucketing
# ──────────────────────────────────────────────────────────────────────

def quintile_analysis(
    df: pd.DataFrame,
    prob_col: str,
    label: str,
) -> List[Dict[str, Any]]:
    """Bucket candidates by probability quintile and report per-bucket stats."""
    if df.empty:
        return []

    df = df.copy()
    # Use 5 equal-frequency bins
    try:
        df["quintile"] = pd.qcut(df[prob_col], 5, labels=False, duplicates="drop")
    except ValueError:
        # Not enough unique values for 5 bins
        df["quintile"] = pd.cut(df[prob_col], 5, labels=False, duplicates="drop")

    if df["quintile"].isna().all():
        return []

    results = []
    for q in sorted(df["quintile"].dropna().unique()):
        bucket = df[df["quintile"] == q]
        n = len(bucket)
        wins = int((bucket["outcome"] == "WIN").sum())
        results.append({
            "quintile": f"Q{int(q)+1}",
            "prob_label": label,
            "prob_min": float(bucket[prob_col].min()),
            "prob_max": float(bucket[prob_col].max()),
            "prob_mean": float(bucket[prob_col].mean()),
            "n": n,
            "wins": wins,
            "win_rate": wins / n if n > 0 else 0.0,
            "mean_gross_return": float(bucket["gross_return"].mean()),
            "mean_mfe": float(bucket["mfe"].mean()),
            "mean_mae": float(bucket["mae"].mean()),
        })
    return results


# ──────────────────────────────────────────────────────────────────────
# Main diagnostic
# ──────────────────────────────────────────────────────────────────────

def run_b0_diagnostics(args) -> int:
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    settlement_end = end + pd.Timedelta(args.timeframe) * args.settlement_bars

    print(f"B0 Model Ranking Diagnostics")
    print(f"  Window: {start.date()} → {end.date()}")
    print(f"  Coins: {coins}")
    print(f"  Horizon: {args.horizon_bars} bars ({args.horizon_bars * 15} min)")
    print(f"  TP/SL: {args.tp_pct*100:.2f}% / {args.sl_pct*100:.2f}%")
    print()

    # 1. Load candles
    candles = load_closed_candles(
        Path(args.data_dir), coins, args.timeframe, start, end, settlement_end,
        warmup_bars=args.warmup_bars,
    )

    for coin_rows in candles.values():
        for row in coin_rows:
            row["time"] = pd.Timestamp(row["time"]).strftime("%Y-%m-%d %H:%M:%S")

    # 2. Load model
    manifest_path = Path(args.research_artifact_manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle_path = REPO_ROOT / manifest["paths"]["bundle"]
    bundle = joblib.load(bundle_path)
    cclf = bundle["model"]
    feature_names = bundle["features"]

    # 3. Import pipeline components
    from btc_scraper.analysis import analyze_all_market
    from btc_scraper.ml_engine.causal_context_bridge import get_hybrid_provider
    from btc_scraper.ml_engine.inference_coordinator import InferenceCoordinator
    from btc_scraper.ml_engine.feature_extractor import build_meta_features_v2

    # 4. Build analysis timeline
    analysis_by_time: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for coin in coins:
        rows = [dict(c) for c in candles.get(coin, [])]
        for val in analyze_all_market(rows):
            observed_at = pd.Timestamp(val["time"], tz="UTC")
            if start <= observed_at <= end:
                analysis_by_time.setdefault(val["time"], {})[coin] = val

    # 5. Score all technical candidates
    coordinator = InferenceCoordinator()
    candidate_records = []

    with research_model_override(str(manifest_path)):
        with isolated_policy_runtime():
            timestamps = sorted(analysis_by_time.keys())
            n_ts = len(timestamps)
            for idx, observed_at in enumerate(timestamps):
                if (idx + 1) % 200 == 0:
                    print(f"  Processing {idx+1}/{n_ts} timestamps...")
                cycle_id = f"b0-{pd.Timestamp(observed_at).strftime('%Y%m%dT%H%M%SZ')}"
                for coin in coins:
                    analysis = analysis_by_time[observed_at].get(coin)
                    if analysis is None:
                        continue
                    analysis = dict(analysis)
                    analysis.update({
                        "coin": coin,
                        "symbol": f"{coin}USDT",
                        "timeframe": args.timeframe,
                        "cycle_id": cycle_id,
                        "observed_at": observed_at,
                    })

                    tech_action = str(analysis.get("action")).upper()
                    is_tech_buy = tech_action == "BUY"
                    is_tech_sell = tech_action == "SELL"

                    if not (is_tech_buy or is_tech_sell):
                        continue

                    side = "BUY" if is_tech_buy else "SELL"

                    # Get model predictions
                    prediction = coordinator.predict_once(
                        analysis,
                        symbol=coin,
                        timeframe=args.timeframe,
                        decision_context="entry",
                        caller_context="hmr_v1_3b_b0",
                    )

                    # Raw probability (before calibration)
                    feat = build_meta_features_v2(analysis)
                    row_feat = [float(feat.get(k, 0.0)) for k in feature_names]
                    raw_prob = float(
                        cclf.calibrated_classifiers_[0].estimator.predict_proba(
                            [row_feat]
                        )[0, 1]
                    )
                    calibrated_prob = prediction.probability

                    # Forward return
                    entry_price = float(analysis.get("close", 0.0))
                    entry_ts = pd.Timestamp(observed_at)
                    coin_candles = candles.get(coin, [])

                    fwd = compute_forward_excursion(
                        coin=coin,
                        side=side,
                        entry_time=entry_ts,
                        entry_price=entry_price,
                        candles=coin_candles,
                        horizon_bars=args.horizon_bars,
                        tp_pct=args.tp_pct,
                        sl_pct=args.sl_pct,
                    )

                    candidate_records.append({
                        "timestamp": observed_at,
                        "coin": coin,
                        "side": side,
                        "raw_prob": raw_prob,
                        "calibrated_prob": calibrated_prob,
                        "entry_price": entry_price,
                        "outcome": fwd["outcome"],
                        "gross_return": fwd["gross_return"],
                        "mfe": fwd["mfe"],
                        "mae": fwd["mae"],
                        "hit_tp": fwd["hit_tp"],
                        "hit_sl": fwd["hit_sl"],
                        "exit_bar": fwd["exit_bar"],
                    })

    print(f"\n  Total technical candidates scored: {len(candidate_records)}")

    # 6. Build DataFrame
    df = pd.DataFrame(candidate_records)
    if df.empty:
        print("  WARNING: No technical candidates found. Cannot compute diagnostics.")
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        empty_result = {"error": "NO_TECHNICAL_CANDIDATES", "n": 0}
        (output_dir / "b0_model_ranking.json").write_text(
            json.dumps(empty_result, indent=2), encoding="utf-8"
        )
        return 0

    # 7. Compute discrimination metrics per side and overall
    results = {}
    for scope_name, scope_df in [("ALL", df), ("BUY", df[df["side"] == "BUY"]), ("SELL", df[df["side"] == "SELL"])]:
        if scope_df.empty or scope_df["outcome"].isin(["NO_DATA"]).all():
            results[scope_name] = {"n": 0, "error": "EMPTY_OR_NO_DATA"}
            continue

        # Filter out NO_DATA outcomes
        eval_df = scope_df[scope_df["outcome"] != "NO_DATA"].copy()
        labels = (eval_df["outcome"] == "WIN").astype(int).values
        raw_probs = eval_df["raw_prob"].values
        calib_probs = eval_df["calibrated_prob"].values
        returns = eval_df["gross_return"].values

        n = len(eval_df)
        n_win = int(labels.sum())
        base_rate = n_win / n if n > 0 else 0.0

        # Discrimination metrics
        metrics = {
            "n": n,
            "n_win": n_win,
            "n_loss": n - n_win,
            "base_rate": base_rate,
            "raw_prob_distribution": {
                "min": float(raw_probs.min()),
                "p25": float(np.percentile(raw_probs, 25)),
                "median": float(np.median(raw_probs)),
                "p75": float(np.percentile(raw_probs, 75)),
                "max": float(raw_probs.max()),
                "mean": float(raw_probs.mean()),
                "std": float(raw_probs.std()),
            },
            "calibrated_prob_distribution": {
                "min": float(calib_probs.min()),
                "p25": float(np.percentile(calib_probs, 25)),
                "median": float(np.median(calib_probs)),
                "p75": float(np.percentile(calib_probs, 75)),
                "max": float(calib_probs.max()),
                "mean": float(calib_probs.mean()),
                "std": float(calib_probs.std()),
            },
            "return_distribution": {
                "min": float(returns.min()),
                "p25": float(np.percentile(returns, 25)),
                "median": float(np.median(returns)),
                "p75": float(np.percentile(returns, 75)),
                "max": float(returns.max()),
                "mean": float(returns.mean()),
                "std": float(returns.std()),
            },
            "raw_roc_auc": compute_roc_auc(labels, raw_probs),
            "raw_pr_auc": compute_pr_auc(labels, raw_probs),
            "raw_brier": compute_brier(labels, raw_probs),
            "raw_rank_corr_return": compute_rank_correlation(raw_probs, returns),
            "calibrated_roc_auc": compute_roc_auc(labels, calib_probs),
            "calibrated_pr_auc": compute_pr_auc(labels, calib_probs),
            "calibrated_brier": compute_brier(labels, calib_probs),
            "calibrated_rank_corr_return": compute_rank_correlation(calib_probs, returns),
        }

        # Quintile analysis
        metrics["raw_quintiles"] = quintile_analysis(eval_df, "raw_prob", "raw_probability")
        metrics["calibrated_quintiles"] = quintile_analysis(eval_df, "calibrated_prob", "calibrated_probability")

        results[scope_name] = metrics

    # 8. Write outputs
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Raw data
    (output_dir / "b0_candidates.jsonl").write_text(
        "\n".join(json.dumps(r) for r in candidate_records),
        encoding="utf-8",
    )

    # Metrics JSON
    # Convert NaN to null for JSON serialization
    def sanitize(obj):
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        if isinstance(obj, dict):
            return {k: sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [sanitize(v) for v in obj]
        return obj

    (output_dir / "b0_model_ranking.json").write_text(
        json.dumps(sanitize(results), indent=2), encoding="utf-8",
    )

    # 9. Generate markdown report
    report = _generate_report(results, len(candidate_records), args)
    (output_dir / "b0_model_ranking.md").write_text(report, encoding="utf-8")

    print(f"\n  Results written to {output_dir}")
    print("B0 diagnostics completed successfully.")
    return 0


def _generate_report(results: Dict, n_total: int, args) -> str:
    """Generate the B0 markdown report."""
    lines = [
        "# HMR-V1.3B-B0: Threshold-Free Model Ranking Diagnostics",
        "",
        f"**Window**: {args.start[:10]} → {args.end[:10]}",
        f"**Coins**: {args.coins}",
        f"**Forward horizon**: {args.horizon_bars} bars ({args.horizon_bars * 15} min)",
        f"**TP/SL for outcome classification**: {args.tp_pct*100:.2f}% / {args.sl_pct*100:.2f}%",
        f"**Total technical candidates scored**: {n_total}",
        "",
        "---",
        "",
    ]

    for scope in ["ALL", "BUY", "SELL"]:
        m = results.get(scope, {})
        if m.get("error"):
            lines.extend([
                f"## {scope}",
                f"No data available: {m.get('error', 'unknown')}",
                "",
            ])
            continue

        lines.extend([
            f"## {scope} (n={m['n']}, wins={m['n_win']}, base_rate={m['base_rate']*100:.2f}%)",
            "",
            "### Discrimination Metrics",
            "",
            "| Metric | Raw Model | Calibrated |",
            "| :--- | ---: | ---: |",
            f"| ROC-AUC | {_fmt(m['raw_roc_auc'])} | {_fmt(m['calibrated_roc_auc'])} |",
            f"| PR-AUC | {_fmt(m['raw_pr_auc'])} | {_fmt(m['calibrated_pr_auc'])} |",
            f"| Brier Score | {_fmt(m['raw_brier'])} | {_fmt(m['calibrated_brier'])} |",
            f"| Rank Corr (return) | {_fmt(m['raw_rank_corr_return'])} | {_fmt(m['calibrated_rank_corr_return'])} |",
            "",
        ])

        # Probability distributions
        for label, key in [("Raw", "raw_prob_distribution"), ("Calibrated", "calibrated_prob_distribution")]:
            d = m[key]
            lines.extend([
                f"### {label} Probability Distribution",
                f"  min={d['min']:.4f}  p25={d['p25']:.4f}  median={d['median']:.4f}  "
                f"p75={d['p75']:.4f}  max={d['max']:.4f}  mean={d['mean']:.4f}  std={d['std']:.4f}",
                "",
            ])

        # Return distribution
        d = m["return_distribution"]
        lines.extend([
            "### Forward Return Distribution",
            f"  min={d['min']*100:.3f}%  p25={d['p25']*100:.3f}%  median={d['median']*100:.3f}%  "
            f"p75={d['p75']*100:.3f}%  max={d['max']*100:.3f}%  mean={d['mean']*100:.3f}%",
            "",
        ])

        # Quintile tables
        for q_key, q_label in [("raw_quintiles", "Raw Model"), ("calibrated_quintiles", "Calibrated")]:
            quintiles = m.get(q_key, [])
            if not quintiles:
                continue
            lines.extend([
                f"### {q_label} Quintile Analysis",
                "",
                "| Quintile | Prob Range | N | Win Rate | Mean Gross Return | Mean MFE | Mean MAE |",
                "| :--- | :--- | ---: | ---: | ---: | ---: | ---: |",
            ])
            for q in quintiles:
                lines.append(
                    f"| {q['quintile']} | [{q['prob_min']:.4f}, {q['prob_max']:.4f}] "
                    f"| {q['n']} | {q['win_rate']*100:.2f}% "
                    f"| {q['mean_gross_return']*100:.3f}% "
                    f"| {q['mean_mfe']*100:.3f}% "
                    f"| {q['mean_mae']*100:.3f}% |"
                )
            lines.append("")

        lines.extend([
            "---",
            "",
        ])

    # Interpretation guide
    lines.extend([
        "## Interpretation Guide",
        "",
        "### ROC-AUC",
        "- **> 0.55**: Model has some discriminative ability",
        "- **≈ 0.50**: No better than random — model has NO ranking edge",
        "- **< 0.50**: Model is inversely predictive (worse than random)",
        "",
        "### Quintile Pattern",
        "- **Monotonic increase**: Model correctly ranks candidates (edge exists)",
        "- **Flat**: Model has no useful discrimination",
        "- **Inverted**: Model actively selects worse candidates",
        "",
        "### Raw vs Calibrated",
        "- If raw ROC-AUC > calibrated ROC-AUC: calibration destroys ranking",
        "- If raw ≈ calibrated: calibration preserves (or doesn't help) ranking",
        "- If calibrated > raw: calibration improves ranking (unusual but possible)",
        "",
        "### Brier Score",
        "- Lower is better",
        "- Compare to baseline Brier = base_rate × (1 - base_rate)",
        "- If model Brier > baseline Brier: model is worse than always predicting base rate",
        "",
    ])

    return "\n".join(lines)


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "N/A"
    return f"{v:.4f}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="HMR-V1.3B-B0: Threshold-Free Model Ranking Diagnostics"
    )
    parser.add_argument("--start", default="2025-01-01T00:00:00+00:00")
    parser.add_argument("--end", default="2025-03-31T23:45:00+00:00")
    parser.add_argument("--coins", default="BTC,ETH,BNB")
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--data-dir", default="data/fresh_training_data_2023_2026")
    parser.add_argument("--settlement-bars", type=int, default=49)
    parser.add_argument("--warmup-bars", type=int, default=260)
    parser.add_argument("--horizon-bars", type=int, default=48,
                        help="Forward look horizon in bars (default: 48 = 12h)")
    parser.add_argument("--tp-pct", type=float, default=0.01,
                        help="Take-profit percentage for outcome classification (default: 1%%)")
    parser.add_argument("--sl-pct", type=float, default=0.01,
                        help="Stop-loss percentage for outcome classification (default: 1%%)")
    parser.add_argument(
        "--research-artifact-manifest",
        default="research/historical_market_replay_v1/research_artifact_pre2025/manifest.json",
    )
    parser.add_argument(
        "--output-dir",
        default="research/historical_market_replay_v1/v1_3b/b0_model_ranking",
    )
    args = parser.parse_args()

    sys.exit(run_b0_diagnostics(args))
