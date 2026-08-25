"""Tests for MC6-E/F — Universe Preflight & Final Seal."""
import json
import hashlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

MC6_PREFLIGHT      = REPO_ROOT / "model_coverage_mc6_universe_preflight.json"
MC6_RECONCILIATION = REPO_ROOT / "model_coverage_mc6_reconciliation.json"
MC6_INTEGRATION    = REPO_ROOT / "model_coverage_mc6_integration_contract.json"
MC6_INF_REGISTRY   = REPO_ROOT / "model_coverage_mc6_inference_registry.json"
MC1_CONTRACT       = REPO_ROOT / "model_coverage_mc1_contract.json"

ALL_MC6_FILES = [
    MC6_PREFLIGHT, MC6_RECONCILIATION, MC6_INTEGRATION, MC6_INF_REGISTRY,
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def preflight() -> dict:
    return json.loads(MC6_PREFLIGHT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def recon() -> dict:
    return json.loads(MC6_RECONCILIATION.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(MC6_INF_REGISTRY.read_text(encoding="utf-8"))


# ── SHA sidecar validity ────────────────────────────────────────────────────

def test_all_mc6_sha_sidecars_valid() -> None:
    for path in ALL_MC6_FILES:
        sha_path = Path(str(path) + ".sha256")
        assert sha_path.exists(), f"Missing SHA sidecar for {path.name}"
        digest, rel = sha_path.read_text().strip().split()
        assert _sha256(REPO_ROOT / rel) == digest, f"SHA mismatch for {path.name}"


# ── Preflight verdict ───────────────────────────────────────────────────────

def test_preflight_verdict_pass(preflight: dict) -> None:
    assert preflight["preflight_verdict"] == "PASS"


def test_preflight_22_symbols(preflight: dict) -> None:
    assert preflight["runtime_symbols"] == 22
    assert preflight["accounted_symbols"] == 22


def test_preflight_no_unsupported(preflight: dict) -> None:
    assert preflight["unsupported_enabled_symbols"] == 0


def test_preflight_no_ambiguous(preflight: dict) -> None:
    assert preflight["ambiguous_routes"] == 0


def test_preflight_no_integrity_failures(preflight: dict) -> None:
    assert preflight["artifact_integrity_failures"] == 0


def test_preflight_no_schema_failures(preflight: dict) -> None:
    assert preflight["schema_failures"] == 0


def test_preflight_routable_plus_excluded_equals_total(preflight: dict) -> None:
    total = preflight["routable_enabled_symbols"] + preflight["excluded_symbols"]
    assert total == preflight["runtime_symbols"]


# ── Cross-consistency ───────────────────────────────────────────────────────

def test_preflight_routable_matches_registry(preflight: dict, registry: dict) -> None:
    preflight_routable = [r["symbol"] for r in preflight["results"]
                          if r["status"] == "ROUTABLE_OK"]
    registry_symbols = [r["symbol"] for r in registry["routes"]]
    assert sorted(preflight_routable) == sorted(registry_symbols)


def test_preflight_excluded_matches_recon(preflight: dict, recon: dict) -> None:
    preflight_excluded = sorted(
        r["symbol"] for r in preflight["results"]
        if r["status"] == "EXCLUDED_VERIFIED"
    )
    recon_excluded = sorted(e["symbol"] for e in recon["excluded_symbols"])
    assert preflight_excluded == recon_excluded


# ── Seal-level invariants ───────────────────────────────────────────────────

def test_mc6_reconciliation_pass(recon: dict) -> None:
    assert recon["reconciliation_verdict"] == "PASS"


def test_routing_fail_closed() -> None:
    integration = json.loads(MC6_INTEGRATION.read_text(encoding="utf-8"))
    assert integration["routing_semantics"]["policy"] == "FAIL_CLOSED"
    assert integration["routing_semantics"]["silent_fallback"] == "FORBIDDEN"


def test_canonical_universe_unchanged() -> None:
    mc1 = json.loads(MC1_CONTRACT.read_text(encoding="utf-8"))
    recon = json.loads(MC6_RECONCILIATION.read_text(encoding="utf-8"))
    assert mc1["canonical_symbols"] == recon["canonical_symbols"]
    assert mc1["canonical_symbol_count"] == recon["canonical_universe_count"] == 22
