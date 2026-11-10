"""
btc_scraper/research/ml_trade_quality/dataset_builder.py

Builds the trade-level training dataset for M4-ML1 Trade Quality modeling.
Extracts features at signal candle close and records realized trade outcomes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import pandas as pd

from btc_scraper.research.baseline_runner import ExperimentRunner
from btc_scraper.research.experiment_contract import ExperimentSpec
from btc_scraper.research.ml_trade_quality.feature_contract import (
    FEATURE_NAMES,
    extract_features_at_bar,
)
from btc_scraper.research.strategy_registry import EmaTrendFollowingStrategy


def build_trade_quality_dataset(
    candles_by_symbol: Mapping[str, List[Dict[str, Any]]],
    output_manifest_path: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Simulates base_ema_trend on 2023-2025 candles, extracts non-lookahead features
    at the signal bar close, and forms the trade-level dataset with binary win/loss labels.
    """
    # 1. Setup canonical 14 bps baseline spec
    spec = ExperimentSpec(
        experiment_id="m4_ml1_dataset_generation",
        strategy_id="ema_trend_following",
        strategy_version="1.0.0",
        dataset_manifest_identity="canonical_binance_2023_2026_manifest",
        dataset_content_hash="c4ab114eefdd01cfd7edee3ae1352c06aa24822469bfe414ca1743677ca8edf2",
        feature_set_version="raw_1h_spot_v1",
        symbol_universe=tuple(sorted(candles_by_symbol.keys())),
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

    strat = EmaTrendFollowingStrategy(12, 26)
    runner = ExperimentRunner(spec, liquidate_at_end=True)
    res = runner.run(strat, candles_by_symbol)

    trades = list(res.trade_lineage)
    btc_candles = candles_by_symbol.get("BTCUSDT")

    # Build candle lookup index: time -> index
    time_to_idx = {
        sym: {str(c["time"]): i for i, c in enumerate(candles)}
        for sym, candles in candles_by_symbol.items()
    }

    dataset_rows: List[Dict[str, Any]] = []

    for t in trades:
        sym = t["symbol"]
        entry_time = str(t["entry_time"])
        exit_time = str(t["exit_time"])
        entry_idx = time_to_idx[sym].get(entry_time)

        if entry_idx is None or entry_idx < 1:
            continue

        # Signal bar close was at entry_idx - 1 (preceding the NEXT_BAR_OPEN fill)
        signal_idx = entry_idx - 1
        signal_candle = candles_by_symbol[sym][signal_idx]
        signal_time = str(signal_candle["time"])

        # Extract features strictly at signal bar close
        features = extract_features_at_bar(
            symbol_candles=candles_by_symbol[sym],
            bar_idx=signal_idx,
            btc_candles=btc_candles,
        )

        net_pnl = float(t.get("net_pnl", 0.0))
        label = 1 if net_pnl > 0.0 else 0

        row = {
            "trade_id": str(t.get("trade_id")),
            "symbol": sym,
            "signal_idx": signal_idx,
            "signal_time": signal_time,
            "entry_idx": entry_idx,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "hold_bars": int(t.get("hold_bars", 1)),
            "entry_price": float(t.get("entry_price", 0.0)),
            "exit_price": float(t.get("exit_price", 0.0)),
            "invested_notional": float(t.get("notional", 0.0)),
            "gross_pnl": float(t.get("gross_pnl", 0.0)),
            "total_friction": float(t.get("fee_usd", 0.0)) + float(t.get("slippage_usd", 0.0)) + float(t.get("spread_usd", 0.0)),
            "net_pnl_14bps": net_pnl,
            "label": label,
            "features": features,
        }
        dataset_rows.append(row)

    # Sort dataset chronologically by signal_time
    dataset_rows.sort(key=lambda r: (r["signal_time"], r["symbol"]))

    # Summary statistics
    n_total = len(dataset_rows)
    n_wins = sum(1 for r in dataset_rows if r["label"] == 1)
    n_losses = sum(1 for r in dataset_rows if r["label"] == 0)
    win_rate = (n_wins / n_total) if n_total > 0 else 0.0

    btc_rows = [r for r in dataset_rows if r["symbol"] == "BTCUSDT"]
    eth_rows = [r for r in dataset_rows if r["symbol"] == "ETHUSDT"]

    # Manifest metadata
    dataset_content_str = json.dumps(dataset_rows, sort_keys=True)
    dataset_hash = hashlib.sha256(dataset_content_str.encode("utf-8")).hexdigest()

    manifest = {
        "manifest_version": "1.0.0",
        "dataset_id": "m4_ml1_trade_quality_dataset_v1",
        "dataset_content_hash": dataset_hash,
        "development_window": ["2023-01-01T00:00:00Z", "2025-12-31T23:00:00Z"],
        "universe": list(spec.symbol_universe),
        "total_trades": n_total,
        "win_count": n_wins,
        "loss_count": n_losses,
        "class_balance_win_pct": round(win_rate * 100.0, 2),
        "btc_trades": len(btc_rows),
        "btc_wins": sum(1 for r in btc_rows if r["label"] == 1),
        "eth_trades": len(eth_rows),
        "eth_wins": sum(1 for r in eth_rows if r["label"] == 1),
        "feature_names": FEATURE_NAMES,
        "label_contract": "label = 1 if trade_net_pnl_14bps > 0 else 0",
    }

    if output_manifest_path is not None:
        output_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_manifest_path, "w", encoding="utf-8") as f:
            json.dump({"manifest": manifest, "trades": dataset_rows}, f, indent=2)

    return dataset_rows, manifest
