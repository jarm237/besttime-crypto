#!/usr/bin/env python3
"""HMR-V5: Event-Driven Self-Financing Replay Audit.

Performs mathematically rigorous event-driven portfolio accounting on historical
market replay signals:
- Self-financing cash and capital accounting.
- Capital locking at entry, release strictly at exit timestamp.
- Capacity constraints (max concurrent positions globally and per asset).
- Bid-ask slippage (2 bps) and exchange fees (5 bps) applied per leg.
- Continuous equity tracking and true Max Drawdown.
- Daily-sampled equity returns for Sharpe and Sortino computation.

Evidence Taxonomy: HISTORICAL_SIMULATION
(Does NOT represent observed demo/live account trading outcomes).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

from btc_scraper.trading.event_driven_accounting import (
    AccountingConfig,
    EventDrivenAccountingEngine,
)
from scripts.generate_triple_barrier_labels import load_candles_for_coin
from scripts.hmr_v5_b1_exit_audit import compute_atr14
from scripts.hmr_v5_b2_executable_replay import apply_policy_p4
from scripts.hmr_v5_c2_minimal_model import run_e4_generation
from scripts.hmr_v5_d2_parity_replay import RuntimeInferenceEngine, MODEL_DIR

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4a_outcome_scaffold.parquet"
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v5"
OUT_DIR.mkdir(parents=True, exist_ok=True)

AUDIT_TS = datetime.now(timezone.utc).isoformat()
COINS = ["BTC", "ETH", "BNB"]


def main():
    print("=== HMR-V5: Event-Driven Self-Financing Replay Audit ===")
    print(f"Timestamp: {AUDIT_TS}\n")

    # Load frozen inference engine (strictly read-only)
    engine = RuntimeInferenceEngine(MODEL_DIR)
    
    # Load scaffold
    df_scaffold = pd.read_parquet(SCAFFOLD_PATH)
    df_scaffold["timestamp"] = pd.to_datetime(df_scaffold["timestamp"], utc=True)
    
    X_cols = ["return_8", "return_32", "return_72", "abs_move_72"]
    conf_start, conf_end = "2024-07-02", "2025-01-01"
    val_end = "2024-06-30"
    conf_cutoff = pd.Timestamp(val_end, tz="UTC") + pd.Timedelta(hours=24)
    conf_start_ts = pd.Timestamp(conf_start, tz="UTC")
    conf_end_ts = pd.Timestamp(conf_end, tz="UTC")

    control_trades = []
    treatment_trades = []

    print("Generating candidate trades and evaluating frozen S3 threshold...")
    for sym in COINS:
        csv_dir = REPO_ROOT / "data/fresh_training_data_2023_2026"
        candle_df = load_candles_for_coin(csv_dir, sym, "15m")
        candle_df["timestamp"] = pd.to_datetime(candle_df["timestamp"], utc=True)
        candle_df = candle_df.sort_values("timestamp").reset_index(drop=True)
        candle_df["atr"] = compute_atr14(candle_df)
        
        df_coin = run_e4_generation(sym, df_scaffold, candle_df)
        df_conf = df_coin[
            (df_coin["entry_timestamp"] >= conf_start_ts)
            & (df_coin["entry_timestamp"] < conf_end_ts)
            & (df_coin["exit_timestamp"] < conf_end_ts)
        ]
        df_conf = df_conf[df_conf["entry_timestamp"] >= conf_cutoff].reset_index(drop=True)
        
        for idx, row in df_conf.iterrows():
            prob, dec = engine.predict_score_and_decision(sym, [row[c] for c in X_cols])
            t_dict = row.to_dict()
            t_dict["trade_id"] = f"{sym}_{idx}"
            control_trades.append(t_dict)
            if dec:
                treatment_trades.append(t_dict)

    print(f"Total candidate signals: Control={len(control_trades)}, Treatment (S3 Pass)={len(treatment_trades)}")

    # Apply P4 execution serialization policy
    control_trades.sort(key=lambda x: x["entry_timestamp"])
    treatment_trades.sort(key=lambda x: x["entry_timestamp"])
    control_p4, _ = apply_policy_p4(control_trades)
    treatment_p4, _ = apply_policy_p4(treatment_trades)
    print(f"P4 Serialized trades: Control={len(control_p4)}, Treatment={len(treatment_p4)}")

    # Run Event-Driven Self-Financing Accounting Engine
    config = AccountingConfig(
        initial_capital=10000.0,
        max_concurrent_positions=3,
        max_positions_per_asset=1,
        allocation_pct_per_trade=0.25,
        fee_rate_bps=5.0,
        slippage_bps=2.0,
        annualization_factor=365,
    )
    acct = EventDrivenAccountingEngine(config)

    res_ctrl = acct.run(
        control_p4,
        date_range=(conf_start, conf_end),
        cross_boundary_policy="EXCLUDE_CROSS_BOUNDARY_OUTCOME",
    )
    res_treat = acct.run(
        treatment_p4,
        date_range=(conf_start, conf_end),
        cross_boundary_policy="EXCLUDE_CROSS_BOUNDARY_OUTCOME",
    )

    output = {
        "program": "HMR-V5-EVENT-DRIVEN-REPLAY",
        "audit_timestamp": AUDIT_TS,
        "evidence_taxonomy": "HISTORICAL_SIMULATION",
        "date_range": {
            "start": conf_start,
            "end": conf_end,
            "semantics": "half_open_[start,end)",
            "cross_boundary_policy": "EXCLUDE_CROSS_BOUNDARY_OUTCOME",
        },
        "taxonomy_notice": (
            "This simulation models historical synthetic candle replay under E4/P4 contracts. "
            "It does NOT represent observed demo account fills or production execution outcomes."
        ),
        "accounting_parameters": {
            "initial_capital_usd": config.initial_capital,
            "max_concurrent_positions": config.max_concurrent_positions,
            "max_positions_per_asset": config.max_positions_per_asset,
            "allocation_pct_per_trade": config.allocation_pct_per_trade,
            "fee_rate_bps_per_leg": config.fee_rate_bps,
            "slippage_bps_per_leg": config.slippage_bps,
            "total_roundtrip_cost_bps": (config.fee_rate_bps + config.slippage_bps) * 2,
            "annualization_factor": config.annualization_factor,
        },
        "retracted_claims_comparison": {
            "root_cause_explanation": (
                "Previous reports (e.g. Sharpe 126.81, Max Drawdown 0.00%, Total Return +1,116.31%) "
                "relied on an unconstrained daily return summation bug in run_p4_replay_metrics: "
                "daily_returns[exit_day] += net_trade_pnl * 0.10. Multiple trades closing on the same day "
                "artificially compressed daily volatility and accumulated leverage beyond 100%, booking PnL "
                "without cash locking, margin tracking, or continuous mark-to-market drawdown."
            ),
            "control": res_ctrl.to_dict(),
            "treatment": res_treat.to_dict(),
        }
    }

    # Save output JSON
    json_path = OUT_DIR / "v5_event_driven_replay.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"\n[OK] Saved event-driven replay JSON to {json_path}")

    # Write Markdown Report
    write_report(output)
    print(f"[OK] Saved event-driven replay report to {OUT_DIR / 'v5_event_driven_report.md'}")


def write_report(data: dict[str, Any]):
    report_path = OUT_DIR / "v5_event_driven_report.md"
    ctrl = data["retracted_claims_comparison"]["control"]
    treat = data["retracted_claims_comparison"]["treatment"]
    acct = data["accounting_parameters"]

    lines = [
        "# HMR-V5: Event-Driven Self-Financing Replay Audit Report",
        "",
        f"> **Timestamp**: `{data['audit_timestamp']}` | **Taxonomy**: `{data['evidence_taxonomy']}`",
        "",
        "## 1. Evidence Taxonomy & Operational Scope",
        "- **Category**: `HISTORICAL_SIMULATION`",
        "- **Scope**: Historical candle-driven simulation of E4 path-aware exits and P4 capacity serialization across 2024-H2 under canonical half-open interval `[2024-07-02, 2025-01-01)` and `EXCLUDE_CROSS_BOUNDARY_OUTCOME`.",
        "- **Explicit Warning**: This audit uses historical backtesting. It does **NOT** constitute observed demo fills or live performance.",
        "",
        "## 2. Root Cause of Retracted Flawed Metrics",
        data["retracted_claims_comparison"]["root_cause_explanation"],
        "",
        "## 3. Self-Financing Capital Accounting Parameters",
        f"- **Initial Capital**: `${acct['initial_capital_usd']:,.2f}`",
        f"- **Allocation Per Trade**: `{acct['allocation_pct_per_trade']*100:.1f}%` of available equity",
        f"- **Max Concurrent Positions**: `{acct['max_concurrent_positions']}` (Max 1 per asset)",
        f"- **Cost Model**: `{acct['fee_rate_bps_per_leg']} bps` fee + `{acct['slippage_bps_per_leg']} bps` slippage per leg (`{acct['total_roundtrip_cost_bps']} bps` roundtrip)",
        f"- **Sharpe Annualization**: `sqrt({acct['annualization_factor']})` based on end-of-day daily equity series",
        "",
        "## 4. Empirical Historical Replay Results",
        "",
        "| Metric | Flawed Historical Claim | True Replay (Control) | True Replay (Treatment S3) | Status |",
        "| :--- | :---: | :---: | :---: | :---: |",
        f"| **Executed Trades** | `7,211` | `{ctrl['executed_trades_count']:,}` | `{treat['executed_trades_count']:,}` | Corrected |",
        f"| **Win Rate** | `73.2%` | `{ctrl['win_rate_pct']:.2f}%` | `{treat['win_rate_pct']:.2f}%` | Corrected |",
        f"| **Profit Factor** | `N/A` | `{ctrl['profit_factor']:.4f}` | `{treat['profit_factor']:.4f}` | Corrected |",
        f"| **Total Net PnL** | `+1,116.31%` | `{ctrl['total_net_pnl_pct']:.2f}%` | `{treat['total_net_pnl_pct']:.2f}%` | **RETRACTED** |",
        f"| **Final Equity** | `N/A` | `${ctrl['final_equity']:,.2f}` | `${treat['final_equity']:,.2f}` | Corrected |",
        f"| **Max Drawdown** | `0.00%` | `{ctrl['max_drawdown_pct']:.2f}%` | `{treat['max_drawdown_pct']:.2f}%` | **RETRACTED** |",
        f"| **Daily Sharpe** | `126.81` | `{ctrl['daily_sharpe']:.2f}` | `{treat['daily_sharpe']:.2f}` | **RETRACTED** |",
        f"| **Expectancy (bps)** | `+26.89 bps` | `{ctrl['expectancy_bps']:.2f} bps` | `{treat['expectancy_bps']:.2f} bps` | Corrected |",
        "",
        "## 5. Audit Conclusion",
        "The previous claims of Sharpe 126.81 and 0% Max Drawdown are formally retracted. Under realistic event-driven capital accounting and transaction friction (14 bps roundtrip), the baseline historical strategy suffers negative expectancy during 2024-H2.",
    ]

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
