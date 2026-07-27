from tests.live_outage.helpers import make_live_coordinator


def test_rest_outage_is_reconciliation_unavailable_and_blocks_entries(tmp_path):
    coordinator, *_ = make_live_coordinator(tmp_path)

    state = coordinator.classify_exchange_error(channel="rest_reconciliation", error="REST timeout")

    assert state == "RECONCILIATION_UNAVAILABLE"
    health = coordinator.health_snapshot(symbol="BTCUSDT")
    assert health["entry_blocked"] is True
    assert "RECONCILIATION_UNAVAILABLE" in health["degraded_components"]
