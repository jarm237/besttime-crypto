"""
scripts/run_horizon_neural_n0_3_experiment.py

Phase N0.3 — Horizon-Aware Neural Trading Bounded Experiment.
Evaluates the Horizon-Aware Policy (N0.3) against all standard baselines:
1. 100% Cash
2. True Buy & Hold
3. Exposure-Matched Cash Buy & Hold
4. Stateless TCN (N0.1)
5. Stateful Policy (N0.2)
6. Horizon-Aware Policy (N0.3)

Evaluates under both Standard Baseline (14 bps RT) and Stress (28 bps RT).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from typing import Any, Dict, List, Sequence
import numpy as np
import pandas as pd
import torch
import torch.optim as optim

from neural_trading.data.pipeline import MultiAssetDataPipeline, CORE_PILOT_UNIVERSE
from neural_trading.models.tcn_policy import TcnPortfolioPolicy
from neural_trading.models.stateful_policy import StatefulCostAwarePolicy
from neural_trading.models.horizon_policy import HorizonAwarePolicy
from neural_trading.objectives.horizon_loss import HorizonDifferentiableLoss
from neural_trading.engine.portfolio_simulator import NeuralPortfolioSimulator
from neural_trading.engine.walk_forward import ChronologicalNeuralEvaluator


def train_horizon_policy(
    model: HorizonAwarePolicy,
    X_train: np.ndarray,      # (S_train, N, T, F)
    y_train: np.ndarray,      # (S_train, N)
    loss_fn: HorizonDifferentiableLoss,
    epochs: int = 12,
    batch_size: int = 64,
    lr: float = 0.001,
    seed: int = 42,
) -> Dict[str, Any]:
    torch.manual_seed(seed)
    np.random.seed(seed)
    model.train()
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)

    S_train, N, T, F_dim = X_train.shape
    H = model.decision_horizon_hours
    max_idx = S_train - H

    # Precompute compound price relatives over H-hour horizons: (S_train - H, N + 1)
    print(f"\n[Precomputing {H}-hour compound returns across {S_train} train bars...]")
    compound_y_list = []
    cash_col = np.ones((max_idx, 1), dtype=np.float32)
    for i in range(max_idx):
        prod = np.prod(y_train[i : i + H], axis=0)
        compound_y_list.append(prod)
    compound_risky = np.array(compound_y_list, dtype=np.float32)
    compound_y_all = np.concatenate([cash_col, compound_risky], axis=-1)

    print(f"[Horizon Policy Training] {epochs} epochs, batch_size={batch_size}, horizon={H}h...")
    for ep in range(epochs):
        indices = np.random.permutation(max_idx)[:batch_size]
        batch_x = torch.tensor(X_train[indices], dtype=torch.float32)
        batch_compound_y = torch.tensor(compound_y_all[indices], dtype=torch.float32)

        # Previous weights proxy: neutral equal weight or cash
        prev_w = torch.zeros(batch_size, N + 1, dtype=torch.float32)
        prev_w[:, 0] = 0.50
        prev_w[:, 1:] = 0.50 / N

        optimizer.zero_grad()
        loss, diag = loss_fn(model, batch_x, batch_compound_y, prev_w)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()

        if (ep + 1) % 3 == 0 or ep == 0:
            print(f"  Epoch {ep+1:02d}/{epochs}: Loss={diag['loss']:+.4f} | Ann Sharpe={diag['annualized_sharpe']:+.2f} | Cash W={diag['mean_cash_weight']*100:.1f}% | TO={diag['mean_turnover']:.4f}")

    return {"final_loss": diag["loss"], "final_sharpe": diag["annualized_sharpe"]}


def evaluate_horizon_policy_oos(
    model: HorizonAwarePolicy,
    X_val: np.ndarray,
    y_val: np.ndarray,
    timestamps_val: Sequence[str],
    halts_val: np.ndarray,
    simulator: NeuralPortfolioSimulator,
    rebalance_horizon: int = 12,
    deadband_threshold: float = 0.05,
) -> Dict[str, Any]:
    model.eval()
    K, N, T, F_dim = X_val.shape
    device = torch.device("cpu")

    target_weights_seq = np.zeros((K, N + 1), dtype=np.float64)
    is_hold_seq = np.ones(K, dtype=bool)

    # Initial state: 100% Cash
    curr_target_w = np.zeros(N + 1, dtype=np.float64)
    curr_target_w[0] = 1.0

    last_rebal_step = -rebalance_horizon

    with torch.no_grad():
        for t in range(K):
            if halts_val[t]:
                target_weights_seq[t] = curr_target_w.copy()
                is_hold_seq[t] = True
                continue

            time_since_last = t - last_rebal_step
            is_cadence_due = (time_since_last >= rebalance_horizon) or (t == 0)

            if is_cadence_due:
                x_t = torch.tensor(X_val[t : t + 1], dtype=torch.float32)
                pred_w, conviction = model(x_t)
                cand_w = pred_w.squeeze(0).numpy().astype(np.float64)

                # Deadband threshold check on risky assets
                turnover_cand = float(np.sum(np.abs(cand_w[1:] - curr_target_w[1:])))
                if turnover_cand >= deadband_threshold or t == 0:
                    curr_target_w = cand_w
                    is_hold_seq[t] = False
                    last_rebal_step = t
                else:
                    # Turnover below deadband: hold existing
                    is_hold_seq[t] = True
            else:
                is_hold_seq[t] = True

            target_weights_seq[t] = curr_target_w.copy()

    sim_res = simulator.simulate(
        target_weights_seq,
        y_val,
        timestamps_val,
        is_halt_seq=halts_val,
        is_hold_seq=is_hold_seq,
        enforce_barrier=True,
    )
    return sim_res


def run_experiment():
    print("=" * 80)
    print("PHASE N0.3 — GREENFIELD HORIZON-AWARE NEURAL TRADING PILOT")
    print("=" * 80)

    # 1. Canonical Dataset
    pipeline = MultiAssetDataPipeline(symbols=CORE_PILOT_UNIVERSE)
    X, y, timestamps, halts, metadata = pipeline.build_aligned_dataset()
    val_start_cutoff = "2025-01-03 00:00:00"
    train_end_cutoff = "2024-12-31 23:00:00"

    train_indices = [i for i, t in enumerate(timestamps) if t <= train_end_cutoff]
    val_indices = [i for i, t in enumerate(timestamps) if t >= val_start_cutoff]

    X_train_raw = X[train_indices]
    y_train = y[train_indices]
    X_val_raw = X[val_indices]
    y_val = y[val_indices]
    val_timestamps = [timestamps[i] for i in val_indices]
    val_halts = halts[val_indices]

    mean_train = np.mean(X_train_raw, axis=(0, 1, 2), keepdims=True)
    std_train = np.std(X_train_raw, axis=(0, 1, 2), keepdims=True)
    std_train = np.where(std_train < 1e-6, 1.0, std_train)

    X_train = ((X_train_raw - mean_train) / std_train).astype(np.float32)
    X_val = ((X_val_raw - mean_train) / std_train).astype(np.float32)

    # 2. Simulators
    sim_base = NeuralPortfolioSimulator(
        symbols=CORE_PILOT_UNIVERSE,
        initial_capital=20000.0,
        fee_bps=5.0,
        slippage_bps=1.0,
        typical_spread_bps=1.0,
    )
    sim_stress = NeuralPortfolioSimulator(
        symbols=CORE_PILOT_UNIVERSE,
        initial_capital=20000.0,
        fee_bps=10.0,
        slippage_bps=2.0,
        typical_spread_bps=2.0,
    )
    evaluator = ChronologicalNeuralEvaluator(symbols=list(CORE_PILOT_UNIVERSE), simulator=sim_base)
    evaluator_stress = ChronologicalNeuralEvaluator(symbols=list(CORE_PILOT_UNIVERSE), simulator=sim_stress)

    # 3. Train Horizon-Aware Policy (N0.3)
    horizon_hours = 12
    n03_model = HorizonAwarePolicy(
        num_assets=5,
        lookback_window=48,
        num_channels=4,
        hidden_dim=32,
        dilations=(1, 2, 4, 8),
        decision_horizon_hours=horizon_hours,
    )
    loss_fn = HorizonDifferentiableLoss(
        decision_horizon_hours=horizon_hours,
        friction_rate=0.0007,
        lambda_turnover=0.05,
        lambda_downside=1.50,
    )
    train_horizon_policy(n03_model, X_train, y_train, loss_fn, epochs=12, batch_size=64, lr=0.001, seed=42)

    # 4. Out-of-Sample Evaluation: Baseline Scenario (14 bps RT)
    print("\n" + "=" * 80)
    print("OUT-OF-SAMPLE EVALUATION: BASELINE SCENARIO (14 BPS ROUND-TRIP)")
    print("=" * 80)

    res_cash = evaluator.evaluate_100pct_cash(y_val, val_timestamps, is_halt_seq=val_halts)
    res_tbh = evaluator.evaluate_true_buy_and_hold(y_val, val_timestamps, cash_weight=0.05, is_halt_seq=val_halts)
    res_ew_rebal = evaluator.evaluate_periodic_rebalance_ew(y_val, val_timestamps, cash_weight=0.05, is_halt_seq=val_halts)

    # N0.3 Horizon-Aware Policy evaluation
    res_n03 = evaluate_horizon_policy_oos(
        n03_model, X_val, y_val, val_timestamps, val_halts, sim_base, rebalance_horizon=horizon_hours, deadband_threshold=0.05
    )

    # Exposure-matched passive baseline
    avg_cash_n03 = res_n03["average_cash_weight"]
    res_matched_n03 = evaluator.evaluate_matched_cash_buy_and_hold(
        y_val, val_timestamps, target_cash_weight=avg_cash_n03, is_halt_seq=val_halts
    )

    # Legacy results for comparison (from N0.1 & N0.2 audited quality reports)
    # N0.1 Stateless TCN (audited): Net PnL = -$1720.27, Friction = $1705.48, Turnover = 129.1x, Trades = 41031
    # N0.2 Stateful Policy (audited): Net PnL = -$5508.21, Friction = $135.78, Turnover = 11.4x, Trades = 205
    n02_quality_path = REPO_ROOT / "data" / "historical" / "quality_reports" / "neural_trading_n0_2_pilot_results.json"
    n02_data = json.loads(n02_quality_path.read_text())
    res_n01_legacy = n02_data["scorecard_baseline_14bps"]["Stateless TCN (N0.1)"]
    res_n02_legacy = n02_data["scorecard_baseline_14bps"]["Stateful Policy (N0.2)"]

    scorecard_14bps = {
        "100% Cash": res_cash,
        "True Buy & Hold": res_tbh,
        "Hourly EW Rebal": res_ew_rebal,
        f"Matched Cash ({avg_cash_n03*100:.1f}%)": res_matched_n03,
        "Stateless TCN (N0.1)": res_n01_legacy,
        "Stateful Policy (N0.2)": res_n02_legacy,
        "Horizon-Aware (N0.3)": res_n03,
    }

    print(f"\n{'BASELINE (14 bps RT)':<32} | {'Net PnL ($)':>12} | {'Return (%)':>10} | {'Sharpe':>7} | {'MaxDD (%)':>9} | {'Turnover':>9} | {'Friction ($)':>12} | {'Trades':>7} | {'Hold %':>7} | {'Risk Forced':>11}")
    print("-" * 140)
    for name, r in scorecard_14bps.items():
        rf_count = r.get("risk_forced_rebalance_count", 0)
        print(f"{name:<32} | {r['net_pnl_usd']:>12.2f} | {r['total_return_pct']:>9.2f}% | {r['annualized_sharpe']:>7.2f} | {r['max_drawdown_pct']:>8.2f}% | {r['annualized_turnover']:>8.1f}x | {r['total_friction_usd']:>12.2f} | {r['total_trade_count']:>7} | {r.get('hold_decision_rate_pct', 0.0):>6.1f}% | {rf_count:>11}")

    # 5. Stress Scenario (28 bps RT)
    print("\n" + "=" * 80)
    print("OUT-OF-SAMPLE EVALUATION: STRESS SCENARIO (28 BPS ROUND-TRIP)")
    print("=" * 80)
    res_n03_stress = evaluate_horizon_policy_oos(
        n03_model, X_val, y_val, val_timestamps, val_halts, sim_stress, rebalance_horizon=horizon_hours, deadband_threshold=0.05
    )
    res_matched_n03_stress = evaluator_stress.evaluate_matched_cash_buy_and_hold(
        y_val, val_timestamps, target_cash_weight=avg_cash_n03, is_halt_seq=val_halts
    )

    scorecard_28bps = {
        f"Matched Cash ({avg_cash_n03*100:.1f}%)": res_matched_n03_stress,
        "Horizon-Aware (N0.3)": res_n03_stress,
    }

    print(f"\n{'STRESS SCENARIO (28 bps RT)':<32} | {'Net PnL ($)':>12} | {'Return (%)':>10} | {'Sharpe':>7} | {'MaxDD (%)':>9} | {'Turnover':>9} | {'Friction ($)':>12} | {'Trades':>7} | {'Hold %':>7} | {'Risk Forced':>11}")
    print("-" * 140)
    for name, r in scorecard_28bps.items():
        rf_count = r.get("risk_forced_rebalance_count", 0)
        print(f"{name:<32} | {r['net_pnl_usd']:>12.2f} | {r['total_return_pct']:>9.2f}% | {r['annualized_sharpe']:>7.2f} | {r['max_drawdown_pct']:>8.2f}% | {r['annualized_turnover']:>8.1f}x | {r['total_friction_usd']:>12.2f} | {r['total_trade_count']:>7} | {r.get('hold_decision_rate_pct', 0.0):>6.1f}% | {rf_count:>11}")

    # 6. Economic Attribution Audit
    gross_pnl_n03 = res_n03["net_pnl_usd"] + res_n03["total_friction_usd"]
    delta_vs_matched = res_n03["net_pnl_usd"] - res_matched_n03["net_pnl_usd"]
    delta_vs_n02 = res_n03["net_pnl_usd"] - res_n02_legacy["net_pnl_usd"]
    delta_vs_n01 = res_n03["net_pnl_usd"] - res_n01_legacy["net_pnl_usd"]

    print("\n" + "=" * 80)
    print("PHASE N0.3 ECONOMIC ATTRIBUTION & VALUE DECOMPOSITION")
    print("=" * 80)
    print(f"  Horizon-Aware Net PnL (14 bps RT)          : ${res_n03['net_pnl_usd']:+.2f}")
    print(f"  Gross PnL (Pre-Cost)                       : ${gross_pnl_n03:+.2f}")
    print(f"  Total Friction Paid                        : ${res_n03['total_friction_usd']:.2f}")
    print(f"  Annualized Turnover                        : {res_n03['annualized_turnover']:.1f}x (Trades: {res_n03['total_trade_count']})")
    print(f"  Hold Rate                                  : {res_n03['hold_decision_rate_pct']:.1f}%")
    print(f"  Risk Forced Rebalance Count                : {res_n03['risk_forced_rebalance_count']}")
    print(f"  Average Cash Allocation                    : {res_n03['average_cash_weight']*100:.1f}% (Risky Exposure: {res_n03['average_risky_weight']*100:.1f}%)")
    print(f"  Matched Cash Benchmark PnL                 : ${res_matched_n03['net_pnl_usd']:+.2f}")
    print(f"  Excess Timing & Selection Value (vs Matched): ${delta_vs_matched:+.2f}")
    print(f"  Net Delta vs N0.2 Stateful Policy          : ${delta_vs_n02:+.2f}")
    print(f"  Net Delta vs N0.1 Stateless TCN            : ${delta_vs_n01:+.2f}")

    if delta_vs_matched > 100.0:
        verdict = "NEURAL_POLICY_POSITIVE_NET_ALPHA"
        verdict_desc = f"Horizon-Aware Policy beat its matched-cash benchmark by ${delta_vs_matched:.2f} after realistic 14 bps friction."
    elif abs(delta_vs_matched) <= 100.0:
        verdict = "NEURAL_POLICY_EXPOSURE_ONLY"
        verdict_desc = f"Horizon-Aware Policy matched passive constant-cash exposure (${delta_vs_matched:+.2f}), indicating zero predictive timing alpha."
    else:
        verdict = "NEURAL_POLICY_NEGATIVE_NET_VALUE"
        verdict_desc = f"Horizon-Aware Policy underperformed matched cash by ${delta_vs_matched:.2f} net of friction."

    print(f"\n  Authoritative Verdict: {verdict}")
    print(f"  Description          : {verdict_desc}")

    # 7. Serialize Quality Report
    report_data = {
        "audit_version": "N0.3_Horizon_Aware",
        "universe": list(CORE_PILOT_UNIVERSE),
        "horizon_hours": horizon_hours,
        "evaluation_period": {
            "start": val_timestamps[0],
            "end": val_timestamps[-1],
            "bars": len(val_indices),
        },
        "scorecard_baseline_14bps": {
            k: {m: v for m, v in r.items() if m != "equity_curve"}
            for k, r in scorecard_14bps.items()
        },
        "scorecard_stress_28bps": {
            k: {m: v for m, v in r.items() if m != "equity_curve"}
            for k, r in scorecard_28bps.items()
        },
        "attribution": {
            "net_pnl_usd": res_n03["net_pnl_usd"],
            "gross_pnl_usd": round(gross_pnl_n03, 2),
            "friction_usd": res_n03["total_friction_usd"],
            "turnover": res_n03["annualized_turnover"],
            "trades": res_n03["total_trade_count"],
            "hold_rate_pct": res_n03["hold_decision_rate_pct"],
            "risk_forced_rebalances": res_n03["risk_forced_rebalance_count"],
            "average_cash_pct": round(res_n03["average_cash_weight"] * 100.0, 2),
            "average_risky_pct": round(res_n03["average_risky_weight"] * 100.0, 2),
            "matched_cash_pnl_usd": res_matched_n03["net_pnl_usd"],
            "excess_value_vs_matched_usd": round(delta_vs_matched, 2),
            "delta_vs_n02_usd": round(delta_vs_n02, 2),
            "delta_vs_n01_usd": round(delta_vs_n01, 2),
            "verdict": verdict,
            "verdict_description": verdict_desc,
        }
    }

    out_path = REPO_ROOT / "data" / "historical" / "quality_reports" / "neural_trading_n0_3_pilot_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report_data, indent=2))
    print(f"\nSaved N0.3 pilot quality report to {out_path}")

    return report_data


if __name__ == "__main__":
    run_experiment()
