#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from btc_scraper.core.io import smart_read_csv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.feature_engineering.feature_store import FeatureStoreV2
from btc_scraper.feature_engineering.triple_barrier import TripleBarrierConfig, TripleBarrierLabeler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate triple barrier labels for Phase 8")
    parser.add_argument("--input", required=True, help="Signals input path (.json/.csv/.parquet)")
    parser.add_argument(
        "--output",
        default="data/feature_store/labels/triple_barrier_labels.parquet",
        help="Output path (.parquet/.csv)",
    )
    parser.add_argument("--data-dir", default="data", help="Directory containing OHLCV csv files")
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--max-holding-bars", type=int, default=48)
    parser.add_argument("--tp-atr-mult", type=float, default=2.0)
    parser.add_argument("--sl-atr-mult", type=float, default=1.2)
    parser.add_argument("--min-rr", type=float, default=1.3)
    parser.add_argument(
        "--output-format",
        choices=["auto", "parquet", "csv"],
        default="auto",
        help="Persist format for output and feature store",
    )
    return parser.parse_args()


def load_signals(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and "records" in raw:
            raw = raw["records"]
        if not isinstance(raw, list):
            raise ValueError("JSON input must be a list of records")
        return pd.DataFrame(raw)
    if suffix == ".csv":
        return smart_read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported input format: {suffix}")


def _read_csv_candle(path: Path) -> pd.DataFrame:
    from btc_scraper.core.io import smart_read_csv

    frame = smart_read_csv(path)
    frame["source_file"] = path.name
    return frame


def load_candles_for_coin(data_dir: Path, coin: str, timeframe: str) -> pd.DataFrame:
    pattern = f"*_{coin.upper()}_{timeframe}.csv"
    matches = sorted(data_dir.rglob(pattern))
    if not matches:
        return pd.DataFrame()

    frames = [_read_csv_candle(p) for p in matches]
    merged = pd.concat(frames, ignore_index=True)

    ts_col = "time" if "time" in merged.columns else "timestamp"
    if ts_col not in merged.columns:
        raise ValueError(f"Missing time/timestamp column for coin {coin}")
    merged[ts_col] = pd.to_datetime(merged[ts_col], utc=True, errors="coerce")
    merged = merged.dropna(subset=[ts_col]).sort_values(ts_col)

    merged = merged.drop_duplicates(subset=[ts_col], keep="last")
    if ts_col != "timestamp":
        merged = merged.rename(columns={ts_col: "timestamp"})
    return merged.reset_index(drop=True)


def persist_output(frame: pd.DataFrame, output_path: Path, output_format: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = output_format
    if fmt == "auto":
        fmt = "parquet" if output_path.suffix.lower() == ".parquet" else "csv"

    if fmt == "parquet":
        frame.to_parquet(output_path, index=False)
    else:
        frame.to_csv(output_path, index=False)


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    data_dir = Path(args.data_dir)

    if not input_path.exists():
        raise FileNotFoundError(f"Input does not exist: {input_path}")
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory does not exist: {data_dir}")

    signals = load_signals(input_path)
    required = {"coin", "entry_time"}
    missing = required - set(signals.columns)
    if missing:
        raise ValueError(f"Input missing required columns: {sorted(missing)}")

    config = TripleBarrierConfig(
        timeframe=args.timeframe,
        max_holding_bars=args.max_holding_bars,
        tp_atr_mult=args.tp_atr_mult,
        sl_atr_mult=args.sl_atr_mult,
        min_rr=args.min_rr,
    )
    labeler = TripleBarrierLabeler(config=config)

    outputs = []
    skipped_coins = []
    for coin, group in signals.groupby(signals["coin"].astype(str).str.upper()):
        candles = load_candles_for_coin(data_dir=data_dir, coin=coin, timeframe=args.timeframe)
        if candles.empty:
            skipped_coins.append(coin)
            continue
        labeled = labeler.label(group.copy(), candles)
        outputs.append(labeled)

    if not outputs:
        raise RuntimeError("No labeled rows were produced. Check input signals and candle files.")

    all_labeled = pd.concat(outputs, ignore_index=True)
    if "barrier_hit_time" in all_labeled.columns:
        all_labeled["barrier_hit_time"] = pd.to_datetime(
            all_labeled["barrier_hit_time"], utc=True, errors="coerce"
        )

    persist_output(all_labeled, output_path=output_path, output_format=args.output_format)

    store = FeatureStoreV2()
    store.ensure_structure()
    store_fmt = args.output_format if args.output_format != "auto" else "parquet"
    try:
        store.save_table(
            all_labeled,
            layer="labels",
            name="triple_barrier_labels",
            fmt=store_fmt,
        )
    except Exception:
        # Fall back to CSV if parquet backend is unavailable.
        store.save_table(
            all_labeled,
            layer="labels",
            name="triple_barrier_labels",
            fmt="csv",
        )

    outcome_dist = all_labeled["triple_barrier_label"].value_counts(dropna=False).to_dict()

    print(f"Input rows: {len(signals)}")
    print(f"Output rows: {len(all_labeled)}")
    print(f"Saved labels: {output_path}")
    print(f"Outcome distribution: {outcome_dist}")
    if skipped_coins:
        print(f"Skipped coins (missing candles): {sorted(skipped_coins)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
