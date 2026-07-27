from __future__ import annotations

from datetime import datetime, timedelta, timezone

from btc_scraper.execution.live_outage import (
    ExchangeObservationStore,
    LiveOutageCoordinator,
    QuarantineStore,
    RateLimitBackoff,
)
from btc_scraper.execution.order_fill_ledger import OrderFillLedger
from btc_scraper.execution.reservation_store import ReservationStore
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 7, 27, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def outage_paths(tmp_path):
    return {
        "evidence": tmp_path / "runtime_evidence.sqlite",
        "reservations": tmp_path / "reservations.db",
        "ledger": tmp_path / "order_fill_ledger.json",
        "quarantine": tmp_path / "quarantine.json",
        "backoff": tmp_path / "rate_limit.json",
        "observations": tmp_path / "observations.json",
        "children": tmp_path / "child_orders.json",
        "cancel_replace": tmp_path / "cancel_replace.json",
    }


def seed_reservation(store: ReservationStore, reservation_id: str = "res-live-1"):
    record, _ = store.reserve(
        reservation_id=reservation_id,
        idempotency_key=f"idem-{reservation_id}",
        entry_decision_id=f"decision-{reservation_id}",
        symbol="BTCUSDT",
        side="buy",
        reserved_notional=100.0,
        ttl_seconds=300,
    )
    return record


def make_live_coordinator(tmp_path, *, clock: FakeClock | None = None):
    paths = outage_paths(tmp_path)
    evidence = RuntimeEvidenceStore(paths["evidence"])
    reservations = ReservationStore(paths["reservations"])
    ledger = OrderFillLedger(paths["ledger"])
    quarantine = QuarantineStore(paths["quarantine"], evidence_store=evidence)
    backoff = RateLimitBackoff(paths["backoff"], jitter=lambda: 0.125, now=(clock.now if clock else None))
    observations = ExchangeObservationStore(paths["observations"])
    coordinator = LiveOutageCoordinator(
        evidence_store=evidence,
        reservation_store=reservations,
        ledger=ledger,
        quarantine_store=quarantine,
        backoff=backoff,
        observation_store=observations,
    )
    return coordinator, paths, reservations, ledger, quarantine, backoff, observations
