from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class TripleBarrierConfig:
    timeframe: str = "15m"
    max_holding_bars: int = 48
    tp_atr_mult: float = 2.0
    sl_atr_mult: float = 1.2
    use_dynamic_atr: bool = True
    min_rr: float = 1.3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TripleBarrierLabeler:
    def __init__(self, config: TripleBarrierConfig | None = None) -> None:
        self.config = config or TripleBarrierConfig()

    @staticmethod
    def _normalize_candle_schema(candles: pd.DataFrame) -> pd.DataFrame:
        if candles.empty:
            return candles.copy()

        frame = candles.copy()
        lowered = {c.lower().strip(): c for c in frame.columns}

        if "time" in lowered and "timestamp" not in lowered:
            frame = frame.rename(columns={lowered["time"]: "timestamp"})
        elif "timestamp" in lowered:
            frame = frame.rename(columns={lowered["timestamp"]: "timestamp"})

        required = ["timestamp", "open", "high", "low", "close"]
        missing = [name for name in required if name not in {c.lower() for c in frame.columns}]
        if missing:
            raise ValueError(f"Candle data missing columns: {missing}")

        rename_map = {}
        for target in ("open", "high", "low", "close", "volume"):
            for col in frame.columns:
                if col.lower() == target:
                    rename_map[col] = target
                    break
        frame = frame.rename(columns=rename_map)

        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

        for col in ("open", "high", "low", "close"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")

        frame = frame.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
        return frame

    @staticmethod
    def _compute_atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
        high = frame["high"]
        low = frame["low"]
        prev_close = frame["close"].shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(period, min_periods=1).mean()
        return atr

    @staticmethod
    def _infer_direction(signal_row: pd.Series) -> int:
        if "primary_direction" in signal_row and pd.notna(signal_row["primary_direction"]):
            value = str(signal_row["primary_direction"]).upper()
            if value in {"LONG", "BUY", "BULL", "+1", "1"}:
                return 1
            if value in {"SHORT", "SELL", "BEAR", "-1"}:
                return -1

        if "direction" in signal_row and pd.notna(signal_row["direction"]):
            value = str(signal_row["direction"]).upper()
            if value in {"LONG", "BUY", "BULL", "+1", "1"}:
                return 1
            if value in {"SHORT", "SELL", "BEAR", "-1"}:
                return -1

        composite = " ".join(
            str(signal_row.get(key, ""))
            for key in ("signal", "signal_raw", "action", "primary_signal")
        ).upper()
        if any(token in composite for token in ("SELL", "SHORT", "BEAR")):
            return -1
        if any(token in composite for token in ("BUY", "LONG", "BULL")):
            return 1
        return 0

    @staticmethod
    def _calc_mfe_mae(direction: int, entry_price: float, window: pd.DataFrame) -> tuple[float, float]:
        if direction == 1:
            mfe = (window["high"].max() - entry_price) / entry_price * 100.0
            mae = (window["low"].min() - entry_price) / entry_price * 100.0
        else:
            mfe = (entry_price - window["low"].min()) / entry_price * 100.0
            mae = (entry_price - window["high"].max()) / entry_price * 100.0
        return float(mfe), float(mae)

    @staticmethod
    def _calc_return_pct(direction: int, entry_price: float, exit_price: float) -> float:
        if direction == 1:
            return float((exit_price - entry_price) / entry_price * 100.0)
        return float((entry_price - exit_price) / entry_price * 100.0)

    def label(self, signals: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
        if signals.empty:
            return signals.copy()

        candle_frame = self._normalize_candle_schema(candles)
        if candle_frame.empty:
            raise ValueError("No valid candle rows after normalization")

        candle_frame["atr_14"] = self._compute_atr(candle_frame)

        out = signals.copy()
        out["entry_time"] = pd.to_datetime(out["entry_time"], utc=True, errors="coerce")

        labels: list[int] = []
        reasons: list[str] = []
        hit_times: list[pd.Timestamp | pd.NaT] = []
        hold_bars: list[int] = []
        returns_pct: list[float] = []
        mfes_pct: list[float] = []
        maes_pct: list[float] = []

        ts_values = candle_frame["timestamp"].values
        for _, row in out.iterrows():
            entry_time = row.get("entry_time")
            direction = self._infer_direction(row)

            if pd.isna(entry_time):
                labels.append(0)
                reasons.append("invalid_entry_time")
                hit_times.append(pd.NaT)
                hold_bars.append(0)
                returns_pct.append(0.0)
                mfes_pct.append(0.0)
                maes_pct.append(0.0)
                continue

            if direction == 0:
                labels.append(0)
                reasons.append("neutral_signal")
                hit_times.append(pd.NaT)
                hold_bars.append(0)
                returns_pct.append(0.0)
                mfes_pct.append(0.0)
                maes_pct.append(0.0)
                continue

            start_idx = int(ts_values.searchsorted(np.datetime64(entry_time), side="left"))
            if start_idx >= len(candle_frame):
                labels.append(0)
                reasons.append("entry_after_candle_range")
                hit_times.append(pd.NaT)
                hold_bars.append(0)
                returns_pct.append(0.0)
                mfes_pct.append(0.0)
                maes_pct.append(0.0)
                continue

            entry_candle = candle_frame.iloc[start_idx]
            entry_price = float(
                row.get("entry_price")
                or row.get("entry")
                or row.get("close")
                or entry_candle["close"]
            )
            if entry_price <= 0:
                labels.append(0)
                reasons.append("invalid_entry_price")
                hit_times.append(pd.NaT)
                hold_bars.append(0)
                returns_pct.append(0.0)
                mfes_pct.append(0.0)
                maes_pct.append(0.0)
                continue

            atr_value = None
            if self.config.use_dynamic_atr:
                atr_value = row.get("atr")
                if atr_value is None or (isinstance(atr_value, float) and np.isnan(atr_value)):
                    atr_pct = row.get("atr_pct")
                    if atr_pct is not None and not (isinstance(atr_pct, float) and np.isnan(atr_pct)):
                        atr_value = entry_price * float(atr_pct) / 100.0
                if atr_value is None or (isinstance(atr_value, float) and np.isnan(atr_value)):
                    atr_value = float(entry_candle["atr_14"])
            else:
                atr_value = float(entry_candle["atr_14"])

            atr_value = float(atr_value) if atr_value is not None else 0.0
            if atr_value <= 0:
                labels.append(0)
                reasons.append("invalid_atr")
                hit_times.append(pd.NaT)
                hold_bars.append(0)
                returns_pct.append(0.0)
                mfes_pct.append(0.0)
                maes_pct.append(0.0)
                continue

            tp_distance = atr_value * float(self.config.tp_atr_mult)
            sl_distance = atr_value * float(self.config.sl_atr_mult)

            rr = tp_distance / sl_distance if sl_distance > 0 else 0.0
            if rr < self.config.min_rr:
                labels.append(0)
                reasons.append("rr_below_min")
                hit_times.append(pd.NaT)
                hold_bars.append(0)
                returns_pct.append(0.0)
                mfes_pct.append(0.0)
                maes_pct.append(0.0)
                continue

            if direction == 1:
                upper_barrier = entry_price + tp_distance
                lower_barrier = entry_price - sl_distance
            else:
                upper_barrier = entry_price + sl_distance
                lower_barrier = entry_price - tp_distance

            end_idx = min(len(candle_frame) - 1, start_idx + int(self.config.max_holding_bars))
            window = candle_frame.iloc[start_idx : end_idx + 1]
            mfe_pct, mae_pct = self._calc_mfe_mae(direction, entry_price, window)

            final_label = 0
            final_reason = "timeout"
            final_time = candle_frame.iloc[end_idx]["timestamp"]
            final_hold_bars = int(end_idx - start_idx)
            exit_price = float(candle_frame.iloc[end_idx]["close"])

            for i in range(start_idx, end_idx + 1):
                bar = candle_frame.iloc[i]
                high = float(bar["high"])
                low = float(bar["low"])

                if direction == 1:
                    tp_hit = high >= upper_barrier
                    sl_hit = low <= lower_barrier
                else:
                    tp_hit = low <= lower_barrier
                    sl_hit = high >= upper_barrier

                if tp_hit and sl_hit:
                    final_label = -1
                    final_reason = "both_hit_same_bar_stop_loss_priority"
                    final_time = bar["timestamp"]
                    final_hold_bars = int(i - start_idx)
                    exit_price = lower_barrier if direction == 1 else upper_barrier
                    break

                if tp_hit:
                    final_label = 1
                    final_reason = "take_profit"
                    final_time = bar["timestamp"]
                    final_hold_bars = int(i - start_idx)
                    exit_price = upper_barrier if direction == 1 else lower_barrier
                    break

                if sl_hit:
                    final_label = -1
                    final_reason = "stop_loss"
                    final_time = bar["timestamp"]
                    final_hold_bars = int(i - start_idx)
                    exit_price = lower_barrier if direction == 1 else upper_barrier
                    break

            labels.append(int(final_label))
            reasons.append(final_reason)
            hit_times.append(final_time)
            hold_bars.append(final_hold_bars)
            returns_pct.append(self._calc_return_pct(direction, entry_price, exit_price))
            mfes_pct.append(mfe_pct)
            maes_pct.append(mae_pct)

        out["triple_barrier_label"] = labels
        out["triple_barrier_reason"] = reasons
        out["barrier_hit_time"] = hit_times
        out["barrier_hold_bars"] = hold_bars
        out["barrier_return_pct"] = returns_pct
        out["barrier_mfe_pct"] = mfes_pct
        out["barrier_mae_pct"] = maes_pct
        out["primary_direction"] = out.apply(self._infer_direction, axis=1)
        return out
