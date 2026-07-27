from tests.live_outage.helpers import make_live_coordinator, seed_reservation


def test_submit_timeout_missing_order_defers_bounded_lookup_and_keeps_reservation(tmp_path):
    coordinator, _, reservations, ledger, _, _, _ = make_live_coordinator(tmp_path)
    reservation = seed_reservation(reservations)

    result = coordinator.reconcile_submit_timeout(
        reservation_id=reservation.reservation_id,
        client_order_id="client-missing-1",
        symbol="BTCUSDT",
        exchange_lookup=lambda _: [],
    )

    assert result.status == "retry_lookup_deferred"
    assert reservations.get_reservation(reservation.reservation_id).client_order_id is None
    assert ledger.snapshot()["order_count"] == 0
    health = coordinator.health_snapshot(symbol="BTCUSDT")
    assert health["entry_blocked"] is True
    assert "RECONCILIATION_UNAVAILABLE" in health["degraded_components"]
