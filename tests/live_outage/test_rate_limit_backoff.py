from tests.live_outage.helpers import FakeClock, make_live_coordinator


def test_rate_limit_backoff_honors_retry_after_and_preserves_priority(tmp_path):
    clock = FakeClock()
    coordinator, _, _, _, _, backoff, _ = make_live_coordinator(tmp_path, clock=clock)

    first = coordinator.record_rate_limit(scope="exchange", retry_after_seconds=7, error_code="HTTP_429")
    second = coordinator.record_rate_limit(scope="exchange", retry_after_seconds=None, error_code="WEIGHT_LIMIT", weight=1200)

    assert first["delay_seconds"] >= 7
    assert second["delay_seconds"] >= 2
    assert backoff.priority_allowed(scope="exchange", priority="new_entry") is False
    assert backoff.priority_allowed(scope="exchange", priority="cancel_dangerous_order") is True
    health = coordinator.health_snapshot(rate_limit_scope="exchange")
    assert health["rate_limited"] is True
    assert health["priority_allowed"]["new_entry"] is False
    clock.advance(120)
    assert backoff.priority_allowed(scope="exchange", priority="new_entry") is True
