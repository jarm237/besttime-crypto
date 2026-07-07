from typing import Dict, Any, List
import pandas as pd
from datetime import datetime, timedelta

class LatencyModel:
    """
    Simulates execution time delays and price degradation due to API and network latency.
    """
    def __init__(self, config: Dict[str, Any] = None):
        if config is None:
            config = {}
        self.enabled = config.get("enabled", True)
        self.latency_ms = config.get("latency_ms", 250)

    def compute_delayed_execution(
        self,
        candles: List[Dict[str, Any]],
        current_idx: int,
        is_buy: bool,
        timeframe_min: int = 15
    ) -> Dict[str, Any]:
        """
        Computes the delayed fill index, timestamp, and adjusted base price.
        Normally, a signal at the close of candle[current_idx] is executed at candle[current_idx+1] Open.
        If latency is enabled:
          - We calculate delay_bars = latency_ms / (timeframe_min * 60 * 1000).
          - If delay_bars >= 1, execution index increases by int(delay_bars).
          - We apply a slippage-like penalty based on the high-low range of the execution candle
            to model intra-bar price degradation.
            Penalty = (high - low) * (latency_ms_remainder / bar_duration_ms)
        """
        if not self.enabled or self.latency_ms <= 0:
            fill_idx = min(current_idx + 1, len(candles) - 1)
            target_candle = candles[fill_idx]
            return {
                "fill_index": fill_idx,
                "fill_time": target_candle["time"],
                "base_price": target_candle["open"],
                "latency_penalty_bps": 0.0
            }

        bar_duration_ms = timeframe_min * 60 * 1000
        delay_bars = self.latency_ms // bar_duration_ms
        remainder_ms = self.latency_ms % bar_duration_ms
        
        fill_idx = current_idx + 1 + int(delay_bars)
        if fill_idx >= len(candles):
            fill_idx = len(candles) - 1
            
        target_candle = candles[fill_idx]
        open_price = target_candle["open"]
        high_price = target_candle["high"]
        low_price = target_candle["low"]
        
        # Intra-bar degradation: if we are delayed by remainder_ms, price moves against us
        # Maximum penalty is half the candle's high-low range
        range_pct = (high_price - low_price) / open_price if open_price > 0 else 0.0
        ratio = remainder_ms / bar_duration_ms
        penalty_bps = range_pct * ratio * 0.5 * 10000.0
        
        # Adjust base price
        if is_buy:
            # Buying: price increases
            base_price = open_price * (1.0 + (penalty_bps / 10000.0))
            # Keep it capped at high
            base_price = min(base_price, high_price)
        else:
            # Selling: price decreases
            base_price = open_price * (1.0 - (penalty_bps / 10000.0))
            # Keep it floored at low
            base_price = max(base_price, low_price)
            
        return {
            "fill_index": fill_idx,
            "fill_time": target_candle["time"],
            "base_price": base_price,
            "latency_penalty_bps": penalty_bps
        }
