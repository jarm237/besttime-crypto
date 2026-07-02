from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class CrossSectionalFeatureConfig:
    return_window: int = 4
    epsilon: float = 1e-9

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CrossSectionalFeatureBuilder:
    """Build timestamp-safe cross-sectional ranking and relative strength features."""

    def __init__(self, config: CrossSectionalFeatureConfig | None = None) -> None:
        self.config = config or CrossSectionalFeatureConfig()

    @staticmethod
    def _normalize_coin(value: Any) -> str:
        text = str(value or "").strip().upper()
        for suffix in ("USDT", "USD", "-PERP", "PERP"):
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)]
                break
        return text

    @staticmethod
    def _to_numeric(series: pd.Series | Any) -> pd.Series:
        if isinstance(series, pd.Series):
            return pd.to_numeric(series, errors="coerce")
        return pd.Series(dtype="float64")

    @staticmethod
    def _cross_sectional_zscore(series: pd.Series) -> pd.Series:
        std = float(series.std(ddof=0))
        if std == 0.0 or np.isnan(std):
            return pd.Series(np.zeros(len(series), dtype="float64"), index=series.index)
        return (series - float(series.mean())) / std

    @staticmethod
    def _resolve_time_col(frame: pd.DataFrame) -> str:
        if "timestamp" in frame.columns:
            return "timestamp"
        if "entry_time" in frame.columns:
            return "entry_time"
        raise ValueError("Expected one of time columns: timestamp, entry_time")

    @staticmethod
    def _resolve_group_col(frame: pd.DataFrame) -> str | None:
        for col in ("sector", "cluster", "coin_group"):
            if col in frame.columns:
                return col
        return None

    @staticmethod
    def _resolve_price_col(frame: pd.DataFrame) -> str | None:
        for col in ("close", "price", "entry_price", "mark_price"):
            if col in frame.columns:
                return col
        return None

    def build(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame.copy()

        out = frame.copy()
        time_col = self._resolve_time_col(out)

        if "coin" not in out.columns:
            if "symbol" in out.columns:
                out["coin"] = out["symbol"]
            else:
                out["coin"] = "UNKNOWN"

        out["coin"] = out["coin"].astype(str)
        out["coin_norm"] = out["coin"].map(self._normalize_coin)
        out[time_col] = pd.to_datetime(out[time_col], utc=True, errors="coerce")
        out = out.sort_values([time_col, "coin"], kind="mergesort").reset_index(drop=True)

        price_col = self._resolve_price_col(out)
        if price_col is not None:
            out[price_col] = self._to_numeric(out[price_col]).fillna(0.0)
            by_coin = out.groupby("coin_norm", sort=False)[price_col]
            out["cs_return_1"] = by_coin.pct_change(1)
            out["cs_return_n"] = by_coin.pct_change(self.config.return_window)
        else:
            ret1 = self._to_numeric(out.get("return_15m", out.get("pnl_pct", 0.0))).fillna(0.0)
            retn = self._to_numeric(out.get("return_1h", out.get("return_4h", ret1))).fillna(0.0)
            out["cs_return_1"] = ret1
            out["cs_return_n"] = retn

        out["cs_return_1"] = out["cs_return_1"].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        out["cs_return_n"] = out["cs_return_n"].replace([np.inf, -np.inf], np.nan).fillna(0.0)

        out["cs_rank_return_1"] = out.groupby(time_col)["cs_return_1"].rank(method="average", pct=True).fillna(0.5)
        out["cs_rank_return_n"] = out.groupby(time_col)["cs_return_n"].rank(method="average", pct=True).fillna(0.5)
        out["cs_zscore_return_1"] = out.groupby(time_col)["cs_return_1"].transform(self._cross_sectional_zscore)

        btc_series = (
            out.loc[out["coin_norm"] == "BTC", [time_col, "cs_return_1"]]
            .dropna(subset=[time_col])
            .drop_duplicates(subset=[time_col], keep="first")
            .set_index(time_col)["cs_return_1"]
        )
        eth_series = (
            out.loc[out["coin_norm"] == "ETH", [time_col, "cs_return_1"]]
            .dropna(subset=[time_col])
            .drop_duplicates(subset=[time_col], keep="first")
            .set_index(time_col)["cs_return_1"]
        )

        out["cs_btc_return_1"] = out[time_col].map(btc_series).fillna(0.0)
        out["cs_eth_return_1"] = out[time_col].map(eth_series).fillna(0.0)
        out["cs_rel_strength_btc"] = out["cs_return_1"] - out["cs_btc_return_1"]
        out["cs_rel_strength_eth"] = out["cs_return_1"] - out["cs_eth_return_1"]
        out["cs_rel_strength_ratio_btc"] = out["cs_return_1"] / (out["cs_btc_return_1"].abs() + self.config.epsilon)
        out["cs_rel_strength_ratio_eth"] = out["cs_return_1"] / (out["cs_eth_return_1"].abs() + self.config.epsilon)

        group_col = self._resolve_group_col(out)
        if group_col is not None:
            out["cs_group"] = out[group_col].astype(str).replace("", "UNKNOWN").fillna("UNKNOWN")
        else:
            out["cs_group"] = "UNKNOWN"

        grouped = out.groupby([time_col, "cs_group"])
        out["cs_group_rank_return_1"] = grouped["cs_return_1"].rank(method="average", pct=True).fillna(0.5)
        out["cs_group_mean_return_1"] = grouped["cs_return_1"].transform("mean").fillna(0.0)
        out["cs_group_excess_return_1"] = out["cs_return_1"] - out["cs_group_mean_return_1"]

        numeric_cols = out.select_dtypes(include=[np.number]).columns
        out[numeric_cols] = out[numeric_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        return out
