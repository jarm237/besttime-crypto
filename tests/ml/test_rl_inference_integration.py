import numpy as np
import pytest
from btc_scraper.ml_engine.inference_circuit_breaker import InferenceCircuitBreaker
from btc_scraper.ml_engine.rl_inference import guarded_rl_predict

class BrokenModel:
    def predict(self, *args, **kwargs): raise RuntimeError("boom")

class SlowModel:
    def predict(self, *args, **kwargs): return 0, None

def test_breaker_blocks_production_inference_after_failure():
    breaker = InferenceCircuitBreaker(max_failures=1, cooldown_seconds=60)
    with pytest.raises(RuntimeError): guarded_rl_predict(BrokenModel(), np.zeros(20), state=None, episode_start=np.ones(1), breaker=breaker)
    assert not breaker.allowed()
    with pytest.raises(RuntimeError, match="circuit_open"):
        guarded_rl_predict(SlowModel(), np.zeros(20), state=None, episode_start=np.ones(1), breaker=breaker)
