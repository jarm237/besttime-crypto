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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-worktree", type=Path, required=True)
    parser.add_argument("--artifact", default="logs/meta_model.joblib")
    parser.add_argument("--metadata", default="logs/meta_model.json")
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    target_root = args.target_worktree.resolve()
    source_artifact = (source_root / args.artifact).resolve()
    source_metadata = (source_root / args.metadata).resolve()
    target_artifact = (target_root / args.artifact).resolve()
    target_metadata = (target_root / args.metadata).resolve()
    if not source_artifact.is_relative_to(source_root):
        raise RuntimeError("artifact source escapes source root")
    if not source_metadata.is_relative_to(source_root):
        raise RuntimeError("metadata source escapes source root")
    if not target_artifact.is_relative_to(target_root):
        raise RuntimeError("artifact target escapes pinned worktree")
    if not target_metadata.is_relative_to(target_root):
        raise RuntimeError("metadata target escapes pinned worktree")
    if not source_artifact.is_file() or not source_metadata.is_file():
        raise RuntimeError("canonical artifact or metadata is missing")

    metadata = json.loads(source_metadata.read_text(encoding="utf-8"))
    metadata_sha = str(
        metadata.get("artifact_sha256") or metadata.get("sha256") or ""
    )
    expected_sha = str(args.expected_sha256 or metadata_sha)
    if not expected_sha:
        raise RuntimeError("expected artifact SHA is unavailable")
    _copy_verified(source_artifact, target_artifact, expected_sha)
    _copy_verified(source_metadata, target_metadata, None)

    provisioned_metadata = json.loads(target_metadata.read_text(encoding="utf-8"))
    if str(provisioned_metadata.get("artifact_sha256") or "") != expected_sha:
        raise RuntimeError("provisioned metadata does not pin the artifact SHA")
    print(json.dumps({
        "artifact": str(target_artifact),
        "metadata": str(target_metadata),
        "artifact_sha256": _sha256(target_artifact),
        "status": "PROVISIONED",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
