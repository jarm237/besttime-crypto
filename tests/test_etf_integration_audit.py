import json
from pathlib import Path
import pytest
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"

def test_integration_files_exist():
    assert (OUT_DIR / "v4d_1_etf_integration_audit.json").exists()
    assert (OUT_DIR / "v4d_1_etf_integration_report.md").exists()

def test_integration_json_schema():
    with open(OUT_DIR / "v4d_1_etf_integration_audit.json", "r") as f:
        data = json.load(f)
        
    assert data["program"] == "HMR-V4D-1"
    assert data["source"] == "parsebot_farside_etf_flows"
    assert data["primary_asset"] == "BTC"
    assert data["verdict"] == "INTEGRATION_PROMOTED"
    
    # Assert sizing keys
    assert "use_case_1_sizing" in data
    sizing = data["use_case_1_sizing"]
    assert "baseline" in sizing
    assert "volatility_aware_sizing" in sizing
    
    # Assert dynamic widths keys
    assert "use_case_2_widths" in data
    widths = data["use_case_2_widths"]
    assert "baseline" in widths
    assert "dynamic_widths" in widths

def test_integration_rerun_determinism():
    # Read existing
    with open(OUT_DIR / "v4d_1_etf_integration_audit.json", "r") as f:
        existing = json.load(f)
        
    # Rerun script
    cmd = [".venv/bin/python", "scripts/hmr_v4d_1_etf_integration_audit.py"]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0
    
    # Read new
    with open(OUT_DIR / "v4d_1_etf_integration_audit.json", "r") as f:
        new_data = json.load(f)
        
    assert existing["use_case_1_sizing"] == new_data["use_case_1_sizing"]
    assert existing["use_case_2_widths"] == new_data["use_case_2_widths"]
