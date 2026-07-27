from datetime import datetime, timedelta, timezone

from btc_scraper.execution.reservation_store import ReservationStore
from btc_scraper.trading.decision_types import ReservationStatus
from tests.recovery.helpers import make_coordinator


def test_pending_reservation_survives_restart_without_double_reserving(recovery_paths):
    first = make_coordinator(recovery_paths)
    created = first.recover_reservation_for_decision(
        {"decision_id": "ed-p1-6-s3", "status": "eligible"},
        symbol="BTCUSDT",
        side="BUY",
        notional_usdt=100.0,
        ttl_seconds=3600,
    )

    restarted = make_coordinator(recovery_paths)
    result = restarted.recover_pending_reservation(created.record_id)
    assert result.status == "ready_to_resume_submit"
    assert result.record_id == created.record_id

    reused = restarted.recover_reservation_for_decision(
        {"decision_id": "ed-p1-6-s3", "status": "eligible"},
        symbol="BTCUSDT",
        side="BUY",
        notional_usdt=100.0,
    )
    assert reused.status == "already_recovered"
    assert reused.record_id == created.record_id


def test_expired_pending_reservation_is_released_with_audit_event(recovery_paths):
    coord = make_coordinator(recovery_paths)
    created = coord.recover_reservation_for_decision(
        {"decision_id": "ed-expired", "status": "eligible"},
        symbol="BTCUSDT",
        side="BUY",
        notional_usdt=100.0,
        ttl_seconds=1,
    )
    future = datetime.now(timezone.utc) + timedelta(seconds=10)
    result = make_coordinator(recovery_paths).recover_pending_reservation(created.record_id, now=future)

    assert result.status == "released_expired"
    reservation = ReservationStore(recovery_paths["reservations"]).get_reservation(created.record_id)
    assert reservation.status == ReservationStatus.RELEASED
    assert coord.evidence_store.count_rows("audit_events") >= 1
