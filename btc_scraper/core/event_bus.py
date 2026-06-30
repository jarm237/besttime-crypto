"""
Event Bus - Pub/Sub system for real-time event distribution.

When macro events occur (e.g., CPI announcement), they're published to the bus
and all interested subscribers (Context Engine, Scenario Simulator, Reasoning, Telegram) 
receive them immediately.

Designed to scale to Kafka/Redis Streams later.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Callable, Optional, Set
import json
import threading
from enum import Enum
from queue import Queue


class EventType(Enum):
    """Types of events."""
    # Macro events
    MACRO_EVENT = "macro_event"  # CPI, NFP, FOMC decision, etc
    FED_PIVOT = "fed_pivot"
    ECONOMIC_SHOCK = "economic_shock"
    
    # Market events
    FUNDING_SPIKE = "funding_spike"
    OI_SPIKE = "oi_spike"
    LIQUIDITY_CRISIS = "liquidity_crisis"
    MARKET_REGIME_CHANGE = "regime_change"
    
    # Sentiment events
    SENTIMENT_SHIFT = "sentiment_shift"
    SOCIAL_VOLUME_SPIKE = "social_volume_spike"
    WHALE_ACTIVITY = "whale_activity"
    
    # Internal events
    DECISION_MADE = "decision_made"
    TRADE_EXECUTED = "trade_executed"
    TRADE_CLOSED = "trade_closed"
    ALERT_SENT = "alert_sent"
    
    # System events
    GRAPH_UPDATED = "graph_updated"
    RULES_RELOADED = "rules_reloaded"
    SNAPSHOT_CREATED = "snapshot_created"
    ERROR_OCCURRED = "error_occurred"


@dataclass
class Event:
    """
    Unified event structure.
    
    Attributes:
        type: EventType
        timestamp: When event occurred
        source: Which module created it
        data: Event-specific payload
        priority: 0 (low) to 10 (critical)
        event_id: Unique identifier for tracking
        causally_related_to: List of previous event IDs (for causal chains)
    """
    type: EventType
    timestamp: datetime
    source: str
    data: Dict[str, Any]
    priority: int = 5
    event_id: str = field(default_factory=lambda: str(datetime.now().timestamp()))
    causally_related_to: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict (for logging/Kafka)."""
        return {
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "data": self.data,
            "priority": self.priority,
            "event_id": self.event_id,
            "causally_related_to": self.causally_related_to,
        }
    
    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'Event':
        """Deserialize from dict."""
        return Event(
            type=EventType(d["type"]),
            timestamp=datetime.fromisoformat(d["timestamp"]),
            source=d["source"],
            data=d["data"],
            priority=d.get("priority", 5),
            event_id=d.get("event_id", str(datetime.now().timestamp())),
            causally_related_to=d.get("causally_related_to", []),
        )


class EventSubscriber:
    """Subscription to events with optional filtering."""
    
    def __init__(self, name: str, callback: Callable[[Event], None], 
                 event_types: Optional[List[EventType]] = None,
                 min_priority: int = 0):
        """
        Args:
            name: Subscriber name (for debugging)
            callback: Function to call when event received
            event_types: List of event types to subscribe to (None = all)
            min_priority: Only receive events with priority >= min_priority
        """
        self.name = name
        self.callback = callback
        self.event_types = event_types
        self.min_priority = min_priority
    
    def should_receive(self, event: Event) -> bool:
        """Check if subscriber should receive this event."""
        if event.priority < self.min_priority:
            return False
        if self.event_types and event.type not in self.event_types:
            return False
        return True


class EventBus:
    """
    Thread-safe event bus with pub/sub support.
    
    Currently in-memory. Can be extended to use Kafka/Redis Streams.
    """
    
    def __init__(self, max_history: int = 10000):
        """
        Args:
            max_history: Keep last N events in memory
        """
        self._subscribers: Dict[str, EventSubscriber] = {}
        self._event_history: List[Event] = []
        self._max_history = max_history
        self._lock = threading.RLock()
        self._queue = Queue()
        self._event_count = 0
    
    def subscribe(self, name: str, callback: Callable[[Event], None],
                 event_types: Optional[List[EventType]] = None,
                 min_priority: int = 0) -> str:
        """
        Subscribe to events.
        
        Args:
            name: Subscriber name
            callback: Function to call on event
            event_types: Which event types to receive (None = all)
            min_priority: Only high-priority events
        
        Returns:
            Subscription ID
        """
        subscriber = EventSubscriber(name, callback, event_types, min_priority)
        sub_id = f"{name}_{id(callback)}"
        
        with self._lock:
            self._subscribers[sub_id] = subscriber
        
        return sub_id
    
    def unsubscribe(self, sub_id: str) -> None:
        """Unsubscribe from events."""
        with self._lock:
            self._subscribers.pop(sub_id, None)
    
    def publish(self, event: Event) -> None:
        """
        Publish event to all subscribers.
        
        Args:
            event: Event to publish
        """
        with self._lock:
            self._event_count += 1
            self._event_history.append(event)
            
            # Keep only last N events
            if len(self._event_history) > self._max_history:
                self._event_history = self._event_history[-self._max_history:]
            
            # Notify subscribers
            for subscriber in self._subscribers.values():
                if subscriber.should_receive(event):
                    try:
                        subscriber.callback(event)
                    except Exception as e:
                        # Log but don't crash
                        print(f"Error in subscriber {subscriber.name}: {str(e)}")
    
    def get_history(self, event_type: Optional[EventType] = None, 
                   limit: int = 100) -> List[Event]:
        """
        Get recent event history.
        
        Args:
            event_type: Filter by type (None = all)
            limit: Max events to return
        
        Returns:
            List of events (most recent first)
        """
        with self._lock:
            history = list(reversed(self._event_history))
            if event_type:
                history = [e for e in history if e.type == event_type]
            return history[:limit]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get bus statistics."""
        with self._lock:
            event_counts = {}
            for event in self._event_history:
                key = event.type.value
                event_counts[key] = event_counts.get(key, 0) + 1
            
            return {
                "total_events": self._event_count,
                "history_size": len(self._event_history),
                "subscribers": len(self._subscribers),
                "event_types": event_counts,
            }


# Global singleton instance
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get or create global event bus."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


if __name__ == "__main__":
    # Test
    bus = get_event_bus()
    
    # Subscribe
    received_events = []
    
    def on_macro_event(event: Event):
        received_events.append(event)
        print(f"  Received: {event.type.value} from {event.source}")
    
    bus.subscribe(
        "test_subscriber",
        on_macro_event,
        event_types=[EventType.MACRO_EVENT, EventType.FED_PIVOT]
    )
    
    # Publish
    event1 = Event(
        type=EventType.MACRO_EVENT,
        timestamp=datetime.now(),
        source="collector",
        data={"indicator": "CPI", "value": 3.5, "expected": 3.4},
        priority=8,
    )
    bus.publish(event1)
    
    event2 = Event(
        type=EventType.MACRO_EVENT,
        timestamp=datetime.now(),
        source="collector",
        data={"indicator": "NFP", "value": 210000},
        priority=9,
    )
    bus.publish(event2)
    
    event3 = Event(
        type=EventType.DECISION_MADE,
        timestamp=datetime.now(),
        source="decision_engine",
        data={"action": "BUY", "posterior": 0.75},
        priority=5,
    )
    bus.publish(event3)
    
    print(f"✓ Event Bus test complete")
    print(f"  Received {len(received_events)} events (filtered)")
    print(f"  Bus stats: {bus.get_stats()}")
    print(f"  Recent macro events: {len(bus.get_history(EventType.MACRO_EVENT))}")
