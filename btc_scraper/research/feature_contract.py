"""
btc_scraper/research/feature_contract.py
Phase M3-A: Feature Set Specification Contract.

Defines immutable, content-hashed specifications for point-in-time technical and
multi-timeframe (MTF) feature pipelines. Ensures zero feature drift between
batch feature extraction and replay/online inference.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from btc_scraper.research.experiment_contract import freeze_nested, unfreeze_nested


M3_STANDARD_FEATURE_NAMES: Tuple[str, ...] = (
    # Base technical momentum and returns
    "ret_1",           # 1-bar return: (close[t] - close[t-1]) / close[t-1]
    "ret_4",           # 4-bar return (1h equivalent on 15m)
    "ret_12",          # 12-bar return (3h equivalent)
    "ret_48",          # 48-bar return (12h equivalent)
    "log_ret_1",       # 1-bar log return: ln(close[t] / close[t-1])
    
    # Volatility and range
    "atr_14",          # Average True Range (14 bars)
    "natr_14",         # Normalized ATR: atr_14 / close[t]
    "volatility_20",   # Rolling return standard deviation (20 bars)
    "hl_spread",       # High-low range spread: (high - low) / close
    
    # Technical oscillators and moving averages
    "rsi_14",          # Relative Strength Index (14 bars)
    "macd_line",       # MACD line: EMA(12) - EMA(26)
    "macd_signal",     # MACD signal: EMA(9, macd_line)
    "macd_hist",       # MACD histogram: macd_line - macd_signal
    "macd_hist_norm",  # MACD histogram normalized by close
    "sma_dist_20",     # Distance to SMA 20: close / sma_20 - 1.0
    "sma_dist_50",     # Distance to SMA 50: close / sma_50 - 1.0
    
    # Volume dynamics
    "vol_ratio_20",    # Volume relative to 20-bar average
    "vol_z_20",        # Volume z-score over 20 bars
    
    # Point-in-time Multi-Timeframe (MTF) Context
    "mtf_1h_ret_1",    # 1-bar return of latest fully closed 1h bar
    "mtf_1h_trend",    # SMA20 trend distance of latest closed 1h bar
    "mtf_4h_ret_1",    # 1-bar return of latest fully closed 4h bar
    "mtf_4h_trend",    # SMA20 trend distance of latest closed 4h bar
)


@dataclass(frozen=True)
class FeatureSetSpec:
    """
    Immutable specification of a research feature set.
    All attributes are deeply immutable. The feature_schema_hash is deterministically
    computed from all configuration fields and uniquely identifies the exact feature engineering pipeline.
    """
    feature_set_id: str
    schema_version: str
    dataset_manifest_hash: str
    symbol_universe: Tuple[str, ...]
    base_timeframe: str
    higher_timeframes: Tuple[str, ...]
    feature_names: Tuple[str, ...]
    feature_parameters: Mapping[str, Any] = field(default_factory=lambda: freeze_nested({}))
    lookback_requirements: Mapping[str, int] = field(default_factory=lambda: freeze_nested({}))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    feature_schema_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol_universe", tuple(self.symbol_universe))
        object.__setattr__(self, "higher_timeframes", tuple(self.higher_timeframes))
        object.__setattr__(self, "feature_names", tuple(self.feature_names))
        object.__setattr__(self, "feature_parameters", freeze_nested(self.feature_parameters))
        object.__setattr__(self, "lookback_requirements", freeze_nested(self.lookback_requirements))

        computed_hash = self.compute_schema_hash()
        if self.feature_schema_hash and self.feature_schema_hash != computed_hash:
            raise ValueError(
                f"feature_schema_hash mismatch: expected {computed_hash}, got {self.feature_schema_hash}"
            )
        object.__setattr__(self, "feature_schema_hash", computed_hash)

    def compute_schema_hash(self) -> str:
        """Computes deterministic SHA-256 of all spec fields."""
        clean = {
            "feature_set_id": self.feature_set_id,
            "schema_version": self.schema_version,
            "dataset_manifest_hash": self.dataset_manifest_hash,
            "symbol_universe": sorted(list(self.symbol_universe)),
            "base_timeframe": self.base_timeframe,
            "higher_timeframes": sorted(list(self.higher_timeframes)),
            "feature_names": sorted(list(self.feature_names)),
            "feature_parameters": unfreeze_nested(self.feature_parameters),
            "lookback_requirements": unfreeze_nested(self.lookback_requirements),
        }
        raw_json = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_set_id": self.feature_set_id,
            "schema_version": self.schema_version,
            "dataset_manifest_hash": self.dataset_manifest_hash,
            "symbol_universe": list(self.symbol_universe),
            "base_timeframe": self.base_timeframe,
            "higher_timeframes": list(self.higher_timeframes),
            "feature_names": list(self.feature_names),
            "feature_parameters": unfreeze_nested(self.feature_parameters),
            "lookback_requirements": unfreeze_nested(self.lookback_requirements),
            "created_at": self.created_at,
            "feature_schema_hash": self.feature_schema_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FeatureSetSpec":
        return cls(
            feature_set_id=str(data["feature_set_id"]),
            schema_version=str(data["schema_version"]),
            dataset_manifest_hash=str(data["dataset_manifest_hash"]),
            symbol_universe=tuple(data["symbol_universe"]),
            base_timeframe=str(data["base_timeframe"]),
            higher_timeframes=tuple(data["higher_timeframes"]),
            feature_names=tuple(data["feature_names"]),
            feature_parameters=data.get("feature_parameters", {}),
            lookback_requirements=data.get("lookback_requirements", {}),
            created_at=str(data.get("created_at", datetime.now(timezone.utc).isoformat())),
            feature_schema_hash=str(data.get("feature_schema_hash", "")),
        )

    def save(self, filepath: Path | str) -> None:
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, sort_keys=True, ensure_ascii=False)

    @classmethod
    def load(cls, filepath: Path | str) -> "FeatureSetSpec":
        with open(filepath, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


def build_m3_standard_feature_spec(
    dataset_manifest_hash: str,
    feature_set_id: str = "m3_technical_mtf_v1",
    symbol_universe: Sequence[str] = ("BTC", "ETH"),
    base_timeframe: str = "15m",
    higher_timeframes: Sequence[str] = ("1h", "4h"),
) -> FeatureSetSpec:
    """Builds the canonical standard M3 feature specification."""
    default_parameters = {
        "rsi_period": 14,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "atr_period": 14,
        "sma_periods": [20, 50],
        "volatility_period": 20,
        "volume_period": 20,
        "return_periods": [1, 4, 12, 48],
    }
    lookbacks = {
        "min_warmup_bars": 60,
        "max_lookback_bars": 100,
        "mtf_warmup_bars": 30,
    }
    return FeatureSetSpec(
        feature_set_id=feature_set_id,
        schema_version="1.0.0",
        dataset_manifest_hash=dataset_manifest_hash,
        symbol_universe=tuple(symbol_universe),
        base_timeframe=base_timeframe,
        higher_timeframes=tuple(higher_timeframes),
        feature_names=M3_STANDARD_FEATURE_NAMES,
        feature_parameters=default_parameters,
        lookback_requirements=lookbacks,
    )
