from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

from btc_scraper.core.runtime_ownership import describe_runtime_changes, snapshot_runtime_roots


REPO_ROOT = Path(__file__).resolve().parents[1]
WATCH_ROOTS = (
    REPO_ROOT / "data",
    REPO_ROOT / "logs",
    REPO_ROOT / "catboost_info",
    REPO_ROOT / "btc_scraper" / "logs",
)

_INITIAL_RUNTIME_SNAPSHOT = {}


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
    _INITIAL_RUNTIME_SNAPSHOT = snapshot_runtime_roots(WATCH_ROOTS)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if os.getenv("BTC_DISABLE_TEST_RUNTIME_GUARD", "").lower() in {"1", "true", "yes"}:
        return

    after = snapshot_runtime_roots(WATCH_ROOTS)
    raw_changes = describe_runtime_changes(_INITIAL_RUNTIME_SNAPSHOT, after, repo_root=REPO_ROOT)
    # Background prospective collector writes continuously to data/prospective_raw_research_r1; exclude it from test isolation
    changes = [
        c for c in raw_changes
        if not str(c.get("path", "")).replace("\\", "/").startswith("data/prospective_raw_research_r1")
    ]
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
