from btc_scraper.ml_engine.inference_circuit_breaker import InferenceCircuitBreaker

def test_breaker_opens_after_failures_and_latency():
    breaker = InferenceCircuitBreaker(max_failures=2, max_latency_ms=10, cooldown_seconds=60)
    breaker.record_failure(); breaker.record_success(11)
    assert not breaker.allowed()
