"""
neural_trading/data/schema.py

Data schemas, universe definitions, and tensor contracts for neural trading.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple


CORE_PILOT_UNIVERSE: Tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "DOGEUSDT",
)

FEATURE_CHANNELS: Tuple[str, ...] = (
    "log_return_1h",      # ln(close_t / close_{t-1})
    "vol_spread_1h",      # (high_t - low_t) / close_t
    "volume_flow_ratio",  # ln(volume_t / SMA(volume, 24) + 1e-4)
    "macro_momentum_4h",  # ln(close_t / close_{t-4})
    "funding_skew_bps",   # funding_rate * 10,000 (clipped)
)


@dataclass(frozen=True)
class TensorMetadata:
    """Metadata describing the geometry and semantics of a multi-asset tensor."""
    num_samples: int
    num_assets: int
    lookback_window: int
    num_channels: int
    symbols: List[str]
    channel_names: List[str]
    timeframe: str = "1h"
    start_timestamp: str = ""
    end_timestamp: str = ""
