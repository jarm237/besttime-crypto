#!/usr/bin/env python3
"""HMR-V1.3C-C2: Cumulative Top-k Economic Ranking Diagnostics.

Loads technical candidates from Jan-Mar 2025, scores them using the raw model,
computes forward return metrics under the default TP/SL contract, and aggregates
them into cumulative top-k buckets (Top 1%, 2.5%, 5%, 10%, 20%, 30%, 50%, 100%).
"""

import argparse
import json
import math
import os
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Tuple

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
from scripts.hmr_v1_3b_b0_model_ranking import compute_forward_excursion


def cumulative_economic_analysis(
    df: pd.DataFrame,
    prob_col: str,
) -> List[Dict[str, Any]]:
    """Sort candidates by probability descending and calculate cumulative top-k stats."""
    if df.empty:
        return []

    # Sort descending
    df_sorted = df.sort_values(by=prob_col, ascending=False).reset_index(drop=True)
    n_total = len(df_sorted)

    percentiles = [0.01, 0.025, 0.05, 0.10, 0.20, 0.30, 0.50, 1.00]
    results = []

    for p in percentiles:
        k = max(1, int(round(p * n_total)))
        bucket = df_sorted.head(k)
        
        n = len(bucket)
        wins = int((bucket["outcome"] == "WIN").sum())
        gross_returns = bucket["gross_return"].values

        results.append({
            "bucket": f"Top {p*100:.1f}%",
            "percentile": p,
            "cutoff_prob": float(bucket[prob_col].iloc[-1]) if n > 0 else 0.0,
            "n": n,
            "wins": wins,
            "win_rate": wins / n if n > 0 else 0.0,
            "mean_gross_return": float(bucket["gross_return"].mean()),
            "median_gross_return": float(bucket["gross_return"].median()),
            "gross_expectancy": float(bucket["gross_return"].mean()),  # Gross expectancy is the average return
            "mean_mfe": float(bucket["mfe"].mean()),
            "mean_mae": float(bucket["mae"].mean()),
        })

    return results


def run_c2_diagnostics(args) -> int:
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    settlement_end = end + pd.Timedelta(args.timeframe) * args.settlement_bars

    print(f"C2 Top-k Economic Ranking Diagnostics")
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
                cycle_id = f"c2-{pd.Timestamp(observed_at).strftime('%Y%m%dT%H%M%SZ')}"
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
                        caller_context="hmr_v1_3c_c2",
                    )

                    # Raw probability (before calibration)
                    feat = build_meta_features_v2(analysis)
                    row_feat = [float(feat.get(k, 0.0)) for k in feature_names]
                    raw_prob = float(
                        cclf.calibrated_classifiers_[0].estimator.predict_proba(
                            [row_feat]
                        )[0, 1]
                    )
                    
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
                        "entry_price": entry_price,
                        "outcome": fwd["outcome"],
                        "gross_return": fwd["gross_return"],
                        "mfe": fwd["mfe"],
                        "mae": fwd["mae"],
                    })

    print(f"\n  Total technical candidates scored: {len(candidate_records)}")

    # 6. Build DataFrame
    df = pd.DataFrame(candidate_records)
    if df.empty:
        print("  WARNING: No technical candidates found.")
        return 0

    # 7. Cumulative analysis per side
    results = {}
    for side in ["BUY", "SELL"]:
        side_df = df[df["side"] == side].copy()
        if side_df.empty:
            results[side] = []
            continue
        results[side] = cumulative_economic_analysis(side_df, "raw_prob")

    # 8. Write outputs
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize float values
    def sanitize(obj):
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        if isinstance(obj, dict):
            return {k: sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [sanitize(v) for v in obj]
        return obj

    (output_dir / "c2_economic_ranking.json").write_text(
        json.dumps(sanitize(results), indent=2), encoding="utf-8"
    )

    # 9. Format Markdown Report
    report_lines = [
        "# HMR-V1.3C-C2: Cumulative Economic Ranking Diagnostics",
        "",
        f"**Window**: {args.start[:10]} → {args.end[:10]}",
        f"**Coins**: {args.coins}",
        f"**Forward horizon**: {args.horizon_bars} bars ({args.horizon_bars * 15} min)",
        f"**TP/SL**: {args.tp_pct*100:.2f}% / {args.sl_pct*100:.2f}%",
        f"**Total scored candidates**: {len(df)} (BUY: {len(df[df['side']=='BUY'])}, SELL: {len(df[df['side']=='SELL'])})",
        "",
        "---",
        ""
    ]

    for side in ["BUY", "SELL"]:
        side_results = results.get(side, [])
        report_lines.extend([
            f"## {side} Cumulative Cohorts",
            "",
            "| Cohort | n | Win Rate | Mean Gross Return | Median Gross Return | Gross Expectancy | Mean MFE | Mean MAE | Cutoff Prob |",
            "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
        ])
        for r in side_results:
            report_lines.append(
                f"| {r['bucket']} | {r['n']} | {r['win_rate']*100:.2f}% | "
                f"{r['mean_gross_return']*100:.3f}% | {r['median_gross_return']*100:.3f}% | "
                f"{r['gross_expectancy']*100:.3f}% | {r['mean_mfe']*100:.3f}% | "
                f"{r['mean_mae']*100:.3f}% | {r['cutoff_prob']:.4f} |"
            )
        report_lines.append("\n")

    report_lines.extend([
        "## Core Conclusion",
        "",
        "Use this report to evaluate if the top percentile subsets produce a gross positive return.",
        "- If `mean_gross_return` or `gross_expectancy` in the top buckets (e.g. Top 1% - 10%) is positive, `MODEL_ECONOMIC_EDGE = YES`.",
        "- If all top buckets remain gross negative, `MODEL_ECONOMIC_EDGE = NO`. Threshold search is not recommended."
    ])

    (output_dir / "c2_economic_ranking.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"  Markdown report written to {output_dir / 'c2_economic_ranking.md'}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HMR-V1.3C-C2 Cumulative Economic Ranking")
    parser.add_argument("--start", default="2025-01-01T00:00:00+00:00")
    parser.add_argument("--end", default="2025-03-31T23:45:00+00:00")
    parser.add_argument("--coins", default="BTC,ETH,BNB")
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--data-dir", default="data/fresh_training_data_2023_2026")
    parser.add_argument("--settlement-bars", type=int, default=49)
    parser.add_argument("--warmup-bars", type=int, default=260)
    parser.add_argument("--horizon-bars", type=int, default=48)
    parser.add_argument("--tp-pct", type=float, default=0.01)
    parser.add_argument("--sl-pct", type=float, default=0.01)
    parser.add_argument(
        "--research-artifact-manifest",
        default="research/historical_market_replay_v1/research_artifact_pre2025/manifest.json",
    )
    parser.add_argument(
        "--output-dir",
        default="research/historical_market_replay_v1/v1_3c/c2_ranking",
    )
    args = parser.parse_args()

    sys.exit(run_c2_diagnostics(args))
