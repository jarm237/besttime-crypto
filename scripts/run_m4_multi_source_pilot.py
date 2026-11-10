"""
scripts/run_m4_multi_source_pilot.py
Phase D: M4 Controlled Successor Research Pilot.

Evaluates whether multi-source context (basis, derivatives flow, macro yield slope) creates
genuine economic value over price-only baselines on historical development data (2023-01-01 to 2025-12-31).

Constraints & Invariants:
- Frozen candidate vol_aware_mean_reversion_v1 is strictly untouched.
- H1/2026 OOS period is strictly excluded (burned/holdout preserved).
- Identical 14 bps round-trip transaction costs (10 bps spot taker fee + 2 bps spread + 2 bps slippage).
- Spot long-only positions: derivatives funding cashflows are NOT deducted from spot PnL.
- Multi-fold chronological walk-forward accounting with 24h purge gap.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple
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
from btc_scraper.research.experiment_contract import ExperimentSpec
from btc_scraper.research.multi_source_features import MultiSourceFeatureProvider
from btc_scraper.research.multi_source_strategies import (
    BasisFilteredTrendStrategy,
    MacroFilteredMeanReversionStrategy,
    OiFilteredTrendStrategy,
)
from btc_scraper.research.strategy_registry import (
    EmaTrendFollowingStrategy,
    RsiBollingerMeanReversionStrategy,
)
from btc_scraper.research.walk_forward_lab import WalkForwardSplitter

EXISTING_SPOT_DIR = PROJECT_ROOT / "data" / "fresh_training_data_2023_2026"
REPORT_DIR = PROJECT_ROOT / "data" / "historical" / "quality_reports"


def load_development_candles(symbol: str, start_ym: str = "2023-01", end_ym: str = "2025-12") -> List[Dict[str, Any]]:
    """Loads and filters spot candles for development window 2023-01 to 2025-12 (36 months)."""
    sym_clean = symbol.replace("USDT", "")
    sym_dir = EXISTING_SPOT_DIR / sym_clean / "1h"
    
    # Generate month strings
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
    for ym in months:
        f = sym_dir / f"{sym_clean}_1h_{ym}.csv"
        if f.exists():
            df = pd.read_csv(f)
            # Remove warmup rows
            df_trade = df[df["is_warmup"] == 0].copy()
            for r in df_trade.to_dict(orient="records"):
                records.append(r)

    # Sort chronologically
    records.sort(key=lambda r: str(r.get("time", "")))
    return records


def compute_bootstrap_ci(net_returns: Sequence[float], n_bootstrap: int = 1000) -> Tuple[float, float]:
    """Calculates 95% bootstrap confidence interval for net returns per trade."""
    if len(net_returns) < 5:
        return 0.0, 0.0
    arr = np.array(net_returns)
    means = [np.mean(np.random.choice(arr, size=len(arr), replace=True)) for _ in range(n_bootstrap)]
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def run_controlled_pilot() -> Dict[str, Any]:
    print("=================================================================")
    print("   M4 CONTROLLED MULTI-SOURCE RESEARCH PILOT")
    print("   Development Horizon: 2023-01-01 to 2025-12-31 (36 Months)")
    print("   Holdout Integrity: H1/2026 Preserved / Untouched")
    print("   Cost Model: 14 bps Round-Trip (Spot Long-Only)")
    print("=================================================================\n")

    provider = MultiSourceFeatureProvider(metrics_latency_buffer_minutes=5)

    # 1. Load and enrich development candles
    print("[1/4] Loading and enriching development candles for BTC and ETH...")
    btc_raw = load_development_candles("BTCUSDT", "2023-01", "2025-12")
    eth_raw = load_development_candles("ETHUSDT", "2023-01", "2025-12")
    print(f"  BTC raw candles: {len(btc_raw)}, ETH raw candles: {len(eth_raw)}")

    btc_enriched = provider.enrich_candle_batch("BTCUSDT", btc_raw, secondary_symbol_candles=eth_raw)
    eth_enriched = provider.enrich_candle_batch("ETHUSDT", eth_raw, secondary_symbol_candles=btc_raw)
    print(f"  BTC enriched candles: {len(btc_enriched)}, ETH enriched candles: {len(eth_enriched)}")

    # 2. Experiment Spec setup
    base_spec = ExperimentSpec(
        experiment_id="m4_multi_source_pilot_2023_2025",
        strategy_id="pilot_multi_source",
        strategy_version="1.0.0",
        dataset_manifest_identity="canonical_m2_backfill_20261110",
        dataset_content_hash="c4ab114eefdd01cfd7edee3ae1352c06aa24822469bfe414ca1743677ca8edf2",
        feature_set_version="multi_source_v1",
        symbol_universe=("BTCUSDT", "ETHUSDT"),
        timeframe="1h",
        oos_window=("2023-01-01T00:00:00Z", "2025-12-31T23:59:59Z"),
        initial_capital=20_000.0,  # $10,000 per asset
        fee_model={
            "is_futures": False,
            "spot_maker_bps": 10.0,
            "spot_taker_bps": 10.0,
        },
        slippage_model={"enabled": True, "base_slippage_bps": 2.0},
        spread_model={"enabled": True, "typical_spread_bps": 2.0},
        execution_timing_policy="NEXT_BAR_OPEN",
    )

    # 3. Define candidate and benchmark strategies
    strategies: List[BaselineStrategy] = [
        AlwaysFlatStrategy(),
        PassiveBuyAndHoldStrategy(),
        EmaTrendFollowingStrategy(fast_period=12, slow_period=26),
        BasisFilteredTrendStrategy(fast_period=12, slow_period=26, min_basis_bps=0.0),
        OiFilteredTrendStrategy(fast_period=12, slow_period=26, min_taker_flow=1.0),
        RsiBollingerMeanReversionStrategy(rsi_period=14, rsi_oversold=30.0, rsi_exit=50.0, bb_period=20, bb_std=2.0),
        MacroFilteredMeanReversionStrategy(rsi_period=14, bb_period=20, bb_std=2.0, min_slope=-1.0),
    ]

    # Pre-registered hypotheses
    hypotheses = {
        "basis_filtered_trend_v1": "Filtering EMA trend entries with positive futures basis eliminates false breakouts during spot-led bearish drift.",
        "oi_filtered_trend_v1": "Filtering EMA trend entries with expanding taker flow (>1.0) improves win rate and reduces whipsaws.",
        "macro_filtered_mr_v1": "Filtering mean-reversion entries to avoid severe yield curve inversion (slope < -1.0%) avoids high-volatility credit cascade drawdowns.",
    }

    # 4. Chronological Walk-Forward Folds Setup
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

    candles_by_symbol = {
        "BTCUSDT": btc_enriched,
        "ETHUSDT": eth_enriched,
    }

    # 5. Run Evaluations
    print("\n[3/4] Running backtests and economic evaluations...")
    results_summary = []

    for strat in strategies:
        strat_name = strat.name
        
        # A. Full 3-Year Evaluation
        runner = ExperimentRunner(base_spec, liquidate_at_end=True)
        res = runner.run(strat, candles_by_symbol)
        
        # Economic metrics
        trades = list(res.trade_lineage)
        n_trades = res.total_trades
        net_pnls = [float(t.get("net_pnl", 0.0)) for t in trades]
        total_net_pnl = float(res.net_pnl)
        expectancy = (total_net_pnl / n_trades) if n_trades > 0 else 0.0
        
        win_rate = (float(res.win_rate) * 100.0) if res.win_rate is not None else 0.0
        profit_factor = float(res.profit_factor) if res.profit_factor is not None else 0.0
        max_dd_usd = float(res.max_drawdown_usd)
        max_dd_pct = float(res.max_drawdown_pct) if res.max_drawdown_pct is not None else 0.0
        total_fees = float(res.total_fees)
        total_slippage = float(res.total_slippage)

        # Asset breakdown
        btc_trades = [t for t in trades if t.get("symbol") == "BTCUSDT"]
        eth_trades = [t for t in trades if t.get("symbol") == "ETHUSDT"]
        btc_pnl = sum(float(t.get("net_pnl", 0.0)) for t in btc_trades)
        eth_pnl = sum(float(t.get("net_pnl", 0.0)) for t in eth_trades)

        # Bootstrap confidence interval for expectancy
        ci_low, ci_high = compute_bootstrap_ci(net_pnls)

        # B. Walk-Forward Fold Evaluation
        fold_summaries = []
        positive_folds = 0
        for fold in folds:
            fold_spec = ExperimentSpec(
                experiment_id=f"pilot_{strat_name}_fold_{fold.fold_id}",
                strategy_id=strat_name,
                strategy_version="1.0.0",
                dataset_manifest_identity="canonical_m2_backfill_20261110",
                dataset_content_hash="c4ab114eefdd01cfd7edee3ae1352c06aa24822469bfe414ca1743677ca8edf2",
                feature_set_version="multi_source_v1",
                symbol_universe=("BTCUSDT", "ETHUSDT"),
                timeframe="1h",
                oos_window=(fold.val_start, fold.val_end),
                initial_capital=20_000.0,
                fee_model={"is_futures": False, "spot_maker_bps": 10.0, "spot_taker_bps": 10.0},
                slippage_model={"enabled": True, "base_slippage_bps": 2.0},
                spread_model={"enabled": True, "typical_spread_bps": 2.0},
                execution_timing_policy="NEXT_BAR_OPEN",
            )
            fold_runner = ExperimentRunner(fold_spec, liquidate_at_end=True)
            f_res = fold_runner.run(strat, candles_by_symbol)
            f_net = float(f_res.net_pnl)
            if f_net > 0:
                positive_folds += 1
            fold_summaries.append({
                "fold_id": fold.fold_id,
                "train_window": [fold.train_start, fold.train_end],
                "val_window": [fold.val_start, fold.val_end],
                "trades": f_res.total_trades,
                "net_pnl_usd": round(f_net, 2),
                "profit_factor": round(float(f_res.profit_factor), 2) if f_res.profit_factor is not None else None,
                "win_rate_pct": round(float(f_res.win_rate) * 100.0, 1) if f_res.win_rate is not None else None,
            })

        # Disposition assignment
        disposition = "BENCHMARK"
        if strat.TIER == "CANDIDATE":
            if total_net_pnl > 0 and profit_factor > 1.2 and n_trades >= 15 and positive_folds >= 2:
                disposition = "PROMISING_DEVELOPMENT_CANDIDATE"
            elif total_net_pnl > 0:
                disposition = "MARGINAL_DEVELOPMENT_CANDIDATE"
            else:
                disposition = "REJECTED"

        summary_item = {
            "strategy_id": strat_name,
            "tier": strat.TIER,
            "hypothesis": hypotheses.get(strat_name, "N/A"),
            "trade_count": n_trades,
            "win_rate_pct": round(win_rate, 2),
            "net_pnl_usd": round(total_net_pnl, 2),
            "expectancy_per_trade_usd": round(expectancy, 2),
            "expectancy_95_ci": [round(ci_low, 2), round(ci_high, 2)],
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_usd": round(max_dd_usd, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "total_fee_usd": round(total_fees, 2),
            "total_slippage_usd": round(total_slippage, 2),
            "btc_pnl_usd": round(btc_pnl, 2),
            "btc_trade_count": len(btc_trades),
            "eth_pnl_usd": round(eth_pnl, 2),
            "eth_trade_count": len(eth_trades),
            "positive_folds": f"{positive_folds}/{len(folds)}",
            "fold_results": fold_summaries,
            "disposition": disposition,
        }
        results_summary.append(summary_item)

        print(f"  {strat_name:35s} | Trades: {n_trades:3d} | Net PnL: ${total_net_pnl:+8.2f} | PF: {profit_factor:5.2f} | DD: {max_dd_pct:5.2f}% | Folds+: {positive_folds}/3 | Disp: {disposition}")

    # 6. Save results report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = REPORT_DIR / "m4_multi_source_pilot_results.json"
    report_data = {
        "execution_timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "milestone": "M4_CONTROLLED_RESEARCH_PILOT",
        "dataset_manifest_hash": "c4ab114eefdd01cfd7edee3ae1352c06aa24822469bfe414ca1743677ca8edf2",
        "development_window": "2023-01-01 to 2025-12-31",
        "holdout_window": "2026-01-01 to 2026-06-30 (PRESERVED_UNTOUCHED)",
        "cost_model": "14 bps round-trip (10 bps fee + 2 bps slippage + 2 bps spread)",
        "results": results_summary,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    print(f"\n[4/4] Pilot execution completed. Full report saved to {out_file}")
    return report_data


if __name__ == "__main__":
    run_controlled_pilot()
