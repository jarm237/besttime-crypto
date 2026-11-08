from __future__ import annotations

import json

from btc_scraper.core.operational_resilience import CircuitBreaker, DatabaseResilience, SQLiteEventSpool, ShutdownCoordinator, atomic_write_json, service_health


def test_db_outage_spools_and_replays_idempotently(tmp_path):
    spool = SQLiteEventSpool(tmp_path / "spool.sqlite")
    resilience = DatabaseResilience(spool, CircuitBreaker(failure_threshold=1, recovery_seconds=0))
    delivered = {}
    def outage(*_):
        raise ConnectionError()
    assert resilience.submit("one", {"value": 1}, outage) == "SPOOLED"
    assert spool.size() == 1
    assert resilience.replay(lambda event_id, payload: delivered.setdefault(event_id, payload)) == 1
    assert delivered == {"one": {"value": 1}}
    assert resilience.replay(lambda *_: None) == 0


def test_circuit_breaker_moves_open_half_open_closed():
    breaker = CircuitBreaker(failure_threshold=1, recovery_seconds=0)
    breaker.failure(); assert breaker.state == "OPEN"
    assert breaker.allow() is True and breaker.state == "HALF_OPEN"
    breaker.success(); assert breaker.state == "CLOSED"


def test_atomic_write_never_leaves_partial_json(tmp_path):
    path = tmp_path / "latest_signals.json"
    atomic_write_json(path, {"signal": "BUY"})
    assert json.loads(path.read_text()) == {"signal": "BUY"}
    assert not list(tmp_path.glob("*.tmp"))


def test_health_readiness_reflects_dependencies(monkeypatch, tmp_path):
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", lambda path: shutil._ntuple_diskusage(100 * 1024**3, 50 * 1024**3, 50 * 1024**3))
    unhealthy = service_health(db_ok=False, exchange_ok=True, model_ok=True, data_path=tmp_path)
    assert unhealthy["live"] is True and unhealthy["ready"] is False
    healthy = service_health(db_ok=True, exchange_ok=True, model_ok=True, data_path=tmp_path)
    assert healthy["ready"] is True and healthy["dependencies"]["disk"] is True


def test_graceful_shutdown_runs_all_cleanup_callbacks():
    stopped = []
    coordinator = ShutdownCoordinator()
    coordinator.register(lambda: stopped.append("scheduler"))
    coordinator.register(lambda: stopped.append("session"))
    assert coordinator.shutdown() == []
    assert set(stopped) == {"scheduler", "session"}
