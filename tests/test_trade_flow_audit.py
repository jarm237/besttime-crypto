import json
from pathlib import Path
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"
PARQUET_PATH = OUT_DIR / "v4b_4b_trade_flow_history.parquet"
JSON_PATH = OUT_DIR / "v4b_4b_trade_flow_audit.json"

def test_trade_flow_files_exist():
    assert PARQUET_PATH.exists()
    assert JSON_PATH.exists()
    assert (OUT_DIR / "v4b_4b_trade_flow_report.md").exists()

def test_trade_flow_history_schema():
    df = pd.read_parquet(PARQUET_PATH)
    assert set(df["symbol"].unique()) == {"BTC", "ETH", "BNB"}
    required_cols = {
        "symbol", "open_time", "close_time",
        "taker_buy_notional", "taker_sell_notional",
        "taker_buy_qty", "taker_sell_qty", "trade_count",
        "source_timestamp", "available_at", "source",
        "provenance_class", "interval"
    }
    assert required_cols.issubset(df.columns)

    # Assert PIT boundary case: bar is only available at open_time + 15m
    assert (df["available_at"] == df["open_time"] + pd.Timedelta(minutes=15)).all()

def test_pit_no_lookahead():
    # Load audit JSON and assert verdicts are reject
    with open(JSON_PATH, "r") as f:
        data = json.load(f)

    assert len(data["feature_verdicts"]) == 5
    for fv in data["feature_verdicts"]:
        assert fv["verdict"] == "REJECT_NO_ECONOMIC_INFORMATION"
        assert fv["best_horizon"] is None
        for h in fv["horizons"]:
            assert h["verdict"] == "REJECT_NO_ECONOMIC_INFORMATION"
            assert h["pooled_spread_bps"] < h["floor_bps"]

def test_determinism_invariant():
    import subprocess
    # Read existing JSON verdict
    with open(JSON_PATH, "r") as f:
        existing_data = json.load(f)

    # Re-run the audit script
    import sys, os
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, "scripts/hmr_v4b_4b_trade_flow_audit.py"]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, encoding="utf-8")
    assert res.returncode == 0

    # Read newly generated JSON verdict
    with open(JSON_PATH, "r") as f:
        new_data = json.load(f)

    # Verify features and verdicts match exactly
    assert len(existing_data["feature_verdicts"]) == len(new_data["feature_verdicts"])
    for i in range(len(existing_data["feature_verdicts"])):
        ev = existing_data["feature_verdicts"][i]
        nv = new_data["feature_verdicts"][i]
        assert ev["feature"] == nv["feature"]
        assert ev["verdict"] == nv["verdict"]
        for j in range(len(ev["horizons"])):
            eh = ev["horizons"][j]
            nh = nv["horizons"][j]
            assert eh["horizon"] == nh["horizon"]
            assert eh["pooled_spread_bps"] == nh["pooled_spread_bps"]
            assert eh["verdict"] == nh["verdict"]
