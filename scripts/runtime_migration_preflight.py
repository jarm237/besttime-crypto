#!/usr/bin/env python3
"""Read-only runtime migration preflight and clean-proof helper.

The script intentionally avoids importing trading modules with external side
effects. It inspects /proc, fingerprints legacy artifact roots, and summarizes
runtime stores from SQLite/JSON files without creating missing stores.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_REPO_ROOT))

from btc_scraper.core.paths import REPO_ROOT, get_runtime_paths

OWNERSHIP_ENV_KEYS = (
    "BTC_ENVIRONMENT",
    "BTC_RUNTIME_ENVIRONMENT",
    "BTC_DEPLOYMENT_ID",
    "BTC_RUNTIME_ID",
    "BTC_RUNTIME_ROOT",
    "BTC_DATA_DIR",
    "BTC_LOG_DIR",
    "BTC_MODEL_DIR",
    "BTC_STATE_DIR",
    "BTC_EXECUTION_DATA_DIR",
    "BTC_PREDICTION_AUDIT_DIR",
    "BTC_RUNTIME_EVIDENCE_PATH",
    "BTC_RESERVATION_DB_PATH",
    "BTC_DISABLE_RUNTIME_LOCK",
)

DEFAULT_LEGACY_ROOTS = (
    Path("data"),
    Path("logs"),
    Path("catboost_info"),
    Path("btc_scraper/logs"),
)


def build_report(
    *,
    pid: int | None,
    repo_root: Path = REPO_ROOT,
    legacy_roots: Iterable[Path] = DEFAULT_LEGACY_ROOTS,
    include_file_list: bool = False,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    paths = get_runtime_paths()
    legacy_root_paths = [_resolve_under_repo(repo_root, root) for root in legacy_roots]
    process = inspect_process(pid) if pid is not None else {"pid": None, "running": None}
    fingerprint = fingerprint_roots(repo_root, legacy_root_paths, include_file_list=include_file_list)

    ledger_path = paths.state_root / "order_fill_ledger.json"
    quarantine_path = paths.state_root / "quarantine.json"
    return {
        "generated_at": _now(),
        "repo_root": str(repo_root),
        "process": process,
        "runtime": {
            "environment": paths.environment,
            "deployment_id": paths.deployment_id,
            "runtime_id": paths.runtime_id,
            "runtime_root": str(paths.runtime_root),
            "data_root": str(paths.data_root),
            "logs_root": str(paths.logs_root),
            "state_root": str(paths.state_root),
            "runtime_lock_path": str(paths.runtime_lock_path),
            "runtime_evidence_path": str(paths.runtime_evidence_path),
            "reservation_db_path": str(paths.reservation_db_path),
            "evidence_eligible": paths.evidence_eligible,
            "paper_run_id": paths.paper_run_id,
        },
        "runtime_lock": runtime_lock_snapshot(paths.runtime_lock_path),
        "runtime_evidence": runtime_evidence_snapshot(paths.runtime_evidence_path),
        "reservations": reservation_snapshot(paths.reservation_db_path),
        "order_fill_ledger": json_state_snapshot(
            ledger_path,
            count_fields={
                "orders": "order_count",
                "fills": "fill_count",
                "pending_fills": "pending_fill_count",
                "conflicts": "conflict_count",
            },
        ),
        "quarantine": json_state_snapshot(
            quarantine_path,
            count_fields={"records": "record_count", "audit_events": "audit_event_count"},
            unresolved_field=("records", "resolution_status", "OPEN", "unresolved_count"),
        ),
        "legacy_roots": fingerprint,
        "git_dirty_runtime_artifacts": git_dirty_under(repo_root, legacy_root_paths),
        "acceptance_hints": acceptance_hints(process, fingerprint, paths.runtime_lock_path),
    }


def inspect_process(pid: int) -> dict[str, Any]:
    proc = Path("/proc") / str(pid)
    if not proc.exists():
        running = bool(_pid_alive(pid)) if sys.platform == "win32" else False
        return {
            "pid": pid,
            "running": running,
            "cmdline": None,
            "cwd": None,
            "ownership_env": {},
            "has_owned_runtime_env": False,
            "fd_count": None,
            "fd_sample": [],
        }

    environ = _read_proc_environ(proc / "environ")
    fd_targets = []
    fd_dir = proc / "fd"
    fds: list[Path] = []
    if fd_dir.exists():
        try:
            fds = sorted(fd_dir.iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else 10**9)
        except OSError:
            fds = []
        for fd in fds[:50]:
            try:
                fd_targets.append({"fd": fd.name, "target": os.readlink(fd)})
            except OSError as exc:
                fd_targets.append({"fd": fd.name, "error": str(exc)})

    return {
        "pid": pid,
        "running": True,
        "cmdline": _read_proc_cmdline(proc / "cmdline"),
        "cwd": _readlink_or_none(proc / "cwd"),
        "ownership_env": {key: environ[key] for key in OWNERSHIP_ENV_KEYS if key in environ},
        "has_owned_runtime_env": any(key in environ for key in OWNERSHIP_ENV_KEYS),
        "fd_count": len(fds) if fd_dir.exists() else None,
        "fd_sample": fd_targets,
    }


def fingerprint_roots(
    repo_root: Path,
    roots: Iterable[Path],
    *,
    include_file_list: bool = False,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    total_bytes = 0
    existing_roots = []
    for root in roots:
        root = root.resolve()
        if not root.exists():
            continue
        existing_roots.append(_display_path(repo_root, root))
        for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: str(p)):
            stat = path.stat()
            file_hash = _sha256_file(path)
            total_bytes += stat.st_size
            row = {
                "path": _display_path(repo_root, path),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": file_hash,
            }
            line = f"{row['path']}|{row['size']}|{row['mtime_ns']}|{row['sha256']}\n"
            digest.update(line.encode("utf-8"))
            if include_file_list:
                entries.append(row)
    result: dict[str, Any] = {
        "roots": existing_roots,
        "file_count": len(entries) if include_file_list else _count_files(roots),
        "total_bytes": total_bytes,
        "aggregate_sha256": digest.hexdigest(),
    }
    if include_file_list:
        result["files"] = entries
    return result


def compare_reports(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_fp = before.get("legacy_roots", {})
    after_fp = after.get("legacy_roots", {})
    return {
        "legacy_roots_unchanged": before_fp.get("aggregate_sha256") == after_fp.get("aggregate_sha256"),
        "before_aggregate_sha256": before_fp.get("aggregate_sha256"),
        "after_aggregate_sha256": after_fp.get("aggregate_sha256"),
        "before_file_count": before_fp.get("file_count"),
        "after_file_count": after_fp.get("file_count"),
        "before_total_bytes": before_fp.get("total_bytes"),
        "after_total_bytes": after_fp.get("total_bytes"),
    }


def runtime_lock_snapshot(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if payload is None:
        return {"path": str(path), "exists": False}
    owner_pid = _safe_int(payload.get("process_id")) if isinstance(payload, dict) else None
    return {
        "path": str(path),
        "exists": True,
        "owner": payload,
        "owner_pid_alive": _pid_alive(owner_pid),
    }


def runtime_evidence_snapshot(path: Path) -> dict[str, Any]:
    tables = ("predictions", "feature_snapshots", "final_decisions", "outcome_links", "audit_events", "evidence_quarantine", "evidence_incidents")
    result = sqlite_snapshot(path, tables=tables)
    if result.get("exists") is not True or result.get("readable") is not True:
        return result
    counts = result["counts"]
    result["health"] = {
        "status": "healthy" if (
            result.get("integrity") == "ok"
            and counts.get("evidence_quarantine", 0) == 0
            and counts.get("evidence_incidents", 0) == 0
        ) else "degraded",
        "unresolved_incidents": counts.get("evidence_incidents"),
        "quarantined_records": counts.get("evidence_quarantine"),
    }
    return result


def reservation_snapshot(path: Path) -> dict[str, Any]:
    result = sqlite_snapshot(path, tables=("reservations",))
    if result.get("exists") is not True or result.get("readable") is not True:
        return result
    status_counts: dict[str, int] = {}
    try:
        with _connect_readonly(path) as db:
            if _table_exists(db, "reservations"):
                rows = db.execute("SELECT status, COUNT(*) FROM reservations GROUP BY status").fetchall()
                status_counts = {str(status): int(count) for status, count in rows}
    except Exception as exc:
        result["status_read_error"] = str(exc)
    active = sum(status_counts.get(status, 0) for status in ("PENDING", "COMMITTED", "PARTIALLY_COMMITTED"))
    result["status_counts"] = status_counts
    result["active_count"] = active
    return result


def sqlite_snapshot(path: Path, *, tables: Iterable[str]) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    try:
        with _connect_readonly(path) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            counts = {
                table: int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in tables
                if _table_exists(db, table)
            }
        return {"path": str(path), "exists": True, "readable": True, "integrity": integrity, "counts": counts}
    except Exception as exc:
        return {"path": str(path), "exists": True, "readable": False, "error": str(exc)}


def json_state_snapshot(
    path: Path,
    *,
    count_fields: dict[str, str],
    unresolved_field: tuple[str, str, str, str] | None = None,
) -> dict[str, Any]:
    payload = _read_json(path)
    if payload is None:
        return {"path": str(path), "exists": False}
    if isinstance(payload, dict) and payload.get("readable") is False:
        return {"path": str(path), "exists": True, **payload}
    result: dict[str, Any] = {"path": str(path), "exists": True, "readable": True}
    if isinstance(payload, dict):
        for source, target in count_fields.items():
            value = payload.get(source)
            result[target] = len(value) if isinstance(value, (dict, list)) else 0
        if unresolved_field is not None:
            source, field, expected, target = unresolved_field
            rows = payload.get(source)
            if isinstance(rows, dict):
                result[target] = sum(1 for row in rows.values() if isinstance(row, dict) and row.get(field) == expected)
            elif isinstance(rows, list):
                result[target] = sum(1 for row in rows if isinstance(row, dict) and row.get(field) == expected)
    return result


def git_dirty_under(repo_root: Path, roots: Iterable[Path]) -> list[dict[str, str]]:
    root_prefixes = {_display_path(repo_root, root.resolve()).rstrip("/") + "/" for root in roots}
    try:
        output = subprocess.check_output(
            ["git", "status", "--short"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []
    rows = []
    for line in output.splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:]
        if any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in root_prefixes):
            rows.append({"status": status, "path": path})
    return rows


def acceptance_hints(process: dict[str, Any], fingerprint: dict[str, Any], lock_path: Path) -> dict[str, Any]:
    return {
        "legacy_process_has_owned_runtime_env": bool(process.get("has_owned_runtime_env")),
        "legacy_roots_fingerprint_recorded": bool(fingerprint.get("aggregate_sha256")),
        "runtime_lock_file_present": lock_path.exists(),
        "clean_guard_full_suite_ready": (
            process.get("running") is False
            or bool(process.get("has_owned_runtime_env"))
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create read-only P1.8 runtime migration preflight evidence.")
    parser.add_argument("--pid", type=int, default=None, help="Runtime process PID to inspect.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="Repository root. Defaults to detected repo root.")
    parser.add_argument("--legacy-root", action="append", type=Path, dest="legacy_roots", help="Legacy root to fingerprint. May be repeated.")
    parser.add_argument("--include-file-list", action="store_true", help="Include every file fingerprint in the report.")
    parser.add_argument("--compare-before", type=Path, help="Compare this report with a previous JSON report.")
    parser.add_argument("--expect-legacy-unchanged", action="store_true", help="Exit non-zero if --compare-before detects legacy root changes.")
    parser.add_argument("--output", type=Path, help="Write JSON report to this path. Otherwise print to stdout.")
    args = parser.parse_args(argv)

    report = build_report(
        pid=args.pid,
        repo_root=args.repo_root,
        legacy_roots=args.legacy_roots or DEFAULT_LEGACY_ROOTS,
        include_file_list=args.include_file_list,
    )
    exit_code = 0
    if args.compare_before:
        before = json.loads(args.compare_before.read_text(encoding="utf-8"))
        report["comparison"] = compare_reports(before, report)
        if args.expect_legacy_unchanged and not report["comparison"]["legacy_roots_unchanged"]:
            exit_code = 2

    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return exit_code


def _connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _read_proc_environ(path: Path) -> dict[str, str]:
    try:
        raw = path.read_bytes()
    except OSError:
        return {}
    env: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        env[key.decode(errors="replace")] = value.decode(errors="replace")
    return env


def _read_proc_cmdline(path: Path) -> list[str]:
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    return [part.decode(errors="replace") for part in raw.split(b"\0") if part]


def _readlink_or_none(path: Path) -> str | None:
    try:
        return os.readlink(path)
    except OSError:
        return None


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"readable": False, "error": str(exc)}


def _resolve_under_repo(repo_root: Path, path: Path) -> Path:
    path = Path(path).expanduser()
    return path if path.is_absolute() else repo_root / path


def _display_path(repo_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_files(roots: Iterable[Path]) -> int:
    total = 0
    for root in roots:
        if root.exists():
            total += sum(1 for path in root.rglob("*") if path.is_file())
    return total


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _windows_pid_alive(pid: int) -> bool:
    """Query a Windows process handle without delivering a console signal."""
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    error_access_denied = 5
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() == error_access_denied
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int | None) -> bool | None:
    if pid is None or pid <= 0:
        return None
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
