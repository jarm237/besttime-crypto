from tests.live_outage.helpers import make_live_coordinator


def test_ws_rest_conflict_records_observations_and_keeps_rest_authoritative(tmp_path):
    coordinator, _, _, _, quarantine, _, observations = make_live_coordinator(tmp_path)

    ws = coordinator.record_observation(
        source="WS",
        status="OPEN",
        symbol="BTCUSDT",
        client_order_id="client-conflict-1",
    )
    rest = coordinator.record_observation(
        source="REST",
        status="FILLED",
        symbol="BTCUSDT",
        client_order_id="client-conflict-1",
    )

    assert ws.status == "observation_recorded"
    assert rest.status == "rest_authoritative_conflict_recorded"
    assert observations.authoritative_status(client_order_id="client-conflict-1")["status"] == "FILLED"
    assert quarantine.unresolved()[0]["reason_code"] == "ws_rest_order_state_conflict"
