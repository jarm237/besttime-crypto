"""In-process ML health and degradation counters for observable fallback paths."""
from __future__ import annotations

from collections import Counter
from threading import Lock
from typing import Any

_lock = Lock()
_counters: Counter[str] = Counter()
METRIC_NAMES = (
    "ml_inference_failure_total", "artifact_load_rejected_total",
    "prediction_audit_write_failure_total", "context_provider_failure_total",
    "registry_conflict_total", "calibration_report_failure_total",
)
_components: dict[str, dict[str, Any]] = {
    name: {"status": "healthy", "last_error": None}
    for name in (
        "ml_inference", "ml_governance", "artifact_loader",
        "prediction_audit", "runtime_calibration", "rl_environment",
        "context_provider",
    )
}


def increment(metric: str, amount: int = 1) -> None:
    with _lock:
        _counters[metric] += amount


def record_degradation(component: str, metric: str, error: BaseException | str) -> None:
    with _lock:
        _counters[metric] += 1
        _components.setdefault(component, {})
        _components[component].update({"status": "degraded", "last_error": str(error)})


def record_healthy(component: str) -> None:
    with _lock:
        _components.setdefault(component, {})
        _components[component].update({"status": "healthy", "last_error": None})


def health_snapshot() -> dict[str, Any]:
    with _lock:
        metrics = {name: int(_counters.get(name, 0)) for name in METRIC_NAMES}
        metrics.update({key: int(value) for key, value in _counters.items()})
        return {"components": {key: dict(value) for key, value in _components.items()}, "metrics": metrics}
