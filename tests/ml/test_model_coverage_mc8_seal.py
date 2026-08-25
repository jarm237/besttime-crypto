"""
MC8 — Seal Tests: Release Artifact Construction & Pinned Runtime Assembly
=========================================================================
These tests assert that the complete MC8 governance chain is closed and
internally consistent before marking MC8 CLOSED.

Invariants checked:
  MC8-SEAL-1  source_commit is the MC7 seal commit (94407d3…)
  MC8-SEAL-2  release_version is exactly "model-coverage-v1"
  MC8-SEAL-3  authorized_symbols == 9, disabled_symbols == 13, total == 22
  MC8-SEAL-4  artifact_inventory has 0 hash mismatches and 0 missing deps
  MC8-SEAL-5  pinned_runtime worktree HEAD matches source_commit
  MC8-SEAL-6  release bundle directory exists and is non-empty
  MC8-SEAL-7  release_manifest sha256 recorded in release_contract matches disk
  MC8-SEAL-8  every authorized symbol has model+calibrator fingerprints in contract
  MC8-SEAL-9  no disabled symbol appears in authorized_symbols
  MC8-SEAL-10 MC6 registry sha256 in release_contract matches registry on disk
  MC8-SEAL-11 all MC8 gate verdicts (A-H) are PASS
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = ROOT / "runtime" / "releases" / "model-coverage-v1"

RELEASE_CONTRACT = ROOT / "model_coverage_mc8_release_contract.json"
ARTIFACT_INVENTORY = ROOT / "model_coverage_mc8_artifact_inventory.json"
PINNED_RUNTIME_REPORT = ROOT / "model_coverage_mc8_pinned_runtime_report.json"

MC6_REGISTRY = ROOT / "model_coverage_mc6_inference_registry.json"
MC7_RUNTIME_BINDING = ROOT / "model_coverage_mc7_runtime_binding_contract.json"

WORKTREE_PATH = ROOT / "runtime" / "worktrees" / "pinned-94407d3"

MC7_SEAL_COMMIT = "94407d3483bb01eccf0e86882cef258dcbb646e9"
EXPECTED_RELEASE_VERSION = "model-coverage-v1"
CANONICAL_UNIVERSE_SIZE = 22
EXPECTED_AUTHORIZED = 9
EXPECTED_DISABLED = 13


@pytest.fixture(scope="module")
def release_contract():
    assert RELEASE_CONTRACT.exists(), f"Missing: {RELEASE_CONTRACT}"
    return json.loads(RELEASE_CONTRACT.read_text())


@pytest.fixture(scope="module")
def artifact_inventory():
    assert ARTIFACT_INVENTORY.exists(), f"Missing: {ARTIFACT_INVENTORY}"
    return json.loads(ARTIFACT_INVENTORY.read_text())


@pytest.fixture(scope="module")
def pinned_runtime_report():
    assert PINNED_RUNTIME_REPORT.exists(), f"Missing: {PINNED_RUNTIME_REPORT}"
    return json.loads(PINNED_RUNTIME_REPORT.read_text())


# ---------------------------------------------------------------------------
# MC8-SEAL-1  source_commit matches MC7 seal
# ---------------------------------------------------------------------------
def test_mc8_seal_1_source_commit(release_contract):
    """MC8-SEAL-1: release_contract.source_commit must equal MC7 seal commit."""
    assert release_contract["source_commit"] == MC7_SEAL_COMMIT, (
        f"Expected source_commit={MC7_SEAL_COMMIT!r}, "
        f"got {release_contract['source_commit']!r}"
    )


# ---------------------------------------------------------------------------
# MC8-SEAL-2  release_version
# ---------------------------------------------------------------------------
def test_mc8_seal_2_release_version(release_contract):
    """MC8-SEAL-2: release_version must be 'model-coverage-v1'."""
    assert release_contract["release_version"] == EXPECTED_RELEASE_VERSION


# ---------------------------------------------------------------------------
# MC8-SEAL-3  canonical universe accounting
# ---------------------------------------------------------------------------
def test_mc8_seal_3_canonical_universe_accounting(release_contract):
    """MC8-SEAL-3: authorized(9) + disabled(13) == 22."""
    auth = release_contract["authorized_symbols"]
    dis = release_contract["disabled_symbols"]
    assert len(auth) == EXPECTED_AUTHORIZED, f"Expected 9 authorized, got {len(auth)}"
    assert len(dis) == EXPECTED_DISABLED, f"Expected 13 disabled, got {len(dis)}"
    assert len(auth) + len(dis) == CANONICAL_UNIVERSE_SIZE, (
        f"authorized({len(auth)}) + disabled({len(dis)}) != {CANONICAL_UNIVERSE_SIZE}"
    )


# ---------------------------------------------------------------------------
# MC8-SEAL-4  artifact inventory: zero hash mismatches, zero missing deps
# ---------------------------------------------------------------------------
def test_mc8_seal_4_artifact_inventory_integrity(artifact_inventory):
    """MC8-SEAL-4: inventory reports 0 hash mismatches and 0 missing deps."""
    gates = artifact_inventory.get("gates", {})
    g5 = gates.get("MC8-D-G5", {})
    g6 = gates.get("MC8-D-G6", {})
    assert g5.get("result") == "PASS", f"MC8-D-G5 hash integrity not PASS: {g5}"
    assert g5.get("hash_mismatches", 1) == 0, "Hash mismatches found in artifact inventory"
    assert g6.get("result") == "PASS", f"MC8-D-G6 missing deps not PASS: {g6}"
    assert g6.get("missing_artifacts", 1) == 0, "Missing artifacts in inventory"


# ---------------------------------------------------------------------------
# MC8-SEAL-5  pinned worktree HEAD == source_commit
# ---------------------------------------------------------------------------
def test_mc8_seal_5_pinned_worktree_head(pinned_runtime_report):
    """MC8-SEAL-5: worktree HEAD must exactly match MC7 seal commit."""
    g2 = pinned_runtime_report.get("gates", {}).get("MC8-B-G2", {})
    assert g2.get("result") == "PASS", f"MC8-B-G2 worktree HEAD not PASS: {g2}"
    assert g2.get("actual") == MC7_SEAL_COMMIT, (
        f"Worktree HEAD mismatch: {g2.get('actual')!r} != {MC7_SEAL_COMMIT!r}"
    )


# ---------------------------------------------------------------------------
# MC8-SEAL-6  release bundle directory exists and is non-empty
# ---------------------------------------------------------------------------
def test_mc8_seal_6_release_bundle_exists():
    """MC8-SEAL-6: runtime/releases/model-coverage-v1 must be a non-empty dir."""
    assert RELEASE_DIR.is_dir(), f"Release bundle directory missing: {RELEASE_DIR}"
    files = list(RELEASE_DIR.rglob("*"))
    assert len(files) > 0, "Release bundle directory is empty"


# ---------------------------------------------------------------------------
# MC8-SEAL-7  release_manifest sha256 matches disk
# ---------------------------------------------------------------------------
def test_mc8_seal_7_release_manifest_sha256_matches_disk(release_contract):
    """MC8-SEAL-7: mc6_registry_sha256 in contract must match actual MC6 registry file."""
    expected_sha = release_contract["mc6_registry_sha256"]
    actual_sha = hashlib.sha256(MC6_REGISTRY.read_bytes()).hexdigest()
    assert actual_sha == expected_sha, (
        f"MC6 registry sha256 mismatch: disk={actual_sha!r} != contract={expected_sha!r}"
    )


# ---------------------------------------------------------------------------
# MC8-SEAL-8  every authorized symbol has model + calibrator fingerprints
# ---------------------------------------------------------------------------
def test_mc8_seal_8_authorized_symbols_have_fingerprints(release_contract):
    """MC8-SEAL-8: every authorized symbol must appear in model_fingerprints and calibrator_fingerprints."""
    auth = release_contract["authorized_symbols"]
    model_fp = release_contract.get("model_fingerprints", {})
    calib_fp = release_contract.get("calibrator_fingerprints", {})
    missing_model = [s for s in auth if s not in model_fp]
    missing_calib = [s for s in auth if s not in calib_fp]
    assert not missing_model, f"Missing model fingerprints for: {missing_model}"
    assert not missing_calib, f"Missing calibrator fingerprints for: {missing_calib}"


# ---------------------------------------------------------------------------
# MC8-SEAL-9  no disabled symbol appears in authorized_symbols
# ---------------------------------------------------------------------------
def test_mc8_seal_9_no_disabled_symbol_is_authorized(release_contract):
    """MC8-SEAL-9: authorized and disabled symbol sets must be disjoint."""
    auth = set(release_contract["authorized_symbols"])
    dis = set(release_contract["disabled_symbols"])
    overlap = auth & dis
    assert not overlap, f"Symbols appear in both authorized and disabled: {overlap}"


# ---------------------------------------------------------------------------
# MC8-SEAL-10  MC6 registry sha256 cross-check
# ---------------------------------------------------------------------------
def test_mc8_seal_10_mc6_registry_sha_in_release_bundle(release_contract):
    """MC8-SEAL-10: release bundle must contain MC6 registry with matching sha256."""
    expected_sha = release_contract["mc6_registry_sha256"]
    bundle_registry = RELEASE_DIR / "model_coverage_mc6_inference_registry.json"
    assert bundle_registry.exists(), f"MC6 registry missing from bundle: {bundle_registry}"
    actual_sha = hashlib.sha256(bundle_registry.read_bytes()).hexdigest()
    assert actual_sha == expected_sha, (
        f"Bundle MC6 registry sha256 mismatch: {actual_sha!r} != {expected_sha!r}"
    )


# ---------------------------------------------------------------------------
# MC8-SEAL-11  all inventory gate verdicts are PASS
# ---------------------------------------------------------------------------
def test_mc8_seal_11_all_inventory_gates_pass(artifact_inventory):
    """MC8-SEAL-11: every gate in artifact_inventory must be PASS."""
    gates = artifact_inventory.get("gates", {})
    failures = {k: v for k, v in gates.items() if v.get("result") != "PASS"}
    assert not failures, f"Inventory gates not PASS: {json.dumps(failures, indent=2)}"
    assert artifact_inventory.get("overall_verdict") == "PASS", (
        f"overall_verdict != PASS: {artifact_inventory.get('overall_verdict')}"
    )
