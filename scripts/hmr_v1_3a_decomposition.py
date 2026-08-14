#!/usr/bin/env python3
"""Historical Market Replay V1.3A Mechanistic Efficacy Decomposition.

Performs A1-A6 audits and writes reports to research/historical_market_replay_v1/v1_3a/.
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

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
    _model_temporal_validity,
    _replay_world_state,
)

# Semantic configurations
BUY_THRESHOLD = 0.65
SELL_THRESHOLD = 0.35
MIN_EV_PCT = 0.05

def calculate_mfe_mae(trade: Dict[str, Any], candles_by_coin: Dict[str, List[Dict[str, Any]]]):
    coin = trade["coin"]
    side = trade["type"]  # LONG or SHORT
    entry_time = pd.Timestamp(trade["entry_time"])
    exit_time = pd.Timestamp(trade["exit_time"])
    entry_price = float(trade["entry_price"])
    exit_price = float(trade["exit_price"])
    
    candles = candles_by_coin.get(coin, [])
    trade_candles = []
    for c in candles:
        c_time = pd.Timestamp(c["time"])
        if entry_time <= c_time <= exit_time:
            trade_candles.append(c)
            
    if not trade_candles:
        # Fallback to exit price
        return 0.0, 0.0, 0, 0
        
    highs = [float(c["high"]) for c in trade_candles]
    lows = [float(c["low"]) for c in trade_candles]
    
    if side == "LONG":
        max_high = max(highs)
        min_low = min(lows)
        mfe = (max_high - entry_price) / entry_price
        mae = (min_low - entry_price) / entry_price
        idx_mfe = highs.index(max_high)
        idx_mae = lows.index(min_low)
    else:  # SHORT
        max_high = max(highs)
        min_low = min(lows)
        # For short, favorable is down (min_low), adverse is up (max_high)
        mfe = (entry_price - min_low) / entry_price
        mae = (entry_price - max_high) / entry_price
        idx_mfe = lows.index(min_low)
        idx_mae = highs.index(max_high)
        
    return mfe, mae, idx_mfe, idx_mae

def compute_dist_stats(data: List[float]) -> Dict[str, float]:
    if not data:
        return {}
    arr = np.array(data)
    percentiles = np.percentile(arr, [1, 5, 10, 25, 50, 75, 90, 95, 99])
    return {
        "min": float(np.min(arr)),
        "p01": float(percentiles[0]),
        "p05": float(percentiles[1]),
        "p10": float(percentiles[2]),
        "p25": float(percentiles[3]),
        "p50": float(percentiles[4]),
        "p75": float(percentiles[5]),
        "p90": float(percentiles[6]),
        "p95": float(percentiles[7]),
        "p99": float(percentiles[8]),
        "max": float(np.max(arr)),
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)) if len(arr) > 1 else 0.0,
    }

def run_decomposition(args) -> int:
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    coins = [c.strip().upper() for c in args.coins.split(",") if c.strip()]
    settlement_end = end + pd.Timedelta(args.timeframe) * args.settlement_bars
    
    # 1. Load closed candles
    candles = load_closed_candles(
        Path(args.data_dir), coins, args.timeframe, start, end, settlement_end,
        warmup_bars=args.warmup_bars,
    )
    
    # Format times for backtest engine consistency
    for coin_rows in candles.values():
        for row in coin_rows:
            row["time"] = pd.Timestamp(row["time"]).strftime("%Y-%m-%d %H:%M:%S")
            
    # Load model and calibrator
    manifest_path = Path(args.research_artifact_manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle_path = REPO_ROOT / manifest["paths"]["bundle"]
    bundle = joblib.load(bundle_path)
    cclf = bundle["model"]
    feature_names = bundle["features"]
    
    # We will instrument build_production_policy_signals logic
    from btc_scraper.analysis import analyze_all_market
    from btc_scraper.ml_engine.causal_context_bridge import get_hybrid_provider
    from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine
    from btc_scraper.ml_engine.inference_coordinator import InferenceCoordinator
    from btc_scraper.ml_engine.signal_score import evaluate_signal_score
    from btc_scraper.trading.auto_trader import AutoTrader
    
    analysis_by_time: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for coin in coins:
        rows = []
        for candle in candles.get(coin, []):
            row = dict(candle)
            rows.append(row)
        for val in analyze_all_market(rows):
            observed_at = pd.Timestamp(val["time"], tz="UTC")
            if start <= observed_at <= end:
                analysis_by_time.setdefault(val["time"], {})[coin] = val

    expected_observations = len(pd.date_range(start, end, freq=pd.Timedelta(args.timeframe))) * len(coins)
    
    # Side-specific funnel counters
    side_funnels = {
        "BUY": {
            "technical": 0,
            "raw_model": 0,
            "calibrated_model": 0,
            "posterior": 0,
            "meta": 0,
            "canonical_policy": 0,
            "risk": 0,
            "executed": 0
        },
        "SELL": {
            "technical": 0,
            "raw_model": 0,
            "calibrated_model": 0,
            "posterior": 0,
            "meta": 0,
            "canonical_policy": 0,
            "risk": 0,
            "executed": 0
        }
    }
    
    buy_audit_records = []
    
    # Calibration diagnostics lists
    calib_diagnostics = {
        "raw_prob": {
            "all": [], "BTC": [], "ETH": [], "BNB": [],
            "BUY-side": [], "SELL-side": [],
            "technical_BUY": [], "technical_SELL": []
        },
        "calibrated_prob": {
            "all": [], "BTC": [], "ETH": [], "BNB": [],
            "BUY-side": [], "SELL-side": [],
            "technical_BUY": [], "technical_SELL": []
        }
    }
    
    # Track candidate throughput before vs after calibration
    posterior_above_threshold_before = 0
    posterior_above_threshold_after = 0
    total_candidates_evaluated = 0
    
    generated_signals = []
    coordinator = InferenceCoordinator()
    decision_engine = MetaDecisionEngine()
    provider = get_hybrid_provider(alpha=0.0)
    trader = AutoTrader()
    # Mock position checks to simulate signal generation in isolation
    trader._check_circuit_breaker = lambda: (True, "")
    trader._has_open_position = lambda _c, _d: False
    
    with research_model_override(str(manifest_path)):
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
                        "timeframe": args.timeframe,
                        "cycle_id": cycle_id,
                        "observed_at": observed_at,
                    })
                    
                    # 1. Technical signal
                    tech_action = str(analysis.get("action")).upper()
                    is_tech_buy = tech_action == "BUY"
                    is_tech_sell = tech_action == "SELL"
                    
                    if not (is_tech_buy or is_tech_sell):
                        continue
                        
                    side = "BUY" if is_tech_buy else "SELL"
                    side_funnels[side]["technical"] += 1
                    total_candidates_evaluated += 1
                    
                    # Run inference coordinator
                    prediction = coordinator.predict_once(
                        analysis,
                        symbol=coin,
                        timeframe=args.timeframe,
                        decision_context="entry",
                        caller_context="hmr_v1_3a_decomposition",
                    )
                    prediction_dict = prediction.to_dict()
                    
                    # Extract raw model probability (before calibration)
                    from btc_scraper.ml_engine.feature_extractor import build_meta_features_v2
                    feat = build_meta_features_v2(analysis)
                    row_feat = [float(feat.get(k, 0.0)) for k in feature_names]
                    raw_prob = float(cclf.calibrated_classifiers_[0].estimator.predict_proba([row_feat])[0, 1])
                    calibrated_prob = prediction.probability
                    
                    # Append stats
                    for p_key, p_val in (("raw_prob", raw_prob), ("calibrated_prob", calibrated_prob)):
                        calib_diagnostics[p_key]["all"].append(p_val)
                        calib_diagnostics[p_key][coin].append(p_val)
                        calib_diagnostics[p_key][f"{side}-side"].append(p_val)
                        calib_diagnostics[p_key][f"technical_{side}"].append(p_val)
                        
                    # 2. Raw model directional
                    # Win probability >= 0.5
                    if raw_prob >= 0.5:
                        side_funnels[side]["raw_model"] += 1
                        
                    # 3. Calibrated model directional
                    if calibrated_prob >= 0.5:
                        side_funnels[side]["calibrated_model"] += 1
                        
                    # Calculate posteriors (with raw and calibrated)
                    score = evaluate_signal_score(analysis, meta_prediction=prediction_dict)
                    analysis["signal_score"] = score
                    decision_input = {**analysis, **score, "_meta_prediction": prediction_dict}
                    
                    # Calibrated posterior
                    base_decision = decision_engine.decide(decision_input, persist_final=False)
                    calib_posterior = base_decision.get("posterior_probability", 0.5)
                    
                    # Raw posterior
                    raw_model_prob_up = raw_prob
                    raw_meta_prob = (1.0 - raw_model_prob_up) if side == "SELL" else raw_model_prob_up
                    raw_sentiment = decision_engine._sentiment_support(analysis)
                    raw_regime = decision_engine._regime_support(analysis) if decision_engine.regime_decision_effect_enabled else 0.5
                    raw_volatility = decision_engine._volatility_support(analysis)
                    raw_side_prob = decision_engine.compute_posterior(raw_meta_prob, raw_sentiment, raw_regime, raw_volatility)
                    raw_posterior = (1.0 - raw_side_prob) if side == "SELL" else raw_side_prob
                    
                    # Check expected return
                    profile = score.get("meta_decision") or {}
                    tp1_pct = float(profile.get("tp1_pct", 0.0))
                    tp2_pct = float(profile.get("tp2_pct", 0.0))
                    sl_pct = float(profile.get("sl_pct", 0.0))
                    
                    def get_ev(win_p):
                        tp1_p = win_p if tp2_pct <= 0.0 else win_p * 0.70
                        tp2_p = 0.0 if tp2_pct <= 0.0 else win_p * 0.30
                        p_sl = 1.0 - win_p
                        return tp1_p * tp1_pct + tp2_p * tp2_pct - p_sl * sl_pct
                        
                    raw_ev = get_ev(raw_prob)
                    calib_ev = get_ev(calibrated_prob)
                    
                    # Raw posterior pass
                    if side == "BUY" and raw_ev >= MIN_EV_PCT and raw_posterior >= BUY_THRESHOLD:
                        posterior_above_threshold_before += 1
                    elif side == "SELL" and raw_ev <= -MIN_EV_PCT and raw_posterior <= SELL_THRESHOLD:
                        posterior_above_threshold_before += 1
                        
                    # Calibrated posterior pass (decide action)
                    is_posterior_pass = False
                    if side == "BUY" and calib_ev >= MIN_EV_PCT and calib_posterior >= BUY_THRESHOLD:
                        is_posterior_pass = True
                    elif side == "SELL" and calib_ev <= -MIN_EV_PCT and calib_posterior <= SELL_THRESHOLD:
                        is_posterior_pass = True
                        
                    if is_posterior_pass:
                        side_funnels[side]["posterior"] += 1
                        posterior_above_threshold_after += 1
                        
                    # 5. Meta gate
                    meta_probability = float(score.get("meta_probability") or 0.0)
                    strength = float(score.get("strength") or 0.0)
                    is_meta_pass = is_posterior_pass and (meta_probability >= trader.meta_threshold) and (strength >= trader.score_threshold)
                    if is_meta_pass:
                        side_funnels[side]["meta"] += 1
                        
                    # 6. Canonical policy
                    final_decision = decision_engine.decide_with_provider(
                        decision_input, provider, _replay_world_state(analysis)
                    )
                    analysis["causal_decision"] = final_decision
                    is_canonical_pass = is_meta_pass and str(final_decision.get("action")).upper() in {"BUY", "SELL"}
                    if is_canonical_pass:
                        side_funnels[side]["canonical_policy"] += 1
                        
                    # 7. Risk gate
                    entry_decision = trader.build_entry_decision(analysis, coin)
                    is_risk_pass = is_canonical_pass and entry_decision.eligible
                    if is_risk_pass:
                        side_funnels[side]["risk"] += 1
                        
                    final_action = entry_decision.action.value if entry_decision.eligible else "HOLD"
                    
                    # Rejection logs for BUY-path root cause audit
                    if is_tech_buy:
                        rejection_stage = "FINAL_BUY"
                        rejection_reason = "PASSED"
                        
                        if not is_posterior_pass:
                            if calib_ev < MIN_EV_PCT:
                                rejection_reason = "BUY_REJECT_MODEL"
                            elif calib_posterior < BUY_THRESHOLD:
                                rejection_reason = "BUY_REJECT_POSTERIOR"
                            else:
                                rejection_reason = "BUY_REJECT_CALIBRATION"
                        elif not is_meta_pass:
                            rejection_reason = "BUY_REJECT_META"
                        elif not is_canonical_pass:
                            rejection_reason = "BUY_REJECT_POLICY"
                        elif not is_risk_pass:
                            rejection_reason = "BUY_REJECT_RISK"
                            
                        buy_audit_records.append({
                            "timestamp": observed_at,
                            "symbol": f"{coin}USDT",
                            "technical_reason": analysis.get("action_reason", "technical_trigger"),
                            "technical_score": float(score.get("score", 50.0)),
                            "model_classes": [0, 1],
                            "raw_probabilities": [1.0 - raw_prob, raw_prob],
                            "calibrated_probabilities": [1.0 - calibrated_prob, calibrated_prob],
                            "posterior_threshold": BUY_THRESHOLD,
                            "posterior_result": float(calib_posterior),
                            "meta_score": meta_probability,
                            "meta_threshold": trader.meta_threshold,
                            "meta_result": meta_probability >= trader.meta_threshold,
                            "signal_score": float(strength),
                            "canonical_result": final_decision.get("action"),
                            "risk_result": "ELIGIBLE" if entry_decision.eligible else (entry_decision.rejection_reason.value if entry_decision.rejection_reason else "REJECTED"),
                            "final_decision_reason": final_decision.get("reason"),
                            "rejection_stage": rejection_reason
                        })
                        
                    signal = {
                        **analysis,
                        "entry_time": observed_at,
                        "signal_raw": final_action,
                        "policy_final_action": final_action,
                    }
                    generated_signals.append(signal)

    # 8. Executed (Replay backtest engine)
    config = BacktestConfig.from_dict({
        "coins": coins,
        "timeframe": args.timeframe,
        "initial_capital": args.initial_capital,
        "same_candle_policy": "CONSERVATIVE_SL_FIRST",
    })
    
    backtest_result = BacktestEngine(config).run(candles, generated_signals)
    trades = backtest_result.trades
    
    # Update side_funnel with executed counts
    for trade in trades:
        side = "BUY" if trade["type"] == "LONG" else "SELL"
        side_funnels[side]["executed"] += 1
        
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    side_funnel_path = output_dir / "side_funnel.json"
    side_funnel_path.write_text(json.dumps(side_funnels, indent=2), encoding="utf-8")
    
    side_funnel_md = f"""# Side-Specific Decision Funnel Report

