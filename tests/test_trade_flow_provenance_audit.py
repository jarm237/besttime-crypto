import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"

def test_trade_flow_provenance_files_exist():
    assert (OUT_DIR / "v4b_4a_trade_flow_source_manifest.json").exists()
    assert (OUT_DIR / "v4b_4a_trade_flow_coverage.json").exists()
    assert (OUT_DIR / "v4b_4a_trade_flow_provenance_audit.json").exists()
    assert (OUT_DIR / "v4b_4a_trade_flow_provenance_report.md").exists()

def test_manifest_schema():
    with open(OUT_DIR / "v4b_4a_trade_flow_source_manifest.json", "r") as f:
        m = json.load(f)
    assert m["symbols"] == ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    assert "canonical_schema" in m
    assert "aggressor_semantics_mapping" in m
    # Verify exact aggressor buyer-maker logic
    mapping = m["aggressor_semantics_mapping"]
    assert "is_buyer_maker == True" in mapping["maker_buy_taker_sell"]
    assert "is_buyer_maker == False" in mapping["maker_sell_taker_buy"]

def test_provenance_verdict_gates():
    with open(OUT_DIR / "v4b_4a_trade_flow_provenance_audit.json", "r") as f:
        a = json.load(f)
    assert a["verdict"] == "AUTHORIZE_V4B_4B"
    assert a["provenance"] == "PROVEN"
    
    gates = a["provenance_gates"]
    assert gates["F0_SOURCE_PROVENANCE"] is True
    assert gates["F1_HISTORICAL_AVAILABILITY"] is True
    assert gates["F2_COVERAGE"] is True
    assert gates["F3_TRADE_SIDE_SEMANTICS"] is True
    assert gates["F4_TIMESTAMP_GRANULARITY"] is True
    assert gates["F7_SEQUENCE_ANOMALY"] is True
    assert gates["F8_SUITABILITY"] is True

def test_determinism_invariant():
    import subprocess
    # Read existing audit json
    with open(OUT_DIR / "v4b_4a_trade_flow_provenance_audit.json", "r") as f:
        existing_data = json.load(f)
        
    # Re-run the script
    cmd = [".venv/bin/python", "scripts/audit_real_trade_flow_provenance.py"]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0
    
    # Read new audit json
    with open(OUT_DIR / "v4b_4a_trade_flow_provenance_audit.json", "r") as f:
        new_data = json.load(f)
        
    # Check that they match exactly
    assert existing_data["verdict"] == new_data["verdict"]
    assert existing_data["provenance_gates"] == new_data["provenance_gates"]
