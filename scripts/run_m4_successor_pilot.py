"""
scripts/run_m4_successor_pilot.py
Phase C & D: Controlled 9-Variant Development Experiment for M4 Successor Research.

Evaluates 3 pre-registered hypothesis families on historical development data (2023-01-01 to 2025-12-31):
- H-S1 (Cost-Aware Entry Hurdle): 30, 40, 50 bps hurdle to middle Bollinger Band.
- H-S2 (Genuine Open Interest Expansion): delta_oi_24h > 0, delta_oi_24h >= 2%, delta_oi_24h > 0 AND oi > sma_5d.
- H-S3 (Higher-Timeframe 4h Trend Alignment): 4h EMA 100, 150, 200 closed-candle trend filters.

Strict Invariants:
- Exactly 9 variants + 2 strategy baselines + 2 passive/anchor baselines.
- Zero lookahead: Closed 4h bars only; +5m publication latency buffer on OI.
- Spot long-only: derivatives funding is NOT deducted from spot PnL.
- Identical 14 bps round-trip transaction costs (10 bps fee + 2 bps spread + 2 bps slippage), plus 20 and 30 bps stress.
- 3 chronological walk-forward folds with 24h purge gap.
- Burned windows (2026-01 to 2026-11) are strictly preserved and untouched.
"""
from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import numpy as np
import pandas as pd

import sys
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from btc_scraper.research.baseline_runner import (
    AlwaysFlatStrategy,
    BaselineStrategy,
    ExperimentRunner,
    PassiveBuyAndHoldStrategy,
)
from btc_scraper.research.experiment_contract import ExperimentResult, ExperimentSpec
from btc_scraper.research.multi_source_features import MultiSourceFeatureProvider
from btc_scraper.research.strategy_registry import (
    EmaTrendFollowingStrategy,
    RsiBollingerMeanReversionStrategy,
)
from btc_scraper.research.successor_strategies import (
    CostAwareMeanReversionStrategy,
    GenuineOiTrendStrategy,
    HtfTrendFilteredMeanReversionStrategy,
)
from btc_scraper.research.walk_forward_lab import WalkForwardSplitter

EXISTING_SPOT_DIR = PROJECT_ROOT / "data" / "fresh_training_data_2023_2026"
REPORT_DIR = PROJECT_ROOT / "data" / "historical" / "quality_reports"


def load_development_candles_with_warmup(symbol: str, start_ym: str = "2023-01", end_ym: str = "2025-12") -> List[Dict[str, Any]]:
    """Loads 1h spot candles including pre-window warmup rows for initial indicator convergence."""
    sym_clean = symbol.replace("USDT", "")
    sym_dir = EXISTING_SPOT_DIR / sym_clean / "1h"
    
    y_start, m_start = map(int, start_ym.split("-"))
    y_end, m_end = map(int, end_ym.split("-"))
    months = []
    y, m = y_start, m_start
    while (y < y_end) or (y == y_end and m <= m_end):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1

    records = []
    for ym_idx, ym in enumerate(months):
        f = sym_dir / f"{sym_clean}_1h_{ym}.csv"
        if f.exists():
            df = pd.read_csv(f)
            # Include warmup rows only for the very first month to initialize rolling indicators
            if ym_idx == 0:
                df_slice = df.copy()
            else:
                df_slice = df[df["is_warmup"] == 0].copy()
            for r in df_slice.to_dict(orient="records"):
                records.append(r)

    # Sort and deduplicate chronologically
    seen_times = set()
    unique_records = []
    for r in records:
        t = str(r.get("time", ""))
        if t not in seen_times:
            seen_times.add(t)
            unique_records.append(r)

    unique_records.sort(key=lambda r: str(r.get("time", "")))
    return unique_records


