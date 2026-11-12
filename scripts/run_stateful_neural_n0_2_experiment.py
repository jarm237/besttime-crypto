"""
scripts/run_stateful_neural_n0_2_experiment.py

End-to-End Execution of Phase N0.2: Stateful Cost-Aware Neural Portfolio Learning.
Trains a stateful policy with explicit HOLD gating on sequential rollouts,
evaluates on 2025 validation against exposure-matched benchmarks under 14 bps & 28 bps RT contracts.
"""
import json
import sys
from pathlib import Path
import numpy as np
import torch
import torch.optim as optim

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from neural_trading.data.pipeline import MultiAssetDataPipeline
from neural_trading.data.schema import CORE_PILOT_UNIVERSE
from neural_trading.models.stateful_policy import StatefulCostAwarePolicy
from neural_trading.models.tcn_policy import TcnPortfolioPolicy
from neural_trading.engine.portfolio_simulator import NeuralPortfolioSimulator
from neural_trading.engine.walk_forward import ChronologicalNeuralEvaluator
from neural_trading.objectives.stateful_loss import StatefulDifferentiableLoss


def train_stateful_policy(
    model: StatefulCostAwarePolicy,
    X_train: np.ndarray,      # (S_train, N, T, F)
    y_train: np.ndarray,      # (S_train, N)
    loss_fn: StatefulDifferentiableLoss,
    epochs: int = 15,
    batch_size: int = 64,
    rollout_len: int = 64,
    lr: float = 0.001,
    seed: int = 42,
) -> Dict[str, Any]:
    torch.manual_seed(seed)
    np.random.seed(seed)
    model.train()
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)

    S_train, N, T, F_dim = X_train.shape
    num_rollouts = S_train - rollout_len
    history = []

    print(f"\n[Stateful Policy Training] {epochs} epochs, batch_size={batch_size}, rollout_len={rollout_len} bars...")
    for ep in range(epochs):
        indices = np.random.permutation(num_rollouts)[:batch_size]
        ep_losses = []
        ep_sharpes = []
        ep_gates = []
        ep_turnovers = []

        for idx in indices:
            x_seq = torch.tensor(X_train[idx : idx + rollout_len], dtype=torch.float32)
            y_risky = torch.tensor(y_train[idx : idx + rollout_len], dtype=torch.float32)
            cash_col = torch.ones((rollout_len, 1), dtype=torch.float32)
            y_seq = torch.cat([cash_col, y_risky], dim=-1)

            optimizer.zero_grad()
            loss, diag = loss_fn(model, x_seq, y_seq)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            ep_losses.append(diag["loss"])
            ep_sharpes.append(diag["annualized_sharpe"])
            ep_gates.append(diag["rebalance_rate"])
            ep_turnovers.append(diag["mean_turnover"])

        mean_loss = float(np.mean(ep_losses))
        mean_sh = float(np.mean(ep_sharpes))
        mean_gate = float(np.mean(ep_gates))
        mean_to = float(np.mean(ep_turnovers))
        history.append({
            "epoch": ep + 1,
            "loss": round(mean_loss, 4),
            "sharpe": round(mean_sh, 2),
            "rebal_rate": round(mean_gate * 100.0, 1),
            "turnover": round(mean_to, 4),
        })
        if (ep + 1) % 3 == 0 or ep == 0:
            print(f"  Epoch {ep+1:02d}/{epochs}: Loss={mean_loss:+.4f} | Sharpe={mean_sh:+.2f} | Rebal Rate={mean_gate*100:.1f}% | Turnover={mean_to:.4f}")

    return {"final_loss": mean_loss, "final_sharpe": mean_sh, "history": history}


