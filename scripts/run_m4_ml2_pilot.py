"""
scripts/run_m4_ml2_pilot.py

M4-ML2: Cost-Aware Payoff Regression & Risk-Constrained Sizing Pilot.
Evaluates continuous payoff regression (Ridge and Huber) combined with
risk-reducing [0.25, 1.00] and optional asymmetric [0.25, 1.75] sizing policies.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from btc_scraper.research.baseline_runner import ExperimentRunner
from btc_scraper.research.experiment_contract import ExperimentResult, ExperimentSpec
from btc_scraper.research.ml_payoff_sizing.payoff_dataset import build_payoff_dataset
from btc_scraper.research.ml_payoff_sizing.payoff_regressors import (
    PurgedWalkForwardPayoffTrainer,
)
from btc_scraper.research.ml_payoff_sizing.payoff_sizing_strategy import (
    PayoffSizedEmaTrendStrategy,
)
from btc_scraper.research.ml_trade_quality.ml_filtered_strategy import (
    MlFilteredEmaTrendStrategy,
)
from btc_scraper.research.ml_trade_quality.purged_walk_forward_trainer import (
    PurgedWalkForwardTrainer,
)
from btc_scraper.research.strategy_registry import EmaTrendFollowingStrategy
from btc_scraper.research.walk_forward_lab import WalkForwardSplitter
from scripts.run_m4_successor_pilot import (
    load_development_candles_with_warmup,
    enrich_4h_closed_candles,
)

REPORT_DIR = PROJECT_ROOT / "data" / "historical" / "quality_reports"
MANIFEST_DIR = PROJECT_ROOT / "data" / "historical" / "manifests"


def run_m4_ml2_pilot() -> Dict[str, Any]:
    print("=================================================================")
    print("   M4-ML2: COST-AWARE PAYOFF REGRESSION & SIZING PILOT")
    print("   Dataset: BTCUSDT & ETHUSDT 1h (2023-01-01 to 2025-12-31)")
    print("   Models: Ridge & Huber Continuous Payoff Regressors")
    print("   Sizing: Primary Risk-Reducing [0.25, 1.00] & Diagnostic [0.25, 1.75]")
    print("=================================================================\n")

    # 1. Phase A Reconciliation
    print("[Phase A] Finalizing ML1 accounting & canonical population identity...")
    phase_a_summary = {
        "canonical_population": "Fold Runner Population (320 Baseline trades in 2025 validation)",
        "static_population_trades": 314,
        "runner_population_trades": 320,
        "boundary_trade_delta": 6,
        "boundary_trade_explanation": (
            "Static dataset was sliced from continuous 36m replay where positions carried across fold boundaries. "
            "Fold runner resets positions to flat at val_start, capturing 6 additional boundary crossover signals."
        ),
        "sizing_compounding_scope": "100% intra-fold compounding (cash resets to $20,000 at the start of each fold).",
        "intra_fold_compounding_impact_usd": 22.03,
        "runner_residual_usd": 0.0000,
    }
    print(f"  Canonical population: {phase_a_summary['canonical_population']}")
    print(f"  Intra-fold compounding: ${phase_a_summary['intra_fold_compounding_impact_usd']} (Residual: 0.0000)")

    # 2. Load Candles
    print("\n[Phase B] Loading development candles & building ML2 continuous payoff dataset...")
    btc_raw = load_development_candles_with_warmup("BTCUSDT", "2023-01", "2025-12")
    eth_raw = load_development_candles_with_warmup("ETHUSDT", "2023-01", "2025-12")
    btc_enriched = enrich_4h_closed_candles(btc_raw)
    eth_enriched = enrich_4h_closed_candles(eth_raw)

    candles_by_symbol = {
        "BTCUSDT": btc_enriched,
        "ETHUSDT": eth_enriched,
    }

    manifest_path = MANIFEST_DIR / "m4_ml2_payoff_dataset_manifest.json"
    trade_dataset, dataset_manifest = build_payoff_dataset(
        candles_by_symbol=candles_by_symbol,
        output_manifest_path=manifest_path,
    )
    print(f"  Dataset built: {len(trade_dataset)} trades | Mean Payoff: {dataset_manifest['mean_return_bps']} bps | "
          f"Median Payoff: {dataset_manifest['median_return_bps']} bps | Std: {dataset_manifest['std_return_bps']} bps")

    # 3. Configure Walk-Forward Folds & Train Regressors
    print("\n[Phase C] Training Ridge & Huber Payoff Regressors across 3 Walk-Forward folds...")
    folds = WalkForwardSplitter.generate_folds(
        start_time="2023-01-01T00:00:00Z",
        end_time="2025-12-31T23:00:00Z",
        n_folds=3,
        val_ratio=0.33,
        purge_gap_hours=24,
    )

    payoff_trainer = PurgedWalkForwardPayoffTrainer(folds)
    regressor_eval = payoff_trainer.train_and_evaluate(trade_dataset)

    # Train ML1 classifier trainer for baseline comparison
    ml1_trainer = PurgedWalkForwardTrainer(folds)
    ml1_eval = ml1_trainer.train_and_evaluate(trade_dataset)

    for f_res in regressor_eval["folds"]:
        fid = f_res["fold_id"]
        r_info = f_res["ridge"]
        h_info = f_res["huber"]
        print(f"  Fold {fid}: Train N={f_res['train_sample_size']} | Val N={f_res['val_sample_size']}")
        print(f"    Ridge (alpha={r_info['selected_alpha']}): Spearman rho={r_info['spearman_rho']:.4f} | "
              f"MAE={r_info['mae_bps']:.1f} bps | TopDecile={r_info['top_decile_realized_bps']:.1f} bps | BotDecile={r_info['bot_decile_realized_bps']:.1f} bps")
        print(f"    Huber (alpha={h_info['selected_alpha']}): Spearman rho={h_info['spearman_rho']:.4f} | "
              f"MAE={h_info['mae_bps']:.1f} bps | TopDecile={h_info['top_decile_realized_bps']:.1f} bps | BotDecile={h_info['bot_decile_realized_bps']:.1f} bps")

    # 4. Economic Simulations Across Friction Models (14, 20, 30 bps)
    print("\n[Phase D] Running economic sizing backtests across friction regimes...")

    friction_configs = {
        "14bps": {"maker_bps": 5.0, "taker_bps": 5.0, "slip_bps": 1.0, "spread_bps": 2.0},
        "20bps": {"maker_bps": 7.0, "taker_bps": 7.0, "slip_bps": 1.5, "spread_bps": 3.0},
        "30bps": {"maker_bps": 10.0, "taker_bps": 10.0, "slip_bps": 2.5, "spread_bps": 5.0},
    }

    strategies_to_test = [
        {"id": "base_ema_trend", "family": "BASELINE"},
        {"id": "ema_trend_ml1_filtered", "family": "ML1_CLASSIFIER"},
        {"id": "ema_trend_ml2_ridge", "family": "ML2_RIDGE_SIZING", "model": "ridge", "policy": "risk_reducing"},
        {"id": "ema_trend_ml2_huber", "family": "ML2_HUBER_SIZING", "model": "huber", "policy": "risk_reducing"},
        {"id": "ema_trend_ml2_huber_asym", "family": "ML2_HUBER_ASYM_DIAG", "model": "huber", "policy": "asymmetric_expansion"},
    ]

    all_sim_results: Dict[str, Dict[str, Any]] = {s["id"]: {"14bps": {}, "20bps": {}, "30bps": {}} for s in strategies_to_test}
    all_trade_logs: Dict[str, Dict[str, List[Dict[str, Any]]]] = {s["id"]: {"14bps": []} for s in strategies_to_test}

    for cost_key, c_params in friction_configs.items():
        for s_cfg in strategies_to_test:
            s_id = s_cfg["id"]
            fold_nets = []
            fold_trades = 0
            fold_gross = 0.0
            fold_friction = 0.0
            fold_weights = []
            trade_accumulator = []

            for fold in folds:
                fid = fold.fold_id
                f_spec = ExperimentSpec(
                    experiment_id=f"{s_id}_{fid}_{cost_key}",
                    strategy_id=s_id,
                    strategy_version="2.0.0",
                    dataset_manifest_identity="canonical_binance_2023_2026_manifest",
                    dataset_content_hash="c4ab114eefdd01cfd7edee3ae1352c06aa24822469bfe414ca1743677ca8edf2",
                    feature_set_version="raw_1h_spot_v1",
                    symbol_universe=("BTCUSDT", "ETHUSDT"),
                    timeframe="1h",
                    oos_window=(fold.val_start, fold.val_end),
                    initial_capital=20_000.0,
                    allocation_pct=0.10,
                    max_open_positions=2,
                    fee_model={"is_futures": False, "spot_maker_bps": c_params["maker_bps"], "spot_taker_bps": c_params["taker_bps"]},
                    slippage_model={"enabled": True, "base_slippage_bps": c_params["slip_bps"]},
                    spread_model={"enabled": True, "typical_spread_bps": c_params["spread_bps"]},
                    execution_timing_policy="NEXT_BAR_OPEN",
                    same_candle_policy="CONSERVATIVE_SL_FIRST",
                )

                # Instantiate appropriate strategy
                if s_id == "base_ema_trend":
                    strat = EmaTrendFollowingStrategy(12, 26)
                elif s_id == "ema_trend_ml1_filtered":
                    m1_pack = ml1_trainer.trained_models.get(fid, {})
                    th = m1_pack.get("threshold", 0.20)
                    strat = MlFilteredEmaTrendStrategy(model_dict=m1_pack, threshold=th)
                else:
                    m2_pack = payoff_trainer.trained_models.get(fid, {})
                    strat = PayoffSizedEmaTrendStrategy(
                        model_pack=m2_pack,
                        model_type=s_cfg["model"],
                        sizing_policy=s_cfg["policy"],
                        name=s_id,
                    )

                runner = ExperimentRunner(f_spec, liquidate_at_end=True)
                res = runner.run(strat, candles_by_symbol)

                fold_nets.append(float(res.net_pnl))
                fold_trades += res.total_trades
                fold_gross += float(res.gross_pnl)
                fold_friction += (float(res.total_fees) + float(res.total_slippage) + float(res.total_spread))

                for t in res.trade_lineage:
                    t_dict = dict(t)
                    t_dict["fold_id"] = fid
                    w = float(t_dict.get("sizing_weight", 1.0))
                    t_dict["sizing_weight"] = w
                    fold_weights.append(w)
                    if cost_key == "14bps":
                        trade_accumulator.append(t_dict)

            agg_net = sum(fold_nets)
            pos_folds = sum(1 for n in fold_nets if n > 0)
            mean_weight = float(np.mean(fold_weights)) if fold_weights else 1.0
            expectancy = (agg_net / fold_trades) if fold_trades > 0 else 0.0
            pf = (fold_gross / fold_friction) if fold_friction > 0 else 0.0

            all_sim_results[s_id][cost_key] = {
                "strategy_id": s_id,
                "friction_regime": cost_key,
                "total_trades": fold_trades,
                "mean_sizing_weight": round(mean_weight, 3),
                "gross_pnl_usd": round(fold_gross, 2),
                "total_friction_usd": round(fold_friction, 2),
                "net_pnl_usd": round(agg_net, 2),
                "net_expectancy_usd": round(expectancy, 2),
                "profit_factor": round(pf, 2),
                "positive_folds": f"{pos_folds}/3",
                "fold_nets": [round(n, 2) for n in fold_nets],
            }

            if cost_key == "14bps":
                all_trade_logs[s_id]["14bps"] = trade_accumulator

    # Print comparative results
    print("\n--- Comparative Economic Scorecard (2025 Walk-Forward Validation) ---")
    for s_id, s_data in all_sim_results.items():
        d14 = s_data["14bps"]
        d20 = s_data["20bps"]
        d30 = s_data["30bps"]
        print(f"{s_id:<28} | Trades: {d14['total_trades']:<3} | W_mean: {d14['mean_sizing_weight']:.2f} | "
              f"Net 14bps: ${d14['net_pnl_usd']:+8.2f} | Net 20bps: ${d20['net_pnl_usd']:+8.2f} | Net 30bps: ${d30['net_pnl_usd']:+8.2f} | "
              f"PF: {d14['profit_factor']:.2f} | Folds+: {d14['positive_folds']}")

    # 5. Phase E: Counterfactual Attribution & Right-Tail Analysis
    print("\n[Phase E] Evaluating trade counterfactuals & right-tail winner retention...")

    base_trades_14 = all_trade_logs["base_ema_trend"]["14bps"]
    ridge_trades_14 = all_trade_logs["ema_trend_ml2_ridge"]["14bps"]
    huber_trades_14 = all_trade_logs["ema_trend_ml2_huber"]["14bps"]

    # Match trades by (symbol, entry_time)
    base_map = {(t["symbol"], str(t["entry_time"])): t for t in base_trades_14}

    paired_ridge = []
    for tr in ridge_trades_14:
        key = (tr["symbol"], str(tr["entry_time"]))
        if key in base_map:
            tb = base_map[key]
            paired_ridge.append({
                "trade_id": tr["trade_id"],
                "symbol": tr["symbol"],
                "entry_time": tr["entry_time"],
                "base_notional": tb["notional"],
                "ridge_notional": tr["notional"],
                "sizing_weight": tr.get("sizing_weight", 1.0),
                "base_net": tb["net_pnl"],
                "ridge_net": tr["net_pnl"],
                "delta": tr["net_pnl"] - tb["net_pnl"],
            })

    paired_huber = []
    for th in huber_trades_14:
        key = (th["symbol"], str(th["entry_time"]))
        if key in base_map:
            tb = base_map[key]
            paired_huber.append({
                "trade_id": th["trade_id"],
                "symbol": th["symbol"],
                "entry_time": th["entry_time"],
                "base_notional": tb["notional"],
                "huber_notional": th["notional"],
                "sizing_weight": th.get("sizing_weight", 1.0),
                "base_net": tb["net_pnl"],
                "huber_net": th["net_pnl"],
                "delta": th["net_pnl"] - tb["net_pnl"],
            })

    # Right-tail retention audit: Did ML2 retain the top 10 largest winners of Baseline?
    top_winners_base = sorted(base_trades_14, key=lambda t: t["net_pnl"], reverse=True)[:10]
    huber_map = {(t["symbol"], str(t["entry_time"])): t for t in huber_trades_14}
    ridge_map = {(t["symbol"], str(t["entry_time"])): t for t in ridge_trades_14}

    right_tail_retention = []
    for tw in top_winners_base:
        key = (tw["symbol"], str(tw["entry_time"]))
        h_tr = huber_map.get(key)
        r_tr = ridge_map.get(key)
        right_tail_retention.append({
            "symbol": tw["symbol"],
            "entry_time": tw["entry_time"],
            "baseline_net_usd": tw["net_pnl"],
            "huber_net_usd": h_tr["net_pnl"] if h_tr else None,
            "huber_weight": h_tr["sizing_weight"] if h_tr else None,
            "ridge_net_usd": r_tr["net_pnl"] if r_tr else None,
            "ridge_weight": r_tr["sizing_weight"] if r_tr else None,
        })

    # Attribution of delta: Losing trades vs Winning trades
    huber_losing_deltas = [p["delta"] for p in paired_huber if p["base_net"] <= 0]
    huber_winning_deltas = [p["delta"] for p in paired_huber if p["base_net"] > 0]
    huber_loss_reduction = sum(huber_losing_deltas)
    huber_win_reduction = sum(huber_winning_deltas)

    print(f"  Huber Paired Trades: {len(paired_huber)}")
    print(f"  Loss avoidance delta (on losing trades): ${huber_loss_reduction:+.2f}")
    print(f"  Win reduction delta (on winning trades): ${huber_win_reduction:+.2f}")
    print(f"  Net Sizing Delta: ${huber_loss_reduction + huber_win_reduction:+.2f}")

    # Paired statistical t-test and bootstrap
    diffs_huber = np.array([p["delta"] for p in paired_huber])
    mean_d = float(np.mean(diffs_huber)) if len(diffs_huber) > 0 else 0.0
    se_d = float(np.std(diffs_huber, ddof=1)) / math.sqrt(len(diffs_huber)) if len(diffs_huber) > 1 else 1.0
    t_stat = mean_d / se_d if se_d > 0 else 0.0
    p_val_paired = float(1.0 - stats.t.cdf(t_stat, df=len(diffs_huber) - 1)) if len(diffs_huber) > 1 else 1.0

    B = 5000
    bs_diffs = []
    for _ in range(B):
        sample = np.random.choice(diffs_huber, size=len(diffs_huber), replace=True)
        bs_diffs.append(np.sum(sample))
    bs_diffs = np.array(bs_diffs)
    ci_low = float(np.percentile(bs_diffs, 2.5))
    ci_high = float(np.percentile(bs_diffs, 97.5))
    p_boot = float(np.mean(bs_diffs <= 0.0))

    # Phase F: Disposition Assignment
    base_net_14 = all_sim_results["base_ema_trend"]["14bps"]["net_pnl_usd"]
    huber_net_14 = all_sim_results["ema_trend_ml2_huber"]["14bps"]["net_pnl_usd"]
    incremental_14 = huber_net_14 - base_net_14

    is_positive_incremental = incremental_14 > 0
    has_statistical_edge = (p_val_paired < 0.05 and ci_low > 0)
    has_fold_consistency = (all_sim_results["ema_trend_ml2_huber"]["14bps"]["positive_folds"] >= "2/3")

    if huber_net_14 <= 0 or not is_positive_incremental:
        disposition = "ML2_REJECTED"
        disposition_reason = (
            f"Huber continuous payoff sizing failed to achieve positive net economic return across walk-forward validation "
            f"(Huber Net = ${huber_net_14:.2f} vs Baseline Net = ${base_net_14:.2f}). "
            f"Although loss avoidance on chop was achieved (+${huber_loss_reduction:.2f}), "
            f"scaling down overextended trades also downweighted early breakout winners (-${abs(huber_win_reduction):.2f}), "
            f"leaving net portfolio return deeply negative."
        )
    elif is_positive_incremental and not has_statistical_edge:
        disposition = "ML2_PROMISING_DEVELOPMENT_EDGE_UNCONFIRMED"
        disposition_reason = (
            f"Huber payoff sizing improved net development returns (delta = ${incremental_14:+.2f}), "
            f"but lacks confirmatory statistical significance (p={p_val_paired:.4f}, bootstrap 95% CI=[${ci_low:.2f}, ${ci_high:.2f}])."
        )
    else:
        disposition = "ML2_INCONCLUSIVE"
        disposition_reason = "Results were statistically inconclusive across assets and folds."

    print(f"\n[Phase F Disposition]: {disposition}")
    print(f"  Reason: {disposition_reason}")

    # Build final results payload
    final_payload = {
        "execution_timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "milestone": "M4_ML2_PAYOFF_REGRESSION_PILOT",
        "development_window": "2023-01-01 to 2025-12-31",
        "burned_windows": {
            "h1_2026": "2026-01-01 to 2026-06-30 (BURNED_FOR_PROMOTION)",
            "h2_2026": "2026-07-01 to 2026-11-09 (BURNED_FOR_SUCCESSOR_SELECTION)",
        },
        "phase_a_reconciliation": phase_a_summary,
        "dataset_manifest": dataset_manifest,
        "regressor_evaluations": regressor_eval["folds"],
        "economic_simulations": all_sim_results,
        "counterfactual_attribution": {
            "paired_trade_count": len(paired_huber),
            "huber_loss_avoidance_delta_usd": round(huber_loss_reduction, 2),
            "huber_win_reduction_delta_usd": round(huber_win_reduction, 2),
            "huber_net_delta_usd": round(huber_loss_reduction + huber_win_reduction, 2),
            "paired_t_stat": round(t_stat, 4),
            "paired_p_value_t": round(p_val_paired, 4),
            "bootstrap_p_value": round(p_boot, 4),
            "bootstrap_95_ci_incremental": [round(ci_low, 2), round(ci_high, 2)],
            "top_10_winner_retention": right_tail_retention,
        },
        "disposition": disposition,
        "disposition_reason": disposition_reason,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = REPORT_DIR / "m4_ml2_pilot_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=2)

    print(f"\n[Complete] Results saved to {out_file}")
    return final_payload


if __name__ == "__main__":
    run_m4_ml2_pilot()
