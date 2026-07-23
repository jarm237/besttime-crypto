#!/usr/bin/env python3
"""
CLI Script: Tìm quan hệ causal giữa các coin và tạo tín hiệu CAUSAL ANOMALY.

Usage examples:
    # Chạy với demo data (không cần dữ liệu thực)
    python scripts/find_coin_causal_relations.py --demo

    # Chạy với file CSV giá coin
    python scripts/find_coin_causal_relations.py \\
        --input data/coin_prices.csv \\
        --coins BTC ETH SOL AVAX \\
        --output data/causal_coin_graph.json

    # Chạy với rl_candle_cache.pkl (multi-coin cache)
    python scripts/find_coin_causal_relations.py \\
        --cache data/rl_candle_cache.pkl \\
        --timeframe 15m \\
        --coins BTC ETH SOL BNB XRP AVAX DOGE LINK MATIC OP ARB \\
        --output data/causal_coin_graph.json \\
        --signal-output data/causal_anomaly_signals.parquet

    # Chạy với latest_signals.json (fallback)
    python scripts/find_coin_causal_relations.py \\
        --signals data/latest_signals.json \\
        --output data/causal_coin_graph.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# Ensure repo root is on PYTHONPATH
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from btc_scraper.ml_engine.coin_causal_finder import (
    CoinCausalGraph,
    CoinCausalRelationFinder,
    DEFAULT_COINS,
)
from btc_scraper.ml_engine.causal_anomaly_signal import (
    CausalAnomalyConfig,
    CausalAnomalySignalGenerator,
)

logger = logging.getLogger(__name__)

# ─── Data Loaders ─────────────────────────────────────────────────────────────

def _load_from_csv(path: str, coins: List[str]) -> pd.DataFrame:
    """Load giá coin từ CSV. Expect columns = coin names hoặc coin+suffix."""
    logger.info(f"Loading CSV: {path}")
    df = pd.read_csv(path, parse_dates=True)

    # Detect index column
    for col in ["timestamp", "date", "time", "index"]:
        if col in df.columns:
            df = df.set_index(col)
            break

    # Filter to requested coins
    available = [c for c in coins if c in df.columns]
    if not available:
        logger.warning(f"Không tìm thấy columns {coins} trong {list(df.columns)}")
        return pd.DataFrame()

    logger.info(f"Found {len(available)} coins in CSV: {available}")
    return df[available].dropna(how="all")


def _load_from_pkl_cache(
    path: str,
    coins: List[str],
    timeframe: str = "15m",
) -> pd.DataFrame:
    """
    Load từ rl_candle_cache.pkl.
    Format: dict[symbol → DataFrame(OHLCV per timeframe)] hoặc
            dict[symbol → dict[timeframe → DataFrame]]
    """
    logger.info(f"Loading pkl cache: {path}")
    try:
        from btc_scraper.ml_engine.governed_artifact_loader import load_trusted_pickle
        cache = load_trusted_pickle(path, approved_root=Path(path).resolve().parent)
    except Exception as e:
        logger.error(f"Failed to load pkl: {e}")
        return pd.DataFrame()

    if not isinstance(cache, dict):
        logger.warning("Cache format không phải dict, bỏ qua")
        return pd.DataFrame()

    price_dict: Dict[str, pd.Series] = {}

    for coin in coins:
        # Try various symbol formats
        for sym in [f"{coin}USDT", f"{coin}/USDT", f"{coin}USDT:USDT", coin]:
            if sym not in cache:
                continue
            data = cache[sym]

            # Handle nested dict (timeframe → df)
            if isinstance(data, dict):
                if timeframe in data:
                    data = data[timeframe]
                else:
                    # Lấy frame đầu tiên
                    data = next(iter(data.values()))

            if not isinstance(data, pd.DataFrame):
                continue

            # Lấy cột close
            for close_col in ["close", "Close", "c"]:
                if close_col in data.columns:
                    price_dict[coin] = data[close_col]
                    logger.debug(f"  {coin}: loaded {len(price_dict[coin])} rows from '{sym}'")
                    break
            break  # Found the coin

    if not price_dict:
        logger.warning("Không load được coin nào từ pkl cache")
        return pd.DataFrame()

    df = pd.DataFrame(price_dict)
    df = df.dropna(how="all")
    logger.info(f"Loaded {len(df)} rows, {len(df.columns)} coins from cache")
    return df


def _load_from_signals_json(path: str, coins: List[str]) -> pd.DataFrame:
    """
    Load từ latest_signals.json hoặc adaptive_signals_v2.json.
    Extract close price per coin per timestamp.
    """
    logger.info(f"Loading signals JSON: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load JSON: {e}")
        return pd.DataFrame()

    if isinstance(data, list):
        signals = data
    elif isinstance(data, dict) and "signals" in data:
        signals = data["signals"]
    else:
        signals = []

    if not signals:
        logger.warning("Không có signals nào trong file")
        return pd.DataFrame()

    # Build pivot: timestamp × coin → close price
    rows = []
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        ts = sig.get("timestamp") or sig.get("entry_time")
        coin_raw = sig.get("coin") or sig.get("symbol") or ""
        # Normalize coin name
        coin = coin_raw.upper().replace("USDT", "").replace("/", "").replace("-PERP", "")
        close = sig.get("close") or sig.get("entry_price") or sig.get("price")
        if ts and coin and close:
            rows.append({"timestamp": ts, "coin": coin, "close": float(close)})

    if not rows:
        logger.warning("Không extract được rows từ signals")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Filter coins
    df = df[df["coin"].isin(coins)]
    if df.empty:
        logger.warning(f"Không có signals nào cho coins {coins}")
        return pd.DataFrame()

    # Pivot
    pivot = df.pivot_table(
        index="timestamp", columns="coin", values="close", aggfunc="last"
    )
    pivot = pivot.sort_index()
    logger.info(f"Loaded {len(pivot)} timestamps, {len(pivot.columns)} coins from signals")
    return pivot


def _load_data(args: argparse.Namespace, coins: List[str]) -> pd.DataFrame:
    """Load dữ liệu từ nguồn phù hợp."""
    if args.demo:
        logger.info("Using demo synthetic data")
        return CoinCausalRelationFinder.generate_demo_data(coins=coins[:8], n=600)

    if hasattr(args, "cache") and args.cache and Path(args.cache).exists():
        return _load_from_pkl_cache(args.cache, coins, getattr(args, "timeframe", "15m"))

    if hasattr(args, "input") and args.input and Path(args.input).exists():
        return _load_from_csv(args.input, coins)

    if hasattr(args, "signals") and args.signals and Path(args.signals).exists():
        return _load_from_signals_json(args.signals, coins)

    # Auto-detect từ repo
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        repo_root / "data" / "rl_candle_cache.pkl",
        repo_root / "data" / "latest_signals.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            logger.info(f"Auto-detected data source: {candidate}")
            if candidate.suffix == ".pkl":
                return _load_from_pkl_cache(str(candidate), coins)
            else:
                return _load_from_signals_json(str(candidate), coins)

    logger.warning("Không tìm thấy nguồn dữ liệu — sử dụng demo data")
    return CoinCausalRelationFinder.generate_demo_data(coins=coins[:8], n=600)


# ─── Output Helpers ───────────────────────────────────────────────────────────

def _print_graph_report(graph: CoinCausalGraph) -> None:
    """Print causal graph results to console."""
    print("\n" + "=" * 70)
    print("  CAUSAL COIN GRAPH - RESULTS")
    print("=" * 70)
    print(f"\n[GRAPH] {graph.summary()}")

    if not graph.pairs:
        print("\n  [WARN] No causal relations found.")
        print(f"     (Try reducing min_correlation or adding more data)")
        return

    # Group by cluster pair
    intra = [p for p in graph.pairs if p.is_intra_cluster]
    inter = [p for p in graph.pairs if not p.is_intra_cluster]

    if intra:
        print(f"\n[INTRA-CLUSTER] Intra-cluster pairs ({len(intra)}):")
        for p in intra:
            arrow = "->" if p.effect == "positive" else "~>"
            print(
                f"   [{p.leader_cluster:8s}] {p.leader:6s} {arrow} {p.follower:6s} | "
                f"lag={p.lag:2d}c | corr={p.correlation:+.3f} | "
                f"conf={p.confidence:.2f} | {p.effect}"
            )

    if inter:
        print(f"\n[INTER-CLUSTER] Inter-cluster pairs ({len(inter)}):")
        for p in inter:
            arrow = "->" if p.effect == "positive" else "~>"
            print(
                f"   [{p.leader_cluster:8s}->{p.follower_cluster:8s}] "
                f"{p.leader:6s} {arrow} {p.follower:6s} | "
                f"lag={p.lag:2d}c | corr={p.correlation:+.3f} | "
                f"conf={p.confidence:.2f}"
            )

    # Adjacency summary
    adj = graph.get_adjacency()
    print(f"\n[RANKING] Leaders by number of followers:")
    leaders_ranked = sorted(adj.items(), key=lambda x: len(x[1]), reverse=True)
    for leader, followers in leaders_ranked:
        print(f"   {leader:6s} -> {len(followers)} followers: {followers}")


def _print_anomaly_report(reports: dict) -> None:
    """In anomaly report ra console."""
    if not reports:
        return
    print("\n" + "=" * 70)
    print("  CAUSAL ANOMALY REPORT")
    print("=" * 70)
    print(f"\n{'Coin':6s} | {'Anomalies':10s} | {'Bullish':7s} | {'Bearish':7s} | "
          f"{'Strong':6s} | {'Rate':7s} | {'Max Z':7s}")
    print("-" * 65)
    for coin, rpt in sorted(reports.items()):
        print(
            f"{coin:6s} | {rpt.n_anomalies:10d} | {rpt.n_bullish:7d} | "
            f"{rpt.n_bearish:7d} | {rpt.n_strong:6d} | "
            f"{rpt.anomaly_rate:6.1%} | {rpt.max_anomaly_score:7.2f}"
        )


# ─── Main ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tìm quan hệ causal giữa các coin và tạo tín hiệu CAUSAL ANOMALY",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Data sources (mutual exclusive group)
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--demo", action="store_true",
                     help="Chạy với demo synthetic data")
    src.add_argument("--input", type=str,
                     help="CSV file với giá coin (columns = coin names)")
    src.add_argument("--cache", type=str,
                     help="rl_candle_cache.pkl từ thư mục data/")
    src.add_argument("--signals", type=str,
                     help="latest_signals.json hoặc adaptive_signals_v2.json")

    # Coins
    parser.add_argument(
        "--coins", nargs="+", default=DEFAULT_COINS[:12],
        help=f"Danh sách coins. Default: {DEFAULT_COINS[:12]}"
    )

    # Finder parameters
    parser.add_argument("--max-lag", type=int, default=12,
                        help="Max lag candles để test (default: 12)")
    parser.add_argument("--min-correlation", type=float, default=0.20,
                        help="Min correlation threshold (default: 0.20)")
    parser.add_argument("--max-pvalue", type=float, default=0.10,
                        help="Max Granger p-value (default: 0.10)")
    parser.add_argument("--timeframe", type=str, default="15m",
                        help="Timeframe khi load từ pkl cache (default: 15m)")

    # Signal parameters
    parser.add_argument("--anomaly-threshold", type=float, default=2.0,
                        help="Z-score threshold cho CAUSAL ANOMALY (default: 2.0)")
    parser.add_argument("--strong-threshold", type=float, default=3.0,
                        help="Z-score threshold cho strong anomaly (default: 3.0)")
    parser.add_argument("--rolling-window", type=int, default=48,
                        help="Rolling window cho z-score (default: 48)")

    # Outputs
    parser.add_argument("--output", type=str, default="data/causal_coin_graph.json",
                        help="Output path cho coin causal graph JSON")
    parser.add_argument("--signal-output", type=str, default=None,
                        help="Output path cho anomaly signals parquet (optional)")
    parser.add_argument("--report-output", type=str, default=None,
                        help="Output path cho anomaly report JSON (optional)")

    # Misc
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose logging")

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    print("\n" + "=" * 70)
    print("  COIN CAUSAL RELATION FINDER + CAUSAL ANOMALY SIGNAL")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    # ── Load Data ────────────────────────────────────────────────────────────
    print(f"\n[DATA] Loading data for coins: {args.coins}")
    data = _load_data(args, args.coins)

    if data.empty:
        print("[ERROR] Khong load duoc du lieu!")
        return 1

    print(f"   Data shape: {data.shape}")
    print(f"   Coins available: {list(data.columns)}")

    # ── Run Finder ───────────────────────────────────────────────────────────
    print(f"\n[SEARCH] Chay CoinCausalRelationFinder...")
    print(f"   max_lag={args.max_lag} | min_correlation={args.min_correlation} | "
          f"max_pvalue={args.max_pvalue}")

    finder = CoinCausalRelationFinder(
        coins=list(data.columns),
        max_lag=args.max_lag,
        min_correlation=args.min_correlation,
        max_pvalue=args.max_pvalue,
    )
    graph = finder.run(data)

    _print_graph_report(graph)

    # ── Save Graph ───────────────────────────────────────────────────────────
    output_path = args.output
    print(f"\n[SAVE] Saving causal graph to '{output_path}'...")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    saved = finder.save(graph, output_path)
    print(f"   {'[OK] Saved' if saved else '[FAIL] Failed to save'}")

    if not graph.pairs:
        print("\n[WARN] Khong co pairs nao - bo qua buoc tao anomaly signals")
        return 0

    # ── Generate Anomaly Signals ─────────────────────────────────────────────
    print(f"\n[SIGNAL] Generating CAUSAL ANOMALY signals...")
    print(f"   anomaly_threshold={args.anomaly_threshold} | "
          f"strong_threshold={args.strong_threshold} | "
          f"rolling_window={args.rolling_window}")

    config = CausalAnomalyConfig(
        anomaly_z_threshold=args.anomaly_threshold,
        strong_z_threshold=args.strong_threshold,
        rolling_window=args.rolling_window,
    )
    gen = CausalAnomalySignalGenerator(config=config)
    signals_df = gen.generate(data, graph)
    reports = gen.generate_report(data, graph)

    _print_anomaly_report(reports)

    # ── Save Signals ─────────────────────────────────────────────────────────
    if args.signal_output:
        sig_path = Path(args.signal_output)
        sig_path.parent.mkdir(parents=True, exist_ok=True)
        signals_df.to_parquet(sig_path, index=True)
        print(f"\n💾 Anomaly signals saved to '{sig_path}'")

    if args.report_output:
        rpt_path = Path(args.report_output)
        rpt_path.parent.mkdir(parents=True, exist_ok=True)
        report_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "graph_summary": graph.summary(),
            "config": config.to_dict(),
            "coins_analyzed": list(reports.keys()),
            "per_coin": {coin: rpt.to_dict() for coin, rpt in reports.items()},
        }
        with open(rpt_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        print(f"[SAVE] Anomaly report saved to '{rpt_path}'")

    print("\n[DONE]\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
