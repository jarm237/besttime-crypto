"""
btc_scraper/execution/alerting.py
Phase 6 — Task 6.7: Alert Manager

Levels: INFO / WARNING / CRITICAL
Channels: Telegram (primary), local log file (fallback)
Persistent fingerprint-based deduplication (SQLite, survives restart).

Throttle policy:
    - Same fingerprint: first send immediately
    - Within 5 min: only update count (no repeat)
    - After 5 min: send escalation summary if still active
    - CRITICAL: never throttled to zero (escalation always fires)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
ALERT_DB_PATH = BASE_DIR / "data" / "execution" / "alerts_dedup.db"
ALERT_LOG_PATH = BASE_DIR / "logs" / "alerts.log"

THROTTLE_WINDOW_SECONDS = 300     # 5 minutes
ESCALATION_MIN_COUNT = 2          # escalate if alert fired ≥ 2 times in window


@dataclass
class AlertEvent:
    severity: str
    message: str
    alert_type: str
    symbol: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class AlertManager:
    """
    Centralized alert dispatch with persistent deduplication.

    Usage:
        mgr = AlertManager()
        mgr.send(severity="CRITICAL", alert_type="kill_switch_triggered",
                 message="Kill-switch triggered: daily_loss_breach", symbol="BTCUSDT")
    """

    def __init__(
        self,
        telegram_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        db_path: Optional[str] = None,
        log_path: Optional[str] = None,
    ):
        self._token = telegram_token if telegram_token is not None else os.environ.get("TELEGRAM_BOT_TOKEN")
        self._chat_id = telegram_chat_id if telegram_chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID")
        self._has_telegram = bool(self._token and self._chat_id)


        self._db_path = Path(db_path) if db_path else ALERT_DB_PATH
        self._log_path = Path(log_path) if log_path else ALERT_LOG_PATH
        self._lock = RLock()

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        if not self._has_telegram:
            logger.warning(
                "[AlertManager] No Telegram credentials found. "
                "CRITICAL alerts will only go to local log. "
                "Live gate WARNING: remote channel not configured."
            )

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS alert_state (
                    fingerprint TEXT PRIMARY KEY,
                    alert_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    first_sent_at REAL NOT NULL,
                    last_sent_at REAL NOT NULL,
                    count INTEGER NOT NULL DEFAULT 1,
                    last_escalated_at REAL
                )"""
            )

    def _connect(self):
        return sqlite3.connect(self._db_path)

    def _fingerprint(self, alert_type: str, symbol: Optional[str], message: str) -> str:
        raw = f"{alert_type}:{symbol or ''}:{message[:80]}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ── Throttle logic ────────────────────────────────────────────────────────

    def _should_send(self, fp: str, severity: str) -> tuple[bool, bool, int]:
        """
        Returns (send_now, is_escalation, count).
        """
        now = time.time()
        with self._connect() as db:
            row = db.execute(
                "SELECT first_sent_at, last_sent_at, count, last_escalated_at "
                "FROM alert_state WHERE fingerprint = ?", (fp,)
            ).fetchone()

            if row is None:
                return True, False, 1

            first_sent, last_sent, count, last_escalated = row
            new_count = count + 1
            in_window = (now - last_sent) < THROTTLE_WINDOW_SECONDS

            if not in_window:
                # Window expired — send fresh if count warrants escalation or is new cycle
                if new_count >= ESCALATION_MIN_COUNT:
                    return True, True, new_count
                return True, False, new_count

            # Within window
            if severity == "CRITICAL":
                # CRITICAL: escalate if not escalated yet in this window
                if last_escalated is None or (now - last_escalated) >= THROTTLE_WINDOW_SECONDS:
                    return True, True, new_count
            # INFO/WARNING: suppress within window, just update count
            return False, False, new_count

    def _update_state(self, fp: str, alert_type: str, severity: str, is_escalation: bool, count: int) -> None:
        now = time.time()
        with self._connect() as db:
            db.execute(
                """INSERT INTO alert_state (fingerprint, alert_type, severity, first_sent_at, last_sent_at, count, last_escalated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(fingerprint) DO UPDATE SET
                       last_sent_at = excluded.last_sent_at,
                       count = excluded.count,
                       last_escalated_at = CASE WHEN ? THEN excluded.last_escalated_at ELSE alert_state.last_escalated_at END""",
                (fp, alert_type, severity, now, now, count, now if is_escalation else None, is_escalation),
            )

    # ── Send channels ─────────────────────────────────────────────────────────

    def _send_telegram(self, text: str) -> bool:
        if not self._has_telegram:
            return False
        try:
            import requests
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            resp = requests.post(url, json={"chat_id": self._chat_id, "text": text}, timeout=5)
            return resp.ok
        except Exception as exc:
            logger.error(f"[AlertManager] Telegram send failed: {exc}")
            return False

    def _send_log(self, severity: str, message: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = json.dumps({"timestamp": timestamp, "severity": severity, "message": message})
        try:
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(entry + "\n")
        except Exception as exc:
            logger.error(f"[AlertManager] Log write failed: {exc}")

    # ── Main send ─────────────────────────────────────────────────────────────

    def send(
        self,
        severity: str,
        alert_type: str,
        message: str,
        symbol: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Send alert through configured channels with persistent deduplication.
        Returns True if alert was dispatched.
        """
        with self._lock:
            fp = self._fingerprint(alert_type, symbol, message)
            should_send, is_escalation, count = self._should_send(fp, severity)

            if not should_send:
                logger.debug(f"[AlertManager] Throttled: {alert_type} ({count}x)")
                self._update_state(fp, alert_type, severity, False, count)
                return False

            prefix_map = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🚨"}
            prefix = prefix_map.get(severity, "📢")
            esc_tag = " [ESCALATION]" if is_escalation else ""
            count_tag = f" (×{count})" if count > 1 else ""

            text = f"{prefix} [{severity}]{esc_tag}{count_tag}\n{message}"
            if symbol:
                text += f"\nSymbol: {symbol}"

            sent_telegram = self._send_telegram(text)
            self._send_log(severity, message)
            self._update_state(fp, alert_type, severity, is_escalation, count)

            channel = "telegram+log" if sent_telegram else "log_only"
            logger.log(
                logging.CRITICAL if severity == "CRITICAL" else logging.WARNING if severity == "WARNING" else logging.INFO,
                f"[Alert:{severity}] {alert_type}: {message} [channel={channel}]"
            )
            return True

    # ── Convenience methods ───────────────────────────────────────────────────

    def info(self, alert_type: str, message: str, **kwargs) -> bool:
        return self.send("INFO", alert_type, message, **kwargs)

    def warning(self, alert_type: str, message: str, **kwargs) -> bool:
        return self.send("WARNING", alert_type, message, **kwargs)

    def critical(self, alert_type: str, message: str, **kwargs) -> bool:
        return self.send("CRITICAL", alert_type, message, **kwargs)

    def has_remote_channel(self) -> bool:
        """Returns True if at least one remote (non-log) channel is configured."""
        return self._has_telegram
