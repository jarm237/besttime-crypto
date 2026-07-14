"""Production RL inference boundary: contract, latency and circuit-breaker enforcement."""
from __future__ import annotations
import time
from typing import Any
import numpy as np
from .inference_circuit_breaker import InferenceCircuitBreaker, RL_INFERENCE_BREAKER

def guarded_rl_predict(model: Any, observation: np.ndarray, *, state: Any, episode_start: np.ndarray,
                       breaker: InferenceCircuitBreaker = RL_INFERENCE_BREAKER) -> tuple[int, Any]:
    if not breaker.allowed():
        raise RuntimeError("rl_inference_circuit_open")
    started = time.perf_counter()
    try:
        action, next_state = model.predict(observation, state=state, episode_start=episode_start, deterministic=True)
        if not breaker.record_success((time.perf_counter() - started) * 1000):
            raise RuntimeError("rl_inference_latency_sla_exceeded")
        return int(action), next_state
    except Exception:
        breaker.record_failure()
        raise
