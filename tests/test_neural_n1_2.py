"""Unit and contract tests for N1.2 Independent Alpha Mechanism Discovery & PIT Acquisition."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from neural_trading.n1_2.acquisition import MANDATORY_PROVENANCE_FIELDS
from neural_trading.n1_2.discovery import (
    _newey_west_tstat,
    build_cash_weights,
    build_ha_features_and_targets,
    build_passive_equal_weight,
    build_simple_hypothesis_baseline_weights,
    simulate_spot_long_only_portfolio,
)
from neural_trading.n1_2.experiment import MicrostructureDislocationPolicy

ROOT = Path(__file__).resolve().parents[1]


def test_n1_2_mandatory_provenance_fields_contract() -> None:
    expected = {
        "source",
        "original_timestamp",
        "actual_availability_timestamp",
        "ingestion_timestamp",
        "raw_payload",
        "source_checksum",
        "local_sha256",
        "trading_eligibility",
        "missing_intervals",
        "execution_constraints",
    }
    assert set(MANDATORY_PROVENANCE_FIELDS) == expected


def test_n1_2_ha_feature_builder_strictly_causal() -> None:
    rng = np.random.default_rng(7)
    hours = np.arange(0, 300) * 3_600_000 + 1_650_000_000_000
    rows = []
    for sym in ["LINKUSDT", "ADAUSDT"]:
        price = 10.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, size=len(hours))))
        for h_ms, p in zip(hours, price):
            rows.append(
                {
                    "symbol": sym,
                    "hour_close_ms": int(h_ms),
                    "open_price": float(p * 0.998),
                    "high_price": float(p * 1.005),
                    "low_price": float(p * 0.995),
                    "close_price": float(p),
                    "agg_trade_count": 1000.0,
                    "underlying_order_count": 1850.0,
                    "total_notional": 500_000.0,
                    "buy_notional": 260_000.0,
                    "sell_notional": 240_000.0,
                    "whale_buy_notional": 90_000.0,
                    "whale_sell_notional": 70_000.0,
                    "retail_buy_notional": 40_000.0,
                    "retail_sell_notional": 50_000.0,
                    "buy_sweep_orders": 1000.0,
                    "sell_sweep_orders": 850.0,
                    "multi_fill_buy_notional": 120_000.0,
                    "multi_fill_sell_notional": 95_000.0,
                    "bounce_spread_bps_sum": 600.0,
                    "flip_count": 400.0,
                    "buy_impact_bps_sum": 300.0,
                    "sell_impact_bps_sum": 250.0,
                    "cont_buy_count": 300.0,
                    "cont_sell_count": 300.0,
                }
            )
    panel = pd.DataFrame(rows)
    df1 = build_ha_features_and_targets(panel)

    # Perturb future rows after bar 200 and verify causal features at bar <= 200 are identical
    panel_perturbed = panel.copy()
    cutoff_ms = int(hours[200])
    mask_future = panel_perturbed["hour_close_ms"] > cutoff_ms
    panel_perturbed.loc[mask_future, "whale_buy_notional"] *= 5.0
    panel_perturbed.loc[mask_future, "close_price"] *= 2.5
    df2 = build_ha_features_and_targets(panel_perturbed)

    past1 = df1[df1["hour_close_ms"] <= cutoff_ms]
    past2 = df2[df2["hour_close_ms"] <= cutoff_ms]
    for col in ["ha_whale_ofi", "ha_whale_minus_retail", "ha_signed_sweep_imb", "ha_multifill_ofi"]:
        np.testing.assert_allclose(past1[col].to_numpy(), past2[col].to_numpy(), rtol=1e-12, atol=1e-12)


def test_n1_2_spot_simulator_accounting_and_long_only_bounds() -> None:
    hours = np.arange(0, 48) * 3_600_000 + 1_700_000_000_000
    rows = []
    for sym in ["LINKUSDT", "ADAUSDT", "XLMUSDT"]:
        for h_ms in hours:
            rows.append(
                {
                    "symbol": sym,
                    "hour_close_ms": int(h_ms),
                    "fwd_ret_1h": 0.001,
                    "ha_realized_bounce_spread_bps": 1.2,
                    "score": 2.5 if sym == "LINKUSDT" else -0.5,
                }
            )
    df = pd.DataFrame(rows)
    w_cash = build_cash_weights(df)
    sim_cash = simulate_spot_long_only_portfolio(df, w_cash, cost_per_leg_bps=7.0)
    assert sim_cash["net_pnl_usd"] == 0.0
    assert sim_cash["realized_execution_cost_usd"] == 0.0

    w_simple = build_simple_hypothesis_baseline_weights(df, score_col="score", rebalance_every_h=12, max_weight_per_asset=0.35)
    assert (w_simple.to_numpy() >= 0.0).all()
    assert (w_simple.to_numpy() <= 0.35 + 1e-9).all()
    assert (w_simple.sum(axis=1).to_numpy() <= 1.0 + 1e-9).all()

    sim_simple = simulate_spot_long_only_portfolio(
        df, w_simple, cost_per_leg_bps=7.0, extra_half_spread_col="ha_realized_bounce_spread_bps"
    )
    assert sim_simple["realized_execution_cost_usd"] > 0.0
    assert sim_simple["gross_pnl_usd"] > sim_simple["net_pnl_usd"]


def test_n1_2_microstructure_dislocation_policy_constraints() -> None:
    policy = MicrostructureDislocationPolicy(n_features=6, n_assets=5, max_weight=0.35)
    x_t = torch.randn(5, 6)
    prev_w = torch.zeros(5)
    new_w, raw_scores = policy.forward_step(x_t, prev_w)
    assert new_w.shape == (5,)
    assert raw_scores.shape == (5,)
    assert torch.all(new_w >= 0.0)
    assert torch.all(new_w <= 0.35 + 1e-6)
    assert float(new_w.sum().item()) <= 1.0 + 1e-6


def test_n1_2_manifests_and_deliverables_exist_and_comply() -> None:
    manifest_dir = ROOT / "research" / "neural_n1_2" / "manifests"
    for fname in [
        "n1_2_aggtrades_manifest.json",
        "n1_2_coinbase_cross_venue_manifest.json",
        "n1_2_5m_perp_spot_manifest.json",
    ]:
        fpath = manifest_dir / fname
        assert fpath.exists(), f"Missing manifest {fname}"
        data = json.loads(fpath.read_text(encoding="utf-8"))
        assert data.get("records"), f"Empty records in {fname}"
        sample_rec = data["records"][0]
        for field in MANDATORY_PROVENANCE_FIELDS:
            assert field in sample_rec, f"Missing {field} in {fname}"

    for doc_name in [
        "NEURAL_N1_2_ALPHA_MECHANISM_DISCOVERY.md",
        "NEURAL_N1_2_FRESH_DATA_AND_PIT_REPORT.md",
        "NEURAL_N1_2_ECONOMIC_FEASIBILITY.md",
    ]:
        doc_path = ROOT / "docs" / "research" / doc_name
        assert doc_path.exists(), f"Missing deliverable {doc_name}"

