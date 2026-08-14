#!/usr/bin/env python3
"""HMR-V1.3B: Diagnostic Ablation Study.

Runs the historical market replay over the Jan-Mar 2025 window under various
ablation scenarios:
  1. CURRENT_CLEAN (Control): correct semantics, existing calibration/thresholds/meta.
  2. TECHNICAL_ONLY: bypass model/calib/posterior/meta; execute all technical signals directly.
  3. NO_CALIBRATION: bypass calibration (use raw ensemble probability directly) with existing thresholds.
  4. NO_META: bypass meta thresholds (meta_prob/strength) but keep posterior and model.
  5. TECHNICAL_LONG_ONLY: Long technical signals only.
  6. TECHNICAL_SHORT_ONLY: Short technical signals only.
  7. NO_CALIB_LONG_ONLY: Long signals only under NO_CALIBRATION.
  8. NO_CALIB_SHORT_ONLY: Short signals only under NO_CALIBRATION.

Also performs Exit Diagnostics (B7) on the resulting trade cohorts.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import joblib

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.backtesting.config import BacktestConfig
from btc_scraper.backtesting.engine import BacktestEngine
from scripts.generate_triple_barrier_labels import load_candles_for_coin
from scripts.hmr_v1_baseline import (
    load_closed_candles,
    research_model_override,
    isolated_policy_runtime,
    _replay_world_state,
)
from scripts.hmr_v1_3a_decomposition import calculate_mfe_mae


def run_ablation_scenario(
    scenario_name: str,
    candles: Dict[str, List[Dict[str, Any]]],
    coins: List[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    timeframe: str,
    cclf: Any,
    feature_names: List[str],
    research_manifest_path: Path,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    """Runs a single ablation scenario and return the executed signals and trades."""
    from btc_scraper.analysis import analyze_all_market
    from btc_scraper.ml_engine.causal_context_bridge import get_hybrid_provider
    from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine
    from btc_scraper.ml_engine.inference_coordinator import InferenceCoordinator
    from btc_scraper.ml_engine.signal_score import evaluate_signal_score
    from btc_scraper.trading.auto_trader import AutoTrader

    analysis_by_time: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for coin in coins:
        rows = [dict(c) for c in candles.get(coin, [])]
        for val in analyze_all_market(rows):
            observed_at = pd.Timestamp(val["time"], tz="UTC")
            if start <= observed_at <= end:
                analysis_by_time.setdefault(val["time"], {})[coin] = val

    generated_signals = []
    coordinator = InferenceCoordinator()
    decision_engine = MetaDecisionEngine()
    provider = get_hybrid_provider(alpha=0.0)
    trader = AutoTrader()
    trader._check_circuit_breaker = lambda: (True, "")
    trader._has_open_position = lambda _c, _d: False

    # Adjust parameters based on scenario
    orig_meta_env = os.environ.get("AUTO_TRADE_META_THRESHOLD")
    orig_score_env = os.environ.get("AUTO_TRADE_SCORE_THRESHOLD")
    if scenario_name == "NO_META":
        os.environ["AUTO_TRADE_META_THRESHOLD"] = "0.0"
        os.environ["AUTO_TRADE_SCORE_THRESHOLD"] = "0"

    with research_model_override(str(research_manifest_path)):
        with isolated_policy_runtime():
            for observed_at in sorted(analysis_by_time):
                cycle_id = f"hmr-{pd.Timestamp(observed_at).strftime('%Y%m%dT%H%M%SZ')}"
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
                    is_tech_buy = tech_action == "BUY"
                    is_tech_sell = tech_action == "SELL"

                    if not (is_tech_buy or is_tech_sell):
                        continue

                    # Side filters
                    if "LONG_ONLY" in scenario_name and not is_tech_buy:
                        continue
                    if "SHORT_ONLY" in scenario_name and not is_tech_sell:
                        continue

                    # Scenario B2: TECHNICAL_ONLY
                    if scenario_name in {"TECHNICAL_ONLY", "TECHNICAL_LONG_ONLY", "TECHNICAL_SHORT_ONLY"}:
                        signal = {
                            **analysis,
                            "entry_time": observed_at,
                            "signal_raw": tech_action,
                            "policy_final_action": tech_action,
                        }
                        generated_signals.append(signal)
                        continue

                    # Run inference coordinator
                    prediction = coordinator.predict_once(
                        analysis,
                        symbol=coin,
                        timeframe=timeframe,
                        decision_context="entry",
                        caller_context="hmr_v1_3b_ablations",
                    )

                    # Override probability if using raw model
                    if "NO_CALIBRATION" in scenario_name:
                        feat = build_meta_features_v2(analysis)
                        row_feat = [float(feat.get(k, 0.0)) for k in feature_names]
                        raw_prob = float(cclf.calibrated_classifiers_[0].estimator.predict_proba([row_feat])[0, 1])
                        import dataclasses
                        prediction = dataclasses.replace(prediction, probability=raw_prob)

                    prediction_dict = prediction.to_dict()

                    # Core pipeline scoring & decisions
                    score = evaluate_signal_score(analysis, meta_prediction=prediction_dict)
                    analysis["signal_score"] = score
                    decision_input = {**analysis, **score, "_meta_prediction": prediction_dict}

                    final_decision = decision_engine.decide_with_provider(
                        decision_input, provider, _replay_world_state(analysis)
                    )
                    analysis["causal_decision"] = final_decision

                    entry_decision = trader.build_entry_decision(analysis, coin)
                    final_action = entry_decision.action.value if entry_decision.eligible else "HOLD"

                    if entry_decision.eligible:
                        signal = {
                            **analysis,
                            "entry_time": observed_at,
                            "signal_raw": final_action,
                            "policy_final_action": final_action,
                        }
                        generated_signals.append(signal)

    # Run BacktestEngine
    config = BacktestConfig.from_dict({
        "coins": coins,
        "timeframe": timeframe,
        "initial_capital": 10000.0,
        "same_candle_policy": "CONSERVATIVE_SL_FIRST",
    })
    # Restore env vars
    if orig_meta_env is not None:
        os.environ["AUTO_TRADE_META_THRESHOLD"] = orig_meta_env
    elif "AUTO_TRADE_META_THRESHOLD" in os.environ:
        del os.environ["AUTO_TRADE_META_THRESHOLD"]

    if orig_score_env is not None:
        os.environ["AUTO_TRADE_SCORE_THRESHOLD"] = orig_score_env
    elif "AUTO_TRADE_SCORE_THRESHOLD" in os.environ:
        del os.environ["AUTO_TRADE_SCORE_THRESHOLD"]

    backtest_result = BacktestEngine(config).run(candles, generated_signals)
    return generated_signals, backtest_result.metrics, backtest_result.trades


def run_exit_decomposition(trades: List[Dict[str, Any]], candles: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Decomposes trade execution quality (MFE/MAE analysis)."""
    if not trades:
        return {
            "counts": {"BAD_ENTRY": 0, "EDGE_NOT_CAPTURED": 0, "GOOD_CAPTURE": 0, "COST_DESTROYED": 0},
            "averages": {"MFE": 0.0, "MAE": 0.0, "mfe_realized_capture_ratio": 0.0}
        }

    records = []
    for t in trades:
        mfe, mae, _, _ = calculate_mfe_mae(t, candles)
        gross_pnl = float(t["gross_pnl"])
        net_pnl = float(t["pnl"])
        
        # Classification
        if gross_pnl <= 0.0:
            classification = "BAD_ENTRY"
        elif net_pnl <= 0.0:
            classification = "COST_DESTROYED"
        elif mfe > 0.0 and (gross_pnl / mfe) < 0.20:
            classification = "EDGE_NOT_CAPTURED"
        else:
            classification = "GOOD_CAPTURE"

        records.append({
            "MFE": mfe,
            "MAE": mae,
            "mfe_realized_capture_ratio": gross_pnl / mfe if mfe > 0 else 0.0,
            "classification": classification
        })

    df = pd.DataFrame(records)
    counts = df["classification"].value_counts().to_dict()
    for cat in ("BAD_ENTRY", "EDGE_NOT_CAPTURED", "GOOD_CAPTURE", "COST_DESTROYED"):
        counts.setdefault(cat, 0)

    return {
        "counts": counts,
        "averages": {
            "MFE": float(df["MFE"].mean()),
            "MAE": float(df["MAE"].mean()),
            "mfe_realized_capture_ratio": float(df[df["MFE"] > 0]["mfe_realized_capture_ratio"].mean()) if len(df[df["MFE"] > 0]) > 0 else 0.0,
        }
    }


