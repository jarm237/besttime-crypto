import json
from pathlib import Path
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4b_2b_premium_audit.json"
PARQUET_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4b_2b_premium_history.parquet"

def test_parquet_schema():
    assert PARQUET_PATH.exists()
    df = pd.read_parquet(PARQUET_PATH)
    required_cols = {
        "symbol", "open_time", "close_time",
        "premium_open", "premium_high", "premium_low", "premium_close",
        "source_timestamp", "available_at", "source",
        "provenance_class", "interval"
    }
    assert required_cols.issubset(df.columns)
    assert not df["available_at"].isna().any()
    assert (df["available_at"] == df["close_time"]).all()

def test_no_lookahead():
    df_quantiles = pd.read_parquet(REPO_ROOT / "research/historical_market_replay_v4/v4b_2b_premium_quantiles.parquet")
    time_col = "timestamp" if "timestamp" in df_quantiles.columns else "decision_time"
    df_valid = df_quantiles.dropna(subset=["available_at"])
    assert (df_valid["available_at"] <= df_valid[time_col]).all()

def test_determinism_invariant():
    # Read existing JSON verdict
    with open(JSON_PATH, "r") as f:
        existing_data = json.load(f)
        
    # Re-run the audit script
    import subprocess
    cmd = [".venv/bin/python", "scripts/hmr_v4b_2b_premium_audit.py"]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"Audit script failed: {res.stderr}"
    
    # Read the newly generated JSON verdict
    with open(JSON_PATH, "r") as f:
        new_data = json.load(f)
        
    # Assert features and verdicts match exactly
    assert len(existing_data["feature_verdicts"]) == len(new_data["feature_verdicts"])
    for i in range(len(existing_data["feature_verdicts"])):
        ev = existing_data["feature_verdicts"][i]
        nv = new_data["feature_verdicts"][i]
        assert ev["feature"] == nv["feature"]
        assert ev["verdict"] == nv["verdict"]
