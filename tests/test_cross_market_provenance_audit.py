import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"

def test_cross_market_provenance_files_exist():
    assert (OUT_DIR / "v4c_1a_cross_market_source_manifest.json").exists()
    assert (OUT_DIR / "v4c_1a_cross_market_coverage.json").exists()
    assert (OUT_DIR / "v4c_1a_cross_market_provenance_audit.json").exists()
    assert (OUT_DIR / "v4c_1a_cross_market_provenance_report.md").exists()

def test_manifest_schema():
    with open(OUT_DIR / "v4c_1a_cross_market_source_manifest.json", "r") as f:
        m = json.load(f)
    assert m["symbols"] == ["VIX", "SPX", "DXY", "US10Y"]
    assert "known_censoring" in m
    assert m["coverage_ratio"] == 1.0

def test_provenance_verdict_gates():
    with open(OUT_DIR / "v4c_1a_cross_market_provenance_audit.json", "r") as f:
        a = json.load(f)
    assert a["verdict"] == "AUTHORIZE_V4C_1B"
    assert a["provenance"] == "PROVEN"

    gates = a["provenance_gates"]
    assert gates["C0_SOURCE_PROVENANCE"] is True
    assert gates["C1_HISTORICAL_COVERAGE"] is True
    assert gates["C2_TIMESTAMP_SESSION_SEMANTICS"] is True
    assert gates["C3_REVISION_SEMANTICS"] is True
    assert gates["C4_MARKET_HOURS_ALIGNMENT"] is True
    assert gates["C5_PIT_AVAILABILITY"] is True
    assert gates["C9_SUITABILITY"] is True

def test_determinism_invariant():
    import subprocess
    # Read existing audit json
    with open(OUT_DIR / "v4c_1a_cross_market_provenance_audit.json", "r") as f:
        existing_data = json.load(f)

    # Re-run the script
    import sys, os
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, "scripts/audit_cross_market_provenance.py"]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, encoding="utf-8")
    assert res.returncode == 0

    # Read new audit json
    with open(OUT_DIR / "v4c_1a_cross_market_provenance_audit.json", "r") as f:
        new_data = json.load(f)

    # Check that they match exactly
    assert existing_data["verdict"] == new_data["verdict"]
    assert existing_data["provenance_gates"] == new_data["provenance_gates"]
