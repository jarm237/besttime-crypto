from concurrent.futures import ThreadPoolExecutor

from btc_scraper.execution.reservation_store import ReservationStore
from tests.recovery.helpers import make_coordinator


def test_decision_creates_one_deterministic_reservation_under_concurrent_recovery(recovery_paths):
    decision = {"decision_id": "ed-p1-6-s2", "prediction_id": "pred-p1-6-s2", "status": "eligible"}

    def recover_once(_):
        coord = make_coordinator(recovery_paths)
        return coord.recover_reservation_for_decision(
            decision,
            symbol="BTCUSDT",
            side="BUY",
            notional_usdt=100.0,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(recover_once, range(8)))

    reservation_ids = {result.record_id for result in results}
    assert len(reservation_ids) == 1
    reservation = ReservationStore(recovery_paths["reservations"]).get_by_entry_decision_id("ed-p1-6-s2")
    assert reservation is not None
    assert reservation.idempotency_key.startswith("idem-")
    assert reservation.reservation_id.startswith("res-")


def test_rejected_decision_is_not_reserved_or_submitted(recovery_paths):
    coord = make_coordinator(recovery_paths)
    result = coord.recover_reservation_for_decision(
        {"decision_id": "ed-rejected", "prediction_id": "pred-rejected", "status": "rejected"},
        symbol="BTCUSDT",
        side="BUY",
        notional_usdt=100.0,
    )
    assert result.status == "skipped_non_executable_decision"
    assert ReservationStore(recovery_paths["reservations"]).get_by_entry_decision_id("ed-rejected") is None
