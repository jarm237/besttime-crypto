from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class FractionalDiffConfig:
    enabled: bool = True
    d_candidates: list[float] = field(default_factory=lambda: [0.0, 0.2, 0.4, 0.6, 0.8])
    adf_critical_value: float = -2.86
    weight_threshold: float = 1e-5
    max_weight_size: int = 256
    min_valid_ratio: float = 0.30
    epsilon: float = 1e-9

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FractionalDiffBuilder:
    """Create fractional-differenced features and a stationarity selection report."""

    def __init__(self, config: FractionalDiffConfig | None = None) -> None:
        self.config = config or FractionalDiffConfig()
        self._last_report: dict[str, Any] = {}

    @staticmethod
    def _resolve_time_col(frame: pd.DataFrame) -> str:
        if "timestamp" in frame.columns:
            return "timestamp"
        if "entry_time" in frame.columns:
            return "entry_time"
        raise ValueError("Expected one of time columns: timestamp, entry_time")

    @staticmethod
    def _resolve_coin_col(frame: pd.DataFrame) -> str:
        if "coin" in frame.columns:
            return "coin"
        if "symbol" in frame.columns:
            return "symbol"
        return "coin"

    @staticmethod
    def _resolve_price_col(frame: pd.DataFrame) -> str:
        for col in ("close", "price", "entry_price", "mark_price"):
            if col in frame.columns:
                return col
        for col in ("return_15m", "pnl_pct"):
            if col in frame.columns:
                return col
        raise ValueError("Expected a price-like column: close, price, entry_price, mark_price, return_15m, pnl_pct")

    @staticmethod
    def _adf_tstat(series: pd.Series) -> float:
        """Lightweight ADF-style t-stat (no external statsmodels dependency)."""
        clean = pd.to_numeric(series, errors="coerce").dropna()
        if len(clean) < 20:
            return float("nan")

        y = clean.values.astype("float64")
        dy = np.diff(y)
        y_lag = y[:-1]

        x = np.column_stack([np.ones(len(y_lag)), y_lag])
        beta, _, _, _ = np.linalg.lstsq(x, dy, rcond=None)
        residuals = dy - x @ beta

        dof = len(dy) - x.shape[1]
        if dof <= 0:
            return float("nan")

        sigma2 = float((residuals @ residuals) / dof)
        xtx_inv = np.linalg.inv(x.T @ x)
        se_beta = np.sqrt(np.diag(sigma2 * xtx_inv))
        if se_beta[1] == 0.0:
            return float("nan")
        return float(beta[1] / se_beta[1])

    def _fracdiff_weights(self, d: float) -> np.ndarray:
        weights = [1.0]
        for k in range(1, self.config.max_weight_size):
            next_w = -weights[-1] * (d - k + 1) / k
            if abs(next_w) < self.config.weight_threshold:
                break
            weights.append(next_w)
        # Reverse for dot product over trailing window
        return np.array(weights[::-1], dtype="float64")

    def _fractional_difference(self, series: pd.Series, d: float) -> pd.Series:
        values = pd.to_numeric(series, errors="coerce").values.astype("float64")
        weights = self._fracdiff_weights(d)
        width = len(weights)

        out = np.full(len(values), np.nan, dtype="float64")
        for i in range(width - 1, len(values)):
            window = values[i - width + 1 : i + 1]
            if np.isnan(window).any():
                continue
            out[i] = float(np.dot(weights, window))
        return pd.Series(out, index=series.index)

    def _build_coin_features(self, coin_frame: pd.DataFrame, time_col: str, price_col: str) -> tuple[pd.DataFrame, dict[str, Any]]:
        out = coin_frame.copy()
        price = pd.to_numeric(out[price_col], errors="coerce").astype("float64")

        if price_col in ("return_15m", "pnl_pct"):
            pseudo_price = (1.0 + price.fillna(0.0) / 100.0).cumprod()
            log_price = np.log(pseudo_price.clip(lower=self.config.epsilon))
        else:
            log_price = np.log(price.clip(lower=self.config.epsilon))

        out["fracdiff_source_log_price"] = log_price
        out["fracdiff_return_1_raw"] = log_price.diff(1)

        stationarity_stats: list[dict[str, Any]] = []
        chosen_d = max(self.config.d_candidates)
        chosen_col = ""

        for d in sorted(set(float(x) for x in self.config.d_candidates)):
            col = f"fracdiff_d_{d:.2f}".replace(".", "_")
            out[col] = self._fractional_difference(log_price, d)
            valid_ratio = float(out[col].notna().mean())
            t_stat = self._adf_tstat(out[col])
            stationarity_stats.append({
                "d": d,
                "adf_t_stat": None if np.isnan(t_stat) else float(t_stat),
                "valid_ratio": valid_ratio,
            })
            if chosen_col == "":
                if (not np.isnan(t_stat)) and (t_stat <= self.config.adf_critical_value) and (valid_ratio >= self.config.min_valid_ratio):
                    chosen_d = d
                    chosen_col = col

        if chosen_col == "":
            chosen_col = f"fracdiff_d_{chosen_d:.2f}".replace(".", "_")

        out["fracdiff_d_selected"] = float(chosen_d)
        out["fracdiff_price"] = out[chosen_col]
        out["fracdiff_return_1"] = out["fracdiff_price"].diff(1)

        report = {
            "coin": str(out.iloc[0][out.columns.intersection(["coin", "symbol"])[0]]) if len(out) else "UNKNOWN",
            "selected_d": float(chosen_d),
            "chosen_feature": chosen_col,
            "stationarity": stationarity_stats,
            "rows": int(len(out)),
        }
        return out, report

    def build(self, frame: pd.DataFrame, timeframe: str = "15m") -> pd.DataFrame:
        if frame.empty:
            self._last_report = {
                "timeframe": timeframe,
                "enabled": self.config.enabled,
                "rows": 0,
                "coins": [],
            }
            return frame.copy()

        if not self.config.enabled:
            self._last_report = {
                "timeframe": timeframe,
                "enabled": False,
                "rows": int(len(frame)),
                "coins": [],
                "note": "Fractional differencing disabled via config",
            }
            return frame.copy()

        out = frame.copy()
        time_col = self._resolve_time_col(out)
        coin_col = self._resolve_coin_col(out)
        price_col = self._resolve_price_col(out)

        if coin_col not in out.columns:
            out[coin_col] = "GLOBAL"

        out[coin_col] = out[coin_col].astype(str)
        out[time_col] = pd.to_datetime(out[time_col], utc=True, errors="coerce")
        out = out.sort_values([coin_col, time_col], kind="mergesort").reset_index(drop=True)

        parts: list[pd.DataFrame] = []
        coin_reports: list[dict[str, Any]] = []
        for coin, idx in out.groupby(coin_col, sort=False).groups.items():
            sub = out.loc[idx].copy()
            built, report = self._build_coin_features(sub, time_col=time_col, price_col=price_col)
            report["coin"] = str(coin)
            parts.append(built)
            coin_reports.append(report)

        merged = pd.concat(parts, axis=0).sort_values([coin_col, time_col], kind="mergesort").reset_index(drop=True)
        numeric_cols = merged.select_dtypes(include=[np.number]).columns
        merged[numeric_cols] = merged[numeric_cols].replace([np.inf, -np.inf], np.nan)

        self._last_report = {
            "timeframe": timeframe,
            "enabled": True,
            "rows": int(len(merged)),
            "price_source": price_col,
            "config": self.config.to_dict(),
            "coins": coin_reports,
        }
        return merged

    def get_report(self) -> dict[str, Any]:
        return dict(self._last_report)
