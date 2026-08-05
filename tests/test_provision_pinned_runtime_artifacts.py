from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _write_source_bundle(tmp_path: Path, *, artifact_bytes: bytes = b"immutable-model") -> tuple[Path, Path, str]:
    source = tmp_path / "source"
    target = tmp_path / "target"
    logs_dir = source / "logs"
    logs_dir.mkdir(parents=True)

    artifact = logs_dir / "meta_model.joblib"
    artifact.write_bytes(artifact_bytes)
    artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()
    registry = {
        "records": [
            {
                "model_name": "meta_model",
                "version": "v3.1",
                "status": "production",
                "artifact_path": "logs\\meta_model.joblib",
                "sha256": artifact_sha,
                "schema_version": "meta-v3.1-43f",
                "metrics": {"artifact_sha256": artifact_sha},
                "registered_at": "2026-07-14T15:14:19.865276+00:00",
            }
        ]
    }
    (source / "logs" / "meta_model.json").write_text(
        json.dumps({"artifact_sha256": artifact_sha, "model_version": "v3.1"}), encoding="utf-8"
    )
    (source / "logs" / "model_registry.json").write_text(json.dumps(registry), encoding="utf-8")
    return source, target, artifact_sha


def test_provisioner_copies_and_verifies_immutable_artifact_and_registry(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    source, target, digest = _write_source_bundle(tmp_path)
    registry_sha = hashlib.sha256((source / "logs" / "model_registry.json").read_bytes()).hexdigest()

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "provision_pinned_runtime_artifacts.py"),
            "--source-root", str(source),
            "--target-worktree", str(target),
            "--expected-sha256", digest,
            "--expected-registry-sha256", registry_sha,
            "--release-sha", "e341d213b84603930cf2d3013f97bc4d0a23c32c",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (target / "logs" / "meta_model.joblib").read_bytes() == b"immutable-model"
    assert (target / "logs" / "model_registry.json").exists()
    manifest = json.loads((target / "logs" / "pinned_runtime_manifest.json").read_text(encoding="utf-8"))
    assert manifest["release_sha"] == "e341d213b84603930cf2d3013f97bc4d0a23c32c"
    assert manifest["meta_artifact_sha256"] == digest
    assert manifest["registry_sha256"] == registry_sha
    assert manifest["registry_artifact_sha256"] == digest
    assert manifest["registry_artifact_inside_pinned_root"] is True
    assert json.loads(result.stdout)["status"] == "PROVISIONED"


def test_provisioner_rejects_missing_registry(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    source, target, digest = _write_source_bundle(tmp_path)
    (source / "logs" / "model_registry.json").unlink()

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "provision_pinned_runtime_artifacts.py"),
            "--source-root", str(source),
            "--target-worktree", str(target),
            "--expected-sha256", digest,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "canonical artifact, metadata, or registry is missing" in result.stderr


