from typing import Dict, Any

class CostModel:
    """
    Calculates execution fees (maker/taker) and spread impact.
    """
    def __init__(self, fee_config: Dict[str, Any] = None):
        if fee_config is None:
            fee_config = {}
        self.spot_maker_bps = fee_config.get("spot_maker_bps", 10.0)
        self.spot_taker_bps = fee_config.get("spot_taker_bps", 10.0)
        self.futures_maker_bps = fee_config.get("futures_maker_bps", 2.0)
        self.futures_taker_bps = fee_config.get("futures_taker_bps", 5.0)
        self.is_futures = fee_config.get("is_futures", True)

    def calculate_fee(self, notional: float, is_taker: bool = True) -> float:
        """
        Calculates trade execution fee based on notional value.
        """
        if self.is_futures:
            bps = self.futures_taker_bps if is_taker else self.futures_maker_bps
        else:
            bps = self.spot_taker_bps if is_taker else self.spot_maker_bps
        
        return notional * (bps / 10000.0)

    def get_fill_price_with_spread(self, base_price: float, is_buy: bool, spread_bps: float) -> float:
        """
        Adjusts base price (e.g. close price) to account for bid-ask spread.
        If is_buy (LONG entry or SHORT exit), fill is at Ask (higher).
        If is_sell (SHORT entry or LONG exit), fill is at Bid (lower).
        
        Formula:
          Ask = mid * (1 + spread_bps / 20000)
          Bid = mid * (1 - spread_bps / 20000)
        """
        if spread_bps <= 0:
            return base_price
            
        multiplier = 1.0 + (spread_bps / 20000.0) if is_buy else 1.0 - (spread_bps / 20000.0)
        return base_price * multiplier
