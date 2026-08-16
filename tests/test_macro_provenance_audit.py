"""Tests for HMR-V4C-4A macro event state provenance audit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_JSON = REPO_ROOT / "research/historical_market_replay_v4/v4c_4a_macro_provenance_audit.json"


@pytest.fixture(scope="module")
def audit_data():
    assert AUDIT_JSON.exists(), f"Audit JSON not found: {AUDIT_JSON}"
    return json.loads(AUDIT_JSON.read_text())


def test_program_metadata(audit_data):
    """Audit JSON has correct program metadata."""
    assert audit_data["program"] == "HMR-V4C-4A"
    assert audit_data["audit_class"] == "PROVENANCE_ONLY"


def test_discovery_gates(audit_data):
    """Discovery close gate is ARMED; hard stop is DISARMED."""
    assert "ARMED" in audit_data["discovery_close_gate"]
    assert "DISARMED" in audit_data["feature_discovery_hard_stop"]


def test_discovery_outcome(audit_data):
    """Discovery outcome is COMPLETE; promoted count >= 1."""
    assert audit_data["discovery_outcome"] == "DISCOVERY_PHASE_COMPLETE"
    assert audit_data["promoted_sources_count"] >= 1


def test_expected_sources_present(audit_data):
    """All three macro event sources (CPI, NFP, FOMC) are audited."""
    source_ids = {s["source"] for s in audit_data["sources"]}
    assert "CPI_BLS" in source_ids
    assert "NFP_BLS" in source_ids
    assert "FOMC_FED" in source_ids


def test_c7_fails_universally(audit_data):
    """C7 (surprise PIT safety) fails for all three sources — universal blocker."""
    for s in audit_data["sources"]:
        c7 = s["gates"]["C7_surprise_pit_safe"]
        assert c7.startswith("FAIL"), (
            f"{s['source']} C7 should FAIL (consensus vintage not public); got {c7!r}"
        )


def test_c2_fails_universally(audit_data):
    """C2 (consensus vintage) fails for all sources — same root cause as C7."""
    for s in audit_data["sources"]:
        c2 = s["gates"]["C2_consensus_vintage"]
        assert c2.startswith("FAIL"), (
            f"{s['source']} C2 should FAIL; got {c2!r}"
        )


def test_fomc_no_revision(audit_data):
    """FOMC rate decisions are classified NO_REVISION (not restated post-announcement)."""
    fomc = next(s for s in audit_data["sources"] if s["source"] == "FOMC_FED")
    assert fomc["revision_class"] == "NO_REVISION"


def test_nfp_major_revision_risk(audit_data):
    """NFP is classified MAJOR_REVISION_RISK due to benchmark revisions."""
    nfp = next(s for s in audit_data["sources"] if s["source"] == "NFP_BLS")
    # C3 should fail due to major revision risk
    c3 = nfp["gates"]["C3_revision_risk"]
    assert "MAJOR_REVISION_RISK" in c3 or "FAIL" in c3, (
        f"NFP C3 should flag major revision risk; got {c3!r}"
    )


def test_overall_verdict(audit_data):
    """Overall verdict is REJECT_SURPRISE_FEATURE_FAMILY."""
    assert audit_data["overall_verdict"] == "REJECT_SURPRISE_FEATURE_FAMILY"


def test_v4c4_stage_verdict(audit_data):
    """V4C-4 stage verdict is REJECTED_FINAL."""
    assert audit_data["v4c4_stage_verdict"] == "REJECTED_FINAL"


def test_ml_training_blocked(audit_data):
    """ML training remains BLOCKED."""
    assert audit_data["ml_training"] == "BLOCKED"


def test_binary_event_state_viable_flag(audit_data):
    """Binary event-state features are noted as PIT-viable but out of scope for V4C-4B."""
    assert audit_data["binary_event_state_viable"] is True
    assert "out of scope" in audit_data["binary_event_state_note"].lower() or \
           "separate" in audit_data["binary_event_state_note"].lower()


def test_special_findings_present(audit_data):
    """Special findings include NFP benchmark revision and consensus blocker."""
    finding_ids = {sf["finding"] for sf in audit_data.get("special_findings", [])}
    assert "NFP_BENCHMARK_REVISION_LOOKAHEAD" in finding_ids
    assert "CONSENSUS_VINTAGE_UNIVERSAL_BLOCKER" in finding_ids


def test_gate_c5_passes(audit_data):
    """C5 (PIT lag policy definable) passes for all sources — conventional times are known."""
    for s in audit_data["sources"]:
        assert s["gates"]["C5_pit_lag_policy_definable"] == "PASS", (
            f"{s['source']} C5 should PASS; got {s['gates']['C5_pit_lag_policy_definable']!r}"
        )


def test_gate_c6_passes(audit_data):
    """C6 (schema determinism) passes — release date + headline is a stable schema."""
    for s in audit_data["sources"]:
        assert s["gates"]["C6_schema_determinism"] == "PASS", (
            f"{s['source']} C6 should PASS; got {s['gates']['C6_schema_determinism']!r}"
        )