def test_provisioner_rejects_registry_path_outside_target_root(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    source, target, digest = _write_source_bundle(tmp_path)
    registry = json.loads((source / "logs" / "model_registry.json").read_text(encoding="utf-8"))
    registry["records"][0]["artifact_path"] = str(tmp_path / "outside" / "meta_model.joblib")
    (source / "logs" / "model_registry.json").write_text(json.dumps(registry), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "provision_pinned_runtime_artifacts.py"),
            "--source-root", str(source),
            "--target-worktree", str(target),
            "--expected-sha256", digest,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "registry artifact path is absolute and not portable" in result.stderr


def test_provisioner_rejects_registry_relative_traversal_path_outside_target_root(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    source, target, digest = _write_source_bundle(tmp_path)
    registry = json.loads((source / "logs" / "model_registry.json").read_text(encoding="utf-8"))
    registry["records"][0]["artifact_path"] = "../logs/meta_model.joblib"
    (source / "logs" / "model_registry.json").write_text(json.dumps(registry), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "provision_pinned_runtime_artifacts.py"),
            "--source-root", str(source),
            "--target-worktree", str(target),
            "--expected-sha256", digest,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "registry artifact path escapes pinned worktree" in result.stderr


def test_provisioner_rejects_registry_with_multiple_production_records(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    source, target, digest = _write_source_bundle(tmp_path)
    registry = json.loads((source / "logs" / "model_registry.json").read_text(encoding="utf-8"))
    conflicting = dict(registry["records"][0])
    conflicting["version"] = "v3.2"
    registry["records"].append(conflicting)
    (source / "logs" / "model_registry.json").write_text(json.dumps(registry), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "provision_pinned_runtime_artifacts.py"),
            "--source-root", str(source),
            "--target-worktree", str(target),
            "--expected-sha256", digest,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "multiple production registry records" in result.stderr


def test_provisioner_rejects_registry_artifact_sha_mismatch(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    source, target, digest = _write_source_bundle(tmp_path)
    registry = json.loads((source / "logs" / "model_registry.json").read_text(encoding="utf-8"))
    registry["records"][0]["sha256"] = "deadbeef"
    registry["records"][0]["metrics"]["artifact_sha256"] = "deadbeef"
    (source / "logs" / "model_registry.json").write_text(json.dumps(registry), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "provision_pinned_runtime_artifacts.py"),
            "--source-root", str(source),
            "--target-worktree", str(target),
            "--expected-sha256", digest,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "registry artifact binding does not match the pinned artifact SHA" in result.stderr


def test_provisioner_does_not_leave_partial_bundle_on_failure(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    source, target, digest = _write_source_bundle(tmp_path)
    registry = json.loads((source / "logs" / "model_registry.json").read_text(encoding="utf-8"))
    registry["records"][0]["sha256"] = "deadbeef"
    registry["records"][0]["metrics"]["artifact_sha256"] = "deadbeef"
    (source / "logs" / "model_registry.json").write_text(json.dumps(registry), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "provision_pinned_runtime_artifacts.py"),
            "--source-root", str(source),
            "--target-worktree", str(target),
            "--expected-sha256", digest,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert not (target / "logs" / "meta_model.joblib").exists()
    assert not (target / "logs" / "model_registry.json").exists()
    assert not (target / "logs" / "pinned_runtime_manifest.json").exists()


def test_provisioner_preserves_existing_valid_target_on_failure(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    source, target, digest = _write_source_bundle(tmp_path)
    registry_sha = hashlib.sha256((source / "logs" / "model_registry.json").read_bytes()).hexdigest()

    first = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "provision_pinned_runtime_artifacts.py"),
            "--source-root", str(source),
            "--target-worktree", str(target),
            "--expected-sha256", digest,
            "--expected-registry-sha256", registry_sha,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, first.stderr
    original_manifest = (target / "logs" / "pinned_runtime_manifest.json").read_text(encoding="utf-8")
    original_artifact = (target / "logs" / "meta_model.joblib").read_bytes()

    registry = json.loads((source / "logs" / "model_registry.json").read_text(encoding="utf-8"))
    registry["records"][0]["sha256"] = "deadbeef"
    (source / "logs" / "model_registry.json").write_text(json.dumps(registry), encoding="utf-8")

    second = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "provision_pinned_runtime_artifacts.py"),
            "--source-root", str(source),
            "--target-worktree", str(target),
            "--expected-sha256", digest,
            "--expected-registry-sha256", registry_sha,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert second.returncode != 0
    assert (target / "logs" / "meta_model.joblib").read_bytes() == original_artifact
    assert (target / "logs" / "pinned_runtime_manifest.json").read_text(encoding="utf-8") == original_manifest


def test_provisioner_is_idempotent_and_preserves_existing_target(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    source, target, digest = _write_source_bundle(tmp_path)
    registry_sha = hashlib.sha256((source / "logs" / "model_registry.json").read_bytes()).hexdigest()

    first = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "provision_pinned_runtime_artifacts.py"),
            "--source-root", str(source),
            "--target-worktree", str(target),
            "--expected-sha256", digest,
            "--expected-registry-sha256", registry_sha,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    second = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "provision_pinned_runtime_artifacts.py"),
            "--source-root", str(source),
            "--target-worktree", str(target),
            "--expected-sha256", digest,
            "--expected-registry-sha256", registry_sha,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (target / "logs" / "meta_model.joblib").read_bytes() == b"immutable-model"
    assert json.loads(second.stdout)["status"] == "PROVISIONED"
