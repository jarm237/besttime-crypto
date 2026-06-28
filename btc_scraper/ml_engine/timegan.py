"""TimeGAN preprocessing utilities for Phase 5 Stage 1.

Stage 1 responsibilities:
- load 15m historical candle CSVs from data/historical_18m
- chunk them into fixed-length sequences of [open, high, low, close, volume]
- normalize sequences with MinMax scaling to [0, 1]
- provide PyTorch Dataset / DataLoader support
"""

import glob
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset, DataLoader

OHLCV_FEATURES = ["open", "high", "low", "close", "volume"]


def _extract_coin_from_filename(filename: str) -> str:
    base = os.path.basename(filename)
    match = re.search(r"_([A-Za-z0-9]+)_15m\.csv$", base)
    if match:
        return match.group(1).upper()
    return os.path.splitext(base)[0].upper()


def _validate_sequence_array(sequences: np.ndarray, seq_len: int) -> None:
    if sequences.ndim != 3 or sequences.shape[1] != seq_len or sequences.shape[2] != len(OHLCV_FEATURES):
        raise ValueError(
            f"Expected sequences shape (N, {seq_len}, {len(OHLCV_FEATURES)}), got {sequences.shape}"
        )


def load_historical_15m_sequences(
    data_dir: str = "data/historical_18m",
    seq_len: int = 24,
    coins: Optional[Sequence[str]] = None,
    min_candles: Optional[int] = None,
) -> np.ndarray:
    """Load 15m historical candle data and return fixed-length OHLCV sequences.

    Args:
        data_dir: Directory containing historical CSV files.
        seq_len: Length of each time series sequence.
        coins: Optional list of coin symbols to include.
        min_candles: Minimum number of candles required in a file.

    Returns:
        NumPy array with shape (N, seq_len, 5).
    """
    source_path = Path(data_dir)
    csv_pattern = str(source_path / "**" / "*_15m.csv")
    paths = sorted(glob.glob(csv_pattern, recursive=True))

    coin_filter = {c.upper() for c in coins} if coins else None
    sequences: List[np.ndarray] = []

    for path in paths:
        coin = _extract_coin_from_filename(path)
        if coin_filter and coin not in coin_filter:
            continue

        try:
            df = pd.read_csv(path, parse_dates=["time"] if "time" in pd.read_csv(path, nrows=0).columns else [])
        except Exception:
            continue

        if not all(feature in df.columns for feature in OHLCV_FEATURES):
            continue

        if "time" in df.columns:
            df = df.sort_values("time")

        df = df.loc[:, OHLCV_FEATURES].dropna()
        if min_candles is None:
            min_candles = seq_len
        if len(df) < max(seq_len, min_candles):
            continue

        values = df.astype(np.float32).values
        if values.shape[1] != len(OHLCV_FEATURES):
            continue

        for start in range(0, values.shape[0] - seq_len + 1):
            window = values[start : start + seq_len]
            if not np.isfinite(window).all():
                continue
            sequences.append(window)

    if not sequences:
        return np.zeros((0, seq_len, len(OHLCV_FEATURES)), dtype=np.float32)
    return np.stack(sequences).astype(np.float32)


class OHLCVScaler:
    """MinMax scaler for OHLCV sequences."""

    def __init__(self, feature_range: Tuple[float, float] = (0.0, 1.0)):
        self.price_min_: Optional[float] = None
        self.price_max_: Optional[float] = None
        self.price_scale_: Optional[float] = None
        self.volume_min_: Optional[float] = None
        self.volume_max_: Optional[float] = None
        self.volume_scale_: Optional[float] = None
        self.feature_range = feature_range
        self.fitted = False

    def fit(self, sequences: np.ndarray) -> "OHLCVScaler":
        if sequences.size == 0:
            raise ValueError("Cannot fit scaler on empty sequence data.")

        if sequences.ndim != 3 or sequences.shape[2] != len(OHLCV_FEATURES):
            raise ValueError("Input sequences must have shape (N, seq_len, 5).")

        flat = sequences.reshape(-1, len(OHLCV_FEATURES)).astype(np.float32)
        prices = flat[:, :4]
        volumes = flat[:, 4]

        self.price_min_ = float(np.nanmin(prices))
        self.price_max_ = float(np.nanmax(prices))
        self.price_scale_ = self.price_max_ - self.price_min_
        if self.price_scale_ == 0.0:
            self.price_scale_ = 1.0

        self.volume_min_ = float(np.nanmin(volumes))
        self.volume_max_ = float(np.nanmax(volumes))
        self.volume_scale_ = self.volume_max_ - self.volume_min_
        if self.volume_scale_ == 0.0:
            self.volume_scale_ = 1.0

        self.fitted = True
        return self

    def transform(self, sequences: np.ndarray) -> np.ndarray:
        if not self.fitted or self.price_min_ is None or self.volume_min_ is None:
            raise ValueError("Scaler has not been fitted yet.")

        _validate_sequence_array(sequences, sequences.shape[1])
        seq = sequences.astype(np.float32).copy()

        lo, hi = self.feature_range
        seq[:, :, :4] = (seq[:, :, :4] - self.price_min_) / self.price_scale_
        seq[:, :, 4] = (seq[:, :, 4] - self.volume_min_) / self.volume_scale_
        seq = seq * (hi - lo) + lo
        return np.clip(seq, lo, hi)

    def inverse_transform(self, sequences: np.ndarray) -> np.ndarray:
        if not self.fitted or self.price_min_ is None or self.volume_min_ is None:
            raise ValueError("Scaler has not been fitted yet.")

        _validate_sequence_array(sequences, sequences.shape[1])
        lo, hi = self.feature_range
        unscaled = (np.asarray(sequences, dtype=np.float32) - lo) / (hi - lo)
        unscaled[:, :, :4] = unscaled[:, :, :4] * self.price_scale_ + self.price_min_
        unscaled[:, :, 4] = unscaled[:, :, 4] * self.volume_scale_ + self.volume_min_
        return unscaled

    def fit_transform(self, sequences: np.ndarray) -> np.ndarray:
        self.fit(sequences)
        return self.transform(sequences)


class AltcoinSequenceDataset(Dataset):
    """PyTorch Dataset for TimeGAN OHLCV sequences."""

    def __init__(self, sequences: np.ndarray):
        sequences = np.asarray(sequences, dtype=np.float32)
        if sequences.ndim != 3 or sequences.shape[2] != len(OHLCV_FEATURES):
            raise ValueError(
                f"Expected sequences shape (N, seq_len, {len(OHLCV_FEATURES)}), got {sequences.shape}"
            )
        self.sequences = torch.from_numpy(sequences)

    def __len__(self) -> int:
        return self.sequences.shape[0]

    def __getitem__(self, idx: int) -> torch.Tensor:
        return self.sequences[idx]

    @property
    def feature_names(self) -> List[str]:
        return OHLCV_FEATURES


def build_timegan_dataloader(
    sequences: np.ndarray,
    batch_size: int = 64,
    shuffle: bool = True,
    num_workers: int = 0,
    pin_memory: bool = False,
) -> DataLoader:
    dataset = AltcoinSequenceDataset(sequences)
    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=num_workers,
        pin_memory=pin_memory,
        drop_last=False,
    )


def save_sequences(sequences: np.ndarray, output_path: str) -> None:
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_path, sequences)


def load_sequences(output_path: str) -> np.ndarray:
    return np.load(output_path)
