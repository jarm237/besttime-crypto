"""
World State Manager - Centralized state representation of the market.

Maintains unified world state across all modules:
- Macro layer (economic indicators)
- Liquidity layer (funding, OI)
- Crypto layer (BTC, ETH, etc)
- Sentiment layer (fear index, social)
- Risk layer (drawdown, volatility)

All modules read from WorldState instead of each fetching from Feature Store independently.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, Any, Optional
import json
import threading
from enum import Enum


class MarketRegime(Enum):
    """Market regime classification."""
    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    TRANSITIONING = "transitioning"
    UNKNOWN = "unknown"


class LiquidityRegime(Enum):
    """Liquidity conditions."""
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    EXTREME = "extreme"


@dataclass
class MacroLayer:
    """Macro economic indicators."""
    DXY: float = 0.0  # US Dollar Index
    FedRate: float = 0.0  # Federal Funds Rate
    RealYield: float = 0.0  # 10Y Real Yield
    BondYield: float = 0.0  # 10Y Treasury Yield
    VIX: float = 20.0  # Volatility Index
    CPI: Optional[float] = None  # Latest CPI if available
    NFP: Optional[float] = None  # Non-farm payroll if available
    updated_at: Optional[datetime] = None


@dataclass
class LiquidityLayer:
    """Funding and order flow metrics."""
    BTC_Funding: float = 0.0  # Funding rate
    ETH_Funding: float = 0.0
    BTC_OI: float = 0.0  # Open Interest
    ETH_OI: float = 0.0
    BTC_LongShortRatio: float = 1.0
    ETH_LongShortRatio: float = 1.0
    Funding_Z: float = 0.0  # Zscore of funding
    OI_Delta: float = 0.0  # Change in OI
    updated_at: Optional[datetime] = None


@dataclass
class CryptoLayer:
    """Crypto market data."""
    BTC_Price: float = 0.0
    BTC_Volume: float = 0.0
    ETH_Price: float = 0.0
    ETH_Volume: float = 0.0
    BTC_24h_Change: float = 0.0  # Percentage
    ETH_24h_Change: float = 0.0
    Altcoin_Dominance: float = 0.0  # Alt cap / Total cap
    updated_at: Optional[datetime] = None


@dataclass
class SentimentLayer:
    """Market sentiment indicators."""
    FearGreed: float = 50.0  # Fear & Greed Index (0-100)
    SocialVolume: float = 0.0  # Social media mentions
    LongTermHolders: float = 0.0  # LTH percentage
    NewAddresses: float = 0.0
    updated_at: Optional[datetime] = None


@dataclass
class RiskLayer:
    """Risk metrics."""
    CurrentDrawdown: float = 0.0  # Current DD from peak
    MaxDrawdown: float = 0.0  # Max DD in period
    Volatility: float = 0.0  # Realized volatility
    VaR95: float = 0.0  # Value at Risk 95%
    Sharpe: float = 0.0  # Sharpe ratio
    updated_at: Optional[datetime] = None


@dataclass
class AlternativeLayer:
    """Alternative data features that enrich the market state."""
    exchange_netflow: float = 0.0
    whale_score: float = 0.0
    stablecoin_supply: float = 0.0
    stablecoin_supply_total: float = 0.0
    etf_flow: float = 0.0
    chain_tvl: float = 0.0
    defi_liquidity_score: float = 0.0
    orderbook_imbalance: float = 0.0
    funding_pressure: float = 0.0
    open_interest_pressure: float = 0.0
    large_tx_proxy_score: float = 0.0
    options_iv: float = 0.0
    options_iv_rank: float = 0.0
    options_skew: float = 0.0
    macro_pressure: float = 0.0
    macro_risk_score: float = 0.0
    stablecoin_momentum: float = 0.0
    etf_momentum: float = 0.0
    risk_on_score: float = 0.0
    updated_at: Optional[datetime] = None


@dataclass
class WorldState:
    """
    Unified market state snapshot.
    
    All modules read from this instead of independently querying Feature Store.
    Created at each analysis cycle and passed through decision flow.
    """
    timestamp: datetime
    regime: MarketRegime = MarketRegime.UNKNOWN
    liquidity_regime: LiquidityRegime = LiquidityRegime.NORMAL
    
    macro: MacroLayer = field(default_factory=MacroLayer)
    liquidity: LiquidityLayer = field(default_factory=LiquidityLayer)
    crypto: CryptoLayer = field(default_factory=CryptoLayer)
    sentiment: SentimentLayer = field(default_factory=SentimentLayer)
    risk: RiskLayer = field(default_factory=RiskLayer)
    alternative: AlternativeLayer = field(default_factory=AlternativeLayer)
    
    # Metadata
    is_snapshot: bool = False  # Whether loaded from snapshot
    snapshot_id: Optional[str] = None
    source: str = "realtime"  # "realtime", "snapshot", "replay"
    
    # Custom fields
    custom_indicators: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (for serialization)."""
        result = {
            "timestamp": self.timestamp.isoformat(),
            "regime": self.regime.value,
            "liquidity_regime": self.liquidity_regime.value,
            "macro": asdict(self.macro),
            "liquidity": asdict(self.liquidity),
            "crypto": asdict(self.crypto),
            "sentiment": asdict(self.sentiment),
            "risk": asdict(self.risk),
            "alternative": asdict(self.alternative),
            "is_snapshot": self.is_snapshot,
            "snapshot_id": self.snapshot_id,
            "source": self.source,
            "custom_indicators": self.custom_indicators,
        }
        # Convert datetime fields to ISO format
        for layer_name in ["macro", "liquidity", "crypto", "sentiment", "risk", "alternative"]:
            if result[layer_name]["updated_at"]:
                result[layer_name]["updated_at"] = result[layer_name]["updated_at"].isoformat()
        
        return result
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'WorldState':
        """Create WorldState from dictionary."""
        timestamp = datetime.fromisoformat(data["timestamp"])
        
        # Parse layers
        macro = MacroLayer(**{
            k: v for k, v in data.get("macro", {}).items()
            if k != "updated_at"
        })
        if data.get("macro", {}).get("updated_at"):
            macro.updated_at = datetime.fromisoformat(data["macro"]["updated_at"])
        
        liquidity = LiquidityLayer(**{
            k: v for k, v in data.get("liquidity", {}).items()
            if k != "updated_at"
        })
        if data.get("liquidity", {}).get("updated_at"):
            liquidity.updated_at = datetime.fromisoformat(data["liquidity"]["updated_at"])
        
        crypto = CryptoLayer(**{
            k: v for k, v in data.get("crypto", {}).items()
            if k != "updated_at"
        })
        if data.get("crypto", {}).get("updated_at"):
            crypto.updated_at = datetime.fromisoformat(data["crypto"]["updated_at"])
        
        sentiment = SentimentLayer(**{
            k: v for k, v in data.get("sentiment", {}).items()
            if k != "updated_at"
        })
        if data.get("sentiment", {}).get("updated_at"):
            sentiment.updated_at = datetime.fromisoformat(data["sentiment"]["updated_at"])
        
        risk = RiskLayer(**{
            k: v for k, v in data.get("risk", {}).items()
            if k != "updated_at"
        })
        if data.get("risk", {}).get("updated_at"):
            risk.updated_at = datetime.fromisoformat(data["risk"]["updated_at"])

        alternative = AlternativeLayer(**{
            k: v for k, v in data.get("alternative", {}).items()
            if k != "updated_at"
        })
        if data.get("alternative", {}).get("updated_at"):
            alternative.updated_at = datetime.fromisoformat(data["alternative"]["updated_at"])
        
        regime = MarketRegime(data.get("regime", "unknown"))
        liquidity_regime = LiquidityRegime(data.get("liquidity_regime", "normal"))
        
        return WorldState(
            timestamp=timestamp,
            regime=regime,
            liquidity_regime=liquidity_regime,
            macro=macro,
            liquidity=liquidity,
            crypto=crypto,
            sentiment=sentiment,
            risk=risk,
            alternative=alternative,
            is_snapshot=data.get("is_snapshot", False),
            snapshot_id=data.get("snapshot_id"),
            source=data.get("source", "realtime"),
            custom_indicators=data.get("custom_indicators", {}),
        )


