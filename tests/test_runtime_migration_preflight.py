from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
from pathlib import Path


def _load_preflight_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "runtime_migration_preflight.py"
    spec = importlib.util.spec_from_file_location("runtime_migration_preflight", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_migration_preflight_reports_process_and_runtime_state(monkeypatch, tmp_path):
    module = _load_preflight_module()
    repo = tmp_path / "repo"
    legacy_data = repo / "data"
    legacy_logs = repo / "logs"
    legacy_data.mkdir(parents=True)
    legacy_logs.mkdir(parents=True)
    (legacy_data / "latest_signals.json").write_text('{"ok": true}\n', encoding="utf-8")
    (legacy_logs / "paper.log").write_text("cycle complete\n", encoding="utf-8")

    runtime_root = tmp_path / "runtime-root"
    evidence_path = runtime_root / "logs" / "runtime_evidence.sqlite"
    reservation_path = runtime_root / "data" / "execution" / "reservations.db"
    lock_path = runtime_root / "state" / "runtime.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text(json.dumps({"process_id": os.getpid(), "runtime_id": "paper-runtime"}), encoding="utf-8")

    evidence_path.parent.mkdir(parents=True)
    with sqlite3.connect(evidence_path) as db:
        db.execute("CREATE TABLE predictions(prediction_id TEXT)")
        db.execute("CREATE TABLE feature_snapshots(prediction_id TEXT)")
        db.execute("CREATE TABLE final_decisions(decision_id TEXT)")
        db.execute("CREATE TABLE outcome_links(outcome_id TEXT)")
        db.execute("CREATE TABLE audit_events(id INTEGER)")
        db.execute("CREATE TABLE evidence_quarantine(id INTEGER)")
        db.execute("CREATE TABLE evidence_incidents(id INTEGER)")
        db.execute("INSERT INTO predictions VALUES ('pred-1')")

    reservation_path.parent.mkdir(parents=True)
    with sqlite3.connect(reservation_path) as db:
        db.execute("CREATE TABLE reservations(status TEXT)")
        db.execute("INSERT INTO reservations VALUES ('PENDING')")

    monkeypatch.setenv("BTC_ENVIRONMENT", "paper")
    monkeypatch.setenv("BTC_DEPLOYMENT_ID", "local-paper-main")
    monkeypatch.setenv("BTC_RUNTIME_ID", "paper-runtime")
    monkeypatch.setenv("BTC_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("BTC_RUNTIME_EVIDENCE_PATH", str(evidence_path))
    monkeypatch.setenv("BTC_RESERVATION_DB_PATH", str(reservation_path))
    monkeypatch.setenv("BTC_RUNTIME_LOCK_PATH", str(lock_path))

    report = module.build_report(
        pid=os.getpid(),
        repo_root=repo,
        legacy_roots=(Path("data"), Path("logs")),
        include_file_list=True,
    )

    assert report["process"]["running"] is True
    assert report["runtime_lock"]["exists"] is True
    assert report["runtime_lock"]["owner_pid_alive"] is True
    assert report["runtime_evidence"]["counts"]["predictions"] == 1
    assert report["runtime_evidence"]["health"]["status"] == "healthy"
    assert report["reservations"]["active_count"] == 1
    assert report["legacy_roots"]["file_count"] == 2
    assert len(report["legacy_roots"]["files"]) == 2


def test_runtime_migration_preflight_compare_detects_legacy_changes(tmp_path):
    module = _load_preflight_module()
    repo = tmp_path / "repo"
    data = repo / "data"
    data.mkdir(parents=True)
    target = data / "latest_signals.json"
    target.write_text('{"version": 1}\n', encoding="utf-8")

    before = module.build_report(
        pid=None,
        repo_root=repo,
        legacy_roots=(Path("data"),),
    )
    target.write_text('{"version": 2}\n', encoding="utf-8")
    after = module.build_report(
        pid=None,
        repo_root=repo,
        legacy_roots=(Path("data"),),
    )

    comparison = module.compare_reports(before, after)
    assert comparison["legacy_roots_unchanged"] is False
    assert comparison["before_aggregate_sha256"] != comparison["after_aggregate_sha256"]