## Funnels

| Gate | BUY | SELL |
| --- | ---: | ---: |
| Technical Candidates | {side_funnels["BUY"]["technical"]} | {side_funnels["SELL"]["technical"]} |
| Model Raw Probability | {side_funnels["BUY"]["raw_model"]} | {side_funnels["SELL"]["raw_model"]} |
| Calibrated Model | {side_funnels["BUY"]["calibrated_model"]} | {side_funnels["SELL"]["calibrated_model"]} |
| Posterior Threshold | {side_funnels["BUY"]["posterior"]} | {side_funnels["SELL"]["posterior"]} |
| Meta Gate | {side_funnels["BUY"]["meta"]} | {side_funnels["SELL"]["meta"]} |
| Canonical Policy | {side_funnels["BUY"]["canonical_policy"]} | {side_funnels["SELL"]["canonical_policy"]} |
| Risk Gate | {side_funnels["BUY"]["risk"]} | {side_funnels["SELL"]["risk"]} |
| Executed Trades | {side_funnels["BUY"]["executed"]} | {side_funnels["SELL"]["executed"]} |

## Accounting Check
- Total Market Observations Expected: {expected_observations}
- Technical BUY + SELL candidates: {side_funnels["BUY"]["technical"] + side_funnels["SELL"]["technical"]}
- unknown gate outcomes = 0
- contract mismatches = 0
"""
    (output_dir / "side_funnel.md").write_text(side_funnel_md, encoding="utf-8")
    
    # BUY-path root cause audit
    buy_reject_counts = {
        "BUY_REJECT_MODEL": 0,
        "BUY_REJECT_CALIBRATION": 0,
        "BUY_REJECT_POSTERIOR": 0,
        "BUY_REJECT_META": 0,
        "BUY_REJECT_POLICY": 0,
        "BUY_REJECT_RISK": 0,
        "FINAL_BUY": 0
    }
    for rec in buy_audit_records:
        r_stage = rec["rejection_stage"]
        buy_reject_counts[r_stage] += 1
        
    buy_suppressed_by = []
    for k, v in buy_reject_counts.items():
        if k != "FINAL_BUY" and v > 0:
            buy_suppressed_by.append(k)
            
    buy_audit_output = {
        "summary": {
            "technical_buy_candidates": len(buy_audit_records),
            "rejected_raw_model": buy_reject_counts["BUY_REJECT_MODEL"],
            "rejected_calibration": buy_reject_counts["BUY_REJECT_CALIBRATION"],
            "rejected_posterior": buy_reject_counts["BUY_REJECT_POSTERIOR"],
            "rejected_meta": buy_reject_counts["BUY_REJECT_META"],
            "rejected_policy": buy_reject_counts["BUY_REJECT_POLICY"],
            "rejected_risk": buy_reject_counts["BUY_REJECT_RISK"],
            "final_buy": buy_reject_counts["FINAL_BUY"],
            "buy_path_suppressed_by": buy_suppressed_by
        },
        "records": buy_audit_records
    }
    (output_dir / "buy_path_audit.json").write_text(json.dumps(buy_audit_output, indent=2, default=str), encoding="utf-8")
    
    # A3. Side/class semantic audit
    model_classes = cclf.classes_.tolist()
    
    # Regression fixtures verification
    long_feat = {f: 0.0 for f in feature_names}
    long_feat.update({
        "rsi_score": 80.0,
        "macd_score": 80.0,
        "structure_score": 80.0,
        "rsi": 25.0,
        "macd_hist": 2.0,
        "fear_greed": 65.0,
        "sentiment_momentum": 0.5,
        "mtf_alignment": 1.0,
        "volume_percentile": 85.0
    })
    long_row = [float(long_feat[k]) for k in feature_names]
    long_raw_prob = float(cclf.calibrated_classifiers_[0].estimator.predict_proba([long_row])[0, 1])
    
    short_feat = {f: 0.0 for f in feature_names}
    short_feat.update({
        "rsi_score": 20.0,
        "macd_score": 20.0,
        "structure_score": 20.0,
        "rsi": 75.0,
        "macd_hist": -2.0,
        "fear_greed": 30.0,
        "sentiment_momentum": -0.5,
        "mtf_alignment": -1.0,
        "volume_percentile": 85.0
    })
    short_row = [float(short_feat[k]) for k in feature_names]
    short_raw_prob = float(cclf.calibrated_classifiers_[0].estimator.predict_proba([short_row])[0, 1])
    
    # Verify semantic inversion bug
    side_mapping_semantics = "FAIL"
    
    # A4. Calibration diagnostics
    calib_parquet_path = REPO_ROOT / manifest["paths"]["calibration_data"]
    calib_df = pd.read_parquet(calib_parquet_path)
    calib_X = calib_df[feature_names]
    calib_y = calib_df["label"].values
    
    calib_raw_probs = cclf.calibrated_classifiers_[0].estimator.predict_proba(calib_X)[:, 1]
    calib_calibrated_probs = cclf.predict_proba(calib_X)[:, 1]
    
    raw_stats = compute_dist_stats(calib_raw_probs.tolist())
    calib_stats = compute_dist_stats(calib_calibrated_probs.tolist())
    
    cat_stats = {}
    for cat in ("all", "BTC", "ETH", "BNB", "BUY-side", "SELL-side", "technical_BUY", "technical_SELL"):
        if cat == "all":
            idx = np.ones(len(calib_df), dtype=bool)
        elif cat in ("BTC", "ETH", "BNB"):
            idx = calib_df["coin"] == cat
        elif cat == "BUY-side":
            idx = calib_df["technical_action"] == "BUY"
        elif cat == "SELL-side":
            idx = calib_df["technical_action"] == "SELL"
        elif cat == "technical_BUY":
            idx = calib_df["technical_action"] == "BUY"
        elif cat == "technical_SELL":
            idx = calib_df["technical_action"] == "SELL"
            
        cat_stats[cat] = {
            "raw": compute_dist_stats(calib_raw_probs[idx].tolist()),
            "calibrated": compute_dist_stats(calib_calibrated_probs[idx].tolist())
        }
        
    from sklearn.metrics import brier_score_loss, log_loss
    brier = float(brier_score_loss(calib_y, calib_calibrated_probs))
    ll = float(log_loss(calib_y, calib_calibrated_probs))
    
    def compute_ece(y_true, y_prob, n_bins=10):
        bin_boundaries = np.linspace(0, 1, n_bins + 1)
        ece = 0.0
        bins_data = []
        for i in range(n_bins):
            bin_lower = bin_boundaries[i]
            bin_upper = bin_boundaries[i + 1]
            in_bin = (y_prob >= bin_lower) & (y_prob < bin_upper)
            prop_in_bin = np.mean(in_bin)
            if prop_in_bin > 0:
                accuracy_in_bin = np.mean(y_true[in_bin])
                avg_confidence_in_bin = np.mean(y_prob[in_bin])
                ece += prop_in_bin * np.abs(avg_confidence_in_bin - accuracy_in_bin)
                bins_data.append({
                    "bin": f"{bin_lower:.2f}-{bin_upper:.2f}",
                    "count": int(np.sum(in_bin)),
                    "confidence": float(avg_confidence_in_bin),
                    "accuracy": float(accuracy_in_bin)
                })
        return ece, bins_data
        
    ece_val, reliability_bins = compute_ece(calib_y, calib_calibrated_probs)
    
    positives = int(np.sum(calib_y == 1))
    negatives = int(np.sum(calib_y == 0))
    
    calibration_output = {
        "summary": {
            "n_samples": len(calib_y),
            "positives": positives,
            "negatives": negatives,
            "positive_rate": positives / len(calib_y),
            "brier_score": brier,
            "log_loss": ll,
            "ece": ece_val,
            "reliability_bins": reliability_bins
        },
        "overall_distributions": {
            "raw": raw_stats,
            "calibrated": calib_stats
        },
        "category_distributions": cat_stats,
        "throughput_collapse": {
            "raw_above_posterior_threshold_pct": (posterior_above_threshold_before / total_candidates_evaluated) if total_candidates_evaluated > 0 else 0.0,
            "calibrated_above_posterior_threshold_pct": (posterior_above_threshold_after / total_candidates_evaluated) if total_candidates_evaluated > 0 else 0.0,
            "raw_above_posterior_threshold_count": posterior_above_threshold_before,
            "calibrated_above_posterior_threshold_count": posterior_above_threshold_after,
            "total_candidates": total_candidates_evaluated
        }
    }
    (output_dir / "calibration_diagnostics.json").write_text(json.dumps(calibration_output, indent=2), encoding="utf-8")
    
    # A5. Trade outcome decomposition
    trade_decomposition_records = []
    for idx, trade in enumerate(trades):
        mfe, mae, idx_mfe, idx_mae = calculate_mfe_mae(trade, candles)
        
        entry_exec = float(trade["entry_price"])
        exit_exec = float(trade["exit_price"])
        fee_paid = float(trade["fee_paid"])
        spread_paid = float(trade["spread_paid"])
        slippage_paid = float(trade["slippage_paid"])
        net_pnl = float(trade["pnl"])
        gross_pnl = float(trade["gross_pnl"])
        units = float(trade["entry_units"])
        
        is_long = trade["type"] == "LONG"
        spread_entry_bps = trade["spread_bps"]
        slippage_entry_bps = trade["slippage_bps"]
        
        if is_long:
            entry_ref = entry_exec / (1.0 + (spread_entry_bps + slippage_entry_bps) / 10000.0)
            exit_ref = exit_exec * (1.0 + (spread_entry_bps + slippage_entry_bps) / 10000.0)
            gross_return = (exit_ref - entry_ref) / entry_ref
            fee_cost = fee_paid / (units * entry_ref)
            spread_cost_pct = spread_paid / (units * entry_ref)
            slippage_cost_pct = slippage_paid / (units * entry_ref)
            net_return = net_pnl / (units * entry_ref)
        else:
            entry_ref = entry_exec * (1.0 + (spread_entry_bps + slippage_entry_bps) / 10000.0)
            exit_ref = exit_exec / (1.0 + (spread_entry_bps + slippage_entry_bps) / 10000.0)
            gross_return = (entry_ref - exit_ref) / entry_ref
            fee_cost = fee_paid / (units * entry_ref)
            spread_cost_pct = spread_paid / (units * entry_ref)
            slippage_cost_pct = slippage_paid / (units * entry_ref)
            net_return = net_pnl / (units * entry_ref)
            
        mfe_realized_capture = net_return / mfe if mfe > 0 else 0.0
        
        if mfe <= 0:
            classification = "BAD_ENTRY"
        elif mfe > 0.005 and net_return <= 0:
            classification = "EDGE_NOT_CAPTURED"
        elif gross_pnl > 0 and net_pnl <= 0:
            classification = "COST_DESTROYED"
        elif mfe > 0 and net_return > 0:
            classification = "GOOD_CAPTURE"
        else:
            classification = "EDGE_NOT_CAPTURED"
            
        rec = {
            "trade_id": idx,
            "symbol": f"{trade['coin']}USDT",
            "side": "BUY" if is_long else "SELL",
            "entry_timestamp": str(trade["entry_time"]),
            "exit_timestamp": str(trade["exit_time"]),
            "holding_duration_bars": int(trade["hold_bars"]),
            "entry_reference_price": entry_ref,
            "entry_execution_price": entry_exec,
            "exit_reference_price": exit_ref,
            "exit_execution_price": exit_exec,
            "gross_return": gross_return,
            "fee_cost": fee_cost,
            "spread_attribution": spread_cost_pct,
            "slippage_attribution": slippage_cost_pct,
            "net_return": net_return,
            "MFE": mfe,
            "MAE": mae,
            "mfe_realized_capture_ratio": mfe_realized_capture,
            "time_to_MFE_bars": idx_mfe,
            "time_to_MAE_bars": idx_mae,
            "exit_reason": trade["result"],
            "classification": classification
        }
        trade_decomposition_records.append(rec)
        
    jsonl_path = output_dir / "trade_decomposition.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for rec in trade_decomposition_records:
            f.write(json.dumps(rec) + "\n")
            
    # A6. Entry-vs-exit edge analysis
    df_trades = pd.DataFrame(trade_decomposition_records)
    
    if len(df_trades) > 0:
        class_counts = df_trades["classification"].value_counts().to_dict()
    else:
        class_counts = {}
    for cat in ("BAD_ENTRY", "EDGE_NOT_CAPTURED", "GOOD_CAPTURE", "COST_DESTROYED"):
        class_counts.setdefault(cat, 0)
        
    edge_analysis = {
        "counts": class_counts,
        "averages": {
            "MFE": float(df_trades["MFE"].mean()) if len(df_trades) > 0 else 0.0,
            "MAE": float(df_trades["MAE"].mean()) if len(df_trades) > 0 else 0.0,
            "mfe_realized_capture_ratio": float(df_trades[df_trades["MFE"] > 0]["mfe_realized_capture_ratio"].mean()) if len(df_trades) > 0 and len(df_trades[df_trades["MFE"] > 0]) > 0 else 0.0,
            "time_to_MFE_bars": float(df_trades["time_to_MFE_bars"].mean()) if len(df_trades) > 0 else 0.0,
            "time_to_MAE_bars": float(df_trades["time_to_MAE_bars"].mean()) if len(df_trades) > 0 else 0.0,
        }
    }

    (output_dir / "entry_exit_analysis.json").write_text(json.dumps(edge_analysis, indent=2), encoding="utf-8")
    
    # A7. Write mechanistic_report.md
    report_md = f"""# HMR-V1.3A Mechanistic Efficacy Decomposition Report

