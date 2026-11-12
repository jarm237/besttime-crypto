"""Unit and economic accounting tests for N1.4 Greenfield Economic-First Alpha Discovery."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from neural_trading.n1_4.acquisition import N1_4_SYMBOLS, QUARTERLY_EXPIRIES
from neural_trading.n1_4.falsification import (
    build_h1_simple_carry_weights,
    simulate_quarterly_carry_portfolio,
)
from neural_trading.n1_4.neural_pilot import H1_FEATURE_COLS, TermStructureCarryPolicy


def test_n1_4_expiry_calendar_and_governance_bounds() -> None:
    """Verify quarterly delivery expiry calendar and 2025-12-31 governance cutoff."""
    assert len(QUARTERLY_EXPIRIES) == 17
    exp_map = {code: iso for code, iso, _ in QUARTERLY_EXPIRIES}
    assert exp_map["220325"] == "2022-03-25T08:00:00Z"
    assert exp_map["251226"] == "2025-12-26T08:00:00Z"
    assert exp_map["260327"] == "2026-03-27T08:00:00Z"
    assert len(N1_4_SYMBOLS) == 8


def test_n1_4_coinm_1x_carry_telescoping_and_five_term_bridge() -> None:
    """Verify 1x COIN-M Dated Quarterly Carry telescoping math and $0.00 5-term bridge residual."""
    n_bars = 240
    ts_idx = pd.date_range("2024-01-01 00:00:00", periods=n_bars, freq="1h", tz="UTC")
    hours_ms = (ts_idx.astype("int64") // 10**6).to_numpy()
    rows = []
    for s_idx, sym in enumerate(N1_4_SYMBOLS):
        spot_0 = 40000.0 if s_idx == 0 else 2500.0
        b_start = 0.0150 if s_idx == 0 else 0.0020  # Symbol 0 has +150 bps contango (> 75 bps entry)
        for t in range(n_bars):
            spot_t = spot_0 * (1.0 + 0.10 * np.sin(t / 15.0) + 0.0005 * t)
            spot_next = spot_0 * (1.0 + 0.10 * np.sin((t + 1) / 15.0) + 0.0005 * (t + 1))
            b_t = max(0.0, b_start * (1.0 - t / float(n_bars - 10)))
            b_next = max(0.0, b_start * (1.0 - (t + 1) / float(n_bars - 10)))

            carry_ret_1h = (1.0 + b_t) / (1.0 + b_next) - 1.0
            spot_ret_1h = float(np.log(spot_next / spot_t))
            ttm_h = max(2.0, (45.0 * 24.0) - t)
            ann_y_pct = (b_t * 100.0) * (365.25 / (ttm_h / 24.0))

            rows.append(
                {
                    "hour_close_ms": int(hours_ms[t]),
                    "symbol": sym,
                    "spot_close": spot_t,
                    "spot_low": spot_t * 0.99,
                    "spot_ret_1h": spot_ret_1h,
                    "f1_high": spot_t * (1.0 + b_t) * 1.01,
                    "f1_notional_usd": 50_000_000.0,
                    "f1_ttm_hours": ttm_h,
                    "f1_basis_bps": b_t * 1e4,
                    "f1_basis_ma24_bps": b_t * 1e4,
                    "f1_implied_yield_ann_pct": ann_y_pct,
                    "f1_yield_ma24_pct": ann_y_pct,
                    "f1_carry_ret_1h": carry_ret_1h,
                    "f1_settling_next_hour": 1 if t == n_bars - 10 else 0,
                    "f1_entry_open_slippage_bps": 1.5,
                }
            )

    df = pd.DataFrame(rows)
    w_df = build_h1_simple_carry_weights(df, rebalance_every_hours=24, entry_basis_bps=75.0, exit_basis_bps=15.0)
    res = simulate_quarterly_carry_portfolio(df, w_df, pair_cost_per_leg_bps=11.0, latency_mode="close_t")

    assert abs(res["reconciliation_residual_usd"]) < 1e-6
    assert res["net_pnl_usd"] > 0.0
    assert res["gross_pnl_usd"] > res["transaction_friction_paid"]
    assert abs(res["empirical_beta_vs_btc"]) < 0.05
    assert res["tail_risk"]["margin_liquidation_events"] == 0


def test_n1_4_neural_policy_simplex_and_deterministic_masking() -> None:
    """Verify TermStructureCarryPolicy respects max weight, cash reserve, and active/contango masks."""
    policy = TermStructureCarryPolicy(n_features=len(H1_FEATURE_COLS), hidden_dim=24, max_single_weight=0.35)
    policy.eval()

    x_t = torch.randn(8, len(H1_FEATURE_COLS))
    active_mask = torch.tensor([1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=torch.float32)
    contango_mask = torch.tensor([1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=torch.float32)
    w_prev = torch.zeros(8, dtype=torch.float32)

    with torch.no_grad():
        w_new = policy.forward_step(x_t, active_mask, contango_mask, w_prev)

    assert w_new.shape == (8,)
    # Inactive or non-contango symbols must have strictly zero weight
    assert torch.all(w_new[2:] == 0.0)
    # Active symbols must not exceed max_single_weight (0.35)
    assert torch.all(w_new <= 0.35 + 1e-6)
    assert torch.all(w_new >= 0.0)
    assert float(w_new.sum().item()) <= 1.0 + 1e-6


def test_n1_4_deliverables_and_results_contract() -> None:
    """Verify N1.4 markdown reports, manifest, and economic results JSON exist and satisfy contracts."""
    root = Path(__file__).resolve().parents[1]
    rep1 = root / "docs" / "research" / "NEURAL_N1_4_ECONOMIC_MECHANISM_DISCOVERY.md"
    rep2 = root / "docs" / "research" / "NEURAL_N1_4_DATA_FEASIBILITY.md"
    rep3 = root / "docs" / "research" / "NEURAL_N1_4_POST_COST_HYPOTHESIS_EVALUATION.md"
    manifest_p = root / "research" / "neural_n1_4" / "manifests" / "n1_4_quarterly_delivery_manifest.json"
    results_p = root / "research" / "neural_n1_4" / "n1_4_economic_discovery_results.json"

    assert rep1.exists(), f"Missing {rep1}"
    assert rep2.exists(), f"Missing {rep2}"
    assert rep3.exists(), f"Missing {rep3}"
    assert manifest_p.exists(), f"Missing {manifest_p}"
    assert results_p.exists(), f"Missing {results_p}"

    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    assert manifest["hard_end_utc"] == "2025-12-31T23:00:00Z"
    assert manifest["verified_delivery_archives_count"] > 400
    assert manifest["pit_contract"]["lookahead_rows_count"] == 0

    results = json.loads(results_p.read_text(encoding="utf-8"))
    assert results["phase_a_n1_3_closure"]["H_B_POST_COST_DISPOSITION"] == "REJECTED"
    assert results["phase_g_research_decision"]["prospective_collector"] == "STOPPED"
    assert results["phase_g_research_decision"]["real_trading"] == "DISABLED"
    h1_full = results["phase_e_economic_falsification"]["results"]["h1_quarterly_delivery_carry"]["full_2022_2025"][
        "simple_carry_by_latency"
    ]["close_t"]
    assert abs(h1_full["reconciliation_residual_usd"]) < 1e-5
