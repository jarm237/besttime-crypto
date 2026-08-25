#!/usr/bin/env python3
"""MC8-B/C — Pinned Runtime Builder & Canonical Release Manifest Generator.

1. Installs a clean git worktree checked out at the exact MC7 seal commit
   (94407d3483bb01eccf0e86882cef258dcbb646e9) under `runtime/worktrees/pinned-94407d3`.
2. Verifies the worktree state (head commit, no uncommitted files).
3. Generates the canonical release manifest model_coverage_mc8_release_manifest.json.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MC8_CONTRACT = REPO_ROOT / "model_coverage_mc8_release_contract.json"
MC6_REGISTRY = REPO_ROOT / "model_coverage_mc6_inference_registry.json"
MC7_CONTRACT = REPO_ROOT / "model_coverage_mc7_runtime_binding_contract.json"
MC8_MANIFEST = REPO_ROOT / "model_coverage_mc8_release_manifest.json"
MC8_REPORT   = REPO_ROOT / "model_coverage_mc8_pinned_runtime_report.json"

TARGET_COMMIT = "94407d3483bb01eccf0e86882cef258dcbb646e9"
WORKTREE_PATH = REPO_ROOT / "runtime" / "worktrees" / "pinned-94407d3"


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


def construct_worktree() -> tuple[str, bool]:
    # Prune any dead worktrees first to prevent lock/already-exists errors
    try:
        subprocess.check_call(["git", "worktree", "prune"], cwd=str(REPO_ROOT))
    except Exception:
        pass

    if WORKTREE_PATH.exists():
        print(f"Removing existing worktree path {WORKTREE_PATH}...")
        try:
            subprocess.check_call(
                ["git", "worktree", "remove", "--force", str(WORKTREE_PATH)],
                cwd=str(REPO_ROOT),
            )
        except Exception:
            # Fallback to shutil if git worktree remove fails or isn't registered
            shutil.rmtree(WORKTREE_PATH, ignore_errors=True)

    print(f"Adding git worktree at {WORKTREE_PATH} check out at {TARGET_COMMIT}...")
    subprocess.check_call(
        ["git", "worktree", "add", "--force", str(WORKTREE_PATH), TARGET_COMMIT],
        cwd=str(REPO_ROOT),
    )

    # Verify head in worktree
    out = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(WORKTREE_PATH)
    ).decode().strip()

    # Check status in worktree (must have no modifications)
    status_out = subprocess.check_output(
        ["git", "status", "--porcelain", "-uno"], cwd=str(WORKTREE_PATH)
    ).decode().strip()
    is_clean = len(status_out) == 0

    return out, is_clean


def main() -> None:
    print("MC8-B/C: Pinned Runtime Builder …")

    # Load inputs
    contract = json.loads(MC8_CONTRACT.read_text(encoding="utf-8"))
    registry = json.loads(MC6_REGISTRY.read_text(encoding="utf-8"))
    mc7_contract = json.loads(MC7_CONTRACT.read_text(encoding="utf-8"))

    # Setup worktree
    actual_commit, is_clean = construct_worktree()

    gates = {}
    gates["MC8-B-G1"] = {
        "gate": "worktree_created",
        "path": str(WORKTREE_PATH.relative_to(REPO_ROOT)),
        "result": "PASS" if WORKTREE_PATH.exists() else "FAIL",
    }
    gates["MC8-B-G2"] = {
        "gate": "exact_head_commit",
        "expected": TARGET_COMMIT,
        "actual": actual_commit,
        "result": "PASS" if actual_commit == TARGET_COMMIT else "FAIL",
    }
    gates["MC8-B-G3"] = {
        "gate": "worktree_clean_no_modifications",
        "result": "PASS" if is_clean else "FAIL",
    }

    # Generate Manifest
    routes_details = {}
    for r in registry["routes"]:
        sym = r["symbol"]
        routes_details[sym] = {
            "symbol": sym,
            "route_type": r["route_type"],
            "route_version": r["route_version"],
            "model_sha256": r.get("model_sha256"),
            "calibrator_sha256": r.get("calibrator_sha256"),
            "feature_schema": r["feature_schema"],
            "feature_schema_version": r["feature_schema_version"],
            "qualification_verdict": r["qualification_verdict"],
        }

    manifest = {
        "release_version": "model-coverage-v1",
        "source_commit": TARGET_COMMIT,
        "canonical_universe": 22,
        "effective_runtime_universe": 9,
        "registry": registry,
        "runtime_binding": mc7_contract,
        "routes": routes_details,
        "disabled_symbols": sorted(mc7_contract["inference_disabled_symbols"]),
        "contracts": {
            "inference_contract_version": "explicit-inference/v1",
            "feature_contract_version": "features_v5_4f",
        },
        "provenance": {
            "mc6_registry_seal": contract["mc6_registry_seal"],
            "mc6_registry_sha256": contract["mc6_registry_sha256"],
            "mc7_verdict_sha256": contract["mc7_verdict_sha256"],
        },
    }
    _write_json(MC8_MANIFEST, manifest)

    overall = "PASS" if all(g["result"] == "PASS" for g in gates.values()) else "FAIL"

    report = {
        "artifact": "model_coverage_mc8_pinned_runtime_report",
        "gates": gates,
        "overall_verdict": overall,
        "manifest_sha256": _sha256_file(MC8_MANIFEST),
    }
    _write_json(MC8_REPORT, report)

    for gk, gv in gates.items():
        print(f"  {gk} {gv['gate']:<45} {gv['result']}")
    print(f"  Manifest written to model_coverage_mc8_release_manifest.json")
    print(f"  Overall: {overall}")


if __name__ == "__main__":
    main()
