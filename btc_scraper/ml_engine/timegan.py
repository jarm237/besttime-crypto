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

try:
    import torch
    from torch.utils.data import Dataset, DataLoader
except Exception as exc:  # pragma: no cover - environment dependent
    torch = None
    Dataset = object
    DataLoader = None
    TORCH_IMPORT_ERROR = exc
else:
    TORCH_IMPORT_ERROR = None

OHLCV_FEATURES = ["open", "high", "low", "close", "volume"]


def _extract_coin_from_filename(filename: str) -> str:
    """Extract coin symbol from CSV filename.
    
    Supports formats:
    - 2025_01_BTC_15m.csv -> BTC
    - april_2025_BTC_15m.csv -> BTC
    - BTC_15m.csv -> BTC
    - BTC_1d.csv -> BTC
    """
    base = os.path.basename(filename)
    
    # Try pattern with timeframe (15m, 1d, 1h, 4h)
    # Matches: anything_COIN_15m.csv, anything_COIN_1d.csv, etc.
    match = re.search(r"([A-Za-z0-9]{2,5})_(15m|1d|1h|4h)\.csv$", base)
    if match:
        return match.group(1).upper()
    
    # Fallback: get last part before .csv
    base_name = os.path.splitext(base)[0]
    parts = base_name.split("_")
    if parts:
        return parts[-1].upper()
    
    return base_name.upper()


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
        if torch is None:
            raise ImportError(f"PyTorch is unavailable: {TORCH_IMPORT_ERROR}")
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
):
    if torch is None or DataLoader is None:
        raise ImportError(f"PyTorch is unavailable: {TORCH_IMPORT_ERROR}")
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


def _enforce_ohlc_constraints(sequences: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """Ensure High/Low are consistent with Open/Close and High>=Low.

    Modifies a copy of sequences and returns it.
    """
    seq = sequences.copy()
    opens = seq[:, :, 0]
    highs = seq[:, :, 1]
    lows = seq[:, :, 2]
    closes = seq[:, :, 3]

    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    # ensure high >= low
    mask = highs < lows
    if np.any(mask):
        highs[mask] = lows[mask] + eps

    seq[:, :, 1] = highs
    seq[:, :, 2] = lows
    return seq


def postprocess_synthetic_sequences(
    sequences, scaler: OHLCVScaler, device: str = "cpu", enforce_ohlc: bool = True
) -> np.ndarray:
    """Inverse-transform synthetic sequences (scaled) back to original OHLCV.

    Parameters:
    - sequences: np.ndarray or torch.Tensor of shape (N, T, 5). If torch and on GPU,
      the tensor will be moved to CPU for inverse transform.
    - scaler: fitted `OHLCVScaler` instance.
    - device: hint for device where sequences live ("cpu" or "cuda").
    - enforce_ohlc: whether to correct High/Low post-hoc.

    Returns:
    - NumPy array (N, T, 5) with real-scale OHLCV values.
    """
    if isinstance(sequences, torch.Tensor):
        if sequences.device.type == "cuda" and device == "cuda":
            arr = sequences.detach().to("cpu").numpy()
        else:
            arr = sequences.detach().numpy()
    else:
        arr = np.asarray(sequences, dtype=np.float32)

    if arr.ndim != 3 or arr.shape[2] != len(OHLCV_FEATURES):
        raise ValueError("synthetic sequences must have shape (N, T, 5)")

    real = scaler.inverse_transform(arr)
    if enforce_ohlc:
        real = _enforce_ohlc_constraints(real)
    return real


def compute_simple_indicators(sequences: np.ndarray, windows: Sequence[int] = (3, 5)) -> Dict[str, np.ndarray]:
    """Compute simple moving averages on `close` for given windows.

    Returns a dict mapping `sma_{w}` -> array shape (N, T).
    """
    seq = np.asarray(sequences, dtype=np.float32)
    if seq.ndim != 3 or seq.shape[2] < 4:
        raise ValueError("sequences must be (N, T, >=4) to compute indicators")

    closes = seq[:, :, 3]
    N, T = closes.shape
    out: Dict[str, np.ndarray] = {}
    for w in windows:
        sma = np.full((N, T), np.nan, dtype=np.float32)
        if w <= 0:
            continue
        for t in range(T):
            start = max(0, t - w + 1)
            sma[:, t] = closes[:, start : t + 1].mean(axis=1)
        out[f"sma_{w}"] = sma
    return out


def compute_rsi(sequences: np.ndarray, period: int = 14) -> np.ndarray:
    """Compute RSI for close prices in sequences. Returns shape (N, T).

    Uses Wilder smoothing (EMA-like) for average gains and losses.
    """
    seq = np.asarray(sequences, dtype=np.float32)
    if seq.ndim != 3 or seq.shape[2] < 4:
        raise ValueError("sequences must be (N, T, >=4) to compute RSI")
    closes = seq[:, :, 3]
    N, T = closes.shape
    rsi = np.full((N, T), np.nan, dtype=np.float32)

    if period <= 0:
        return rsi

    # compute deltas
    deltas = np.diff(closes, axis=1)

    # initial average gains/losses
    for i in range(N):
        if T <= 1:
            continue
        gains = np.where(deltas[i] > 0, deltas[i], 0.0)
        losses = np.where(deltas[i] < 0, -deltas[i], 0.0)
        # first avg over first `period` values (if available)
        if deltas.shape[1] >= period:
            avg_gain = gains[:period].mean()
            avg_loss = losses[:period].mean()
            # RSI for index period -> set at position period
            rs = avg_gain / (avg_loss + 1e-8)
            rsi[i, period] = 100.0 - (100.0 / (1.0 + rs))
            # iterate forward
            for t in range(period + 1, T):
                g = gains[t - 1]
                l = losses[t - 1]
                avg_gain = (avg_gain * (period - 1) + g) / period
                avg_loss = (avg_loss * (period - 1) + l) / period
                rs = avg_gain / (avg_loss + 1e-8)
                rsi[i, t] = 100.0 - (100.0 / (1.0 + rs))
        else:
            # not enough data; compute simple RSI where possible
            for t in range(1, T):
                window_gains = np.where(deltas[i, :t] > 0, deltas[i, :t], 0.0)
                window_losses = np.where(deltas[i, :t] < 0, -deltas[i, :t], 0.0)
                ag = window_gains.mean() if window_gains.size else 0.0
                al = window_losses.mean() if window_losses.size else 0.0
                rs = ag / (al + 1e-8)
                rsi[i, t] = 100.0 - (100.0 / (1.0 + rs))

    return rsi


def compute_atr(sequences: np.ndarray, period: int = 14) -> np.ndarray:
    """Compute ATR from sequences. Returns shape (N, T).

    ATR uses True Range and Wilder smoothing.
    """
    seq = np.asarray(sequences, dtype=np.float32)
    if seq.ndim != 3 or seq.shape[2] < 4:
        raise ValueError("sequences must be (N, T, >=4) to compute ATR")
    highs = seq[:, :, 1]
    lows = seq[:, :, 2]
    closes = seq[:, :, 3]
    N, T = closes.shape
    atr = np.full((N, T), np.nan, dtype=np.float32)
    if period <= 0:
        return atr

    # compute true ranges
    prev_close = np.concatenate([closes[:, :1], closes[:, :-1]], axis=1)
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_close), np.abs(lows - prev_close)))

    for i in range(N):
        if T <= 0:
            continue
        if T >= period:
            # initial ATR is simple mean of first `period` TR values (positions 0..period-1)
            init = tr[i, :period].mean()
            atr[i, period - 1] = init
            prev_atr = init
            for t in range(period, T):
                prev_atr = (prev_atr * (period - 1) + tr[i, t]) / period
                atr[i, t] = prev_atr
            # fill earlier positions with cumulative mean
            for t in range(0, period - 1):
                atr[i, t] = tr[i, : t + 1].mean()
        else:
            # not enough data: cumulative mean
            for t in range(T):
                atr[i, t] = tr[i, : t + 1].mean()

    return atr


