"""
scripts/run_m4_vcb_pilot.py
Phase D: Bounded Volatility Compression Breakout (VCB-v2) Development Pilot.

Evaluates the pre-registered VCB-v2 hypothesis on historical development data (2023-01-01 to 2025-12-31):
- Universe: BTCUSDT & ETHUSDT 1h
- Realistic Cost Models: 14 bps baseline (marketable spot), 20 bps stress, 30 bps stress.
- Strict Invariants: Spot long-only, zero lookahead (closed 1h & 4h bars), 3-fold walk-forward with 24h purge.
- Baselines: always_flat, buy_and_hold, base_ema_trend (945 trades).
- Variants:
  1. VCB_V2_BASELINE: Full strategy (Compression <= 25th pct + 24h Donchian Breakout + 4h EMA100 Trend).
  2. VCB_V2_ABL_NO_COMPRESSION: Ablation 1 (Donchian Breakout + 4h EMA100 Trend, no compression filter).
  3. VCB_V2_ABL_NO_HTF: Ablation 2 (Compression + Donchian Breakout, no 4h HTF trend filter).
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from btc_scraper.research.baseline_runner import (
    AlwaysFlatStrategy,
    BaselineStrategy,
    ExperimentRunner,
    PassiveBuyAndHoldStrategy,
)
from btc_scraper.research.experiment_contract import ExperimentResult, ExperimentSpec
from btc_scraper.research.strategy_registry import EmaTrendFollowingStrategy
from btc_scraper.research.vcb_strategies import VcbV2Strategy
from btc_scraper.research.walk_forward_lab import WalkForwardSplitter
from scripts.run_m4_successor_pilot import (
    load_development_candles_with_warmup,
    enrich_4h_closed_candles,
)

REPORT_DIR = PROJECT_ROOT / "data" / "historical" / "quality_reports"


def run_vcb_pilot() -> Dict[str, Any]:
    print("=================================================================")
    print("   M4 VCB-V2 BOUNDED DEVELOPMENT PILOT")
    print("   Development Window: 2023-01-01 to 2025-12-31 (36 Months, 3 Folds)")
    print("   Universe: BTCUSDT & ETHUSDT 1h (Spot Long-Only)")
    print("   Cost Model: 14 bps Baseline, 20 bps & 30 bps Stress")
    print("=================================================================\n")

    # 1. Load and enrich development candles
    print("[1/4] Loading and enriching development candles...")
    btc_raw = load_development_candles_with_warmup("BTCUSDT", "2023-01", "2025-12")
    eth_raw = load_development_candles_with_warmup("ETHUSDT", "2023-01", "2025-12")
    btc_enriched = enrich_4h_closed_candles(btc_raw)
    eth_enriched = enrich_4h_closed_candles(eth_raw)
    print(f"  BTC fully enriched bars: {len(btc_enriched)}, ETH bars: {len(eth_enriched)}")

    candles_by_symbol = {
        "BTCUSDT": btc_enriched,
        "ETHUSDT": eth_enriched,
    }

    # 2. Pre-register Experiment Specs
    spec_14bps = ExperimentSpec(
        experiment_id="m4_vcb_v2_14bps",
        strategy_id="vcb_v2_pilot",
        strategy_version="2.0.0",
        dataset_manifest_identity="canonical_binance_2023_2026_manifest",
        dataset_content_hash="c4ab114eefdd01cfd7edee3ae1352c06aa24822469bfe414ca1743677ca8edf2",
        feature_set_version="vcb_v2_closed_4h_v1",
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
        experiment_id="m4_vcb_v2_20bps",
        strategy_id="vcb_v2_pilot",
        strategy_version="2.0.0",
        dataset_manifest_identity="canonical_binance_2023_2026_manifest",
        dataset_content_hash="c4ab114eefdd01cfd7edee3ae1352c06aa24822469bfe414ca1743677ca8edf2",
        feature_set_version="vcb_v2_closed_4h_v1",
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
        experiment_id="m4_vcb_v2_30bps",
        strategy_id="vcb_v2_pilot",
        strategy_version="2.0.0",
        dataset_manifest_identity="canonical_binance_2023_2026_manifest",
        dataset_content_hash="c4ab114eefdd01cfd7edee3ae1352c06aa24822469bfe414ca1743677ca8edf2",
        feature_set_version="vcb_v2_closed_4h_v1",
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

    # 3. Strategy Suite Setup
    configs = [
        {"id": "always_flat", "family": "ANCHOR", "strat": AlwaysFlatStrategy()},
        {"id": "buy_and_hold", "family": "ANCHOR", "strat": PassiveBuyAndHoldStrategy()},
        {"id": "base_ema_trend", "family": "BASELINE_TREND", "strat": EmaTrendFollowingStrategy(12, 26)},
        {
            "id": "VCB_V2_BASELINE",
            "family": "VCB_V2",
            "strat": VcbV2Strategy(
                atr_period=14,
                compression_lookback_bars=72,
                compression_percentile=25.0,
                donchian_breakout_bars=24,
                require_htf_trend=True,
                require_compression=True,
                variant_id="VCB_V2_BASELINE",
            ),
        },
        {
            "id": "VCB_V2_ABL_NO_COMPRESSION",
            "family": "VCB_V2_ABLATION",
            "strat": VcbV2Strategy(
                atr_period=14,
                compression_lookback_bars=72,
                compression_percentile=25.0,
                donchian_breakout_bars=24,
                require_htf_trend=True,
                require_compression=False,  # Ablation: no compression
                variant_id="VCB_V2_ABL_NO_COMPRESSION",
            ),
        },
        {
            "id": "VCB_V2_ABL_NO_HTF",
            "family": "VCB_V2_ABLATION",
            "strat": VcbV2Strategy(
                atr_period=14,
                compression_lookback_bars=72,
                compression_percentile=25.0,
                donchian_breakout_bars=24,
                require_htf_trend=False,  # Ablation: no HTF
                require_compression=True,
                variant_id="VCB_V2_ABL_NO_HTF",
            ),
        },
    ]

    # 4. Chronological Walk-Forward Folds
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

    # 5. Execute Evaluations
    print("\n[3/4] Running backtests across configurations...")
    results_map: Dict[str, Any] = {}

    for item in configs:
        exp_id = item["id"]
        family = item["family"]
        strat = item["strat"]

        # A. 14 bps baseline
        runner_14 = ExperimentRunner(spec_14bps, liquidate_at_end=True)
        res_14 = runner_14.run(strat, candles_by_symbol)

        # B. Stress models (20 bps, 30 bps)
        runner_20 = ExperimentRunner(spec_20bps, liquidate_at_end=True)
        res_20 = runner_20.run(strat, candles_by_symbol)

        runner_30 = ExperimentRunner(spec_30bps, liquidate_at_end=True)
        res_30 = runner_30.run(strat, candles_by_symbol)

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

        # Reconciliation check
        assert math.isclose(net_pnl_14, raw_gross_pnl - total_friction, abs_tol=0.05), (
            f"Reconciliation error on {exp_id}: net={net_pnl_14}, raw-fric={raw_gross_pnl - total_friction}"
        )

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
        exposure_pct = float(res_14.exposure_pct)
        turnover = float(res_14.turnover)

        # Multi-asset breakdown
        btc_trades = [t for t in trades_14 if t.get("symbol") == "BTCUSDT"]
        eth_trades = [t for t in trades_14 if t.get("symbol") == "ETHUSDT"]
        btc_pnl = sum(float(t.get("net_pnl", 0.0)) for t in btc_trades)
        eth_pnl = sum(float(t.get("net_pnl", 0.0)) for t in eth_trades)

        # Statistical bootstrap & t-test
        if n_trades >= 5:
            arr = np.array(net_pnls_14)
            se = float(np.std(arr, ddof=1)) / math.sqrt(n_trades) if n_trades > 1 else 1.0
            t_stat = expectancy / se if se > 0 else 0.0
            p_val_t = float(1.0 - stats.t.cdf(t_stat, df=n_trades - 1))

            # Block bootstrap
            B = 5000
            bs_means = []
            block_size = 3
            n_blocks = int(math.ceil(n_trades / block_size))
            for _ in range(B):
                sample = []
                for _ in range(n_blocks):
                    idx = np.random.randint(0, n_trades)
                    sample.extend([arr[(idx + i) % n_trades] for i in range(block_size)])
                bs_means.append(np.mean(sample[:n_trades]))

            bs_means = np.array(bs_means)
            p_val_boot = float(np.mean(bs_means <= 0.0))
            ci_low = float(np.percentile(bs_means, 2.5))
            ci_high = float(np.percentile(bs_means, 97.5))
        else:
            p_val_t = 1.0
            p_val_boot = 1.0
            ci_low, ci_high = 0.0, 0.0

        # Walk-forward fold validation
        positive_folds = 0
        fold_summaries = []
        for fold in folds:
            f_spec = ExperimentSpec(
                experiment_id=f"{exp_id}_fold_{fold.fold_id}",
                strategy_id=exp_id,
                strategy_version="2.0.0",
                dataset_manifest_identity=spec_14bps.dataset_manifest_identity,
                dataset_content_hash=spec_14bps.dataset_content_hash,
                feature_set_version="vcb_v2_closed_4h_v1",
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
                "val_window": [fold.val_start, fold.val_end],
                "trades": f_res.total_trades,
                "net_pnl_14bps": round(f_net, 2),
                "profit_factor": round(float(f_res.profit_factor), 2) if f_res.profit_factor is not None else 0.0,
                "win_rate_pct": round(float(f_res.win_rate) * 100.0, 1) if f_res.win_rate is not None else 0.0,
            })

        results_map[exp_id] = {
            "id": exp_id,
            "family": family,
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
            "bootstrap_ci": {"ci_95": [round(ci_low, 2), round(ci_high, 2)]},
            "p_value_t": round(p_val_t, 5),
            "p_value_boot": round(p_val_boot, 5),
            "btc_pnl_usd": round(btc_pnl, 2),
            "btc_trades": len(btc_trades),
            "eth_pnl_usd": round(eth_pnl, 2),
            "eth_trades": len(eth_trades),
            "positive_folds": f"{positive_folds}/{len(folds)}",
            "fold_results": fold_summaries,
            "trade_lineage": [dict(t) for t in trades_14],
        }

        print(f"  {exp_id:26s} ({family:16s}) | Trades: {n_trades:4d} | Net 14bps: ${net_pnl_14:+8.2f} | PF: {profit_factor:5.2f} | DD: {max_dd_pct:5.2f}% | Exp: ${expectancy:+6.2f} | Folds+: {positive_folds}/3")

    # 6. Incremental Comparison vs base_ema_trend
    print("\n[4/4] Computing incremental economic value vs base_ema_trend...")
    base_trend_res = results_map["base_ema_trend"]

    for exp_id in ["VCB_V2_BASELINE", "VCB_V2_ABL_NO_COMPRESSION", "VCB_V2_ABL_NO_HTF"]:
        res = results_map[exp_id]
        delta_net_pnl = res["net_pnl_14bps"] - base_trend_res["net_pnl_14bps"]
        delta_pf = res["profit_factor"] - base_trend_res["profit_factor"]
        delta_trades = res["trade_count"] - base_trend_res["trade_count"]
        delta_friction = res["total_friction_usd"] - base_trend_res["total_friction_usd"]
        delta_dd = res["max_drawdown_pct"] - base_trend_res["max_drawdown_pct"]
        delta_exp = res["net_expectancy"] - base_trend_res["net_expectancy"]

        if res["net_pnl_14bps"] > base_trend_res["net_pnl_14bps"] and res["positive_folds"] == "3/3" and res["p_value_boot"] < 0.05:
            disp = "PROMISING_DEVELOPMENT / EDGE_UNCONFIRMED"
        elif res["net_pnl_14bps"] <= 0:
            disp = "REJECTED"
        elif res["net_pnl_14bps"] > 0 and res["net_pnl_14bps"] < base_trend_res["net_pnl_14bps"]:
            disp = "INCONCLUSIVE_SUB_BASELINE"
        else:
            disp = "INCONCLUSIVE"

        res["incremental_vs_ema_trend"] = {
            "delta_trades": delta_trades,
            "friction_saved_usd": round(-delta_friction, 2),
            "delta_net_pnl_usd": round(delta_net_pnl, 2),
            "delta_profit_factor": round(delta_pf, 2),
            "delta_expectancy_usd": round(delta_exp, 2),
            "delta_max_drawdown_pct": round(delta_dd, 2),
            "disposition": disp,
        }
        res["disposition"] = disp

    # Serialize results payload
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / "m4_vcb_v2_pilot_results.json"
    payload = {
        "execution_timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "milestone": "M4_VCB_V2_BOUNDED_PILOT",
        "development_window": "2023-01-01 to 2025-12-31",
        "burned_windows": {
            "h1_2026": "2026-01-01 to 2026-06-30 (BURNED_FOR_PROMOTION)",
            "h2_2026": "2026-07-01 to 2026-11-09 (BURNED_FOR_SUCCESSOR_SELECTION)",
        },
        "results": results_map,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"\n[Complete] Results saved to {out_path}")
    return payload


if __name__ == "__main__":
    import copy
    run_vcb_pilot()
