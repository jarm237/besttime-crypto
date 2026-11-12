"""Unit and economic accounting tests for N1.5 COIN-M Quarterly Carry Reality Check."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from neural_trading.n1_4.acquisition import N1_4_SYMBOLS
from neural_trading.n1_5.coinm_simulator import simulate_h1_coinm_reality_check
from neural_trading.n1_5.contract_specs_and_data import (
    COINM_CONTRACT_SPECS,
    FEE_SCENARIOS,
)

MANDATORY_PHASE_A_LEDGER_FIELDS = [
    "entry_spot_notional",
    "entry_spot_fee",
    "coin_acquired",
    "coin_transferred_as_collateral",
    "contract_size_usd",
    "contracts_short",
    "future_entry_price",
    "future_mark_price",
    "inverse_unrealized_pnl_coin",
    "margin_wallet_balance_coin",
    "maintenance_margin_coin",
    "margin_ratio",
    "delivery_settlement_index",
    "realized_pnl_coin",
    "delivery_fee_coin",
    "exit_spot_proceeds",
    "final_portfolio_equity_usd",
]


def test_n1_5_contract_specs_and_fee_governance() -> None:
    """Verify official COIN-M contract multipliers and BNB discount ineligibility on COIN-M."""
    assert COINM_CONTRACT_SPECS["BTCUSDT"].contract_size_usd == 100.0
    for sym in N1_4_SYMBOLS:
        if sym != "BTCUSDT":
            assert COINM_CONTRACT_SPECS[sym].contract_size_usd == 10.0
    # COIN-M futures settle fees in base coin and are ineligible for the 10% USD-M BNB discount
    for scen in FEE_SCENARIOS.values():
        assert scen.bnb_discount_applied_cm is False


def test_n1_5_inverse_coinm_ledger_and_zero_double_counting() -> None:
    """Verify physical COIN-M inverse contract simulation, 17 mandatory ledger fields, and $0.00 residual."""
    n_bars = 240
    ts_idx = pd.date_range("2024-01-01 00:00:00", periods=n_bars, freq="1h", tz="UTC")
    hours_ms = (ts_idx.astype("int64") // 10**6).to_numpy()
    rows = []
    for s_idx, sym in enumerate(N1_4_SYMBOLS):
        spot_0 = 50_000.0 if sym == "BTCUSDT" else 2_500.0
        b_start = 0.0180 if s_idx == 0 else 0.0020  # Symbol 0 (BTCUSDT) has +180 bps contango
        for t in range(n_bars):
            spot_t = spot_0 * (1.0 + 0.08 * np.sin(t / 18.0))
            spot_next = spot_0 * (1.0 + 0.08 * np.sin((t + 1) / 18.0))
            b_t = max(0.0, b_start * (1.0 - t / float(n_bars - 12)))
            fut_t = spot_t * (1.0 + b_t)
            fut_next = spot_next * (1.0 + max(0.0, b_start * (1.0 - (t + 1) / float(n_bars - 12))))
            ttm_h = max(1.0, (20.0 * 24.0) - t) if t < n_bars - 12 else 1.0
            ann_y_pct = (b_t * 100.0) * (365.25 / max(ttm_h / 24.0, 1.0))

            rows.append(
                {
                    "hour_close_ms": int(hours_ms[t]),
                    "symbol": sym,
                    "spot_close_usd": spot_t,
                    "spot_open_usd": spot_t,
                    "spot_low": spot_t * 0.99,
                    "usdt_usd_close": 1.0,
                    "spot_next_open_usd": spot_next,
                    "spot_ret_1h": float(np.log(spot_next / spot_t)),
                    "f1_contract": f"{sym[:3]}USD_240329",
                    "f1_expiry_code": "240329",
                    "f1_ttm_hours": ttm_h,
                    "f1_close": fut_t,
                    "f1_next_open_same": fut_next,
                    "f1_mark_close": fut_t,
                    "f1_mark_high": fut_t * 1.01,
                    "f1_notional_usd": 10_000_000.0,
                    "f1_basis_bps": b_t * 1e4,
                    "f1_basis_ma24_bps": b_t * 1e4,
                    "f1_yield_ma24_pct": ann_y_pct,
                    "f1_settling_next_hour": 1.0 if t == n_bars - 12 else 0.0,
                    "official_settlement_twap_30m_usd": spot_t,
                }
            )

    df = pd.DataFrame(rows)
    res = simulate_h1_coinm_reality_check(
        df,
        scenario=FEE_SCENARIOS["standard_retail_taker"],
        execution_mode="EXECUTABLE_TWAP_CONSTRAINED",
        initial_capital=20_000.0,
    )

    assert abs(res["reconciliation"]["ledger_reconciliation_residual_usd"]) < 1e-3
    assert res["reconciliation"]["double_counting_events"] == 0
    assert len(res["position_ledgers"]) >= 1
    first_ledger = res["position_ledgers"][0]
    for field_name in MANDATORY_PHASE_A_LEDGER_FIELDS:
        assert field_name in first_ledger, f"Missing mandatory ledger field: {field_name}"
    assert isinstance(first_ledger["contracts_short"], int)
    assert first_ledger["contracts_short"] >= 1
    assert first_ledger["coin_acquired"] == first_ledger["coin_transferred_as_collateral"]
    assert res["realized_net_pnl_usd"] > 0.0


def test_n1_5_deliverables_and_results_contract() -> None:
    """Verify N1.5 deliverable markdown report and results JSON exist and satisfy governance contracts."""
    root = Path(__file__).resolve().parents[1]
    report_p = root / "docs" / "research" / "NEURAL_N1_5_COIN_M_CARRY_REALITY_CHECK.md"
    results_p = root / "research" / "neural_n1_5" / "n1_5_coinm_reality_check_results.json"

    assert report_p.exists(), f"Missing {report_p}"
    assert results_p.exists(), f"Missing {results_p}"

    results = json.loads(results_p.read_text(encoding="utf-8"))
    assert results["phase_f_final_decision"]["final_h1_disposition"] in {
        "H1_CONTRACT_MODEL_INCORRECT",
        "H1_EXECUTION_DATA_INSUFFICIENT",
        "H1_REJECTED_AFTER_REALISTIC_COSTS",
        "H1_EXPLORATORY_NET_CARRY_SUPPORTED",
    }
    assert results["phase_f_final_decision"]["prospective_collector"] == "STOPPED"
    assert results["phase_f_final_decision"]["real_trading"] == "DISABLED"
    assert results["phase_f_final_decision"]["neural_incremental_value_disposition"] == "NEURAL_INCREMENTAL_VALUE_NOT_SUPPORTED"

    for scen_id in [
        "verified_historical_fee_schedule",
        "standard_retail_taker",
        "bnb_discount_if_eligible",
        "stressed_execution_cost",
    ]:
        assert scen_id in results["phase_e_modelled_net_carry_by_fee_scenario"]
        assert scen_id in results["phase_e_executable_net_carry_by_fee_scenario"]
        exec_run = results["phase_e_executable_net_carry_by_fee_scenario"][scen_id]
        assert abs(exec_run["reconciliation"]["ledger_reconciliation_residual_usd"]) < 1e-3
