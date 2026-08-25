#!/usr/bin/env python3
"""MC8-D — Artifact Bundle Assembly.

Materializes all code, metadata registries, models, and calibrators into the
self-contained release directory: `runtime/releases/model-coverage-v1`.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MC8_CONTRACT = REPO_ROOT / "model_coverage_mc8_release_contract.json"
RELEASE_DIR  = REPO_ROOT / "runtime" / "releases" / "model-coverage-v1"
INVENTORY    = REPO_ROOT / "model_coverage_mc8_artifact_inventory.json"


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


def main() -> None:
    print("MC8-D: Artifact Bundle Assembly …")

    if RELEASE_DIR.exists():
        print(f"Cleaning existing release directory: {RELEASE_DIR}")
        shutil.rmtree(RELEASE_DIR, ignore_errors=True)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)

    contract = json.loads(MC8_CONTRACT.read_text(encoding="utf-8"))

    # Load registry to find source file paths
    registry_file = REPO_ROOT / "model_coverage_mc6_inference_registry.json"
    registry = json.loads(registry_file.read_text(encoding="utf-8"))

    copied_items = []
    hash_mismatches = 0
    missing_artifacts = 0

    # 1. Copy registries and contracts
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

    # 2. Copy legacy model and json metadata
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

    # 3. Copy per-symbol candidate model and calibrator artifacts
    for route in registry["routes"]:
        sym = route["symbol"]
        if route["route_type"] == "LEGACY":
            continue

        # Model artifact
        m_path = route.get("model_artifact_path")
        m_sha = route.get("model_sha256")
        if m_path:
            src = REPO_ROOT / m_path
            dest = RELEASE_DIR / m_path
            if not src.exists():
                missing_artifacts += 1
                print(f"Qualified model file missing for {sym}: {m_path}")
            else:
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

        # Calibrator artifact
        c_path = route.get("calibrator_artifact_path")
        c_sha = route.get("calibrator_sha256")
        if c_path:
            src = REPO_ROOT / c_path
            dest = RELEASE_DIR / c_path
            if not src.exists():
                missing_artifacts += 1
                print(f"Qualified calibrator file missing for {sym}: {c_path}")
            else:
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

    # Gates
    gates = {}
    gates["MC8-D-G1"] = {
        "gate": "release_directory_created",
        "result": "PASS" if RELEASE_DIR.exists() else "FAIL"
    }
    gates["MC8-D-G2"] = {
        "gate": "legacy_grandfathered_copied",
        "result": "PASS" if any(i["rel_path"] == "logs/meta_model.joblib" for i in copied_items) else "FAIL"
    }
    gates["MC8-D-G3"] = {
        "gate": "mc5_candidates_copied",
        "expected_mc5_models": 6,
        "actual_mc5_models": sum(1 for i in copied_items if i["type"] == "model_artifact"),
        "result": "PASS" if sum(1 for i in copied_items if i["type"] == "model_artifact") == 6 else "FAIL"
    }
    gates["MC8-D-G4"] = {
        "gate": "mc5_calibrators_copied",
        "expected_mc5_calibrators": 6,
        "actual_mc5_calibrators": sum(1 for i in copied_items if i["type"] == "calibrator_artifact"),
        "result": "PASS" if sum(1 for i in copied_items if i["type"] == "calibrator_artifact") == 6 else "FAIL"
    }
    gates["MC8-D-G5"] = {
        "gate": "hash_integrity_revalidated",
        "hash_mismatches": hash_mismatches,
        "result": "PASS" if hash_mismatches == 0 else "FAIL"
    }
    gates["MC8-D-G6"] = {
        "gate": "zero_missing_dependencies",
        "missing_artifacts": missing_artifacts,
        "result": "PASS" if missing_artifacts == 0 else "FAIL"
    }

    overall = "PASS" if all(g["result"] == "PASS" for g in gates.values()) else "FAIL"

    inventory = {
        "artifact": "model_coverage_mc8_artifact_inventory",
        "release_id": "model-coverage-v1",
        "gates": gates,
        "copied_items": copied_items,
        "overall_verdict": overall,
    }
    _write_json(INVENTORY, inventory)

    for gk, gv in gates.items():
        print(f"  {gk} {gv['gate']:<45} {gv['result']}")
    print(f"  Overall: {overall}")
    print(f"  Copied items count: {len(copied_items)}")


if __name__ == "__main__":
    main()
