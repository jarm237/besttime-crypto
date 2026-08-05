#!/usr/bin/env python3
"""Provision immutable ignored artifacts into a detached runtime worktree."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_verified(source: Path, target: Path, expected_sha256: str | None) -> None:
    source_sha = _sha256(source)
    if expected_sha256 and source_sha != expected_sha256:
        raise RuntimeError(
            f"source artifact SHA mismatch: expected={expected_sha256} actual={source_sha}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target_sha = _sha256(target)
        if target_sha != source_sha:
            raise RuntimeError(
                f"refusing to overwrite conflicting pinned artifact: {target}"
            )
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        if _sha256(temporary) != source_sha:
            raise RuntimeError("artifact changed while provisioning")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _normalize_registry_path(raw: str) -> Path:
    return Path(str(raw).replace("\\", "/"))


def _create_staging_directory(target_root: Path) -> Path:
    return Path(tempfile.mkdtemp(prefix=".staging.", dir=str(target_root.parent)))


def _cleanup_staging(staging_root: Path) -> None:
    shutil.rmtree(staging_root, ignore_errors=True)


def _publish_staged_files(staging_root: Path, target_root: Path, rel_paths: list[Path]) -> None:
    backup_root = staging_root / "backup"
    created: list[Path] = []
    restored: list[Path] = []
    try:
        for rel_path in rel_paths:
            source_file = staging_root / rel_path
            target_file = target_root / rel_path
            backup_file = backup_root / rel_path
            target_file.parent.mkdir(parents=True, exist_ok=True)
            if target_file.exists():
                backup_file.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target_file, backup_file)
                restored.append(rel_path)
            os.replace(source_file, target_file)
            created.append(rel_path)
        if backup_root.exists():
            shutil.rmtree(backup_root)
    except Exception:
        for rel_path in reversed(created):
            target_file = target_root / rel_path
            if target_file.exists():
                target_file.unlink(missing_ok=True)
        for rel_path in restored:
            backup_file = backup_root / rel_path
            target_file = target_root / rel_path
            if backup_file.exists():
                target_file.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup_file, target_file)
        raise


def _load_registry_record(registry_path: Path, model_name: str) -> dict[str, object]:
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise RuntimeError("registry payload is malformed")
    active = [
        record for record in records
        if isinstance(record, dict)
        and record.get("model_name") == model_name
        and record.get("status") == "production"
    ]
    if not active:
        raise RuntimeError(f"production registry record missing for {model_name}")
    if len(active) > 1:
        raise RuntimeError(f"multiple production registry records found for {model_name}")
    return active[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-worktree", type=Path, required=True)
    parser.add_argument("--artifact", default="logs/meta_model.joblib")
    parser.add_argument("--metadata", default="logs/meta_model.json")
    parser.add_argument("--registry", default="logs/model_registry.json")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--expected-registry-sha256")
    parser.add_argument("--release-sha", default="")
    parser.add_argument("--manifest", default="logs/pinned_runtime_manifest.json")
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    target_root = args.target_worktree.resolve()
    source_artifact = (source_root / args.artifact).resolve()
    source_metadata = (source_root / args.metadata).resolve()
    source_registry = (source_root / args.registry).resolve()
    staging_root = _create_staging_directory(target_root)
    try:
        staged_artifact = (staging_root / args.artifact).resolve()
        staged_metadata = (staging_root / args.metadata).resolve()
        staged_registry = (staging_root / args.registry).resolve()
        staged_manifest = (staging_root / args.manifest).resolve()

        target_artifact = (target_root / args.artifact).resolve()
        target_metadata = (target_root / args.metadata).resolve()
        target_registry = (target_root / args.registry).resolve()
        target_manifest = (target_root / args.manifest).resolve()

        if not _is_relative_to(source_artifact, source_root):
            raise RuntimeError("artifact source escapes source root")
        if not _is_relative_to(source_metadata, source_root):
            raise RuntimeError("metadata source escapes source root")
        if not _is_relative_to(source_registry, source_root):
            raise RuntimeError("registry source escapes source root")
        if not _is_relative_to(target_artifact, target_root):
            raise RuntimeError("artifact target escapes pinned worktree")
        if not _is_relative_to(target_metadata, target_root):
            raise RuntimeError("metadata target escapes pinned worktree")
        if not _is_relative_to(target_registry, target_root):
            raise RuntimeError("registry target escapes pinned worktree")
        if not _is_relative_to(target_manifest, target_root):
            raise RuntimeError("manifest target escapes pinned worktree")
        if not source_artifact.is_file() or not source_metadata.is_file() or not source_registry.is_file():
            raise RuntimeError("canonical artifact, metadata, or registry is missing")

        metadata = json.loads(source_metadata.read_text(encoding="utf-8"))
        metadata_sha = str(
            metadata.get("artifact_sha256") or metadata.get("sha256") or ""
        )
        expected_sha = str(args.expected_sha256 or metadata_sha)
        if not expected_sha:
            raise RuntimeError("expected artifact SHA is unavailable")

        source_registry_sha = _sha256(source_registry)
        if args.expected_registry_sha256 and source_registry_sha != args.expected_registry_sha256:
            raise RuntimeError(
                f"source registry SHA mismatch: expected={args.expected_registry_sha256} actual={source_registry_sha}"
            )

        _copy_verified(source_artifact, staged_artifact, expected_sha)
        _copy_verified(source_metadata, staged_metadata, None)
        _copy_verified(source_registry, staged_registry, args.expected_registry_sha256)

        provisioned_metadata = json.loads(staged_metadata.read_text(encoding="utf-8"))
        if str(provisioned_metadata.get("artifact_sha256") or "") != expected_sha:
            raise RuntimeError("provisioned metadata does not pin the artifact SHA")

        registry_record = _load_registry_record(staged_registry, "meta_model")
        registry_artifact_path = _normalize_registry_path(str(registry_record.get("artifact_path") or ""))
        if registry_artifact_path.is_absolute():
            raise RuntimeError("registry artifact path is absolute and not portable")
        registry_target = (staging_root / registry_artifact_path).resolve()
        if not _is_relative_to(registry_target, staging_root):
            raise RuntimeError("registry artifact path escapes pinned worktree")
        if registry_target != staged_artifact:
            raise RuntimeError("registry points to an unexpected artifact path")
        registry_artifact_sha = str(registry_record.get("sha256") or "")
        registry_metrics_artifact_sha = str((registry_record.get("metrics") or {}).get("artifact_sha256") or "")
        if registry_artifact_sha != expected_sha or registry_metrics_artifact_sha != expected_sha:
            raise RuntimeError("registry artifact binding does not match the pinned artifact SHA")

        manifest = {
            "release_sha": str(args.release_sha or ""),
            "meta_artifact_sha256": _sha256(staged_artifact),
            "metadata_sha256": _sha256(staged_metadata),
            "registry_sha256": _sha256(staged_registry),
            "registry_model": "meta_model",
            "registry_environment": "production",
            "registry_artifact_sha256": expected_sha,
            "registry_artifact_inside_pinned_root": True,
        }
        staged_manifest.parent.mkdir(parents=True, exist_ok=True)
        staged_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        rel_paths = [Path(args.artifact), Path(args.metadata), Path(args.registry), Path(args.manifest)]
        _publish_staged_files(staging_root, target_root, rel_paths)

        print(json.dumps({
            "artifact": str(target_artifact),
            "metadata": str(target_metadata),
            "registry": str(target_registry),
            "manifest": str(target_manifest),
            "artifact_sha256": _sha256(target_artifact),
            "registry_sha256": _sha256(target_registry),
            "status": "PROVISIONED",
            "registry_artifact_inside_pinned_root": True,
        }, sort_keys=True))
        return 0
    finally:
        _cleanup_staging(staging_root)


if __name__ == "__main__":
    raise SystemExit(main())
