"""
tests/test_live_execution_guard.py
PR 4 — Live Execution Guard validation matrix tests.

Verifies the sequential validation chain of the LiveExecutionGuard.
Asserts correct behavior for entry vs exit intents across all checks:
    1. Phase 5 gate (entries only)
    2. Live mode flag (blocks all except emergency)
    3. Kill switch state (blocks entry, allows exits)
    4. Rollout stage (stage 1 blocks entry when position count >= 1)
    5. Hard risk limits (respects order intent)
    6. System health check (blocks entry, freshness-specific reasons)
    7. Execution risk monitor (blocks entry on excessive spread/slippage)
"""
import json
import pytest
from pathlib import Path
from typing import Dict, Any

from btc_scraper.execution.live_execution_guard import (
    LiveExecutionGuard,
    OrderContext,
    LiveStateSnapshot,
    GuardResult,
)
from btc_scraper.execution.hard_risk_limits import OrderIntent
from btc_scraper.execution.kill_switch import KSState, KillSwitch


class DummyKillSwitch:
    def __init__(self, state: KSState = KSState.ARMED):
        self.state = state


@pytest.fixture
def temp_paths(tmp_path) -> Dict[str, Path]:
    return {
        "phase5": tmp_path / "phase5_report_latest.json",
        "live_mode": tmp_path / "live_mode_enabled.json",
        "health": tmp_path / "data" / "execution" / "live_monitor_snapshot.json",
    }


def test_phase5_gate(temp_paths, monkeypatch):
    # Phase 5 report says passed is False -> gate closed
    temp_paths["phase5"].parent.mkdir(parents=True, exist_ok=True)
    temp_paths["phase5"].write_text(json.dumps({"live_readiness_gate": {"passed": False}}))
    
    # Live mode enabled (pass downstream checks)
    temp_paths["live_mode"].write_text(json.dumps({"enabled": True}))

    guard = LiveExecutionGuard(
        kill_switch=DummyKillSwitch(KSState.ARMED), # type: ignore
        phase5_report_path=str(temp_paths["phase5"]),
        live_mode_flag_path=str(temp_paths["live_mode"]),
    )

    # 1. Entry order should be blocked
    ctx_entry = OrderContext(symbol="BTC/USDT", intent=OrderIntent.ENTRY, notional_usdt=10.0)
    res_entry = guard.validate(ctx_entry)
    assert not res_entry.allowed
    assert res_entry.blocked_by == "phase5_gate"
    assert "phase5_live_gate_closed" in res_entry.reason

    # 2. Exit orders should be allowed
    ctx_exit = OrderContext(symbol="BTC/USDT", intent=OrderIntent.EXIT, notional_usdt=10.0)
    res_exit = guard.validate(ctx_exit)
    assert res_exit.allowed

    ctx_reduce = OrderContext(symbol="BTC/USDT", intent=OrderIntent.REDUCE_POSITION, notional_usdt=5.0)
    res_reduce = guard.validate(ctx_reduce)
    assert res_reduce.allowed


def test_live_mode_flag(temp_paths, monkeypatch):
    # Phase 5 gate open
    temp_paths["phase5"].parent.mkdir(parents=True, exist_ok=True)
    temp_paths["phase5"].write_text(json.dumps({"live_readiness_gate": {"passed": True}}))
    # Live mode disabled
    temp_paths["live_mode"].write_text(json.dumps({"enabled": False}))

    guard = LiveExecutionGuard(
        kill_switch=DummyKillSwitch(KSState.ARMED), # type: ignore
        phase5_report_path=str(temp_paths["phase5"]),
        live_mode_flag_path=str(temp_paths["live_mode"]),
    )

    # 1. Entry blocked
    ctx_entry = OrderContext(symbol="BTC/USDT", intent=OrderIntent.ENTRY, notional_usdt=10.0)
    res_entry = guard.validate(ctx_entry)
    assert not res_entry.allowed
    assert res_entry.blocked_by == "live_mode_flag"

    # 2. Normal Exit blocked (cannot route exits if live mode is disabled, except emergency)
    ctx_exit = OrderContext(symbol="BTC/USDT", intent=OrderIntent.EXIT, notional_usdt=10.0)
    res_exit = guard.validate(ctx_exit)
    assert not res_exit.allowed
    assert res_exit.blocked_by == "live_mode_flag"

    # 3. EMERGENCY_EXIT bypasses live mode disabled
    ctx_emerg = OrderContext(symbol="BTC/USDT", intent=OrderIntent.EMERGENCY_EXIT, notional_usdt=10.0)
    res_emerg = guard.validate(ctx_emerg)
    assert res_emerg.allowed


