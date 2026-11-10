"""
btc_scraper/research/baseline_runner.py
Phase M1-E: Minimum Reproducible Baseline Runner.

Executes baseline strategies across common historical dataset and cost models:
1. AlwaysFlatStrategy (0 trades anchor)
2. PassiveBuyAndHoldStrategy (exposure-matched passive baseline)
3. SimpleMovingAverageCrossoverStrategy (SMA trend baseline)
4. SevenLayerProxyStrategy (heuristic trend-pullback proxy; PROXY / NOT_PRODUCTION_EQUIVALENT)
"""
from __future__ import annotations

import copy
import math
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from btc_scraper.research.experiment_contract import (
    ExperimentResult,
    ExperimentSpec,
    freeze_nested,
)


# ── Baseline Strategy Interface ───────────────────────────────────────────────

class BaselineStrategy(ABC):
    """
    Standard interface for all benchmark and candidate strategies.
    Ensures that every strategy is evaluated on identical bar-by-bar inputs.
    """
    TIER: str = "BENCHMARK"
    STATUS: str = "ACTIVE"

    def __init__(self, name: str):
        self.name = name

    def reset(self) -> None:
        """Reset internal strategy state between evaluation runs."""
        pass

    @abstractmethod
    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluate a single bar in sequence.
        Returns:
            None if no action is taken.
            dict with {
                'action': 'BUY' | 'SELL' | 'CLOSE',
                'target_notional': float,  # optional override
                'stop_loss': float,         # optional price
                'take_profit': float,       # optional price
                'reason': str,
            }
        """
        pass


# ── Strategy 1: Always Flat (No-Trade Anchor) ──────────────────────────────────

class AlwaysFlatStrategy(BaselineStrategy):
    """
    Anchor strategy that never enters any position.
    Proves that the experiment framework records 0 trades, 0 fees, and 0 drift.
    """
    TIER = "BENCHMARK"
    STATUS = "ACTIVE"

    def __init__(self):
        super().__init__("always_flat")

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        return None


# ── Strategy 2: Passive Buy & Hold ───────────────────────────────────────────

class PassiveBuyAndHoldStrategy(BaselineStrategy):
    """
    Buys on the first available opportunity and holds throughout the evaluation window.
    Measures the underlying asset's beta and raw buy-and-hold benchmark.
    """
    TIER = "BENCHMARK"
    STATUS = "ACTIVE"

    def __init__(self):
        super().__init__("buy_and_hold")
        self._entered: Dict[str, bool] = {}

    def reset(self) -> None:
        self._entered.clear()

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if not self._entered.get(symbol, False) and current_position is None:
            self._entered[symbol] = True
            return {
                "action": "BUY",
                "reason": "buy_and_hold_initial_entry",
            }
        return None


# ── Strategy 3: Simple Trend Following (SMA Crossover) ─────────────────────────

class SimpleMovingAverageCrossoverStrategy(BaselineStrategy):
    """
    Standard trend-following benchmark using fast and slow Simple Moving Averages.
    """
    TIER = "BENCHMARK"
    STATUS = "ACTIVE"

    def __init__(self, fast_period: int = 9, slow_period: int = 21):
        super().__init__(f"sma_crossover_{fast_period}_{slow_period}")
        self.fast_period = fast_period
        self.slow_period = slow_period

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if len(historical_candles) < self.slow_period + 1:
            return None

        # Slicing the required tail ensures O(1) step evaluation
        tail = historical_candles[-(self.slow_period + 2):]
        closes = [float(c["close"]) for c in tail]
        fast_sma = sum(closes[-self.fast_period:]) / self.fast_period
        slow_sma = sum(closes[-self.slow_period:]) / self.slow_period
        
        prev_fast_sma = sum(closes[-self.fast_period - 1:-1]) / self.fast_period
        prev_slow_sma = sum(closes[-self.slow_period - 1:-1]) / self.slow_period

        # Bullish crossover (Golden Cross) -> Buy if no position
        if prev_fast_sma <= prev_slow_sma and fast_sma > slow_sma:
            if current_position is None:
                return {"action": "BUY", "reason": "sma_golden_cross"}
        
        # Bearish crossover (Death Cross) -> Close if open position
        elif prev_fast_sma >= prev_slow_sma and fast_sma < slow_sma:
            if current_position is not None:
                return {"action": "CLOSE", "reason": "sma_death_cross"}

        return None


# ── Strategy 4: Seven-Layer Proxy Strategy (Heuristic Baseline) ────────────────

class SevenLayerProxyStrategy(BaselineStrategy):
    """
    Heuristic trend-pullback proxy baseline mimicking multi-layer trend & volatility logic.
    STATUS: PROXY / NOT_PRODUCTION_EQUIVALENT.
    Do NOT use this proxy as a canonical champion to declare production strategy superiority.
    """
    TIER = "PROXY"
    STATUS = "PROXY / NOT_PRODUCTION_EQUIVALENT"

    def __init__(self, r_multiple: float = 2.0, name: str = "seven_layer_proxy"):
        super().__init__(name)
        self.r_multiple = r_multiple

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if len(historical_candles) < 30:
            return None

        # Slicing the required tail ensures O(1) step evaluation
        tail = historical_candles[-35:]
        closes = [float(c["close"]) for c in tail]
        current_price = closes[-1]
        sma_20 = sum(closes[-20:]) / 20.0
        
        # Approximate volatility (ATR proxy)
        highs = [float(c.get("high", c["close"])) for c in tail[-14:]]
        lows = [float(c.get("low", c["close"])) for c in tail[-14:]]
        tr_sum = sum(h - l for h, l in zip(highs, lows))
        atr = tr_sum / 14.0 if tr_sum > 0 else current_price * 0.01

        # Intrabar stops are managed by the execution runner.
        # Here we only generate new entry if flat, or manual signal exits.
        if current_position is None:
            # Trend confirmation + pullback crossing SMA 20
            if current_price > sma_20 and closes[-2] <= sma_20:
                sl_price = current_price - 1.5 * atr
                tp_price = current_price + (1.5 * self.r_multiple * atr)
                return {
                    "action": "BUY",
                    "stop_loss": sl_price,
                    "take_profit": tp_price,
                    "reason": "seven_layer_proxy_trend_pullback",
                }

        return None


# Backwards compatibility alias with warning
class Champion7LayerStrategy(SevenLayerProxyStrategy):
    """
    Deprecated alias for SevenLayerProxyStrategy.
    Explicitly marked as PROXY / NOT_PRODUCTION_EQUIVALENT.
    """
    def __init__(self, r_multiple: float = 2.0):
        super().__init__(r_multiple=r_multiple, name="champion_v3_7layer")


# ── Chronological Experiment Runner (M1-E) ───────────────────────────────────

class ExperimentRunner:
    """
    Standardized, zero-leakage, event-driven runner that simulates execution
    of any BaselineStrategy against an ExperimentSpec and historical candle dataset.
    
    Execution Timing Model:
    - Default policy: NEXT_BAR_OPEN.
    - Signal generated at bar t close -> Order filled at bar t+1 open (plus spread + slippage).
    - Intrabar SL/TP execution checked against bar t+1 high/low with conservative policy:
      if both hit, same_candle_policy (e.g. CONSERVATIVE_SL_FIRST) governs.
    """
    def __init__(self, spec: ExperimentSpec, liquidate_at_end: bool = False):
        self.spec = spec
        self.liquidate_at_end = liquidate_at_end
        self._fee_bps = float(
            self.spec.fee_model.get("futures_taker_bps", 5.0)
            if self.spec.fee_model.get("is_futures", True)
            else self.spec.fee_model.get("spot_taker_bps", 10.0)
        )
        self._slippage_bps = float(
            self.spec.slippage_model.get("base_slippage_bps", 2.0)
            if self.spec.slippage_model.get("enabled", True)
            else 0.0
        )
        self._spread_bps = float(
            self.spec.spread_model.get("typical_spread_bps", 1.5)
            if self.spec.spread_model.get("enabled", True)
            else 0.0
        )

    def _calc_effective_price(self, raw_price: float, side: str) -> Tuple[float, float, float]:
        """Calculates effective price after spread and slippage."""
        spread_drag = raw_price * (self._spread_bps / 20_000.0)
        slip_drag = raw_price * (self._slippage_bps / 10_000.0)
        if side.upper() in ("BUY", "LONG"):
            eff_p = raw_price + spread_drag + slip_drag
        else:
            eff_p = raw_price - spread_drag - slip_drag
        return eff_p, spread_drag, slip_drag

    def run(
        self,
        strategy: BaselineStrategy,
        candles_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> ExperimentResult:
        """
        Executes bar-by-bar chronological simulation across all symbols in spec.
        """
        initial_capital = float(self.spec.initial_capital)
        current_cash = initial_capital
        strategy.reset()
        open_positions: Dict[str, Dict[str, Any]] = {}
        pending_orders: Dict[str, Dict[str, Any]] = {}
        trade_log: List[Dict[str, Any]] = []
        equity_curve: List[Dict[str, Any]] = []

        # 1. Align timeline across symbols (sorted unique timestamps)
        all_times = set()
        for sym in self.spec.symbol_universe:
            candles = candles_by_symbol.get(sym, [])
            for c in candles:
                all_times.add(str(c.get("time", c.get("timestamp"))))
        
        sorted_times = sorted(list(all_times))
        if not sorted_times:
            return ExperimentResult.from_trades_and_equity(self.spec, [], [])

        candle_indices: Dict[str, Dict[str, int]] = {}
        for sym in self.spec.symbol_universe:
            candle_indices[sym] = {
                str(c.get("time", c.get("timestamp"))): idx
                for idx, c in enumerate(candles_by_symbol.get(sym, []))
            }

        start_oos, end_oos = self.spec.oos_window

        # 2. Bar-by-bar chronological walk
        for t_step in sorted_times:
            # Filter OOS evaluation window
            if t_step < start_oos or t_step > end_oos:
                continue

            for sym in self.spec.symbol_universe:
                sym_candles = candles_by_symbol.get(sym, [])
                idx_map = candle_indices.get(sym, {})
                if t_step not in idx_map:
                    continue
                
                curr_idx = idx_map[t_step]
                curr_candle = sym_candles[curr_idx]
                bar_open = float(curr_candle.get("open", curr_candle["close"]))
                bar_high = float(curr_candle.get("high", curr_candle["close"]))
                bar_low = float(curr_candle.get("low", curr_candle["close"]))
                bar_close = float(curr_candle["close"])

                # ── Step A: Process pending signal from previous bar (NEXT_BAR_OPEN execution) ──
                pending = pending_orders.pop(sym, None)
                if pending is not None:
                    p_action = pending.get("action", "").upper()
                    
                    # Handle Pending CLOSE
                    if p_action in ("CLOSE", "EXIT") and sym in open_positions:
                        pos = open_positions[sym]
                        eff_exit_p, sp_drag, sl_drag = self._calc_effective_price(bar_open, side="SELL")
                        qty = float(pos["qty"])
                        entry_p = float(pos["entry_price"])
                        notional_entry = float(pos["invested_notional"])
                        notional_exit = qty * eff_exit_p
                        
                        gross_pnl = (eff_exit_p - entry_p) * qty
                        exit_fee = notional_exit * (self._fee_bps / 10_000.0)
                        entry_fee = float(pos["entry_fee"])
                        total_fee = entry_fee + exit_fee
                        net_pnl = gross_pnl - total_fee

                        hold_bars = curr_idx - int(pos["entry_idx"])
                        trade_record = {
                            "trade_id": f"trade-{uuid.uuid4().hex[:8]}",
                            "symbol": sym,
                            "direction": pos["direction"],
                            "entry_time": pos["entry_time"],
                            "exit_time": t_step,
                            "entry_price": round(entry_p, 4),
                            "exit_price": round(eff_exit_p, 4),
                            "qty": round(qty, 6),
                            "notional": round(notional_entry, 2),
                            "sizing_weight": float(pos.get("sizing_weight", 1.0)),
                            "gross_pnl": round(gross_pnl, 4),
                            "entry_fee": round(entry_fee, 4),
                            "exit_fee": round(exit_fee, 4),
                            "fee_usd": round(total_fee, 4),
                            "slippage_usd": round((sl_drag + pos["entry_slip_drag"]) * qty, 4),
                            "spread_usd": round((sp_drag + pos["entry_spread_drag"]) * qty, 4),
                            "funding_usd": 0.0,
                            "net_pnl": round(net_pnl, 4),
                            "hold_bars": hold_bars,
                            "reason": pending.get("reason", "signal_close_next_bar_open"),
                        }
                        trade_log.append(trade_record)
                        # Cash returned: cash += notional_entry + gross_pnl - exit_fee (perfect reconciliation)
                        current_cash += (notional_exit - exit_fee)
                        del open_positions[sym]

                    # Handle Pending BUY (only if flat and capacity available)
                    elif p_action in ("BUY",) and sym not in open_positions:
                        if len(open_positions) < self.spec.max_open_positions:
                            fee_rate = self._fee_bps / 10_000.0
                            # Sizing constraint ensuring cash covers notional + fee
                            max_usable_cash = current_cash / (1.0 + fee_rate)
                            sizing_weight = float(pending.get("sizing_weight", 1.0))
                            base_notional = current_cash * self.spec.allocation_pct
                            target_notional = float(pending.get("target_notional") or (base_notional * sizing_weight))
                            target_notional = min(target_notional, max_usable_cash)

                            if target_notional >= 10.0:
                                eff_entry_p, sp_drag, sl_drag = self._calc_effective_price(bar_open, side="BUY")
                                qty = target_notional / eff_entry_p
                                entry_fee = target_notional * fee_rate
                                current_cash -= (target_notional + entry_fee)

                                open_positions[sym] = {
                                    "symbol": sym,
                                    "direction": "LONG",
                                    "entry_time": t_step,
                                    "entry_idx": curr_idx,
                                    "entry_price": eff_entry_p,
                                    "qty": qty,
                                    "invested_notional": target_notional,
                                    "sizing_weight": sizing_weight,
                                    "entry_fee": entry_fee,
                                    "entry_spread_drag": sp_drag,
                                    "entry_slip_drag": sl_drag,
                                    "stop_loss": pending.get("stop_loss"),
                                    "take_profit": pending.get("take_profit"),
                                    "current_price": bar_close,
                                }

                # ── Step B: Intrabar Stop Loss / Take Profit monitoring for held positions ──
                if sym in open_positions:
                    pos = open_positions[sym]
                    sl = pos.get("stop_loss")
                    tp = pos.get("take_profit")
                    exit_triggered = False
                    raw_exit_p = bar_close
                    exit_reason = ""

                    sl_hit = sl is not None and bar_low <= float(sl)
                    tp_hit = tp is not None and bar_high >= float(tp)

                    if sl_hit and tp_hit:
                        # Same candle policy
                        if self.spec.same_candle_policy == "CONSERVATIVE_SL_FIRST":
                            exit_triggered = True
                            exit_reason = "stop_loss_hit_conservative"
                            # Check gap on open
                            raw_exit_p = bar_open if bar_open <= float(sl) else float(sl)
                        else:
                            exit_triggered = True
                            exit_reason = "take_profit_hit"
                            raw_exit_p = bar_open if bar_open >= float(tp) else float(tp)
                    elif sl_hit:
                        exit_triggered = True
                        exit_reason = "stop_loss_hit"
                        raw_exit_p = bar_open if bar_open <= float(sl) else float(sl)
                    elif tp_hit:
                        exit_triggered = True
                        exit_reason = "take_profit_hit"
                        raw_exit_p = bar_open if bar_open >= float(tp) else float(tp)

                    if exit_triggered:
                        eff_exit_p, sp_drag, sl_drag = self._calc_effective_price(raw_exit_p, side="SELL")
                        qty = float(pos["qty"])
                        entry_p = float(pos["entry_price"])
                        notional_entry = float(pos["invested_notional"])
                        notional_exit = qty * eff_exit_p

                        gross_pnl = (eff_exit_p - entry_p) * qty
                        exit_fee = notional_exit * (self._fee_bps / 10_000.0)
                        entry_fee = float(pos["entry_fee"])
                        total_fee = entry_fee + exit_fee
                        net_pnl = gross_pnl - total_fee

                        hold_bars = curr_idx - int(pos["entry_idx"])
                        trade_record = {
                            "trade_id": f"trade-{uuid.uuid4().hex[:8]}",
                            "symbol": sym,
                            "direction": pos["direction"],
                            "entry_time": pos["entry_time"],
                            "exit_time": t_step,
                            "entry_price": round(entry_p, 4),
                            "exit_price": round(eff_exit_p, 4),
                            "qty": round(qty, 6),
                            "notional": round(notional_entry, 2),
                            "sizing_weight": float(pos.get("sizing_weight", 1.0)),
                            "gross_pnl": round(gross_pnl, 4),
                            "entry_fee": round(entry_fee, 4),
                            "exit_fee": round(exit_fee, 4),
                            "fee_usd": round(total_fee, 4),
                            "slippage_usd": round((sl_drag + pos["entry_slip_drag"]) * qty, 4),
                            "spread_usd": round((sp_drag + pos["entry_spread_drag"]) * qty, 4),
                            "funding_usd": 0.0,
                            "net_pnl": round(net_pnl, 4),
                            "hold_bars": hold_bars,
                            "reason": exit_reason,
                        }
                        trade_log.append(trade_record)
                        current_cash += (notional_exit - exit_fee)
                        del open_positions[sym]
                    else:
                        # Update current marked price
                        pos["current_price"] = bar_close

                # ── Step C: Strategy evaluation at bar close (Signal queued for Next-Bar-Open) ──
                historical_candles = sym_candles[:curr_idx + 1]
                pos = open_positions.get(sym)
                sig = strategy.evaluate_bar(
                    symbol=sym,
                    current_candle=curr_candle,
                    historical_candles=historical_candles,
                    current_position=pos,
                )
                if sig is not None:
                    pending_orders[sym] = sig

            # ── Step D: Mark-to-market equity curve snapshot at bar close ──
            unrealized_mtm = sum(float(p["qty"]) * float(p["current_price"]) for p in open_positions.values())
            total_equity = current_cash + unrealized_mtm
            equity_curve.append({
                "time": t_step,
                "equity": total_equity,
                "cash": current_cash,
                "open_positions": len(open_positions),
            })

        # ── Step E: Optional liquidation at end of window ──
        if self.liquidate_at_end and open_positions:
            for sym, pos in list(open_positions.items()):
                last_candle = candles_by_symbol.get(sym, [])[-1]
                last_price = float(last_candle["close"])
                eff_exit_p, sp_drag, sl_drag = self._calc_effective_price(last_price, side="SELL")
                qty = float(pos["qty"])
                entry_p = float(pos["entry_price"])
                notional_entry = float(pos["invested_notional"])
                notional_exit = qty * eff_exit_p

                gross_pnl = (eff_exit_p - entry_p) * qty
                exit_fee = notional_exit * (self._fee_bps / 10_000.0)
                entry_fee = float(pos["entry_fee"])
                total_fee = entry_fee + exit_fee
                net_pnl = gross_pnl - total_fee

                trade_log.append({
                    "trade_id": f"trade-eow-{uuid.uuid4().hex[:6]}",
                    "symbol": sym,
                    "direction": pos["direction"],
                    "entry_time": pos["entry_time"],
                    "exit_time": sorted_times[-1],
                    "entry_price": round(entry_p, 4),
                    "exit_price": round(eff_exit_p, 4),
                    "qty": round(qty, 6),
                    "notional": round(notional_entry, 2),
                    "sizing_weight": float(pos.get("sizing_weight", 1.0)),
                    "gross_pnl": round(gross_pnl, 4),
                    "entry_fee": round(entry_fee, 4),
                    "exit_fee": round(exit_fee, 4),
                    "fee_usd": round(total_fee, 4),
                    "slippage_usd": round((sl_drag + pos["entry_slip_drag"]) * qty, 4),
                    "spread_usd": round((sp_drag + pos["entry_spread_drag"]) * qty, 4),
                    "funding_usd": 0.0,
                    "net_pnl": round(net_pnl, 4),
                    "hold_bars": len(sorted_times) - int(pos["entry_idx"]),
                    "reason": "end_of_window_liquidation",
                })
                current_cash += (notional_exit - exit_fee)
                del open_positions[sym]

            # Update final point on equity curve
            if equity_curve:
                equity_curve[-1]["equity"] = current_cash
                equity_curve[-1]["cash"] = current_cash
                equity_curve[-1]["open_positions"] = 0

        final_mtm = sum(float(p["qty"]) * float(p["current_price"]) for p in open_positions.values())

        return ExperimentResult.from_trades_and_equity(
            spec=self.spec,
            trade_records=trade_log,
            equity_curve=equity_curve,
            open_positions=open_positions,
            final_cash=current_cash,
            final_mtm_value=final_mtm,
        )