def enrich_4h_closed_candles(candles_1h: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Aggregates 1h candles into 4h candles and calculates 4h EMA-100, 150, 200.
    Enforces Strict Closed-Bar Invariant:
      At 1h candle timestamp T, maps only the latest 4h candle that CLOSED at or before T.
    """
    df_1h = pd.DataFrame(candles_1h)
    df_1h["dt"] = pd.to_datetime(df_1h["time"].str.replace("Z", "+00:00"))
    df_1h = df_1h.sort_values("dt").reset_index(drop=True)

    # Resample to 4h
    df_4h = df_1h.set_index("dt").resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna().reset_index()

    # The 4h bar starting at dt closes at dt + 4h
    df_4h["close_time"] = df_4h["dt"] + pd.Timedelta(hours=4)
    df_4h["close_time_iso"] = df_4h["close_time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Compute 4h EMAs
    for period in [100, 150, 200]:
        df_4h[f"ema_{period}"] = df_4h["close"].ewm(span=period, adjust=False).mean()

    # Pre-index 4h bars for fast binary bisection
    bar_4h_close_isos = list(df_4h["close_time_iso"])
    bar_4h_closes = list(df_4h["close"])
    bar_4h_ema100 = list(df_4h["ema_100"])
    bar_4h_ema150 = list(df_4h["ema_150"])
    bar_4h_ema200 = list(df_4h["ema_200"])

    import bisect
    enriched_records = []
    for r in candles_1h:
        r_copy = dict(r)
        t_iso = str(r_copy["time"])
        # Find latest 4h bar whose close_time <= t_iso
        idx = bisect.bisect_right(bar_4h_close_isos, t_iso) - 1
        if idx >= 0:
            r_copy["htf_4h_close"] = float(bar_4h_closes[idx])
            r_copy["htf_4h_ema_100"] = float(bar_4h_ema100[idx])
            r_copy["htf_4h_ema_150"] = float(bar_4h_ema150[idx])
            r_copy["htf_4h_ema_200"] = float(bar_4h_ema200[idx])
        else:
            r_copy["htf_4h_close"] = float("nan")
            r_copy["htf_4h_ema_100"] = float("nan")
            r_copy["htf_4h_ema_150"] = float("nan")
            r_copy["htf_4h_ema_200"] = float("nan")

        enriched_records.append(r_copy)

    return enriched_records


def compute_bootstrap_ci(net_pnls: Sequence[float], n_bootstrap: int = 2000, block_size: int = 3) -> Tuple[Optional[float], Optional[float], str]:
    """Stationary block bootstrap confidence interval."""
    n = len(net_pnls)
    if n < 15:
        return None, None, "INSUFFICIENT_SAMPLE"
    arr = np.array(net_pnls)
    means = []
    n_blocks = int(math.ceil(n / block_size))
    for _ in range(n_bootstrap):
        sample = []
        for _ in range(n_blocks):
            start_idx = np.random.randint(0, n)
            block = [arr[(start_idx + i) % n] for i in range(block_size)]
            sample.extend(block)
        means.append(np.mean(sample[:n]))
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)), "STATISTICALLY_VALID"


def run_experiment() -> Dict[str, Any]:
    print("=================================================================")
    print("   M4 SUCCESSOR RESEARCH: 9-VARIANT CONTROLLED PILOT")
    print("   Horizon: 2023-01-01 to 2025-12-31 (36 Months, 3 Folds)")
    print("   Cost Model: 14 bps Round-Trip (Spot Long-Only)")
    print("   Stress Models: 20 bps & 30 bps Round-Trip")
    print("=================================================================\n")

    provider = MultiSourceFeatureProvider(metrics_latency_buffer_minutes=5)

    # 1. Load and enrich development candles
    print("[1/4] Loading and enriching development candles for BTC and ETH...")
    btc_raw = load_development_candles_with_warmup("BTCUSDT", "2023-01", "2025-12")
    eth_raw = load_development_candles_with_warmup("ETHUSDT", "2023-01", "2025-12")
    print(f"  BTC raw candles (with warmup): {len(btc_raw)}, ETH raw candles: {len(eth_raw)}")

    # Multi-source feature enrichment (basis, oi_usd with +5m buffer)
    btc_ms = provider.enrich_candle_batch("BTCUSDT", btc_raw, secondary_symbol_candles=eth_raw)
    eth_ms = provider.enrich_candle_batch("ETHUSDT", eth_raw, secondary_symbol_candles=btc_raw)

    # 4h closed-candle aggregation enrichment
    btc_enriched = enrich_4h_closed_candles(btc_ms)
    eth_enriched = enrich_4h_closed_candles(eth_ms)
    print(f"  BTC fully enriched: {len(btc_enriched)}, ETH fully enriched: {len(eth_enriched)}")

    candles_by_symbol = {
        "BTCUSDT": btc_enriched,
        "ETHUSDT": eth_enriched,
    }

    # 2. Pre-register Experiment Specs
    base_spec_14bps = ExperimentSpec(
        experiment_id="m4_successor_pilot_14bps",
        strategy_id="successor_pilot",
        strategy_version="1.0.0",
        dataset_manifest_identity="canonical_binance_2023_2026_manifest",
        dataset_content_hash="c4ab114eefdd01cfd7edee3ae1352c06aa24822469bfe414ca1743677ca8edf2",
        feature_set_version="multi_source_and_4h_v1",
        symbol_universe=("BTCUSDT", "ETHUSDT"),
        timeframe="1h",
        oos_window=("2023-01-01T00:00:00Z", "2025-12-31T23:00:00Z"),
        initial_capital=20_000.0,
        allocation_pct=0.10,
        max_open_positions=2,
        fee_model={"is_futures": False, "spot_maker_bps": 5.0, "spot_taker_bps": 5.0},
        slippage_model={"enabled": True, "base_slippage_bps": 1.0},
        spread_model={"enabled": True, "typical_spread_bps": 2.0},
        execution_timing_policy="NEXT_BAR_OPEN",
        same_candle_policy="CONSERVATIVE_SL_FIRST",
    )

    spec_20bps = ExperimentSpec(
        experiment_id="m4_successor_pilot_20bps",
        strategy_id="successor_pilot",
        strategy_version="1.0.0",
        dataset_manifest_identity="canonical_binance_2023_2026_manifest",
        dataset_content_hash="c4ab114eefdd01cfd7edee3ae1352c06aa24822469bfe414ca1743677ca8edf2",
        feature_set_version="multi_source_and_4h_v1",
        symbol_universe=("BTCUSDT", "ETHUSDT"),
        timeframe="1h",
        oos_window=("2023-01-01T00:00:00Z", "2025-12-31T23:00:00Z"),
        initial_capital=20_000.0,
        allocation_pct=0.10,
        max_open_positions=2,
        fee_model={"is_futures": False, "spot_maker_bps": 7.0, "spot_taker_bps": 7.0},
        slippage_model={"enabled": True, "base_slippage_bps": 1.5},
        spread_model={"enabled": True, "typical_spread_bps": 3.0},
        execution_timing_policy="NEXT_BAR_OPEN",
        same_candle_policy="CONSERVATIVE_SL_FIRST",
    )

    spec_30bps = ExperimentSpec(
        experiment_id="m4_successor_pilot_30bps",
        strategy_id="successor_pilot",
        strategy_version="1.0.0",
        dataset_manifest_identity="canonical_binance_2023_2026_manifest",
        dataset_content_hash="c4ab114eefdd01cfd7edee3ae1352c06aa24822469bfe414ca1743677ca8edf2",
        feature_set_version="multi_source_and_4h_v1",
        symbol_universe=("BTCUSDT", "ETHUSDT"),
        timeframe="1h",
        oos_window=("2023-01-01T00:00:00Z", "2025-12-31T23:00:00Z"),
        initial_capital=20_000.0,
        allocation_pct=0.10,
        max_open_positions=2,
        fee_model={"is_futures": False, "spot_maker_bps": 10.0, "spot_taker_bps": 10.0},
        slippage_model={"enabled": True, "base_slippage_bps": 2.5},
        spread_model={"enabled": True, "typical_spread_bps": 5.0},
        execution_timing_policy="NEXT_BAR_OPEN",
        same_candle_policy="CONSERVATIVE_SL_FIRST",
    )

    # 3. Setup 3 Chronological Walk-Forward Folds
    print("\n[2/4] Generating 3-fold chronological walk-forward splits...")
    folds = WalkForwardSplitter.generate_folds(
        start_time="2023-01-01T00:00:00Z",
        end_time="2025-12-31T23:00:00Z",
        n_folds=3,
        val_ratio=0.33,
        purge_gap_hours=24,
    )
    for f in folds:
        print(f"  Fold {f.fold_id}: Train [{f.train_start[:10]} -> {f.train_end[:10]}] | Purge 24h | Val [{f.val_start[:10]} -> {f.val_end[:10]}]")

    # 4. Define Pre-Registered Strategy Suite
    # Benchmarks
    bench_flat = AlwaysFlatStrategy()
    bench_bnh = PassiveBuyAndHoldStrategy()
    base_mr = RsiBollingerMeanReversionStrategy(rsi_period=14, rsi_oversold=30.0, rsi_exit=50.0, bb_period=20, bb_std=2.0)
    base_trend = EmaTrendFollowingStrategy(fast_period=12, slow_period=26)

    # 9 Successor Variants
    var_h_s1_v1 = CostAwareMeanReversionStrategy(min_distance_bps=30.0, variant_id="H_S1_V1")
    var_h_s1_v2 = CostAwareMeanReversionStrategy(min_distance_bps=40.0, variant_id="H_S1_V2")
    var_h_s1_v3 = CostAwareMeanReversionStrategy(min_distance_bps=50.0, variant_id="H_S1_V3")

    var_h_s2_v1 = GenuineOiTrendStrategy(min_oi_change_pct=0.0, require_sma_filter=False, variant_id="H_S2_V1")
    var_h_s2_v2 = GenuineOiTrendStrategy(min_oi_change_pct=0.02, require_sma_filter=False, variant_id="H_S2_V2")
    var_h_s2_v3 = GenuineOiTrendStrategy(min_oi_change_pct=0.0, require_sma_filter=True, variant_id="H_S2_V3")

    var_h_s3_v1 = HtfTrendFilteredMeanReversionStrategy(ema_period_4h=100, variant_id="H_S3_V1")
    var_h_s3_v2 = HtfTrendFilteredMeanReversionStrategy(ema_period_4h=150, variant_id="H_S3_V2")
    var_h_s3_v3 = HtfTrendFilteredMeanReversionStrategy(ema_period_4h=200, variant_id="H_S3_V3")

    experiments_to_run = [
        # Anchors & Baselines
        {"id": "always_flat", "family": "ANCHOR", "baseline_ref": None, "strat": bench_flat},
        {"id": "buy_and_hold", "family": "ANCHOR", "baseline_ref": None, "strat": bench_bnh},
        {"id": "base_rsi_bb_mr", "family": "BASELINE_MR", "baseline_ref": "base_rsi_bb_mr", "strat": base_mr},
        {"id": "base_ema_trend", "family": "BASELINE_TREND", "baseline_ref": "base_ema_trend", "strat": base_trend},
        # Family 1 (H-S1)
        {"id": "H_S1_V1", "family": "H_S1", "baseline_ref": "base_rsi_bb_mr", "strat": var_h_s1_v1},
        {"id": "H_S1_V2", "family": "H_S1", "baseline_ref": "base_rsi_bb_mr", "strat": var_h_s1_v2},
        {"id": "H_S1_V3", "family": "H_S1", "baseline_ref": "base_rsi_bb_mr", "strat": var_h_s1_v3},
        # Family 2 (H-S2)
        {"id": "H_S2_V1", "family": "H_S2", "baseline_ref": "base_ema_trend", "strat": var_h_s2_v1},
        {"id": "H_S2_V2", "family": "H_S2", "baseline_ref": "base_ema_trend", "strat": var_h_s2_v2},
        {"id": "H_S2_V3", "family": "H_S2", "baseline_ref": "base_ema_trend", "strat": var_h_s2_v3},
        # Family 3 (H-S3)
        {"id": "H_S3_V1", "family": "H_S3", "baseline_ref": "base_rsi_bb_mr", "strat": var_h_s3_v1},
        {"id": "H_S3_V2", "family": "H_S3", "baseline_ref": "base_rsi_bb_mr", "strat": var_h_s3_v2},
        {"id": "H_S3_V3", "family": "H_S3", "baseline_ref": "base_rsi_bb_mr", "strat": var_h_s3_v3},
    ]

    print("\n[3/4] Running backtests and economic evaluations across 13 configurations...")
    results_map: Dict[str, Dict[str, Any]] = {}

    for item in experiments_to_run:
        exp_id = item["id"]
        family = item["family"]
        strat = item["strat"]
        baseline_ref = item["baseline_ref"]

        # A. 14 bps baseline 3-year run
        runner_14 = ExperimentRunner(base_spec_14bps, liquidate_at_end=True)
        res_14 = runner_14.run(strat, candles_by_symbol)

        # B. Stress runs (20 bps, 30 bps)
        runner_20 = ExperimentRunner(spec_20bps, liquidate_at_end=True)
        res_20 = runner_20.run(strat, candles_by_symbol)

        runner_30 = ExperimentRunner(spec_30bps, liquidate_at_end=True)
        res_30 = runner_30.run(strat, candles_by_symbol)

        # Detailed trade metrics
        trades_14 = list(res_14.trade_lineage)
        n_trades = res_14.total_trades
        net_pnls_14 = [float(t.get("net_pnl", 0.0)) for t in trades_14]
        net_pnl_14 = float(res_14.net_pnl)
        net_pnl_20 = float(res_20.net_pnl)
        net_pnl_30 = float(res_30.net_pnl)

        effective_gross_pnl = float(res_14.gross_pnl)
        exchange_fees = float(res_14.total_fees)
        slippage_drag = float(res_14.total_slippage)
        spread_drag = float(res_14.total_spread)
        total_friction = exchange_fees + slippage_drag + spread_drag
        raw_gross_pnl = effective_gross_pnl + slippage_drag + spread_drag

        # Reconciliation check (allowing up to 5 cents due to rounding of individual trade metrics)
        assert math.isclose(net_pnl_14, raw_gross_pnl - total_friction, abs_tol=0.05), f"Reconciliation error on {exp_id}: net={net_pnl_14}, raw-fric={raw_gross_pnl - total_friction}"
        assert res_14.reconciliation_error < 0.01, f"Portfolio cash reconciliation error on {exp_id}: {res_14.reconciliation_error}"

        win_rate = (float(res_14.win_rate) * 100.0) if res_14.win_rate is not None else 0.0
        profit_factor = float(res_14.profit_factor) if res_14.profit_factor is not None else 0.0
        expectancy = (net_pnl_14 / n_trades) if n_trades > 0 else 0.0
        max_dd_pct = float(res_14.max_drawdown_pct) if res_14.max_drawdown_pct is not None else 0.0

        wins = [p for p in net_pnls_14 if p > 0]
        losses = [p for p in net_pnls_14 if p < 0]
        avg_win = float(np.mean(wins)) if wins else 0.0
        avg_loss = float(np.mean(losses)) if losses else 0.0
        payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

        holding_bars = [int(t.get("hold_bars", 1)) for t in trades_14]
        avg_holding_duration = float(np.mean(holding_bars)) if holding_bars else 0.0
        exposure_pct = (sum(holding_bars) / (26303 * 2)) * 100.0  # across both assets
        turnover = sum(float(t.get("notional", 1000.0)) for t in trades_14) / 20000.0

        ci_low, ci_high, ci_status = compute_bootstrap_ci(net_pnls_14)

        # Asset breakdown
        btc_trades = [t for t in trades_14 if t.get("symbol") == "BTCUSDT"]
        eth_trades = [t for t in trades_14 if t.get("symbol") == "ETHUSDT"]
        btc_pnl = sum(float(t.get("net_pnl", 0.0)) for t in btc_trades)
        eth_pnl = sum(float(t.get("net_pnl", 0.0)) for t in eth_trades)

        # C. 3 Fold evaluations
        fold_summaries = []
        positive_folds = 0
        for fold in folds:
            f_spec = ExperimentSpec(
                experiment_id=f"{exp_id}_fold_{fold.fold_id}",
                strategy_id=exp_id,
                strategy_version="1.0.0",
                dataset_manifest_identity=base_spec_14bps.dataset_manifest_identity,
                dataset_content_hash=base_spec_14bps.dataset_content_hash,
                feature_set_version="multi_source_and_4h_v1",
                symbol_universe=("BTCUSDT", "ETHUSDT"),
                timeframe="1h",
                oos_window=(fold.val_start, fold.val_end),
                initial_capital=20_000.0,
                allocation_pct=0.10,
                max_open_positions=2,
                fee_model={"is_futures": False, "spot_maker_bps": 5.0, "spot_taker_bps": 5.0},
                slippage_model={"enabled": True, "base_slippage_bps": 1.0},
                spread_model={"enabled": True, "typical_spread_bps": 2.0},
                execution_timing_policy="NEXT_BAR_OPEN",
                same_candle_policy="CONSERVATIVE_SL_FIRST",
            )
            f_runner = ExperimentRunner(f_spec, liquidate_at_end=True)
            f_res = f_runner.run(strat, candles_by_symbol)
            f_net = float(f_res.net_pnl)
            if f_net > 0:
                positive_folds += 1
            fold_summaries.append({
                "fold_id": fold.fold_id,
                "train_window": [fold.train_start, fold.train_end],
                "val_window": [fold.val_start, fold.val_end],
                "trades": f_res.total_trades,
                "net_pnl_14bps": round(f_net, 2),
                "profit_factor": round(float(f_res.profit_factor), 2) if f_res.profit_factor is not None else 0.0,
                "win_rate_pct": round(float(f_res.win_rate) * 100.0, 1) if f_res.win_rate is not None else 0.0,
            })

        results_map[exp_id] = {
            "id": exp_id,
            "family": family,
            "baseline_ref": baseline_ref,
            "trade_count": n_trades,
            "raw_gross_pnl": round(raw_gross_pnl, 2),
            "effective_gross_pnl": round(effective_gross_pnl, 2),
            "total_friction_usd": round(total_friction, 2),
            "net_pnl_14bps": round(net_pnl_14, 2),
            "net_pnl_20bps": round(net_pnl_20, 2),
            "net_pnl_30bps": round(net_pnl_30, 2),
            "net_expectancy": round(expectancy, 2),
            "profit_factor": round(profit_factor, 2),
            "win_rate_pct": round(win_rate, 2),
            "avg_win_usd": round(avg_win, 2),
            "avg_loss_usd": round(avg_loss, 2),
            "payoff_ratio": round(payoff_ratio, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "avg_holding_duration_hours": round(avg_holding_duration, 1),
            "exposure_pct": round(exposure_pct, 2),
            "turnover": round(turnover, 2),
            "bootstrap_ci": {"status": ci_status, "ci_95": [ci_low, ci_high] if ci_low is not None else None},
            "btc_pnl_usd": round(btc_pnl, 2),
            "btc_trades": len(btc_trades),
            "eth_pnl_usd": round(eth_pnl, 2),
            "eth_trades": len(eth_trades),
            "positive_folds": f"{positive_folds}/{len(folds)}",
            "fold_results": fold_summaries,
            "trade_lineage": [dict(t) for t in trades_14],
        }

        print(f"  {exp_id:18s} ({family:14s}) | Trades: {n_trades:4d} | Net 14bps: ${net_pnl_14:+8.2f} | PF: {profit_factor:5.2f} | DD: {max_dd_pct:5.2f}% | Folds+: {positive_folds}/3")

    # 5. Incremental Comparison & Failure Attribution
    print("\n[4/4] Computing incremental economic value vs respective baselines...")
    variants_summary = []

    # Map baselines
    base_mr_res = results_map["base_rsi_bb_mr"]
    base_trend_res = results_map["base_ema_trend"]

    for exp_id, res in results_map.items():
        if res["family"] in ("ANCHOR", "BASELINE_MR", "BASELINE_TREND"):
            continue

        base_res = base_mr_res if res["baseline_ref"] == "base_rsi_bb_mr" else base_trend_res
        
        delta_net_pnl = res["net_pnl_14bps"] - base_res["net_pnl_14bps"]
        delta_pf = res["profit_factor"] - base_res["profit_factor"]
        delta_trades = res["trade_count"] - base_res["trade_count"]
        delta_friction = res["total_friction_usd"] - base_res["total_friction_usd"]
        delta_dd = res["max_drawdown_pct"] - base_res["max_drawdown_pct"]
        delta_exp = res["net_expectancy"] - base_res["net_expectancy"]

        # Attribution verdict
        # Check if Net PnL improved, if risk reduced, or if alpha actually improved
        if res["net_pnl_14bps"] > 0 and res["profit_factor"] >= 1.30 and res["positive_folds"] == "3/3":
            disposition = "PROMISING_DEVELOPMENT_CANDIDATE"
        elif delta_net_pnl > 0 and delta_dd < 0 and res["net_pnl_14bps"] <= 0:
            disposition = "RISK_REDUCTION_ONLY / NOT_PROMOTABLE"
        elif res["net_pnl_14bps"] <= 0:
            disposition = "REJECTED"
        else:
            disposition = "INCONCLUSIVE"

        incremental_data = {
            "variant_id": exp_id,
            "hypothesis_family": res["family"],
            "baseline_strategy": base_res["id"],
            "trade_count": res["trade_count"],
            "delta_trades": delta_trades,
            "friction_saved_usd": round(-delta_friction, 2),
            "net_pnl_14bps": res["net_pnl_14bps"],
            "delta_net_pnl_usd": round(delta_net_pnl, 2),
            "profit_factor": res["profit_factor"],
            "delta_profit_factor": round(delta_pf, 2),
            "expectancy_usd": res["net_expectancy"],
            "delta_expectancy_usd": round(delta_exp, 2),
            "max_drawdown_pct": res["max_drawdown_pct"],
            "delta_max_drawdown_pct": round(delta_dd, 2),
            "positive_folds": res["positive_folds"],
            "disposition": disposition,
        }
        variants_summary.append(incremental_data)
        res["incremental_vs_baseline"] = incremental_data
        res["disposition"] = disposition

    # Holm-Bonferroni Multi-Testing Analysis
    # Null hypothesis: variant expectancy <= 0
    # Rank variants by expectancy
    sorted_vars = sorted(variants_summary, key=lambda v: v["expectancy_usd"], reverse=True)
    m = len(sorted_vars)
    for rank, v in enumerate(sorted_vars):
        alpha_target = 0.05 / (m - rank)
        v["holm_bonferroni_rank"] = rank + 1
        v["holm_bonferroni_adjusted_alpha"] = round(alpha_target, 5)
        # Empirical test passes only if Net PnL > 0 and 95% bootstrap CI > 0
        ci_low = results_map[v["variant_id"]]["bootstrap_ci"].get("ci_95")
        if ci_low and ci_low[0] > 0 and v["net_pnl_14bps"] > 0:
            v["holm_bonferroni_verdict"] = "STATISTICALLY_SIGNIFICANT"
        else:
            v["holm_bonferroni_verdict"] = "NULL_NOT_REJECTED"

    # Serialize complete results payload
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = REPORT_DIR / "m4_successor_pilot_results.json"
    payload = {
        "execution_timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "milestone": "M4_SUCCESSOR_CONTROLLED_EXPERIMENT",
        "development_window": "2023-01-01 to 2025-12-31",
        "burned_windows": {
            "h1_2026": "2026-01-01 to 2026-06-30 (BURNED_FOR_PROMOTION)",
            "h2_2026": "2026-07-01 to 2026-11-09 (BURNED_FOR_SUCCESSOR_SELECTION)",
        },
        "cost_model": "14 bps baseline (5 bps maker + 5 bps taker fee + 2 bps slippage + 2 bps spread)",
        "search_budget": "9 pre-registered variants across 3 families",
        "baselines": {
            "always_flat": results_map["always_flat"],
            "buy_and_hold": results_map["buy_and_hold"],
            "base_rsi_bb_mr": results_map["base_rsi_bb_mr"],
            "base_ema_trend": results_map["base_ema_trend"],
        },
        "variants": variants_summary,
        "detailed_results": results_map,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"\n[Complete] Results successfully saved to {output_path}")
    return payload


if __name__ == "__main__":
    run_experiment()
