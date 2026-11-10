"""
neural_trading/data/pipeline.py

Independent extraction, cross-asset alignment, and deterministic feature tensor builder.
Constructs strictly point-in-time multi-asset input tensors for neural policies.
"""
from __future__ import annotations

import glob
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
import numpy as np
import pandas as pd

from neural_trading.data.schema import CORE_PILOT_UNIVERSE, FEATURE_CHANNELS, TensorMetadata


class MultiAssetDataPipeline:
    """
    Constructs aligned 3D/4D multi-asset tensors for neural portfolio optimization.
    Guarantees strict point-in-time causal integrity with zero future leakage.
    """

    def __init__(
        self,
        symbols: Sequence[str] = CORE_PILOT_UNIVERSE,
        data_dir: Path = Path("data/fresh_training_data_2023_2026"),
        funding_dir: Path = Path("data/historical/normalized/futures_funding"),
        lookback_window: int = 48,
        timeframe: str = "1h",
    ):
        self.symbols = list(symbols)
        self.data_dir = Path(data_dir)
        self.funding_dir = Path(funding_dir)
        self.lookback_window = lookback_window
        self.timeframe = timeframe

    def load_raw_candles_for_symbol(
        self,
        symbol: str,
        start_year_month: str = "2023-01",
        end_year_month: str = "2025-12",
    ) -> pd.DataFrame:
        """Loads and concatenates monthly Spot 1h CSVs for a symbol."""
        # Symbol directory name (e.g. 'BTC' for 'BTCUSDT')
        sym_prefix = symbol.replace("USDT", "")
        sym_dir = self.data_dir / sym_prefix / self.timeframe
        if not sym_dir.exists():
            # Try full symbol name
            sym_dir = self.data_dir / symbol / self.timeframe

        if not sym_dir.exists():
            raise FileNotFoundError(f"Spot data directory not found for {symbol} at {sym_dir}")

        files = sorted(list(sym_dir.glob(f"{sym_prefix}_{self.timeframe}_*.csv")))
        if not files:
            files = sorted(list(sym_dir.glob(f"{symbol}_{self.timeframe}_*.csv")))

        dfs = []
        for f in files:
            # Check monthly bounds: YYYY-MM
            stem = f.stem
            parts = stem.split("_")
            ym = parts[-1]  # '2023-01'
            if start_year_month <= ym <= end_year_month:
                df_m = pd.read_csv(f)
                dfs.append(df_m)

        if not dfs:
            raise ValueError(f"No CSV files found for {symbol} between {start_year_month} and {end_year_month}")

        full_df = pd.concat(dfs, ignore_index=True)
        # Drop duplicates on 'time' and filter out warmup if requested
        full_df["time"] = pd.to_datetime(full_df["time"])
        full_df.sort_values("time", inplace=True)
        full_df.drop_duplicates(subset=["time"], inplace=True)
        # Keep non-warmup or use warmup for rolling features only
        full_df.reset_index(drop=True, inplace=True)
        return full_df

    def load_funding_for_symbol(self, symbol: str) -> pd.DataFrame:
        """Loads normalized 8h funding rates if available."""
        funding_sym_dir = self.funding_dir / symbol
        if not funding_sym_dir.exists():
            return pd.DataFrame(columns=["available_at", "funding_rate"])

        parquet_files = sorted(list(funding_sym_dir.glob("*.parquet")))
        if not parquet_files:
            return pd.DataFrame(columns=["available_at", "funding_rate"])

        dfs = [pd.read_parquet(f) for f in parquet_files]
        f_df = pd.concat(dfs, ignore_index=True)
        if "available_at" in f_df.columns:
            f_df["time"] = pd.to_datetime(f_df["available_at"]).dt.tz_localize(None)
        elif "timestamp" in f_df.columns:
            f_df["time"] = pd.to_datetime(f_df["timestamp"], unit="ms")
        f_df.sort_values("time", inplace=True)
        f_df.drop_duplicates(subset=["time"], inplace=True)
        f_df.reset_index(drop=True, inplace=True)
        return f_df[["time", "funding_rate"]]

    def build_aligned_dataset(
        self,
        start_date: str = "2023-01-01",
        end_date: str = "2025-12-31",
    ) -> Tuple[np.ndarray, np.ndarray, List[str], TensorMetadata]:
        """
        Builds synchronized multi-asset tensor X: (S, N, T, F) and price relatives y: (S, N).
        S: Number of sliding sequence samples
        N: Number of assets
        T: Lookback window
        F: Number of feature channels
        """
        raw_data: Dict[str, pd.DataFrame] = {}
        for sym in self.symbols:
            df = self.load_raw_candles_for_symbol(sym, "2023-01", "2025-12")
            # Load funding
            f_df = self.load_funding_for_symbol(sym)
            if not f_df.empty:
                df = pd.merge_asof(df, f_df, on="time", direction="backward")
                df["funding_rate"] = df["funding_rate"].fillna(0.0)
            else:
                df["funding_rate"] = 0.0
            raw_data[sym] = df

        # Find common timestamps across all assets
        common_times = None
        for sym, df in raw_data.items():
            valid_times = set(df[df["is_warmup"] == 0]["time"])
            if common_times is None:
                common_times = valid_times
            else:
                common_times = common_times.intersection(valid_times)

        sorted_times = sorted(list(common_times))
        start_ts = pd.Timestamp(start_date)
        end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1)
        sorted_times = [t for t in sorted_times if start_ts <= t < end_ts]

        time_to_idx = {t: i for i, t in enumerate(sorted_times)}
        num_timesteps = len(sorted_times)
        num_assets = len(self.symbols)
        num_channels = len(FEATURE_CHANNELS)

        # 1. Compute per-asset continuous features
        asset_feature_matrices = []  # List of (num_timesteps, num_channels)
        asset_closes = []            # List of (num_timesteps,)

        for sym in self.symbols:
            df = raw_data[sym].copy()
            df.set_index("time", inplace=True)
            # Reindex to exact common times (ffill for rare hiatus like Binance outage)
            df_aligned = df.reindex(sorted_times).ffill()

            c = df_aligned["close"].values
            h = df_aligned["high"].values
            l = df_aligned["low"].values
            v = df_aligned["volume"].values
            fr = df_aligned["funding_rate"].values

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

            # Feature 4: Funding rate in bps (clipped to [-50, 50])
            funding_bps = np.clip(fr * 10000.0, -50.0, 50.0).astype(np.float32)

            feat_matrix = np.column_stack([r_1h, vol_spread, vol_ratio, r_4h, funding_bps])
            asset_feature_matrices.append(feat_matrix)
            asset_closes.append(c)

        # 2. Slice into sliding window tensors (S, N, T, F) and price relatives y: (S, N)
        # Sequence at step s ends at bar index `curr_idx`.
        # Prediction is evaluated at `curr_idx` close.
        # Price relative is `close[curr_idx + 1] / close[curr_idx]` (next bar return).
        T = self.lookback_window
        samples_X = []
        samples_y = []
        sample_timestamps = []

        for curr_idx in range(T - 1, num_timesteps - 1):
            window_slice = slice(curr_idx - T + 1, curr_idx + 1)
            # Tensor for this time step: (N, T, F)
            x_t = np.stack([mat[window_slice] for mat in asset_feature_matrices], axis=0)
            
            # Next bar price relative: p_{t+1} / p_t
            y_t = np.array([closes[curr_idx + 1] / closes[curr_idx] for closes in asset_closes], dtype=np.float32)

            samples_X.append(x_t)
            samples_y.append(y_t)
            sample_timestamps.append(str(sorted_times[curr_idx]))

        X = np.stack(samples_X, axis=0).astype(np.float32)
        y = np.stack(samples_y, axis=0).astype(np.float32)

        metadata = TensorMetadata(
            num_samples=len(samples_X),
            num_assets=num_assets,
            lookback_window=T,
            num_channels=num_channels,
            symbols=self.symbols,
            channel_names=list(FEATURE_CHANNELS),
            timeframe=self.timeframe,
            start_timestamp=sample_timestamps[0] if sample_timestamps else "",
            end_timestamp=sample_timestamps[-1] if sample_timestamps else "",
        )

        return X, y, sample_timestamps, metadata
