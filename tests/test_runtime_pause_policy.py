from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from btc_scraper.core.runtime_pause import (
    RuntimePauseController,
    RuntimePausePolicy,
    external_reason_for_exception,
)


class FakeClock:
    def __init__(self) -> None:
        self.wall = datetime(2026, 8, 3, tzinfo=timezone.utc)
        self.monotonic = 100.0

    def advance(self, seconds: float, *, monotonic_seconds: float | None = None) -> None:
        self.wall += timedelta(seconds=seconds)
        self.monotonic += seconds if monotonic_seconds is None else monotonic_seconds


def _controller(tmp_path, clock: FakeClock, **policy_overrides):
    policy = RuntimePausePolicy(**policy_overrides)
    return RuntimePauseController(
        tmp_path,
        policy=policy,
        wall_clock=lambda: clock.wall,
        monotonic_clock=lambda: clock.monotonic,
    )


def test_network_pause_preserves_epoch_and_creates_no_synthetic_evidence(tmp_path):
    clock = FakeClock()
    controller = _controller(tmp_path, clock)
    controller.mark_running()
    evidence_counts = {"predictions": 7, "decisions": 7, "outcomes": 1}

    controller.pause("RUNTIME_PAUSED_NETWORK_UNAVAILABLE", detail="wifi_down")

    state = controller.snapshot()
    assert state["runtime_state"] == "PAUSED_NETWORK"
    assert state["epoch_state"] == "ACTIVE"
    assert evidence_counts == {"predictions": 7, "decisions": 7, "outcomes": 1}
    assert "INVALIDATED" not in controller.events_path.read_text(encoding="utf-8")


def test_recovery_requires_consecutive_probes_and_stabilization(tmp_path):
    clock = FakeClock()
    controller = _controller(
        tmp_path,
        clock,
        recovery_success_threshold=3,
        recovery_stabilization_seconds=30.0,
    )
    controller.mark_running()
    controller.pause("RUNTIME_PAUSED_MONGODB_UNAVAILABLE")

    assert controller.observe_recovery_probe(True) is False
    clock.advance(15)
    assert controller.observe_recovery_probe(True) is False
    clock.advance(15)
    assert controller.observe_recovery_probe(True) is True
    assert controller.runtime_state == "RUNNING"


def test_transient_probe_failure_returns_to_paused_dependency(tmp_path):
    clock = FakeClock()
    controller = _controller(tmp_path, clock, recovery_stabilization_seconds=0.0)
    controller.mark_running()
    controller.pause("RUNTIME_PAUSED_MONGODB_UNAVAILABLE")
    assert controller.observe_recovery_probe(True) is False

    assert controller.observe_recovery_probe(False, detail="flapping") is False
    assert controller.runtime_state == "PAUSED_DEPENDENCY"
    assert controller.snapshot()["consecutive_healthy_probes"] == 0


def test_clock_gap_detects_sleep_and_requires_recovery(tmp_path):
    clock = FakeClock()
    controller = _controller(
        tmp_path,
        clock,
        maximum_clock_gap_before_recovery_seconds=60.0,
    )
    controller.mark_running()
    controller.heartbeat()
    clock.advance(3600, monotonic_seconds=1)

    gap = controller.heartbeat()

    assert gap > 3500
    assert controller.runtime_state == "PAUSED_SYSTEM_SLEEP"
    assert controller.snapshot()["epoch_state"] == "ACTIVE"


def test_restart_during_outage_restores_paused_state(tmp_path):
    clock = FakeClock()
    controller = _controller(tmp_path, clock)
    controller.mark_running()
    controller.pause("RUNTIME_PAUSED_DNS_UNAVAILABLE")

    restarted = _controller(tmp_path, clock)

    assert restarted.runtime_state == "PAUSED_NETWORK"
    assert restarted.is_paused is True


def test_pause_time_is_excluded_from_coverage_age_and_missed_cycles_are_separate(tmp_path):
    clock = FakeClock()
    controller = _controller(
        tmp_path,
        clock,
        recovery_success_threshold=1,
        recovery_stabilization_seconds=0.0,
    )
    controller.mark_running()
    started = clock.wall
    clock.advance(10)
    controller.pause("RUNTIME_PAUSED_EXTERNAL_API_UNAVAILABLE")
    clock.advance(300)
    assert controller.observe_recovery_probe(True) is True
    clock.advance(10)
    controller.record_missed_cycles(4)

    assert controller.excluded_seconds_between(started, clock.wall) == 300.0
    assert controller.snapshot()["scheduled_cycle_missed_external_pause"] == 4


def test_connection_failure_is_not_confused_with_integrity_conflict():
    assert external_reason_for_exception(
        RuntimeError("MongoDB ServerSelectionTimeout")
    ) == "RUNTIME_PAUSED_MONGODB_UNAVAILABLE"
    assert external_reason_for_exception(
        RuntimeError("MongoDB canonical payload conflict")
    ) is None


def test_heartbeat_persists_every_30_seconds_on_frequent_ticks(tmp_path):
    clock = FakeClock()
    controller = _controller(tmp_path, clock)
    controller.mark_running()
    initial_mtime = controller.state_path.stat().st_mtime_ns

    # Advance 1 second at a time for 25 seconds
    for _ in range(25):
        clock.advance(1)
        controller.heartbeat()

    state_mid = controller.snapshot()
    disk_json_mid = json.loads(controller.state_path.read_text(encoding="utf-8"))
    assert state_mid.get("last_persisted_wall_heartbeat") is None
    assert disk_json_mid.get("last_persisted_wall_heartbeat") is None
    assert controller.state_path.stat().st_mtime_ns == initial_mtime

    # Advance 10 more seconds (total 35 seconds)
    for _ in range(10):
        clock.advance(1)
        controller.heartbeat()

    state_after = controller.snapshot()
    disk_json_after = json.loads(controller.state_path.read_text(encoding="utf-8"))
    assert state_after.get("last_persisted_wall_heartbeat") is not None
    assert disk_json_after.get("last_persisted_wall_heartbeat") is not None
    assert controller.state_path.stat().st_mtime_ns > initial_mtime
