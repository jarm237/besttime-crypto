from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


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

    def _canonical_regime(self, row: pd.Series) -> str:
        direct = self._norm_text(row.get("regime"))
        if direct != "UNKNOWN":
            if any(token in direct for token in ("BULL", "RISK_ON")):
                return "BULL_TREND"
            if any(token in direct for token in ("BEAR", "RISK_OFF", "PANIC_SELL")):
                return "BEAR_TREND"
            if any(token in direct for token in ("RANGE", "SIDEWAY", "COMPRESSION", "MEAN_REVERSION")):
                return "SIDEWAY"
            if any(token in direct for token in ("TRANSITION", "BREAKOUT")):
                return "TRANSITIONING"

        if float(row.get("regime_trending_bull") or 0.0) > 0:
            return "BULL_TREND"
        if float(row.get("regime_trending_bear") or 0.0) > 0:
            return "BEAR_TREND"
        if float(row.get("regime_ranging") or 0.0) > 0:
            return "SIDEWAY"
        return "SIDEWAY"

    def _regime_duration(self, frame: pd.DataFrame) -> pd.Series:
        if "coin" in frame.columns:
            out = pd.Series(index=frame.index, dtype="int64")
            for _, idx in frame.groupby(frame["coin"].astype(str), sort=False).groups.items():
                sub = frame.loc[idx]
                regime_change = sub["regime"].ne(sub["regime"].shift(1)).cumsum()
                out.loc[idx] = sub.groupby(regime_change).cumcount() + 1
            return out.astype(int)

        regime_change = frame["regime"].ne(frame["regime"].shift(1)).cumsum()
        return (frame.groupby(regime_change).cumcount() + 1).astype(int)

    def build(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame.copy()

        out = frame.copy()

        if "entry_time" in out.columns:
            out["entry_time"] = pd.to_datetime(out["entry_time"], utc=True, errors="coerce")
        if "timestamp" in out.columns:
            out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")

        out["regime"] = out.apply(self._canonical_regime, axis=1)

        if "regime_confidence" not in out.columns:
            out["regime_confidence"] = pd.to_numeric(
                out.get("confidence", out.get("signal_score", 50.0)),
                errors="coerce",
            )
            if out["regime_confidence"].max(skipna=True) > 1.0:
                out["regime_confidence"] = out["regime_confidence"] / 100.0
        out["regime_confidence"] = out["regime_confidence"].fillna(0.5).clip(0.0, 1.0)

        out["regime_duration_bars"] = self._regime_duration(out)

        transition_flag = out["regime"].ne(out["regime"].shift(1)).astype(float)
        out["regime_transition_probability"] = (
            transition_flag.rolling(self.config.transition_window, min_periods=1).mean().clip(0.0, 1.0)
        )

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

        out["regime_bull_trend"] = (out["regime"] == "BULL_TREND").astype(int)
        out["regime_bear_trend"] = (out["regime"] == "BEAR_TREND").astype(int)
        out["regime_sideway"] = (out["regime"] == "SIDEWAY").astype(int)
        out["regime_high_vol"] = (out["regime_volatility_state"] == "HIGH_VOL").astype(int)
        out["regime_low_vol"] = (out["regime_volatility_state"] == "LOW_VOL").astype(int)
        out["regime_risk_on"] = out["regime_bull_trend"].astype(int)
        out["regime_risk_off"] = out["regime_bear_trend"].astype(int)
        out["regime_transitioning"] = (out["regime"] == "TRANSITIONING").astype(int)

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

        return out
