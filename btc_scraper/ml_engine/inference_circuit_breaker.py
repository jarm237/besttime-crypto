"""Fail-closed in-process circuit breaker for inference failures and latency."""
from __future__ import annotations
import os
import time
from dataclasses import dataclass

@dataclass
class InferenceCircuitBreaker:
    max_failures: int = 3
    max_latency_ms: float = 150.0
    cooldown_seconds: float = 300.0
    failures: int = 0
    opened_at: float | None = None
    def allowed(self) -> bool:
        if self.opened_at is None: return True
        if time.monotonic() - self.opened_at >= self.cooldown_seconds:
            self.failures, self.opened_at = 0, None
            return True
        return False
    def record_success(self, latency_ms: float) -> bool:
        if latency_ms > self.max_latency_ms:
            return self.record_failure()
        self.failures = 0
        return True
    def record_failure(self) -> bool:
        self.failures += 1
        if self.failures >= self.max_failures: self.opened_at = time.monotonic()
        return False

RL_INFERENCE_BREAKER = InferenceCircuitBreaker(
    max_failures=int(os.getenv("RL_EXIT_MAX_INFERENCE_FAILURES", "3")),
    max_latency_ms=float(os.getenv("RL_EXIT_MAX_LATENCY_MS", "150")),
)
