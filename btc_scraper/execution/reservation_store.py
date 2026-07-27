"""
btc_scraper/execution/reservation_store.py
PR 5 — SQLite-backed Persistent Reservation Store.

Provides atomic, crash-resilient pre-trade slot and notional reservations
to prevent double-entry and race conditions during live execution.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple

from btc_scraper.core.paths import build_execution_data_path
from btc_scraper.trading.decision_types import ReservationStatus

DEFAULT_DB_PATH = build_execution_data_path("reservations.db")


@dataclass
class ReservationRecord:
    reservation_id: str
    idempotency_key: str
    entry_decision_id: str
    symbol: str
    side: str
    reserved_notional: float
    filled_notional: float
    reserved_position_slots: int
    status: ReservationStatus
    exchange_order_id: Optional[str]
    client_order_id: Optional[str]
    created_at: str
    expires_at: str
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reservation_id": self.reservation_id,
            "idempotency_key": self.idempotency_key,
            "entry_decision_id": self.entry_decision_id,
            "symbol": self.symbol,
            "side": self.side,
            "reserved_notional": self.reserved_notional,
            "filled_notional": self.filled_notional,
            "reserved_position_slots": self.reserved_position_slots,
            "status": self.status.value,
            "exchange_order_id": self.exchange_order_id,
            "client_order_id": self.client_order_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "updated_at": self.updated_at,
        }


class ReservationStore:
    """SQLite-backed persistent reservation store for thread-safe/process-safe operations."""

    def __init__(self, db_path: Optional[str | Path] = None):
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._lock = RLock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS reservations (
                        reservation_id TEXT PRIMARY KEY,
                        idempotency_key TEXT NOT NULL UNIQUE,
                        entry_decision_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        side TEXT NOT NULL,
                        reserved_notional REAL NOT NULL,
                        filled_notional REAL NOT NULL DEFAULT 0,
                        reserved_position_slots INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        exchange_order_id TEXT,
                        client_order_id TEXT,
                        created_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                # Indices for fast lookups
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_res_status ON reservations(status)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_res_expiry ON reservations(expires_at)"
                )
                conn.commit()

    def reserve(
        self,
        reservation_id: str,
        idempotency_key: str,
        entry_decision_id: str,
        symbol: str,
        side: str,
        reserved_notional: float,
        reserved_position_slots: int = 1,
        ttl_seconds: int = 60,
    ) -> Tuple[ReservationRecord, bool]:
        """Atomically reserve a slot and notional.

        Returns (record, created_new). If the idempotency key already exists,
        returns the existing record and False.
        """
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            expires = datetime.fromtimestamp(time.time() + ttl_seconds, tz=timezone.utc).isoformat()

            conn = self._get_conn()
            try:
                with conn:
                    # Attempt insertion
                    conn.execute(
                        """
                        INSERT INTO reservations (
                            reservation_id, idempotency_key, entry_decision_id, symbol, side,
                            reserved_notional, filled_notional, reserved_position_slots, status,
                            exchange_order_id, client_order_id, created_at, expires_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 0.0, ?, ?, NULL, NULL, ?, ?, ?)
                        """,
                        (
                            reservation_id,
                            idempotency_key,
                            entry_decision_id,
                            symbol,
                            side,
                            reserved_notional,
                            reserved_position_slots,
                            ReservationStatus.PENDING.value,
                            now,
                            expires,
                            now,
                        ),
                    )
                record = self.get_reservation(reservation_id)
                assert record is not None
                return record, True
            except sqlite3.IntegrityError:
                # Idempotency key already exists, fetch it
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM reservations WHERE idempotency_key = ?",
                    (idempotency_key,),
                )
                row = cursor.fetchone()
                if row:
                    rec = self._row_to_record(row)
                    return rec, False
                raise

    def commit(
        self,
        reservation_id: str,
        filled_notional: float,
        exchange_order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> Optional[ReservationRecord]:
        """Commit the reservation upon successful order fill on the exchange."""
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            with self._get_conn() as conn:
                conn.execute(
                    """
                    UPDATE reservations
                    SET status = ?, filled_notional = ?, exchange_order_id = ?, client_order_id = ?, updated_at = ?
                    WHERE reservation_id = ?
                    """,
                    (
                        ReservationStatus.COMMITTED.value,
                        filled_notional,
                        exchange_order_id,
                        client_order_id,
                        now,
                        reservation_id,
                    ),
                )
            return self.get_reservation(reservation_id)

    def partial_commit(
        self,
        reservation_id: str,
        filled_notional: float,
        exchange_order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> Optional[ReservationRecord]:
        """Record a partial fill, setting status to PARTIALLY_COMMITTED."""
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            with self._get_conn() as conn:
                conn.execute(
                    """
                    UPDATE reservations
                    SET status = ?, filled_notional = ?, exchange_order_id = ?, client_order_id = ?, updated_at = ?
                    WHERE reservation_id = ?
                    """,
                    (
                        ReservationStatus.PARTIALLY_COMMITTED.value,
                        filled_notional,
                        exchange_order_id,
                        client_order_id,
                        now,
                        reservation_id,
                    ),
                )
            return self.get_reservation(reservation_id)

    def attach_order(
        self,
        reservation_id: str,
        *,
        client_order_id: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
    ) -> Optional[ReservationRecord]:
        """Attach known exchange/client order IDs without marking fill committed."""
        with self._lock:
            current = self.get_reservation(reservation_id)
            if current is None:
                return None
            desired_client_order_id = client_order_id or current.client_order_id
            desired_exchange_order_id = exchange_order_id or current.exchange_order_id
            if (
                desired_client_order_id == current.client_order_id
                and desired_exchange_order_id == current.exchange_order_id
            ):
                return current
            now = datetime.now(timezone.utc).isoformat()
            with self._get_conn() as conn:
                conn.execute(
                    """
                    UPDATE reservations
                    SET exchange_order_id = COALESCE(?, exchange_order_id),
                        client_order_id = COALESCE(?, client_order_id),
                        updated_at = ?
                    WHERE reservation_id = ?
                    """,
                    (exchange_order_id, client_order_id, now, reservation_id),
                )
            return self.get_reservation(reservation_id)

    def release(self, reservation_id: str) -> Optional[ReservationRecord]:
        """Release the reservation if the order was rejected or failed."""
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            with self._get_conn() as conn:
                conn.execute(
                    """
                    UPDATE reservations
                    SET status = ?, updated_at = ?
                    WHERE reservation_id = ?
                    """,
                    (ReservationStatus.RELEASED.value, now, reservation_id),
                )
            return self.get_reservation(reservation_id)

    def expire_stale(self) -> int:
        """Expire pending reservations that have exceeded their TTL.

        Returns the number of expired reservations.
        """
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            with self._get_conn() as conn:
                cursor = conn.execute(
                    """
                    UPDATE reservations
                    SET status = ?, updated_at = ?
                    WHERE status = ? AND expires_at <= ?
                    """,
                    (
                        ReservationStatus.EXPIRED.value,
                        now,
                        ReservationStatus.PENDING.value,
                        now,
                    ),
                )
                return cursor.rowcount

    def get_reservation(self, reservation_id: str) -> Optional[ReservationRecord]:
        with self._lock:
            with self._get_conn() as conn:
                cursor = conn.execute(
                    "SELECT * FROM reservations WHERE reservation_id = ?",
                    (reservation_id,),
                )
                row = cursor.fetchone()
                if row:
                    return self._row_to_record(row)
        return None

    def get_by_idempotency_key(self, idempotency_key: str) -> Optional[ReservationRecord]:
        with self._lock:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM reservations WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
        return self._row_to_record(row) if row else None

    def get_by_entry_decision_id(self, entry_decision_id: str) -> Optional[ReservationRecord]:
        with self._lock:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM reservations WHERE entry_decision_id = ? ORDER BY created_at LIMIT 1",
                    (entry_decision_id,),
                ).fetchone()
        return self._row_to_record(row) if row else None

    def get_active_notional_and_slots(self, exclude_reservation_id: Optional[str] = None) -> Tuple[float, int]:
        """Get the total reserved notional and position slots for active
        reservations (PENDING, COMMITTED, PARTIALLY_COMMITTED).

        Used to validate portfolio caps pre-trade.
        """
        with self._lock:
            # First, clean up any stale pending ones
            self.expire_stale()

            active_statuses = [
                ReservationStatus.PENDING.value,
                ReservationStatus.COMMITTED.value,
                ReservationStatus.PARTIALLY_COMMITTED.value,
            ]
            sql = """
                SELECT SUM(reserved_notional) as total_notional, SUM(reserved_position_slots) as total_slots
                FROM reservations
                WHERE status IN (?, ?, ?)
            """
            params = list(active_statuses)
            if exclude_reservation_id is not None:
                sql += " AND reservation_id != ?"
                params.append(exclude_reservation_id)

            with self._get_conn() as conn:
                cursor = conn.execute(sql, params)
                row = cursor.fetchone()
                if row and row["total_notional"] is not None:
                    return float(row["total_notional"]), int(row["total_slots"])
        return 0.0, 0

    def _row_to_record(self, row: sqlite3.Row) -> ReservationRecord:
        return ReservationRecord(
            reservation_id=row["reservation_id"],
            idempotency_key=row["idempotency_key"],
            entry_decision_id=row["entry_decision_id"],
            symbol=row["symbol"],
            side=row["side"],
            reserved_notional=row["reserved_notional"],
            filled_notional=row["filled_notional"],
            reserved_position_slots=row["reserved_position_slots"],
            status=ReservationStatus(row["status"]),
            exchange_order_id=row["exchange_order_id"],
            client_order_id=row["client_order_id"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            updated_at=row["updated_at"],
        )
