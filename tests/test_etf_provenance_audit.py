import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"

def test_etf_provenance_files_exist():
    assert (OUT_DIR / "v4c_3a_etf_source_manifest.json").exists()
    assert (OUT_DIR / "v4c_3a_etf_coverage.json").exists()
    assert (OUT_DIR / "v4c_3a_etf_provenance_audit.json").exists()
    assert (OUT_DIR / "v4c_3a_etf_provenance_report.md").exists()

def test_etf_manifest_schema():
    with open(OUT_DIR / "v4c_3a_etf_source_manifest.json", "r") as f:
        m = json.load(f)
    assert m["primary_asset"] == "BTC"
    assert "IBIT" in m["individual_funds"]
    assert "GBTC" in m["individual_funds"]
    assert m["time_semantics"] == "DATE_ONLY_UNKNOWN_LATENCY"
    assert m["revision_semantics"] == "REVISION_CLASS = UNKNOWN"

def test_etf_provenance_verdict_gates():
    with open(OUT_DIR / "v4c_3a_etf_provenance_audit.json", "r") as f:
        a = json.load(f)
    assert a["verdict"] == "AUTHORIZED_V4C_3B"
    assert a["provenance"] == "AUTHORIZED_V4C_3B"
    
    gates = a["gates"]
    assert gates["E0_SOURCE_PROVENANCE"] is True
    assert gates["E1_HISTORICAL_COVERAGE"] is True
    assert gates["E4_PUBLICATION_TIME_SEMANTICS"] is False
    assert gates["E5_REVISION_CORRECTION_POLICY"] is False
    assert gates["E7_PIT_AVAILABILITY"] is True

def test_etf_determinism_invariant():
    import subprocess
    # Read existing audit json
    with open(OUT_DIR / "v4c_3a_etf_provenance_audit.json", "r") as f:
        existing_data = json.load(f)
        
    # Re-run the script
    cmd = [".venv/bin/python", "scripts/audit_etf_provenance.py"]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0
    
    # Read new audit json
    with open(OUT_DIR / "v4c_3a_etf_provenance_audit.json", "r") as f:
        new_data = json.load(f)
        
    # Check that they match exactly
    assert existing_data["verdict"] == new_data["verdict"]
    assert existing_data["gates"] == new_data["gates"]