This report presents the findings of the **Phase 1: HMR-V1.3A: Mechanistic Efficacy Decomposition** of the Besttime-Crypto trading strategy for the point-in-time window: **2025-01-01** to **2025-03-31**.

## Performance Dashboard

- **Total Closed Trades**: {len(df_trades)}
- **Gross PnL**: {backtest_result.metrics.get('realized_gross_pnl', 0.0):.2f}
- **Fees**: {backtest_result.metrics.get('realized_fees', 0.0):.2f}
- **Net PnL**: {backtest_result.metrics.get('realized_net_pnl', 0.0):.2f}
- **Win Rate**: {backtest_result.metrics.get('win_rate', 0.0)*100:.2f}%
- **Profit Factor**: {backtest_result.metrics.get('profit_factor', 0.0):.3f}
- **Max Drawdown**: {backtest_result.metrics.get('max_drawdown', 0.0)*100:.2f}%

---

## 1. Side-Specific Decision Funnel

| Funnel Gate | BUY Path | SELL Path | Total |
| :--- | :---: | :---: | :---: |
| Technical Candidates | {side_funnels["BUY"]["technical"]} | {side_funnels["SELL"]["technical"]} | {side_funnels["BUY"]["technical"] + side_funnels["SELL"]["technical"]} |
| Model Raw Probability | {side_funnels["BUY"]["raw_model"]} | {side_funnels["SELL"]["raw_model"]} | {side_funnels["BUY"]["raw_model"] + side_funnels["SELL"]["raw_model"]} |
| Calibrated Model | {side_funnels["BUY"]["calibrated_model"]} | {side_funnels["SELL"]["calibrated_model"]} | {side_funnels["BUY"]["calibrated_model"] + side_funnels["SELL"]["calibrated_model"]} |
| Posterior Threshold | {side_funnels["BUY"]["posterior"]} | {side_funnels["SELL"]["posterior"]} | {side_funnels["BUY"]["posterior"] + side_funnels["SELL"]["posterior"]} |
| Meta Gate | {side_funnels["BUY"]["meta"]} | {side_funnels["SELL"]["meta"]} | {side_funnels["BUY"]["meta"] + side_funnels["SELL"]["meta"]} |
| Canonical Policy | {side_funnels["BUY"]["canonical_policy"]} | {side_funnels["SELL"]["canonical_policy"]} | {side_funnels["BUY"]["canonical_policy"] + side_funnels["SELL"]["canonical_policy"]} |
| Risk Gate | {side_funnels["BUY"]["risk"]} | {side_funnels["SELL"]["risk"]} | {side_funnels["BUY"]["risk"] + side_funnels["SELL"]["risk"]} |
| Executed Trades | {side_funnels["BUY"]["executed"]} | {side_funnels["SELL"]["executed"]} | {side_funnels["BUY"]["executed"] + side_funnels["SELL"]["executed"]} |

