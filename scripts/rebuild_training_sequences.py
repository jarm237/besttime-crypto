#!/usr/bin/env python3
"""Build sliding-window OHLCV sequences from fresh monthly CSVs.

Saves per-month sequence arrays as .npy under the output directory, and
creates a manifest.json summarizing produced files.

Usage:
  python scripts/rebuild_training_sequences.py --data-dir data/fresh_training_data_2023_2026 --output data/fresh_training_sequences --interval 15m --seq-len 24 --use-gpu
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

from btc_scraper.core.config import FRESH_TRAINING_DATA_DIR
from btc_scraper.core.io import smart_read_csv


def discover_csvs(data_dir: Path, interval: str) -> List[Path]:
    pattern = f"*_{interval}_*.csv"
    return sorted(data_dir.rglob(pattern))


def extract_coin_from_name(name: str) -> str:
    parts = Path(name).stem.split("_")
    # coin usually appears as the token equal to uppercase letters
    for p in parts:
        if p.isalpha() and p.upper() == p:
            return p.upper()
    # fallback: first token
    return parts[0].upper()


def build_and_save_sequences(
    csv_path: Path,
    out_dir: Path,
    seq_len: int = 24,
    use_gpu: bool = False,
    features: List[str] | None = None,
):
    if features is None:
        features = ["open", "high", "low", "close", "volume"]

    try:
        header = smart_read_csv(csv_path, nrows=0)
        df = smart_read_csv(csv_path, parse_dates=["time"] if "time" in header.columns else [])
    except Exception as e:
        print(f"[WARN] Failed to read {csv_path}: {e}")
        return 0

    if not all(f in df.columns for f in features):
        print(f"[WARN] Missing OHLCV columns in {csv_path}")
        return 0

    df = df.dropna(subset=features)
    if "time" in df.columns:
        df = df.sort_values("time")

    arr = df.loc[:, features].astype(np.float32).values
    n = arr.shape[0]
    if n < seq_len:
        return 0

    # GPU-accelerated windowing via torch if requested
    use_torch = False
    if use_gpu:
        try:
            import torch

            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            use_torch = True
        except Exception:
            use_torch = False

    if use_torch:
        t = torch.from_numpy(arr).to(device)
        windows = t.unfold(0, seq_len, 1).contiguous()  # shape (num_windows, seq_len, features)
        windows = windows.cpu().numpy()
    else:
        # NumPy sliding window (memory efficient view if possible)
        shape = (n - seq_len + 1, seq_len, arr.shape[1])
        strides = (arr.strides[0], arr.strides[0], arr.strides[1])
        try:
            windows = np.lib.stride_tricks.as_strided(arr, shape=shape, strides=strides).copy()
        except Exception:
            # Fallback manual
            windows = np.stack([arr[i : i + seq_len] for i in range(0, n - seq_len + 1)])

    # Save sequences per-month under out_dir/<COIN>/<INTERVAL>/<basename>.npy
    coin = extract_coin_from_name(csv_path.name)
    interval = csv_path.stem.split("_")[-2]
    target_dir = out_dir / coin / interval
    target_dir.mkdir(parents=True, exist_ok=True)
    out_path = target_dir / f"{csv_path.stem}.npy"
    try:
        np.save(out_path, windows)
        print(f"Saved {out_path} ({windows.shape[0]} sequences)")
        return int(windows.shape[0])
    except Exception as e:
        print(f"[ERROR] Failed to save {out_path}: {e}")
        return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default=None, help="Source fresh data dir (defaults to FRESH_TRAINING_DATA_DIR)")
    p.add_argument("--output", default=None, help="Output sequences root dir (default: <data-dir>_sequences)")
    p.add_argument("--interval", default="15m", help="Timeframe interval to process (e.g. 15m)")
    p.add_argument("--seq-len", type=int, default=24, help="Sliding window length (timesteps)")
    p.add_argument("--use-gpu", action="store_true", help="Attempt to use GPU (PyTorch) for windowing")
    args = p.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else Path(FRESH_TRAINING_DATA_DIR)
    if not data_dir.exists():
        raise FileNotFoundError(f"Data dir not found: {data_dir}")

    output_root = Path(args.output) if args.output else Path(str(data_dir) + "_sequences")
    output_root.mkdir(parents=True, exist_ok=True)

    csvs = discover_csvs(data_dir, args.interval)
    manifest = {"files": [], "total_sequences": 0}

    for csv in csvs:
        count = build_and_save_sequences(csv, output_root, seq_len=args.seq_len, use_gpu=args.use_gpu)
        if count:
            manifest["files"].append({"source": str(csv), "out": str((output_root / extract_coin_from_name(csv.name) / args.interval / f"{csv.stem}.npy")), "sequences": count})
            manifest["total_sequences"] += count

    # Write manifest
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Completed: {manifest['total_sequences']} sequences saved across {len(manifest['files'])} files")


if __name__ == "__main__":
    main()
