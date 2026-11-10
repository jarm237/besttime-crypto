"""
btc_scraper/research/strategy_registry.py
Phase M4-A: Canonical Strategy Registry & Rule-Based Candidates.

Provides:
1. StrategySpec: Immutable specification of baseline and candidate strategies with deterministic config hash.
2. Standard candidate strategies:
   - AlwaysFlatStrategy (Benchmark)
   - PassiveBuyAndHoldStrategy (Benchmark)
   - SimpleMovingAverageCrossoverStrategy (Benchmark)
   - EmaTrendFollowingStrategy (Candidate)
   - RsiBollingerMeanReversionStrategy (Candidate)
   - SevenLayerProxyStrategy (Diagnostic Proxy Only)
3. StrategyRegistry: Central registry for instantiating and inspecting strategies.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from btc_scraper.research.baseline_runner import (
    AlwaysFlatStrategy,
    BaselineStrategy,
    PassiveBuyAndHoldStrategy,
    SevenLayerProxyStrategy,
    SimpleMovingAverageCrossoverStrategy,
)
from btc_scraper.research.experiment_contract import freeze_nested, unfreeze_nested


@dataclass(frozen=True)
class StrategySpec:
    """
    Immutable specification of a strategy.
    Contains metadata, hyperparameters, required features, and a deterministic configuration hash.
    """
    strategy_id: str
    strategy_name: str
    tier: str                      # "BENCHMARK", "CANDIDATE", "PROXY"
    status: str                    # "ACTIVE", "EXPERIMENTAL", "DIAGNOSTIC_ONLY"
    parameters: Mapping[str, Any] = field(default_factory=lambda: freeze_nested({}))
    required_features: Tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    config_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", freeze_nested(self.parameters))
        object.__setattr__(self, "required_features", tuple(self.required_features))

        computed_hash = self.compute_config_hash()
        if self.config_hash and self.config_hash != computed_hash:
            raise ValueError(
                f"config_hash mismatch: expected {computed_hash}, got {self.config_hash}"
            )
        object.__setattr__(self, "config_hash", computed_hash)

    def compute_config_hash(self) -> str:
        """Computes deterministic SHA-256 of all configuration parameters."""
        clean = {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "tier": self.tier,
            "status": self.status,
            "parameters": unfreeze_nested(self.parameters),
            "required_features": sorted(list(self.required_features)),
        }
        raw_json = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "tier": self.tier,
            "status": self.status,
            "parameters": unfreeze_nested(self.parameters),
            "required_features": list(self.required_features),
            "description": self.description,
            "config_hash": self.config_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "StrategySpec":
        return cls(
            strategy_id=str(data["strategy_id"]),
            strategy_name=str(data["strategy_name"]),
            tier=str(data["tier"]),
            status=str(data["status"]),
            parameters=data.get("parameters", {}),
            required_features=tuple(data.get("required_features", ())),
            description=str(data.get("description", "")),
            config_hash=str(data.get("config_hash", "")),
        )


# ── Candidate 1: Exponential Moving Average Trend Following ───────────────────

class EmaTrendFollowingStrategy(BaselineStrategy):
    """
    Candidate trend-following strategy using fast (12) and slow (26) Exponential Moving Averages.
    Enters Long on bullish EMA crossover.
    Exits on bearish EMA crossover or intrabar stop loss.
    """
    TIER = "CANDIDATE"
    STATUS = "ACTIVE"

    def __init__(self, fast_period: int = 12, slow_period: int = 26, name: str = "ema_trend_following"):
        super().__init__(name)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.alpha_fast = 2.0 / (fast_period + 1.0)
        self.alpha_slow = 2.0 / (slow_period + 1.0)
        self._ema_fast: Dict[str, float] = {}
        self._ema_slow: Dict[str, float] = {}
        self._prev_fast: Dict[str, float] = {}
        self._prev_slow: Dict[str, float] = {}

    def reset(self) -> None:
        self._ema_fast.clear()
        self._ema_slow.clear()
        self._prev_fast.clear()
        self._prev_slow.clear()

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        c = float(current_candle["close"])

        if symbol not in self._ema_fast:
            self._ema_fast[symbol] = c
            self._ema_slow[symbol] = c
            self._prev_fast[symbol] = c
            self._prev_slow[symbol] = c
            return None

        self._prev_fast[symbol] = self._ema_fast[symbol]
        self._prev_slow[symbol] = self._ema_slow[symbol]

        self._ema_fast[symbol] = self.alpha_fast * c + (1.0 - self.alpha_fast) * self._prev_fast[symbol]
        self._ema_slow[symbol] = self.alpha_slow * c + (1.0 - self.alpha_slow) * self._prev_slow[symbol]

        if len(historical_candles) < self.slow_period + 2:
            return None

        prev_fast = self._prev_fast[symbol]
        prev_slow = self._prev_slow[symbol]
        curr_fast = self._ema_fast[symbol]
        curr_slow = self._ema_slow[symbol]

        # Bullish crossover
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            if current_position is None:
                return {
                    "action": "BUY",
                    "reason": "ema_golden_cross",
                }

        # Bearish crossover
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            if current_position is not None:
                return {
                    "action": "CLOSE",
                    "reason": "ema_death_cross",
                }

        return None


# ── Candidate 2: RSI & Bollinger Bands Mean Reversion ─────────────────────────

class RsiBollingerMeanReversionStrategy(BaselineStrategy):
    """
    Candidate mean-reversion strategy:
    Enters Long when price drops below lower Bollinger Band AND RSI is oversold (< 30).
    Exits when price reverts to middle band (SMA 20) or RSI crosses above 50.
    """
    TIER = "CANDIDATE"
    STATUS = "ACTIVE"

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_exit: float = 50.0,
        bb_period: int = 20,
        bb_std: float = 2.0,
        name: str = "rsi_bollinger_mean_reversion",
    ):
        super().__init__(name)
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_exit = rsi_exit
        self.bb_period = bb_period
        self.bb_std = bb_std

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        min_bars = max(self.bb_period, self.rsi_period) + 5
        if len(historical_candles) < min_bars:
            return None

        # Slicing only the needed trailing window ensures O(1) step execution
        needed = max(self.bb_period, self.rsi_period + 1)
        tail_slice = historical_candles[-needed:]
        closes = [float(c["close"]) for c in tail_slice]
        current_price = closes[-1]

        # Bollinger Bands calculation
        bb_slice = closes[-self.bb_period:]
        sma = sum(bb_slice) / self.bb_period
        variance = sum((x - sma) ** 2 for x in bb_slice) / self.bb_period
        std = variance ** 0.5
        lower_band = sma - self.bb_std * std

        # RSI calculation over the trailing slice
        gains = []
        losses = []
        for i in range(-self.rsi_period, 0):
            diff = closes[i] - closes[i - 1]
            if diff >= 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(-diff)

        avg_gain = sum(gains) / len(gains) if gains else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        if avg_loss < 1e-12:
            rsi = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # Mean-reversion Entry: oversold + price breached lower band
        if current_position is None:
            if current_price < lower_band and rsi < self.rsi_oversold:
                return {
                    "action": "BUY",
                    "reason": f"rsi_bb_oversold (rsi={rsi:.1f}, close={current_price:.2f} < bb={lower_band:.2f})",
                }

        # Mean-reversion Exit: price reverted back to middle SMA or RSI reached neutral
        elif current_position is not None:
            if current_price >= sma or rsi >= self.rsi_exit:
                return {
                    "action": "CLOSE",
                    "reason": f"rsi_bb_mean_reverted (close={current_price:.2f} >= sma={sma:.2f})",
                }

        return None


# ── Candidate 3: Regime-Aware Trend Following (Successor 1) ───────────────────

class RegimeAwareTrendStrategy(BaselineStrategy):
    """
    Successor Candidate 1 (M4.1): Regime-Aware Trend Following.
    Hypothesis: Adding a macro-trend filter (SMA 50) and an ATR-based protective
    stop to fast/slow EMA crossovers eliminates whipsaws during ranging/reversal regimes.
    """
    TIER = "CANDIDATE"
    STATUS = "ACTIVE"

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        macro_period: int = 50,
        atr_period: int = 14,
        atr_stop_multiplier: float = 2.0,
        name: str = "regime_aware_trend",
    ):
        super().__init__(name)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.macro_period = macro_period
        self.atr_period = atr_period
        self.atr_stop_multiplier = atr_stop_multiplier
        self.alpha_fast = 2.0 / (fast_period + 1.0)
        self.alpha_slow = 2.0 / (slow_period + 1.0)
        self._ema_fast: Dict[str, float] = {}
        self._ema_slow: Dict[str, float] = {}
        self._prev_fast: Dict[str, float] = {}
        self._prev_slow: Dict[str, float] = {}

    def reset(self) -> None:
        self._ema_fast.clear()
        self._ema_slow.clear()
        self._prev_fast.clear()
        self._prev_slow.clear()

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        c = float(current_candle["close"])

        if symbol not in self._ema_fast:
            self._ema_fast[symbol] = c
            self._ema_slow[symbol] = c
            self._prev_fast[symbol] = c
            self._prev_slow[symbol] = c
            return None

        self._prev_fast[symbol] = self._ema_fast[symbol]
        self._prev_slow[symbol] = self._ema_slow[symbol]

        self._ema_fast[symbol] = self.alpha_fast * c + (1.0 - self.alpha_fast) * self._prev_fast[symbol]
        self._ema_slow[symbol] = self.alpha_slow * c + (1.0 - self.alpha_slow) * self._prev_slow[symbol]

        needed = max(self.macro_period, self.atr_period + 1, self.slow_period + 2)
        if len(historical_candles) < needed:
            return None

        prev_fast = self._prev_fast[symbol]
        prev_slow = self._prev_slow[symbol]
        curr_fast = self._ema_fast[symbol]
        curr_slow = self._ema_slow[symbol]

        tail_macro = historical_candles[-self.macro_period:]
        sma_macro = sum(float(x["close"]) for x in tail_macro) / self.macro_period

        # ATR calculation
        tail_atr = historical_candles[-(self.atr_period + 1):]
        trs = []
        for i in range(1, len(tail_atr)):
            h = float(tail_atr[i]["high"])
            l = float(tail_atr[i]["low"])
            pc = float(tail_atr[i - 1]["close"])
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs) / len(trs) if trs else 0.0

        # Bullish crossover with macro trend confirmation
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            if current_position is None and c > sma_macro:
                return {
                    "action": "BUY",
                    "reason": f"regime_golden_cross (c={c:.2f} > sma50={sma_macro:.2f})",
                }

        # Exit conditions: bearish crossover OR trailing stop
        elif current_position is not None:
            # Bearish crossover
            if prev_fast >= prev_slow and curr_fast < curr_slow:
                return {
                    "action": "CLOSE",
                    "reason": "regime_death_cross",
                }
            # ATR protective stop
            entry_p = float(current_position.get("entry_price", c))
            stop_price = entry_p - self.atr_stop_multiplier * atr
            if c < stop_price:
                return {
                    "action": "CLOSE",
                    "reason": f"regime_atr_stop (c={c:.2f} < stop={stop_price:.2f})",
                }

        return None


# ── Candidate 4: Volatility-Aware Mean Reversion (Successor 2) ─────────────────

class VolAwareMeanReversionStrategy(BaselineStrategy):
    """
    Successor Candidate 2 (M4.1): Volatility-Aware Mean Reversion.
    Hypothesis: Coupling RSI/Bollinger oversold entry with an ATR-based stop loss and
    a macro-regime trend filter prevents catching falling knives during downward momentum breaks.
    """
    TIER = "CANDIDATE"
    STATUS = "ACTIVE"

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_exit: float = 50.0,
        bb_period: int = 20,
        bb_std: float = 2.0,
        macro_period: int = 50,
        atr_period: int = 14,
        atr_stop_multiplier: float = 1.5,
        name: str = "vol_aware_mean_reversion",
    ):
        super().__init__(name)
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_exit = rsi_exit
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.macro_period = macro_period
        self.atr_period = atr_period
        self.atr_stop_multiplier = atr_stop_multiplier

    def evaluate_bar(
        self,
        symbol: str,
        current_candle: Mapping[str, Any],
        historical_candles: Sequence[Mapping[str, Any]],
        current_position: Optional[Mapping[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        needed = max(self.macro_period, self.bb_period, self.rsi_period + 1, self.atr_period + 1) + 2
        if len(historical_candles) < needed:
            return None

        closes = [float(c["close"]) for c in historical_candles[-needed:]]
        current_price = closes[-1]

        # Macro trend check (don't buy when cascading downwards far below macro SMA)
        macro_closes = closes[-self.macro_period:]
        sma_macro = sum(macro_closes) / self.macro_period

        # ATR calculation
        tail_atr = historical_candles[-(self.atr_period + 1):]
        trs = []
        for i in range(1, len(tail_atr)):
            h = float(tail_atr[i]["high"])
            l = float(tail_atr[i]["low"])
            pc = float(tail_atr[i - 1]["close"])
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs) / len(trs) if trs else 0.0

        # Bollinger Bands
        bb_slice = closes[-self.bb_period:]
        sma_bb = sum(bb_slice) / self.bb_period
        variance = sum((x - sma_bb) ** 2 for x in bb_slice) / self.bb_period
        std = variance ** 0.5
        lower_band = sma_bb - self.bb_std * std

        # RSI calculation
        gains = []
        losses = []
        for i in range(-self.rsi_period, 0):
            diff = closes[i] - closes[i - 1]
            if diff >= 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(-diff)

        avg_gain = sum(gains) / len(gains) if gains else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        if avg_loss < 1e-12:
            rsi = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # Entry: oversold + lower band breach + macro trend condition (price >= sma_macro - 2 * atr)
        if current_position is None:
            if current_price < lower_band and rsi < self.rsi_oversold:
                if current_price >= (sma_macro - 2.0 * atr):
                    return {
                        "action": "BUY",
                        "reason": f"vol_mr_oversold (rsi={rsi:.1f}, close={current_price:.2f} < bb={lower_band:.2f})",
                    }

        # Exit: take profit at middle band / rsi neutral, OR cut loss at ATR stop
        elif current_position is not None:
            entry_p = float(current_position.get("entry_price", current_price))
            stop_price = entry_p - self.atr_stop_multiplier * atr
            if current_price < stop_price:
                return {
                    "action": "CLOSE",
                    "reason": f"vol_mr_atr_stop (close={current_price:.2f} < stop={stop_price:.2f})",
                }
            if current_price >= sma_bb or rsi >= self.rsi_exit:
                return {
                    "action": "CLOSE",
                    "reason": f"vol_mr_mean_reverted (close={current_price:.2f} >= sma={sma_bb:.2f})",
                }

        return None


# ── Central Strategy Registry ─────────────────────────────────────────────────

class StrategyRegistry:
    """
    Registry for strategy specifications and factory constructors.
    Ensures that every strategy is deterministically tracked by version and config hash.
    """
    def __init__(self):
        self._specs: Dict[str, StrategySpec] = {}
        self._factories: Dict[str, Callable[[], BaselineStrategy]] = {}
        self._register_default_strategies()

    def register(
        self,
        spec: StrategySpec,
        factory: Callable[[], BaselineStrategy],
    ) -> None:
        self._specs[spec.strategy_id] = spec
        self._factories[spec.strategy_id] = factory

    def get_spec(self, strategy_id: str) -> StrategySpec:
        if strategy_id not in self._specs:
            raise KeyError(f"Unknown strategy_id: '{strategy_id}'. Available: {list(self._specs.keys())}")
        return self._specs[strategy_id]

    def create(self, strategy_id: str) -> BaselineStrategy:
        if strategy_id not in self._factories:
            raise KeyError(f"Unknown strategy_id: '{strategy_id}'. Available: {list(self._factories.keys())}")
        return self._factories[strategy_id]()

    def list_strategies(self) -> List[StrategySpec]:
        return [self._specs[k] for k in sorted(self._specs.keys())]

    def _register_default_strategies(self) -> None:
        # 1. Always Flat
        spec_flat = StrategySpec(
            strategy_id="always_flat_v1",
            strategy_name="Always Flat Anchor",
            tier="BENCHMARK",
            status="ACTIVE",
            parameters={},
            description="No-trade control anchor: 0 trades, 0 fees, zero market exposure",
        )
        self.register(spec_flat, lambda: AlwaysFlatStrategy())

        # 2. Buy & Hold
        spec_bnh = StrategySpec(
            strategy_id="buy_and_hold_v1",
            strategy_name="Passive Buy and Hold",
            tier="BENCHMARK",
            status="ACTIVE",
            parameters={},
            description="Passive market exposure benchmark: buy at inception and hold",
        )
        self.register(spec_bnh, lambda: PassiveBuyAndHoldStrategy())

        # 3. SMA Crossover (9 / 21)
        spec_sma = StrategySpec(
            strategy_id="sma_crossover_9_21_v1",
            strategy_name="SMA Crossover (9, 21)",
            tier="BENCHMARK",
            status="ACTIVE",
            parameters={"fast_period": 9, "slow_period": 21},
            description="Standard moving average crossover trend-following benchmark",
        )
        self.register(spec_sma, lambda: SimpleMovingAverageCrossoverStrategy(fast_period=9, slow_period=21))

        # 4. EMA Trend Following (12 / 26)
        spec_ema = StrategySpec(
            strategy_id="ema_trend_12_26_v1",
            strategy_name="EMA Trend Following (12, 26)",
            tier="CANDIDATE",
            status="ACTIVE",
            parameters={"fast_period": 12, "slow_period": 26},
            description="Exponential moving average trend following candidate",
        )
        self.register(spec_ema, lambda: EmaTrendFollowingStrategy(fast_period=12, slow_period=26))

        # 5. RSI Bollinger Mean Reversion
        spec_rsi_bb = StrategySpec(
            strategy_id="rsi_bollinger_mr_v1",
            strategy_name="RSI & Bollinger Mean Reversion",
            tier="CANDIDATE",
            status="ACTIVE",
            parameters={
                "rsi_period": 14,
                "rsi_oversold": 30.0,
                "rsi_exit": 50.0,
                "bb_period": 20,
                "bb_std": 2.0,
            },
            description="Mean reversion candidate buying oversold lower-band breaches",
        )
        self.register(
            spec_rsi_bb,
            lambda: RsiBollingerMeanReversionStrategy(
                rsi_period=14, rsi_oversold=30.0, rsi_exit=50.0, bb_period=20, bb_std=2.0
            ),
        )

        # 6. Seven Layer Proxy (Diagnostic Only)
        spec_proxy = StrategySpec(
            strategy_id="seven_layer_proxy_v1",
            strategy_name="Seven-Layer Proxy Baseline",
            tier="PROXY",
            status="DIAGNOSTIC_ONLY",
            parameters={"r_multiple": 2.0},
            description="Heuristic multi-layer trend-pullback proxy; DIAGNOSTIC ONLY, NOT PRODUCTION EQUIVALENT",
        )
        self.register(spec_proxy, lambda: SevenLayerProxyStrategy(r_multiple=2.0))

        # 7. Regime-Aware Trend Following (Successor 1)
        spec_regime_trend = StrategySpec(
            strategy_id="regime_aware_trend_v1",
            strategy_name="Regime-Aware Trend Following",
            tier="CANDIDATE",
            status="ACTIVE",
            parameters={
                "fast_period": 12,
                "slow_period": 26,
                "macro_period": 50,
                "atr_period": 14,
                "atr_stop_multiplier": 2.0,
            },
            description="EMA trend following candidate filtered by SMA50 regime and ATR protective stop",
        )
        self.register(
            spec_regime_trend,
            lambda: RegimeAwareTrendStrategy(
                fast_period=12,
                slow_period=26,
                macro_period=50,
                atr_period=14,
                atr_stop_multiplier=2.0,
            ),
        )

        # 8. Volatility-Aware Mean Reversion (Successor 2)
        spec_vol_mr = StrategySpec(
            strategy_id="vol_aware_mean_reversion_v1",
            strategy_name="Volatility-Aware Mean Reversion",
            tier="CANDIDATE",
            status="ACTIVE",
            parameters={
                "rsi_period": 14,
                "rsi_oversold": 30.0,
                "rsi_exit": 50.0,
                "bb_period": 20,
                "bb_std": 2.0,
                "macro_period": 50,
                "atr_period": 14,
                "atr_stop_multiplier": 1.5,
            },
            description="RSI & Bollinger mean reversion candidate with macro trend filter and ATR stop",
        )
        self.register(
            spec_vol_mr,
            lambda: VolAwareMeanReversionStrategy(
                rsi_period=14,
                rsi_oversold=30.0,
                rsi_exit=50.0,
                bb_period=20,
                bb_std=2.0,
                macro_period=50,
                atr_period=14,
                atr_stop_multiplier=1.5,
            ),
        )


# Global default registry instance
GLOBAL_STRATEGY_REGISTRY = StrategyRegistry()
