"""Tests for MC8-B/C — Canonical Release Manifest & Pinned Runtime Worktree."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

MC8_CONTRACT = REPO_ROOT / "model_coverage_mc8_release_contract.json"
MC8_MANIFEST = REPO_ROOT / "model_coverage_mc8_release_manifest.json"
MC8_REPORT   = REPO_ROOT / "model_coverage_mc8_pinned_runtime_report.json"
WORKTREE_DIR = REPO_ROOT / "runtime" / "worktrees" / "pinned-94407d3"
V1_MANIFEST_COMMIT = "56231dc093445280b6b4e73ae7d453b5e6409a16"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_artifact_json(commit: str, path: str) -> dict:
    raw = subprocess.check_output(
        ["git", "show", f"{commit}:{path}"],
        cwd=REPO_ROOT,
    )
    return json.loads(raw)


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MC8_MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(MC8_REPORT.read_text(encoding="utf-8"))


# ── SHA sidecar validity ─────────────────────────────────────────────────────

def test_mc8_manifest_sha_sidecar_valid() -> None:
    sha_path = Path(str(MC8_MANIFEST) + ".sha256")
    assert sha_path.exists()
    digest, rel = sha_path.read_text().strip().split()
    assert _sha256(REPO_ROOT / rel) == digest


def test_mc8_pinned_runtime_report_sha_sidecar_valid() -> None:
    sha_path = Path(str(MC8_REPORT) + ".sha256")
    assert sha_path.exists()
    digest, rel = sha_path.read_text().strip().split()
    assert _sha256(REPO_ROOT / rel) == digest


# ── Manifest Structure ────────────────────────────────────────────────────────

def test_manifest_basic_metadata(manifest: dict) -> None:
    assert manifest["release_version"] == "model-coverage-v1-r1"
    assert manifest["source_commit"] == "b284ad36f311c5cbf4986c6dfe7f47e8aee01062"
    assert manifest["canonical_universe"] == 22
    assert manifest["effective_runtime_universe"] == 9
    assert len(manifest["routes"]) == 9
    assert len(manifest["disabled_symbols"]) == 13


def test_manifest_matches_registry_and_binding(manifest: dict) -> None:
    registry_symbols = {r["symbol"] for r in manifest["registry"]["routes"]}
    assert set(manifest["routes"].keys()) == registry_symbols
    assert set(manifest["disabled_symbols"]) == set(manifest["runtime_binding"]["inference_disabled_symbols"])


# ── Pinned Runtime Worktree ───────────────────────────────────────────────────

def test_pinned_worktree_exists_and_checked_out() -> None:
    assert WORKTREE_DIR.exists()
    assert (WORKTREE_DIR / "btc_scraper").exists()
    assert (WORKTREE_DIR / ".git").exists()  # git worktree has a .git file pointing to the main repo git dir


def test_worktree_commit_matches_its_v1_manifest() -> None:
    historical_manifest = _git_artifact_json(
        V1_MANIFEST_COMMIT,
        "model_coverage_mc8_release_manifest.json",
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(WORKTREE_DIR)
    ).decode().strip()
    assert historical_manifest["release_version"] == "model-coverage-v1"
    assert head == historical_manifest["source_commit"]


# ── PYTHONPATH / import isolation preflight ──────────────────────────────────

def test_pythonpath_import_isolation() -> None:
    """Verifies that running python with PYTHONPATH pointing to the pinned worktree
    loads all packages strictly from the worktree and NOT the main working directory.
    """
    code = """
import sys
import btc_scraper
import btc_scraper.ml_engine.runtime_symbol_policy as policy
import btc_scraper.ml_engine.inference_router as router

print("SCRAPER_FILE:" + btc_scraper.__file__)
print("POLICY_FILE:" + policy.__file__)
print("ROUTER_FILE:" + router.__file__)
"""
    # Exclude REPO_ROOT from python path so it cannot fall back to the main workspace
    env = os.environ.copy()
    env["PYTHONPATH"] = str(WORKTREE_DIR)

    # Run from a temporary directory outside the workspace to prevent directory-relative loading
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        out = subprocess.check_output(
            [sys.executable, "-c", code], env=env, cwd=tmp_dir
        ).decode().strip()

    lines = out.splitlines()
    assert len(lines) >= 3

    for line in lines:
        if line.startswith("SCRAPER_FILE:") or line.startswith("POLICY_FILE:") or line.startswith("ROUTER_FILE:"):
            key, val = line.split(":", 1)
            # The file path must start with the worktree directory path
            assert val.startswith(str(WORKTREE_DIR)), f"{key} resolved outside worktree: {val}"
