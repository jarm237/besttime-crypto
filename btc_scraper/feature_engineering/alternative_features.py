from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class AlternativeFeatureConfig:
    zscore_window: int = 24
    momentum_window: int = 4

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AlternativeFeatureBuilder:
    """Build model-ready alternative features with point-in-time-safe transforms."""

    BASE_COLUMNS = [
        "exchange_netflow",
        "whale_score",
        "stablecoin_supply",
        "tvl",
        "funding_rate",
        "open_interest",
        "dxy",
        "vix",
        "us10y",
        "gold",
        "orderbook_imbalance",
        "liquidity_pressure",
        "macro_pressure",
        "funding_pressure",
        "stablecoin_momentum",
        "etf_momentum",
        "risk_on_score",
        "active_addresses",
        "hashrate",
        "options_iv",
        "iv_skew",
        "etf_flow",
        "sentiment_score",
        "social_sentiment",
    ]

    def __init__(self, config: AlternativeFeatureConfig | None = None) -> None:
        self.config = config or AlternativeFeatureConfig()
        self._last_quality_report: dict[str, Any] = {}

    @staticmethod
    def _to_numeric(series: pd.Series) -> pd.Series:
        return pd.to_numeric(series, errors="coerce")

    def _temporal_sort(self, frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        if "timestamp" in out.columns:
            out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
        if "entry_time" in out.columns:
            out["entry_time"] = pd.to_datetime(out["entry_time"], utc=True, errors="coerce")

        if "coin" in out.columns and "timestamp" in out.columns:
            return out.sort_values(["coin", "timestamp"], kind="mergesort").reset_index(drop=True)
        if "coin" in out.columns and "entry_time" in out.columns:
            return out.sort_values(["coin", "entry_time"], kind="mergesort").reset_index(drop=True)
        if "timestamp" in out.columns:
            return out.sort_values(["timestamp"], kind="mergesort").reset_index(drop=True)
        if "entry_time" in out.columns:
            return out.sort_values(["entry_time"], kind="mergesort").reset_index(drop=True)
        return out.reset_index(drop=True)

    def _safe_rank(self, frame: pd.DataFrame, source_col: str) -> pd.Series:
        if "timestamp" in frame.columns and frame["timestamp"].notna().any():
            counts = frame.groupby("timestamp")[source_col].transform("count")
            if counts.max(skipna=True) and float(counts.max(skipna=True)) > 1:
                return frame.groupby("timestamp")[source_col].rank(method="average", pct=True)
        return pd.Series(np.nan, index=frame.index, dtype="float64")

    def _rolling_zscore(self, series: pd.Series) -> pd.Series:
        rolling_mean = series.rolling(self.config.zscore_window, min_periods=2).mean()
        rolling_std = series.rolling(self.config.zscore_window, min_periods=2).std(ddof=0).replace(0.0, np.nan)
        zscore = (series - rolling_mean) / rolling_std
        return zscore.replace([np.inf, -np.inf], np.nan)

    def _build_quality_report(
        self,
        frame_before: pd.DataFrame,
        frame_after: pd.DataFrame,
        generated_columns: list[str],
    ) -> dict[str, Any]:
        missing_before = {
            col: int(frame_before[col].isna().sum()) if col in frame_before.columns else len(frame_before)
            for col in self.BASE_COLUMNS
        }
        total_rows = max(len(frame_before), 1)
        missing_before_ratio = {
            col: float(count) / float(total_rows)
            for col, count in missing_before.items()
        }
        missing_after_generated = frame_after[generated_columns].isna().sum().to_dict() if generated_columns else {}

        return {
            "input_rows": int(len(frame_before)),
            "output_rows": int(len(frame_after)),
            "base_feature_count": int(len(self.BASE_COLUMNS)),
            "generated_feature_count": int(len(generated_columns)),
            "generated_features": generated_columns,
            "missing_before": missing_before,
            "missing_before_ratio": missing_before_ratio,
            "missing_after_generated": missing_after_generated,
        }

    def build(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            self._last_quality_report = {
                "input_rows": 0,
                "output_rows": 0,
                "base_feature_count": int(len(self.BASE_COLUMNS)),
                "generated_feature_count": 0,
                "generated_features": [],
                "missing_before": {col: 0 for col in self.BASE_COLUMNS},
                "missing_before_ratio": {col: 0.0 for col in self.BASE_COLUMNS},
                "missing_after_generated": {},
            }
            return frame.copy()

        out = self._temporal_sort(frame)
        original = out.copy()

        for col in self.BASE_COLUMNS:
            if col not in out.columns:
                out[col] = np.nan
            out[col] = self._to_numeric(out[col])

        # Preserve source missingness.  An imputer is fitted only in the ML
        # pipeline; filling here would turn an unavailable source into a fake
        # neutral signal.  The flags are model-ready indicators for that step.
        for col in self.BASE_COLUMNS:
            out[f"{col}__missing"] = out[col].isna().astype("int8")

        generated_columns: list[str] = []
        for col in self.BASE_COLUMNS:
            z_col = f"alt_z_{col}"
            m_col = f"alt_mom_{col}"
            d_col = f"alt_chg_{col}"
            r_col = f"alt_rank_{col}"

            if "coin" in out.columns:
                grouped = out.groupby(out["coin"].astype(str), sort=False)[col]
                out[z_col] = grouped.transform(self._rolling_zscore)
                out[m_col] = grouped.transform(lambda s: s.pct_change(self.config.momentum_window))
                out[d_col] = grouped.transform(lambda s: s.diff(1))
            else:
                out[z_col] = self._rolling_zscore(out[col])
                out[m_col] = out[col].pct_change(self.config.momentum_window)
                out[d_col] = out[col].diff(1)

            out[r_col] = self._safe_rank(out, col)

            generated_columns.extend([z_col, m_col, d_col, r_col])

        out[generated_columns] = out[generated_columns].replace([np.inf, -np.inf], np.nan)

        out["alt_macro_stress_composite"] = (
            out["alt_z_dxy"].abs() + out["alt_z_vix"].abs() + out["alt_z_us10y"].abs()
        ) / 3.0
        out["alt_onchain_strength_composite"] = (
            out["alt_z_active_addresses"] + out["alt_z_hashrate"]
        ) / 2.0
        out["alt_sentiment_spread"] = out["sentiment_score"] - out["social_sentiment"]
        out["alt_liquidity_risk_composite"] = (
            out["liquidity_pressure"] + out["funding_pressure"] + out["alt_z_exchange_netflow"].abs()
        ) / 3.0

        generated_columns.extend(
            [
                "alt_macro_stress_composite",
                "alt_onchain_strength_composite",
                "alt_sentiment_spread",
                "alt_liquidity_risk_composite",
            ]
        )

        self._last_quality_report = self._build_quality_report(original, out, generated_columns)
        return out

    def get_quality_report(self) -> dict[str, Any]:
        return dict(self._last_quality_report)
