from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
WATCH_ROOTS = (
    REPO_ROOT / "data",
    REPO_ROOT / "logs",
    REPO_ROOT / "catboost_info",
    REPO_ROOT / "btc_scraper" / "logs",
)

_INITIAL_RUNTIME_SNAPSHOT: dict[Path, tuple[int, int]] = {}


def _snapshot_runtime_roots() -> dict[Path, tuple[int, int]]:
    snapshot: dict[Path, tuple[int, int]] = {}
    for root in WATCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                stat = path.stat()
                snapshot[path] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def pytest_configure(config: pytest.Config) -> None:
    global _INITIAL_RUNTIME_SNAPSHOT

    worker = os.getenv("PYTEST_XDIST_WORKER", "gw0")
    run_id = os.getenv("BTC_TEST_RUN_ID") or f"{worker}-{uuid.uuid4().hex[:12]}"
    run_root = Path(tempfile.gettempdir()) / "btc-scraper-tests" / run_id

    os.environ["BTC_TEST_RUN_ID"] = run_id
    os.environ["BTC_RUNTIME_ENVIRONMENT"] = "test"
    os.environ["BTC_ENVIRONMENT"] = "test"
    os.environ["BTC_EVIDENCE_ELIGIBLE"] = "false"
    os.environ["BTC_PAPER_RUN_ID"] = run_id
    os.environ["BTC_DATA_DIR"] = str(run_root / "data")
    os.environ["BTC_LOG_DIR"] = str(run_root / "logs")
    os.environ["BTC_MODEL_DIR"] = str(run_root / "models")
    os.environ["BTC_EXECUTION_DATA_DIR"] = str(run_root / "data" / "execution")
    os.environ["BTC_PREDICTION_AUDIT_DIR"] = str(run_root / "logs" / "prediction_audit")
    os.environ["BTC_RUNTIME_EVIDENCE_PATH"] = str(run_root / "logs" / "runtime_evidence.sqlite")
    os.environ["CATBOOST_INFO_DIR"] = str(run_root / "catboost_info")
    os.environ["BTC_REMEDIATION_DOCS_DIR"] = str(run_root / "docs" / "remediation")

    run_root.mkdir(parents=True, exist_ok=True)
    _INITIAL_RUNTIME_SNAPSHOT = _snapshot_runtime_roots()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if os.getenv("BTC_DISABLE_TEST_RUNTIME_GUARD", "").lower() in {"1", "true", "yes"}:
        return

    after = _snapshot_runtime_roots()
    changed = sorted(
        str(path.relative_to(REPO_ROOT))
        for path, state in after.items()
        if _INITIAL_RUNTIME_SNAPSHOT.get(path) != state
    )
    deleted = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in _INITIAL_RUNTIME_SNAPSHOT
        if path not in after
    )
    if changed or deleted:
        tr = session.config.pluginmanager.get_plugin("terminalreporter")
        if tr is not None:
            tr.section("runtime artifact isolation")
            for path in changed[:30]:
                tr.write_line(f"modified-or-created: {path}")
            for path in deleted[:30]:
                tr.write_line(f"deleted: {path}")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
