"""MC9-B — Pinned release read-back tests."""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
READBACK_PATH = ROOT / "model_coverage_mc9_release_readback.json"
READBACK_SHA_PATH = ROOT / "model_coverage_mc9_release_readback.json.sha256"

AUTHORIZED = ["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"]
DISABLED = ["AEVO", "AR", "AVAX", "ENA", "SOPH", "TAO", "TRB", "TRUMP",
            "WLD", "XAUT", "XLM", "XPL", "XRP"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@pytest.fixture(scope="module")
def readback():
    assert READBACK_PATH.exists(), f"Missing: {READBACK_PATH}"
    return json.loads(READBACK_PATH.read_bytes())


# ── T1  SHA256 sidecar matches disk ─────────────────────────────────────────
def test_mc9_b_t1_sha256_sidecar():
    assert READBACK_SHA_PATH.exists()
    recorded = READBACK_SHA_PATH.read_text().strip()
    actual = sha256_file(READBACK_PATH)
    assert actual == recorded


# ── T2  all imports resolve inside pinned worktree ───────────────────────────
def test_mc9_b_t2_import_provenance(readback):
    prov = readback["import_provenance"]
    assert prov["all_in_pinned_worktree"] is True, f"Leaks: {prov['leaks']}"
    assert prov["leaks"] == []


# ── T3  9/9 routes resolved ──────────────────────────────────────────────────
def test_mc9_b_t3_all_routes_resolved(readback):
    assert readback["routes_requested"] == 9
    assert readback["routes_resolved"] == 9
    assert readback["model_load_failures"] == 0


# ── T4  zero hash failures ───────────────────────────────────────────────────
def test_mc9_b_t4_zero_hash_failures(readback):
    assert readback["hash_failures"] == 0


# ── T5  zero repo-research fallback reads ────────────────────────────────────
def test_mc9_b_t5_zero_fallback_reads(readback):
    assert readback["repo_research_fallback_reads"] == 0


# ── T6  SOL explicit PASS (not inferred from aggregate) ──────────────────────
def test_mc9_b_t6_sol_explicit_pass(readback):
    sol = readback["sol_explicit"]
    assert sol["runtime_enabled"] is True, "SOL not runtime_enabled"
    assert sol["route_authorized"] is True, "SOL not route_authorized"
    assert sol["overall"] == "PASS", f"SOL overall: {sol['overall']}"


# ── T7  SOL model_load and calibrator_load individually PASS ─────────────────
def test_mc9_b_t7_sol_load_detail(readback):
    sol = readback["sol_explicit"]
    assert sol.get("model_load") == "PASS"
    assert sol.get("calibrator_load") == "PASS"


# ── T8  each of 9 authorized routes has overall=PASS ─────────────────────────
def test_mc9_b_t8_every_authorized_route_pass(readback):
    route_results = readback["route_results"]
    for sym in AUTHORIZED:
        assert sym in route_results, f"Missing route result for {sym}"
        assert route_results[sym]["overall"] == "PASS", (
            f"{sym} route overall: {route_results[sym]['overall']}"
        )


# ── T9  each of 13 disabled symbols pre-dispatch rejected ────────────────────
def test_mc9_b_t9_disabled_symbols_rejected(readback):
    disabled_results = readback["disabled_results"]
    for sym in DISABLED:
        assert sym in disabled_results, f"Missing disabled result for {sym}"
        assert disabled_results[sym]["pre_dispatch_rejected"] is True, (
            f"{sym} was not pre-dispatch rejected"
        )


# ── T10  disabled_rejected_count == 13 ───────────────────────────────────────
def test_mc9_b_t10_disabled_count(readback):
    assert readback["disabled_rejected_count"] == 13


# ── T11  overall_verdict PASS ────────────────────────────────────────────────
def test_mc9_b_t11_overall_pass(readback):
    assert readback["overall_verdict"] == "PASS"


# ── T12  all gates PASS ───────────────────────────────────────────────────────
def test_mc9_b_t12_all_gates_pass(readback):
    gates = readback.get("gates", {})
    failures = {k: v for k, v in gates.items() if v.get("result") != "PASS"}
    assert not failures, f"Gates not PASS: {failures}"
