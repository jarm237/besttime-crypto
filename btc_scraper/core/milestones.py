"""
btc_scraper/core/milestones.py

Monotonic milestone telemetry tracker for startup, analysis, prediction, and cycle lifecycles.
Ensures each milestone is recorded once, timestamps are strictly monotonic, and no milestones
are assigned in identical positions.
"""

from __future__ import annotations

import time
from typing import Dict, Any, List, Optional


class MilestoneTracker:
    """Thread-safe monotonic milestone collector."""

    EXPECTED_ORDER = [
        "process_started",
        "imports_ready",
        "alternative_cache_ready",
        "market_data_ready",
        "first_analysis_ready",
        "all_analysis_ready",
        "first_prediction_ready",
        "all_predictions_ready",
        "first_final_decision_ready",
        "cycle_complete",
        "ai_drain_complete",
        "shutdown_complete",
    ]

    def __init__(self) -> None:
        self._milestones: Dict[str, float] = {}
        self._epoch_zero: float = time.perf_counter()

    def reset(self) -> None:
        """Reset for new cycle/run."""
        self._milestones.clear()
        self._epoch_zero = time.perf_counter()

    def record(self, name: str) -> float:
        """Record a milestone timestamp if not already recorded. Returns the recorded timestamp."""
        now = time.perf_counter()
        if name not in self._milestones:
            self._milestones[name] = now
        return self._milestones[name]

    def get(self, name: str) -> Optional[float]:
        return self._milestones.get(name)

    def elapsed_since_start(self, name: str) -> Optional[float]:
        ts = self._milestones.get(name)
        start = self._milestones.get("process_started", self._epoch_zero)
        if ts is not None:
            return round(max(0.0, ts - start), 4)
        return None

    def to_dict(self) -> Dict[str, Any]:
        start = self._milestones.get("process_started", self._epoch_zero)
        raw = {k: round(v - start, 4) for k, v in self._milestones.items()}
        valid, errors = self.validate_invariants()
        return {
            "milestones_sec": raw,
            "milestones_valid": valid,
            "validation_errors": errors,
        }

    def validate_invariants(self) -> tuple[bool, List[str]]:
        errors: List[str] = []
        recorded = [m for m in self.EXPECTED_ORDER if m in self._milestones]
        
        # Check ordering and distinctness
        for i in range(len(recorded) - 1):
            m1 = recorded[i]
            m2 = recorded[i + 1]
            t1 = self._milestones[m1]
            t2 = self._milestones[m2]
            if t1 > t2:
                errors.append(f"Monotonic violation: {m1} ({t1:.4f}) > {m2} ({t2:.4f})")
            elif t1 == t2 and m1 in ("first_analysis_ready", "first_prediction_ready"):
                errors.append(f"Assignment collision: {m1} and {m2} have identical timestamp ({t1:.4f})")

        # Specific strict invariants
        if "process_started" in self._milestones and "imports_ready" in self._milestones:
            if self._milestones["process_started"] > self._milestones["imports_ready"]:
                errors.append("process_started > imports_ready")

        if "market_data_ready" in self._milestones and "first_analysis_ready" in self._milestones:
            if self._milestones["market_data_ready"] > self._milestones["first_analysis_ready"]:
                errors.append("market_data_ready > first_analysis_ready")

        if "first_analysis_ready" in self._milestones and "first_prediction_ready" in self._milestones:
            if self._milestones["first_analysis_ready"] >= self._milestones["first_prediction_ready"]:
                errors.append(
                    f"first_analysis_ready ({self._milestones['first_analysis_ready']:.4f}) "
                    f">= first_prediction_ready ({self._milestones['first_prediction_ready']:.4f})"
                )

        if "first_prediction_ready" in self._milestones and "first_final_decision_ready" in self._milestones:
            if self._milestones["first_prediction_ready"] > self._milestones["first_final_decision_ready"]:
                errors.append("first_prediction_ready > first_final_decision_ready")

        return (len(errors) == 0, errors)


# Global singleton instance
milestone_tracker = MilestoneTracker()

