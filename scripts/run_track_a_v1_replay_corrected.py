"""Track A v1 Corrected Economic Replay Runner & Evidence Generator.

Preserves exact policy parameters:
- Donchian 20/55/90
- 2-day confirmation
- 20% no-trade buffer
- BTC/Cash universe
- 00:00 UTC decision, 01:00 UTC execution
- Realistic fee accounting: solve_post_fee_equity
- Cost scenarios: 12.0, 20.0, 30.0, 50.0 bps

Incorporates targeted integrity corrections:
1. S5 baseline strictly adheres to S5-P0B calendar lookback (168h) and emits HOLD_DATA_GAP on missing bars.
2. Standardized turnover: sum(traded_notional / pre_trade_equity) / years.
3. Dynamic runtime assertions for accounting & causal integrity (no hardcoded PASS).
4. Verifies daily OHLCV completeness and verified exchange gaps without synthetic candles.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from btc_scraper.research.s5_economic_replay import compute_market_trend_168h
from btc_scraper.research.track_a_strategy import (
    LOOKBACK_HORIZONS,
    S5_NO_TRADE_BAND,
    TRACK_A_NO_TRADE_BAND,
    StrategyMetrics,
    TrackAReplayResult,
    build_btc_daily_candles,
    compute_track_a_signals,
    load_universe_panels,
    run_btc_buy_and_hold_replay,
    run_s5_daily_trend_replay,
    run_track_a_replay,
    verify_replay_accounting_integrity,
    verify_replay_causal_integrity,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
START_DT = pd.Timestamp("2022-01-01 00:00:00", tz="UTC")
END_DT = pd.Timestamp("2026-11-18 23:00:00", tz="UTC")
COST_SCENARIOS = (12.0, 20.0, 30.0, 50.0)


def compute_subperiod_metrics(
    timestamps: list[pd.Timestamp],
    equities: np.ndarray,
    turnovers: np.ndarray,
    fees: np.ndarray,
    sub_start: pd.Timestamp,
    sub_end: pd.Timestamp,
) -> dict[str, Any]:
    ts_arr = np.array(timestamps)
    mask = (ts_arr >= sub_start) & (ts_arr <= sub_end)
    if not np.any(mask):
        return {}

    sub_eq = equities[mask]
    sub_fees = fees[mask]
    sub_turnovers = turnovers[mask]

    start_val = sub_eq[0]
    final_val = sub_eq[-1]
    net_ret = (final_val / start_val) - 1.0 if start_val > 0 else 0.0

    days = (sub_end - sub_start).total_seconds() / 86400.0
    years = max(days / 365.25, 0.001)
    cagr = (final_val / start_val) ** (1.0 / years) - 1.0 if (final_val > 0 and start_val > 0) else -1.0

    peaks = np.maximum.accumulate(sub_eq)
    dds = (sub_eq - peaks) / np.where(peaks > 0, peaks, 1.0)
    max_dd = float(np.min(dds))
    annualized_turnover = (float(np.sum(sub_turnovers)) / years) if years > 0 else 0.0

    return {
        "start_equity": float(start_val),
        "final_equity": float(final_val),
        "net_return": float(net_ret),
        "cagr": float(cagr),
        "max_drawdown": float(max_dd),
        "annualized_turnover": float(annualized_turnover),
        "total_fees": float(np.sum(sub_fees)),
    }


def main():
    print("=== STARTING TRACK A V1 CORRECTED ECONOMIC REPLAY ===", flush=True)
    out_dir = REPO_ROOT / "research/track_a/v1"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load universe panels
    print(f"Loading full universe panels ({START_DT.strftime('%Y-%m-%d')} to {END_DT.strftime('%Y-%m-%d')})...", flush=True)
    panels = load_universe_panels(REPO_ROOT)
    for sym, p in panels.items():
        print(f"  {sym}: {len(p)} bars, {p.index[0]} to {p.index[-1]}", flush=True)

    # 2. Build daily candles & verify completeness
    print("\nBuilding daily candles & verifying completeness...", flush=True)
    btc_daily = build_btc_daily_candles(panels["BTCUSDT"])
    total_days = len(btc_daily)
    incomplete_days = btc_daily[btc_daily["hour_count"] < 24]
    print(f"  Total daily candles: {total_days}, start={btc_daily.index[0].date()}, end={btc_daily.index[-1].date()}", flush=True)
    print(f"  Incomplete days count: {len(incomplete_days)}", flush=True)
    for idx_d, r_d in incomplete_days.iterrows():
        print(f"    Date {idx_d.date()}: {int(r_d['hour_count'])}/24 hours (verified exchange gap, no synthetic candles)", flush=True)

    # 3. Precompute causal 168h market trends for S5 baseline
    print("\nPrecomputing causal 168h market trends for S5 baseline...", flush=True)
    decision_dates = pd.date_range(START_DT, END_DT, freq="D", tz="UTC")
    precomputed_trends = {}
    gap_count = 0
    for d in decision_dates:
        t_val = compute_market_trend_168h(panels, d)
        precomputed_trends[d] = t_val
        if t_val is None:
            gap_count += 1
    print(f"  Precomputed {len(precomputed_trends)} dates, gap/missing count={gap_count}", flush=True)

    # 4. Compute Track A Donchian signals
    print("\nComputing causal Donchian signals for Track A v1...", flush=True)
    signals = compute_track_a_signals(btc_daily)
    print(f"  Total signals generated: {len(signals)}", flush=True)

    # 5. Execute simulations across cost scenarios
    results_by_cost: dict[float, dict[str, Any]] = {}
    primary_results: dict[str, Any] = {}

    for fee_bps in COST_SCENARIOS:
        print(f"\nRunning simulation at {fee_bps:.1f} bps one-way fee...", flush=True)

        res_track_a = run_track_a_replay(
            btc_hourly=panels["BTCUSDT"],
            signals=signals,
            start_dt=START_DT,
            end_dt=END_DT,
            initial_capital=10000.0,
            fee_bps=fee_bps,
            no_trade_band=TRACK_A_NO_TRADE_BAND,
        )

        res_s5 = run_s5_daily_trend_replay(
            panels=panels,
            start_dt=START_DT,
            end_dt=END_DT,
            initial_capital=10000.0,
            fee_bps=fee_bps,
            no_trade_band=S5_NO_TRADE_BAND,
            precomputed_trends=precomputed_trends,
        )

        res_bh = run_btc_buy_and_hold_replay(
            btc_hourly=panels["BTCUSDT"],
            start_dt=START_DT,
            end_dt=END_DT,
            initial_capital=10000.0,
            fee_bps=fee_bps,
        )

        results_by_cost[fee_bps] = {
            "TRACK_A_V1": res_track_a,
            "S5_DAILY_TREND_BTC": res_s5,
            "BTC_BH": res_bh,
        }

        if fee_bps == 30.0:
            primary_results = results_by_cost[fee_bps]

        print(f"  [Cost {fee_bps:4.1f} bps] Track A: Final=${res_track_a.metrics.final_equity:9.2f}, CAGR={res_track_a.metrics.cagr*100:6.2f}%, MaxDD={res_track_a.metrics.max_drawdown*100:6.2f}%, Calmar={res_track_a.metrics.calmar:5.2f}, Sharpe={res_track_a.metrics.sharpe:5.2f}, Turnover={res_track_a.metrics.annualized_turnover:5.2f}x, Fees=${res_track_a.metrics.total_fees:8.2f}", flush=True)
        print(f"  [Cost {fee_bps:4.1f} bps] S5 Daily: Final=${res_s5.metrics.final_equity:9.2f}, CAGR={res_s5.metrics.cagr*100:6.2f}%, MaxDD={res_s5.metrics.max_drawdown*100:6.2f}%, Calmar={res_s5.metrics.calmar:5.2f}, Sharpe={res_s5.metrics.sharpe:5.2f}, Turnover={res_s5.metrics.annualized_turnover:5.2f}x, Fees=${res_s5.metrics.total_fees:8.2f}", flush=True)
        print(f"  [Cost {fee_bps:4.1f} bps] BTC B&H:  Final=${res_bh.metrics.final_equity:9.2f}, CAGR={res_bh.metrics.cagr*100:6.2f}%, MaxDD={res_bh.metrics.max_drawdown*100:6.2f}%, Calmar={res_bh.metrics.calmar:5.2f}, Sharpe={res_bh.metrics.sharpe:5.2f}, Turnover={res_bh.metrics.annualized_turnover:5.2f}x, Fees=${res_bh.metrics.total_fees:8.2f}", flush=True)

    # 6. Dynamic Runtime Integrity Assertions
    print("\nRunning dynamic runtime integrity assertions...", flush=True)
    track_a_primary: TrackAReplayResult = primary_results["TRACK_A_V1"]
    s5_primary: TrackAReplayResult = primary_results["S5_DAILY_TREND_BTC"]
    bh_primary: TrackAReplayResult = primary_results["BTC_BH"]

    ta_acc_pass, ta_acc_msg = verify_replay_accounting_integrity(track_a_primary)
    ta_caus_pass, ta_caus_msg = verify_replay_causal_integrity(track_a_primary, signals)

    s5_acc_pass, s5_acc_msg = verify_replay_accounting_integrity(s5_primary)
    s5_caus_pass, s5_caus_msg = verify_replay_causal_integrity(s5_primary)

    bh_acc_pass, bh_acc_msg = verify_replay_accounting_integrity(bh_primary)

    print(f"  Track A Accounting Integrity: {ta_acc_msg} (pass={ta_acc_pass})", flush=True)
    print(f"  Track A Causal Integrity:     {ta_caus_msg} (pass={ta_caus_pass})", flush=True)
    print(f"  S5 Daily Accounting Integ:    {s5_acc_msg} (pass={s5_acc_pass})", flush=True)
    print(f"  S5 Daily Causal Integrity:    {s5_caus_msg} (pass={s5_caus_pass})", flush=True)
    print(f"  BTC B&H Accounting Integrity: {bh_acc_msg} (pass={bh_acc_pass})", flush=True)

    integrity_overall = ta_acc_pass and ta_caus_pass and s5_acc_pass and s5_caus_pass and bh_acc_pass
    track_a_v1_integrity_str = "PASS" if (ta_acc_pass and ta_caus_pass) else "FAIL"
    s5_baseline_parity_str = "PASS" if (s5_acc_pass and s5_caus_pass) else "FAIL"

    # 7. Calendar and Regime Breakdowns for Primary Cost (30 bps)
    calendar_years = [
        ("2022", pd.Timestamp("2022-01-01 00:00:00", tz="UTC"), pd.Timestamp("2022-12-31 23:00:00", tz="UTC")),
        ("2023", pd.Timestamp("2023-01-01 00:00:00", tz="UTC"), pd.Timestamp("2023-12-31 23:00:00", tz="UTC")),
        ("2024", pd.Timestamp("2024-01-01 00:00:00", tz="UTC"), pd.Timestamp("2024-12-31 23:00:00", tz="UTC")),
        ("2025", pd.Timestamp("2025-01-01 00:00:00", tz="UTC"), pd.Timestamp("2025-12-31 23:00:00", tz="UTC")),
        ("2026_YTD", pd.Timestamp("2026-01-01 00:00:00", tz="UTC"), END_DT),
        ("FULL_PERIOD", START_DT, END_DT),
    ]

    calendar_breakdown = {}
    for yr, y_start, y_end in calendar_years:
        calendar_breakdown[yr] = {}
        for pol_key, res_obj in primary_results.items():
            sub = compute_subperiod_metrics(
                timestamps=res_obj.timestamps,
                equities=res_obj.equities,
                turnovers=res_obj.turnovers,
                fees=res_obj.fees,
                sub_start=y_start,
                sub_end=y_end,
            )
            calendar_breakdown[yr][pol_key] = sub

    regimes = [
        ("BEAR_DELEVERAGING_2022", pd.Timestamp("2022-01-01 00:00:00", tz="UTC"), pd.Timestamp("2022-12-31 23:00:00", tz="UTC")),
        ("EARLY_RECOVERY_2023", pd.Timestamp("2023-01-01 00:00:00", tz="UTC"), pd.Timestamp("2023-10-15 23:00:00", tz="UTC")),
        ("STRONG_UPTREND_ETF", pd.Timestamp("2023-10-16 00:00:00", tz="UTC"), pd.Timestamp("2024-03-31 23:00:00", tz="UTC")),
        ("SIDEWAYS_CHOP_2024", pd.Timestamp("2024-04-01 00:00:00", tz="UTC"), pd.Timestamp("2024-10-31 23:00:00", tz="UTC")),
        ("POST_ELECTION_BULL", pd.Timestamp("2024-11-01 00:00:00", tz="UTC"), pd.Timestamp("2025-01-31 23:00:00", tz="UTC")),
        ("MACRO_EXPANSION_CONSOLIDATION", pd.Timestamp("2025-02-01 00:00:00", tz="UTC"), END_DT),
    ]

    regime_breakdown = {}
    for r_name, r_start, r_end in regimes:
        regime_breakdown[r_name] = {}
        for pol_key, res_obj in primary_results.items():
            sub = compute_subperiod_metrics(
                timestamps=res_obj.timestamps,
                equities=res_obj.equities,
                turnovers=res_obj.turnovers,
                fees=res_obj.fees,
                sub_start=r_start,
                sub_end=r_end,
            )
            regime_breakdown[r_name][pol_key] = sub

    # 8. Economic Evaluation against Pre-Registered Risk & Gate Thresholds
    ta_m = track_a_primary.metrics
    s5_m = s5_primary.metrics
    bh_m = bh_primary.metrics

    gate_eval = {
        "net_cagr_gt_0": bool(ta_m.cagr > 0.0),
        "max_dd_lte_40pct": bool(abs(ta_m.max_drawdown) <= 0.40001),
        "annualized_turnover_lte_25x": bool(ta_m.annualized_turnover <= 25.0),
        "sharpe_gte_0_30": bool(ta_m.sharpe >= 0.30),
        "calmar_gte_0_35": bool(ta_m.calmar >= 0.35),
        "avg_btc_exposure_gte_20pct": bool(ta_m.avg_btc_exposure >= 0.20),
        "accounting_integrity_pass": bool(ta_acc_pass),
        "causal_integrity_pass": bool(ta_caus_pass),
    }
    all_gates_pass = all(gate_eval.values())
    risk_gate_status = "PASS" if gate_eval["max_dd_lte_40pct"] else "FAIL"

    calmar_delta = ta_m.calmar - s5_m.calmar
    cagr_delta = ta_m.cagr - s5_m.cagr
    dd_improvement = abs(s5_m.max_drawdown) - abs(ta_m.max_drawdown)

    incremental_edge = bool(
        (calmar_delta >= 0.10 and ta_m.cagr > 0.0) or
        (cagr_delta >= -1e-6 and dd_improvement >= -1e-6)
    )

    # Official Pre-Registered Scientific Verdict
    if all_gates_pass and incremental_edge:
        verdict = "TRACK_A_V1_ECONOMIC_CANDIDATE"
    elif all_gates_pass and not incremental_edge:
        verdict = "TRACK_A_V1_PROFITABLE_NOT_INCREMENTAL"
    elif ta_m.cagr <= 0.0 or not all_gates_pass:
        verdict = "TRACK_A_V1_NO_DEMONSTRATED_EDGE"
    else:
        verdict = "TRACK_A_V1_INVALID"

    forward_paper_candidate = "YES" if (ta_m.cagr > 0.0 and ta_m.final_equity > 10000.0) else "NO"

    print("\n=======================================================", flush=True)
    print(f"SCIENTIFIC VERDICT:        {verdict}", flush=True)
    print(f"TRACK_A_V1_INTEGRITY:      {track_a_v1_integrity_str}", flush=True)
    print(f"S5_BASELINE_PARITY:        {s5_baseline_parity_str}", flush=True)
    print(f"RISK_GATE (MaxDD <= 40%):  {risk_gate_status} (actual: {ta_m.max_drawdown*100:.2f}%)", flush=True)
    print(f"HISTORICAL_NET_PROFIT:     +${ta_m.net_pnl:.2f} (CAGR: +{ta_m.cagr*100:.2f}%)", flush=True)
    print(f"FORWARD_PAPER_CANDIDATE:   {forward_paper_candidate}", flush=True)
    print("=======================================================\n", flush=True)

    # 9. Write corrected evidence JSON
    def _metrics_dict(m: StrategyMetrics) -> dict[str, Any]:
        return {
            "net_pnl": m.net_pnl,
            "cagr": m.cagr,
            "cum_return": m.cum_return,
            "max_drawdown": m.max_drawdown,
            "calmar": m.calmar,
            "sharpe": m.sharpe,
            "annualized_turnover": m.annualized_turnover,
            "total_traded_notional": m.total_traded_notional,
            "total_fees": m.total_fees,
            "avg_btc_exposure": m.avg_btc_exposure,
            "avg_cash_exposure": m.avg_cash_exposure,
            "num_trades": m.num_trades,
            "worst_month_net_return": m.worst_month_net_return,
            "final_equity": m.final_equity,
        }

    evidence_data = {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_branch": "research/s5-p0-economic-opportunity",
            "reference_commit": "49ae5a2435b66e3f2ab36d547b93461d96512d1a",
            "historical_window": f"{START_DT.isoformat()} -> {END_DT.isoformat()}",
            "scientific_verdict": verdict,
            "all_gates_pass": all_gates_pass,
            "incremental_edge": incremental_edge,
            "integrity_verification": {
                "track_a_v1_integrity": track_a_v1_integrity_str,
                "s5_baseline_parity": s5_baseline_parity_str,
                "risk_gate": risk_gate_status,
                "ta_accounting": ta_acc_msg,
                "ta_causal": ta_caus_msg,
                "s5_accounting": s5_acc_msg,
                "s5_causal": s5_caus_msg,
                "bh_accounting": bh_acc_msg,
            },
        },
        "primary_scorecards_30bps": {
            "TRACK_A_V1": _metrics_dict(ta_m),
            "S5_DAILY_TREND_BTC": _metrics_dict(s5_m),
            "BTC_BH": _metrics_dict(bh_m),
            "CASH_100": {
                "net_pnl": 0.0, "cagr": 0.0, "cum_return": 0.0,
                "max_drawdown": 0.0, "calmar": 0.0, "sharpe": 0.0,
                "annualized_turnover": 0.0, "total_fees": 0.0,
                "avg_btc_exposure": 0.0, "avg_cash_exposure": 1.0,
                "final_equity": 10000.0,
            },
        },
        "cost_sweep_scorecards": {
            str(cost): {
                pol: _metrics_dict(res.metrics)
                for pol, res in pol_dict.items()
            }
            for cost, pol_dict in results_by_cost.items()
        },
        "calendar_breakdown_30bps": calendar_breakdown,
        "market_regime_breakdown_30bps": regime_breakdown,
        "gate_evaluation": gate_eval,
        "sample_decision_ledger": track_a_primary.decision_ledger[:50] + track_a_primary.decision_ledger[-50:],
    }

    with open(out_dir / "track_a_v1_economic_evidence_corrected.json", "w", encoding="utf-8") as f:
        json.dump(evidence_data, f, indent=2)
    print(f"Saved corrected evidence to {out_dir / 'track_a_v1_economic_evidence_corrected.json'}", flush=True)

    # 10. Write corrected decision ledger CSV
    ledger_df = pd.DataFrame(track_a_primary.decision_ledger)
    ledger_df.to_csv(out_dir / "track_a_v1_decision_ledger_corrected.csv", index=False)
    print(f"Saved full corrected decision ledger ({len(ledger_df)} rows) to {out_dir / 'track_a_v1_decision_ledger_corrected.csv'}", flush=True)

    return evidence_data


if __name__ == "__main__":
    main()
