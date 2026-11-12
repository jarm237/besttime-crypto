"""
scripts/run_neural_n0_1_experiment.py

End-to-End Greenfield Neural Trading Reconstruction & Corrected Economic Evaluation.
Operates on canonical 26,303-bar dataset with exact risky-notional friction accounting,
train-only standardization, full receptive field TCN-DPA, and exposure-matched baselines.
"""
import json
import sys
from pathlib import Path
import numpy as np
import torch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from neural_trading.data.pipeline import MultiAssetDataPipeline
from neural_trading.data.schema import CORE_PILOT_UNIVERSE
from neural_trading.models.tcn_policy import TcnPortfolioPolicy
from neural_trading.models.gru_policy import GruPortfolioPolicy
from neural_trading.engine.portfolio_simulator import NeuralPortfolioSimulator
from neural_trading.engine.walk_forward import ChronologicalNeuralEvaluator
from neural_trading.objectives.differentiable_economic_loss import DifferentiableSharpeLoss


def run_experiment():
    print("=" * 80)
    print("PHASE N0.1 — GREENFIELD NEURAL RECONSTRUCTION & ECONOMIC CORRECTNESS")
    print("=" * 80)

    # 1. Load reconstructed dataset
    pipeline = MultiAssetDataPipeline(
        symbols=CORE_PILOT_UNIVERSE,
        reconstructed_dir=REPO_ROOT / "data" / "historical" / "reconstructed_neural_n0_1",
        lookback_window=48,
        timeframe="1h",
        use_funding=False,
    )
    X, y, timestamps, halts, metadata = pipeline.build_aligned_dataset()
    print(f"\n[Data Pipeline] Loaded canonical dataset:")
    print(f"  Shape X: {X.shape} (Samples, Assets, Lookback, Channels)")
    print(f"  Shape y: {y.shape} (Price relatives)")
    print(f"  Timestamps: {len(timestamps)} bars ({timestamps[0]} -> {timestamps[-1]})")
    print(f"  Channels ({len(metadata.channel_names)}): {metadata.channel_names}")
    print(f"  Trading halt bars: {int(np.sum(halts))}")

    # 2. Chronological Train / Validation Split with 48h Purge Gap
    # Train: 2023-01 to 2024-12
    # Purge: 48h (2025-01-01 00:00 to 2025-01-02 23:00)
    # Validation: 2025-01-03 00:00 to 2025-12-31 23:00
    val_start_cutoff = "2025-01-03 00:00:00"
    train_end_cutoff = "2024-12-31 23:00:00"

    train_indices = [i for i, t in enumerate(timestamps) if t <= train_end_cutoff]
    val_indices = [i for i, t in enumerate(timestamps) if t >= val_start_cutoff]
    purge_indices = [i for i, t in enumerate(timestamps) if train_end_cutoff < t < val_start_cutoff]

    print(f"\n[Walk-Forward Split]")
    print(f"  Train: {len(train_indices)} samples ({timestamps[train_indices[0]]} -> {timestamps[train_indices[-1]]})")
    print(f"  Purge Gap: {len(purge_indices)} samples ({timestamps[purge_indices[0]]} -> {timestamps[purge_indices[-1]]})")
    print(f"  Validation: {len(val_indices)} samples ({timestamps[val_indices[0]]} -> {timestamps[val_indices[-1]]})")

    X_train_raw = X[train_indices]
    y_train = y[train_indices]

    X_val_raw = X[val_indices]
    y_val = y[val_indices]
    val_timestamps = [timestamps[i] for i in val_indices]
    val_halts = halts[val_indices]

    # 3. Train-Only Feature Standardization (Causal, Zero Leakage)
    # Fit mean and std strictly on X_train_raw across (Samples, Assets, Time) for each feature channel
    mean_train = np.mean(X_train_raw, axis=(0, 1, 2), keepdims=True)
    std_train = np.std(X_train_raw, axis=(0, 1, 2), keepdims=True)
    std_train = np.where(std_train < 1e-6, 1.0, std_train)

    X_train = ((X_train_raw - mean_train) / std_train).astype(np.float32)
    X_val = ((X_val_raw - mean_train) / std_train).astype(np.float32)

    print(f"\n[Feature Normalization] Causal Train-Only Fit:")
    for ch_idx, ch_name in enumerate(metadata.channel_names):
        print(f"  {ch_name:<20}: Mean={mean_train[0,0,0,ch_idx]:.6f}, Std={std_train[0,0,0,ch_idx]:.6f}")

    # 4. Initialize Evaluator and Loss Function
    simulator = NeuralPortfolioSimulator(
        symbols=CORE_PILOT_UNIVERSE,
        initial_capital=20_000.0,
        fee_bps=10.0,
        slippage_bps=2.0,
        typical_spread_bps=2.0,
    )
    loss_fn = DifferentiableSharpeLoss(
        friction_rate=0.0014,
        lambda_turnover=0.30,
        lambda_downside=1.50,
    )
    evaluator = ChronologicalNeuralEvaluator(
        symbols=list(CORE_PILOT_UNIVERSE),
        simulator=simulator,
        loss_fn=loss_fn,
        device="cpu",
    )

    # 5. Train TCN-DPA Model (Dilations 1, 2, 4, 8 -> Receptive Field = 61 bars >= 48)
    print("\n" + "-" * 50)
    print("Training TCN-DPA Neural Policy (Receptive Field = 61 bars, 4 channels)...")
    tcn_model = TcnPortfolioPolicy(
        num_assets=len(CORE_PILOT_UNIVERSE),
        lookback_window=48,
        num_channels=4,
        hidden_dim=32,
        dilations=(1, 2, 4, 8),
        kernel_size=3,
        dropout=0.20,
    )
    tcn_train_res = evaluator.train_policy(
        tcn_model,
        X_train,
        y_train,
        epochs=12,
        batch_size=128,
        lr=0.001,
        rollout_steps=64,
        seed=42,
    )
    print(f"TCN Training Complete: Final Loss = {tcn_train_res['final_epoch_loss']:.4f}, Train Sharpe = {tcn_train_res['final_epoch_sharpe']:.2f}")

    # 6. Train Multi-Asset GRU Policy
    print("\n" + "-" * 50)
    print("Training Multi-Asset GRU Policy (Architectural Benchmark)...")
    gru_model = GruPortfolioPolicy(
        num_assets=len(CORE_PILOT_UNIVERSE),
        lookback_window=48,
        num_channels=4,
        hidden_dim=32,
        num_layers=2,
        dropout=0.20,
    )
    gru_train_res = evaluator.train_policy(
        gru_model,
        X_train,
        y_train,
        epochs=12,
        batch_size=128,
        lr=0.001,
        rollout_steps=64,
        seed=42,
    )
    print(f"GRU Training Complete: Final Loss = {gru_train_res['final_epoch_loss']:.4f}, Train Sharpe = {gru_train_res['final_epoch_sharpe']:.2f}")

    # 7. Evaluate Out-of-Sample (2025)
    print("\n" + "=" * 80)
    print("OUT-OF-SAMPLE EVALUATION (2025: 8,712 Decision Steps)")
    print("=" * 80)

    # 1. 100% Cash
    cash_res = evaluator.evaluate_100pct_cash(y_val, val_timestamps, is_halt_seq=val_halts)

    # 2. True Buy & Hold (5% cash, drift only, zero rebalance)
    tbh_res = evaluator.evaluate_true_buy_and_hold(y_val, val_timestamps, cash_weight=0.05, is_halt_seq=val_halts)

    # 3. Hourly Equal-Weight Periodic Rebalancing (5% cash, 1h rebalancing)
    pr_res = evaluator.evaluate_periodic_rebalance_ew(y_val, val_timestamps, cash_weight=0.05, is_halt_seq=val_halts)

    # 4. TCN-DPA Policy
    tcn_res = evaluator.evaluate_policy_oos(tcn_model, X_val, y_val, val_timestamps, is_halt_seq=val_halts)

    # 5. GRU Policy
    gru_res = evaluator.evaluate_policy_oos(gru_model, X_val, y_val, val_timestamps, is_halt_seq=val_halts)

    # 6. Constant-Cash Allocation (Matched to TCN Average Cash Exposure)
    tcn_avg_cash = tcn_res["average_cash_weight"]
    matched_cash_res = evaluator.evaluate_matched_cash_buy_and_hold(y_val, val_timestamps, target_cash_weight=tcn_avg_cash, is_halt_seq=val_halts)

    # 8. Scorecard Summary
    scorecard = {
        "100pct_cash": cash_res,
        "true_buy_and_hold": tbh_res,
        "hourly_rebalance_ew": pr_res,
        "matched_cash_exposure": matched_cash_res,
        "tcn_dpa_policy": tcn_res,
        "gru_policy": gru_res,
    }

    # Print Comparative Matrix
    headers = ["Strategy", "Net PnL ($)", "Return (%)", "Sharpe", "MaxDD (%)", "Avg Cash (%)", "Turnover (x/yr)", "Friction ($)", "Trades"]
    print(f"\n{' | '.join([f'{h:<16}' for h in headers])}")
    print("-" * 155)

    display_names = {
        "100pct_cash": "100% Cash",
        "true_buy_and_hold": "True Buy & Hold",
        "hourly_rebalance_ew": "Hourly EW Rebal",
        "matched_cash_exposure": f"Matched Cash ({tcn_avg_cash*100:.1f}%)",
        "tcn_dpa_policy": "TCN-DPA Neural",
        "gru_policy": "GRU Neural",
    }

    for key, name in display_names.items():
        res = scorecard[key]
        row = [
            f"{name:<16}",
            f"{res['net_pnl_usd']:>14.2f}",
            f"{res['total_return_pct']:>14.2f}%",
            f"{res['annualized_sharpe']:>14.2f}",
            f"{res['max_drawdown_pct']:>14.2f}%",
            f"{res['average_cash_weight']*100:>14.1f}%",
            f"{res['annualized_turnover']:>14.2f}x",
            f"{res['total_friction_usd']:>14.2f}",
            f"{res['actual_trade_count']:>14}",
        ]
        print(" | ".join(row))

    # Attribution: Neural Allocation Value vs Exposure Reduction Only
    delta_vs_tbh = tcn_res["net_pnl_usd"] - tbh_res["net_pnl_usd"]
    delta_vs_matched = tcn_res["net_pnl_usd"] - matched_cash_res["net_pnl_usd"]

    print("\n" + "=" * 80)
    print("ECONOMIC ATTRIBUTION AUDIT")
    print("=" * 80)
    print(f"  TCN Net PnL vs True Buy & Hold (0% cash defense)    : ${delta_vs_tbh:+.2f}")
    print(f"  TCN Net PnL vs Matched Exposure ({tcn_avg_cash*100:.1f}% cash)     : ${delta_vs_matched:+.2f}")
    
    if delta_vs_matched > 50.0:
        verdict = "GENUINE_NEURAL_ALLOCATION_ALPHA_CONFIRMED"
        verdict_desc = f"TCN outperformed constant-cash exposure by ${delta_vs_matched:.2f}, demonstrating genuine cross-asset timing/selection edge."
    elif delta_vs_matched >= -50.0:
        verdict = "EXPOSURE_REDUCTION_DOMINATED_WITH_NEUTRAL_ALPHA"
        verdict_desc = f"TCN performance difference vs matched cash is within noise (${delta_vs_matched:+.2f}). Gains primarily derive from disciplined cash preservation."
    else:
        verdict = "NEGATIVE_TIMING_DRAG"
        verdict_desc = f"TCN underperformed matched cash by ${delta_vs_matched:.2f} due to rebalancing turnover drag."

    print(f"  Research Verdict: {verdict}")
    print(f"  Reason: {verdict_desc}")

    # 9. Serialize Quality Report
    report_data = {
        "audit_version": "N0.1_Reconstructed",
        "universe": list(CORE_PILOT_UNIVERSE),
        "horizon_start": timestamps[val_indices[0]],
        "horizon_end": timestamps[val_indices[-1]],
        "decision_steps": len(val_indices),
        "scorecard": {k: {m: v for m, v in res.items() if m != "equity_curve"} for k, res in scorecard.items()},
        "attribution": {
            "tcn_vs_true_buy_and_hold_usd": round(delta_vs_tbh, 2),
            "tcn_vs_matched_cash_usd": round(delta_vs_matched, 2),
            "tcn_avg_cash_pct": round(tcn_avg_cash * 100.0, 2),
            "verdict": verdict,
            "verdict_description": verdict_desc,
        }
    }

    out_file = REPO_ROOT / "data" / "historical" / "quality_reports" / "neural_trading_n0_1_pilot_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(report_data, indent=2))
    print(f"\nSaved quality report to {out_file}")

    return report_data


if __name__ == "__main__":
    run_experiment()
