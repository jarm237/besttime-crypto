"""Feature and RL-observation contracts used at inference boundaries."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

RL_EXIT_OBSERVATION_V2_FEATURES = (
    "rsi_normalized", "macd_hist_normalized", "atr_pct_normalized", "adx_normalized",
    "entry_confidence", "regime_strong_trend", "regime_weak_trend", "regime_compression",
    "regime_breakout", "regime_mean_reversion", "regime_panic_sell", "regime_low_liquidity",
    "regime_pump_risk", "pnl_normalized", "hold_time_normalized", "fear_greed_normalized",
    "volume_ratio_normalized", "bb_width_normalized", "max_drawdown_normalized", "market_correlation",
)


@dataclass(frozen=True)
class RLExitObservationV2:
    values: tuple[float, ...]
    feature_names: tuple[str, ...] = RL_EXIT_OBSERVATION_V2_FEATURES
    schema_version: str = "rl-exit-obs-v2"

    def validate(self) -> None:
        if self.schema_version != "rl-exit-obs-v2":
            raise ValueError("unsupported RL observation schema")
        if self.feature_names != RL_EXIT_OBSERVATION_V2_FEATURES or len(self.values) != 20:
            raise ValueError("RL observation schema mismatch: expected 20 ordered features")
        if any(not math.isfinite(float(v)) for v in self.values):
            raise ValueError("RL observation contains NaN/Inf")
        # All runtime features are normalized, with market correlation allowed in [-1, 1].
        if any(abs(float(v)) > 1.000001 for v in self.values):
            raise ValueError("RL observation value outside normalized range")

    def as_list(self) -> list[float]:
        self.validate()
        return list(self.values)


def validate_feature_names(actual: Iterable[str], expected: Iterable[str]) -> None:
    if tuple(actual) != tuple(expected):
        raise ValueError("feature-name/order mismatch")
