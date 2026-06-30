"""
Context Provider - Abstract interface for context adjustment strategies.

Allows different approaches to be plugged in:
- RuleContextProvider (Phase 3 - current)
- BayesianContextProvider (Phase 5)
- RLContextProvider (Phase 6)
- LLMContextProvider (Phase 7)

Decision Engine uses the interface, not the implementation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum

from btc_scraper.core.world_state import WorldState


class RiskLevel(Enum):
    """Risk assessment levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ContextAdjustment:
    """Single context adjustment."""
    provider_name: str
    factor_name: str  # "Macro Risk", "Funding Spike", etc
    original_score: float
    adjustment: float  # Can be positive or negative
    adjusted_score: float
    confidence: float  # 0.0 to 1.0
    reason: str
    metadata: Dict[str, Any] = None


@dataclass
class ContextReport:
    """Complete context analysis report."""
    timestamp: datetime
    provider_name: str  # Which provider generated this
    world_state: Optional[Dict[str, Any]] = None  # Snapshot of world state
    original_score: float = 0.0
    adjusted_score: float = 0.0
    risk_level: RiskLevel = RiskLevel.MEDIUM
    adjustments: List[ContextAdjustment] = None
    explanation: str = ""
    # For multi-layer providers
    breakdown: Dict[str, float] = None  # Layer name → total adjustment
    stop_processing: bool = False  # Stop further context adjustments
    
    def __post_init__(self):
        if self.adjustments is None:
            self.adjustments = []
        if self.breakdown is None:
            self.breakdown = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "provider_name": self.provider_name,
            "original_score": self.original_score,
            "adjusted_score": self.adjusted_score,
            "risk_level": self.risk_level.value,
            "adjustments": [
                {
                    "provider": adj.provider_name,
                    "factor": adj.factor_name,
                    "original": adj.original_score,
                    "adjustment": adj.adjustment,
                    "adjusted": adj.adjusted_score,
                    "confidence": adj.confidence,
                    "reason": adj.reason,
                    "metadata": adj.metadata or {},
                }
                for adj in self.adjustments
            ],
            "explanation": self.explanation,
            "breakdown": self.breakdown,
            "stop_processing": self.stop_processing,
            "world_state_snapshot": self.world_state,
        }


class ContextProvider(ABC):
    """
    Abstract base class for context adjustment strategies.
    
    Subclasses implement different approaches to generating context reports.
    """
    
    def __init__(self, name: str):
        """
        Args:
            name: Provider name (e.g., "RuleContextProvider", "BayesianContextProvider")
        """
        self.name = name
    
    @abstractmethod
    def generate_context_report(self, original_score: float, 
                               world_state: WorldState) -> ContextReport:
        """
        Generate context report for a given signal score.
        
        Args:
            original_score: Original signal score (0.0 to 1.0)
            world_state: Current market state
        
        Returns:
            ContextReport with adjustments and explanation
        """
        pass
    
    @abstractmethod
    def should_apply_context(self, world_state: WorldState) -> bool:
        """
        Check if context adjustments should be applied in current conditions.
        
        Allows providers to say "don't adjust now" (e.g., during extreme volatility).
        
        Args:
            world_state: Current market state
        
        Returns:
            True if adjustments should be applied
        """
        pass
    
    @abstractmethod
    def validate(self) -> tuple[bool, str]:
        """
        Validate provider configuration.
        
        Returns:
            (is_valid, error_message)
        """
        pass
    
    def explain_adjustment(self, adjustment: ContextAdjustment) -> str:
        """
        Generate human-readable explanation for an adjustment.
        
        Can be overridden by subclasses for more sophisticated explanations.
        
        Args:
            adjustment: The adjustment to explain
        
        Returns:
            Explanation string
        """
        direction = "increased" if adjustment.adjustment > 0 else "decreased"
        magnitude = abs(adjustment.adjustment)
        return (
            f"{adjustment.factor_name}: signal {direction} by {magnitude:.3f} "
            f"({adjustment.reason})"
        )


