from tests.live_outage.helpers import make_live_coordinator, seed_reservation


def test_submit_timeout_attaches_existing_exchange_order_without_duplicate(tmp_path):
    coordinator, _, reservations, ledger, _, _, _ = make_live_coordinator(tmp_path)
    reservation = seed_reservation(reservations)

    result = coordinator.reconcile_submit_timeout(
        reservation_id=reservation.reservation_id,
        client_order_id="client-timeout-1",
        symbol="BTCUSDT",
        exchange_lookup=lambda client_id: [{
            "client_order_id": client_id,
            "exchange_order_id": "exchange-timeout-1",
            "status": "OPEN",
        }],
    )
    replay = coordinator.reconcile_submit_timeout(
        reservation_id=reservation.reservation_id,
        client_order_id="client-timeout-1",
        symbol="BTCUSDT",
        exchange_lookup=lambda client_id: [{
            "client_order_id": client_id,
            "exchange_order_id": "exchange-timeout-1",
            "status": "OPEN",
        }],
    )

    assert result.status == "attached"
    assert replay.status == "attached"
    attached = reservations.get_reservation(reservation.reservation_id)
    assert attached.client_order_id == "client-timeout-1"
    assert attached.exchange_order_id == "exchange-timeout-1"
    assert ledger.snapshot()["order_count"] == 1
