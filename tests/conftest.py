from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

from btc_scraper.core.runtime_ownership import (
    FileFingerprint,
    _read_owner_sidecar,
    _sha256,
    describe_runtime_changes,
    snapshot_runtime_roots,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
_INITIAL_RUNTIME_SNAPSHOT = {}


def _snapshot_isolated_roots() -> dict[Path, FileFingerprint]:
    if os.getenv("BTC_DISABLE_TEST_RUNTIME_GUARD", "").lower() in {"1", "true", "yes"}:
        return {}
    roots: list[Path] = []
    data_dir = REPO_ROOT / "data"
    direct_files: list[Path] = []
    if data_dir.exists():
        for child in data_dir.iterdir():
            if child.name == "prospective_raw_research_r1":
                continue
            if child.is_dir():
                roots.append(child)
            elif child.is_file():
                direct_files.append(child)
    roots.extend([
        REPO_ROOT / "logs",
        REPO_ROOT / "catboost_info",
        REPO_ROOT / "btc_scraper" / "logs",
    ])
    snapshot = snapshot_runtime_roots(roots)
    for path in direct_files:
        stat = path.stat()
        snapshot[path] = FileFingerprint(
            path=path,
            inode=stat.st_ino,
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            sha256=_sha256(path),
            owner=_read_owner_sidecar(path),
        )
    return snapshot


def pytest_configure(config: pytest.Config) -> None:
    global _INITIAL_RUNTIME_SNAPSHOT

    worker = os.getenv("PYTEST_XDIST_WORKER", "gw0")
    run_id = os.getenv("BTC_TEST_RUN_ID") or f"{worker}-{uuid.uuid4().hex[:12]}"
    run_root = Path(tempfile.gettempdir()) / "btc-scraper-tests" / run_id

    os.environ["BTC_TEST_RUN_ID"] = run_id
    os.environ["BTC_RUNTIME_ENVIRONMENT"] = "test"
    os.environ["BTC_ENVIRONMENT"] = "test"
    os.environ["BTC_DEPLOYMENT_ID"] = os.getenv("BTC_DEPLOYMENT_ID") or f"pytest-{run_id}"
    os.environ["BTC_RUNTIME_ID"] = os.getenv("BTC_RUNTIME_ID") or run_id
    os.environ["BTC_EVIDENCE_ELIGIBLE"] = "false"
    os.environ["BTC_PAPER_RUN_ID"] = run_id
    os.environ["BTC_DATA_DIR"] = str(run_root / "data")
    os.environ["BTC_LOG_DIR"] = str(run_root / "logs")
    os.environ["BTC_MODEL_DIR"] = str(run_root / "models")
    os.environ["BTC_STATE_DIR"] = str(run_root / "state")
    os.environ["BTC_EXECUTION_DATA_DIR"] = str(run_root / "data" / "execution")
    os.environ["BTC_PREDICTION_AUDIT_DIR"] = str(run_root / "logs" / "prediction_audit")
    os.environ["BTC_RUNTIME_EVIDENCE_PATH"] = str(run_root / "logs" / "runtime_evidence.sqlite")
    os.environ["BTC_RESERVATION_DB_PATH"] = str(run_root / "data" / "execution" / "reservations.db")
    os.environ["CATBOOST_INFO_DIR"] = str(run_root / "catboost_info")
    os.environ["BTC_REMEDIATION_DOCS_DIR"] = str(run_root / "docs" / "remediation")

    run_root.mkdir(parents=True, exist_ok=True)
    _INITIAL_RUNTIME_SNAPSHOT = _snapshot_isolated_roots()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if os.getenv("BTC_DISABLE_TEST_RUNTIME_GUARD", "").lower() in {"1", "true", "yes"}:
        return

    after = _snapshot_isolated_roots()
    changes = describe_runtime_changes(_INITIAL_RUNTIME_SNAPSHOT, after, repo_root=REPO_ROOT)
    if changes:
        tr = session.config.pluginmanager.get_plugin("terminalreporter")
        if tr is not None:
            tr.section("runtime artifact isolation")
            for change in changes[:30]:
                tr.write_line(
                    "modified-or-created: "
                    f"{change['path']} "
                    f"before={change['before_hash']} after={change['after_hash']} "
                    f"writer_runtime_id={change['suspected_writer_runtime_id']} "
                    f"writer_process_id={change['suspected_writer_process_id']}"
                )
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