def evaluate_stateful_policy_oos(
    model: StatefulCostAwarePolicy,
    X_val: np.ndarray,
    y_val: np.ndarray,
    timestamps_val: Sequence[str],
    halts_val: np.ndarray,
    simulator: NeuralPortfolioSimulator,
) -> Dict[str, Any]:
    """
    Evaluates stateful policy sequentially: tracks drifted weights, passes current_weights
    to gating head, and executes discrete HOLD/REBALANCE decisions.
    """
    model.eval()
    K, N, T, F_dim = X_val.shape
    device = torch.device("cpu")

    target_weights_list = []
    is_hold_list = []

    curr_drifted_w = np.zeros(N + 1, dtype=np.float64)
    curr_drifted_w[0] = 1.0  # 100% Cash

    with torch.no_grad():
        for t in range(K):
            if halts_val[t]:
                # Halt: hold existing
                target_weights_list.append(curr_drifted_w.copy())
                is_hold_list.append(True)
                continue

            x_t = torch.tensor(X_val[t : t + 1], dtype=torch.float32)
            w_input = torch.tensor(curr_drifted_w.reshape(1, N + 1), dtype=torch.float32)

            eff_w, cand_w, g_t = model(x_t, w_input, deterministic=True)
            eff_w_np = eff_w.squeeze(0).numpy()
            cand_w_np = cand_w.squeeze(0).numpy()
            gate_prob = float(g_t.item())

            is_rebal = bool(gate_prob >= model.rebalance_threshold)
            is_hold = not is_rebal

            target_weights_list.append(eff_w_np)
            is_hold_list.append(is_hold)

            # Update drifted weight for next time step
            y_t = np.concatenate([[1.0], y_val[t]])
            drifted = (eff_w_np * y_t) / np.sum(eff_w_np * y_t)
            curr_drifted_w = drifted

    target_weights_seq = np.array(target_weights_list, dtype=np.float64)
    is_hold_seq = np.array(is_hold_list, dtype=bool)

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
    print("PHASE N0.2 — GREENFIELD STATEFUL COST-AWARE NEURAL TRADING PILOT")
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

    # Causal train-only normalization
    mean_train = np.mean(X_train_raw, axis=(0, 1, 2), keepdims=True)
    std_train = np.std(X_train_raw, axis=(0, 1, 2), keepdims=True)
    std_train = np.where(std_train < 1e-6, 1.0, std_train)

    X_train = ((X_train_raw - mean_train) / std_train).astype(np.float32)
    X_val = ((X_val_raw - mean_train) / std_train).astype(np.float32)

    # 2. Define Simulators for Baseline (14 bps RT) and Stress (28 bps RT)
    # Baseline: 7 bps per leg (5 fee, 1 slip, 1 spread) -> 14 bps RT
    sim_base = NeuralPortfolioSimulator(
        symbols=CORE_PILOT_UNIVERSE,
        initial_capital=20000.0,
        fee_bps=5.0,
        slippage_bps=1.0,
        typical_spread_bps=1.0,
    )
    # Stress: 14 bps per leg (10 fee, 2 slip, 2 spread) -> 28 bps RT
    sim_stress = NeuralPortfolioSimulator(
        symbols=CORE_PILOT_UNIVERSE,
        initial_capital=20000.0,
        fee_bps=10.0,
        slippage_bps=2.0,
        typical_spread_bps=2.0,
    )

    evaluator = ChronologicalNeuralEvaluator(symbols=list(CORE_PILOT_UNIVERSE), simulator=sim_base)

    # 3. Train Stateful Cost-Aware Policy
    stateful_model = StatefulCostAwarePolicy(
        num_assets=5,
        lookback_window=48,
        num_channels=4,
        hidden_dim=32,
        dilations=(1, 2, 4, 8),
        kernel_size=3,
        rebalance_threshold=0.50,
    )
    loss_fn = StatefulDifferentiableLoss(
        friction_rate=0.0007,  # 7 bps per leg
        lambda_turnover=0.80,  # Strong turnover penalty
        lambda_churn=0.50,     # Penalize rebalance gating
        lambda_downside=2.00,  # Downside semi-variance
    )
    train_res = train_stateful_policy(
        stateful_model,
        X_train,
        y_train,
        loss_fn,
        epochs=15,
        batch_size=64,
        rollout_len=64,
        lr=0.001,
        seed=42,
    )

    # 4. Out-of-Sample Evaluation (Baseline 14 bps RT)
    print("\n" + "=" * 80)
    print("OUT-OF-SAMPLE EVALUATION: BASELINE SCENARIO (14 BPS ROUND-TRIP)")
    print("=" * 80)

    # Benchmarks
    res_cash = evaluator.evaluate_100pct_cash(y_val, val_timestamps, is_halt_seq=val_halts)
    res_tbh = evaluator.evaluate_true_buy_and_hold(y_val, val_timestamps, cash_weight=0.05, is_halt_seq=val_halts)
    res_ew_rebal = evaluator.evaluate_periodic_rebalance_ew(y_val, val_timestamps, cash_weight=0.05, is_halt_seq=val_halts)

    # Stateless TCN Model (from N0.1)
    stateless_model = TcnPortfolioPolicy(num_assets=5, lookback_window=48, num_channels=4, hidden_dim=32, dilations=(1, 2, 4, 8))
    evaluator.train_policy(stateless_model, X_train, y_train, epochs=12, batch_size=128, lr=0.001, seed=42)
    res_stateless = evaluator.evaluate_policy_oos(stateless_model, X_val, y_val, val_timestamps, is_halt_seq=val_halts)

    # Stateful Model
    res_stateful = evaluate_stateful_policy_oos(stateful_model, X_val, y_val, val_timestamps, val_halts, sim_base)

    # Exposure-Matched Baseline for Stateful Policy
    avg_cash_stateful = res_stateful["average_cash_weight"]
    res_matched = evaluator.evaluate_matched_cash_buy_and_hold(y_val, val_timestamps, target_cash_weight=avg_cash_stateful, is_halt_seq=val_halts)

    # 5. Stress Scenario (28 bps RT)
    print("\n" + "=" * 80)
    print("OUT-OF-SAMPLE EVALUATION: STRESS SCENARIO (28 BPS ROUND-TRIP)")
    print("=" * 80)
    evaluator_stress = ChronologicalNeuralEvaluator(symbols=list(CORE_PILOT_UNIVERSE), simulator=sim_stress)
    res_stateful_stress = evaluate_stateful_policy_oos(stateful_model, X_val, y_val, val_timestamps, val_halts, sim_stress)
    res_stateless_stress = evaluator_stress.evaluate_policy_oos(stateless_model, X_val, y_val, val_timestamps, is_halt_seq=val_halts)
    res_matched_stress = evaluator_stress.evaluate_matched_cash_buy_and_hold(y_val, val_timestamps, target_cash_weight=avg_cash_stateful, is_halt_seq=val_halts)

    # 6. Scorecard Presentation
    scorecard_14bps = {
        "100% Cash": res_cash,
        "True Buy & Hold": res_tbh,
        "Hourly EW Rebal": res_ew_rebal,
        f"Matched Cash ({avg_cash_stateful*100:.1f}%)": res_matched,
        "Stateless TCN (N0.1)": res_stateless,
        "Stateful Policy (N0.2)": res_stateful,
    }

    print(f"\n{'BASELINE (14 bps RT)':<32} | {'Net PnL ($)':>12} | {'Return (%)':>10} | {'Sharpe':>7} | {'MaxDD (%)':>9} | {'Turnover':>9} | {'Friction ($)':>12} | {'Trades':>7} | {'Hold %':>7}")
    print("-" * 125)
    for name, r in scorecard_14bps.items():
        print(f"{name:<32} | {r['net_pnl_usd']:>12.2f} | {r['total_return_pct']:>9.2f}% | {r['annualized_sharpe']:>7.2f} | {r['max_drawdown_pct']:>8.2f}% | {r['annualized_turnover']:>8.1f}x | {r['total_friction_usd']:>12.2f} | {r['total_trade_count']:>7} | {r.get('hold_decision_rate_pct', 0.0):>6.1f}%")

    print(f"\n{'STRESS SCENARIO (28 bps RT)':<32} | {'Net PnL ($)':>12} | {'Return (%)':>10} | {'Sharpe':>7} | {'MaxDD (%)':>9} | {'Turnover':>9} | {'Friction ($)':>12} | {'Trades':>7} | {'Hold %':>7}")
    print("-" * 125)
    stress_rows = [
        (f"Matched Cash ({avg_cash_stateful*100:.1f}%)", res_matched_stress),
        ("Stateless TCN (N0.1)", res_stateless_stress),
        ("Stateful Policy (N0.2)", res_stateful_stress),
    ]
    for name, r in stress_rows:
        print(f"{name:<32} | {r['net_pnl_usd']:>12.2f} | {r['total_return_pct']:>9.2f}% | {r['annualized_sharpe']:>7.2f} | {r['max_drawdown_pct']:>8.2f}% | {r['annualized_turnover']:>8.1f}x | {r['total_friction_usd']:>12.2f} | {r['total_trade_count']:>7} | {r.get('hold_decision_rate_pct', 0.0):>6.1f}%")

    # 7. Economic Attribution
    delta_vs_stateless = res_stateful["net_pnl_usd"] - res_stateless["net_pnl_usd"]
    delta_vs_matched = res_stateful["net_pnl_usd"] - res_matched["net_pnl_usd"]
    fee_reduction = res_stateless["total_friction_usd"] - res_stateful["total_friction_usd"]

    print("\n" + "=" * 80)
    print("PHASE N0.2 ECONOMIC ATTRIBUTION AUDIT")
    print("=" * 80)
    print(f"  Stateful Net PnL vs Stateless TCN          : ${delta_vs_stateless:+.2f}")
    print(f"  Turnover Reduction (Stateless -> Stateful) : {res_stateless['annualized_turnover']:.1f}x -> {res_stateful['annualized_turnover']:.1f}x")
    print(f"  Friction Saved                             : ${fee_reduction:.2f}")
    print(f"  Hold Decision Rate                         : {res_stateful['hold_decision_rate_pct']:.1f}%")
    print(f"  Stateful Net PnL vs Matched Cash Exposure  : ${delta_vs_matched:+.2f}")

    if delta_vs_matched > 50.0:
        verdict = "NEURAL_POLICY_PROMISING_DEVELOPMENT"
        verdict_desc = f"Stateful policy beat matched constant-cash exposure by ${delta_vs_matched:.2f} net of 14 bps friction."
    elif abs(delta_vs_matched) <= 50.0:
        verdict = "NEURAL_POLICY_EXPOSURE_ONLY"
        verdict_desc = f"Stateful policy achieved zero excess return vs matched cash (${delta_vs_matched:+.2f}), indicating value derives from exposure reduction."
    else:
        verdict = "NEURAL_POLICY_NEGATIVE_NET_VALUE"
        verdict_desc = f"Stateful policy underperformed matched cash by ${delta_vs_matched:.2f} despite substantial turnover reduction."

    print(f"  Scientific Verdict: {verdict}")
    print(f"  Verdict Description: {verdict_desc}")

    # 8. Serialize Quality Report
    report_data = {
        "audit_version": "N0.2_Stateful_Cost_Aware",
        "universe": list(CORE_PILOT_UNIVERSE),
        "horizon_start": timestamps[val_indices[0]],
        "horizon_end": timestamps[val_indices[-1]],
        "decision_steps": len(val_indices),
        "cost_contract": {
            "baseline_per_leg_bps": 7.0,
            "baseline_round_trip_bps": 14.0,
            "stress_per_leg_bps": 14.0,
            "stress_round_trip_bps": 28.0,
        },
        "scorecard_baseline_14bps": {k: {m: v for m, v in r.items() if m != "equity_curve"} for k, r in scorecard_14bps.items()},
        "attribution": {
            "stateful_vs_stateless_usd": round(delta_vs_stateless, 2),
            "stateful_vs_matched_cash_usd": round(delta_vs_matched, 2),
            "friction_saved_usd": round(fee_reduction, 2),
            "stateful_hold_rate_pct": res_stateful["hold_decision_rate_pct"],
            "stateful_annual_turnover": res_stateful["annualized_turnover"],
            "verdict": verdict,
            "verdict_description": verdict_desc,
        }
    }

    out_path = REPO_ROOT / "data" / "historical" / "quality_reports" / "neural_trading_n0_2_pilot_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report_data, indent=2))
    print(f"\nSaved quality report to {out_path}")

    return report_data


if __name__ == "__main__":
    run_experiment()
