"""
tests/test_reservation.py
PR 5 — Reservation store unit tests.
"""
import pytest
import time
from pathlib import Path
from btc_scraper.execution.reservation_store import ReservationStore, ReservationStatus


@pytest.fixture
def store(tmp_path) -> ReservationStore:
    db_file = tmp_path / "reservations.db"
    return ReservationStore(db_path=db_file)


def test_successful_reservation(store):
    rec, created = store.reserve(
        reservation_id="res-1",
        idempotency_key="idem-key-1",
        entry_decision_id="ed-123",
        symbol="BTC/USDT",
        side="buy",
        reserved_notional=100.0,
    )
    assert created
    assert rec.reservation_id == "res-1"
    assert rec.status == ReservationStatus.PENDING
    assert rec.reserved_notional == 100.0


def test_idempotency_duplicate_key(store):
    rec1, created1 = store.reserve(
        reservation_id="res-1",
        idempotency_key="idem-key-1",
        entry_decision_id="ed-123",
        symbol="BTC/USDT",
        side="buy",
        reserved_notional=100.0,
    )
    assert created1

    # Attempt to reserve with same idempotency key but different reservation ID
    rec2, created2 = store.reserve(
        reservation_id="res-2",
        idempotency_key="idem-key-1",
        entry_decision_id="ed-123",
        symbol="BTC/USDT",
        side="buy",
        reserved_notional=100.0,
    )
    assert not created2
    assert rec2.reservation_id == "res-1" # Returns the existing reservation record
    assert rec2.status == ReservationStatus.PENDING


def test_commit_flow(store):
    store.reserve("res-1", "idem-1", "ed-1", "BTC/USDT", "buy", 10.0)
    rec = store.commit("res-1", filled_notional=9.8, exchange_order_id="ex-1", client_order_id="cl-1")
    assert rec.status == ReservationStatus.COMMITTED
    assert rec.filled_notional == 9.8
    assert rec.exchange_order_id == "ex-1"
    assert rec.client_order_id == "cl-1"


def test_partial_commit_flow(store):
    store.reserve("res-1", "idem-1", "ed-1", "BTC/USDT", "buy", 10.0)
    rec = store.partial_commit("res-1", filled_notional=4.0, exchange_order_id="ex-1", client_order_id="cl-1")
    assert rec.status == ReservationStatus.PARTIALLY_COMMITTED
    assert rec.filled_notional == 4.0


def test_release_flow(store):
    store.reserve("res-1", "idem-1", "ed-1", "BTC/USDT", "buy", 10.0)
    rec = store.release("res-1")
    assert rec.status == ReservationStatus.RELEASED


def test_get_active_totals(store):
    store.reserve("res-1", "idem-1", "ed-1", "BTC/USDT", "buy", 10.0, reserved_position_slots=1)
    store.reserve("res-2", "idem-2", "ed-2", "BTC/USDT", "buy", 15.0, reserved_position_slots=1)
    # Excluded from active because it is released
    store.reserve("res-3", "idem-3", "ed-3", "BTC/USDT", "buy", 20.0, reserved_position_slots=1)
    store.release("res-3")

    notional, slots = store.get_active_notional_and_slots()
    assert notional == 25.0
    assert slots == 2


def test_expiry(store):
    # Reserve with TTL = 0 (expires immediately)
    rec, created = store.reserve(
        reservation_id="res-1",
        idempotency_key="idem-key-1",
        entry_decision_id="ed-123",
        symbol="BTC/USDT",
        side="buy",
        reserved_notional=100.0,
        ttl_seconds=-10, # past time to trigger expiry
    )
    assert rec.status == ReservationStatus.PENDING

    # Run expiry cleanup
    expired_count = store.expire_stale()
    assert expired_count == 1

    rec_after = store.get_reservation("res-1")
    assert rec_after.status == ReservationStatus.EXPIRED

    # Active totals should be 0 since it is expired
    notional, slots = store.get_active_notional_and_slots()
    assert notional == 0.0
    assert slots == 0
