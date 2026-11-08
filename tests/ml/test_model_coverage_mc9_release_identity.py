"""MC9-A — Release Identity Freeze: seal tests.

Verifies that model_coverage_mc9_release_identity.json is internally consistent,
matches all upstream MC artifacts, and satisfies canonical universe accounting.
"""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IDENTITY_PATH = ROOT / "model_coverage_mc9_release_identity.json"
IDENTITY_SHA_PATH = ROOT / "model_coverage_mc9_release_identity.json.sha256"

MC8_VERDICT = ROOT / "model_coverage_mc8_final_verdict.json"
MC8_CONTRACT = ROOT / "model_coverage_mc8_release_contract.json"
MC8_MANIFEST = ROOT / "model_coverage_mc8_release_manifest.json"
MC6_REGISTRY = ROOT / "model_coverage_mc6_inference_registry.json"
MC7_BINDING = ROOT / "model_coverage_mc7_runtime_binding_contract.json"

EXPECTED_SOURCE_COMMIT = "b284ad36f311c5cbf4986c6dfe7f47e8aee01062"
EXPECTED_RELEASE_ID = "model-coverage-v1-r1"
EXPECTED_AUTHORIZED = ["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"]
EXPECTED_DISABLED = ["AEVO", "AR", "AVAX", "ENA", "SOPH", "TAO", "TRB", "TRUMP",
                     "WLD", "XAUT", "XLM", "XPL", "XRP"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@pytest.fixture(scope="module")
def identity():
    assert IDENTITY_PATH.exists(), f"Missing: {IDENTITY_PATH}"
    return json.loads(IDENTITY_PATH.read_bytes())


@pytest.fixture(scope="module")
def contract():
    return json.loads(MC8_CONTRACT.read_bytes())


# ── MC9-A-T1  SHA256 sidecar matches artifact on disk ───────────────────────
def test_mc9_a_t1_sha256_sidecar_matches_disk():
    """Identity SHA256 sidecar must match actual file on disk."""
    assert IDENTITY_SHA_PATH.exists(), f"Missing sidecar: {IDENTITY_SHA_PATH}"
    recorded = IDENTITY_SHA_PATH.read_text().strip().split()[0]
    actual = sha256_file(IDENTITY_PATH)
    assert actual == recorded, f"SHA256 mismatch: disk={actual[:16]} sidecar={recorded[:16]}"


# ── MC9-A-T2  source commit exact ───────────────────────────────────────────
def test_mc9_a_t2_source_commit_exact(identity):
    assert identity["source_commit"] == EXPECTED_SOURCE_COMMIT, (
        f"Unexpected source_commit: {identity['source_commit']!r}"
    )


# ── MC9-A-T3  release_id correct ────────────────────────────────────────────
def test_mc9_a_t3_release_id(identity):
    assert identity["release_id"] == EXPECTED_RELEASE_ID


# ── MC9-A-T4  universe accounting: 9 + 13 == 22 ─────────────────────────────
def test_mc9_a_t4_universe_accounting(identity):
    auth = identity["authorized_symbols"]
    dis = identity["disabled_symbols"]
    assert len(auth) == 9, f"Expected 9 authorized, got {len(auth)}"
    assert len(dis) == 13, f"Expected 13 disabled, got {len(dis)}"
    assert len(auth) + len(dis) == 22


# ── MC9-A-T5  authorized and disabled lists exact ───────────────────────────
def test_mc9_a_t5_authorized_list_exact(identity):
    assert sorted(identity["authorized_symbols"]) == sorted(EXPECTED_AUTHORIZED)


def test_mc9_a_t5_disabled_list_exact(identity):
    assert sorted(identity["disabled_symbols"]) == sorted(EXPECTED_DISABLED)


# ── MC9-A-T6  authorized and disabled are disjoint ──────────────────────────
def test_mc9_a_t6_sets_disjoint(identity):
    auth = set(identity["authorized_symbols"])
    dis = set(identity["disabled_symbols"])
    overlap = auth & dis
    assert not overlap, f"Symbols in both sets: {overlap}"


# ── MC9-A-T7  every authorized symbol has non-ambiguous fingerprints ─────────
def test_mc9_a_t7_route_identities_complete(identity):
    route_identities = identity["route_identities"]
    for sym in EXPECTED_AUTHORIZED:
        assert sym in route_identities, f"Missing route identity for {sym}"
        ri = route_identities[sym]
        assert ri.get("model_sha256"), f"{sym}: empty model_sha256"
        assert ri.get("artifact_verified") is True, f"{sym}: artifact_verified != True"


# ── MC9-A-T8  all gates PASS ─────────────────────────────────────────────────
def test_mc9_a_t8_all_gates_pass(identity):
    gates = identity.get("gates", {})
    assert len(gates) == 8, f"Expected 8 gates, got {len(gates)}"
    failures = {k: v for k, v in gates.items() if v.get("result") != "PASS"}
    assert not failures, f"Gates not PASS: {failures}"
    assert identity.get("overall_verdict") == "PASS"


# ── MC9-A-T9  manifest sha256 in identity matches disk ───────────────────────
def test_mc9_a_t9_manifest_sha256_matches_disk(identity):
    recorded = identity["release_manifest"]["sha256"]
    actual = sha256_file(MC8_MANIFEST)
    assert actual == recorded, f"Manifest sha256: disk={actual[:16]} identity={recorded[:16]}"


# ── MC9-A-T10  MC6 registry sha256 matches disk ──────────────────────────────
def test_mc9_a_t10_registry_sha256_matches_disk(identity):
    recorded = identity["inference_registry"]["sha256"]
    actual = sha256_file(MC6_REGISTRY)
    assert actual == recorded, f"Registry sha256: disk={actual[:16]} identity={recorded[:16]}"


# ── MC9-A-T11  MC7 binding sha256 matches disk ───────────────────────────────
def test_mc9_a_t11_binding_sha256_matches_disk(identity):
    recorded = identity["runtime_binding_contract"]["sha256"]
    actual = sha256_file(MC7_BINDING)
    assert actual == recorded
