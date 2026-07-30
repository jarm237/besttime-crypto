from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from btc_scraper.regime.contract import (
    MAPPING_VERSION,
    TAXONOMY_VERSION,
    RegimeDirection,
    RegimeFamily,
    RegimeSnapshot,
    map_legacy_regime,
)


@dataclass
class RegimeFeatureConfig:
    transition_window: int = 8
    high_vol_threshold: float = 2.0
    low_vol_threshold: float = 0.8

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RegimeFeatureBuilder:
    def __init__(self, config: RegimeFeatureConfig | None = None) -> None:
        self.config = config or RegimeFeatureConfig()

    @staticmethod
    def _norm_text(value: Any) -> str:
        if value is None:
            return "UNKNOWN"
        text = str(value).strip().upper()
        return text if text else "UNKNOWN"

    def _legacy_regime(self, row: pd.Series) -> str:
        direct = self._norm_text(row.get("regime"))
        if direct != "UNKNOWN":
            return direct

        if float(row.get("regime_trending_bull") or 0.0) > 0:
            return "TRENDING_BULL"
        if float(row.get("regime_trending_bear") or 0.0) > 0:
            return "TRENDING_BEAR"
        if float(row.get("regime_ranging") or 0.0) > 0:
            return "RANGING"
        if float(row.get("regime_high_volatility") or 0.0) > 0:
            return "HIGH_VOLATILITY"
        return "UNKNOWN"

    def _canonical_components(self, row: pd.Series) -> pd.Series:
        raw_snapshot = row.get("regime_snapshot")
        if isinstance(raw_snapshot, dict) and raw_snapshot.get("taxonomy_version"):
            try:
                snapshot = RegimeSnapshot.from_dict(raw_snapshot)
                return pd.Series(
                    {
                        "regime": snapshot.regime_id,
                        "regime_family": snapshot.family.value,
                        "regime_direction": snapshot.direction.value,
                        "regime_mapping_quality": snapshot.mapping_quality.value,
                        "regime_taxonomy_version": snapshot.taxonomy_version,
                        "regime_mapping_version": snapshot.mapping_version,
                        "_snapshot_confidence": snapshot.confidence,
                    }
                )
            except (TypeError, ValueError):
                pass

        label, mapped = map_legacy_regime(self._legacy_regime(row))
        return pd.Series(
            {
                "regime": label,
                "regime_family": mapped.family.value,
                "regime_direction": mapped.direction.value,
                "regime_mapping_quality": mapped.quality.value,
                "regime_taxonomy_version": TAXONOMY_VERSION,
                "regime_mapping_version": MAPPING_VERSION,
                "_snapshot_confidence": np.nan,
            }
        )

    def _regime_duration(self, frame: pd.DataFrame) -> pd.Series:
        if "coin" in frame.columns:
            out = pd.Series(index=frame.index, dtype="int64")
            for _, idx in frame.groupby(frame["coin"].astype(str), sort=False).groups.items():
                sub = frame.loc[idx]
                state = sub["_canonical_state"]
                regime_change = state.ne(state.shift(1)).cumsum()
                out.loc[idx] = sub.groupby(regime_change).cumcount() + 1
            return out.astype(int)

        regime_change = frame["_canonical_state"].ne(frame["_canonical_state"].shift(1)).cumsum()
        return (frame.groupby(regime_change).cumcount() + 1).astype(int)

    def build(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame.copy()

        out = frame.copy()

        if "entry_time" in out.columns:
            out["entry_time"] = pd.to_datetime(out["entry_time"], utc=True, errors="coerce")
        if "timestamp" in out.columns:
            out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")

        time_col = "entry_time" if "entry_time" in out.columns else "timestamp" if "timestamp" in out.columns else None
        sort_cols = [column for column in ("coin", time_col) if column and column in out.columns]
        if sort_cols:
            out = out.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)
        if time_col and "coin" in out.columns and out.duplicated(["coin", time_col]).any():
            raise ValueError("Duplicate coin/time rows are not allowed in regime features")

        components = out.apply(self._canonical_components, axis=1)
        for column in components.columns:
            out[column] = components[column]
        out["_canonical_state"] = (
            out["regime_family"].astype(str)
            + ":"
            + out["regime_direction"].astype(str)
            + ":"
            + out["regime"].astype(str)
        )

        explicit_confidence = (
            pd.to_numeric(out["regime_confidence"], errors="coerce")
            if "regime_confidence" in out.columns
            else pd.Series(np.nan, index=out.index, dtype=float)
        )
        snapshot_confidence = pd.to_numeric(out["_snapshot_confidence"], errors="coerce")
        out["regime_confidence"] = explicit_confidence.combine_first(snapshot_confidence).clip(0.0, 1.0)
        out["regime_confidence_missing"] = out["regime_confidence"].isna().astype(int)

        out["regime_duration_bars"] = self._regime_duration(out)

        def transition_probability(state: pd.Series) -> pd.Series:
            transition = state.ne(state.shift(1)).astype(float)
            if not transition.empty:
                transition.iloc[0] = 0.0
            return transition.rolling(self.config.transition_window, min_periods=1).mean().clip(0.0, 1.0)

        if "coin" in out.columns:
            out["regime_transition_probability"] = out.groupby(
                out["coin"].astype(str), sort=False
            )["_canonical_state"].transform(
                transition_probability
            )
        else:
            out["regime_transition_probability"] = transition_probability(out["_canonical_state"])

        if "atr_pct" in out.columns:
            vol_proxy = pd.to_numeric(out["atr_pct"], errors="coerce").fillna(0.0)
        elif "realized_vol_20" in out.columns:
            vol_proxy = pd.to_numeric(out["realized_vol_20"], errors="coerce").fillna(0.0)
        else:
            vol_proxy = pd.Series(0.0, index=out.index)
        out["regime_volatility_state"] = np.select(
            [vol_proxy >= self.config.high_vol_threshold, vol_proxy <= self.config.low_vol_threshold],
            ["HIGH_VOL", "LOW_VOL"],
            default="NORMAL_VOL",
        )

        ema9 = pd.to_numeric(out["ema9_slope"], errors="coerce").fillna(0.0) if "ema9_slope" in out.columns else pd.Series(0.0, index=out.index)
        ema21 = pd.to_numeric(out["ema21_slope"], errors="coerce").fillna(0.0) if "ema21_slope" in out.columns else pd.Series(0.0, index=out.index)
        trend_proxy = ema9 - ema21
        out["regime_trend_state"] = np.select(
            [trend_proxy > 0.0, trend_proxy < 0.0],
            ["UPTREND", "DOWNTREND"],
            default="FLAT",
        )

        if "volume_ratio" in out.columns:
            liquidity_proxy = pd.to_numeric(out["volume_ratio"], errors="coerce").fillna(1.0)
        elif "liquidity_pressure" in out.columns:
            liquidity_proxy = pd.to_numeric(out["liquidity_pressure"], errors="coerce").fillna(1.0)
        else:
            liquidity_proxy = pd.Series(1.0, index=out.index)
        out["regime_liquidity_state"] = np.select(
            [liquidity_proxy >= 1.5, liquidity_proxy <= 0.8],
            ["HIGH", "LOW"],
            default="NORMAL",
        )

        out["regime_bull_trend"] = (
            (out["regime_family"] == RegimeFamily.TREND.value)
            & (out["regime_direction"] == RegimeDirection.BULL.value)
        ).astype(int)
        out["regime_bear_trend"] = (
            (out["regime_family"] == RegimeFamily.TREND.value)
            & (out["regime_direction"] == RegimeDirection.BEAR.value)
        ).astype(int)
        out["regime_sideway"] = (out["regime_family"] == RegimeFamily.RANGE.value).astype(int)
        out["regime_unknown"] = (out["regime_family"] == RegimeFamily.UNKNOWN.value).astype(int)
        out["regime_high_vol"] = (out["regime_volatility_state"] == "HIGH_VOL").astype(int)
        out["regime_low_vol"] = (out["regime_volatility_state"] == "LOW_VOL").astype(int)
        out["regime_risk_on"] = out["regime_bull_trend"].astype(int)
        out["regime_risk_off"] = out["regime_bear_trend"].astype(int)
        out["regime_transitioning"] = (out["regime_family"] == RegimeFamily.BREAKOUT.value).astype(int)

        rsi = pd.to_numeric(out["rsi"], errors="coerce").fillna(0.0) if "rsi" in out.columns else pd.Series(0.0, index=out.index)
        funding = pd.to_numeric(out["funding_rate"], errors="coerce").fillna(0.0) if "funding_rate" in out.columns else pd.Series(0.0, index=out.index)
        
        if "dxy" in out.columns:
            dxy = pd.to_numeric(out["dxy"], errors="coerce").fillna(0.0)
        elif "DXY" in out.columns:
            dxy = pd.to_numeric(out["DXY"], errors="coerce").fillna(0.0)
        else:
            dxy = pd.Series(0.0, index=out.index)
            
        if "open_interest_delta" in out.columns:
            oi_delta = pd.to_numeric(out["open_interest_delta"], errors="coerce").fillna(0.0)
        elif "oi_delta" in out.columns:
            oi_delta = pd.to_numeric(out["oi_delta"], errors="coerce").fillna(0.0)
        else:
            oi_delta = pd.Series(0.0, index=out.index)
            
        orderbook_imbalance = pd.to_numeric(out["orderbook_imbalance"], errors="coerce").fillna(0.0) if "orderbook_imbalance" in out.columns else pd.Series(0.0, index=out.index)

        out["rsi_x_regime_bull"] = rsi * out["regime_bull_trend"]
        out["funding_x_regime_risk_on"] = funding * out["regime_risk_on"]
        out["dxy_x_regime_risk_off"] = dxy * out["regime_risk_off"]
        out["oi_delta_x_high_vol"] = oi_delta * out["regime_high_vol"]
        out["orderbook_imbalance_x_trend"] = orderbook_imbalance * (out["regime_bull_trend"] - out["regime_bear_trend"])

        return out.drop(columns=["_snapshot_confidence", "_canonical_state"], errors="ignore")
