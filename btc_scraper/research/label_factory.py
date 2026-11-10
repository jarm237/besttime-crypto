"""
btc_scraper/research/label_factory.py
Phase M3-C: Point-in-Time Triple-Barrier Label Factory.

Enforces:
1. Next-Bar-Open execution semantics: entry strictly at bar[t+1].open.
2. Triple barriers: Take-Profit (TP), Stop-Loss (SL), and Vertical (Max Holding Time).
3. Intrabar collision resolution: CONSERVATIVE_SL_FIRST if both TP and SL are crossed within the same bar.
4. Economic accounting: gross return, transaction fees, slippage, and net return.
5. Purging & Embargo metadata: label_start_time and label_end_time to prevent walk-forward information leakage.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence


@dataclass(frozen=True)
class TripleBarrierSpec:
    """
    Specification for Triple-Barrier labeling.
    """
    take_profit_pct: float = 0.015       # 1.5% TP
    stop_loss_pct: float = 0.010         # 1.0% SL
    max_holding_bars: int = 16           # 16 bars (4 hours on 15m)
    fee_rate: float = 0.0005             # 5 bps taker fee per side (10 bps roundtrip)
    slippage_rate: float = 0.0002        # 2 bps slippage per side (4 bps roundtrip)
    intrabar_policy: str = "CONSERVATIVE_SL_FIRST"
    min_net_profit_threshold: float = 0.001  # Minimum positive net return for class +1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TripleBarrierSpec":
        return cls(
            take_profit_pct=float(data.get("take_profit_pct", 0.015)),
            stop_loss_pct=float(data.get("stop_loss_pct", 0.010)),
            max_holding_bars=int(data.get("max_holding_bars", 16)),
            fee_rate=float(data.get("fee_rate", 0.0005)),
            slippage_rate=float(data.get("slippage_rate", 0.0002)),
            intrabar_policy=str(data.get("intrabar_policy", "CONSERVATIVE_SL_FIRST")),
            min_net_profit_threshold=float(data.get("min_net_profit_threshold", 0.001)),
        )


@dataclass(frozen=True)
class TripleBarrierLabel:
    """
    Resolved label and economic outcome for an individual decision bar.
    """
    decision_bar_index: int
    decision_time: str
    entry_bar_index: int
    entry_time: str
    entry_price: float
    exit_bar_index: int
    exit_time: str
    exit_price: float
    holding_bars: int
    exit_reason: str  # "TAKE_PROFIT", "STOP_LOSS", "VERTICAL_BARRIER"
    gross_return: float
    net_return: float
    total_cost: float
    label_class: int  # +1 (bullish/profitable), -1 (bearish/loss), 0 (neutral)
    label_start_time: str
    label_end_time: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TripleBarrierLabelFactory:
    """
    Generates point-in-time triple barrier labels aligned with M1 execution semantics.
    """

    def __init__(self, spec: TripleBarrierSpec):
        self.spec = spec
        self.roundtrip_cost = 2.0 * (self.spec.fee_rate + self.spec.slippage_rate)

    def compute_labels(
        self,
        candles: Sequence[Mapping[str, Any]],
        side: str = "LONG",
    ) -> List[Optional[TripleBarrierLabel]]:
        """
        Computes triple barrier labels for each candle in `candles`.
        Returns a list of TripleBarrierLabel (or None for candles too close to dataset end).
        """
        n = len(candles)
        labels: List[Optional[TripleBarrierLabel]] = [None] * n

        if n < 2:
            return labels

        side_upper = side.upper()
        if side_upper not in ("LONG", "SHORT"):
            raise ValueError(f"Unsupported side: {side}. Must be 'LONG' or 'SHORT'")

        is_long = side_upper == "LONG"

        for i in range(n - 1):
            decision_candle = candles[i]
            decision_time = str(decision_candle.get("close_time", decision_candle.get("time", "")))

            # Next-Bar-Open execution
            entry_idx = i + 1
            entry_candle = candles[entry_idx]
            entry_price = float(entry_candle["open"])
            entry_time = str(entry_candle.get("open_time", entry_candle.get("time", "")))

            if entry_price <= 0:
                continue

            # Barrier price levels
            if is_long:
                tp_price = entry_price * (1.0 + self.spec.take_profit_pct)
                sl_price = entry_price * (1.0 - self.spec.stop_loss_pct)
            else:
                tp_price = entry_price * (1.0 - self.spec.take_profit_pct)
                sl_price = entry_price * (1.0 + self.spec.stop_loss_pct)

            # Search forward through holding window
            exit_idx = None
            exit_price = None
            exit_reason = None
            max_eval_idx = min(entry_idx + self.spec.max_holding_bars, n)

            for j in range(entry_idx, max_eval_idx):
                c = candles[j]
                high = float(c["high"])
                low = float(c["low"])

                if is_long:
                    hit_tp = high >= tp_price
                    hit_sl = low <= sl_price

                    if hit_tp and hit_sl:
                        # Collision: conservative policy triggers SL
                        exit_idx = j
                        exit_price = sl_price
                        exit_reason = "STOP_LOSS"
                        break
                    elif hit_sl:
                        exit_idx = j
                        exit_price = sl_price
                        exit_reason = "STOP_LOSS"
                        break
                    elif hit_tp:
                        exit_idx = j
                        exit_price = tp_price
                        exit_reason = "TAKE_PROFIT"
                        break
                else:  # SHORT
                    hit_tp = low <= tp_price
                    hit_sl = high >= sl_price

                    if hit_tp and hit_sl:
                        exit_idx = j
                        exit_price = sl_price
                        exit_reason = "STOP_LOSS"
                        break
                    elif hit_sl:
                        exit_idx = j
                        exit_price = sl_price
                        exit_reason = "STOP_LOSS"
                        break
                    elif hit_tp:
                        exit_idx = j
                        exit_price = tp_price
                        exit_reason = "TAKE_PROFIT"
                        break

            # If not triggered by TP or SL, check vertical barrier timeout
            if exit_idx is None:
                # Vertical barrier reached at last bar of holding window
                terminal_idx = max_eval_idx - 1
                c_term = candles[terminal_idx]
                exit_idx = terminal_idx
                exit_price = float(c_term["close"])
                exit_reason = "VERTICAL_BARRIER"

            exit_candle = candles[exit_idx]
            exit_time = str(exit_candle.get("close_time", exit_candle.get("time", "")))
            holding_bars = exit_idx - entry_idx + 1

            # Returns calculation
            if is_long:
                gross_ret = (exit_price - entry_price) / entry_price
            else:
                gross_ret = (entry_price - exit_price) / entry_price

            net_ret = gross_ret - self.roundtrip_cost

            # Label class assignment
            if exit_reason == "TAKE_PROFIT" and net_ret >= self.spec.min_net_profit_threshold:
                label_class = 1
            elif exit_reason == "STOP_LOSS" or net_ret < -self.spec.min_net_profit_threshold:
                label_class = -1
            else:
                label_class = 0

            # Purge interval: from entry open to exit close
            label_start_time = entry_time
            label_end_time = exit_time

            labels[i] = TripleBarrierLabel(
                decision_bar_index=i,
                decision_time=decision_time,
                entry_bar_index=entry_idx,
                entry_time=entry_time,
                entry_price=entry_price,
                exit_bar_index=exit_idx,
                exit_time=exit_time,
                exit_price=exit_price,
                holding_bars=holding_bars,
                exit_reason=exit_reason,
                gross_return=gross_ret,
                net_return=net_ret,
                total_cost=self.roundtrip_cost,
                label_class=label_class,
                label_start_time=label_start_time,
                label_end_time=label_end_time,
            )

        return labels
