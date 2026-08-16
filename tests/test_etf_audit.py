import json
from pathlib import Path
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"

def test_parquet_schema():
    df = pd.read_parquet(OUT_DIR / "v4c_3b_etf_history.parquet")
    required_cols = [
        "date", "IBIT", "GBTC", "Total", "available_at",
        "ETF1_total_net_flow_usd", "ETF2_ex_gbtc_net_flow_usd",
        "ETF3_net_flow_as_pct_aum", "ETF4_rolling_flow_zscore_20d",
        "ETF5_cumulative_net_flow_5d"
    ]
    for col in required_cols:
        assert col in df.columns
    assert len(df) == 731
    
    # Assert 2023 has zero flows
    df_2023 = df[df["date"] < "2024-01-01"]
    assert len(df_2023) == 365
    for col in ["IBIT", "GBTC", "Total", "ETF1_total_net_flow_usd", "ETF2_ex_gbtc_net_flow_usd"]:
        assert (df_2023[col] == 0.0).all()

def test_audit_results_verdicts():
    # Verify presence of output files
    assert (OUT_DIR / "v4c_3b_etf_audit.json").exists()
    assert (OUT_DIR / "v4c_3b_etf_report.md").exists()
    
    with open(OUT_DIR / "v4c_3b_etf_audit.json", "r") as f:
        a = json.load(f)
        
    assert a["program"] == "HMR-V4C-3B"
    assert a["source"] == "parsebot_farside_etf_flows"
    
    # Check that ETF2 volatility is promoted
    vol_dict = {vf["feature"]: vf["verdict"] for vf in a["volatility_audit"]}
    assert vol_dict["ETF2_ex_gbtc_net_flow_usd"] == "PROMOTE_VOLATILITY_INFORMATION"
    
    # Check that ETF3 is rejected with REJECT_FEATURE_PROVENANCE
    dir_dict = {df["feature"]: df["verdict"] for df in a["directional_audit"]}
    assert dir_dict["ETF3_net_flow_as_pct_aum"] == "REJECT_FEATURE_PROVENANCE"
    assert vol_dict["ETF3_net_flow_as_pct_aum"] == "REJECT_FEATURE_PROVENANCE"

def test_rerun_determinism():
    import subprocess
    # Read existing audit
    with open(OUT_DIR / "v4c_3b_etf_audit.json", "r") as f:
        existing_data = json.load(f)
        
    # Rerun script
    cmd = [".venv/bin/python", "scripts/hmr_v4c_3b_etf_audit.py"]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0
    
    # Read new audit
    with open(OUT_DIR / "v4c_3b_etf_audit.json", "r") as f:
        new_data = json.load(f)
        
    # Compare
    assert existing_data["directional_audit"] == new_data["directional_audit"]
    assert existing_data["volatility_audit"] == new_data["volatility_audit"]
    assert existing_data["risk_state_audit"] == new_data["risk_state_audit"]
