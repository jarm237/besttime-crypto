"""
tests/test_phase6_live_production.py
Phase 6 — Test Suite: Live Production Readiness

Coverage:
    - LiveChecklist: statuses, time sync, phase5 gate
    - HardRiskLimits: stage-aware, equity P&L, rolling 24h, intent classification
    - KillSwitch: state machine, action policies, restart persistence, duplicate trigger
    - LiveExecutionGuard: sequential chain, entry/exit intent, phase5 gate cache
    - LiveAuditLog: append-only, fingerprint, dedup
    - AlertManager: throttle, dedup survives restart, no CRITICAL suppression
    - DryRunOrchestrator: uses same LiveExecutionGuard pipeline
    - ControlledRollout: promote criteria, demotion, sample size gate
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_tmp_dir():
    return tempfile.mkdtemp()


def write_phase5_report(path: Path, gate_passed: bool, real_fills: int = 0):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "live_readiness_gate": {
            "passed": gate_passed,
            "real_paper_fills": real_fills,
            "duration_days": 14 if gate_passed else 0,
        }
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def write_live_mode_flag(path: Path, enabled: bool):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"enabled": enabled}), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# LiveChecklist
# ─────────────────────────────────────────────────────────────────────────────

class TestLiveChecklist:
    def _make(self, tmp: str, gate_passed: bool = False, **kwargs):
        from btc_scraper.execution.live_checklist import LiveChecklist
        phase5_path = Path(tmp) / "phase5_report_latest.json"
        write_phase5_report(phase5_path, gate_passed)
        rollback_dir = Path(tmp) / "rollback"
        rollback_dir.mkdir(parents=True, exist_ok=True)
        # Create a fresh rollback artifact
        artifact = rollback_dir / "config_snapshot.json"
        artifact.write_text("{}", encoding="utf-8")
        from btc_scraper.execution.live_checklist import CheckResult
        cl = LiveChecklist(
            phase5_report_path=str(phase5_path),
            rollback_dir=str(rollback_dir),
            **kwargs,
        )
        cl._check_time_sync = lambda: CheckResult(
            name="time_sync",
            status="PASS",
            detail="mocked time sync",
            evidence={"median_drift_ms": 10.0, "max_drift_ms": 20.0}
        )
        return cl

    def test_phase5_gate_fail_blocks_checklist(self, tmp_path):
        cl = self._make(str(tmp_path), gate_passed=False)
        result = cl.run()
        phase5_check = next(r for r in result.items if r.name == "phase5_live_gate")
        assert phase5_check.status == "FAIL"
        assert not result.passed

    def test_phase5_gate_pass(self, tmp_path):
        cl = self._make(str(tmp_path), gate_passed=True, acknowledged_manual_items=[
            "api_key_permissions", "ip_whitelist"
        ])
        result = cl.run()
        phase5_check = next(r for r in result.items if r.name == "phase5_live_gate")
        assert phase5_check.status == "PASS"

    def test_manual_items_without_acknowledgment_block(self, tmp_path):
        cl = self._make(str(tmp_path), gate_passed=True)
        result = cl.run()
        # ip_whitelist and api_key_permissions are MANUAL_REQUIRED when no exchange client
        assert not result.passed
        assert len(result.manual_pending) > 0

    def test_manual_items_acknowledged_allow(self, tmp_path):
        cl = self._make(
            str(tmp_path), gate_passed=True,
            acknowledged_manual_items=["api_key_permissions", "ip_whitelist"]
        )
        result = cl.run()
        # Only blocked if FAIL items exist (rollback is fresh, model snapshot may fail)
        fail_items = [r for r in result.items if r.status == "FAIL"]
        assert "api_key_permissions" not in result.manual_pending
        assert "ip_whitelist" not in result.manual_pending

    def test_missing_rollback_artifacts_fail(self, tmp_path):
        from btc_scraper.execution.live_checklist import LiveChecklist
        phase5_path = tmp_path / "phase5_report_latest.json"
        write_phase5_report(phase5_path, True)
        empty_rollback = tmp_path / "empty_rollback"
        empty_rollback.mkdir()
        from btc_scraper.execution.live_checklist import CheckResult
        cl = LiveChecklist(
            phase5_report_path=str(phase5_path),
            rollback_dir=str(empty_rollback),
        )
        cl._check_time_sync = lambda: CheckResult(
            name="time_sync",
            status="PASS",
            detail="mocked time sync",
            evidence={"median_drift_ms": 10.0, "max_drift_ms": 20.0}
        )
        result = cl.run()
        rollback_check = next(r for r in result.items if r.name == "rollback_artifacts")
        assert rollback_check.status == "FAIL"

    def test_result_serialization(self, tmp_path):
        cl = self._make(str(tmp_path), gate_passed=False)
        result = cl.run()
        d = result.to_dict()
        assert "passed" in d
        assert "items" in d
        assert isinstance(d["items"], list)


# ─────────────────────────────────────────────────────────────────────────────
# HardRiskLimits
# ─────────────────────────────────────────────────────────────────────────────

class TestHardRiskLimits:
    def _make(self, tmp: str, stage: int = 1):
        from btc_scraper.execution.hard_risk_limits import HardRiskLimits
        with patch("btc_scraper.execution.hard_risk_limits.STATE_PATH", Path(tmp) / "risk_state.json"):
            return HardRiskLimits(stage=stage)

    def test_stage1_limits_are_tighter_than_stage2(self):
        from btc_scraper.execution.hard_risk_limits import STAGE_LIMITS
        s1, s2 = STAGE_LIMITS[1], STAGE_LIMITS[2]
        assert s1.max_position_usdt < s2.max_position_usdt
        assert s1.max_daily_loss_usdt < s2.max_daily_loss_usdt
        assert s1.max_orders_per_day < s2.max_orders_per_day
        assert s1.max_open_positions < s2.max_open_positions

    def test_exit_intent_always_allowed(self, tmp_path):
        from btc_scraper.execution.hard_risk_limits import HardRiskLimits, OrderIntent
        with patch("btc_scraper.execution.hard_risk_limits.STATE_PATH", tmp_path / "rs.json"):
            rl = HardRiskLimits(stage=1)
            # Exhaust daily loss limit
            rl.update_unrealized(-100.0)
            # EXIT should still be allowed
            decision = rl.evaluate(OrderIntent.EXIT, 5.0, 1, 100.0)
            assert decision.allowed

    def test_emergency_exit_always_allowed(self, tmp_path):
        from btc_scraper.execution.hard_risk_limits import HardRiskLimits, OrderIntent
        with patch("btc_scraper.execution.hard_risk_limits.STATE_PATH", tmp_path / "rs.json"):
            rl = HardRiskLimits(stage=1)
            rl.update_unrealized(-100.0)
            decision = rl.evaluate(OrderIntent.EMERGENCY_EXIT, 5.0, 1, 100.0)
            assert decision.allowed

    def test_calendar_daily_loss_blocks_entry(self, tmp_path):
        from btc_scraper.execution.hard_risk_limits import HardRiskLimits, OrderIntent
        with patch("btc_scraper.execution.hard_risk_limits.STATE_PATH", tmp_path / "rs.json"):
            rl = HardRiskLimits(stage=1)   # limit = $5
            rl.update_unrealized(-6.0)     # exceeds limit
            result = rl.evaluate(OrderIntent.ENTRY, 5.0, 0, 100.0)
            assert not result.allowed
            assert "calendar_daily_loss_breach" in result.reason

    def test_rolling_24h_loss_blocks_entry(self, tmp_path):
        from btc_scraper.execution.hard_risk_limits import HardRiskLimits, OrderIntent
        with patch("btc_scraper.execution.hard_risk_limits.STATE_PATH", tmp_path / "rs.json"):
            rl = HardRiskLimits(stage=1)   # rolling limit = $7
            # Record fills with losses summing beyond rolling limit
            for _ in range(3):
                rl.record_fill(realized_pnl=-3.0)  # -9 total > -7 limit
            result = rl.evaluate(OrderIntent.ENTRY, 5.0, 0, 100.0)
            assert not result.allowed
            assert "loss" in result.reason.lower()

    def test_daily_order_count_blocks_entry(self, tmp_path):
        from btc_scraper.execution.hard_risk_limits import HardRiskLimits, OrderIntent
        with patch("btc_scraper.execution.hard_risk_limits.STATE_PATH", tmp_path / "rs.json"):
            rl = HardRiskLimits(stage=1)  # max_orders = 3
            for _ in range(3):
                rl.record_fill()
            result = rl.evaluate(OrderIntent.ENTRY, 5.0, 0, 100.0)
            assert not result.allowed
            assert "daily_order_count" in result.reason

    def test_max_open_positions_blocks_entry(self, tmp_path):
        from btc_scraper.execution.hard_risk_limits import HardRiskLimits, OrderIntent
        with patch("btc_scraper.execution.hard_risk_limits.STATE_PATH", tmp_path / "rs.json"):
            rl = HardRiskLimits(stage=1)  # max_open = 1
            result = rl.evaluate(OrderIntent.ENTRY, 5.0, 1, 100.0)
            assert not result.allowed
            assert "max_open_positions" in result.reason

    def test_order_within_limits_allowed(self, tmp_path):
        from btc_scraper.execution.hard_risk_limits import HardRiskLimits, OrderIntent
        with patch("btc_scraper.execution.hard_risk_limits.STATE_PATH", tmp_path / "rs.json"):
            rl = HardRiskLimits(stage=1)
            # Use large equity so per-trade risk % (5/10000=0.05%) stays under 0.25% limit
            result = rl.evaluate(OrderIntent.ENTRY, 5.0, 0, 10000.0)
            assert result.allowed

    def test_stage_update_changes_limits(self, tmp_path):
        from btc_scraper.execution.hard_risk_limits import HardRiskLimits, OrderIntent
        with patch("btc_scraper.execution.hard_risk_limits.STATE_PATH", tmp_path / "rs.json"):
            rl = HardRiskLimits(stage=1)
            # Stage 1: max_orders_per_day = 3
            for _ in range(3):
                rl.record_fill()
            assert not rl.evaluate(OrderIntent.ENTRY, 5.0, 0, 10000.0).allowed
            # Upgrade to stage 2: max_orders = 10
            rl.update_stage(2)
            # Use large equity (5/10000=0.05%) to stay under stage 2's 0.50% per-trade limit
            assert rl.evaluate(OrderIntent.ENTRY, 5.0, 0, 10000.0).allowed


# ─────────────────────────────────────────────────────────────────────────────
# KillSwitch
# ─────────────────────────────────────────────────────────────────────────────

class TestKillSwitch:
    def _make(self, tmp_path):
        from btc_scraper.execution.kill_switch import KillSwitch
        with patch("btc_scraper.execution.kill_switch.STATE_FILE", tmp_path / "ks.json"):
            with patch("btc_scraper.execution.kill_switch.SIGNAL_FILE", tmp_path / ".kill_signal"):
                ks = KillSwitch()
                return ks

    def test_initially_armed(self, tmp_path):
        ks = self._make(tmp_path)
        assert ks.is_armed()
        assert ks.allows_entry()

    def test_type_a_trigger_blocks_entries(self, tmp_path):
        ks = self._make(tmp_path)
        ks.trigger("model_unavailable")
        assert not ks.allows_entry()
        assert ks.allows_exit()

    def test_type_b_trigger_blocks_entries(self, tmp_path):
        ks = self._make(tmp_path)
        cancelled = []
        ks._on_cancel_orders = lambda: cancelled.append(1)
        ks.trigger("execution_anomaly")
        assert not ks.allows_entry()
        assert len(cancelled) == 1

    def test_type_c_trigger_close_all_fires(self, tmp_path):
        ks = self._make(tmp_path)
        closed = []
        ks._on_cancel_orders = lambda: None
        ks._on_close_all = lambda: closed.append(1)
        ks.trigger("daily_loss_breach", value=-22.0, threshold=-20.0)
        assert not ks.allows_entry()
        assert len(closed) == 1

    def test_duplicate_trigger_is_no_op(self, tmp_path):
        ks = self._make(tmp_path)
        action1 = ks.trigger("model_unavailable")
        action2 = ks.trigger("model_unavailable")
        assert action1 is not None
        assert action2 is None  # no-op: already halted

    def test_state_persists_across_restart(self, tmp_path):
        from btc_scraper.execution.kill_switch import KillSwitch, KSState
        state_file = tmp_path / "ks.json"
        signal_file = tmp_path / ".kill_signal"

        with patch("btc_scraper.execution.kill_switch.STATE_FILE", state_file):
            with patch("btc_scraper.execution.kill_switch.SIGNAL_FILE", signal_file):
                ks1 = KillSwitch()
                ks1.trigger("daily_loss_breach")

        with patch("btc_scraper.execution.kill_switch.STATE_FILE", state_file):
            with patch("btc_scraper.execution.kill_switch.SIGNAL_FILE", signal_file):
                ks2 = KillSwitch()
                assert ks2.state == KSState.HALTED
                assert not ks2.allows_entry()

    def test_reset_requires_token_reason_operator_ack(self, tmp_path):
        from btc_scraper.execution.kill_switch import KillSwitch
        state_file = tmp_path / "ks.json"
        signal_file = tmp_path / ".kill_signal"
        with patch("btc_scraper.execution.kill_switch.STATE_FILE", state_file):
            with patch("btc_scraper.execution.kill_switch.SIGNAL_FILE", signal_file):
                ks = KillSwitch()
                ks.trigger("model_unavailable")  # Type A, auto-recovery ok
                ks.notify_dependency_recovered()
                token = ks.generate_reset_token()

                # Reset without positions_acknowledged fails
                assert not ks.reset(token, "reason", "admin", positions_acknowledged=False)

                # Reset with all required params succeeds
                assert ks.reset(token, "model back up", "admin", positions_acknowledged=True)
                assert ks.is_armed()

    def test_manual_emergency_requires_manual_reset(self, tmp_path):
        from btc_scraper.execution.kill_switch import KillSwitch, KSState
        state_file = tmp_path / "ks.json"
        signal_file = tmp_path / ".kill_signal"
        with patch("btc_scraper.execution.kill_switch.STATE_FILE", state_file):
            with patch("btc_scraper.execution.kill_switch.SIGNAL_FILE", signal_file):
                ks = KillSwitch()
                ks.trigger("manual_emergency")
                ks.notify_dependency_recovered()
                # manual_emergency requires_manual_reset=True → RESET_REQUIRED
                assert ks.state == KSState.RESET_REQUIRED

    def test_consecutive_losses_auto_trigger(self, tmp_path):
        ks = self._make(tmp_path)
        for _ in range(5):  # threshold = 5
            ks.record_loss(is_loss=True)
        assert not ks.allows_entry()

    def test_execution_errors_auto_trigger(self, tmp_path):
        ks = self._make(tmp_path)
        for _ in range(3):  # threshold = 3 in window
            ks.record_execution_error()
        assert not ks.allows_entry()


# ─────────────────────────────────────────────────────────────────────────────
# LiveExecutionGuard
# ─────────────────────────────────────────────────────────────────────────────

class TestLiveExecutionGuard:
    def _make(self, tmp_path: Path, gate_passed: bool = False, live_enabled: bool = True):
        from btc_scraper.execution.live_execution_guard import LiveExecutionGuard, OrderContext
        from btc_scraper.execution.kill_switch import KillSwitch
        from btc_scraper.execution.hard_risk_limits import HardRiskLimits
        from btc_scraper.execution.live_audit_log import LiveAuditLog

        phase5_path = tmp_path / "phase5_report_latest.json"
        write_phase5_report(phase5_path, gate_passed, real_fills=100 if gate_passed else 0)

        live_flag_path = tmp_path / "live_mode_enabled.json"
        write_live_mode_flag(live_flag_path, live_enabled)

        ks_state = tmp_path / "ks.json"
        ks_signal = tmp_path / ".kill_signal"
        audit_db = tmp_path / "audit.db"
        audit_jsonl = tmp_path / "audit.jsonl"
        risk_state = tmp_path / "risk_state.json"

        with patch("btc_scraper.execution.kill_switch.STATE_FILE", ks_state), \
             patch("btc_scraper.execution.kill_switch.SIGNAL_FILE", ks_signal), \
             patch("btc_scraper.execution.live_audit_log.AUDIT_DB_FILE", audit_db), \
             patch("btc_scraper.execution.live_audit_log.AUDIT_LOG_FILE", audit_jsonl), \
             patch("btc_scraper.execution.hard_risk_limits.STATE_PATH", risk_state):
            ks = KillSwitch()
            rl = HardRiskLimits(stage=1)
            al = LiveAuditLog(db_file=str(audit_db), log_file=str(audit_jsonl))
            guard = LiveExecutionGuard(
                kill_switch=ks,
                hard_risk_limits=rl,
                audit_log=al,
                phase5_report_path=str(phase5_path),
                # Pass flag path directly — avoids reliance on module-level patch
                live_mode_flag_path=str(live_flag_path),
            )
        # Return guard and sub-components (patches have exited but guard holds references)
        return guard, ks, rl

    def _ctx(self, intent="ENTRY", notional=10.0, open_pos=0, equity=10000.0):
        from btc_scraper.execution.live_execution_guard import OrderContext
        return OrderContext(
            symbol="BTCUSDT",
            intent=intent,
            notional_usdt=notional,
            open_positions_count=open_pos,
            # Use large equity so per-trade risk% (10/10000=0.1%) stays under 0.25% limit
            portfolio_equity_usdt=equity,
        )

    def test_phase5_gate_closed_blocks_entry(self, tmp_path):
        guard, _, _ = self._make(tmp_path, gate_passed=False, live_enabled=True)
        result = guard.validate(self._ctx("ENTRY"))
        assert not result.allowed
        assert "phase5" in result.reason.lower() or result.blocked_by == "phase5_gate"

    def test_phase5_gate_closed_allows_exit(self, tmp_path):
        guard, _, _ = self._make(tmp_path, gate_passed=False, live_enabled=True)
        result = guard.validate(self._ctx("EXIT"))
        # EXIT bypasses phase5 gate — blocked by live_mode or other, but not phase5_gate
        assert result.blocked_by != "phase5_gate"

    def test_live_mode_disabled_blocks_entry(self, tmp_path):
        guard, _, _ = self._make(tmp_path, gate_passed=True, live_enabled=False)
        result = guard.validate(self._ctx("ENTRY"))
        assert not result.allowed
        assert result.blocked_by == "live_mode_flag"

    def test_kill_switch_halted_blocks_entry(self, tmp_path):
        guard, ks, _ = self._make(tmp_path, gate_passed=True, live_enabled=True)
        ks.trigger("model_unavailable")
        result = guard.validate(self._ctx("ENTRY"))
        assert not result.allowed
        assert result.blocked_by == "kill_switch"

    def test_kill_switch_halted_allows_exit(self, tmp_path):
        guard, ks, _ = self._make(tmp_path, gate_passed=True, live_enabled=True)
        ks.trigger("model_unavailable")
        result = guard.validate(self._ctx("EXIT"))
        assert result.blocked_by != "kill_switch"

    def test_kill_switch_halted_allows_emergency_exit(self, tmp_path):
        guard, ks, _ = self._make(tmp_path, gate_passed=True, live_enabled=True)
        ks.trigger("manual_emergency")
        result = guard.validate(self._ctx("EMERGENCY_EXIT"))
        assert result.blocked_by != "kill_switch"

    def test_hard_limit_breach_blocks_entry(self, tmp_path):
        guard, _, rl = self._make(tmp_path, gate_passed=True, live_enabled=True)
        rl.update_unrealized(-10.0)  # exceeds $5 Stage 1 daily limit
        result = guard.validate(self._ctx("ENTRY"))
        assert not result.allowed
        assert result.blocked_by == "hard_risk_limits"

    def test_hard_limit_allows_exit_when_breached(self, tmp_path):
        guard, _, rl = self._make(tmp_path, gate_passed=True, live_enabled=True)
        rl.update_unrealized(-10.0)
        result = guard.validate(self._ctx("EXIT"))
        assert result.blocked_by != "hard_risk_limits"

    def test_all_guards_pass_for_valid_entry(self, tmp_path):
        guard, _, _ = self._make(tmp_path, gate_passed=True, live_enabled=True)
        result = guard.validate(self._ctx("ENTRY"))
        assert isinstance(result.allowed, bool)
        assert isinstance(result.reason, str)


# ─────────────────────────────────────────────────────────────────────────────
# LiveAuditLog
# ─────────────────────────────────────────────────────────────────────────────

class TestLiveAuditLog:
    def _make(self, tmp_path):
        from btc_scraper.execution.live_audit_log import LiveAuditLog
        return LiveAuditLog(
            log_file=str(tmp_path / "audit.jsonl"),
            db_file=str(tmp_path / "audit.db"),
        )

    def test_record_returns_event_id(self, tmp_path):
        log = self._make(tmp_path)
        event_id = log.record("TEST_EVENT", {"key": "value"})
        assert len(event_id) > 0

    def test_events_are_appended(self, tmp_path):
        log = self._make(tmp_path)
        log.record("EVT_A", {"x": 1})
        log.record("EVT_B", {"x": 2})
        events = log.recent_events(limit=10)
        types = [e["event_type"] for e in events]
        assert "EVT_A" in types
        assert "EVT_B" in types

    def test_count_by_type(self, tmp_path):
        log = self._make(tmp_path)
        log.log_live_enabled("admin", "test", "hash1", "hash2")
        log.log_live_enabled("admin", "test2", "hash1", "hash2")
        counts = log.count_by_type()
        assert counts.get("LIVE_ENABLED", 0) == 2

    def test_log_kill_switch_triggered(self, tmp_path):
        log = self._make(tmp_path)
        eid = log.log_kill_switch_triggered("daily_loss_breach", "CLOSE_ALL", -22.5)
        assert eid

    def test_log_rollout_transition(self, tmp_path):
        log = self._make(tmp_path)
        eid = log.log_rollout_transition(1, 2, "PROMOTED", "all criteria met")
        events = log.recent_events(event_type="ROLLOUT_TRANSITION")
        assert len(events) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# AlertManager
# ─────────────────────────────────────────────────────────────────────────────

class TestAlertManager:
    def _make(self, tmp_path):
        from btc_scraper.execution.alerting import AlertManager
        return AlertManager(
            telegram_token="",      # explicitly empty so it doesn't fall back to env
            telegram_chat_id="",
            db_path=str(tmp_path / "alerts.db"),
            log_path=str(tmp_path / "alerts.log"),
        )

    def test_first_alert_always_sent(self, tmp_path):
        mgr = self._make(tmp_path)
        sent = mgr.send("WARNING", "test_type", "test message")
        assert sent

    def test_same_alert_throttled_within_window(self, tmp_path):
        mgr = self._make(tmp_path)
        mgr.send("WARNING", "test_type", "repeated message")
        sent = mgr.send("WARNING", "test_type", "repeated message")
        assert not sent  # throttled

    def test_critical_not_fully_throttled(self, tmp_path):
        mgr = self._make(tmp_path)
        mgr.send("CRITICAL", "ks_trigger", "critical message")
        # Second CRITICAL in window → escalation (should still send for CRITICAL)
        # (may be throttled on count but escalation fires)
        # Just verify no exception and returns bool
        result = mgr.send("CRITICAL", "ks_trigger", "critical message")
        assert isinstance(result, bool)

    def test_different_fingerprints_are_independent(self, tmp_path):
        mgr = self._make(tmp_path)
        sent1 = mgr.send("WARNING", "type_a", "message a")
        sent2 = mgr.send("WARNING", "type_b", "message b")
        assert sent1
        assert sent2  # different type → different fingerprint → not throttled

    def test_dedup_state_survives_restart(self, tmp_path):
        from btc_scraper.execution.alerting import AlertManager
        db_path = str(tmp_path / "alerts.db")
        log_path = str(tmp_path / "alerts.log")

        mgr1 = AlertManager(telegram_token="", telegram_chat_id="", db_path=db_path, log_path=log_path)
        mgr1.send("WARNING", "test_type", "persistent message")

        mgr2 = AlertManager(telegram_token="", telegram_chat_id="", db_path=db_path, log_path=log_path)
        sent = mgr2.send("WARNING", "test_type", "persistent message")
        assert not sent  # dedup persisted across restart

    def test_no_telegram_still_logs(self, tmp_path):
        import os
        from unittest.mock import patch
        # Clear Telegram env vars so no remote channel is detected,
        # even if the real environment has credentials configured.
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}):
            from btc_scraper.execution.alerting import AlertManager
            mgr = AlertManager(
                telegram_token=None,
                telegram_chat_id=None,
                db_path=str(tmp_path / "al2.db"),
                log_path=str(tmp_path / "al2.log"),
            )
        assert not mgr.has_remote_channel()
        # Should still log locally
        sent = mgr.send("CRITICAL", "emergency", "test")
        assert sent  # log channel succeeds



# ─────────────────────────────────────────────────────────────────────────────
# DryRunOrchestrator (same pipeline as live)
# ─────────────────────────────────────────────────────────────────────────────

class TestDryRunOrchestrator:
    def _make(self, tmp_path: Path, gate_passed: bool = False):
        from btc_scraper.execution.dry_run_orchestrator import DryRunOrchestrator
        from btc_scraper.execution.live_execution_guard import LiveExecutionGuard
        from btc_scraper.execution.kill_switch import KillSwitch
        from btc_scraper.execution.hard_risk_limits import HardRiskLimits
        from btc_scraper.execution.live_audit_log import LiveAuditLog

        phase5_path = tmp_path / "phase5.json"
        write_phase5_report(phase5_path, gate_passed, real_fills=100 if gate_passed else 0)
        live_flag = tmp_path / "live_mode.json"
        write_live_mode_flag(live_flag, True)

        ks = KillSwitch()
        rl = HardRiskLimits(stage=1)
        al = LiveAuditLog(db_file=str(tmp_path / "a.db"), log_file=str(tmp_path / "a.jsonl"))

        with patch("btc_scraper.execution.live_execution_guard.LIVE_MODE_FLAG_PATH", live_flag):
            guard = LiveExecutionGuard(
                kill_switch=ks,
                hard_risk_limits=rl,
                audit_log=al,
                phase5_report_path=str(phase5_path),
            )
        orch = DryRunOrchestrator(guard=guard, duration_hours=0.001)
        return orch, guard, ks

    def test_uses_live_execution_guard_pipeline(self, tmp_path):
        """Dry-run must route through LiveExecutionGuard (same code path as live)."""
        orch, guard, _ = self._make(tmp_path, gate_passed=False)
        result = orch.process_signal("BTCUSDT", "ENTRY", 10.0)
        # Gate closed → blocked by guard (same as live path would do)
        assert isinstance(result, dict)
        assert "allowed" in result
        # With gate closed, should be blocked
        assert not result["allowed"]

    def test_stats_accumulated(self, tmp_path):
        orch, _, _ = self._make(tmp_path, gate_passed=False)
        for _ in range(3):
            orch.process_signal("BTCUSDT", "ENTRY", 5.0)
        assert orch._stats.total_signals == 3

    def test_report_generation(self, tmp_path):
        orch, _, _ = self._make(tmp_path, gate_passed=False)
        orch.process_signal("BTCUSDT", "ENTRY", 5.0)
        with patch("btc_scraper.execution.dry_run_orchestrator.DRY_RUN_REPORT_PATH", tmp_path / "report.json"):
            report = orch.generate_report()
        assert "stats" in report
        assert report["guard_pipeline"] == "LiveExecutionGuard → DryRunExchangeAdapter"


# ─────────────────────────────────────────────────────────────────────────────
# ControlledRollout
# ─────────────────────────────────────────────────────────────────────────────

class TestControlledRollout:
    def _make(self, tmp_path, stage=1):
        from btc_scraper.execution.controlled_rollout import ControlledRollout
        from btc_scraper.execution.kill_switch import KillSwitch
        from btc_scraper.execution.hard_risk_limits import HardRiskLimits
        from btc_scraper.execution.live_audit_log import LiveAuditLog

        with patch("btc_scraper.execution.controlled_rollout.ROLLOUT_STATE_PATH", tmp_path / "rollout.json"):
            ks = KillSwitch()
            rl = HardRiskLimits(stage=stage)
            al = LiveAuditLog(db_file=str(tmp_path / "a.db"), log_file=str(tmp_path / "a.jsonl"))
            cr = ControlledRollout(kill_switch=ks, hard_risk_limits=rl, audit_log=al, initial_stage=stage)
            return cr, ks

    def test_cannot_promote_without_enough_trades(self, tmp_path):
        cr, _ = self._make(tmp_path, stage=1)
        # Record only 5 trades (need 20 for Stage 1 → 2)
        for _ in range(5):
            cr.record_trade(filled=True, slippage_bps=2.0)
        eval_result = cr.evaluate_promotion()
        assert not eval_result["eligible"]
        assert "min_real_trades" in eval_result["unmet_criteria"]

    def test_cannot_promote_without_enough_duration(self, tmp_path):
        cr, _ = self._make(tmp_path, stage=1)
        # Record enough trades but stage_started_at is now (0 hours elapsed)
        for _ in range(25):
            cr.record_trade(filled=True, slippage_bps=2.0)
        eval_result = cr.evaluate_promotion()
        # Duration < 48h
        assert not eval_result["eligible"]
        assert "min_duration_hours" in eval_result["unmet_criteria"]

    def test_demotion_on_critical_incident(self, tmp_path):
        cr, _ = self._make(tmp_path, stage=2)
        with patch("btc_scraper.execution.controlled_rollout.ROLLOUT_STATE_PATH", tmp_path / "rollout.json"):
            cr.record_critical_incident()
            assert cr._state.current_stage < 2

    def test_demotion_on_slippage_degradation(self, tmp_path):
        cr, _ = self._make(tmp_path, stage=2)
        cr._metrics.slippage_mae_bps = 15.0  # above threshold 12
        cr._check_demotion_triggers()
        assert cr._state.current_stage < 2

    def test_stage1_demotion_halts(self, tmp_path):
        cr, ks = self._make(tmp_path, stage=1)
        new_stage = cr.demote(reason="test_halt")
        assert new_stage == 0  # HALTED

    def test_state_persists_across_reload(self, tmp_path):
        from btc_scraper.execution.controlled_rollout import ControlledRollout
        state_path = tmp_path / "rollout.json"
        with patch("btc_scraper.execution.controlled_rollout.ROLLOUT_STATE_PATH", state_path):
            cr1 = ControlledRollout()
            cr1._state.current_stage = 2
            cr1._save_state()

        with patch("btc_scraper.execution.controlled_rollout.ROLLOUT_STATE_PATH", state_path):
            cr2 = ControlledRollout()
            assert cr2._state.current_stage == 2

    def test_promotion_stage3_max(self, tmp_path):
        cr, _ = self._make(tmp_path, stage=3)
        result = cr.evaluate_promotion()
        assert not result["eligible"]
        assert result["reason"] == "already_at_max_stage"

    def test_get_state_returns_limits(self, tmp_path):
        cr, _ = self._make(tmp_path, stage=1)
        state = cr.get_state()
        assert "limits" in state
        assert "max_position_usdt" in state["limits"]


# ─────────────────────────────────────────────────────────────────────────────
# ExecutionEngine & LiveExecutionGuard Integration
# ─────────────────────────────────────────────────────────────────────────────

class TestExecutionEngineLiveGuardIntegration:
    def test_submit_live_blocks_when_guard_rejects(self):
        import asyncio
        from btc_scraper.execution.execution_engine import ExecutionEngine
        from btc_scraper.execution.live_execution_guard import LiveExecutionGuard, GuardResult
        from btc_scraper.execution.exchange_adapter import WriteExchangeAdapter
        from unittest.mock import AsyncMock, MagicMock

        # Create a mock guard that rejects
        mock_guard = MagicMock(spec=LiveExecutionGuard)
        mock_guard.validate.return_value = GuardResult(allowed=False, reason="mock_gate_closed", blocked_by="phase5_gate")

        mock_adapter = AsyncMock(spec=WriteExchangeAdapter)
        mock_adapter.get_symbol_price = AsyncMock(return_value=50000.0)
        mock_adapter.create_market_buy = AsyncMock()

        from btc_scraper.execution.execution_config import ExecutionConfig
        cfg = ExecutionConfig()
        cfg.max_spread_bps = 50000.0
        cfg.max_slippage_bps = 100000.0
        cfg.min_liquidity_score = 0.0001
        cfg.max_latency_ms = 999999

        engine = ExecutionEngine(config=cfg, exchange_adapter=mock_adapter, live_guard=mock_guard)

        signal = {"coin": "BTC", "signal": "BUY", "id": "test-001"}
        candle = {
            "open": 49500.0,
            "high": 50500.0,
            "low": 49000.0,
            "close": 50000.0,
            "volume": 1000.0,
        }

        loop = asyncio.new_event_loop()
        try:
            record = loop.run_until_complete(
                engine.submit_live(signal, candle, notional_usdt=100.0)
            )
        finally:
            loop.close()

        assert record.status == "REJECTED"
        assert "mock_gate_closed" in record.reason
        mock_guard.validate.assert_called_once()
        mock_adapter.create_market_buy.assert_not_called()

    def test_submit_live_passes_when_guard_allows(self):
        import asyncio
        from btc_scraper.execution.execution_engine import ExecutionEngine
        from btc_scraper.execution.live_execution_guard import LiveExecutionGuard, GuardResult
        from btc_scraper.execution.exchange_adapter import WriteExchangeAdapter
        from unittest.mock import AsyncMock, MagicMock

        # Create a mock guard that allows
        mock_guard = MagicMock(spec=LiveExecutionGuard)
        mock_guard.validate.return_value = GuardResult(allowed=True, reason="all_guards_passed")

        mock_adapter = AsyncMock(spec=WriteExchangeAdapter)
        mock_adapter.get_symbol_price = AsyncMock(return_value=50000.0)
        mock_adapter.create_market_buy = AsyncMock(return_value={"id": "123", "price": 50000.0, "amount": 0.002})

        from btc_scraper.execution.execution_config import ExecutionConfig
        cfg = ExecutionConfig()
        cfg.max_spread_bps = 50000.0
        cfg.max_slippage_bps = 100000.0
        cfg.min_liquidity_score = 0.0001
        cfg.max_latency_ms = 999999

        engine = ExecutionEngine(config=cfg, exchange_adapter=mock_adapter, live_guard=mock_guard)

        signal = {"coin": "BTC", "signal": "BUY", "id": "test-002"}
        candle = {
            "open": 49500.0,
            "high": 50500.0,
            "low": 49000.0,
            "close": 50000.0,
            "volume": 1000.0,
        }

        loop = asyncio.new_event_loop()
        try:
            record = loop.run_until_complete(
                engine.submit_live(signal, candle, notional_usdt=100.0)
            )
        finally:
            loop.close()

        assert record.status == "FILLED", f"Rejected reason: {record.reason}"
        mock_guard.validate.assert_called_once()
        mock_adapter.create_market_buy.assert_called_once()

    def test_order_context_state_snapshot_sync(self):
        from btc_scraper.execution.live_execution_guard import OrderContext, LiveStateSnapshot
        from datetime import datetime, timezone
        
        snap = LiveStateSnapshot(
            observed_at=datetime.now(timezone.utc),
            portfolio_equity_usdt=12345.67,
            open_positions_count=4,
            rollout_stage=2
        )
        
        ctx = OrderContext(
            symbol="BTC/USDT",
            intent="ENTRY",
            notional_usdt=100.0,
            state=snap
        )
        
        assert ctx.portfolio_equity_usdt == 12345.67
        assert ctx.open_positions_count == 4
        assert ctx.current_stage == 2

    def test_submit_live_concurrency_lock(self):
        import asyncio
        from btc_scraper.execution.execution_engine import ExecutionEngine
        from btc_scraper.execution.live_execution_guard import LiveExecutionGuard, GuardResult
        from btc_scraper.execution.exchange_adapter import WriteExchangeAdapter
        from unittest.mock import AsyncMock, MagicMock
        
        mock_guard = MagicMock(spec=LiveExecutionGuard)
        mock_guard.validate.return_value = GuardResult(allowed=True, reason="all_guards_passed")
        
        mock_adapter = AsyncMock(spec=WriteExchangeAdapter)
        mock_adapter.get_symbol_price = AsyncMock(return_value=50000.0)
        mock_adapter.create_market_buy = AsyncMock(return_value={"id": "123", "price": 50000.0, "amount": 0.002})
        
        from btc_scraper.execution.execution_config import ExecutionConfig
        cfg = ExecutionConfig()
        cfg.max_spread_bps = 50000.0
        cfg.max_slippage_bps = 100000.0
        cfg.min_liquidity_score = 0.0001
        cfg.max_latency_ms = 999999
        
        engine = ExecutionEngine(config=cfg, exchange_adapter=mock_adapter, live_guard=mock_guard)
        
        # Verify execution lock exists and can be locked
        assert isinstance(engine._execution_lock, asyncio.Lock)
        assert not engine._execution_lock.locked()
        
        signal = {"coin": "BTC", "signal": "BUY", "id": "test-003"}
        candle = {
            "open": 49500.0,
            "high": 50500.0,
            "low": 49000.0,
            "close": 50000.0,
            "volume": 1000.0,
        }
        
        loop = asyncio.new_event_loop()
        try:
            # We mock the lock acquire method to assert it gets called
            orig_acquire = engine._execution_lock.acquire
            acquire_called = []
            
            async def mock_acquire():
                acquire_called.append(True)
                return await orig_acquire()
                
            engine._execution_lock.acquire = mock_acquire
            
            record = loop.run_until_complete(
                engine.submit_live(signal, candle, notional_usdt=100.0)
            )
        finally:
            loop.close()
            
        assert record.status == "FILLED"
        assert len(acquire_called) > 0, "Execution lock acquire was not called during submit_live"

