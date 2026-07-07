from typing import Dict, Any

class SlippageModel:
    """
    Calculates dynamic price slippage based on volatility (ATR), spread, and order size.
    """
    def __init__(self, config: Dict[str, Any] = None):
        if config is None:
            config = {}
        self.enabled = config.get("enabled", True)
        self.base_slippage_bps = config.get("base_slippage_bps", 1.0)

    def calculate_slippage_bps(
        self,
        atr_pct: float = 0.0,
        order_size_pct_adv: float = 0.0,
        spread_bps: float = 0.0
    ) -> float:
        """
        Calculates slippage in basis points (bps) based on current market state.
        Formula:
          slippage_bps = base_slippage_bps + 0.2 * atr_pct + 0.5 * order_size_pct_adv + 0.3 * spread_bps
        """
        if not self.enabled:
            return 0.0
            
        slippage = self.base_slippage_bps
        slippage += 0.2 * (atr_pct * 100.0)  # assume atr_pct is e.g. 0.02 (2%), convert to %
        slippage += 0.5 * (order_size_pct_adv * 100.0) # assume order_size_pct_adv is fraction, convert to %
        slippage += 0.3 * spread_bps
        
        return max(0.0, slippage)

    def apply_slippage(self, price: float, is_buy: bool, slippage_bps: float) -> float:
        """
        Applies slippage to the fill price.
        If buying (LONG entry or SHORT exit), slippage increases the price.
        If selling (SHORT entry or LONG exit), slippage decreases the price.
        """
        if slippage_bps <= 0:
            return price
            
        multiplier = 1.0 + (slippage_bps / 10000.0) if is_buy else 1.0 - (slippage_bps / 10000.0)
        return price * multiplier
