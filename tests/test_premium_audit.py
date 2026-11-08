import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = REPO_ROOT / "research/historical_market_replay_v4"
AUDIT_SCRIPT = REPO_ROOT / "scripts/hmr_v4b_2b_premium_audit.py"
JSON_PATH = RESEARCH_DIR / "v4b_2b_premium_audit.json"
PARQUET_PATH = RESEARCH_DIR / "v4b_2b_premium_history.parquet"
GENERATED_PARQUETS = (
    "v4b_2b_premium_asset_stability.parquet",
    "v4b_2b_premium_conditional.parquet",
    "v4b_2b_premium_funding_redundancy.parquet",
    "v4b_2b_premium_monthly_stability.parquet",
    "v4b_2b_premium_quantiles.parquet",
    "v4b_2b_premium_tail_sensitivity.parquet",
)
CANONICAL_OUTPUTS = (
    JSON_PATH,
    RESEARCH_DIR / "v4b_2b_premium_report.md",
    *(RESEARCH_DIR / name for name in GENERATED_PARQUETS),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

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

def test_determinism_invariant(tmp_path: Path):
    # Read existing JSON verdict
    with open(JSON_PATH, "r") as f:
        existing_data = json.load(f)
    canonical_hashes_before = {path: _sha256(path) for path in CANONICAL_OUTPUTS}

    # Re-run the audit script with generated artifacts isolated from the repository.
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cmd = [sys.executable, str(AUDIT_SCRIPT), "--output-dir", str(tmp_path)]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, encoding="utf-8")
    assert res.returncode == 0, f"Audit script failed: {res.stderr}"

    # Read the newly generated JSON verdict
    with open(tmp_path / JSON_PATH.name, "r") as f:
        new_data = json.load(f)

    # Assert features and verdicts match exactly
    assert len(existing_data["feature_verdicts"]) == len(new_data["feature_verdicts"])
    for i in range(len(existing_data["feature_verdicts"])):
        ev = existing_data["feature_verdicts"][i]
        nv = new_data["feature_verdicts"][i]
        assert ev["feature"] == nv["feature"]
        assert ev["verdict"] == nv["verdict"]

    # Byte serialization may vary by PyArrow version, but table semantics must not.
    for name in GENERATED_PARQUETS:
        expected = pd.read_parquet(RESEARCH_DIR / name)
        actual = pd.read_parquet(tmp_path / name)
        assert actual.equals(expected), f"Generated parquet differs semantically: {name}"

    assert (tmp_path / "v4b_2b_premium_report.md").exists()
    assert {path: _sha256(path) for path in CANONICAL_OUTPUTS} == canonical_hashes_before
