"""
neural_trading/data/pipeline.py

Independent extraction, cross-asset alignment, and deterministic feature tensor builder.
Constructs strictly point-in-time multi-asset input tensors for neural policies.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
import numpy as np
import pandas as pd

from neural_trading.data.schema import CORE_PILOT_UNIVERSE, FEATURE_CHANNELS, TensorMetadata

FEATURE_CHANNELS_PV: Tuple[str, ...] = (
    "log_return_1h",
    "vol_spread_1h",
    "volume_flow_ratio",
    "macro_momentum_4h",
)


class MultiAssetDataPipeline:
    """
    Constructs aligned 3D/4D multi-asset tensors for neural portfolio optimization.
    Guarantees strict point-in-time causal integrity with zero future leakage.
    """

    def __init__(
        self,
        symbols: Sequence[str] = CORE_PILOT_UNIVERSE,
        reconstructed_dir: Path = Path("data/historical/reconstructed_neural_n0_1"),
        lookback_window: int = 48,
        timeframe: str = "1h",
        use_funding: bool = False,
    ):
        self.symbols = list(symbols)
        self.reconstructed_dir = Path(reconstructed_dir)
        self.lookback_window = lookback_window
        self.timeframe = timeframe
        self.use_funding = use_funding
        self.channel_names = list(FEATURE_CHANNELS) if use_funding else list(FEATURE_CHANNELS_PV)

    def load_aligned_data(self) -> Dict[str, pd.DataFrame]:
        """Loads canonical synchronized parquets for all symbols."""
        data = {}
        for sym in self.symbols:
            f_path = self.reconstructed_dir / f"{sym}_1h_aligned.parquet"
            if not f_path.exists():
                raise FileNotFoundError(f"Canonical reconstructed parquet not found at {f_path}. Run scripts/reconstruct_authoritative_timeline.py first.")
            df = pd.read_parquet(f_path)
            df["time"] = pd.to_datetime(df["time"])
            df.sort_values("time", inplace=True)
            df.reset_index(drop=True, inplace=True)
            data[sym] = df
        return data

    def build_aligned_dataset(
        self,
    ) -> Tuple[np.ndarray, np.ndarray, List[str], np.ndarray, TensorMetadata]:
        """
        Builds synchronized multi-asset tensor X: (S, N, T, F), price relatives y: (S, N),
        timestamps, and is_halt boolean array.
        """
        raw_data = self.load_aligned_data()
        ref_df = raw_data[self.symbols[0]]
        sorted_times = ref_df["time"].tolist()
        num_timesteps = len(sorted_times)
        num_assets = len(self.symbols)
        num_channels = len(self.channel_names)

        # 1. Compute per-asset continuous features
        asset_feature_matrices = []
        asset_closes = []

        for sym in self.symbols:
            df = raw_data[sym]
            c = df["close"].values
            h = df["high"].values
            l = df["low"].values
            v = df["volume"].values

            # Feature 0: 1h log return
            r_1h = np.zeros(num_timesteps, dtype=np.float32)
            r_1h[1:] = np.log(np.maximum(c[1:] / np.maximum(c[:-1], 1e-8), 1e-8))

            # Feature 1: Normalized high-low volatility spread
            vol_spread = ((h - l) / np.maximum(c, 1e-8)).astype(np.float32)

            # Feature 2: Volume flow ratio (vs 24h rolling SMA)
            v_series = pd.Series(v)
            v_sma = v_series.rolling(24, min_periods=1).mean().values
            vol_ratio = np.log(np.maximum(v / np.maximum(v_sma, 1e-8) + 1e-4, 1e-8)).astype(np.float32)

            # Feature 3: 4h macro momentum
            r_4h = np.zeros(num_timesteps, dtype=np.float32)
            r_4h[4:] = np.log(np.maximum(c[4:] / np.maximum(c[:-4], 1e-8), 1e-8))

            channels = [r_1h, vol_spread, vol_ratio, r_4h]
            if self.use_funding and "funding_rate" in df.columns:
                fr = df["funding_rate"].values
                funding_bps = np.clip(fr * 10000.0, -50.0, 50.0).astype(np.float32)
                channels.append(funding_bps)

            feat_matrix = np.column_stack(channels)
            asset_feature_matrices.append(feat_matrix)
            asset_closes.append(c)

        # 2. Slice into sliding window tensors (S, N, T, F) and price relatives y: (S, N)
        T = self.lookback_window
        samples_X = []
        samples_y = []
        sample_timestamps = []
        sample_halts = []

        # Find halt timestamps where time jump > 1 hour
        time_series = pd.Series(sorted_times)
        diffs = time_series.diff()

        for curr_idx in range(T - 1, num_timesteps - 1):
            window_slice = slice(curr_idx - T + 1, curr_idx + 1)
            x_t = np.stack([mat[window_slice] for mat in asset_feature_matrices], axis=0)

            # Check if next step is a trading halt (diff > 1h)
            next_t = sorted_times[curr_idx + 1]
            curr_t = sorted_times[curr_idx]
            is_halt = bool((next_t - curr_t) > pd.Timedelta(hours=1))

            y_t = np.array([closes[curr_idx + 1] / closes[curr_idx] for closes in asset_closes], dtype=np.float32)
            if is_halt:
                # During halt, price relative is frozen at 1.0 (no trading executed)
                y_t = np.ones(num_assets, dtype=np.float32)

            samples_X.append(x_t)
            samples_y.append(y_t)
            sample_timestamps.append(str(curr_t))
            sample_halts.append(is_halt)

        X = np.stack(samples_X, axis=0).astype(np.float32)
        y = np.stack(samples_y, axis=0).astype(np.float32)
        halts = np.array(sample_halts, dtype=bool)

        metadata = TensorMetadata(
            num_samples=len(samples_X),
            num_assets=num_assets,
            lookback_window=T,
            num_channels=num_channels,
            symbols=self.symbols,
            channel_names=self.channel_names,
            timeframe=self.timeframe,
            start_timestamp=sample_timestamps[0] if sample_timestamps else "",
            end_timestamp=sample_timestamps[-1] if sample_timestamps else "",
        )

        return X, y, sample_timestamps, halts, metadata