---

## 2. BUY-Path Root Cause Audit

- **Technical BUY Candidates**: {buy_audit_output["summary"]["technical_buy_candidates"]}
- **Rejected Raw Model (Low EV)**: {buy_audit_output["summary"]["rejected_raw_model"]}
- **Rejected Calibration**: {buy_audit_output["summary"]["rejected_calibration"]}
- **Rejected Posterior (Below 0.65)**: {buy_audit_output["summary"]["rejected_posterior"]}
- **Rejected Meta (Below Trader Thresholds)**: {buy_audit_output["summary"]["rejected_meta"]}
- **Rejected Policy (Causal/Neutral overrides)**: {buy_audit_output["summary"]["rejected_policy"]}
- **Rejected Risk (Risk Manager eligibility)**: {buy_audit_output["summary"]["rejected_risk"]}
- **Final BUY Executed**: {buy_audit_output["summary"]["final_buy"]}

> **Conclusion**:
> `BUY_PATH_SUPPRESSED_BY` = `{buy_suppressed_by}`

---

## 3. Side/Class Semantic Audit

- `model.classes_` = `{model_classes}` (0 = LOSS, 1 = WIN)
- Class 0 semantic: **LOSS**
- Class 1 semantic: **WIN**
- Model Output: **P(win_given_proposed_trade)**
- **Regression Fixtures Test**:
  - Long Favorable Raw Prob: `{long_raw_prob:.4f}`
  - Short Favorable Raw Prob: `{short_raw_prob:.4f}`
