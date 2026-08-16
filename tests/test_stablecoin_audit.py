import json
from pathlib import Path
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"

def test_parquet_schema():
    df = pd.read_parquet(OUT_DIR / "v4c_2b_stablecoin_history.parquet")
    required_cols = ["date", "stablecoin_supply", "available_at",
                     "SC1_stablecoin_supply_growth_7d", "SC2_stablecoin_supply_growth_30d",
                     "SC3_net_issuance_7d_normalized", "SC4_net_issuance_percentile_90d"]
    for col in required_cols:
        assert col in df.columns
    assert len(df) == 731

def test_audit_results_verdicts():
    # Verify presence of output files
    assert (OUT_DIR / "v4c_2b_stablecoin_audit.json").exists()
    assert (OUT_DIR / "v4c_2b_stablecoin_report.md").exists()
    
    with open(OUT_DIR / "v4c_2b_stablecoin_audit.json", "r") as f:
        a = json.load(f)
        
    assert a["program"] == "HMR-V4C-2B"
    assert a["source"] == "defillama_stablecoin_supply"
    
    # All directional features rejected due to no economic info
    for df in a["directional_audit"]:
        assert df["verdict"] == "REJECT_NO_ECONOMIC_INFORMATION"
        
    # All volatility features rejected
    for vf in a["volatility_audit"]:
        assert vf["verdict"] == "REJECT_NO_INFORMATION"
        
    # All risk state features rejected
    for rf in a["risk_state_audit"]:
        assert rf["verdict"] == "REJECT_NO_INFORMATION"

def test_rerun_determinism():
    import subprocess
    # Read existing audit
    with open(OUT_DIR / "v4c_2b_stablecoin_audit.json", "r") as f:
        existing_data = json.load(f)
        
    # Rerun script
    cmd = [".venv/bin/python", "scripts/hmr_v4c_2b_stablecoin_audit.py"]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0
    
    # Read new audit
    with open(OUT_DIR / "v4c_2b_stablecoin_audit.json", "r") as f:
        new_data = json.load(f)
        
    # Compare
    assert existing_data["directional_audit"] == new_data["directional_audit"]
    assert existing_data["volatility_audit"] == new_data["volatility_audit"]
    assert existing_data["risk_state_audit"] == new_data["risk_state_audit"]
