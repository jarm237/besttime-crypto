#!/usr/bin/env python3
"""HMR-V1.3D-D5: Out-of-Sample Validation Runner.

Freezes a specific candidate policy threshold (e.g. raw_prob >= 0.21 for SELL)
and runs historical market replay backtests over Jan-Mar (Discovery),
Apr-Jun (Validation), and Jul-Sep (Untouched Test) windows.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd
import joblib

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.backtesting.config import BacktestConfig
from btc_scraper.backtesting.engine import BacktestEngine
from scripts.hmr_v1_baseline import (
    load_closed_candles,
    research_model_override,
    isolated_policy_runtime,
    _replay_world_state,
)
from btc_scraper.ml_engine.feature_extractor import build_meta_features_v2


def run_window_backtest(
    start_str: str,
    end_str: str,
    args,
    cclf: Any,
    feature_names: List[str],
    manifest_path: Path,
    candles: Dict[str, List[Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    """Run backtest over a specific window under the candidate policy contract."""
    from btc_scraper.analysis import analyze_all_market
    from btc_scraper.ml_engine.causal_context_bridge import get_hybrid_provider
    from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine
    from btc_scraper.ml_engine.inference_coordinator import InferenceCoordinator
    from btc_scraper.ml_engine import signal_score as ss_mod
    ss_mod._load_optimized_params = lambda: {"signal_cutoff": 0.0, "kelly_multiplier": 1.0}
    from btc_scraper.ml_engine.signal_score import evaluate_signal_score
    from btc_scraper.trading.auto_trader import AutoTrader

    start = pd.Timestamp(start_str, tz="UTC")
    end = pd.Timestamp(end_str, tz="UTC")
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    timeframe = args.timeframe

    analysis_by_time: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for coin in coins:
        coin_candles = candles.get(coin, [])
        rows = []
        for c in coin_candles:
            c_time = pd.Timestamp(c["time"], tz="UTC")
            if start <= c_time <= (end + pd.Timedelta(timeframe) * args.settlement_bars):
                rows.append(dict(c))
        
        for val in analyze_all_market(rows):
            observed_at = pd.Timestamp(val["time"], tz="UTC")
            if start <= observed_at <= end:
                analysis_by_time.setdefault(val["time"], {})[coin] = val

    generated_signals = []
    rejection_counts = {}
    coordinator = InferenceCoordinator()
    
    # Configure decision engine with candidate thresholds
    decision_engine = MetaDecisionEngine(
        buy_threshold=args.buy_threshold,
        sell_threshold=args.sell_threshold,
        min_ev_pct=args.min_ev_pct,
    )
    provider = get_hybrid_provider(alpha=0.0)
    trader = AutoTrader()
    trader._check_circuit_breaker = lambda: (True, "")
    trader._has_open_position = lambda _c, _d: False

    with research_model_override(str(manifest_path)):
        with isolated_policy_runtime():
            # Force auto trader thresholds and disable lineage evidence database
            os.environ["AUTO_TRADE_META_THRESHOLD"] = str(args.meta_threshold)
            os.environ["AUTO_TRADE_SCORE_THRESHOLD"] = "0"
            os.environ["BTC_EVIDENCE_ELIGIBLE"] = "false"
            os.environ["AUTO_TRADE_MIN_EXPECTED_EDGE"] = "-1.0"
            os.environ["AUTO_TRADE_USE_KELLY"] = "false"
            os.environ["AUTO_TRADE_MIN_RR"] = "0.0"

            for observed_at in sorted(analysis_by_time):
                cycle_id = f"val-{pd.Timestamp(observed_at).strftime('%Y%m%dT%H%M%SZ')}"
                for coin in coins:
                    analysis = analysis_by_time[observed_at].get(coin)
                    if analysis is None:
                        continue
                    analysis = dict(analysis)
                    analysis.update({
                        "coin": coin,
                        "symbol": f"{coin}USDT",
                        "timeframe": timeframe,
                        "cycle_id": cycle_id,
                        "observed_at": observed_at,
                    })

                    tech_action = str(analysis.get("action")).upper()
                    if tech_action not in {"BUY", "SELL"}:
                        continue
                    analysis["signal"] = tech_action

                    # Execute prediction
                    prediction = coordinator.predict_once(
                        analysis,
                        symbol=coin,
                        timeframe=timeframe,
                        decision_context="entry",
                        caller_context="hmr_v1_3d_d5",
                    )

                    # Raw model override if enabled
                    if args.use_raw_model:
                        feat = build_meta_features_v2(analysis)
                        row_feat = [float(feat.get(k, 0.0)) for k in feature_names]
                        raw_prob = float(cclf.calibrated_classifiers_[0].estimator.predict_proba([row_feat])[0, 1])
                        import dataclasses
                        prediction = dataclasses.replace(prediction, probability=raw_prob)

                    prediction_dict = prediction.to_dict()

                    # Scoring
                    score = evaluate_signal_score(analysis, meta_prediction=prediction_dict)
                    analysis["signal_score"] = score
                    decision_input = {**analysis, **score, "_meta_prediction": prediction_dict}

                    final_decision = decision_engine.decide_with_provider(
                        decision_input, provider, _replay_world_state(analysis)
                    )
                    analysis["causal_decision"] = final_decision

                    entry_decision = trader.build_entry_decision(analysis, coin)
                    final_action = entry_decision.action.value if entry_decision.eligible else "HOLD"

                    if not entry_decision.eligible:
                        reason = entry_decision.rejection_reason.value if entry_decision.rejection_reason else "UNKNOWN"
                        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
                        if reason == "action_disagreement":
                            print(f"      DEBUG: coin={coin}, tech_action={tech_action}, signal={analysis.get('signal')}, sig_score_action={score.get('action')}, entry_decision_action={entry_decision.action}")

                    if entry_decision.eligible:
                        signal = {
                            **analysis,
                            "entry_time": observed_at,
                            "signal_raw": final_action,
                            "policy_final_action": final_action,
                        }
                        generated_signals.append(signal)

            print(f"    Rejection counts for epoch: {rejection_counts}")

    config = BacktestConfig.from_dict({
        "coins": coins,
        "timeframe": timeframe,
        "initial_capital": 10000.0,
        "same_candle_policy": "CONSERVATIVE_SL_FIRST",
    })
    backtest_result = BacktestEngine(config).run(candles, generated_signals)
    return generated_signals, backtest_result.metrics, backtest_result.trades


def main():
    parser = argparse.ArgumentParser(description="HMR-V1.3D Out-of-Sample Validation Sweep")
    parser.add_argument("--coins", default="BTC,ETH,BNB")
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--data-dir", default="data/fresh_training_data_2023_2026")
    parser.add_argument("--settlement-bars", type=int, default=49)
    parser.add_argument("--warmup-bars", type=int, default=260)
    
    # Candidate policy parameters (Top 5% SELL = score >= 0.21, disable BUY via 0.50 threshold)
    parser.add_argument("--buy-threshold", type=float, default=0.50)
    parser.add_argument("--sell-threshold", type=float, default=0.21)
    parser.add_argument("--meta-threshold", type=float, default=0.21)
    parser.add_argument("--min-ev-pct", type=float, default=0.0005)
    parser.add_argument("--use-raw-model", type=bool, default=True)

    parser.add_argument(
        "--research-artifact-manifest",
        default="research/historical_market_replay_v1/research_artifact_pre2025/manifest.json",
    )
    parser.add_argument(
        "--output-dir",
        default="research/historical_market_replay_v1/v1_3d/validation",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load model
    manifest_path = Path(args.research_artifact_manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle_path = REPO_ROOT / manifest["paths"]["bundle"]
    bundle = joblib.load(bundle_path)
    cclf = bundle["model"]
    feature_names = bundle["features"]

    # 2. Define windows
    windows = [
        {"name": "DISCOVERY", "start": "2025-01-01T00:00:00+00:00", "end": "2025-03-31T23:45:00+00:00"},
        {"name": "VALIDATION", "start": "2025-04-01T00:00:00+00:00", "end": "2025-06-30T23:45:00+00:00"},
        {"name": "UNTOUCHED_TEST", "start": "2025-07-01T00:00:00+00:00", "end": "2025-09-30T23:45:00+00:00"},
    ]

    # Load candles covering all windows
    global_start = pd.Timestamp(windows[0]["start"], tz="UTC")
    global_end = pd.Timestamp(windows[-1]["end"], tz="UTC")
    settlement_end = global_end + pd.Timedelta(args.timeframe) * args.settlement_bars

    print("Loading candles...")
    candles = load_closed_candles(
        Path(args.data_dir), [c.strip() for c in args.coins.split(",")], args.timeframe,
        global_start, global_end, settlement_end, warmup_bars=args.warmup_bars
    )

    for coin_rows in candles.values():
        for row in coin_rows:
            row["time"] = pd.Timestamp(row["time"]).strftime("%Y-%m-%d %H:%M:%S")

    results = {}
    for win in windows:
        print(f"\nRunning epoch: {win['name']} ({win['start'][:10]} → {win['end'][:10]})...")
        signals, metrics, trades = run_window_backtest(
            win["start"], win["end"], args, cclf, feature_names, manifest_path, candles
        )

        results[win["name"]] = {
            "metrics": metrics,
            "trades_count": len(trades),
            "buy_count": sum(1 for t in trades if t["type"] == "LONG"),
            "sell_count": sum(1 for t in trades if t["type"] == "SHORT"),
        }

        # Save details
        win_dir = output_dir / win["name"].lower()
        win_dir.mkdir(parents=True, exist_ok=True)
        (win_dir / "trades.json").write_text(json.dumps(trades, indent=2), encoding="utf-8")
        (win_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    # Generate Markdown Report
    report = [
        "# HMR-V1.3D-D5: Out-of-Sample Validation Report",
        "",
        "**Candidate Policy Configuration**:",
        f"- Gating: raw model probabilities (use_raw_model={args.use_raw_model})",
        f"- Gating Thresholds: BUY >= {args.buy_threshold:.2f}, SELL >= {args.sell_threshold:.2f}",
        f"- Meta Gating: meta_threshold >= {args.meta_threshold:.2f}, min_ev_pct >= {args.min_ev_pct:.3f}",
        "",
        "## Performance Across Epochs",
        "",
        "| Window | Dates | Trades | BUY | SELL | Gross PnL ($) | Net PnL ($) | Win Rate | Profit Factor | MaxDD |",
        "| :--- | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    ]

    for win in windows:
        res = results[win["name"]]
        m = res["metrics"]
        
        if res["trades_count"] > 0:
            gross = f"{m.get('realized_gross_pnl', 0.0):,.2f}"
            net = f"{m.get('realized_net_pnl', 0.0):,.2f}"
            wr = f"{m.get('win_rate', 0.0)*100:.1f}%"
            pf = f"{m.get('profit_factor', 0.0):.3f}"
            dd = f"{m.get('max_drawdown', 0.0)*100:.1f}%"
        else:
            gross = "—"
            net = "—"
            wr = "—"
            pf = "—"
            dd = "—"

        report.append(
            f"| {win['name']} | {win['start'][:10]} → {win['end'][:10]} | "
            f"{res['trades_count']} | {res['buy_count']} | {res['sell_count']} | "
            f"{gross} | {net} | {wr} | {pf} | {dd} |"
        )

    report.extend([
        "",
        "## Core Conclusion",
        "- **Validation Check**: Check if validation and untouched test windows yield positive net expectancy.",
        "- If performance degrades to significant loss out-of-sample, the frozen candidate is not robust."
    ])

    (output_dir / "validation_results.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    (output_dir / "validation_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n  Validation report written to {output_dir / 'validation_results.md'}")


if __name__ == "__main__":
    main()
