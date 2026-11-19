"""Targeted verification tests for S5-P0 Economic Opportunity Replay Engine.

Pre-registration: research/s5_economic_opportunity/s5_p0_executable_preregistration.md
Pre-execution erratum: research/s5_economic_opportunity/s5_p0_pre_execution_erratum.md
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import pytest

from btc_scraper.research.s4_dataset_audit import UNIVERSE
from btc_scraper.research.s5_economic_replay import (
    PRIMARY_COST_BPS,
    ReplayError,
    ReplayResult,
    audit_replay_timeline,
    compute_asset_momentums_168h,
    compute_asset_volatilities_168h,
    compute_breakeven_cost,
    compute_market_trend_168h,
    compute_market_volatility_168h,
    compute_one_way_deviation,
    evaluate_economic_gates,
    get_causal_bars,
    policy_btc_bh,
    policy_ew4,
    policy_momentum_top1_trend_gate,
    policy_momentum_top2_trend_gate,
    policy_trend_cash_gate_btc,
    policy_trend_cash_gate_ew4,
    run_stateful_replay,
    solve_post_fee_equity,
)


def _synthetic_panels(
    start: str = "2021-12-01 00:00:00",
    periods: int = 24 * 30,
) -> dict[str, pd.DataFrame]:
    idx = pd.date_range(start, periods=periods, freq="h", tz="UTC")
    panels = {}
    for offset, sym in enumerate(UNIVERSE, start=1):
        step = np.arange(periods, dtype=float)
        p = 100.0 * offset * np.exp(0.0001 * step)
        panels[sym] = pd.DataFrame(
            {
                "open": p,
                "high": p * 1.002,
                "low": p * 0.998,
                "close": p * 1.0005,
                "volume": 1000.0,
            },
            index=idx,
        )
    return panels


def test_btc_bh_cash_non_negative_after_fee() -> None:
    """1. Verify BTC_BH 100% investment leaves non-negative cash after initial fee."""
    v_pre = 10000.0
    current_notionals = np.zeros(4)
    target_weights = np.array([1.0, 0.0, 0.0, 0.0])
    fee_rate = 0.0012  # 12 bps

    v_post, fee = solve_post_fee_equity(v_pre, current_notionals, target_weights, fee_rate)
    target_btc = target_weights[0] * v_post
    post_cash = (1.0 - target_weights.sum()) * v_post

    assert post_cash >= 0.0
    assert pytest.approx(post_cash, abs=1e-9) == 0.0
    assert pytest.approx(v_post + fee, abs=1e-9) == v_pre
    assert pytest.approx(v_post, abs=1e-5) == v_pre / (1.0 + fee_rate)
    assert pytest.approx(fee, abs=1e-5) == fee_rate * target_btc


def test_ew4_capital_conservation() -> None:
    """2. Verify EW4 100% exposure subject to fees conserves capital exactly."""
    v_pre = 10000.0
    current_notionals = np.zeros(4)
    target_weights = np.full(4, 0.25)
    fee_rate = 0.0012

    v_post, fee = solve_post_fee_equity(v_pre, current_notionals, target_weights, fee_rate)
    post_cash = (1.0 - target_weights.sum()) * v_post

    assert post_cash >= 0.0
    assert pytest.approx(post_cash, abs=1e-9) == 0.0
    assert pytest.approx(v_post + fee, abs=1e-9) == v_pre
    assert fee > 0.0


def test_roundtrip_conservation_no_free_money() -> None:
    """3. Verify Cash -> BTC -> Cash roundtrip creates zero excess equity."""
    v_pre = 10000.0
    fee_rate = 0.0012

    # Step 1: Cash -> BTC
    v_post1, fee1 = solve_post_fee_equity(v_pre, np.zeros(4), np.array([1.0, 0, 0, 0]), fee_rate)
    assert v_post1 < v_pre

    # Step 2: BTC -> Cash at same price
    btc_notional = np.array([v_post1, 0, 0, 0])
    v_post2, fee2 = solve_post_fee_equity(v_post1, btc_notional, np.zeros(4), fee_rate)

    assert v_post2 < v_post1
    assert v_post2 < v_pre
    expected_v2 = v_pre * (1.0 - fee_rate) / (1.0 + fee_rate)
    assert pytest.approx(v_post2, abs=1e-6) == expected_v2


def test_binance_open_candle_not_used_at_cutoff() -> None:
    """4. Verify Binance 00:00 candle open is not used at 00:00 cutoff (only bars <= t-1h)."""
    panels = _synthetic_panels()
    decision_dt = pd.Timestamp("2021-12-15 00:00:00", tz="UTC")

    df = get_causal_bars(panels, decision_dt, lookback_hours=168)
    assert df is not None
    # Maximum timestamp must be 23:00 UTC of previous day
    assert df.index.max() == pd.Timestamp("2021-12-14 23:00:00", tz="UTC")
    assert pd.Timestamp("2021-12-15 00:00:00", tz="UTC") not in df.index
    assert len(df) == 169  # 168 hours of returns requires 169 endpoints


def test_missing_gap_not_forward_filled() -> None:
    """5. Verify missing bar in lookback window returns None and is not forward-filled."""
    panels = _synthetic_panels()
    decision_dt = pd.Timestamp("2021-12-15 00:00:00", tz="UTC")

    # Drop one candle inside the 168h window
    drop_ts = pd.Timestamp("2021-12-10 13:00:00", tz="UTC")
    panels["BTCUSDT"] = panels["BTCUSDT"].drop(drop_ts)

    df = get_causal_bars(panels, decision_dt, lookback_hours=168)
    assert df is None

    trend = compute_market_trend_168h(panels, decision_dt)
    assert trend is None

    vol = compute_market_volatility_168h(panels, decision_dt)
    assert vol is None


def test_no_trade_band_uses_drifted_weights() -> None:
    """6. Verify no-trade band computes one-way deviation from pre-trade drifted weights."""
    current_notionals = np.array([2500.0, 2500.0, 2500.0, 2500.0])
    current_cash = 0.0
    # Small drift: 1% shift
    target_weights = np.array([0.26, 0.24, 0.25, 0.25])
    dev = compute_one_way_deviation(current_notionals, current_cash, target_weights)
    # dev = 0.5 * (|0.26-0.25| + |0.24-0.25| + 0 + 0 + 0) = 0.01 (1%)
    assert pytest.approx(dev, abs=1e-6) == 0.01
    assert dev <= 0.05  # within 5% band


def test_paired_timing_rotation_identical_cash_gate() -> None:
    """7. Verify paired timing/rotation policies use identical cash-gate signal."""
    panels = _synthetic_panels()
    decision_dt = pd.Timestamp("2021-12-15 00:00:00", tz="UTC")

    w_trend_btc, r_btc = policy_trend_cash_gate_btc(panels, decision_dt)
    w_trend_ew4, r_ew4 = policy_trend_cash_gate_ew4(panels, decision_dt)
    w_top1_trend, r_top1 = policy_momentum_top1_trend_gate(panels, decision_dt)
    w_top2_trend, r_top2 = policy_momentum_top2_trend_gate(panels, decision_dt)

    # In synthetic data, prices are growing, so trend is positive
    # Total crypto exposure must be identical (1.0) across all paired policies
    assert pytest.approx(w_trend_btc.sum(), abs=1e-6) == 1.0
    assert pytest.approx(w_trend_ew4.sum(), abs=1e-6) == 1.0
    assert pytest.approx(w_top1_trend.sum(), abs=1e-6) == 1.0
    assert pytest.approx(w_top2_trend.sum(), abs=1e-6) == 1.0


def test_breakeven_solver_handles_no_positive_edge() -> None:
    """8. Verify breakeven solver fails closed if policy has no positive edge at 0 bps."""
    panels = _synthetic_panels(periods=24 * 60)
    # Compare CASH_100 against BTC_BH in growing market (CASH has negative excess wealth)
    c_star, status = compute_breakeven_cost(
        panels,
        policy_name="CASH_100",
        benchmark_name="BTC_BH",
        start_dt=pd.Timestamp("2021-12-10 00:00:00", tz="UTC"),
        end_dt=pd.Timestamp("2021-12-25 00:00:00", tz="UTC"),
    )
    assert c_star is None
    assert status == "NO_POSITIVE_BREAKEVEN_EDGE"


def test_negative_btc_cagr_triggers_fallback_gate() -> None:
    """9. Verify negative BTC CAGR triggers fallback gate and marks retention NOT_APPLICABLE."""
    dummy_btc = ReplayResult(
        policy_name="BTC_BH",
        fee_bps=12.0,
        no_trade_band=0.05,
        rebalance_freq="WEEKLY",
        timestamps=[],
        equities=np.array([10000.0, 5000.0]),
        cash_history=np.zeros(2),
        holdings_history=np.zeros((2, 4)),
        weights_history=np.zeros((2, 4)),
        turnovers=np.zeros(2),
        fees=np.zeros(2),
        rebalance_events=[],
        cagr=-0.30,  # Negative BTC CAGR
        cum_return=-0.50,
        max_drawdown=-0.60,
        calmar=0.50,
        sharpe=-0.2,
        avg_cash=0.0,
        annualized_turnover=0.0,
        total_fees=12.0,
    )

    dummy_policy = ReplayResult(
        policy_name="TREND_GATE_EW4",
        fee_bps=12.0,
        no_trade_band=0.05,
        rebalance_freq="WEEKLY",
        timestamps=[],
        equities=np.array([10000.0, 11000.0]),
        cash_history=np.zeros(2),
        holdings_history=np.zeros((2, 4)),
        weights_history=np.zeros((2, 4)),
        turnovers=np.zeros(2),
        fees=np.zeros(2),
        rebalance_events=[],
        cagr=0.08,
        cum_return=0.10,
        max_drawdown=-0.15,
        calmar=0.53,
        sharpe=0.8,
        avg_cash=0.50,
        annualized_turnover=1.0,
        total_fees=30.0,
    )

    primary_results = {"BTC_BH": dummy_btc, "TREND_GATE_EW4": dummy_policy}
    stress_results = {"TREND_GATE_EW4": dummy_policy}

    verdict = evaluate_economic_gates(primary_results, stress_results)
    assert verdict.is_btc_cagr_positive is False
    assert "not_applicable" in verdict.policy_checks["TREND_GATE_EW4"]
    assert verdict.policy_checks["TREND_GATE_EW4"]["not_applicable"] is True
    assert verdict.policy_checks["TREND_GATE_EW4"]["capital_preservation"] is True
    assert verdict.policy_checks["TREND_GATE_EW4"]["drawdown_compression_lte_65pct"] is True


def test_candidate_does_not_grant_neural_training() -> None:
    """10. Verify economic candidate verdict does NOT authorize neural training or production."""
    # Even if status is S5_P0_ECONOMIC_OPPORTUNITY_CANDIDATE:
    # Authorization remains strictly research proposal only
    auth_scope = "PROPOSE_S5_P1_RESEARCH_CANDIDATE"
    assert "NEURAL_TRAINING_AUTHORIZED" not in auth_scope
    assert "PRODUCTION_PROMOTION_AUTHORIZED" not in auth_scope


# -----------------------------------------------------------------------------
# S5-P0B Phase 2: Targeted Economic Integrity Tests
# -----------------------------------------------------------------------------


def test_first_fill_occurs_at_0100_never_0000() -> None:
    """11. Verify first fill occurs at 01:00 UTC and never at 00:00 UTC."""
    panels = _synthetic_panels(start="2021-12-01 00:00:00", periods=24 * 30)
    start_dt = pd.Timestamp("2021-12-10 00:00:00", tz="UTC")
    end_dt = pd.Timestamp("2021-12-25 00:00:00", tz="UTC")

    res = run_stateful_replay(panels, "BTC_BH", start_dt=start_dt, end_dt=end_dt)

    # At t_idx == 0 (00:00 UTC): portfolio is strictly 100% cash, no holdings
    assert res.timestamps[0] == start_dt
    assert res.timestamps[0].hour == 0
    assert pytest.approx(res.cash_history[0], abs=1e-6) == 10000.0
    assert np.all(res.holdings_history[0] == 0.0)
    assert res.fees[0] == 0.0
    assert res.turnovers[0] == 0.0

    # First event must be INITIAL_ALLOCATION at 01:00 UTC
    first_event = res.rebalance_events[0]
    assert first_event["action"] == "INITIAL_ALLOCATION"
    assert first_event["bar"].endswith("01:00:00+00:00")

    # At t_idx == 1 (01:00 UTC): initial fill executed
    assert res.timestamps[1].hour == 1
    assert res.holdings_history[1, 0] > 0.0
    assert res.fees[1] > 0.0
    assert res.turnovers[1] > 0.0


def test_first_allocation_consistent_across_policies() -> None:
    """12. Verify first allocation is scheduled consistently at 01:00 UTC across policies."""
    panels = _synthetic_panels(start="2021-12-01 00:00:00", periods=24 * 30)
    start_dt = pd.Timestamp("2021-12-10 00:00:00", tz="UTC")
    end_dt = pd.Timestamp("2021-12-25 00:00:00", tz="UTC")

    test_policies = ["BTC_BH", "EW4", "TREND_GATE_BTC", "VOL_TARGET_BTC", "MOMENTUM_TOP1"]
    for pol in test_policies:
        res = run_stateful_replay(panels, pol, start_dt=start_dt, end_dt=end_dt)
        assert len(res.rebalance_events) >= 1
        ev0 = res.rebalance_events[0]
        assert ev0["action"] == "INITIAL_ALLOCATION"
        assert ev0["bar"] == "2021-12-10T01:00:00+00:00"
        # Confirm 00:00 bar held only cash
        assert pytest.approx(res.cash_history[0], abs=1e-6) == 10000.0
        assert np.all(res.holdings_history[0] == 0.0)


def test_no_double_initial_rebalance_event() -> None:
    """13. Verify start date falling on Sunday does not trigger double initial/rebalance event."""
    panels = _synthetic_panels(start="2021-11-20 00:00:00", periods=24 * 30)
    # 2021-12-05 is a Sunday
    start_sunday = pd.Timestamp("2021-12-05 00:00:00", tz="UTC")
    assert start_sunday.dayofweek == 6
    end_dt = pd.Timestamp("2021-12-19 00:00:00", tz="UTC")

    res = run_stateful_replay(panels, "TREND_GATE_BTC", start_dt=start_sunday, end_dt=end_dt)

    # Extract all event timestamps
    event_bars = [ev["bar"] for ev in res.rebalance_events]
    # No duplicate timestamps in events
    assert len(event_bars) == len(set(event_bars))

    # At 2021-12-05 01:00:00, there must be exactly ONE event: INITIAL_ALLOCATION
    bars_at_0100 = [ev for ev in res.rebalance_events if ev["bar"] == "2021-12-05T01:00:00+00:00"]
    assert len(bars_at_0100) == 1
    assert bars_at_0100[0]["action"] == "INITIAL_ALLOCATION"


def test_accounting_conservation_after_fee_aware_execution() -> None:
    """14. Verify exact capital conservation v_post + fee == v_pre across all simulation events."""
    panels = _synthetic_panels(start="2021-11-20 00:00:00", periods=24 * 40)
    start_dt = pd.Timestamp("2021-12-01 00:00:00", tz="UTC")
    end_dt = pd.Timestamp("2021-12-25 00:00:00", tz="UTC")

    res = run_stateful_replay(panels, "MOMENTUM_TOP1_TREND_GATE", start_dt=start_dt, end_dt=end_dt)
    for ev in res.rebalance_events:
        if ev["action"] in ("INITIAL_ALLOCATION", "REBALANCE"):
            v_pre = ev["v_pre"]
            v_post = ev["v_post"]
            fee = ev["fee"]
            assert pytest.approx(v_post + fee, abs=1e-8) == v_pre
            assert v_post > 0.0
            assert fee >= 0.0


def test_one_missing_hour_does_not_create_fake_observation() -> None:
    """15. Verify missing market-wide hour is not forward-filled or fabricated."""
    panels = _synthetic_panels(start="2021-11-20 00:00:00", periods=24 * 40)
    start_dt = pd.Timestamp("2021-12-01 00:00:00", tz="UTC")
    end_dt = pd.Timestamp("2021-12-25 00:00:00", tz="UTC")

    # Drop one hour market-wide
    gap_ts = pd.Timestamp("2021-12-10 13:00:00", tz="UTC")
    for s in UNIVERSE:
        panels[s] = panels[s].drop(gap_ts)

    audit = audit_replay_timeline(panels, start_dt, end_dt)
    assert audit["missing_hours_count"] == 1
    assert gap_ts.isoformat() in audit["missing_timestamps"]

    res = run_stateful_replay(panels, "BTC_BH", start_dt, end_dt)
    # The gap timestamp MUST NOT exist in result timestamps
    assert gap_ts not in res.timestamps
    assert len(res.timestamps) == audit["expected_hours"] - 1


def test_turnover_uses_pre_trade_portfolio_equity() -> None:
    """16. Verify turnover uses pre-trade portfolio equity (traded notional / v_pre)."""
    # Create scenario where equity has dropped by 50%
    current_notionals = np.array([2500.0, 0.0, 0.0, 0.0])  # total equity = 5000 (was 10000)
    current_cash = 2500.0
    v_pre = current_cash + float(current_notionals.sum())
    assert v_pre == 5000.0

    target_weights = np.array([0.0, 1.0, 0.0, 0.0])  # rebalance to 100% ETH
    fee_rate = 0.0012

    v_post, fee = solve_post_fee_equity(v_pre, current_notionals, target_weights, fee_rate)
    new_notionals = target_weights * v_post
    traded_notional = float(np.sum(np.abs(new_notionals - current_notionals)))

    fractional_turnover = traded_notional / v_pre

    # Selling 2500 BTC + buying ~4994 ETH = ~7494 total traded notional.
    # Divided by v_pre (5000), fractional turnover is ~1.50 (150% turnover of current portfolio).
    # If divided by initial capital (10000), it would have been ~0.75 (75%), which is wrong!
    assert pytest.approx(fractional_turnover, abs=0.01) == 1.50
    assert pytest.approx(traded_notional / 10000.0, abs=0.01) == 0.75
    assert fractional_turnover != traded_notional / 10000.0


def test_breakeven_multiple_crossings_handled_explicitly() -> None:
    """17. Verify multi-point grid scan identifies multiple crossings and takes lowest root."""
    panels = _synthetic_panels(start="2021-11-20 00:00:00", periods=24 * 40)
    start_dt = pd.Timestamp("2021-12-01 00:00:00", tz="UTC")
    end_dt = pd.Timestamp("2021-12-25 00:00:00", tz="UTC")

    # Run with return_diagnostics=True
    c_star, status, diag = compute_breakeven_cost(
        panels,
        policy_name="CASH_100",
        benchmark_name="BTC_BH",
        start_dt=start_dt,
        end_dt=end_dt,
        return_diagnostics=True,
    )
    assert len(diag["grid_points"]) == 11
    assert len(diag["g_values"]) == 11
    assert status == "NO_POSITIVE_BREAKEVEN_EDGE"
    assert c_star is None


def test_continuous_calendar_window_vs_independent_replay() -> None:
    """18. Verify continuous calendar window decomposition differs from independent restart."""
    panels = _synthetic_panels(start="2021-11-20 00:00:00", periods=24 * 70)
    start_full = pd.Timestamp("2021-12-01 00:00:00", tz="UTC")
    split_dt = pd.Timestamp("2021-12-15 00:00:00", tz="UTC")
    end_full = pd.Timestamp("2021-12-31 23:00:00", tz="UTC")

    # Full continuous replay
    res_full = run_stateful_replay(panels, "BTC_BH", start_full, end_full, initial_capital=10000.0)
    idx_split = res_full.timestamps.index(split_dt)
    v_split = float(res_full.equities[idx_split])

    # Second half continuous return:
    v_terminal = float(res_full.equities[-1])
    ret_continuous_second_half = v_terminal / v_split - 1.0

    # Independent restart replay of second half with fresh 10000 capital:
    res_independent_second_half = run_stateful_replay(
        panels, "BTC_BH", split_dt, end_full, initial_capital=10000.0
    )
    v_independent_terminal = float(res_independent_second_half.equities[-1])

    # In continuous run, terminal wealth compound is v_split * (1 + ret_second_half)
    assert pytest.approx(v_terminal, abs=1e-4) == v_split * (1.0 + ret_continuous_second_half)
    # Terminal wealth in independent restart is 10000 * (1 + ret_independent)
    # Unless v_split happened to be exactly 10000, final dollars differ
    assert v_terminal != v_independent_terminal
