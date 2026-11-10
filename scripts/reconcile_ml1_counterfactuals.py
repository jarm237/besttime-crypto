"""
scripts/reconcile_ml1_counterfactuals.py

Deep investigative script reconciling Phase A trade-level counterfactuals vs
portfolio-level backtest simulations in M4-ML1.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import pandas as pd
import numpy as np

from btc_scraper.research.baseline_runner import ExperimentRunner
from btc_scraper.research.experiment_contract import ExperimentSpec
from btc_scraper.research.ml_trade_quality.dataset_builder import build_trade_quality_dataset
from btc_scraper.research.ml_trade_quality.ml_filtered_strategy import MlFilteredEmaTrendStrategy
from btc_scraper.research.ml_trade_quality.purged_walk_forward_trainer import PurgedWalkForwardTrainer
from btc_scraper.research.strategy_registry import EmaTrendFollowingStrategy
from btc_scraper.research.walk_forward_lab import WalkForwardSplitter
from scripts.run_m4_successor_pilot import (
    load_development_candles_with_warmup,
    enrich_4h_closed_candles,
)

# 1. Load data
btc_raw = load_development_candles_with_warmup("BTCUSDT", "2023-01", "2025-12")
eth_raw = load_development_candles_with_warmup("ETHUSDT", "2023-01", "2025-12")
btc_enriched = enrich_4h_closed_candles(btc_raw)
eth_enriched = enrich_4h_closed_candles(eth_raw)
candles_by_symbol = {"BTCUSDT": btc_enriched, "ETHUSDT": eth_enriched}

# 2. Re-run dataset & trainer
trade_dataset, dataset_manifest = build_trade_quality_dataset(candles_by_symbol)
folds = WalkForwardSplitter.generate_folds(
    start_time="2023-01-01T00:00:00Z",
    end_time="2025-12-31T23:00:00Z",
    n_folds=3,
    val_ratio=0.33,
    purge_gap_hours=24,
)
trainer = PurgedWalkForwardTrainer(folds)
ml_eval = trainer.train_and_evaluate(trade_dataset)

# 3. Collect trades from fold simulations vs static dataset
fold_base_trades = []
fold_ml_trades = []

for fold in folds:
    fid = fold.fold_id
    model_pack = trainer.trained_models.get(fid, {})
    th = model_pack.get("threshold", 0.20)

    f_spec = ExperimentSpec(
        experiment_id=f"fold_{fid}_diag",
        strategy_id="fold_eval",
        strategy_version="1.0.0",
        dataset_manifest_identity="canonical_binance_2023_2026_manifest",
        dataset_content_hash="c4ab114eefdd01cfd7edee3ae1352c06aa24822469bfe414ca1743677ca8edf2",
        feature_set_version="raw_1h_spot_v1",
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

    strat_base = EmaTrendFollowingStrategy(12, 26)
    r_base = ExperimentRunner(f_spec, liquidate_at_end=True).run(strat_base, candles_by_symbol)
    for t in r_base.trade_lineage:
        t_copy = dict(t)
        t_copy["fold_id"] = fid
        fold_base_trades.append(t_copy)

    strat_ml = MlFilteredEmaTrendStrategy(model_dict=model_pack, threshold=th)
    r_ml = ExperimentRunner(f_spec, liquidate_at_end=True).run(strat_ml, candles_by_symbol)
    for t in r_ml.trade_lineage:
        t_copy = dict(t)
        t_copy["fold_id"] = fid
        fold_ml_trades.append(t_copy)

print(f"Total Fold Baseline Trades: {len(fold_base_trades)}, Total PnL: {sum(t['net_pnl'] for t in fold_base_trades):.2f}")
print(f"Total Fold ML Trades: {len(fold_ml_trades)}, Total PnL: {sum(t['net_pnl'] for t in fold_ml_trades):.2f}")
print(f"Total Static OOF Trades: {len(ml_eval['predictions'])}, Filtered: {sum(1 for p in ml_eval['predictions'] if p['accepted'])}")

# Analyze the difference between fold_base_trades (320) and static OOF trades (314)
# In static dataset, trades were extracted from the 36-MONTH run, and then filtered by signal_time in [val_start, val_end].
# In fold simulation, ExperimentRunner runs on the SLICE of candles in [val_start, val_end]!
print("\n=== Check initial state / liquidation trades in fold simulations ===")
for fid in [1, 2, 3]:
    fb = [t for t in fold_base_trades if t["fold_id"] == fid]
    fml = [t for t in fold_ml_trades if t["fold_id"] == fid]
    soof = [p for p in ml_eval["predictions"] if p["fold_id"] == fid]
    print(f"Fold {fid}: Runner Base Trades = {len(fb)}, Runner ML Trades = {len(fml)}, Static OOF Trades = {len(soof)}")
    
    # Check if there are liquidation trades at end of fold
    liq_fb = [t for t in fb if t.get("reason") == "end_of_window_liquidation"]
    print(f"  Fold {fid} End-of-window liquidations in Runner Base: {len(liq_fb)}")

# Now compare fold_base_trades vs fold_ml_trades trade by trade!
print("\n=== Trade by Trade Matching between Runner Base and Runner ML ===")
matched = 0
unmatched_base = []
unmatched_ml = []
diff_pnl_trades = []

# Map by (symbol, entry_time)
ml_map = {(t["symbol"], str(t["entry_time"])): t for t in fold_ml_trades}

for tb in fold_base_trades:
    key = (tb["symbol"], str(tb["entry_time"]))
    if key in ml_map:
        matched += 1
        tml = ml_map[key]
        pnl_diff = tml["net_pnl"] - tb["net_pnl"]
        notional_diff = tml["notional"] - tb["notional"]
        if abs(pnl_diff) > 0.01 or abs(notional_diff) > 0.01:
            diff_pnl_trades.append({
                "symbol": tb["symbol"],
                "entry_time": tb["entry_time"],
                "base_notional": tb["notional"],
                "ml_notional": tml["notional"],
                "base_net": tb["net_pnl"],
                "ml_net": tml["net_pnl"],
                "pnl_diff": pnl_diff,
            })
    else:
        unmatched_base.append(tb)

base_keys = {(tb["symbol"], str(tb["entry_time"])) for tb in fold_base_trades}
for tml in fold_ml_trades:
    key = (tml["symbol"], str(tml["entry_time"]))
    if key not in base_keys:
        unmatched_ml.append(tml)

print(f"Matched trades: {matched}")
print(f"Unmatched Base (Rejected by ML): {len(unmatched_base)}")
print(f"Unmatched ML (New trades in ML runner): {len(unmatched_ml)}")
print(f"Matched trades with sizing/PnL difference: {len(diff_pnl_trades)}")

print("\n--- Summary of Unmatched Base Trades (Rejected) ---")
for t in unmatched_base:
    print(f"  Fold {t['fold_id']} {t['symbol']} entry={t['entry_time']} exit={t['exit_time']} hold={t['hold_bars']} net={t['net_pnl']:.2f} reason={t.get('reason')}")
pnl_rejected = sum(t["net_pnl"] for t in unmatched_base)
print(f"Total Net PnL of Rejected Base Trades in Runner: ${pnl_rejected:.2f}")

print("\n--- Summary of Unmatched ML Trades (New) ---")
for t in unmatched_ml:
    print(f"  Fold {t['fold_id']} {t['symbol']} entry={t['entry_time']} exit={t['exit_time']} hold={t['hold_bars']} net={t['net_pnl']:.2f}")
pnl_new_ml = sum(t["net_pnl"] for t in unmatched_ml)
print(f"Total Net PnL of New ML Trades in Runner: ${pnl_new_ml:.2f}")

print("\n--- Sizing & Cash Compounding Differences on Matched Trades ---")
total_sizing_diff_pnl = sum(d["pnl_diff"] for d in diff_pnl_trades)
print(f"Sum of PnL differences on matched trades due to sizing: ${total_sizing_diff_pnl:.2f}")
if diff_pnl_trades:
    print(f"  First 3 sizing diffs: {diff_pnl_trades[:3]}")
    print(f"  Last 3 sizing diffs: {diff_pnl_trades[-3:]}")

print("\n=== EXACT BRIDGE DECOMPOSITION ===")
print(f"Baseline Runner Net: {sum(t['net_pnl'] for t in fold_base_trades):.2f}")
print(f"Rejected Trades Impact (- PnL_rejected): {-pnl_rejected:.2f}")
print(f"New ML Trades Impact (+ PnL_new): {pnl_new_ml:.2f}")
print(f"Sizing / Compounding Impact on Matched: {total_sizing_diff_pnl:.2f}")
reconciled_ml = sum(t['net_pnl'] for t in fold_base_trades) - pnl_rejected + pnl_new_ml + total_sizing_diff_pnl
print(f"Reconciled ML Net: {reconciled_ml:.2f}")
print(f"Actual ML Runner Net: {sum(t['net_pnl'] for t in fold_ml_trades):.2f}")
print(f"Residual: {sum(t['net_pnl'] for t in fold_ml_trades) - reconciled_ml:.4f}")