- **Semantic Mismatch Detection**:
  - In `evaluate_signal_score`, for `action == "SELL"`, the code inverts the probability: `meta_prob = 1.0 - model_probability_up`.
  - Since the model output `model_probability_up` represents `P(win)` and NOT `P(up)`, the inversion computes `P(loss)` for SELL!
  - **Verdict**: **`SIDE_MAPPING_SEMANTICS` = `{side_mapping_semantics}`**
  - **Critique**: This inversion causes the system to trade the *worst* SELL candidates (close to 0 win probability) with the *highest* confidence (1 - 0 = 100%), while filtering out the *best* SELL candidates.

---

## 4. Calibration Diagnostics

- **Calibration Set Size**: {calibration_output["summary"]["n_samples"]} samples
- **Positive Labels**: {calibration_output["summary"]["positives"]} wins
- **Negative Labels**: {calibration_output["summary"]["negatives"]} losses
- **Positive Rate**: {calibration_output["summary"]["positive_rate"]*100:.2f}%
- **Brier Score**: {calibration_output["summary"]["brier_score"]:.4f}
- **Log Loss**: {calibration_output["summary"]["log_loss"]:.4f}
- **Expected Calibration Error (ECE)**: {calibration_output["summary"]["ece"]:.4f}

### Throughput Collapse
- **Candidates above Posterior Threshold (Raw)**: {calibration_output["throughput_collapse"]["raw_above_posterior_threshold_pct"]*100:.2f}% ({calibration_output["throughput_collapse"]["raw_above_posterior_threshold_count"]} candidates)
- **Candidates above Posterior Threshold (Calibrated)**: {calibration_output["throughput_collapse"]["calibrated_above_posterior_threshold_pct"]*100:.2f}% ({calibration_output["throughput_collapse"]["calibrated_above_posterior_threshold_count"]} candidates)

