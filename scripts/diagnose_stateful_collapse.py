"""
scripts/diagnose_stateful_collapse.py

Detailed diagnostic of the N0.2 Stateful Policy collapse:
1. Gate probability distribution across 8,711 steps in 2025.
2. Soft relaxation vs Hard threshold simulation on identical inputs.
3. Penalty magnitude decomposition during training rollouts.
4. Opportunity cost and holding duration analysis.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd
import torch

from neural_trading.data.pipeline import MultiAssetDataPipeline, CORE_PILOT_UNIVERSE
from neural_trading.models.stateful_policy import StatefulCostAwarePolicy
from neural_trading.objectives.stateful_loss import StatefulDifferentiableLoss
from neural_trading.engine.portfolio_simulator import NeuralPortfolioSimulator


def run_stateful_collapse_diagnostic():
    print("=" * 80)
    print("PHASE C: STATEFUL POLICY COLLAPSE & GATE DISPARITY DIAGNOSTIC")
    print("=" * 80)

    # 1. Load canonical dataset
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

    # 2. Re-instantiate and train Stateful policy exactly as in N0.2
    model = StatefulCostAwarePolicy(
        num_assets=5,
        lookback_window=48,
        num_channels=4,
        hidden_dim=32,
        dilations=(1, 2, 4, 8),
        rebalance_threshold=0.50,
    )
    loss_fn = StatefulDifferentiableLoss(
        friction_rate=0.0007,
        lambda_turnover=0.80,
        lambda_churn=0.50,
        lambda_downside=2.00,
    )

    # Fast 8 epochs training to diagnose gradient and penalty balance
    torch.manual_seed(42)
    np.random.seed(42)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001, weight_decay=1e-4)

    rollout_len = 64
    batch_size = 32
    num_rollouts = len(X_train) - rollout_len

    history_penalties = []
    print("\nTracing penalty components during rollout training...")
    for ep in range(6):
        indices = np.random.permutation(num_rollouts)[:batch_size]
        for idx in indices:
            x_seq = torch.tensor(X_train[idx : idx + rollout_len], dtype=torch.float32)
            y_risky = torch.tensor(y_train[idx : idx + rollout_len], dtype=torch.float32)
            cash_col = torch.ones((rollout_len, 1), dtype=torch.float32)
            y_seq = torch.cat([cash_col, y_risky], dim=-1)

            optimizer.zero_grad()
            loss, diag = loss_fn(model, x_seq, y_seq)
            loss.backward()
            optimizer.step()

        print(f"  Ep {ep+1}: Sharpe Term={diag['annualized_sharpe']:+.2f} | Churn Pen={diag['rebalance_rate']*0.50:.4f} | TO Pen={diag['mean_turnover']*0.80:.4f} | Gate Mean={diag['rebalance_rate']:.4f}")

    # 3. Analyze Gate Distribution on 2025 Validation
    model.eval()
    K = len(val_indices)
    gate_probs = []
    candidate_cash_weights = []
    effective_cash_weights_soft = []
    effective_cash_weights_hard = []

    curr_w_hard = np.zeros(6, dtype=np.float64)
    curr_w_hard[0] = 1.0

    curr_w_soft = np.zeros(6, dtype=np.float64)
    curr_w_soft[0] = 1.0

    soft_weights_seq = []
    hard_weights_seq = []
    hard_is_hold_seq = []

    with torch.no_grad():
        for t in range(K):
            if val_halts[t]:
                soft_weights_seq.append(curr_w_soft.copy())
                hard_weights_seq.append(curr_w_hard.copy())
                hard_is_hold_seq.append(True)
                gate_probs.append(0.0)
                continue

            x_t = torch.tensor(X_val[t : t + 1], dtype=torch.float32)
            
            # Hard mode step
            w_in_hard = torch.tensor(curr_w_hard.reshape(1, 6), dtype=torch.float32)
            eff_w_h, cand_w_h, g_h = model(x_t, w_in_hard, deterministic=True)
            gate_val = float(g_h.item())
            gate_probs.append(gate_val)
            cand_cash = float(cand_w_h[0, 0].item())
            candidate_cash_weights.append(cand_cash)

            is_rebal = gate_val >= 0.50
            hard_is_hold_seq.append(not is_rebal)
            eff_w_h_np = eff_w_h.squeeze(0).numpy()
            hard_weights_seq.append(eff_w_h_np)

            # Soft mode step
            w_in_soft = torch.tensor(curr_w_soft.reshape(1, 6), dtype=torch.float32)
            eff_w_s, cand_w_s, g_s = model(x_t, w_in_soft, deterministic=False)
            eff_w_s_np = eff_w_s.squeeze(0).numpy()
            soft_weights_seq.append(eff_w_s_np)

            # Drift forward
            y_t = np.concatenate([[1.0], y_val[t]])
            curr_w_hard = (eff_w_h_np * y_t) / np.sum(eff_w_h_np * y_t)
            curr_w_soft = (eff_w_s_np * y_t) / np.sum(eff_w_s_np * y_t)

    gate_arr = np.array(gate_probs)
    print("\n--- Gate Probability Distribution (8,711 steps in 2025) ---")
    print(f"  Min Gate Prob       : {np.min(gate_arr):.6f}")
    print(f"  25th Percentile     : {np.percentile(gate_arr, 25):.6f}")
    print(f"  Median (50th)       : {np.percentile(gate_arr, 50):.6f}")
    print(f"  75th Percentile     : {np.percentile(gate_arr, 75):.6f}")
    print(f"  95th Percentile     : {np.percentile(gate_arr, 95):.6f}")
    print(f"  Max Gate Prob       : {np.max(gate_arr):.6f}")
    print(f"  Bars with g < 0.05  : {np.sum(gate_arr < 0.05)} / {K} ({np.sum(gate_arr < 0.05)/K*100:.1f}%)")
    print(f"  Bars with 0.05<=g<0.5: {np.sum((gate_arr >= 0.05) & (gate_arr < 0.50))} / {K} ({np.sum((gate_arr >= 0.05) & (gate_arr < 0.50))/K*100:.1f}%)")
    print(f"  Bars with g >= 0.50 : {np.sum(gate_arr >= 0.50)} / {K} ({np.sum(gate_arr >= 0.50)/K*100:.2f}%)")

    # 4. Simulate Soft Execution vs Hard Execution
    sim = NeuralPortfolioSimulator(symbols=CORE_PILOT_UNIVERSE, initial_capital=20000.0)
    
    # Soft execution (simulator executes target_weights directly each step)
    res_soft = sim.simulate(
        np.array(soft_weights_seq),
        y_val,
        val_timestamps,
        is_halt_seq=val_halts,
        enforce_barrier=True,
    )
    # Hard execution
    res_hard = sim.simulate(
        np.array(hard_weights_seq),
        y_val,
        val_timestamps,
        is_halt_seq=val_halts,
        is_hold_seq=np.array(hard_is_hold_seq),
        enforce_barrier=True,
    )

    print("\n--- Soft Training Mode vs Hard Inference Mode Simulation ---")
    print(f"{'Mode':<20} | {'Net PnL ($)':>12} | {'Return (%)':>10} | {'Sharpe':>7} | {'Turnover':>9} | {'Friction ($)':>12} | {'Trades':>7} | {'Hold %':>7}")
    print("-" * 95)
    print(f"{'Soft Mode':<20} | {res_soft['net_pnl_usd']:>12.2f} | {res_soft['total_return_pct']:>9.2f}% | {res_soft['annualized_sharpe']:>7.2f} | {res_soft['annualized_turnover']:>8.1f}x | {res_soft['total_friction_usd']:>12.2f} | {res_soft['total_trade_count']:>7} | {res_soft['hold_decision_rate_pct']:>6.1f}%")
    print(f"{'Hard Mode (Eval)':<20} | {res_hard['net_pnl_usd']:>12.2f} | {res_hard['total_return_pct']:>9.2f}% | {res_hard['annualized_sharpe']:>7.2f} | {res_hard['annualized_turnover']:>8.1f}x | {res_hard['total_friction_usd']:>12.2f} | {res_hard['total_trade_count']:>7} | {res_hard['hold_decision_rate_pct']:>6.1f}%")

    out_data = {
        "gate_distribution": {
            "min": float(np.min(gate_arr)),
            "p25": float(np.percentile(gate_arr, 25)),
            "median": float(np.percentile(gate_arr, 50)),
            "p75": float(np.percentile(gate_arr, 75)),
            "p95": float(np.percentile(gate_arr, 95)),
            "max": float(np.max(gate_arr)),
            "pct_below_0_05": float(np.sum(gate_arr < 0.05) / K * 100.0),
            "pct_between_0_05_and_0_50": float(np.sum((gate_arr >= 0.05) & (gate_arr < 0.50)) / K * 100.0),
            "pct_above_0_50": float(np.sum(gate_arr >= 0.50) / K * 100.0),
        },
        "soft_vs_hard": {
            "soft": {
                "net_pnl": res_soft["net_pnl_usd"],
                "return_pct": res_soft["total_return_pct"],
                "turnover": res_soft["annualized_turnover"],
                "friction_usd": res_soft["total_friction_usd"],
                "trades": res_soft["total_trade_count"],
            },
            "hard": {
                "net_pnl": res_hard["net_pnl_usd"],
                "return_pct": res_hard["total_return_pct"],
                "turnover": res_hard["annualized_turnover"],
                "friction_usd": res_hard["total_friction_usd"],
                "trades": res_hard["total_trade_count"],
            }
        }
    }
    out_file = REPO_ROOT / "data" / "historical" / "quality_reports" / "stateful_collapse_diagnostic.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(out_data, indent=2))
    print(f"\nSaved collapse diagnostic to {out_file}")


if __name__ == "__main__":
    run_stateful_collapse_diagnostic()
