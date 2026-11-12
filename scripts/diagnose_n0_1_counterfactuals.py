import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import torch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from neural_trading.data.pipeline import MultiAssetDataPipeline
from neural_trading.data.schema import CORE_PILOT_UNIVERSE
from neural_trading.models.tcn_policy import TcnPortfolioPolicy
from neural_trading.engine.portfolio_simulator import NeuralPortfolioSimulator
from neural_trading.engine.walk_forward import ChronologicalNeuralEvaluator
from neural_trading.objectives.differentiable_economic_loss import DifferentiableSharpeLoss

def run_diagnostics():
    print("=" * 80)
    print("PHASE C — PREDICTIVE TIMING VS FEE DRAG COUNTERFACTUAL AUDIT")
    print("=" * 80)

    # 1. Load data
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

    # Train baseline TCN model with seed 42 (matching N0.1)
    loss_fn = DifferentiableSharpeLoss(friction_rate=0.0014, lambda_turnover=0.30, lambda_downside=1.50)
    sim_base = NeuralPortfolioSimulator(symbols=CORE_PILOT_UNIVERSE, initial_capital=20000.0, fee_bps=5.0, slippage_bps=1.0, typical_spread_bps=1.0) # 7 bps per leg = 14 bps roundtrip
    evaluator = ChronologicalNeuralEvaluator(symbols=list(CORE_PILOT_UNIVERSE), simulator=sim_base, loss_fn=loss_fn)

    tcn_model = TcnPortfolioPolicy(num_assets=5, lookback_window=48, num_channels=4, hidden_dim=32, dilations=(1, 2, 4, 8), kernel_size=3)
    tcn_train_res = evaluator.train_policy(tcn_model, X_train, y_train, epochs=12, batch_size=128, lr=0.001, rollout_steps=64, seed=42)

    # Generate raw sequence of target weights on validation
    tcn_model.eval()
    with torch.no_grad():
        x_tensor = torch.tensor(X_val, dtype=torch.float32)
        chunk_w = []
        for i in range(0, len(x_tensor), 512):
            chunk_w.append(tcn_model(x_tensor[i : i + 512]).cpu().numpy())
        raw_weights_seq = np.concatenate(chunk_w, axis=0)

    print(f"Generated raw validation weights: shape={raw_weights_seq.shape}")

    # Counterfactual 1: Baseline 14 bps round-trip (7 bps per leg)
    sim_14bps = NeuralPortfolioSimulator(symbols=CORE_PILOT_UNIVERSE, initial_capital=20000.0, fee_bps=5.0, slippage_bps=1.0, typical_spread_bps=1.0)
    res_14bps = sim_14bps.simulate(raw_weights_seq, y_val, val_timestamps, is_halt_seq=val_halts)

    # Counterfactual 2: Zero Friction (0 bps)
    sim_zero = NeuralPortfolioSimulator(symbols=CORE_PILOT_UNIVERSE, initial_capital=20000.0, fee_bps=0.0, slippage_bps=0.0, typical_spread_bps=0.0)
    res_zero = sim_zero.simulate(raw_weights_seq, y_val, val_timestamps, is_halt_seq=val_halts)

    # Counterfactual 3: Stress 28 bps round-trip (14 bps per leg)
    sim_28bps = NeuralPortfolioSimulator(symbols=CORE_PILOT_UNIVERSE, initial_capital=20000.0, fee_bps=10.0, slippage_bps=2.0, typical_spread_bps=2.0)
    res_28bps = sim_28bps.simulate(raw_weights_seq, y_val, val_timestamps, is_halt_seq=val_halts)

    # Counterfactual 4: Fixed execution schedule: rebalance every 4h, 12h, 24h
    res_schedules = {}
    for step_interval in [4, 12, 24]:
        sched_weights = raw_weights_seq.copy()
        curr_active_w = sched_weights[0].copy()
        for t in range(len(sched_weights)):
            if t % step_interval == 0:
                curr_active_w = sched_weights[t].copy()
            else:
                # Drift weight naturally without rebalance
                sched_weights[t] = curr_active_w
            # update curr_active_w drift
            y_t = np.concatenate([[1.0], y_val[t]])
            curr_active_w = (curr_active_w * y_t) / np.sum(curr_active_w * y_t)
        res_sched = sim_14bps.simulate(sched_weights, y_val, val_timestamps, is_halt_seq=val_halts)
        res_schedules[f"rebal_{step_interval}h"] = res_sched

    # Counterfactual 5: No-trade deadband threshold (rebalance only if delta_risky > theta)
    res_thresholds = {}
    for theta in [0.02, 0.05, 0.10]:
        th_weights = raw_weights_seq.copy()
        curr_w = th_weights[0].copy()
        for t in range(len(th_weights)):
            prop_w = th_weights[t]
            delta_risky = np.sum(np.abs(prop_w[1:] - curr_w[1:]))
            if delta_risky > theta:
                curr_w = prop_w.copy()
            else:
                th_weights[t] = curr_w.copy()
            y_t = np.concatenate([[1.0], y_val[t]])
            curr_w = (curr_w * y_t) / np.sum(curr_w * y_t)
        res_th = sim_14bps.simulate(th_weights, y_val, val_timestamps, is_halt_seq=val_halts)
        res_thresholds[f"threshold_{int(theta*100)}pct"] = res_th

    # Matched Cash Baseline
    avg_cash = res_14bps["average_cash_weight"]
    matched_cash_res = evaluator.evaluate_matched_cash_buy_and_hold(y_val, val_timestamps, target_cash_weight=avg_cash, is_halt_seq=val_halts)

    # Print Report
    print("\n--- COUNTERFACTUAL RESULTS (2025: 8,711 bars) ---")
    rows = [
        ("Zero Friction (Gross Return)", res_zero),
        ("Standard 14 bps RT (Baseline)", res_14bps),
        ("Stress 28 bps RT", res_28bps),
        ("Rebalance Every 4h (14 bps RT)", res_schedules["rebal_4h"]),
        ("Rebalance Every 12h (14 bps RT)", res_schedules["rebal_12h"]),
        ("Rebalance Every 24h (14 bps RT)", res_schedules["rebal_24h"]),
        ("Deadband Threshold 2% (14 bps RT)", res_thresholds["threshold_2pct"]),
        ("Deadband Threshold 5% (14 bps RT)", res_thresholds["threshold_5pct"]),
        ("Deadband Threshold 10% (14 bps RT)", res_thresholds["threshold_10pct"]),
        (f"Passive Matched Cash ({avg_cash*100:.1f}%)", matched_cash_res),
    ]

    print(f"{'Configuration':<35} | {'Net PnL ($)':>12} | {'Return (%)':>10} | {'Sharpe':>7} | {'MaxDD (%)':>9} | {'Turnover':>9} | {'Friction ($)':>12}")
    print("-" * 110)
    for name, r in rows:
        print(f"{name:<35} | {r['net_pnl_usd']:>12.2f} | {r['total_return_pct']:>9.2f}% | {r['annualized_sharpe']:>7.2f} | {r['max_drawdown_pct']:>8.2f}% | {r['annualized_turnover']:>8.1f}x | {r['total_friction_usd']:>12.2f}")

    return {
        "zero_friction": res_zero,
        "base_14bps": res_14bps,
        "stress_28bps": res_28bps,
        "schedules": res_schedules,
        "thresholds": res_thresholds,
        "matched_cash": matched_cash_res,
    }

if __name__ == "__main__":
    run_diagnostics()