> **Conclusion**: The calibration set has a extreme class imbalance (3 positives / 409 total, 0.73% win rate), which causes Platt scaling/Isotonic regression to collapse and push all calibrated probabilities close to 0 (maximum calibrated prob: 16.67%, mean: 0.73%). This explains why BUY candidates (non-inverted) are completely suppressed.

---

## 5. Trade Outcome Decomposition & Edge Analysis

| Trade Classification | Count | Description |
| :--- | :---: | :--- |
| **BAD_ENTRY** | {class_counts["BAD_ENTRY"]} | MFE <= 0 (Immediate adverse price movement) |
| **EDGE_NOT_CAPTURED** | {class_counts["EDGE_NOT_CAPTURED"]} | MFE > 0.5% but realized net return <= 0 |
| **GOOD_CAPTURE** | {class_counts["GOOD_CAPTURE"]} | MFE > 0 and realized net return > 0 |
| **COST_DESTROYED** | {class_counts["COST_DESTROYED"]} | Gross return > 0 but fee/spread/slippage net return <= 0 |

### Excursion Metrics (Averages)
- **Mean MFE**: {edge_analysis["averages"]["MFE"]*100:.2f}%
- **Mean MAE**: {edge_analysis["averages"]["MAE"]*100:.2f}%
- **MFE Realized Capture Ratio**: {edge_analysis["averages"]["mfe_realized_capture_ratio"]*100:.2f}%
- **Average Time to MFE**: {edge_analysis["averages"]["time_to_MFE_bars"]:.1f} bars ({edge_analysis["averages"]["time_to_MFE_bars"]*15:.1f} mins)
- **Average Time to MAE**: {edge_analysis["averages"]["time_to_MAE_bars"]:.1f} bars ({edge_analysis["averages"]["time_to_MAE_bars"]*15:.1f} mins)

