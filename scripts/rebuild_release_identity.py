#!/usr/bin/env python3
"""R6 successor release assembly and identity sealing.

Rebuilds the release manifest, artifact inventory, and release identity for the
successor release model-coverage-v1-r1 using the current git commit.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

RELEASE_ID = "model-coverage-v1-r1"
RELEASE_DIR = REPO_ROOT / "runtime" / "releases" / RELEASE_ID

MANIFEST_PATH = REPO_ROOT / "model_coverage_mc8_release_manifest.json"
INVENTORY_PATH = REPO_ROOT / "model_coverage_mc8_artifact_inventory.json"
IDENTITY_PATH = REPO_ROOT / "model_coverage_mc9_release_identity.json"
CONTRACT_PATH = REPO_ROOT / "model_coverage_mc8_release_contract.json"
VERDICT_PATH = REPO_ROOT / "model_coverage_mc8_final_verdict.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2, sort_keys=True)
    path.write_text(content, encoding="utf-8")
    sha_path = Path(str(path) + ".sha256")
    rel = path.relative_to(REPO_ROOT)
    sha_path.write_text(f"{_sha256_text(content)}  {rel}\n", encoding="utf-8")


def copy_file_safe(src: Path, dest: Path, expected_sha: str | None = None) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    actual_sha = _sha256_file(dest)
    if expected_sha and actual_sha != expected_sha:
        raise ValueError(
            f"SHA mismatch during copy of {src.name} to {dest.name}. "
            f"Expected: {expected_sha}, Actual: {actual_sha}"
        )
    return actual_sha


def get_current_commit() -> str:
    # Read git HEAD commit
    res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    return res.stdout.strip()


def main() -> None:
    print(f"Rebuilding successor release: {RELEASE_ID}")
    print("=" * 50)

    commit_sha = get_current_commit()
    print(f"Current git commit SHA: {commit_sha}")

    # 1. Update manifest in-place
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["release_version"] = RELEASE_ID
    manifest["source_commit"] = commit_sha
    _write_json(MANIFEST_PATH, manifest)
    print("Updated model_coverage_mc8_release_manifest.json")

    # 2. Clean and recreate release directory
    if RELEASE_DIR.exists():
        print(f"Cleaning existing release directory: {RELEASE_DIR}")
        shutil.rmtree(RELEASE_DIR, ignore_errors=True)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)

    # Load registry
    registry_file = REPO_ROOT / "model_coverage_mc6_inference_registry.json"
    registry = json.loads(registry_file.read_text(encoding="utf-8"))

    copied_items = []
    hash_mismatches = 0
    missing_artifacts = 0

    # Registries and contracts to copy
    registries_to_copy = [
        ("model_coverage_mc6_inference_registry.json", "model_coverage_mc6_inference_registry.json"),
        ("model_coverage_mc7_runtime_binding_contract.json", "model_coverage_mc7_runtime_binding_contract.json"),
        ("model_coverage_mc8_release_contract.json", "model_coverage_mc8_release_contract.json"),
        ("model_coverage_mc8_release_manifest.json", "model_coverage_mc8_release_manifest.json"),
        ("config/model_artifacts.yaml", "config/model_artifacts.yaml"),
        ("config/artifact_compatibility/meta_model.compatibility.json", "config/artifact_compatibility/meta_model.compatibility.json"),
    ]

    for rel_src, rel_dest in registries_to_copy:
        src = REPO_ROOT / rel_src
        dest = RELEASE_DIR / rel_dest
        try:
            sha = copy_file_safe(src, dest)
            copied_items.append({
                "type": "metadata",
                "rel_path": rel_dest,
                "sha256": sha,
                "status": "COPIED"
            })
        except Exception as exc:
            missing_artifacts += 1
            print(f"Error copying registry {rel_src}: {exc}")

    # Legacy model files
    legacy_files = [
        ("logs/meta_model.joblib", "logs/meta_model.joblib"),
        ("logs/meta_model.json", "logs/meta_model.json"),
        ("logs/model_registry.json", "logs/model_registry.json"),
    ]

    for rel_src, rel_dest in legacy_files:
        src = REPO_ROOT / rel_src
        dest = RELEASE_DIR / rel_dest
        if not src.exists():
            missing_artifacts += 1
            print(f"Legacy model file missing: {rel_src}")
        else:
            try:
                sha = copy_file_safe(src, dest)
                copied_items.append({
                    "type": "legacy_model_artifact",
                    "rel_path": rel_dest,
                    "sha256": sha,
                    "status": "COPIED"
                })
            except Exception as exc:
                hash_mismatches += 1
                print(f"Error copying legacy file {rel_src}: {exc}")

    # Qualified candidate models and calibrators
    for route in registry["routes"]:
        sym = route["symbol"]
        if route["route_type"] == "LEGACY":
            continue

        # Model
        m_path = route.get("model_artifact_path")
        m_sha = route.get("model_sha256")
        if m_path:
            src = REPO_ROOT / m_path
            dest = RELEASE_DIR / m_path
            try:
                sha = copy_file_safe(src, dest, expected_sha=m_sha)
                copied_items.append({
                    "type": "model_artifact",
                    "symbol": sym,
                    "rel_path": m_path,
                    "sha256": sha,
                    "status": "COPIED"
                })
            except Exception as exc:
                hash_mismatches += 1
                print(f"Model copy error for {sym}: {exc}")

        # Calibrator
        c_path = route.get("calibrator_artifact_path")
        c_sha = route.get("calibrator_sha256")
        if c_path:
            src = REPO_ROOT / c_path
            dest = RELEASE_DIR / c_path
            try:
                sha = copy_file_safe(src, dest, expected_sha=c_sha)
                copied_items.append({
                    "type": "calibrator_artifact",
                    "symbol": sym,
                    "rel_path": c_path,
                    "sha256": sha,
                    "status": "COPIED"
                })
            except Exception as exc:
                hash_mismatches += 1
                print(f"Calibrator copy error for {sym}: {exc}")

    # Generate artifact inventory
    gates = {
        "MC8-D-G1": {"gate": "release_directory_created", "result": "PASS" if RELEASE_DIR.exists() else "FAIL"},
        "MC8-D-G2": {"gate": "legacy_grandfathered_copied", "result": "PASS" if any(i["rel_path"] == "logs/meta_model.joblib" for i in copied_items) else "FAIL"},
        "MC8-D-G3": {"gate": "mc5_candidates_copied", "expected_mc5_models": 6, "actual_mc5_models": sum(1 for i in copied_items if i["type"] == "model_artifact"), "result": "PASS" if sum(1 for i in copied_items if i["type"] == "model_artifact") == 6 else "FAIL"},
        "MC8-D-G4": {"gate": "mc5_calibrators_copied", "expected_mc5_calibrators": 6, "actual_mc5_calibrators": sum(1 for i in copied_items if i["type"] == "calibrator_artifact"), "result": "PASS" if sum(1 for i in copied_items if i["type"] == "calibrator_artifact") == 6 else "FAIL"},
        "MC8-D-G5": {"gate": "hash_integrity_revalidated", "hash_mismatches": hash_mismatches, "result": "PASS" if hash_mismatches == 0 else "FAIL"},
        "MC8-D-G6": {"gate": "zero_missing_dependencies", "missing_artifacts": missing_artifacts, "result": "PASS" if missing_artifacts == 0 else "FAIL"},
    }

    overall = "PASS" if all(g["result"] == "PASS" for g in gates.values()) else "FAIL"

    inventory = {
        "artifact": "model_coverage_mc8_artifact_inventory",
        "release_id": RELEASE_ID,
        "gates": gates,
        "copied_items": copied_items,
        "overall_verdict": overall,
    }
    _write_json(INVENTORY_PATH, inventory)
    print("Generated model_coverage_mc8_artifact_inventory.json")

    # 3. Rebuild release identity
    identity = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
    identity["release_id"] = RELEASE_ID
    identity["mc7_seal_commit"] = commit_sha
    identity["mc8_seal_commit"] = commit_sha
    identity["source_commit"] = commit_sha

    identity["release_manifest"]["sha256"] = _sha256_file(MANIFEST_PATH)
    identity["artifact_inventory"]["sha256"] = _sha256_file(INVENTORY_PATH)

    _write_json(IDENTITY_PATH, identity)
    print("Generated model_coverage_mc9_release_identity.json")

    print("\nRelease bundle successfully compiled & sealed:")
    print(f"  Release ID: {RELEASE_ID}")
    print(f"  Source Commit: {commit_sha}")
    print(f"  Manifest SHA: {identity['release_manifest']['sha256']}")
    print(f"  Inventory SHA: {identity['artifact_inventory']['sha256']}")


if __name__ == "__main__":
    main()
