"""
btc_scraper/research/ml_trade_quality/ml_filtered_strategy.py

Strategy implementation combining base_ema_trend with the trained
M4-ML1 Trade Quality Filter for backtesting in ExperimentRunner.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence
import numpy as np
from btc_scraper.research.baseline_runner import BaselineStrategy
from btc_scraper.research.ml_trade_quality.feature_contract import (
    FEATURE_NAMES,
    extract_features_at_bar,
)


class MlFilteredEmaTrendStrategy(BaselineStrategy):
    """
    EMA Trend Following (12, 26) with an inline ML Trade Quality Filter.
    Evaluates probability of net positive return and filters out low-conviction crossovers.
    """
    TIER = "CANDIDATE"
    STATUS = "ACTIVE"

    def __init__(
        self,
        model_dict: Optional[Dict[str, Any]] = None,
        threshold: float = 0.30,
        fast_period: int = 12,
        slow_period: int = 26,
        name: str = "ema_trend_ml1_filtered",
    ):
        super().__init__(name)
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.alpha_fast = 2.0 / (fast_period + 1.0)
        self.alpha_slow = 2.0 / (slow_period + 1.0)
        self.model_dict = model_dict
        self.threshold = threshold

        self._ema_fast: Dict[str, float] = {}
        self._ema_slow: Dict[str, float] = {}
        self._prev_fast: Dict[str, float] = {}
        self._prev_slow: Dict[str, float] = {}

    def reset(self) -> None:
        self._ema_fast.clear()
        self._ema_slow.clear()
        self._prev_fast.clear()
        self._prev_slow.clear()

    def set_model(self, model_dict: Dict[str, Any], threshold: float) -> None:
        """Dynamically injects fold-specific trained model and frozen threshold."""
        self.model_dict = model_dict
        self.threshold = threshold

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

        # Bullish crossover: Golden Cross
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            if current_position is None:
                # If ML model is provided, evaluate trade quality filter
                if self.model_dict is not None and "model" in self.model_dict:
                    try:
                        curr_idx = len(historical_candles) - 1
                        feats = extract_features_at_bar(
                            symbol_candles=historical_candles,
                            bar_idx=curr_idx,
                            btc_candles=None,
                        )
                        feat_vec = np.array([[feats[f] for f in FEATURE_NAMES]])
                        scaler = self.model_dict["scaler"]
                        model = self.model_dict["model"]
                        feat_scaled = scaler.transform(feat_vec)
                        prob_win = float(model.predict_proba(feat_scaled)[0, 1])

                        if prob_win < self.threshold:
                            # Filtered out by ML quality model
                            return None
                    except Exception:
                        # Fallback if insufficient history for features (<48 bars)
                        return None

                return {
                    "action": "BUY",
                    "reason": "ema_golden_cross_ml_approved",
                }

        # Bearish crossover: Death Cross
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            if current_position is not None:
                return {
                    "action": "CLOSE",
                    "reason": "ema_death_cross",
                }

        return None
