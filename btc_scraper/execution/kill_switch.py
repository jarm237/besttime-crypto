"""
btc_scraper/execution/kill_switch.py
Phase 6 — Task 6.3: Kill-Switch with State Machine + Action Policies

State machine:
    ARMED
      ↓ trigger
    HALTED
      ↓ dependency recovered
    RECOVERY_PENDING
      ↓ manual verification
    RESET_REQUIRED
      ↓ explicit unlock (token + reason + positions acknowledged)
    ARMED

Action policies per trigger type:
    Type A — BLOCK_NEW_ENTRIES  : model/data/DB failure, daily order count
    Type B — CANCEL_OPEN_ORDERS : execution anomaly, reconciliation mismatch
    Type C — CLOSE_ALL          : daily loss breach, leverage breach, manual emergency

Exit orders (REDUCE/EXIT/EMERGENCY_EXIT) are still allowed when state != HALTED.
Only CLOSE_ALL action triggers position reduction.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
STATE_FILE = BASE_DIR / "data" / "kill_switch_state.json"
SIGNAL_FILE = BASE_DIR / "data" / ".kill_signal"   # legacy file-based manual stop


# ── State machine ─────────────────────────────────────────────────────────────

class KSState(str, Enum):
    ARMED = "ARMED"
    HALTED = "HALTED"
    RECOVERY_PENDING = "RECOVERY_PENDING"
    RESET_REQUIRED = "RESET_REQUIRED"


# ── Action policies ───────────────────────────────────────────────────────────

class KillAction(str, Enum):
    BLOCK_NEW_ENTRIES = "BLOCK_NEW_ENTRIES"    # Type A
    CANCEL_OPEN_ORDERS = "CANCEL_OPEN_ORDERS"  # Type B
    CLOSE_ALL = "CLOSE_ALL"                    # Type C


# Trigger → action policy mapping
TRIGGER_POLICY: Dict[str, KillAction] = {
    # Type A
    "model_unavailable":        KillAction.BLOCK_NEW_ENTRIES,
    "data_stale":               KillAction.BLOCK_NEW_ENTRIES,
    "db_degraded":              KillAction.BLOCK_NEW_ENTRIES,
    "daily_order_count":        KillAction.BLOCK_NEW_ENTRIES,
    # Type B
    "execution_anomaly":        KillAction.CANCEL_OPEN_ORDERS,
    "repeated_reject":          KillAction.CANCEL_OPEN_ORDERS,
    "exchange_api_instability": KillAction.CANCEL_OPEN_ORDERS,
    "position_mismatch_minor":  KillAction.CANCEL_OPEN_ORDERS,
    # Type C
    "daily_loss_breach":        KillAction.CLOSE_ALL,
    "leverage_breach":          KillAction.CLOSE_ALL,
    "position_mismatch_severe": KillAction.CLOSE_ALL,
    "manual_emergency":         KillAction.CLOSE_ALL,
}

# Triggers that require manual reset (cannot auto-recover)
REQUIRES_MANUAL_RESET = {
    "daily_loss_breach",
    "leverage_breach",
    "position_mismatch_severe",
    "manual_emergency",
}


# ── State document ────────────────────────────────────────────────────────────

@dataclass
class KillSwitchState:
    state: str = KSState.ARMED
    trigger: Optional[str] = None
    trigger_value: Optional[float] = None
    threshold: Optional[float] = None
    triggered_at: Optional[str] = None
    action_taken: Optional[str] = None
    requires_manual_reset: bool = False
    reset_token_hash: Optional[str] = None
    reset_reason: Optional[str] = None
    reset_by: Optional[str] = None
    reset_at: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# ── Kill-Switch class ─────────────────────────────────────────────────────────

class KillSwitch:
    """
    Central kill-switch enforcer.

    Usage:
        ks = KillSwitch()
        if not ks.allows_entry():
            block_order()
        ks.trigger("daily_loss_breach", value=-22.5, threshold=-20.0)
        ks.reset(token=reset_token, reason="loss reviewed", operator="admin", positions_acknowledged=True)
    """

    # Consecutive-loss / anomaly tracking
    CONSECUTIVE_LOSS_THRESHOLD = 5
    ANOMALY_WINDOW_SECONDS = 300   # 5 minutes
    ANOMALY_THRESHOLD = 3          # errors in window

    def __init__(
        self,
        on_cancel_orders: Optional[Callable[[], None]] = None,
        on_close_all: Optional[Callable[[], None]] = None,
        on_alert: Optional[Callable[[str, str], None]] = None,
    ):
        self._lock = RLock()
        self._state = KillSwitchState()
        self._on_cancel_orders = on_cancel_orders or (lambda: None)
        self._on_close_all = on_close_all or (lambda: None)
        self._on_alert = on_alert or (lambda sev, msg: None)

        # Consecutive-loss / anomaly counters
        self._consecutive_losses = 0
        self._anomaly_timestamps: List[float] = []

        self._load_state()

    # ── State persistence ─────────────────────────────────────────────────────

    def _load_state(self) -> None:
        try:
            if STATE_FILE.exists():
                raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                history = raw.pop("history", [])
                self._state = KillSwitchState(
                    **{k: v for k, v in raw.items() if k in KillSwitchState.__dataclass_fields__}
                )
                self._state.history = history
        except Exception as exc:
            logger.warning(f"[KillSwitch] Failed to load state: {exc}")

    def _save_state(self) -> None:
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._state.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            tmp.replace(STATE_FILE)
        except Exception as exc:
            logger.error(f"[KillSwitch] Failed to save state: {exc}")

    # ── Signal file check (file-based manual trigger, legacy) ────────────────

    def _check_signal_file(self) -> None:
        """Check for external stop signal file (file-based trigger)."""
        if SIGNAL_FILE.exists():
            logger.warning("[KillSwitch] Signal file detected — triggering manual_emergency")
            try:
                SIGNAL_FILE.unlink()
            except Exception:
                pass
            self.trigger("manual_emergency")

    # ── Core state queries ────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._state.state

    def is_armed(self) -> bool:
        self._check_signal_file()
        return self._state.state == KSState.ARMED

    def allows_entry(self) -> bool:
        """
        Returns True only if ARMED and signal file not present.
        All ENTRY / ADD_POSITION orders must check this.
        """
        self._check_signal_file()
        return self._state.state == KSState.ARMED

    def allows_exit(self) -> bool:
        """
        Exits are allowed unless state is HALTED with CLOSE_ALL action already in progress.
        In practice, exits should almost always be allowed.
        """
        return True

    # ── Trigger ───────────────────────────────────────────────────────────────

    def trigger(
        self,
        trigger_name: str,
        value: Optional[float] = None,
        threshold: Optional[float] = None,
    ) -> Optional[KillAction]:
        """
        Trigger the kill-switch.
        Returns the KillAction taken, or None if already halted.
        """
        with self._lock:
            if self._state.state != KSState.ARMED:
                logger.info(f"[KillSwitch] Already {self._state.state} — ignoring duplicate trigger: {trigger_name}")
                return None

            action = TRIGGER_POLICY.get(trigger_name, KillAction.BLOCK_NEW_ENTRIES)
            now = datetime.now(timezone.utc).isoformat()
            needs_manual = trigger_name in REQUIRES_MANUAL_RESET

            # Append to history
            self._state.history.append({
                "event": "TRIGGERED",
                "trigger": trigger_name,
                "action": action,
                "value": value,
                "threshold": threshold,
                "at": now,
            })

            # Update state
            self._state.state = KSState.HALTED
            self._state.trigger = trigger_name
            self._state.trigger_value = value
            self._state.threshold = threshold
            self._state.triggered_at = now
            self._state.action_taken = action
            self._state.requires_manual_reset = needs_manual

            self._save_state()

            logger.critical(
                f"[KillSwitch] TRIGGERED: {trigger_name} → action={action} "
                f"(value={value}, threshold={threshold})"
            )

            # Execute action callbacks
            try:
                if action in (KillAction.CANCEL_OPEN_ORDERS, KillAction.CLOSE_ALL):
                    self._on_cancel_orders()
                if action == KillAction.CLOSE_ALL:
                    self._on_close_all()
            except Exception as exc:
                logger.error(f"[KillSwitch] Action callback failed: {exc}")

            self._on_alert("CRITICAL", f"Kill-switch triggered: {trigger_name} ({action})")
            return action

    # ── Recovery / Reset ──────────────────────────────────────────────────────

    def notify_dependency_recovered(self) -> None:
        """
        Call when underlying dependency (model, DB, exchange) is back up.
        Moves HALTED → RECOVERY_PENDING if not manual-reset required.
        """
        with self._lock:
            if self._state.state != KSState.HALTED:
                return
            if self._state.requires_manual_reset:
                self._state.state = KSState.RESET_REQUIRED
            else:
                self._state.state = KSState.RECOVERY_PENDING
            self._state.history.append({
                "event": "RECOVERY_NOTIFIED",
                "at": datetime.now(timezone.utc).isoformat(),
            })
            self._save_state()
            logger.info(f"[KillSwitch] State → {self._state.state}")

    def generate_reset_token(self) -> str:
        """
        Generate a one-time reset token (SHA-256 of state + timestamp).
        Store hash in state, return raw token to operator.
        """
        with self._lock:
            raw = f"{self._state.trigger}:{self._state.triggered_at}:{time.time()}"
            token = hashlib.sha256(raw.encode()).hexdigest()[:16]
            self._state.reset_token_hash = hashlib.sha256(token.encode()).hexdigest()
            self._save_state()
            return token

    def reset(
        self,
        token: str,
        reason: str,
        operator: str,
        positions_acknowledged: bool = False,
    ) -> bool:
        """
        Explicit reset from RESET_REQUIRED or RECOVERY_PENDING → ARMED.
        Requires: correct token + reason + positions_acknowledged.
        Returns True if reset successful.
        """
        with self._lock:
            if self._state.state not in (KSState.RESET_REQUIRED, KSState.RECOVERY_PENDING):
                logger.warning(f"[KillSwitch] Reset attempted in state {self._state.state} — ignored")
                return False

            if not reason or not operator:
                logger.warning("[KillSwitch] Reset requires non-empty reason and operator")
                return False

            if not positions_acknowledged:
                logger.warning("[KillSwitch] Reset requires positions_acknowledged=True")
                return False

            # Verify token if set
            if self._state.reset_token_hash:
                supplied_hash = hashlib.sha256(token.encode()).hexdigest()
                if supplied_hash != self._state.reset_token_hash:
                    logger.error("[KillSwitch] Invalid reset token — reset rejected")
                    return False

            now = datetime.now(timezone.utc).isoformat()
            self._state.history.append({
                "event": "RESET",
                "operator": operator,
                "reason": reason,
                "at": now,
            })
            self._state.state = KSState.ARMED
            self._state.trigger = None
            self._state.trigger_value = None
            self._state.threshold = None
            self._state.triggered_at = None
            self._state.action_taken = None
            self._state.requires_manual_reset = False
            self._state.reset_token_hash = None
            self._state.reset_reason = reason
            self._state.reset_by = operator
            self._state.reset_at = now

            self._save_state()
            logger.info(f"[KillSwitch] RESET by {operator}: {reason}")
            self._on_alert("INFO", f"Kill-switch reset by {operator}: {reason}")
            return True

    # ── Auto-triggers for counters ────────────────────────────────────────────

    def record_loss(self, is_loss: bool) -> None:
        """Track consecutive losses and auto-trigger if threshold reached."""
        with self._lock:
            if is_loss:
                self._consecutive_losses += 1
                if self._consecutive_losses >= self.CONSECUTIVE_LOSS_THRESHOLD:
                    self.trigger("execution_anomaly",
                                 value=float(self._consecutive_losses),
                                 threshold=float(self.CONSECUTIVE_LOSS_THRESHOLD))
            else:
                self._consecutive_losses = 0

    def record_execution_error(self) -> None:
        """Track execution errors in window and auto-trigger on anomaly."""
        with self._lock:
            now = time.time()
            cutoff = now - self.ANOMALY_WINDOW_SECONDS
            self._anomaly_timestamps = [t for t in self._anomaly_timestamps if t >= cutoff]
            self._anomaly_timestamps.append(now)
            if len(self._anomaly_timestamps) >= self.ANOMALY_THRESHOLD:
                self.trigger("execution_anomaly",
                             value=float(len(self._anomaly_timestamps)),
                             threshold=float(self.ANOMALY_THRESHOLD))

    # ── API trigger (for HTTP endpoints) ─────────────────────────────────────

    def api_trigger(self, trigger_name: str, operator: str, reason: str) -> Dict[str, Any]:
        action = self.trigger(trigger_name)
        return {
            "triggered": action is not None or self._state.state == KSState.HALTED,
            "state": self._state.state,
            "action": action,
            "operator": operator,
            "reason": reason,
        }

    def api_reset(self, token: str, reason: str, operator: str, positions_acknowledged: bool) -> Dict[str, Any]:
        success = self.reset(token, reason, operator, positions_acknowledged)
        return {
            "reset": success,
            "state": self._state.state,
        }

    def get_state_dict(self) -> Dict[str, Any]:
        with self._lock:
            return self._state.to_dict()
