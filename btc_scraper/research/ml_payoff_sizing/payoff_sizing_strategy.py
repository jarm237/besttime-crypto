"""
btc_scraper/research/ml_payoff_sizing/payoff_sizing_strategy.py

Payoff-Sized EMA Trend Strategy for M4-ML2.
Scales position sizes based on continuous predicted net payoff (bps)
using strictly risk-reducing [0.25, 1.00] or asymmetric [0.25, 1.75] policies.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence
import numpy as np

from btc_scraper.research.baseline_runner import BaselineStrategy
from btc_scraper.research.ml_payoff_sizing.risk_constrained_sizing import (
    compute_asymmetric_expansion_weight,
    compute_risk_reducing_weight,
)
from btc_scraper.research.ml_trade_quality.feature_contract import (
    FEATURE_NAMES,
    extract_features_at_bar,
)


class PayoffSizedEmaTrendStrategy(BaselineStrategy):
    """
    EMA Trend Following (12, 26) with continuous ML payoff-based position sizing.
    Takes 100% of crossover signals (no hard trade filtering), adjusting notional weight.
    """
    TIER = "CANDIDATE"
    STATUS = "ACTIVE"

    def __init__(
        self,
        model_pack: Optional[Dict[str, Any]] = None,
        model_type: str = "huber",
        sizing_policy: str = "risk_reducing",
        fast_period: int = 12,
        slow_period: int = 26,
        name: Optional[str] = None,
    ):
        strat_name = name or f"ema_trend_ml2_{model_type}_{sizing_policy}"
        super().__init__(strat_name)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.alpha_fast = 2.0 / (fast_period + 1.0)
        self.alpha_slow = 2.0 / (slow_period + 1.0)
        self.model_pack = model_pack
        self.model_type = model_type
        self.sizing_policy = sizing_policy

        self._ema_fast: Dict[str, float] = {}
        self._ema_slow: Dict[str, float] = {}
        self._prev_fast: Dict[str, float] = {}
        self._prev_slow: Dict[str, float] = {}

    def reset(self) -> None:
        self._ema_fast.clear()
        self._ema_slow.clear()
        self._prev_fast.clear()
        self._prev_slow.clear()

    def set_model(self, model_pack: Dict[str, Any], model_type: str = "huber") -> None:
        """Injects fold-specific trained model, scaler, and training quantiles."""
        self.model_pack = model_pack
        self.model_type = model_type

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

        # Bullish Golden Cross
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            if current_position is None:
                sizing_weight = 1.0
                pred_bps = 0.0

                if self.model_pack is not None:
                    try:
                        curr_idx = len(historical_candles) - 1
                        feats = extract_features_at_bar(
                            symbol_candles=historical_candles,
                            bar_idx=curr_idx,
                            btc_candles=None,
                        )
                        feat_vec = np.array([[feats[f] for f in FEATURE_NAMES]])
                        scaler = self.model_pack["scaler"]
                        regressor = self.model_pack[self.model_type]
                        feat_scaled = scaler.transform(feat_vec)
                        pred_bps = float(regressor.predict(feat_scaled)[0])

                        quantiles = self.model_pack.get("train_quantiles", {})
                        if self.sizing_policy == "risk_reducing":
                            sizing_weight = compute_risk_reducing_weight(pred_bps, quantiles)
                        else:
                            sizing_weight = compute_asymmetric_expansion_weight(pred_bps, quantiles)
                    except Exception:
                        sizing_weight = 1.0

                return {
                    "action": "BUY",
                    "reason": f"ema_cross_ml2_{self.model_type}_{self.sizing_policy}",
                    "sizing_weight": sizing_weight,
                    "pred_payoff_bps": pred_bps,
                }

        # Bearish Death Cross
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            if current_position is not None:
                return {
                    "action": "CLOSE",
                    "reason": "ema_death_cross",
                }

        return None