def main():
    parser = argparse.ArgumentParser(description="Run HMR-V1.3B Ablations.")
    parser.add_argument("--start", default="2025-01-01T00:00:00+00:00")
    parser.add_argument("--end", default="2025-03-31T23:45:00+00:00")
    parser.add_argument("--coins", default="BTC,ETH,BNB")
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--data-dir", default="data/fresh_training_data_2023_2026")
    parser.add_argument("--settlement-bars", type=int, default=49)
    parser.add_argument("--warmup-bars", type=int, default=260)
    parser.add_argument("--research-artifact-manifest", default="research/historical_market_replay_v1/research_artifact_pre2025/manifest.json")
    parser.add_argument("--output-dir", default="research/historical_market_replay_v1/v1_3b")
    args = parser.parse_args()

    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    settlement_end = end + pd.Timedelta(args.timeframe) * args.settlement_bars

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

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

    # 3. Import build_meta_features_v2
    global build_meta_features_v2
    from btc_scraper.ml_engine.feature_extractor import build_meta_features_v2

    # Scenarios list
    scenarios = [
        "CURRENT_CLEAN",
        "TECHNICAL_ONLY",
        "NO_CALIBRATION",
        "NO_META",
        "TECHNICAL_LONG_ONLY",
        "TECHNICAL_SHORT_ONLY",
        "NO_CALIB_LONG_ONLY",
        "NO_CALIB_SHORT_ONLY"
    ]

    results = {}
    for sc in scenarios:
        print(f"Running scenario: {sc}...")
        signals, metrics, trades = run_ablation_scenario(
            scenario_name=sc,
            candles=candles,
            coins=coins,
            start=start,
            end=end,
            timeframe=args.timeframe,
            cclf=cclf,
            feature_names=feature_names,
            research_manifest_path=manifest_path
        )
        
        # Exit analysis
        exits = run_exit_decomposition(trades, candles)

        results[sc] = {
            "metrics": metrics,
            "exits": exits,
            "trades_count": len(trades),
            "buy_count": sum(1 for t in trades if t["type"] == "LONG"),
            "sell_count": sum(1 for t in trades if t["type"] == "SHORT"),
        }
        
        # Save detailed trades JSON
        scenario_output_dir = output_dir / sc.lower()
        scenario_output_dir.mkdir(parents=True, exist_ok=True)
        (scenario_output_dir / "trades.json").write_text(json.dumps(trades, indent=2), encoding="utf-8")
        (scenario_output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        (scenario_output_dir / "exit_decomposition.json").write_text(json.dumps(exits, indent=2), encoding="utf-8")

    # Generate markdown table
    md_lines = [
        "# HMR-V1.3B: Diagnostic Ablation Results Matrix",
        "",
        "| Scenario | Trades | BUY | SELL | Gross PnL ($) | Net PnL ($) | Win Rate | Profit Factor | MaxDD |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    ]

    for sc in scenarios:
        res = results[sc]
        m = res["metrics"]
        trades_count = res["trades_count"]
        buy_count = res["buy_count"]
        sell_count = res["sell_count"]
        
        if trades_count > 0:
            gross_pnl = f"{m.get('realized_gross_pnl', 0.0):,.2f}"
            net_pnl = f"{m.get('realized_net_pnl', 0.0):,.2f}"
            win_rate = f"{m.get('win_rate', 0.0)*100:.2f}%"
            profit_factor = f"{m.get('profit_factor', 0.0):.3f}"
            max_dd = f"{m.get('max_drawdown', 0.0)*100:.2f}%"
        else:
            gross_pnl = "—"
            net_pnl = "—"
            win_rate = "—"
            profit_factor = "—"
            max_dd = "—"

        md_lines.append(
            f"| {sc} | {trades_count} | {buy_count} | {sell_count} | {gross_pnl} | {net_pnl} | {win_rate} | {profit_factor} | {max_dd} |"
        )

    md_lines.append("\n## Exit Decomposition Metrics")
    md_lines.append("")
    md_lines.append("| Scenario | BAD_ENTRY | COST_DESTROYED | EDGE_NOT_CAPTURED | GOOD_CAPTURE | Mean MFE | Mean MAE | Capture Ratio |")
    md_lines.append("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")

    for sc in scenarios:
        res = results[sc]
        ex = res["exits"]
        c = ex["counts"]
        avg = ex["averages"]
        
        if res["trades_count"] > 0:
            bad_entry = c["BAD_ENTRY"]
            cost_destroyed = c["COST_DESTROYED"]
            edge_not_captured = c["EDGE_NOT_CAPTURED"]
            good_capture = c["GOOD_CAPTURE"]
            mean_mfe = f"{avg['MFE']*100:.2f}%"
            mean_mae = f"{avg['MAE']*100:.2f}%"
            cap_ratio = f"{avg['mfe_realized_capture_ratio']*100:.2f}%"
        else:
            bad_entry = "—"
            cost_destroyed = "—"
            edge_not_captured = "—"
            good_capture = "—"
            mean_mfe = "—"
            mean_mae = "—"
            cap_ratio = "—"

        md_lines.append(
            f"| {sc} | {bad_entry} | {cost_destroyed} | {edge_not_captured} | {good_capture} | {mean_mfe} | {mean_mae} | {cap_ratio} |"
        )

    # Save summary report
    (output_dir / "ablation_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (output_dir / "ablation_results.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    
    print(f"\nAblation results written to {output_dir}")
    print("Ablation study completed successfully.")


if __name__ == "__main__":
    main()
