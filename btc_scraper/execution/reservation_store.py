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

from btc_scraper.core.paths import get_runtime_paths
from btc_scraper.trading.decision_types import ReservationStatus

DEFAULT_DB_PATH = get_runtime_paths().reservation_db_path


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
    signal_id: Optional[str] = None
    prediction_id: Optional[str] = None
    model_version: Optional[str] = None
    model_artifact_sha256: Optional[str] = None
    feature_schema_version: Optional[str] = None
    deployment_id: Optional[str] = None
    paper_run_id: Optional[str] = None
    cycle_id: Optional[str] = None
    decision_context: Optional[str] = None
    caller_context: Optional[str] = None
    position_id: Optional[str] = None
    execution_mode: Optional[str] = None
    reserved_qty: float = 0.0
    filled_qty: float = 0.0
    intent: Optional[str] = None

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
            "signal_id": self.signal_id,
            "prediction_id": self.prediction_id,
            "model_version": self.model_version,
            "model_artifact_sha256": self.model_artifact_sha256,
            "feature_schema_version": self.feature_schema_version,
            "deployment_id": self.deployment_id,
            "paper_run_id": self.paper_run_id,
            "cycle_id": self.cycle_id,
            "decision_context": self.decision_context,
            "caller_context": self.caller_context,
            "position_id": self.position_id,
            "execution_mode": self.execution_mode,
            "reserved_qty": self.reserved_qty,
            "filled_qty": self.filled_qty,
            "intent": self.intent,
        }