def compute_indicators(sequences: np.ndarray, sma_windows: Sequence[int] = (3, 5), rsi_period: int = 14, atr_period: int = 14) -> Dict[str, np.ndarray]:
    """Compute a set of indicators from sequences.

    Parameters:
    - sequences: (N, T, 5)
    - sma_windows: windows for simple moving averages
    - rsi_period: period for RSI (Wilder smoothing)
    - atr_period: period for ATR (Wilder smoothing)
    - ema_spans: optional list of spans to compute EMA for `close`
    - compute_obv: whether to compute On-Balance Volume
    """
    out = compute_simple_indicators(sequences, windows=sma_windows)
    out[f"rsi_{rsi_period}"] = compute_rsi(sequences, period=rsi_period)
    out[f"atr_{atr_period}"] = compute_atr(sequences, period=atr_period)
    return out


def compute_ema(sequences: np.ndarray, span: int = 10) -> np.ndarray:
    """Compute EMA of close prices for each sequence. Returns (N, T)."""
    seq = np.asarray(sequences, dtype=np.float32)
    closes = seq[:, :, 3]
    N, T = closes.shape
    ema = np.full((N, T), np.nan, dtype=np.float32)
    if span <= 0:
        return ema
    alpha = 2.0 / (span + 1.0)
    for i in range(N):
        prev = closes[i, 0]
        ema[i, 0] = prev
        for t in range(1, T):
            prev = alpha * closes[i, t] + (1 - alpha) * prev
            ema[i, t] = prev
    return ema


def compute_obv(sequences: np.ndarray) -> np.ndarray:
    """Compute On-Balance Volume (OBV) for each sequence. Returns (N, T)."""
    seq = np.asarray(sequences, dtype=np.float32)
    closes = seq[:, :, 3]
    vols = seq[:, :, 4]
    N, T = closes.shape
    obv = np.zeros((N, T), dtype=np.float32)
    for i in range(N):
        running = 0.0
        obv[i, 0] = running
        for t in range(1, T):
            if closes[i, t] > closes[i, t - 1]:
                running += vols[i, t]
            elif closes[i, t] < closes[i, t - 1]:
                running -= vols[i, t]
            obv[i, t] = running
    return obv
