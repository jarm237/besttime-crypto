from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from neural_trading.n1_2.discovery import build_cash_weights
from neural_trading.n1_3.phase_a_reconciliation import (
    AGGTRADES_SEMANTIC_DEFINITIONS,
    FEATURE_RENAME_MAP_N1_2_TO_N1_3,
    compute_exact_gross_net_bridge,
)
from neural_trading.n1_3.phase_b_quote_basis import build_quote_normalized_hb_panel


def test_n1_3_phase_a1_aggtrades_semantics_and_rename_map() -> None:
    assert set(AGGTRADES_SEMANTIC_DEFINITIONS.keys()) == {
        "aggregate_trade_events",
        "underlying_execution_matches",
        "unique_resting_orders",
        "multi_price_level_sweeps",
    }
    assert AGGTRADES_SEMANTIC_DEFINITIONS["unique_resting_orders"]["observable_in_aggtrades"] == (
        "UNOBSERVABLE_WITHOUT_L3_ORDER_ID"
    )
    assert FEATURE_RENAME_MAP_N1_2_TO_N1_3["underlying_order_count"] == "underlying_execution_match_count"
    assert FEATURE_RENAME_MAP_N1_2_TO_N1_3["ha_sweep_intensity_z"] == "ha_same_price_match_fragmentation_z"


def test_n1_3_phase_a2_exact_gross_net_bridge_zero_residual() -> None:
    rng = np.random.default_rng(123)
    hours = [1704067200000 + h * 3600000 for h in range(48)]
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    rows = []
    for h in hours:
        for s in symbols:
            rows.append(
                {
                    "symbol": s,
                    "hour_close_ms": h,
                    "fwd_ret_1h": float(rng.normal(0.0005, 0.01)),
                }
            )
    df = pd.DataFrame(rows)
    w_df = build_cash_weights(df).copy()
    for idx, h in enumerate(w_df.index):
        if idx % 4 == 0:
            w_df.loc[h, "BTCUSDT"] = 0.30 if (idx // 4) % 2 == 0 else 0.05
            w_df.loc[h, "ETHUSDT"] = 0.20 if (idx // 4) % 2 == 1 else 0.10
            w_df.loc[h, "SOLUSDT"] = 0.15

    bridge = compute_exact_gross_net_bridge(df, w_df, cost_per_leg_bps=7.0, initial_capital=20_000.0)
    assert abs(bridge["reconciliation_residual_same_path_usd"]) < 1e-6
    assert abs(bridge["reconciliation_residual_full_bridge_usd"]) < 1e-6
    assert np.isclose(
        bridge["realized_net_pnl"],
        bridge["gross_pnl_same_executed_path"] - bridge["transaction_friction_paid"],
        atol=0.02,
    )
    assert np.isclose(
        bridge["gross_pnl_same_executed_path"],
        bridge["zero_friction_counterfactual_pnl"] + bridge["capital_path_effect"],
        atol=0.02,
    )


def test_n1_3_phase_b_quote_normalization_math() -> None:
    hours = [1704067200000 + h * 3600000 for h in range(60)]
    symbols = ["BTCUSDT", "ETHUSDT"]
    cb_rows = []
    bn_rows = []
    usdt_rows = []
    for idx, h in enumerate(hours):
        # USDT trades at a -10 bps discount (0.9990 USD)
        usdt_close = 0.9990 + 0.0001 * np.sin(idx / 5.0)
        usdt_rows.append(
            {
                "hour_close_ms": h,
                "cb_open": usdt_close,
                "cb_high": usdt_close * 1.0002,
                "cb_low": usdt_close * 0.9998,
                "cb_close": usdt_close,
                "cb_notional_usd": 1000000.0,
            }
        )
        for s_idx, s in enumerate(symbols):
            bn_close = 100.0 * (1.0 + 0.001 * idx + 0.0005 * s_idx)
            # True USD-equivalent price on Coinbase is +2 bps above bn_close * usdt_close for BTC, -2 bps for ETH
            cb_close = bn_close * usdt_close * (1.0 + 0.0002 * (1 if s_idx == 0 else -1))
            cb_rows.append(
                {
                    "symbol": s,
                    "hour_close_ms": h,
                    "open_sec": (h // 1000) - 3600,
                    "cb_open": cb_close,
                    "cb_high": cb_close * 1.001,
                    "cb_low": cb_close * 0.999,
                    "cb_close": cb_close,
                    "cb_notional_usd": 500000.0,
                }
            )
            bn_rows.append(
                {
                    "symbol": s,
                    "hour_close_ms": h,
                    "spot_open": bn_close,
                    "spot_close": bn_close,
                    "spot_quote_vol": 1000000.0,
                }
            )
    cb_df = pd.DataFrame(cb_rows)
    bn_df = pd.DataFrame(bn_rows)
    usdt_df = pd.DataFrame(usdt_rows)
    panel = build_quote_normalized_hb_panel(cb_df, bn_df, usdt_df)

    btc_row = panel[panel["symbol"] == "BTCUSDT"].iloc[30]
    eth_row = panel[panel["symbol"] == "ETHUSDT"].iloc[30]
    assert np.isclose(btc_row["quote_currency_adjusted_premium_bps"], 2.0, atol=1e-4)
    assert np.isclose(eth_row["quote_currency_adjusted_premium_bps"], -2.0, atol=1e-4)


def test_n1_3_deliverables_and_governance_verdict() -> None:
    root = Path(__file__).resolve().parents[1]
    res_path = root / "research" / "neural_n1_3" / "n1_3_executable_cross_venue_edge_results.json"
    doc_path = root / "docs" / "research" / "NEURAL_N1_3_EXECUTABLE_CROSS_VENUE_EDGE.md"
    assert res_path.exists()
    assert doc_path.exists()

    payload = json.loads(res_path.read_text(encoding="utf-8"))
    gate = payload["phase_e_decision_gate"]
    assert gate["primary_decision_gate_outcome"] == "H_B_REJECTED_POST_COST"
    assert gate["historical_l1_execution_data_status"] == "H_B_EXECUTION_DATA_INSUFFICIENT"
    assert gate["bounded_neural_experiment_authorized"] is False
    assert gate["prospective_collector"] == "STOPPED"
    assert gate["real_trading"] == "DISABLED"
