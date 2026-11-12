"""
tests/test_neural_n1.py

Unit tests for the N1 Independent Market Information Discovery & Unified Neural
Research package (`neural_trading.n1`).
"""
from __future__ import annotations

import numpy as np
import torch

from neural_trading.n1.pit_dataset import _open_time_to_avail_sec
from neural_trading.n1.model import CrossSectionalMarketPolicy
from neural_trading.n1.experiment import (
    enforce_external_hard_risk,
    simulate_step_policy,
)


def test_pit_open_time_ms_and_us_epoch_handling() -> None:
    # 2024-01-01 00:00:00 UTC in milliseconds (13 digits) -> available at 01:00:00 UTC
    ms_open = 1704067200_000
    assert _open_time_to_avail_sec(ms_open) == 1704067200 + 3600

    # 2025-01-01 00:00:00 UTC in microseconds (16 digits) -> available at 01:00:00 UTC
    us_open = 1735689600_000_000
    assert _open_time_to_avail_sec(us_open) == 1735689600 + 3600


def test_external_hard_risk_and_delisting_mask() -> None:
    # 4 assets, asset index 2 is inactive (delisted)
    active_t = np.array([True, True, False, True], dtype=bool)
    # Propose 0% cash, 60% in asset 0, 20% in asset 1, 20% in inactive asset 2
    w_prop = np.array([0.0, 0.60, 0.20, 0.20, 0.0], dtype=np.float64)
    w_proj = enforce_external_hard_risk(w_prop, active_t, min_cash=0.05, max_asset=0.35)

    assert np.isclose(np.sum(w_proj), 1.0)
    assert w_proj[0] >= 0.05 - 1e-9
    assert np.all(w_proj[1:] <= 0.35 + 1e-9)
    assert w_proj[3] == 0.0  # inactive asset index 2 (position 3 in [cash, a0, a1, a2, a3])


def test_cross_sectional_market_policy_masking_and_parity() -> None:
    torch.manual_seed(7)
    B, N, d_a, d_m = 4, 6, 11, 9
    model = CrossSectionalMarketPolicy(
        asset_feat_dim=d_a,
        market_feat_dim=d_m,
        embed_dim=16,
        num_heads=4,
        deadband_oneway=0.06,
    )
    asset_x = torch.randn(B, N, d_a)
    market_x = torch.randn(B, d_m)
    active_mask = torch.ones(B, N, dtype=torch.bool)
    # Mark last two assets as inactive
    active_mask[:, 4:] = False

    # Suppose w_curr held some weight on asset 4 which just delisted
    w_curr = torch.zeros(B, N + 1)
    w_curr[:, 0] = 0.20
    w_curr[:, 1] = 0.30
    w_curr[:, 2] = 0.30
    w_curr[:, 5] = 0.20  # asset 4 (index 5 in w_curr)

    model.eval()
    w_eff, w_cand, step_gate = model(asset_x, market_x, active_mask, w_curr)

    assert w_eff.shape == (B, N + 1)
    assert torch.allclose(w_eff.sum(dim=-1), torch.ones(B), atol=1e-5)
    assert torch.allclose(w_cand.sum(dim=-1), torch.ones(B), atol=1e-5)
    # Inactive assets must have strictly zero weight in both w_cand and w_eff
    assert torch.all(w_cand[:, 5:] == 0.0)
    assert torch.all(w_eff[:, 5:] == 0.0)
    assert torch.all((step_gate >= 0.0) & (step_gate <= 1.0))


def test_simulate_step_policy_brinson_identity_and_cost_scaling() -> None:
    rng = np.random.default_rng(123)
    K, N = 40, 5
    fwd_ret = rng.normal(0.001, 0.02, size=(K, N))
    active_seq = np.ones((K, N), dtype=bool)
    # Delist asset 4 halfway through
    active_seq[20:, 4] = False

    target_weights = np.zeros((K, N + 1), dtype=np.float64)
    target_weights[:, 0] = 0.20
    target_weights[:20, 1:] = 0.80 / 5.0
    target_weights[20:, 1:5] = 0.80 / 4.0
    is_hold = np.zeros(K, dtype=bool)
    is_hold[1:19] = True
    is_hold[21:] = True

    res_14 = simulate_step_policy(
        target_weights, is_hold, fwd_ret, active_seq,
        horizon_h=12, initial_capital=20_000.0, cost_per_leg_bps=7.0,
    )
    res_28 = simulate_step_policy(
        target_weights, is_hold, fwd_ret, active_seq,
        horizon_h=12, initial_capital=20_000.0, cost_per_leg_bps=14.0,
    )

    # Brinson identity: timing + selection == gross_excess_vs_matched (up to rounding)
    lhs = res_14["timing_value_pct"] + res_14["asset_selection_value_pct"]
    rhs = res_14["gross_excess_vs_matched_pct"]
    assert abs(lhs - rhs) <= 0.03

    # 28 bps RT must incur ~2x transaction cost and lower net PnL than 14 bps RT
    assert res_28["transaction_cost_usd"] > res_14["transaction_cost_usd"] * 1.95
    assert res_28["net_pnl_usd"] < res_14["net_pnl_usd"]


def test_carino_geometric_reconciliation_identity() -> None:
    from neural_trading.n1.attribution import (
        trace_detailed_ledger,
        reconcile_portfolio_and_brinson,
    )

    rng = np.random.default_rng(99)
    K, N = 50, 4
    fwd_ret = rng.normal(0.002, 0.025, size=(K, N))
    active_seq = np.ones((K, N), dtype=bool)

    w_neural = np.zeros((K, N + 1), dtype=np.float64)
    w_neural[:, 0] = 0.12
    w_neural[:, 1] = 0.35
    w_neural[:, 2] = 0.30
    w_neural[:, 3] = 0.13
    w_neural[:, 4] = 0.10
    hold_neural = np.zeros(K, dtype=bool)

    w_match = np.zeros((K, N + 1), dtype=np.float64)
    w_match[:, 0] = 0.12
    w_match[:, 1:] = 0.88 / N
    hold_match = np.ones(K, dtype=bool)
    hold_match[0] = False

    n_trace = trace_detailed_ledger(w_neural, hold_neural, fwd_ret, active_seq)
    m_trace = trace_detailed_ledger(w_match, hold_match, fwd_ret, active_seq)

    recon = reconcile_portfolio_and_brinson(n_trace, m_trace, m_trace, fwd_ret, active_seq)
    car = recon["carino_geometric_reconciliation_vs_matched_bnh"]

    assert car["step_identity_max_abs_err"] < 1e-12
    assert abs(car["sum_of_components_pct"] - car["exact_direct_net_return_diff_pct"]) <= 0.03
    assert recon["direct_net_pnl_diff_vs_matched_bnh_usd"] == round(
        recon["neural_net_pnl_usd"] - recon["matched_bnh_net_pnl_usd"], 2
    )
