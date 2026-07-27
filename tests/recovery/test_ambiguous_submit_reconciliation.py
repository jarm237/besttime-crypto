from btc_scraper.execution.reservation_store import ReservationStore
from tests.recovery.helpers import make_coordinator


def _pending_reservation(coord):
    return coord.recover_reservation_for_decision(
        {"decision_id": "ed-ambiguous", "idempotency_key": "idem-ambiguous", "status": "eligible"},
        symbol="BTCUSDT",
        side="BUY",
        notional_usdt=100.0,
    )


def test_ambiguous_submit_no_match_defers_retry_without_resubmitting(recovery_paths):
    coord = make_coordinator(recovery_paths)
    reservation = _pending_reservation(coord)
    calls = []

    def lookup(client_order_id):
        calls.append(client_order_id)
        return []

    result = make_coordinator(recovery_paths).reconcile_ambiguous_submit(
        reservation_id=reservation.record_id,
        client_order_id="client-ambiguous",
        exchange_lookup=lookup,
    )

    assert result.status == "retry_deferred"
    assert calls == ["client-ambiguous"]
    assert make_coordinator(recovery_paths).ledger.snapshot()["order_count"] == 0


def test_ambiguous_submit_single_match_attaches_existing_exchange_order(recovery_paths):
    coord = make_coordinator(recovery_paths)
    reservation = _pending_reservation(coord)

    result = make_coordinator(recovery_paths).reconcile_ambiguous_submit(
        reservation_id=reservation.record_id,
        client_order_id="client-ambiguous",
        exchange_lookup=lambda _: [{"exchange_order_id": "ex-order-1", "client_order_id": "client-ambiguous"}],
    )

    assert result.status == "attached"
    stored = ReservationStore(recovery_paths["reservations"]).get_reservation(reservation.record_id)
    assert stored.client_order_id == "client-ambiguous"
    assert stored.exchange_order_id == "ex-order-1"
    snapshot = make_coordinator(recovery_paths).ledger.snapshot()
    assert snapshot["order_count"] == 1


def test_ambiguous_submit_multiple_matches_quarantines_without_new_order(recovery_paths):
    coord = make_coordinator(recovery_paths)
    reservation = _pending_reservation(coord)

    result = make_coordinator(recovery_paths).reconcile_ambiguous_submit(
        reservation_id=reservation.record_id,
        client_order_id="client-ambiguous",
        exchange_lookup=lambda _: [
            {"exchange_order_id": "ex-order-1", "client_order_id": "client-ambiguous"},
            {"exchange_order_id": "ex-order-2", "client_order_id": "client-ambiguous"},
        ],
    )

    assert result.status == "quarantined"
    assert make_coordinator(recovery_paths).ledger.snapshot()["order_count"] == 0
    assert coord.evidence_store.count_rows("evidence_quarantine") == 1
