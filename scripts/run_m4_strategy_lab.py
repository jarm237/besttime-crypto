"""
scripts/run_m4_strategy_lab.py
Phase M4: Walk-Forward Economic Screening Laboratory Runner.

Executes baseline and candidate strategies across chronological folds on verified historical data (BTC/ETH).
Generates an empirical comparison report with economic metrics and candidate dispositions.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.research.dataset_manifest import CanonicalDatasetManifest
from btc_scraper.research.dataset_provider import HistoricalDatasetProvider
from btc_scraper.research.experiment_contract import (
    ExperimentSpec,
    build_seven_layer_proxy_spec,
)
from btc_scraper.research.strategy_registry import GLOBAL_STRATEGY_REGISTRY
from btc_scraper.research.walk_forward_lab import (
    WalkForwardLab,
    WalkForwardSplitter,
)


def run_screening():
    manifest_path = REPO_ROOT / "data/dataset_manifests/canonical_binance_2023_2026_manifest.json"
    data_dir = REPO_ROOT / "data/fresh_training_data_2023_2026"

    print("=" * 80)
    print("M4 Strategy Laboratory: Walk-Forward Economic Screening")
    print(f"Dataset Manifest: {manifest_path}")
    print("=" * 80)

    canonical_manifest = CanonicalDatasetManifest.load(manifest_path)
    provider = HistoricalDatasetProvider(canonical_manifest, data_dir, verify_checksums=False)
    lab = WalkForwardLab(provider, GLOBAL_STRATEGY_REGISTRY)

    # Historical scope: 2023-01 to 2026-04-30
    # May-June 2026 is strictly reserved as Frozen OOS Holdout!
    start_time = "2023-01-01T00:00:00Z"
    end_time = "2026-04-30T23:59:59Z"

    # Generate 3 chronological walk-forward folds
    folds = WalkForwardSplitter.generate_folds(
        start_time=start_time,
        end_time=end_time,
        n_folds=3,
        val_ratio=0.30,      # 30% validation (~14 months across 3 folds)
        purge_gap_hours=24,  # 24h embargo between train and validation
    )

    print("\n[Walk-Forward Folds Plan]")
    for f in folds:
        print(f"  Fold {f.fold_id}: Val Window = {f.val_start[:10]} -> {f.val_end[:10]} (Train ends {f.train_end[:10]}, Purge {f.purge_gap_hours}h)")

    # Base experiment specification (Initial Capital $10,000, canonical cost 14 bps)
    base_spec = build_seven_layer_proxy_spec(
        experiment_id="m4_screening_v1",
        oos_window=(start_time, end_time),
    )

    strategy_ids = [
        "always_flat_v1",
        "buy_and_hold_v1",
        "sma_crossover_9_21_v1",
        "ema_trend_12_26_v1",
        "rsi_bollinger_mr_v1",
        "regime_aware_trend_v1",
        "vol_aware_mean_reversion_v1",
        "seven_layer_proxy_v1",
    ]
    symbols = ["BTCUSDT", "ETHUSDT"]

    print("\nExecuting multi-fold screening across symbols...")
    results = lab.run_screening_suite(
        symbols=symbols,
        strategy_ids=strategy_ids,
        timeframe="1h",
        folds=folds,
        base_spec=base_spec,
    )

    # Print summary table
    print("\n" + "=" * 115)
    print(f"{'Symbol':<9} {'Strategy':<30} {'Tier':<10} {'Trades':<7} {'WinRate':<8} {'ProfitFactor':<13} {'Net PnL ($)':<13} {'MaxDD':<8} {'Disposition'}")
    print("-" * 115)

    out_records = {}
    for sym, summaries in results.items():
        out_records[sym] = []
        for s in summaries:
            wr_str = f"{s.aggregate_win_rate * 100:.1f}%" if s.aggregate_win_rate is not None else "N/A"
            pf_str = f"{s.aggregate_profit_factor:.2f}" if s.aggregate_profit_factor is not None else "N/A"
            dd_str = f"{s.max_drawdown * 100:.1f}%"
            print(
                f"{sym:<9} {s.strategy_name:<30} {s.tier:<10} {s.total_trades:<7d} "
                f"{wr_str:<8} {pf_str:<13} "
                f"{s.total_net_pnl:<+13.2f} {dd_str:<8} {s.disposition}"
            )
            out_records[sym].append(s.to_dict())

    print("=" * 115)

    # Save artifact
    out_file = REPO_ROOT / "data/backtests/m4_screening_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out_records, f, indent=2)
    print(f"\nFull screening results saved to: {out_file}")

    return results


if __name__ == "__main__":
    run_screening()