class ReservationStore:
    """SQLite-backed persistent reservation store for thread-safe/process-safe operations."""

    def __init__(self, db_path: Optional[str | Path] = None):
        self._db_path = Path(db_path) if db_path else get_runtime_paths().reservation_db_path
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
                existing_columns = {
                    str(row["name"])
                    for row in conn.execute("PRAGMA table_info(reservations)").fetchall()
                }
                for column, col_type in (
                    ("signal_id", "TEXT"),
                    ("prediction_id", "TEXT"),
                    ("model_version", "TEXT"),
                    ("model_artifact_sha256", "TEXT"),
                    ("feature_schema_version", "TEXT"),
                    ("deployment_id", "TEXT"),
                    ("paper_run_id", "TEXT"),
                    ("cycle_id", "TEXT"),
                    ("decision_context", "TEXT"),
                    ("caller_context", "TEXT"),
                    ("position_id", "TEXT"),
                    ("execution_mode", "TEXT"),
                    ("reserved_qty", "REAL DEFAULT 0.0"),
                    ("filled_qty", "REAL DEFAULT 0.0"),
                    ("intent", "TEXT"),
                ):
                    if column not in existing_columns:
                        try:
                            conn.execute(f"ALTER TABLE reservations ADD COLUMN {column} {col_type}")
                        except sqlite3.OperationalError as exc:
                            # Multiple recovery workers may migrate the same
                            # database concurrently. A peer winning this race
                            # is success, not a startup failure.
                            if "duplicate column name" not in str(exc).lower():
                                raise
                # Indices for fast lookups
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_res_status ON reservations(status)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_res_expiry ON reservations(expires_at)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_res_position ON reservations(position_id, execution_mode, status)"
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
        signal_id: str | None = None,
        prediction_id: str | None = None,
        model_version: str | None = None,
        model_artifact_sha256: str | None = None,
        feature_schema_version: str | None = None,
        deployment_id: str | None = None,
        paper_run_id: str | None = None,
        cycle_id: str | None = None,
        decision_context: str | None = None,
        caller_context: str | None = None,
        position_id: str | None = None,
        execution_mode: str | None = None,
        reserved_qty: float = 0.0,
        intent: str | None = None,
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
                            exchange_order_id, client_order_id, created_at, expires_at, updated_at,
                            signal_id, prediction_id, model_version, model_artifact_sha256,
                            feature_schema_version, deployment_id, paper_run_id, cycle_id,
                            decision_context, caller_context, position_id, execution_mode,
                            reserved_qty, filled_qty, intent
                        ) VALUES (?, ?, ?, ?, ?, ?, 0.0, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?)
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
                            signal_id,
                            prediction_id,
                            model_version,
                            model_artifact_sha256,
                            feature_schema_version,
                            deployment_id,
                            paper_run_id,
                            cycle_id,
                            decision_context,
                            caller_context,
                            position_id,
                            execution_mode,
                            float(reserved_qty),
                            intent,
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
        filled_qty: Optional[float] = None,
    ) -> Optional[ReservationRecord]:
        """Commit the reservation upon successful order fill on the exchange."""
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            with self._get_conn() as conn:
                if filled_qty is not None:
                    conn.execute(
                        """
                        UPDATE reservations
                        SET status = ?, filled_notional = ?, filled_qty = ?, exchange_order_id = ?, client_order_id = ?, updated_at = ?
                        WHERE reservation_id = ?
                        """,
                        (
                            ReservationStatus.COMMITTED.value,
                            filled_notional,
                            float(filled_qty),
                            exchange_order_id,
                            client_order_id,
                            now,
                            reservation_id,
                        ),
                    )
                else:
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
        filled_qty: Optional[float] = None,
    ) -> Optional[ReservationRecord]:
        """Record a partial fill, setting status to PARTIALLY_COMMITTED."""
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            with self._get_conn() as conn:
                if filled_qty is not None:
                    conn.execute(
                        """
                        UPDATE reservations
                        SET status = ?, filled_notional = ?, filled_qty = ?, exchange_order_id = ?, client_order_id = ?, updated_at = ?
                        WHERE reservation_id = ?
                        """,
                        (
                            ReservationStatus.PARTIALLY_COMMITTED.value,
                            filled_notional,
                            float(filled_qty),
                            exchange_order_id,
                            client_order_id,
                            now,
                            reservation_id,
                        ),
                    )
                else:
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

    def get_position_exit_allocations(
        self,
        position_id: str,
        execution_mode: str,
        exclude_reservation_id: Optional[str] = None,
    ) -> Tuple[float, float, float]:
        """Calculates executed and pending exit quantities for a position.
        
        Returns: (executed_qty, pending_reserved_qty, total_allocated_qty)
        """
        with self._lock:
            self.expire_stale()
            
            sql = """
                SELECT status, reserved_qty, filled_qty
                FROM reservations
                WHERE position_id = ?
                  AND execution_mode = ?
                  AND status IN (?, ?, ?)
            """
            params = [
                str(position_id),
                str(execution_mode).lower(),
                ReservationStatus.COMMITTED.value,
                ReservationStatus.PARTIALLY_COMMITTED.value,
                ReservationStatus.PENDING.value,
            ]
            if exclude_reservation_id:
                sql += " AND reservation_id != ?"
                params.append(str(exclude_reservation_id))
                
            executed_qty = 0.0
            pending_reserved_qty = 0.0
            
            with self._get_conn() as conn:
                cursor = conn.execute(sql, params)
                for row in cursor.fetchall():
                    status = row["status"]
                    res_qty = float(row["reserved_qty"] or 0.0)
                    fill_qty = float(row["filled_qty"] or 0.0)
                    if status in (ReservationStatus.COMMITTED.value, ReservationStatus.PARTIALLY_COMMITTED.value):
                        executed_qty += fill_qty if fill_qty > 0.0 else res_qty
                    elif status == ReservationStatus.PENDING.value:
                        pending_reserved_qty += res_qty
                        
            return executed_qty, pending_reserved_qty, (executed_qty + pending_reserved_qty)

    def reserve_position_exit(
        self,
        *,
        reservation_id: str,
        idempotency_key: str,
        position_id: str,
        execution_mode: str,
        available_position_qty: float,
        intended_qty: float,
        notional_usdt: float,
        symbol: str,
        side: str,
        clip_to_open_qty: bool = False,
        ttl_seconds: int = 60,
        entry_decision_id: str = "",
        signal_id: Optional[str] = None,
        prediction_id: Optional[str] = None,
        model_version: Optional[str] = None,
        model_artifact_sha256: Optional[str] = None,
        feature_schema_version: Optional[str] = None,
        deployment_id: Optional[str] = None,
        paper_run_id: Optional[str] = None,
        cycle_id: Optional[str] = None,
        decision_context: Optional[str] = None,
        caller_context: Optional[str] = None,
    ) -> Tuple[ReservationRecord, float, bool]:
        """Atomically validates position exposure and reserves exit quantity under a write transaction.
        
        Returns: (record, final_qty, created_new)
        Raises ValueError:
          - NO_REMAINING_POSITION_EXPOSURE
          - OVER_REDUCTION
        """
        with self._lock:
            conn = self._get_conn()
            try:
                with conn:
                    # Execute immediate transaction to serialize writes across processes
                    try:
                        conn.execute("BEGIN IMMEDIATE")
                    except sqlite3.OperationalError:
                        pass

                    now = datetime.now(timezone.utc).isoformat()
                    expires = datetime.fromtimestamp(time.time() + ttl_seconds, tz=timezone.utc).isoformat()

                    # Expire stale pending in this transaction
                    conn.execute(
                        """
                        UPDATE reservations
                        SET status = ?, updated_at = ?
                        WHERE status = ? AND expires_at <= ?
                        """,
                        (ReservationStatus.EXPIRED.value, now, ReservationStatus.PENDING.value, now),
                    )

                    # Check for existing idempotency key
                    cursor = conn.execute("SELECT * FROM reservations WHERE idempotency_key = ?", (idempotency_key,))
                    existing_row = cursor.fetchone()
                    if existing_row:
                        rec = self._row_to_record(existing_row)
                        return rec, float(rec.reserved_qty), False

                    # Compute current allocated exit quantity
                    cursor = conn.execute(
                        """
                        SELECT status, reserved_qty, filled_qty
                        FROM reservations
                        WHERE position_id = ?
                          AND execution_mode = ?
                          AND status IN (?, ?, ?)
                        """,
                        (
                            str(position_id),
                            str(execution_mode).lower(),
                            ReservationStatus.COMMITTED.value,
                            ReservationStatus.PARTIALLY_COMMITTED.value,
                            ReservationStatus.PENDING.value,
                        ),
                    )
                    executed = 0.0
                    pending = 0.0
                    for row in cursor.fetchall():
                        st = row["status"]
                        r_q = float(row["reserved_qty"] or 0.0)
                        f_q = float(row["filled_qty"] or 0.0)
                        if st in (ReservationStatus.COMMITTED.value, ReservationStatus.PARTIALLY_COMMITTED.value):
                            executed += f_q if f_q > 0.0 else r_q
                        elif st == ReservationStatus.PENDING.value:
                            pending += r_q
                    allocated = executed + pending
                    remaining_qty = float(available_position_qty) - allocated

                    if remaining_qty <= 1e-9:
                        raise ValueError("NO_REMAINING_POSITION_EXPOSURE")

                    final_qty = float(intended_qty)
                    if final_qty > (remaining_qty * 1.0001):
                        if clip_to_open_qty:
                            final_qty = max(0.0, remaining_qty)
                        else:
                            raise ValueError("OVER_REDUCTION")

                    proportional_notional = (final_qty / intended_qty * notional_usdt) if intended_qty > 0 else notional_usdt

                    conn.execute(
                        """
                        INSERT INTO reservations (
                            reservation_id, idempotency_key, entry_decision_id, symbol, side,
                            reserved_notional, filled_notional, reserved_position_slots, status,
                            exchange_order_id, client_order_id, created_at, expires_at, updated_at,
                            signal_id, prediction_id, model_version, model_artifact_sha256,
                            feature_schema_version, deployment_id, paper_run_id, cycle_id,
                            decision_context, caller_context, position_id, execution_mode,
                            reserved_qty, filled_qty, intent
                        ) VALUES (?, ?, ?, ?, ?, ?, 0.0, 0, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 'EXIT')
                        """,
                        (
                            reservation_id,
                            idempotency_key,
                            entry_decision_id,
                            symbol,
                            side,
                            proportional_notional,
                            ReservationStatus.PENDING.value,
                            now,
                            expires,
                            now,
                            signal_id,
                            prediction_id,
                            model_version,
                            model_artifact_sha256,
                            feature_schema_version,
                            deployment_id,
                            paper_run_id,
                            cycle_id,
                            decision_context,
                            caller_context,
                            str(position_id),
                            str(execution_mode).lower(),
                            final_qty,
                        ),
                    )

                rec = self.get_reservation(reservation_id)
                assert rec is not None
                return rec, final_qty, True
            except sqlite3.IntegrityError:
                # Race check fallback
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM reservations WHERE idempotency_key = ?",
                    (idempotency_key,),
                )
                row = cursor.fetchone()
                if row:
                    rec = self._row_to_record(row)
                    return rec, float(rec.reserved_qty), False
                raise

    def commit_position_exit(
        self,
        reservation_id: str,
        filled_qty: float,
        filled_notional: float,
        client_order_id: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
    ) -> Optional[ReservationRecord]:
        return self.commit(
            reservation_id=reservation_id,
            filled_notional=filled_notional,
            exchange_order_id=exchange_order_id,
            client_order_id=client_order_id,
            filled_qty=filled_qty,
        )

    def partial_commit_position_exit(
        self,
        reservation_id: str,
        filled_qty: float,
        filled_notional: float,
        client_order_id: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
    ) -> Optional[ReservationRecord]:
        return self.partial_commit(
            reservation_id=reservation_id,
            filled_notional=filled_notional,
            exchange_order_id=exchange_order_id,
            client_order_id=client_order_id,
            filled_qty=filled_qty,
        )

    def reconcile_crashed_reservations(self, execution_records: List[Any]) -> int:
        """Reconciles uncommitted PENDING reservations against fill tracker / execution records.
        
        Returns the count of reconciled reservations.
        """
        with self._lock:
            reconciled = 0
            with self._get_conn() as conn:
                cursor = conn.execute(
                    "SELECT reservation_id, idempotency_key FROM reservations WHERE status = ?",
                    (ReservationStatus.PENDING.value,),
                )
                pending_rows = cursor.fetchall()
                if not pending_rows:
                    return 0

                records_by_res = {}
                records_by_idemp = {}
                for r in execution_records:
                    res_id = getattr(r, "reservation_id", None) or (r.get("reservation_id") if isinstance(r, dict) else None)
                    idemp = getattr(r, "idempotency_key", None) or (r.get("idempotency_key") if isinstance(r, dict) else None)
                    if res_id:
                        records_by_res[str(res_id)] = r
                    if idemp:
                        records_by_idemp[str(idemp)] = r

                now = datetime.now(timezone.utc).isoformat()
                for row in pending_rows:
                    res_id = str(row["reservation_id"])
                    idemp = str(row["idempotency_key"])
                    rec = records_by_res.get(res_id) or records_by_idemp.get(idemp)
                    if rec:
                        status = getattr(rec, "status", None) or (rec.get("status") if isinstance(rec, dict) else "")
                        filled_qty = getattr(rec, "filled_qty", None) or (rec.get("filled_qty") if isinstance(rec, dict) else 0.0)
                        filled_notional = getattr(rec, "executed_notional", None) or (rec.get("executed_notional") if isinstance(rec, dict) else 0.0)
                        
                        if status in ("FILLED", "STATUS_FILLED"):
                            conn.execute(
                                """
                                UPDATE reservations
                                SET status = ?, filled_qty = ?, filled_notional = ?, updated_at = ?
                                WHERE reservation_id = ?
                                """,
                                (ReservationStatus.COMMITTED.value, float(filled_qty or 0.0), float(filled_notional or 0.0), now, res_id),
                            )
                            reconciled += 1
                        elif status in ("PARTIAL_FILL", "PARTIALLY_FILLED"):
                            conn.execute(
                                """
                                UPDATE reservations
                                SET status = ?, filled_qty = ?, filled_notional = ?, updated_at = ?
                                WHERE reservation_id = ?
                                """,
                                (ReservationStatus.PARTIALLY_COMMITTED.value, float(filled_qty or 0.0), float(filled_notional or 0.0), now, res_id),
                            )
                            reconciled += 1
                        elif status in ("REJECTED", "CANCELLED", "TIMEOUT"):
                            conn.execute(
                                """
                                UPDATE reservations
                                SET status = ?, updated_at = ?
                                WHERE reservation_id = ?
                                """,
                                (ReservationStatus.RELEASED.value, now, res_id),
                            )
                            reconciled += 1
            return reconciled

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
        keys = row.keys()
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
            signal_id=row["signal_id"],
            prediction_id=row["prediction_id"],
            model_version=row["model_version"],
            model_artifact_sha256=row["model_artifact_sha256"],
            feature_schema_version=row["feature_schema_version"],
            deployment_id=row["deployment_id"],
            paper_run_id=row["paper_run_id"],
            cycle_id=row["cycle_id"],
            decision_context=row["decision_context"],
            caller_context=row["caller_context"],
            position_id=row["position_id"] if "position_id" in keys else None,
            execution_mode=row["execution_mode"] if "execution_mode" in keys else None,
            reserved_qty=float(row["reserved_qty"] or 0.0) if "reserved_qty" in keys else 0.0,
            filled_qty=float(row["filled_qty"] or 0.0) if "filled_qty" in keys else 0.0,
            intent=row["intent"] if "intent" in keys else None,
        )
