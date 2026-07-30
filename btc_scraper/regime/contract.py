"""Canonical market-regime contract and legacy taxonomy mapping."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


TAXONOMY_VERSION = "2.0"
MAPPING_VERSION = "2.0"
DETECTOR_VERSION = "2.0.0"


class RegimeFamily(str, Enum):
    TREND = "TREND"
    RANGE = "RANGE"
    COMPRESSION = "COMPRESSION"
    BREAKOUT = "BREAKOUT"
    EXTREME = "EXTREME"
    UNKNOWN = "UNKNOWN"


class RegimeDirection(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class VolatilityState(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"
    UNKNOWN = "UNKNOWN"


class RegimeLiquidityState(str, Enum):
    NORMAL = "NORMAL"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class MappingQuality(str, Enum):
    EXACT = "EXACT"
    LEGACY = "LEGACY"
    LOSSY = "LOSSY"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RegimeSnapshot:
    regime_id: str
    family: RegimeFamily
    direction: RegimeDirection
    volatility: VolatilityState
    liquidity: RegimeLiquidityState
    confidence: float
    observed_at: str | None
    source_timeframe: str
    detector_version: str
    taxonomy_version: str
    config_sha256: str
    input_end_time: str | None
    warmup_complete: bool
    confidence_method: str = "threshold_distance_v1"
    mapping_version: str = MAPPING_VERSION
    mapping_quality: MappingQuality = MappingQuality.EXACT
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.taxonomy_version:
            raise ValueError("taxonomy_version is required")
        if not self.detector_version:
            raise ValueError("detector_version is required")
        if not self.config_sha256:
            raise ValueError("config_sha256 is required")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("family", "direction", "volatility", "liquidity", "mapping_quality"):
            value = data[key]
            data[key] = value.value if isinstance(value, Enum) else str(value)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RegimeSnapshot":
        return cls(
            regime_id=str(data.get("regime_id") or "UNKNOWN"),
            family=RegimeFamily(str(data.get("family") or "UNKNOWN").upper()),
            direction=RegimeDirection(str(data.get("direction") or "UNKNOWN").upper()),
            volatility=VolatilityState(str(data.get("volatility") or "UNKNOWN").upper()),
            liquidity=RegimeLiquidityState(str(data.get("liquidity") or "UNKNOWN").upper()),
            confidence=float(data.get("confidence") or 0.0),
            observed_at=data.get("observed_at"),
            source_timeframe=str(data.get("source_timeframe") or "unknown"),
            detector_version=str(data.get("detector_version") or ""),
            taxonomy_version=str(data.get("taxonomy_version") or ""),
            config_sha256=str(data.get("config_sha256") or ""),
            input_end_time=data.get("input_end_time"),
            warmup_complete=bool(data.get("warmup_complete", False)),
            confidence_method=str(data.get("confidence_method") or "threshold_distance_v1"),
            mapping_version=str(data.get("mapping_version") or MAPPING_VERSION),
            mapping_quality=MappingQuality(str(data.get("mapping_quality") or "UNKNOWN").upper()),
            reason=data.get("reason"),
        )


@dataclass(frozen=True)
class LegacyRegimeMapping:
    family: RegimeFamily
    direction: RegimeDirection
    volatility: VolatilityState
    liquidity: RegimeLiquidityState = RegimeLiquidityState.NORMAL
    quality: MappingQuality = MappingQuality.EXACT


LEGACY_REGIME_MAP: dict[str, LegacyRegimeMapping] = {
    "STRONG_TREND_BULL": LegacyRegimeMapping(RegimeFamily.TREND, RegimeDirection.BULL, VolatilityState.NORMAL),
    "STRONG_TREND_BEAR": LegacyRegimeMapping(RegimeFamily.TREND, RegimeDirection.BEAR, VolatilityState.NORMAL),
    "WEAK_TREND_BULL": LegacyRegimeMapping(RegimeFamily.TREND, RegimeDirection.BULL, VolatilityState.NORMAL),
    "WEAK_TREND_BEAR": LegacyRegimeMapping(RegimeFamily.TREND, RegimeDirection.BEAR, VolatilityState.NORMAL),
    "TRENDING_BULL": LegacyRegimeMapping(
        RegimeFamily.TREND, RegimeDirection.BULL, VolatilityState.UNKNOWN, quality=MappingQuality.LEGACY
    ),
    "TRENDING_BEAR": LegacyRegimeMapping(
        RegimeFamily.TREND, RegimeDirection.BEAR, VolatilityState.UNKNOWN, quality=MappingQuality.LEGACY
    ),
    "BULL_TREND": LegacyRegimeMapping(
        RegimeFamily.TREND, RegimeDirection.BULL, VolatilityState.UNKNOWN, quality=MappingQuality.LEGACY
    ),
    "BULLISH": LegacyRegimeMapping(
        RegimeFamily.TREND, RegimeDirection.BULL, VolatilityState.UNKNOWN, quality=MappingQuality.LEGACY
    ),
    "BEAR_TREND": LegacyRegimeMapping(
        RegimeFamily.TREND, RegimeDirection.BEAR, VolatilityState.UNKNOWN, quality=MappingQuality.LEGACY
    ),
    "BEARISH": LegacyRegimeMapping(
        RegimeFamily.TREND, RegimeDirection.BEAR, VolatilityState.UNKNOWN, quality=MappingQuality.LEGACY
    ),
    "STRONG_TREND": LegacyRegimeMapping(
        RegimeFamily.TREND, RegimeDirection.UNKNOWN, VolatilityState.UNKNOWN, quality=MappingQuality.LOSSY
    ),
    "WEAK_TREND": LegacyRegimeMapping(
        RegimeFamily.TREND, RegimeDirection.UNKNOWN, VolatilityState.UNKNOWN, quality=MappingQuality.LOSSY
    ),
    "RANGING": LegacyRegimeMapping(RegimeFamily.RANGE, RegimeDirection.NEUTRAL, VolatilityState.NORMAL),
    "SIDEWAY": LegacyRegimeMapping(
        RegimeFamily.RANGE, RegimeDirection.NEUTRAL, VolatilityState.UNKNOWN, quality=MappingQuality.LEGACY
    ),
    "COMPRESSION": LegacyRegimeMapping(RegimeFamily.COMPRESSION, RegimeDirection.NEUTRAL, VolatilityState.LOW),
    "BREAKOUT_BULL": LegacyRegimeMapping(RegimeFamily.BREAKOUT, RegimeDirection.BULL, VolatilityState.HIGH),
    "BREAKOUT_BEAR": LegacyRegimeMapping(RegimeFamily.BREAKOUT, RegimeDirection.BEAR, VolatilityState.HIGH),
    "BREAKOUT": LegacyRegimeMapping(
        RegimeFamily.BREAKOUT, RegimeDirection.UNKNOWN, VolatilityState.HIGH, quality=MappingQuality.LOSSY
    ),
    "MEAN_REVERSION": LegacyRegimeMapping(RegimeFamily.RANGE, RegimeDirection.NEUTRAL, VolatilityState.HIGH),
    "PANIC_SELL": LegacyRegimeMapping(RegimeFamily.EXTREME, RegimeDirection.BEAR, VolatilityState.EXTREME),
    "PUMP_RISK": LegacyRegimeMapping(RegimeFamily.EXTREME, RegimeDirection.BULL, VolatilityState.EXTREME),
    "HIGH_VOLATILITY": LegacyRegimeMapping(
        RegimeFamily.UNKNOWN,
        RegimeDirection.UNKNOWN,
        VolatilityState.HIGH,
        quality=MappingQuality.INCOMPLETE,
    ),
    "LOW_LIQUIDITY": LegacyRegimeMapping(
        RegimeFamily.UNKNOWN,
        RegimeDirection.UNKNOWN,
        VolatilityState.UNKNOWN,
        liquidity=RegimeLiquidityState.LOW,
        quality=MappingQuality.INCOMPLETE,
    ),
    "UNKNOWN": LegacyRegimeMapping(
        RegimeFamily.UNKNOWN,
        RegimeDirection.UNKNOWN,
        VolatilityState.UNKNOWN,
        liquidity=RegimeLiquidityState.UNKNOWN,
        quality=MappingQuality.UNKNOWN,
    ),
}


def map_legacy_regime(value: Any) -> tuple[str, LegacyRegimeMapping]:
    label = str(value or "UNKNOWN").strip().upper() or "UNKNOWN"
    return label, LEGACY_REGIME_MAP.get(label, LEGACY_REGIME_MAP["UNKNOWN"])


MODEL_REGIME_BUCKET_MAP = {
    "STRONG_TREND_BULL": "STRONG_TREND",
    "STRONG_TREND_BEAR": "STRONG_TREND",
    "STRONG_TREND": "STRONG_TREND",
    "WEAK_TREND_BULL": "WEAK_TREND",
    "WEAK_TREND_BEAR": "WEAK_TREND",
    "WEAK_TREND": "WEAK_TREND",
    "COMPRESSION": "COMPRESSION",
    "BREAKOUT_BULL": "BREAKOUT",
    "BREAKOUT_BEAR": "BREAKOUT",
    "BREAKOUT": "BREAKOUT",
    "MEAN_REVERSION": "MEAN_REVERSION",
    "RANGING": "MEAN_REVERSION",
    "PANIC_SELL": "PANIC_SELL",
    "HIGH_VOLATILITY": "PANIC_SELL",
    "LOW_LIQUIDITY": "LOW_LIQUIDITY",
    "PUMP_RISK": "PUMP_RISK",
}


def model_regime_bucket(value: Any, *, default: str = "STRONG_TREND") -> str:
    """Exact, centralized adapter for legacy 8-way model observation schemas."""
    label = str(value or "UNKNOWN").strip().upper()
    return MODEL_REGIME_BUCKET_MAP.get(label, default)


def snapshot_from_legacy(
    value: Any,
    *,
    confidence: float = 0.0,
    observed_at: str | None = None,
    input_end_time: str | None = None,
    source_timeframe: str = "unknown",
    config_sha256: str,
    detector_version: str = DETECTOR_VERSION,
    taxonomy_version: str = TAXONOMY_VERSION,
    warmup_complete: bool = True,
    confidence_method: str = "threshold_distance_v1",
    reason: str | None = None,
) -> RegimeSnapshot:
    label, mapped = map_legacy_regime(value)
    return RegimeSnapshot(
        regime_id=label,
        family=mapped.family,
        direction=mapped.direction,
        volatility=mapped.volatility,
        liquidity=mapped.liquidity,
        confidence=max(0.0, min(1.0, float(confidence))),
        observed_at=observed_at,
        source_timeframe=source_timeframe,
        detector_version=detector_version,
        taxonomy_version=taxonomy_version,
        config_sha256=config_sha256,
        input_end_time=input_end_time,
        warmup_complete=warmup_complete,
        confidence_method=confidence_method,
        mapping_quality=mapped.quality,
        reason=reason,
    )


def coerce_regime_snapshot(
    value: Mapping[str, Any] | RegimeSnapshot | None,
    *,
    fallback_regime: Any = "UNKNOWN",
    fallback_confidence: float = 0.0,
    config_sha256: str,
) -> RegimeSnapshot:
    if isinstance(value, RegimeSnapshot):
        return value
    if isinstance(value, Mapping) and value.get("taxonomy_version"):
        return RegimeSnapshot.from_dict(value)
    return snapshot_from_legacy(
        fallback_regime,
        confidence=fallback_confidence,
        config_sha256=config_sha256,
    )
