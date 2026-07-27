from tests.live_outage.helpers import make_live_coordinator, seed_reservation


def test_submit_timeout_multiple_candidates_quarantines_and_blocks_entry(tmp_path):
    coordinator, _, reservations, ledger, quarantine, _, _ = make_live_coordinator(tmp_path)
    reservation = seed_reservation(reservations)

    result = coordinator.reconcile_submit_timeout(
        reservation_id=reservation.reservation_id,
        client_order_id="client-ambiguous-1",
        symbol="BTCUSDT",
        exchange_lookup=lambda client_id: [
            {"client_order_id": client_id, "exchange_order_id": "ex-a"},
            {"client_order_id": client_id, "exchange_order_id": "ex-b"},
        ],
        decision_id="decision-live-ambiguous",
        prediction_id="prediction-live-ambiguous",
    )

    assert result.status == "quarantined"
    assert result.details["reason_code"] == "submit_timeout_multiple_candidates"
    assert result.details["reservation_id"] == reservation.reservation_id
    assert len(result.details["exchange_order_candidates"]) == 2
    assert quarantine.blocks_entries(symbol="BTCUSDT") is True
    assert ledger.snapshot()["order_count"] == 0
