import json
from pathlib import Path
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"

def test_parquet_schema_and_dst():
    df = pd.read_parquet(OUT_DIR / "v4c_1b_cross_market_history.parquet")
    required_cols = ["date", "vix_close", "spx_close", "dxy_close", "us10y_close", "available_at",
                     "CM1_VIX_percentile_60d", "CM2_VIX_change_5d", "CM3_SPX_return_5d",
                     "CM4_DXY_return_5d", "CM5_US10Y_change_5d", "spx_rv_30d"]
    for col in required_cols:
        assert col in df.columns
        
    # Check Summer (EDT - 4 hours behind UTC)
    # June 2nd, 2023: 16:00 close + 1h lag = 17:00 EDT = 21:00 UTC
    row_summer = df[df["date"] == "2023-06-02"]
    assert len(row_summer) == 1
    avail_summer = pd.to_datetime(row_summer.iloc[0]["available_at"])
    assert avail_summer.hour == 21
    assert avail_summer.minute == 0
    
    # Check Winter (EST - 5 hours behind UTC)
    # December 1st, 2023: 16:00 close + 1h lag = 17:00 EST = 22:00 UTC
    row_winter = df[df["date"] == "2023-12-01"]
    assert len(row_winter) == 1
    avail_winter = pd.to_datetime(row_winter.iloc[0]["available_at"])
    assert avail_winter.hour == 22
    assert avail_winter.minute == 0

def test_audit_results_verdicts():
    # Verify presence of output files
    assert (OUT_DIR / "v4c_1b_cross_market_audit.json").exists()
    assert (OUT_DIR / "v4c_1b_cross_market_report.md").exists()
    
    with open(OUT_DIR / "v4c_1b_cross_market_audit.json", "r") as f:
        a = json.load(f)
        
    assert a["program"] == "HMR-V4C-1B"
    assert a["source"] == "cross_market_risk_regime"
    
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
    with open(OUT_DIR / "v4c_1b_cross_market_audit.json", "r") as f:
        existing_data = json.load(f)
        
    # Rerun script
    cmd = [".venv/bin/python", "scripts/hmr_v4c_1b_cross_market_audit.py"]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0
    
    # Read new audit
    with open(OUT_DIR / "v4c_1b_cross_market_audit.json", "r") as f:
        new_data = json.load(f)
        
    # Compare
    assert existing_data["directional_audit"] == new_data["directional_audit"]
    assert existing_data["volatility_audit"] == new_data["volatility_audit"]
    assert existing_data["risk_state_audit"] == new_data["risk_state_audit"]
