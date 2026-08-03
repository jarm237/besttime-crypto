from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def test_provisioner_copies_and_verifies_immutable_artifact(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    source = tmp_path / "source"
    target = tmp_path / "target"
    (source / "logs").mkdir(parents=True)
    artifact = source / "logs" / "meta_model.joblib"
    artifact.write_bytes(b"immutable-model")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (source / "logs" / "meta_model.json").write_text(
        json.dumps({"artifact_sha256": digest}), encoding="utf-8"
    )

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

    assert result.returncode == 0, result.stderr
    assert (target / "logs" / "meta_model.joblib").read_bytes() == b"immutable-model"
    assert json.loads(result.stdout)["status"] == "PROVISIONED"
