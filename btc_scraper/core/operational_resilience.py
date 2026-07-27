"""Durable infrastructure primitives for outage-safe operation."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError


def atomic_write_json(path: str | Path, payload: Any) -> None:
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, target)


class SQLiteEventSpool:
    """Durable at-least-once spool; event ids make replay idempotent."""
    def __init__(self, path: str | Path, max_events: int = 100_000) -> None:
        self.path, self.max_events, self._lock = Path(path), max_events, RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS spool (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL)")
    def _connect(self): return sqlite3.connect(self.path)
    def enqueue(self, event_id: str, payload: dict[str, Any]) -> bool:
        with self._lock, self._connect() as db:
            if db.execute("SELECT COUNT(*) FROM spool").fetchone()[0] >= self.max_events: raise RuntimeError("spool_quota_exceeded")
            cursor = db.execute("INSERT OR IGNORE INTO spool VALUES (?, ?, ?)", (event_id, json.dumps(payload, allow_nan=False), time.time()))
            return cursor.rowcount == 1
    def replay(self, deliver: Callable[[str, dict[str, Any]], None], limit: int = 1000) -> int:
        delivered = 0
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT event_id, payload FROM spool ORDER BY created LIMIT ?", (limit,)).fetchall()
            for event_id, raw in rows:
                deliver(event_id, json.loads(raw))
                db.execute("DELETE FROM spool WHERE event_id = ?", (event_id,)); delivered += 1
        return delivered
    def size(self) -> int:
        with self._connect() as db: return int(db.execute("SELECT COUNT(*) FROM spool").fetchone()[0])


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    recovery_seconds: float = 30.0
    state: str = "CLOSED"
    failures: int = 0
    opened_at: float | None = None
    def allow(self) -> bool:
        if self.state == "CLOSED": return True
        if self.state == "OPEN" and time.monotonic() - (self.opened_at or 0) >= self.recovery_seconds:
            self.state = "HALF_OPEN"; return True
        return self.state == "HALF_OPEN"
    def success(self) -> None: self.state, self.failures, self.opened_at = "CLOSED", 0, None
    def failure(self) -> None:
        self.failures += 1
        if self.state == "HALF_OPEN" or self.failures >= self.failure_threshold:
            self.state, self.opened_at = "OPEN", time.monotonic()


class DatabaseResilience:
    def __init__(self, spool: SQLiteEventSpool, breaker: CircuitBreaker | None = None) -> None: self.spool, self.breaker = spool, breaker or CircuitBreaker()
    def submit(self, event_id: str, payload: dict[str, Any], write: Callable[[str, dict[str, Any]], None]) -> str:
        if not self.breaker.allow(): self.spool.enqueue(event_id, payload); return "SPOOLED"
        try: write(event_id, payload); self.breaker.success(); return "DELIVERED"
        except Exception: self.breaker.failure(); self.spool.enqueue(event_id, payload); return "SPOOLED"
    def replay(self, write: Callable[[str, dict[str, Any]], None]) -> int:
        if not self.breaker.allow(): return 0
        try: result = self.spool.replay(write); self.breaker.success(); return result
        except Exception: self.breaker.failure(); return 0


def service_health(*, db_ok: bool, exchange_ok: bool, model_ok: bool, data_path: str | Path = "data") -> dict[str, Any]:
    from btc_scraper.core.paths import runtime_lock_bypass_reason, runtime_lock_disabled

    disk = shutil.disk_usage(Path(data_path))
    disk_ok = disk.free / max(disk.total, 1) >= .05
    runtime_lock_ok = not runtime_lock_disabled()
    dependencies = {
        "db": bool(db_ok),
        "exchange": bool(exchange_ok),
        "model": bool(model_ok),
        "disk": disk_ok,
        "runtime_lock": runtime_lock_ok,
    }
    return {"live": True, "ready": all(dependencies.values()), "dependencies": dependencies,
            "runtime_ownership": {
                "lock_required": True,
                "lock_disabled": not runtime_lock_ok,
                "severity": "CRITICAL" if not runtime_lock_ok else None,
                "reason": runtime_lock_bypass_reason() if not runtime_lock_ok else None,
            },
            "resources": {"disk_free_bytes": disk.free, "disk_free_ratio": disk.free / max(disk.total, 1)}}


class ShutdownCoordinator:
    """Runs registered stop/flush callbacks without allowing one to hang exit."""
    def __init__(self) -> None: self._callbacks: list[Callable[[], None]] = []
    def register(self, callback: Callable[[], None]) -> None: self._callbacks.append(callback)
    def shutdown(self, timeout_seconds: float = 5.0) -> list[str]:
        failures: list[str] = []
        with ThreadPoolExecutor(max_workers=max(1, len(self._callbacks))) as pool:
            futures = [(callback, pool.submit(callback)) for callback in self._callbacks]
            for callback, future in futures:
                try: future.result(timeout=timeout_seconds)
                except (Exception, TimeoutError): failures.append(getattr(callback, "__name__", "callback"))
        return failures


def resource_snapshot(data_path: str | Path = "data") -> dict[str, Any]:
    disk = shutil.disk_usage(Path(data_path))
    result = {"disk_free_bytes": disk.free, "disk_total_bytes": disk.total, "cpu_percent": None, "ram_percent": None}
    try:
        import psutil
        result.update({"cpu_percent": psutil.cpu_percent(interval=None), "ram_percent": psutil.virtual_memory().percent})
    except Exception:
        pass
    return result