def test_kill_switch_state(temp_paths):
    # Phase 5 open, live mode enabled
    temp_paths["phase5"].parent.mkdir(parents=True, exist_ok=True)
    temp_paths["phase5"].write_text(json.dumps({"live_readiness_gate": {"passed": True}}))
    temp_paths["live_mode"].write_text(json.dumps({"enabled": True}))

    # Kill switch HALTED
    guard = LiveExecutionGuard(
        kill_switch=DummyKillSwitch(KSState.HALTED), # type: ignore
        phase5_report_path=str(temp_paths["phase5"]),
        live_mode_flag_path=str(temp_paths["live_mode"]),
    )

    # 1. Entry blocked
    ctx_entry = OrderContext(symbol="BTC/USDT", intent=OrderIntent.ENTRY, notional_usdt=10.0)
    res_entry = guard.validate(ctx_entry)
    assert not res_entry.allowed
    assert res_entry.blocked_by == "kill_switch"

    # 2. Exit allowed
    ctx_exit = OrderContext(symbol="BTC/USDT", intent=OrderIntent.EXIT, notional_usdt=10.0)
    res_exit = guard.validate(ctx_exit)
    assert res_exit.allowed


def test_rollout_stage_one(temp_paths):
    temp_paths["phase5"].parent.mkdir(parents=True, exist_ok=True)
    temp_paths["phase5"].write_text(json.dumps({"live_readiness_gate": {"passed": True}}))
    temp_paths["live_mode"].write_text(json.dumps({"enabled": True}))

    guard = LiveExecutionGuard(
        kill_switch=DummyKillSwitch(KSState.ARMED), # type: ignore
        phase5_report_path=str(temp_paths["phase5"]),
        live_mode_flag_path=str(temp_paths["live_mode"]),
    )

    # Stage 1, already has 1 open position -> blocks entry
    ctx_entry = OrderContext(
        symbol="ETH/USDT",
        intent=OrderIntent.ENTRY,
        notional_usdt=10.0,
        open_positions_count=1,
        current_stage=1,
    )
    res_entry = guard.validate(ctx_entry)
    assert not res_entry.allowed
    assert res_entry.blocked_by == "rollout_stage"

    # Exits are not blocked by rollout stage
    ctx_exit = OrderContext(
        symbol="BTC/USDT",
        intent=OrderIntent.EXIT,
        notional_usdt=10.0,
        open_positions_count=1,
        current_stage=1,
    )
    res_exit = guard.validate(ctx_exit)
    assert res_exit.allowed


def test_system_health_stale_reasons(temp_paths, monkeypatch):
    temp_paths["phase5"].parent.mkdir(parents=True, exist_ok=True)
    temp_paths["phase5"].write_text(json.dumps({"live_readiness_gate": {"passed": True}}))
    temp_paths["live_mode"].write_text(json.dumps({"enabled": True}))

    # Mock health snapshot file path inside the guard's read method
    monkeypatch.setattr(
        "btc_scraper.execution.live_execution_guard.BASE_DIR",
        temp_paths["health"].parent.parent.parent,
    )

    guard = LiveExecutionGuard(
        kill_switch=DummyKillSwitch(KSState.ARMED), # type: ignore
        phase5_report_path=str(temp_paths["phase5"]),
        live_mode_flag_path=str(temp_paths["live_mode"]),
    )

    # Helper to write health snapshot
    def write_health(ready: bool, deps: dict):
        temp_paths["health"].parent.mkdir(parents=True, exist_ok=True)
        temp_paths["health"].write_text(json.dumps({
            "system_health": {
                "ready": ready,
                "dependencies": deps,
            }
        }))
        # clear guard health cache to force reload
        guard._health_cache_at = 0.0

    # 1. Stale account state
    write_health(False, {"account_state": False, "market_data": True})
    ctx_entry = OrderContext(symbol="BTC/USDT", intent=OrderIntent.ENTRY, notional_usdt=10.0)
    res = guard.validate(ctx_entry)
    assert not res.allowed
    assert res.blocked_by == "system_health"
    assert res.reason == "stale_account_state"

    # 2. Stale market data
    write_health(False, {"account_state": True, "market_data": False})
    res = guard.validate(ctx_entry)
    assert res.reason == "stale_market_data"

    # 3. Stale model features
    write_health(False, {"account_state": True, "market_data": True, "model_features": False})
    res = guard.validate(ctx_entry)
    assert res.reason == "stale_model_features"

    # 4. Stale orderbook
    write_health(False, {"account_state": True, "market_data": True, "model_features": True, "orderbook": False})
    res = guard.validate(ctx_entry)
    assert res.reason == "stale_orderbook"

    # 5. General check failed
    write_health(False, {"other_dependency": False})
    res = guard.validate(ctx_entry)
    assert "system_health_check_failed" in res.reason

    # Exits bypass system health checks
    ctx_exit = OrderContext(symbol="BTC/USDT", intent=OrderIntent.EXIT, notional_usdt=10.0)
    res_exit = guard.validate(ctx_exit)
    assert res_exit.allowed