class CompositeContextProvider(ContextProvider):
    """
    Combines multiple context providers in sequence.
    
    Useful for:
    - Phase 3→5: Mix Rule + Bayesian
    - Phase 5→6: Mix Bayesian + RL
    - Phase 7: Mix all approaches
    """
    
    def __init__(self, name: str, providers: List[ContextProvider],
                 stop_on_critical: bool = True):
        """
        Args:
            name: Composite provider name
            providers: List of providers to apply in order
            stop_on_critical: Stop processing if risk becomes CRITICAL
        """
        super().__init__(name)
        self.providers = providers
        self.stop_on_critical = stop_on_critical
    
    def generate_context_report(self, original_score: float,
                               world_state: WorldState) -> ContextReport:
        """
        Apply providers in sequence, each modifying the score.
        
        Args:
            original_score: Original signal score
            world_state: Current market state
        
        Returns:
            Final composite context report
        """
        current_score = original_score
        all_adjustments: List[ContextAdjustment] = []
        breakdown: Dict[str, float] = {}
        
        for provider in self.providers:
            if not provider.should_apply_context(world_state):
                continue
            
            report = provider.generate_context_report(current_score, world_state)
            
            # Accumulate adjustments
            for adj in report.adjustments:
                all_adjustments.append(adj)
            
            # Update breakdown
            provider_breakdown = report.breakdown or {provider.name: report.adjusted_score - current_score}
            breakdown.update(provider_breakdown)
            
            # Update current score
            current_score = report.adjusted_score
            
            # Stop if critical or provider requests it
            if report.stop_processing or (
                self.stop_on_critical and report.risk_level == RiskLevel.CRITICAL
            ):
                break
        
        # Determine overall risk level
        risk_levels = [RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW]
        max_risk = RiskLevel.LOW
        for adj in all_adjustments:
            # Infer risk level from adjustment (can be overridden)
            if abs(adj.adjustment) > 0.3:
                max_risk = RiskLevel.HIGH
            elif abs(adj.adjustment) > 0.15:
                max_risk = RiskLevel.MEDIUM
        
        return ContextReport(
            timestamp=world_state.timestamp,
            provider_name=self.name,
            world_state=world_state.to_dict(),
            original_score=original_score,
            adjusted_score=current_score,
            risk_level=max_risk,
            adjustments=all_adjustments,
            breakdown=breakdown,
            explanation=f"Composite adjustment via {len(self.providers)} providers",
        )
    
    def should_apply_context(self, world_state: WorldState) -> bool:
        """Apply if any provider should apply."""
        return any(p.should_apply_context(world_state) for p in self.providers)
    
    def validate(self) -> tuple[bool, str]:
        """Validate all providers."""
        if not self.providers:
            return False, "No providers in composite"
        
        for provider in self.providers:
            is_valid, error = provider.validate()
            if not is_valid:
                return False, f"Provider {provider.name}: {error}"
        
        return True, "All providers valid"


class NoOpContextProvider(ContextProvider):
    """
    No-operation context provider (returns score unchanged).
    
    Useful for testing or disabling context adjustments temporarily.
    """
    
    def __init__(self):
        super().__init__("NoOpContextProvider")
    
    def generate_context_report(self, original_score: float,
                               world_state: WorldState) -> ContextReport:
        """Return unchanged score."""
        return ContextReport(
            timestamp=world_state.timestamp,
            provider_name=self.name,
            original_score=original_score,
            adjusted_score=original_score,
            risk_level=RiskLevel.LOW,
            adjustments=[],
            explanation="No-op provider: no adjustments applied",
        )
    
    def should_apply_context(self, world_state: WorldState) -> bool:
        """Never apply."""
        return False
    
    def validate(self) -> tuple[bool, str]:
        """Always valid."""
        return True, "No-op provider has no configuration to validate"


if __name__ == "__main__":
    # Test
    from datetime import datetime
    
    # Create dummy world state
    world_state = WorldState(timestamp=datetime.now())
    world_state.macro.DXY = 104.5
    world_state.sentiment.FearGreed = 35  # Fear
    
    # Use no-op provider
    provider = NoOpContextProvider()
    is_valid, error = provider.validate()
    print(f"✓ Provider validation: {is_valid}")
    
    report = provider.generate_context_report(0.75, world_state)
    print(f"✓ Context Report:")
    print(f"  Original: {report.original_score:.3f}")
    print(f"  Adjusted: {report.adjusted_score:.3f}")
    print(f"  Risk: {report.risk_level.value}")
    print(f"  Adjustments: {len(report.adjustments)}")