class WorldStateManager:
    """
    Thread-safe manager for world state.
    
    Maintains current state and provides atomic reads/writes.
    """
    
    def __init__(self):
        self._state: Optional[WorldState] = None
        self._lock = threading.RLock()
        self._update_count = 0
    
    def update_state(self, state: WorldState) -> None:
        """
        Update world state atomically.
        
        Args:
            state: New world state
        """
        with self._lock:
            self._state = state
            self._update_count += 1
    
    def get_state(self) -> Optional[WorldState]:
        """
        Get current world state (read-only copy).
        
        Returns:
            Current world state or None if not initialized
        """
        with self._lock:
            if self._state is None:
                return None
            # Return as-is (caller should not modify)
            return self._state
    
    def get_macro(self) -> Optional[MacroLayer]:
        """Get macro layer."""
        with self._lock:
            return self._state.macro if self._state else None
    
    def get_liquidity(self) -> Optional[LiquidityLayer]:
        """Get liquidity layer."""
        with self._lock:
            return self._state.liquidity if self._state else None
    
    def get_crypto(self) -> Optional[CryptoLayer]:
        """Get crypto layer."""
        with self._lock:
            return self._state.crypto if self._state else None
    
    def get_sentiment(self) -> Optional[SentimentLayer]:
        """Get sentiment layer."""
        with self._lock:
            return self._state.sentiment if self._state else None
    
    def get_risk(self) -> Optional[RiskLayer]:
        """Get risk layer."""
        with self._lock:
            return self._state.risk if self._state else None
    
    def get_regime(self) -> Optional[MarketRegime]:
        """Get current market regime."""
        with self._lock:
            return self._state.regime if self._state else None
    
    def get_update_count(self) -> int:
        """Get number of updates since creation."""
        with self._lock:
            return self._update_count
    
    def is_initialized(self) -> bool:
        """Check if state has been initialized."""
        with self._lock:
            return self._state is not None


# Global singleton instance
_world_state_manager: Optional[WorldStateManager] = None


def get_world_state_manager() -> WorldStateManager:
    """Get or create global world state manager."""
    global _world_state_manager
    if _world_state_manager is None:
        _world_state_manager = WorldStateManager()
    return _world_state_manager


if __name__ == "__main__":
    # Test
    manager = get_world_state_manager()
    
    state = WorldState(
        timestamp=datetime.now(),
        regime=MarketRegime.RISK_ON,
    )
    state.macro.DXY = 104.5
    state.crypto.BTC_Price = 52000.0
    state.sentiment.FearGreed = 65
    
    manager.update_state(state)
    
    retrieved = manager.get_state()
    print(f"✓ World State Manager initialized")
    print(f"  Regime: {retrieved.regime.value}")
    print(f"  DXY: {retrieved.macro.DXY}")
    print(f"  BTC: ${retrieved.crypto.BTC_Price:,.0f}")
    print(f"  Fear & Greed: {retrieved.sentiment.FearGreed}/100")
    print(f"  Updates: {manager.get_update_count()}")
