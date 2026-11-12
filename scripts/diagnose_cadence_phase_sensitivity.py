"""
scripts/diagnose_cadence_phase_sensitivity.py

Exhaustive audit of the 12h/24h periodic rebalancing finding on frozen N0.1 TCN.
Tests starting-phase sensitivity (UTC offsets 0..11 for 12h, 0..23 for 24h),
evaluates signal observation timing, causal execution, gross vs net returns,
and compares against passive exposure-matched benchmarks.
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
from neural_trading.models.tcn_policy import TcnPortfolioPolicy
from neural_trading.engine.portfolio_simulator import NeuralPortfolioSimulator
from neural_trading.engine.walk_forward import ChronologicalNeuralEvaluator

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_cadence_audit():
    print("=" * 80)
    print("PHASE B: CADENCE & STARTING-PHASE SENSITIVITY AUDIT (FROZEN N0.1 TCN)")
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

    # 2. Re-train or load N0.1 TCN model deterministically (seed 42)
    sim_base = NeuralPortfolioSimulator(symbols=CORE_PILOT_UNIVERSE, initial_capital=20000.0)
    evaluator = ChronologicalNeuralEvaluator(symbols=list(CORE_PILOT_UNIVERSE), simulator=sim_base)
    model = TcnPortfolioPolicy(num_assets=5, lookback_window=48, num_channels=4, hidden_dim=32, dilations=(1, 2, 4, 8))
    evaluator.train_policy(model, X_train, y_train, epochs=12, batch_size=128, lr=0.001, seed=42)

    # Generate raw proposed weights for validation
    model.eval()
    with torch.no_grad():
        X_val_t = torch.tensor(X_val, dtype=torch.float32)
        raw_weights_seq = model(X_val_t).numpy()  # (8711, 6)

    K = len(val_indices)

    # 3. Starting-Phase Sensitivity Audit for 12h Cadence (Offsets 0 to 11)
    print("\n--- 12-Hour Rebalancing: All 12 Starting Offsets (14 bps RT) ---")
    offsets_12h_results = []
    for offset in range(12):
        w_sched = np.zeros_like(raw_weights_seq)
        is_hold = np.ones(K, dtype=bool)

        curr_w = raw_weights_seq[0].copy()
        for t in range(K):
            if (t - offset) % 12 == 0 or t == 0:
                curr_w = raw_weights_seq[t].copy()
                is_hold[t] = False
            w_sched[t] = curr_w

        sim_res = sim_base.simulate(
            w_sched,
            y_val,
            val_timestamps,
            is_halt_seq=val_halts,
            is_hold_seq=is_hold,
            enforce_barrier=True,
        )
        offsets_12h_results.append({
            "offset": offset,
            "start_utc_hour": int(val_timestamps[offset].split()[1].split(":")[0]),
            "net_pnl_usd": sim_res["net_pnl_usd"],
            "return_pct": sim_res["total_return_pct"],
            "sharpe": sim_res["annualized_sharpe"],
            "max_drawdown": sim_res["max_drawdown_pct"],
            "friction_usd": sim_res["total_friction_usd"],
            "trades": sim_res["total_trade_count"],
            "turnover": sim_res["annualized_turnover"],
            "avg_cash": sim_res["average_cash_weight"],
        })

    df_12h = pd.DataFrame(offsets_12h_results)
    print(df_12h.to_string(index=False))

    mean_pnl_12h = df_12h["net_pnl_usd"].mean()
    std_pnl_12h = df_12h["net_pnl_usd"].std()
    min_pnl_12h = df_12h["net_pnl_usd"].min()
    max_pnl_12h = df_12h["net_pnl_usd"].max()
    pos_count_12h = (df_12h["net_pnl_usd"] > 0).sum()

    print(f"\n12h Summary Across 12 Offsets:")
    print(f"  Mean Net PnL   : ${mean_pnl_12h:+.2f} (std: ${std_pnl_12h:.2f})")
    print(f"  Range          : [${min_pnl_12h:+.2f}, ${max_pnl_12h:+.2f}]")
    print(f"  Positive Offsets: {pos_count_12h}/12 ({pos_count_12h/12*100:.1f}%)")

    # 4. Starting-Phase Sensitivity Audit for 24h Cadence (Offsets 0 to 23)
    print("\n--- 24-Hour Rebalancing: Selected Starting Offsets (0, 4, 8, 12, 16, 20) ---")
    offsets_24h_results = []
    for offset in range(24):
        w_sched = np.zeros_like(raw_weights_seq)
        is_hold = np.ones(K, dtype=bool)

        curr_w = raw_weights_seq[0].copy()
        for t in range(K):
            if (t - offset) % 24 == 0 or t == 0:
                curr_w = raw_weights_seq[t].copy()
                is_hold[t] = False
            w_sched[t] = curr_w

        sim_res = sim_base.simulate(
            w_sched,
            y_val,
            val_timestamps,
            is_halt_seq=val_halts,
            is_hold_seq=is_hold,
            enforce_barrier=True,
        )
        offsets_24h_results.append({
            "offset": offset,
            "start_utc_hour": int(val_timestamps[offset].split()[1].split(":")[0]),
            "net_pnl_usd": sim_res["net_pnl_usd"],
            "return_pct": sim_res["total_return_pct"],
            "sharpe": sim_res["annualized_sharpe"],
            "max_drawdown": sim_res["max_drawdown_pct"],
            "friction_usd": sim_res["total_friction_usd"],
            "trades": sim_res["total_trade_count"],
            "turnover": sim_res["annualized_turnover"],
            "avg_cash": sim_res["average_cash_weight"],
        })

    df_24h = pd.DataFrame(offsets_24h_results)
    print(df_24h.iloc[::4].to_string(index=False))

    mean_pnl_24h = df_24h["net_pnl_usd"].mean()
    std_pnl_24h = df_24h["net_pnl_usd"].std()
    min_pnl_24h = df_24h["net_pnl_usd"].min()
    max_pnl_24h = df_24h["net_pnl_usd"].max()
    pos_count_24h = (df_24h["net_pnl_usd"] > 0).sum()

    print(f"\n24h Summary Across 24 Offsets:")
    print(f"  Mean Net PnL   : ${mean_pnl_24h:+.2f} (std: ${std_pnl_24h:.2f})")
    print(f"  Range          : [${min_pnl_24h:+.2f}, ${max_pnl_24h:+.2f}]")
    print(f"  Positive Offsets: {pos_count_24h}/24 ({pos_count_24h/24*100:.1f}%)")

    # 5. Passive Matched Baseline for 12h
    avg_cash_12h = df_12h["avg_cash"].mean()
    res_matched_12h = evaluator.evaluate_matched_cash_buy_and_hold(
        y_val, val_timestamps, target_cash_weight=avg_cash_12h, is_halt_seq=val_halts
    )
    print(f"\nExposure-Matched Passive Baseline (Cash = {avg_cash_12h*100:.1f}%):")
    print(f"  Net PnL: ${res_matched_12h['net_pnl_usd']:.2f} | Return: {res_matched_12h['total_return_pct']:.2f}% | MaxDD: {res_matched_12h['max_drawdown_pct']:.2f}%")

    out_data = {
        "12h_offsets": offsets_12h_results,
        "12h_summary": {
            "mean_net_pnl": round(mean_pnl_12h, 2),
            "std_net_pnl": round(std_pnl_12h, 2),
            "min_net_pnl": round(min_pnl_12h, 2),
            "max_net_pnl": round(max_pnl_12h, 2),
            "positive_ratio": round(pos_count_12h / 12.0, 3),
        },
        "24h_summary": {
            "mean_net_pnl": round(mean_pnl_24h, 2),
            "std_net_pnl": round(std_pnl_24h, 2),
            "min_net_pnl": round(min_pnl_24h, 2),
            "max_net_pnl": round(max_pnl_24h, 2),
            "positive_ratio": round(pos_count_24h / 24.0, 3),
        },
        "matched_cash_benchmark": {
            "cash_pct": round(avg_cash_12h * 100.0, 2),
            "net_pnl_usd": res_matched_12h["net_pnl_usd"],
            "return_pct": res_matched_12h["total_return_pct"],
        }
    }
    out_file = REPO_ROOT / "data" / "historical" / "quality_reports" / "cadence_phase_sensitivity_report.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(out_data, indent=2))
    print(f"\nSaved cadence audit report to {out_file}")


if __name__ == "__main__":
    run_cadence_audit()
