#!/usr/bin/env python3
"""Provision the P7 paper-canary ACTIVE evidence epoch as operational state.

This is not a runtime activation attempt.  The script uses the pinned runtime
release modules to create and activate exactly one deployment-specific evidence
epoch required by pinned ``main.py`` when ``BTC_EVIDENCE_ELIGIBLE=true``.
Canonical runtime inputs are hashed before and after provisioning; only the
deployment-specific runtime evidence store is allowed to change.
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
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_SHA256 = "9140dc0c501349988aae1ff9547e671517f3253545344c506567df56c4c88894"
R2_CONTRACT_VERSION = "p7-r2-evidence-epoch-operational-provisioning/v1"


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pinned_environment(manifest: dict[str, Any], pinned_root: Path) -> dict[str, str]:
    return {
        "PYTHONPATH": str(pinned_root),
        "PYTHONNOUSERSITE": "1",
        "BTC_RUNTIME_ENVIRONMENT": "paper",
        "BTC_DEPLOYMENT_ID": str(manifest["deployment_id"]),
        "BTC_PAPER_RUN_ID": str(manifest["paper_run_id"]),
        "BTC_EVIDENCE_ELIGIBLE": "true",
        "AUTO_TRADE_DRY_RUN": "true",
        "AUTO_TRADE_BINANCE_TESTNET": "true",
        "LIVE_TRADING_ENABLED": "false",
    }


def apply_environment(values: dict[str, str]) -> dict[str, str | None]:
    previous: dict[str, str | None] = {}
    for key, value in values.items():
        previous[key] = os.environ.get(key)
        os.environ[key] = value
    return previous


def restore_environment(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def import_pinned_modules(pinned_root: Path) -> dict[str, Any]:
    pinned = str(pinned_root)
    if pinned in sys.path:
        sys.path.remove(pinned)
    sys.path.insert(0, pinned)
    from btc_scraper.core.config import analysis_universe_hash, get_runtime_universe
    from btc_scraper.core.paths import get_runtime_paths, runtime_evidence_eligible
    from btc_scraper.ml_engine.evidence_epoch import EvidenceEpoch
    from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore

    return {
        "analysis_universe_hash": analysis_universe_hash,
        "get_runtime_universe": get_runtime_universe,
        "get_runtime_paths": get_runtime_paths,
        "runtime_evidence_eligible": runtime_evidence_eligible,
        "EvidenceEpoch": EvidenceEpoch,
        "RuntimeEvidenceStore": RuntimeEvidenceStore,
    }


def immutable_input_hashes(manifest_path: Path, manifest: dict[str, Any], pinned_root: Path) -> dict[str, str]:
    artifact_path = pinned_root / str(manifest["artifact"]["path"])
    sidecar_path = artifact_path.with_suffix(".json")
    registry_path = pinned_root / "logs/model_registry.json"
    return {
        "manifest_sha256": sha256_file(manifest_path),
        "artifact_sha256": sha256_file(artifact_path),
        "artifact_sidecar_sha256": sha256_file(sidecar_path),
        "model_registry_sha256": sha256_file(registry_path),
        "release_commit_sha": git(pinned_root, "rev-parse", "HEAD"),
        "release_tree_sha": git(pinned_root, "rev-parse", "HEAD^{tree}"),
    }


def active_epoch_rows(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as db:
        rows = db.execute(
            "SELECT epoch_id,deployment_id,status,paper_run_id,code_commit_sha,artifact_sha256,"
            "feature_schema_version,release_manifest_sha256 FROM evidence_epochs WHERE status='ACTIVE'"
        ).fetchall()
    return [
        {
            "epoch_id": row[0],
            "deployment_id": row[1],
            "status": row[2],
            "paper_run_id": row[3],
            "code_commit_sha": row[4],
            "artifact_sha256": row[5],
            "feature_schema_version": row[6],
            "release_manifest_sha256": row[7],
        }
        for row in rows
    ]


def build_release_manifest(
    *,
    manifest: dict[str, Any],
    pinned_root: Path,
    analysis_universe: tuple[str, ...],
    feature_schema_version: str,
) -> dict[str, Any]:
    artifact_path = pinned_root / str(manifest["artifact"]["path"])
    sidecar_path = artifact_path.with_suffix(".json")
    registry_path = pinned_root / "logs/model_registry.json"
    return {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": str(manifest["release"]["commit_sha"]),
        "artifact_sha256": str(manifest["artifact"]["sha256"]),
        "metadata_sha256": sha256_file(sidecar_path),
        "registry_sha256": sha256_file(registry_path),
        "deployment_id": str(manifest["deployment_id"]),
        "paper_run_id": str(manifest["paper_run_id"]),
        "feature_schema_version": feature_schema_version,
        "analysis_universe": ",".join(analysis_universe),
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
    }


def build_epoch(
    *,
    manifest: dict[str, Any],
    pinned_root: Path,
    modules: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    metadata = load_json(pinned_root / "logs/meta_model.json")
    universe = modules["get_runtime_universe"]().analysis_symbols
    feature_schema_version = str(metadata.get("feature_schema_version") or "meta-v3.1-43f")
    release_manifest = build_release_manifest(
        manifest=manifest,
        pinned_root=pinned_root,
        analysis_universe=universe,
        feature_schema_version=feature_schema_version,
    )
    epoch = modules["EvidenceEpoch"](
        epoch_id=str(manifest["epoch_id"]),
        deployment_id=str(manifest["deployment_id"]),
        started_at=datetime.now(timezone.utc).isoformat(),
        code_commit_sha=str(manifest["release"]["commit_sha"]),
        model_version=str(metadata.get("model_version") or metadata.get("version") or manifest["artifact"]["artifact_version"]),
        artifact_sha256=str(manifest["artifact"]["sha256"]),
        feature_schema_version=feature_schema_version,
        analysis_universe=universe,
        analysis_universe_hash=modules["analysis_universe_hash"](universe),
        paper_run_id=str(manifest["paper_run_id"]),
        release_manifest=release_manifest,
    )
    return epoch, release_manifest


def validate_startup_precondition(store: Any, modules: dict[str, Any]) -> dict[str, Any]:
    epoch = store.assert_runtime_epoch_ready(require_active=modules["runtime_evidence_eligible"]())
    return {
        "status": "PASS",
        "runtime_evidence_eligible": modules["runtime_evidence_eligible"](),
        "active_epoch": epoch.to_dict() if epoch else None,
    }


def provision(
    *,
    manifest_path: Path,
    expected_manifest_sha256: str,
    pinned_root: Path,
    dry_run: bool,
) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    if sha256_file(manifest_path) != expected_manifest_sha256:
        raise RuntimeError("manifest_sha256_mismatch")
    if git(pinned_root, "rev-parse", "HEAD") != str(manifest["release"]["commit_sha"]):
        raise RuntimeError("pinned_release_commit_mismatch")
    if git(pinned_root, "rev-parse", "HEAD^{tree}") != str(manifest["release"]["tree_sha"]):
        raise RuntimeError("pinned_release_tree_mismatch")

    env = pinned_environment(manifest, pinned_root)
    previous_env = apply_environment(env)
    try:
        modules = import_pinned_modules(pinned_root)
        runtime_paths = modules["get_runtime_paths"]()
        before_inputs = immutable_input_hashes(manifest_path, manifest, pinned_root)
        epoch, release_manifest = build_epoch(manifest=manifest, pinned_root=pinned_root, modules=modules)
        store = modules["RuntimeEvidenceStore"]()
        evidence_db = store.global_index_path
        active_before = active_epoch_rows(evidence_db)
        create_result = None
        activate_result = None
        precondition = {"status": "NOT_RUN_DRY_RUN"}
        if not dry_run:
            create_result = store.create_evidence_epoch(epoch)
            active_after_create = active_epoch_rows(evidence_db)
            activate_result = store.transition_evidence_epoch(epoch.epoch_id, "ACTIVE")
            precondition = validate_startup_precondition(store, modules)
        else:
            active_after_create = active_before
        active_after = active_epoch_rows(evidence_db)
        after_inputs = immutable_input_hashes(manifest_path, manifest, pinned_root)
    finally:
        restore_environment(previous_env)

    if before_inputs != after_inputs:
        raise RuntimeError("immutable_inputs_changed")
    expected_active = [
        row for row in active_after
        if row["epoch_id"] == str(manifest["epoch_id"])
        and row["deployment_id"] == str(manifest["deployment_id"])
        and row["paper_run_id"] == str(manifest["paper_run_id"])
    ]
    status = "PASS_DRY_RUN" if dry_run else "PASS_OPERATIONAL_STATE_PROVISIONED"
    if not dry_run and (len(active_after) != 1 or len(expected_active) != 1):
        raise RuntimeError("active_epoch_invariant_failed")
    return {
        "contract": R2_CONTRACT_VERSION,
        "status": status,
        "dry_run": dry_run,
        "runtime_activation": "NOT_PERFORMED_AFTER_R2",
        "pinned_runtime": {
            "root": str(pinned_root),
            "commit": git(pinned_root, "rev-parse", "HEAD"),
            "tree": git(pinned_root, "rev-parse", "HEAD^{tree}"),
        },
        "evidence_store": {
            "runtime_evidence_path": str(runtime_paths.runtime_evidence_path),
            "global_index_path": str(evidence_db),
            "active_before": active_before,
            "active_after_create": active_after_create,
            "active_after": active_after,
            "active_epoch_count": len(active_after),
        },
        "epoch_identity": {
            "epoch_id": str(manifest["epoch_id"]),
            "deployment_id": str(manifest["deployment_id"]),
            "paper_run_id": str(manifest["paper_run_id"]),
            "execution_mode": "PAPER",
            "evidence_eligible": True,
            "release_commit": str(manifest["release"]["commit_sha"]),
            "release_tree": str(manifest["release"]["tree_sha"]),
            "artifact_sha256": str(manifest["artifact"]["sha256"]),
        },
        "release_manifest": release_manifest,
        "created_epoch": create_result.to_dict() if create_result else None,
        "activated_epoch": activate_result.to_dict() if activate_result else None,
        "startup_precondition_probe": precondition,
        "immutable_inputs_before": before_inputs,
        "immutable_inputs_after": after_inputs,
        "immutable_inputs_unchanged": before_inputs == after_inputs,
        "allowed_writes": [
            "deployment-specific runtime evidence SQLite/global index",
            "epoch activation audit record",
        ],
        "forbidden_writes_preserved": [
            "logs/meta_model.joblib",
            "logs/meta_model.json",
            "logs/model_registry.json",
            "runtime_activation_p7_manifest.json",
            "pinned runtime release tree",
        ],
        "next_gate": "FRESH_P7_PREFLIGHT_THEN_NEW_G6_AUTHORIZATION",
    }


def write_report(report: dict[str, Any], output_path: Path) -> str:
    payload = canonical_json(report)
    output_path.write_bytes(payload + b"\n")
    digest = sha256_bytes(payload)
    output_path.with_suffix(output_path.suffix + ".sha256").write_text(
        f"{digest}  {output_path.name}\n",
        encoding="utf-8",
    )
    return digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-path", type=Path, default=REPO_ROOT / "runtime_activation_p7_manifest.json")
    parser.add_argument("--expected-manifest-sha256", default=DEFAULT_MANIFEST_SHA256)
    parser.add_argument("--pinned-root", type=Path, default=REPO_ROOT / "runtime/worktrees/pinned-5e8d798")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "runtime_activation_p7_r2_provisioning_report.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = provision(
        manifest_path=args.manifest_path.resolve(),
        expected_manifest_sha256=args.expected_manifest_sha256,
        pinned_root=args.pinned_root.resolve(),
        dry_run=args.dry_run,
    )
    digest = write_report(report, args.output.resolve())
    print(json.dumps({"status": report["status"], "report": str(args.output.resolve()), "sha256": digest}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
