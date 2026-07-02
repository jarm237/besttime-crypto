from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class MetaLabelingConfig:
    exclude_neutral: bool = True
    max_holding_bars: int = 48

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MetaLabeler:
    def __init__(self, config: MetaLabelingConfig | None = None) -> None:
        self.config = config or MetaLabelingConfig()

    @staticmethod
    def _infer_primary_signal(row: pd.Series) -> str:
        for key in ("primary_signal", "signal_raw", "signal", "action"):
            value = row.get(key)
            if value is not None and str(value).strip():
                return str(value).upper()
        return "UNKNOWN"

    @staticmethod
    def _infer_primary_direction(row: pd.Series) -> int:
        direct = row.get("primary_direction")
        if direct is not None and not (isinstance(direct, float) and np.isnan(direct)):
            value = int(float(direct))
            if value > 0:
                return 1
            if value < 0:
                return -1

        direction = row.get("direction")
        if direction is not None and str(direction).strip():
            text = str(direction).upper()
            if text in {"LONG", "BUY", "BULL", "+1", "1"}:
                return 1
            if text in {"SHORT", "SELL", "BEAR", "-1"}:
                return -1

        signal_text = MetaLabeler._infer_primary_signal(row)
        if any(token in signal_text for token in ("SELL", "SHORT", "BEAR")):
            return -1
        if any(token in signal_text for token in ("BUY", "LONG", "BULL")):
            return 1
        return 0

    @staticmethod
    def _is_executable_signal(signal_text: str) -> bool:
        upper = signal_text.upper()
        if "NEUTRAL" in upper:
            return False
        if any(token in upper for token in ("BUY", "SELL", "LONG", "SHORT", "BULL", "BEAR")):
            return True
        return False

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _regime_alignment_score(primary_direction: int, row: pd.Series) -> float:
        if primary_direction == 0:
            return 0.0

        trend_text = str(row.get("htf_trend") or row.get("regime") or "").upper()
        if not trend_text:
            return 0.5

        if "MIXED" in trend_text:
            return 0.5
        if primary_direction > 0 and "BULL" in trend_text:
            return 1.0
        if primary_direction < 0 and "BEAR" in trend_text:
            return 1.0
        return 0.2

    def _trade_quality_components(self, row: pd.Series) -> dict[str, float]:
        ret = float(row.get("barrier_return_pct") or 0.0)
        mae = float(row.get("barrier_mae_pct") or 0.0)
        hold_bars = float(row.get("barrier_hold_bars") or 0.0)
        primary_direction = self._infer_primary_direction(row)

        # Maps return to [0, 1] while staying robust to outliers.
        normalized_return = self._clamp01(0.5 + 0.5 * np.tanh(ret / 3.0))

        adverse = abs(mae)
        rr_proxy = (abs(ret) + 1e-9) / (adverse + 1e-9)
        rr_quality = self._clamp01(rr_proxy / 2.0)

        low_drawdown_quality = self._clamp01(1.0 - adverse / 5.0)
        fast_resolution_quality = self._clamp01(1.0 - hold_bars / float(self.config.max_holding_bars))
        regime_alignment_quality = self._regime_alignment_score(primary_direction, row)

        return {
            "normalized_return": normalized_return,
            "rr_quality": rr_quality,
            "low_drawdown_quality": low_drawdown_quality,
            "fast_resolution_quality": fast_resolution_quality,
            "regime_alignment_quality": regime_alignment_quality,
        }

    def _trade_quality_bucket(self, score: float) -> str:
        if score >= 0.75:
            return "A"
        if score >= 0.55:
            return "B"
        if score >= 0.35:
            return "C"
        return "D"

    def label(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame.copy()

        out = frame.copy()
        primary_signals: list[str] = []
        primary_directions: list[int] = []
        meta_labels: list[float] = []
        meta_reasons: list[str] = []

        quality_scores: list[float] = []
        quality_buckets: list[str] = []

        for _, row in out.iterrows():
            signal_text = self._infer_primary_signal(row)
            direction = self._infer_primary_direction(row)
            primary_signals.append(signal_text)
            primary_directions.append(direction)

            executable = self._is_executable_signal(signal_text)
            triple_label = row.get("triple_barrier_label")
            triple_label = int(float(triple_label)) if triple_label is not None and not pd.isna(triple_label) else 0

            if not executable:
                if self.config.exclude_neutral:
                    meta_labels.append(np.nan)
                    meta_reasons.append("neutral_or_non_executable")
                else:
                    meta_labels.append(0.0)
                    meta_reasons.append("neutral_included_as_skip")
            elif direction == 0:
                meta_labels.append(0.0)
                meta_reasons.append("unknown_direction")
            elif triple_label == direction:
                meta_labels.append(1.0)
                meta_reasons.append("direction_confirmed_by_triple_barrier")
            elif triple_label == 0:
                meta_labels.append(0.0)
                meta_reasons.append("timeout_or_no_directional_edge")
            else:
                meta_labels.append(0.0)
                meta_reasons.append("direction_rejected_by_triple_barrier")

            components = self._trade_quality_components(row)
            score = (
                0.35 * components["normalized_return"]
                + 0.25 * components["rr_quality"]
                + 0.20 * components["low_drawdown_quality"]
                + 0.10 * components["fast_resolution_quality"]
                + 0.10 * components["regime_alignment_quality"]
            )
            quality_scores.append(float(score))
            quality_buckets.append(self._trade_quality_bucket(float(score)))

        out["primary_signal"] = primary_signals
        out["primary_direction"] = primary_directions
        out["meta_label"] = meta_labels
        out["meta_label_reason"] = meta_reasons

        out["trade_quality_score"] = quality_scores
        out["trade_quality_bucket"] = quality_buckets
        return out
