import pytest

from tests.live_outage.helpers import make_live_coordinator, seed_reservation


def test_operator_quarantine_resolution_is_audited_without_force_resolve(tmp_path):
    coordinator, _, reservations, _, quarantine, _, _ = make_live_coordinator(tmp_path)
    reservation = seed_reservation(reservations)
    result = coordinator.reconcile_submit_timeout(
        reservation_id=reservation.reservation_id,
        client_order_id="client-operator-1",
        symbol="BTCUSDT",
        exchange_lookup=lambda client_id: [
            {"client_order_id": client_id, "exchange_order_id": "ex-1"},
            {"client_order_id": client_id, "exchange_order_id": "ex-2"},
        ],
    )

    with pytest.raises(ValueError):
        quarantine.resolve(result.details["quarantine_id"], action="FORCE_RESOLVE", operator="ops")

    resolved = quarantine.resolve(
        result.details["quarantine_id"],
        action="ATTACH_EXISTING_ORDER",
        operator="ops-user",
        note="Attached exchange order ex-1 after manual venue check.",
        amendment={"exchange_order_id": "ex-1"},
    )
    snapshot = quarantine.snapshot()

    assert resolved["resolution_status"] == "ATTACH_EXISTING_ORDER"
    assert snapshot["audit_events"][-1]["event_type"] == "quarantine_resolved"
    assert snapshot["records"][result.details["quarantine_id"]]["exchange_order_candidates"][1]["exchange_order_id"] == "ex-2"
