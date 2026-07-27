from tests.live_outage.helpers import make_live_coordinator


def test_websocket_stale_is_market_data_degraded_not_generic_exchange_error(tmp_path):
    coordinator, *_ = make_live_coordinator(tmp_path)

    state = coordinator.classify_exchange_error(channel="websocket_market_data", error="stale websocket feed")

    assert state == "MARKET_DATA_DEGRADED"
    health = coordinator.health_snapshot(symbol="BTCUSDT")
    assert health["entry_blocked"] is True
    assert health["authority"]["reconciliation"] == "REST_ORDER_DETAIL"
