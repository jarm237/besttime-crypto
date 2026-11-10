"""
btc_scraper/research/ml_payoff_sizing/payoff_dataset.py

Constructs the continuous payoff dataset for M4-ML2.
Target: target_net_return_bps = (realized_net_pnl / entry_notional) * 10,000.
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


def compute_target_bps(net_pnl: float, notional: float) -> float:
    """Computes normalized return in basis points: (net_pnl / notional) * 10,000."""
    if notional <= 0.0:
        return 0.0
    return float((net_pnl / notional) * 10000.0)


def build_payoff_dataset(
    candles_by_symbol: Mapping[str, List[Dict[str, Any]]],
    output_manifest_path: Optional[Path] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Simulates base_ema_trend on 2023-2025 candles, extracts non-lookahead features
    at signal bar close, and calculates scale-independent normalized payoff targets in bps.
    """
    spec = ExperimentSpec(
        experiment_id="m4_ml2_payoff_dataset_generation",
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

        signal_idx = entry_idx - 1
        signal_candle = candles_by_symbol[sym][signal_idx]
        signal_time = str(signal_candle["time"])

        features = extract_features_at_bar(
            symbol_candles=candles_by_symbol[sym],
            bar_idx=signal_idx,
            btc_candles=btc_candles,
        )

        notional = float(t.get("notional", 2000.0))
        net_pnl = float(t.get("net_pnl", 0.0))
        target_bps = compute_target_bps(net_pnl, notional)
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
            "invested_notional": notional,
            "gross_pnl": float(t.get("gross_pnl", 0.0)),
            "fee_usd": float(t.get("fee_usd", 0.0)),
            "slippage_usd": float(t.get("slippage_usd", 0.0)),
            "spread_usd": float(t.get("spread_usd", 0.0)),
            "total_friction_usd": float(t.get("fee_usd", 0.0)) + float(t.get("slippage_usd", 0.0)) + float(t.get("spread_usd", 0.0)),
            "net_pnl_14bps": net_pnl,
            "target_net_return_bps": round(target_bps, 2),
            "label": label,
            "features": features,
        }
        dataset_rows.append(row)

    dataset_rows.sort(key=lambda r: (r["signal_time"], r["symbol"]))

    bps_values = [r["target_net_return_bps"] for r in dataset_rows]
    dataset_content_str = json.dumps(dataset_rows, sort_keys=True)
    dataset_hash = hashlib.sha256(dataset_content_str.encode("utf-8")).hexdigest()

    manifest = {
        "manifest_version": "1.0.0",
        "dataset_id": "m4_ml2_payoff_dataset_v1",
        "dataset_content_hash": dataset_hash,
        "development_window": ["2023-01-01T00:00:00Z", "2025-12-31T23:00:00Z"],
        "universe": list(spec.symbol_universe),
        "total_trades": len(dataset_rows),
        "mean_return_bps": round(float(pd.Series(bps_values).mean()), 2),
        "median_return_bps": round(float(pd.Series(bps_values).median()), 2),
        "std_return_bps": round(float(pd.Series(bps_values).std()), 2),
        "min_return_bps": round(float(min(bps_values)), 2),
        "max_return_bps": round(float(max(bps_values)), 2),
        "p25_return_bps": round(float(pd.Series(bps_values).quantile(0.25)), 2),
        "p75_return_bps": round(float(pd.Series(bps_values).quantile(0.75)), 2),
        "target_definition": "target_net_return_bps = (net_pnl_14bps / invested_notional) * 10000.0",
        "feature_names": FEATURE_NAMES,
        "research_designation": "ADAPTIVE_DEVELOPMENT_RESEARCH",
    }

    if output_manifest_path is not None:
        output_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_manifest_path, "w", encoding="utf-8") as f:
            json.dump({"manifest": manifest, "trades": dataset_rows}, f, indent=2)

    return dataset_rows, manifest
