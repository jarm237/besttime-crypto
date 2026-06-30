"""
Causal Monitoring & Metrics - Track system health and performance.

Monitors:
- Graph metrics: size, active edges, cycles
- Context engine: rule hit rate, average adjustment
- Reasoning engine: confidence, latency
- Decision engine: decision latency, action distribution
- System: graph validation errors, snapshot creation
- Event bus: event volume, subscriber count

Essential for 24/7 production operation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict, deque
from threading import Lock
import json


@dataclass
class MetricPoint:
    """Single metric measurement."""
    timestamp: datetime
    name: str
    value: float
    unit: str = ""
    tags: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "tags": self.tags,
        }


class MetricBuffer:
    """
    In-memory metric storage with rolling window.
    
    Stores last N measurements for each metric.
    """
    
    def __init__(self, max_points_per_metric: int = 10000):
        """
        Args:
            max_points_per_metric: Keep last N measurements per metric
        """
        self.max_points = max_points_per_metric
        self._metrics: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=max_points_per_metric)
        )
        self._lock = Lock()
    
    def record(self, metric: MetricPoint) -> None:
        """Record a metric measurement."""
        with self._lock:
            self._metrics[metric.name].append(metric)
    
    def get_latest(self, metric_name: str) -> Optional[MetricPoint]:
        """Get the latest measurement for a metric."""
        with self._lock:
            metrics = self._metrics.get(metric_name)
            if not metrics:
                return None
            return metrics[-1]
    
    def get_history(self, metric_name: str, limit: int = 100) -> List[MetricPoint]:
        """Get recent history for a metric."""
        with self._lock:
            metrics = self._metrics.get(metric_name, [])
            return list(metrics)[-limit:]
    
    def get_stats(self, metric_name: str) -> Dict[str, float]:
        """Calculate statistics for a metric."""
        with self._lock:
            metrics = list(self._metrics.get(metric_name, []))
        
        if not metrics:
            return {}
        
        values = [m.value for m in metrics]
        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "latest": values[-1],
        }
    
    def get_all_metrics(self) -> List[str]:
        """List all metrics being tracked."""
        with self._lock:
            return list(self._metrics.keys())


class CausalMonitor:
    """
    Central monitoring system for causal reasoning pipeline.
    """
    
    def __init__(self):
        self.buffer = MetricBuffer()
        self._lock = Lock()
        self._start_time = datetime.now()
        
        # Counters
        self._counters: Dict[str, int] = defaultdict(int)
    
    # ============================================================================
    # Graph Metrics
    # ============================================================================
    
    def record_graph_loaded(self, num_nodes: int, num_edges: int) -> None:
        """Record graph initialization."""
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="graph.num_nodes",
            value=float(num_nodes),
        ))
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="graph.num_edges",
            value=float(num_edges),
        ))
    
    def record_graph_validation_error(self, error_type: str) -> None:
        """Record graph validation error."""
        with self._lock:
            self._counters[f"graph.validation_errors.{error_type}"] += 1
        
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="graph.validation_error",
            value=1.0,
            tags={"error_type": error_type},
        ))
    
    def record_active_edges(self, count: int, total: int) -> None:
        """Record number of active edges in graph."""
        pct = (count / total * 100) if total > 0 else 0
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="graph.active_edges_pct",
            value=pct,
            unit="%",
        ))
    
    # ============================================================================
    # Context Engine Metrics
    # ============================================================================
    
    def record_context_report_generated(self, 
                                       original_score: float,
                                       adjusted_score: float,
                                       num_adjustments: int,
                                       risk_level: str,
                                       latency_ms: float) -> None:
        """Record context report generation."""
        adjustment = adjusted_score - original_score
        
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="context.adjustment_magnitude",
            value=abs(adjustment),
        ))
        
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="context.num_adjustments",
            value=float(num_adjustments),
        ))
        
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="context.latency_ms",
            value=latency_ms,
            unit="ms",
        ))
        
        with self._lock:
            self._counters[f"context.reports_by_risk.{risk_level}"] += 1
    
    def record_rule_hit(self, rule_name: str, impact: float) -> None:
        """Record when a context rule fires."""
        with self._lock:
            self._counters[f"context.rules.{rule_name}"] += 1
        
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="context.rule_impact",
            value=abs(impact),
            tags={"rule": rule_name},
        ))
    
    # ============================================================================
    # Reasoning Engine Metrics
    # ============================================================================
    
    def record_reasoning_generated(self, confidence: float, path_length: int,
                                   latency_ms: float) -> None:
        """Record causal reasoning generation."""
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="reasoning.confidence",
            value=confidence,
        ))
        
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="reasoning.path_length",
            value=float(path_length),
        ))
        
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="reasoning.latency_ms",
            value=latency_ms,
            unit="ms",
        ))
        
        with self._lock:
            self._counters["reasoning.total_generated"] += 1
    
    # ============================================================================
    # Decision Metrics
    # ============================================================================
    
    def record_decision_made(self, action: str, posterior: float,
                           latency_ms: float) -> None:
        """Record trading decision."""
        with self._lock:
            self._counters[f"decision.action.{action}"] += 1
        
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="decision.posterior",
            value=posterior,
            tags={"action": action},
        ))
        
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="decision.latency_ms",
            value=latency_ms,
            unit="ms",
        ))
    
    # ============================================================================
    # Event Bus Metrics
    # ============================================================================
    
    def record_event_published(self, event_type: str, priority: int) -> None:
        """Record event publication."""
        with self._lock:
            self._counters[f"event.{event_type}"] += 1
        
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="event.published",
            value=1.0,
            tags={"type": event_type, "priority": str(priority)},
        ))
    
    def record_event_subscriber_count(self, count: int) -> None:
        """Record number of active event subscribers."""
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="event.subscriber_count",
            value=float(count),
        ))
    
    # ============================================================================
    # Snapshot Metrics
    # ============================================================================
    
    def record_snapshot_created(self, snapshot_id: str, size_bytes: int) -> None:
        """Record snapshot creation."""
        self.buffer.record(MetricPoint(
            timestamp=datetime.now(),
            name="snapshot.size_bytes",
            value=float(size_bytes),
        ))
        
        with self._lock:
            self._counters["snapshot.total_created"] += 1
    
    # ============================================================================
    # Shadow Mode Metrics
    # ============================================================================
    
    def record_shadow_decision_logged(self, strategy_name: str) -> None:
        """Record shadow mode decision."""
        with self._lock:
            self._counters[f"shadow.decisions.{strategy_name}"] += 1
    
    # ============================================================================
    # Reporting
    # ============================================================================
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Generate dashboard data (for monitoring UI)."""
        with self._lock:
            counters_copy = dict(self._counters)
        
        uptime = datetime.now() - self._start_time
        
        return {
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": uptime.total_seconds(),
            "metrics": {
                "graph": self._get_graph_metrics(),
                "context": self._get_context_metrics(),
                "reasoning": self._get_reasoning_metrics(),
                "decision": self._get_decision_metrics(),
                "event": self._get_event_metrics(),
                "snapshot": self._get_snapshot_metrics(),
                "shadow": self._get_shadow_metrics(),
            },
            "counters": counters_copy,
        }
    
    def _get_graph_metrics(self) -> Dict[str, Any]:
        """Get graph-related metrics."""
        return {
            "validation_errors": self.buffer.get_stats("graph.validation_error"),
            "active_edges_pct": self.buffer.get_latest("graph.active_edges_pct"),
            "num_nodes": self.buffer.get_latest("graph.num_nodes"),
            "num_edges": self.buffer.get_latest("graph.num_edges"),
        }
    
    def _get_context_metrics(self) -> Dict[str, Any]:
        """Get context engine metrics."""
        return {
            "avg_adjustment": self.buffer.get_stats("context.adjustment_magnitude"),
            "avg_latency_ms": self.buffer.get_stats("context.latency_ms"),
            "num_adjustments": self.buffer.get_stats("context.num_adjustments"),
        }
    
    def _get_reasoning_metrics(self) -> Dict[str, Any]:
        """Get reasoning engine metrics."""
        return {
            "avg_confidence": self.buffer.get_stats("reasoning.confidence"),
            "avg_path_length": self.buffer.get_stats("reasoning.path_length"),
            "avg_latency_ms": self.buffer.get_stats("reasoning.latency_ms"),
        }
    
    def _get_decision_metrics(self) -> Dict[str, Any]:
        """Get decision metrics."""
        return {
            "avg_posterior": self.buffer.get_stats("decision.posterior"),
            "avg_latency_ms": self.buffer.get_stats("decision.latency_ms"),
        }
    
    def _get_event_metrics(self) -> Dict[str, Any]:
        """Get event bus metrics."""
        return {
            "subscriber_count": self.buffer.get_latest("event.subscriber_count"),
        }
    
    def _get_snapshot_metrics(self) -> Dict[str, Any]:
        """Get snapshot metrics."""
        return {
            "avg_size_bytes": self.buffer.get_stats("snapshot.size_bytes"),
        }
    
    def _get_shadow_metrics(self) -> Dict[str, Any]:
        """Get shadow mode metrics."""
        return {
            "total_decisions": sum(
                v for k, v in self._counters.items()
                if k.startswith("shadow.decisions.")
            ),
        }
    
    def export_json(self, filepath: str) -> None:
        """Export all metrics to JSON file."""
        data = self.get_dashboard_data()
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)


# Global singleton
_monitor: Optional[CausalMonitor] = None


def get_causal_monitor() -> CausalMonitor:
    """Get or create global causal monitor."""
    global _monitor
    if _monitor is None:
        _monitor = CausalMonitor()
    return _monitor


if __name__ == "__main__":
    # Test
    monitor = get_causal_monitor()
    
    # Record some metrics
    monitor.record_graph_loaded(11, 13)
    monitor.record_context_report_generated(0.75, 0.40, 3, "HIGH", 45.2)
    monitor.record_reasoning_generated(0.85, 3, 52.1)
    monitor.record_decision_made("HOLD", 0.40, 12.3)
    monitor.record_event_published("MACRO_EVENT", 8)
    
    # Get dashboard
    dashboard = monitor.get_dashboard_data()
    
    print(f"✓ Causal Monitor test complete")
    print(f"  Graph: {dashboard['metrics']['graph']}")
    print(f"  Context: {dashboard['metrics']['context']}")
    print(f"  Decision: {dashboard['metrics']['decision']}")
    print(f"  Uptime: {dashboard['uptime_seconds']:.1f}s")
