import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"

def test_liquidation_provenance_files_exist():
    assert (OUT_DIR / "v4b_3a_liquidation_source_manifest.json").exists()
    assert (OUT_DIR / "v4b_3a_liquidation_coverage.json").exists()
    assert (OUT_DIR / "v4b_3a_liquidation_provenance_audit.json").exists()
    assert (OUT_DIR / "v4b_3a_liquidation_provenance_report.md").exists()

def test_manifest_schema():
    with open(OUT_DIR / "v4b_3a_liquidation_source_manifest.json", "r") as f:
        m = json.load(f)
    assert m["symbols"] == ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    assert "known_censoring" in m
    assert "coverage_ratio" in m

def test_provenance_verdict_gates():
    with open(OUT_DIR / "v4b_3a_liquidation_provenance_audit.json", "r") as f:
        a = json.load(f)
    assert a["verdict"] == "REJECT_INCOMPLETE_LIQUIDATION_OBSERVABILITY"
    assert a["provenance"] == "REJECTED"
    
    gates = a["provenance_gates"]
    assert gates["L0_SOURCE_PROVENANCE"] is True
    assert gates["L1_HISTORICAL_AVAILABILITY"] is False
    assert gates["L2_COVERAGE"] is False
    assert gates["L3_SCHEMA_SEMANTICS"] is True
    assert gates["L4_COMPLETENESS_CENSORING"] is False
    assert gates["L7_SUITABILITY"] is False

def test_determinism_invariant():
    import subprocess
    # Read existing audit json
    with open(OUT_DIR / "v4b_3a_liquidation_provenance_audit.json", "r") as f:
        existing_data = json.load(f)
        
    # Re-run the script
    cmd = [".venv/bin/python", "scripts/audit_real_liquidation_provenance.py"]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0
    
    # Read new audit json
    with open(OUT_DIR / "v4b_3a_liquidation_provenance_audit.json", "r") as f:
        new_data = json.load(f)
        
    # Check that they match exactly
    assert existing_data["verdict"] == new_data["verdict"]
    assert existing_data["provenance_gates"] == new_data["provenance_gates"]
