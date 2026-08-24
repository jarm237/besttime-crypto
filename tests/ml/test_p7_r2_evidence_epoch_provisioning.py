from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
from scripts import p7_r2_provision_evidence_epoch as r2


def test_active_epoch_rows_fail_closed_for_missing_db(tmp_path: Path) -> None:
    assert r2.active_epoch_rows(tmp_path / "missing.sqlite") == []


def test_startup_precondition_requires_active_epoch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BTC_RUNTIME_ENVIRONMENT", "paper")
    monkeypatch.setenv("BTC_DEPLOYMENT_ID", "paper-canary-20260824-01")
    monkeypatch.setenv("BTC_PAPER_RUN_ID", "paper-canary-20260824-01")
    monkeypatch.setenv("BTC_EVIDENCE_ELIGIBLE", "true")
    monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", "BTC,ETH,BNB")
    monkeypatch.setenv("AUTO_TRADE_COINS", "BTC,ETH,BNB")
    from btc_scraper.core.config import analysis_universe_hash
    from btc_scraper.core.paths import runtime_evidence_eligible
    from btc_scraper.ml_engine.evidence_epoch import EvidenceEpoch

    modules = {
        "runtime_evidence_eligible": runtime_evidence_eligible,
    }
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    try:
        r2.validate_startup_precondition(store, modules)
    except RuntimeError as exc:
        assert "ACTIVE epoch required" in str(exc)
    else:
        raise AssertionError("precondition unexpectedly passed without ACTIVE epoch")

    release_manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": "release",
        "artifact_sha256": "artifact",
        "metadata_sha256": "metadata",
        "registry_sha256": "registry",
        "deployment_id": "paper-canary-20260824-01",
        "paper_run_id": "paper-canary-20260824-01",
        "feature_schema_version": "schema",
        "analysis_universe": "BTC,ETH,BNB",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }
    epoch = EvidenceEpoch(
        epoch_id="epoch",
        deployment_id="paper-canary-20260824-01",
        started_at=datetime.now(timezone.utc).isoformat(),
        code_commit_sha="release",
        model_version="model",
        artifact_sha256="artifact",
        feature_schema_version="schema",
        analysis_universe=("BTC", "ETH", "BNB"),
        analysis_universe_hash=analysis_universe_hash(("BTC", "ETH", "BNB")),
        paper_run_id="paper-canary-20260824-01",
        release_manifest=release_manifest,
    )
    store.create_evidence_epoch(epoch)
    try:
        r2.validate_startup_precondition(store, modules)
    except RuntimeError as exc:
        assert "ACTIVE epoch required" in str(exc)
    else:
        raise AssertionError("precondition unexpectedly passed for DRAFT epoch")

    store.transition_evidence_epoch("epoch", "ACTIVE")
    assert r2.validate_startup_precondition(store, modules)["status"] == "PASS"


def test_build_release_manifest_binds_deployment_and_artifact(tmp_path: Path) -> None:
    pinned = tmp_path
    logs = pinned / "logs"
    logs.mkdir()
    (logs / "meta_model.joblib").write_bytes(b"model")
    (logs / "meta_model.json").write_text("{}", encoding="utf-8")
    (logs / "model_registry.json").write_text("{}", encoding="utf-8")
    manifest = {
        "deployment_id": "deployment",
        "paper_run_id": "paper",
        "release": {"commit_sha": "commit"},
        "artifact": {"path": "logs/meta_model.joblib", "sha256": "artifact"},
    }

    release_manifest = r2.build_release_manifest(
        manifest=manifest,
        pinned_root=pinned,
        analysis_universe=("BTC", "ETH"),
        feature_schema_version="schema",
    )

    assert release_manifest["release_sha"] == "commit"
    assert release_manifest["artifact_sha256"] == "artifact"
    assert release_manifest["deployment_id"] == "deployment"
    assert release_manifest["paper_run_id"] == "paper"
    assert release_manifest["analysis_universe"] == "BTC,ETH"