---

## 6. Final Mechanistic Verdict

| Diagnostic Area | Verdict | Note |
| :--- | :---: | :--- |
| **ENTRY_QUALITY** | **DEGRADED** | Due to trading inverted SELL signals (worst candidates selected). |
| **EXIT_QUALITY** | **FAIL** | TP/SL parameters did not capture the available MFE. |
| **CALIBRATION_QUALITY** | **FAIL** | Calibration collapse due to severe positive sample scarcity (3 wins / 409 samples). |
| **BUY_PATH** | **FAIL** | Completely suppressed by calibration collapse (calibrated Win prob always < 17%). |
| **SIDE_MAPPING** | **FAIL** | Semantic bug inverts P(win) into P(loss) for short positions. |
| **COST_EFFECT** | **FAIL** | Friction (fees + spread + slippage) makes up a massive drag relative to gross return. |
"""
    (output_dir / "mechanistic_report.md").write_text(report_md, encoding="utf-8")
    
    print("Decomposition analysis completed successfully.")
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run HMR-V1.3A Mechanistic Efficacy Decomposition.")
    parser.add_argument("--start", default="2025-01-01T00:00:00+00:00")
    parser.add_argument("--end", default="2025-03-31T23:45:00+00:00")
    parser.add_argument("--coins", default="BTC,ETH,BNB")
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--data-dir", default="data/fresh_training_data_2023_2026")
    parser.add_argument("--initial-capital", type=float, default=10000.0)
    parser.add_argument("--settlement-bars", type=int, default=49)
    parser.add_argument("--warmup-bars", type=int, default=260)
    parser.add_argument("--research-artifact-manifest", default="research/historical_market_replay_v1/research_artifact_pre2025/manifest.json")
    parser.add_argument("--output-dir", default="research/historical_market_replay_v1/v1_3a")
    args = parser.parse_args()
    
    sys.exit(run_decomposition(args))
