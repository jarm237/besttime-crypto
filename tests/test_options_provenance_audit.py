import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"

def test_options_provenance_files_exist():
    assert (OUT_DIR / "v4b_5a_options_source_manifest.json").exists()
    assert (OUT_DIR / "v4b_5a_options_coverage.json").exists()
    assert (OUT_DIR / "v4b_5a_options_provenance_audit.json").exists()
    assert (OUT_DIR / "v4b_5a_options_provenance_report.md").exists()

def test_manifest_schema():
    with open(OUT_DIR / "v4b_5a_options_source_manifest.json", "r") as f:
        m = json.load(f)
    assert m["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert "known_censoring" in m
    assert m["coverage_ratio"] == 0.0

def test_provenance_verdict_gates():
    with open(OUT_DIR / "v4b_5a_options_provenance_audit.json", "r") as f:
        a = json.load(f)
    assert a["verdict"] == "REJECT_INSUFFICIENT_CHAIN_COVERAGE"
    assert a["provenance"] == "REJECTED"
    
    gates = a["provenance_gates"]
    assert gates["O0_SOURCE_PROVENANCE"] is True
    assert gates["O1_HISTORICAL_AVAILABILITY"] is False
    assert gates["O2_COVERAGE_PERIOD_A_B_C"] is False
    assert gates["O3_INSTRUMENT_CONTRACT_SEMANTICS"] is True
    assert gates["O4_QUOTE_MARK_TIMESTAMP_SEMANTICS"] is False
    assert gates["O10_SUITABILITY_FOR_FEATURE_AUDIT"] is False

def test_determinism_invariant():
    import subprocess
    # Read existing audit json
    with open(OUT_DIR / "v4b_5a_options_provenance_audit.json", "r") as f:
        existing_data = json.load(f)
        
    # Re-run the script
    cmd = [".venv/bin/python", "scripts/audit_real_options_provenance.py"]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0
    
    # Read new audit json
    with open(OUT_DIR / "v4b_5a_options_provenance_audit.json", "r") as f:
        new_data = json.load(f)
        
    # Check that they match exactly
    assert existing_data["verdict"] == new_data["verdict"]
    assert existing_data["provenance_gates"] == new_data["provenance_gates"]
