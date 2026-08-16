import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"

def test_stablecoin_provenance_files_exist():
    assert (OUT_DIR / "v4c_2a_stablecoin_source_manifest.json").exists()
    assert (OUT_DIR / "v4c_2a_stablecoin_coverage.json").exists()
    assert (OUT_DIR / "v4c_2a_stablecoin_provenance_audit.json").exists()
    assert (OUT_DIR / "v4c_2a_stablecoin_provenance_report.md").exists()

def test_manifest_schema():
    with open(OUT_DIR / "v4c_2a_stablecoin_source_manifest.json", "r") as f:
        m = json.load(f)
    assert m["symbols"] == ["USDT", "USDC", "DAI"]
    assert "known_censoring" in m
    assert m["coverage_ratio"] == 1.0

def test_provenance_verdict_gates():
    with open(OUT_DIR / "v4c_2a_stablecoin_provenance_audit.json", "r") as f:
        a = json.load(f)
    assert a["verdict"] == "AUTHORIZED_V4C_2B"
    assert a["provenance"] == "AUTHORIZED_V4C_2B"
    
    classes = a["classes"]
    assert classes["S1_total_circulating_supply"]["verdict"] == "PASS"
    assert classes["S2_net_issuance_redemption"]["verdict"] == "PASS"
    assert classes["S3_exchange_stablecoin_balances"]["verdict"] == "REJECT_ATTRIBUTION_LOOKAHEAD"
    assert classes["S4_exchange_stablecoin_netflows"]["verdict"] == "REJECT_ATTRIBUTION_LOOKAHEAD"
    assert classes["S5_stablecoin_dominance"]["verdict"] == "PASS"

def test_determinism_invariant():
    import subprocess
    # Read existing audit json
    with open(OUT_DIR / "v4c_2a_stablecoin_provenance_audit.json", "r") as f:
        existing_data = json.load(f)
        
    # Re-run the script
    cmd = [".venv/bin/python", "scripts/audit_stablecoin_provenance.py"]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0
    
    # Read new audit json
    with open(OUT_DIR / "v4c_2a_stablecoin_provenance_audit.json", "r") as f:
        new_data = json.load(f)
        
    # Check that they match exactly
    assert existing_data["verdict"] == new_data["verdict"]
    assert existing_data["classes"] == new_data["classes"]
