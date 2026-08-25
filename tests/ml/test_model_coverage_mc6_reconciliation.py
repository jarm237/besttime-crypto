"""Tests for MC6-A — Coverage Reconciliation & Integration Contract."""
import json
import hashlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

MC6_RECONCILIATION = REPO_ROOT / "model_coverage_mc6_reconciliation.json"
MC6_INTEGRATION    = REPO_ROOT / "model_coverage_mc6_integration_contract.json"
MC1_CONTRACT       = REPO_ROOT / "model_coverage_mc1_contract.json"
MC5_VERDICT        = REPO_ROOT / "model_coverage_mc5_final_verdict.json"

LEGACY = {"BTC", "ETH", "BNB"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def recon() -> dict:
    return json.loads(MC6_RECONCILIATION.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def integration() -> dict:
    return json.loads(MC6_INTEGRATION.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def mc1() -> dict:
    return json.loads(MC1_CONTRACT.read_text(encoding="utf-8"))


# ── SHA sidecar validity ────────────────────────────────────────────────────

def test_sha_sidecars_valid() -> None:
    for path in [MC6_RECONCILIATION, MC6_INTEGRATION]:
        sha_path = Path(str(path) + ".sha256")
        assert sha_path.exists(), f"Missing SHA sidecar for {path.name}"
        digest, rel = sha_path.read_text().strip().split()
        assert _sha256(REPO_ROOT / rel) == digest, f"SHA mismatch for {path.name}"


# ── G1: all 22 symbols accounted for ────────────────────────────────────────

def test_all_22_symbols_accounted(recon: dict, mc1: dict) -> None:
    canonical = set(mc1["canonical_symbols"])
    classified = {c["symbol"] for c in recon["classifications"]}
    assert classified == canonical
    assert recon["canonical_universe_count"] == 22


# ── No symbol in multiple categories ─────────────────────────────────────────

def test_no_symbol_in_multiple_categories(recon: dict) -> None:
    symbols = [c["symbol"] for c in recon["classifications"]]
    assert len(symbols) == len(set(symbols)), "Duplicate classification"


# ── Routable contains legacy ∪ mc5_qualified ─────────────────────────────────

def test_routable_superset(recon: dict) -> None:
    mc5_verdict = json.loads(MC5_VERDICT.read_text(encoding="utf-8"))
    expected_routable = LEGACY | set(mc5_verdict["qualified_symbols"])
    actual_routable = set(recon["routable_symbols"])
    assert actual_routable == expected_routable


# ── Excluded ∩ routable = ∅ ──────────────────────────────────────────────────

def test_excluded_disjoint_from_routable(recon: dict) -> None:
    routable = set(recon["routable_symbols"])
    excluded = {e["symbol"] for e in recon["excluded_symbols"]}
    assert routable.isdisjoint(excluded)


# ── Gates G1–G6 ─────────────────────────────────────────────────────────────

def test_gates_pass(recon: dict) -> None:
    gates = recon["gates"]
    for gate, value in gates.items():
        if value == "DEFERRED_TO_MC6B":
            continue
        assert value == "PASS", f"Gate {gate} = {value}"


# ── Reconciliation verdict ───────────────────────────────────────────────────

def test_reconciliation_verdict_pass(recon: dict) -> None:
    assert recon["reconciliation_verdict"] == "PASS"


# ── Unresolved count is zero ────────────────────────────────────────────────

def test_no_unresolved(recon: dict) -> None:
    assert recon["unresolved_count"] == 0


# ── Integration contract semantics ──────────────────────────────────────────

def test_integration_fail_closed(integration: dict) -> None:
    routing = integration["routing_semantics"]
    assert routing["policy"] == "FAIL_CLOSED"
    assert routing["silent_fallback"] == "FORBIDDEN"
    assert routing["default_artifact_route"] == "FORBIDDEN"


def test_integration_routable_matches_recon(recon: dict, integration: dict) -> None:
    assert integration["routable_symbols"] == recon["routable_symbols"]


def test_integration_excluded_matches_recon(recon: dict, integration: dict) -> None:
    recon_excluded = sorted(e["symbol"] for e in recon["excluded_symbols"])
    assert sorted(integration["excluded_symbols"]) == recon_excluded


# ── Specific classification checks ──────────────────────────────────────────

def test_xaut_blocked_data_provenance(recon: dict) -> None:
    xaut = next(c for c in recon["classifications"] if c["symbol"] == "XAUT")
    assert xaut["category"] == "MC3_BLOCKED_DATA_PROVENANCE"
    assert xaut["routable"] is False


def test_soph_trump_xpl_no_candidate(recon: dict) -> None:
    for sym in ["SOPH", "TRUMP", "XPL"]:
        entry = next(c for c in recon["classifications"] if c["symbol"] == sym)
        assert entry["category"] == "MC4_NO_CANDIDATE"
        assert entry["routable"] is False
