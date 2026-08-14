import importlib.util
import sys
from pathlib import Path

import pandas as pd


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "hmr_v1_baseline.py"
    spec = importlib.util.spec_from_file_location("hmr_v1_baseline", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_sanitize_signals_removes_future_outcome_fields():
    module = _load_module()
    signals = pd.DataFrame([
        {
            "coin": "BTC",
            "entry_time": "2025-01-01 00:00",
            "signal_raw": "BUY",
            "return_15m": 0.1,
            "result": "TP",
        }
    ])

    sanitized, report = module.sanitize_signals(signals)

    assert "return_15m" not in sanitized.columns
    assert "result" not in sanitized.columns
    assert report["future_outcome_fields_removed"] == 2


def test_no_lookahead_gate_rejects_missing_closed_bar():
    module = _load_module()
    signals = [{"coin": "BTC", "entry_time": "2025-01-01 00:15:00", "signal_raw": "BUY"}]
    candles = {"BTC": [{"time": "2025-01-01 00:00:00"}]}

    gate = module.no_lookahead_gate(signals, candles, "15m")

    assert gate["status"] == "FAIL"
    assert gate["missing_closed_bar_count"] == 1


def test_replay_parity_counts_market_clock_not_signal_timestamps():
    module = _load_module()
    signals = [{"coin": "BTC", "entry_time": "2025-01-01 00:15:00", "signal_raw": "BUY"}]
    candles = {
        "BTC": [
            {"time": f"2025-01-01 00:{minute:02d}:00"}
            for minute in (0, 15, 30, 45)
        ]
    }

    gate = module.replay_parity_gate(
        signals,
        candles,
        ["BTC"],
        "15m",
        pd.Timestamp("2025-01-01 00:00:00", tz="UTC"),
        pd.Timestamp("2025-01-01 00:45:00", tz="UTC"),
    )

    assert gate["expected_cycle_count"] == 4
    assert gate["actual_cycle_count"] == 4
    assert gate["signal_cycle_count"] == 1
    assert gate["symbol_accounting"]["BTC"]["status"] == "PASS"
    assert gate["production_policy_path"]["status"] == "FAIL"
    assert gate["status"] == "FAIL"


def test_accounting_gate_reconciles_execution_prices_without_double_debiting_slippage():
    module = _load_module()
    result = {
        "trades": [{"coin": "BTC", "gross_pnl": 12.0, "fee_paid": 2.0, "pnl": 10.0}],
        "metrics": {
            "opening_balance": 1000.0,
            "ending_cash": 1010.0,
            "ending_equity": 1010.0,
            "realized_net_pnl": 10.0,
            "unrealized_pnl": 0.0,
            "open_position_count": 0,
            "open_quantity": 0.0,
        },
    }

    gate = module.accounting_gate(result, tolerance=1e-9)

    assert gate["status"] == "PASS"
    assert gate["trade_reconciliation"]["status"] == "PASS"
    assert gate["identity_residual"] == 0.0


def test_policy_contract_rejects_noncanonical_directional_entry():
    module = _load_module()
    rows = [
        {
            "time": "2025-01-01 00:00:00",
            "coin": "BTC",
            "canonical_action": "HOLD",
            "final_action": "SELL",
        },
        {
            "time": "2025-01-01 00:15:00",
            "coin": "ETH",
            "canonical_action": "SELL",
            "final_action": "SELL",
        },
    ]

    mismatches = module._policy_contract_mismatches(rows)

    assert mismatches == [{
        "time": "2025-01-01 00:00:00",
        "coin": "BTC",
        "canonical_action": "HOLD",
        "final_action": "SELL",
    }]
