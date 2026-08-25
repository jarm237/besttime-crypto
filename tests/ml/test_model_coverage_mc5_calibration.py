import json
import hashlib
from pathlib import Path
import pytest
import joblib

REPO_ROOT = Path(__file__).resolve().parents[2]
MC5_RUNS = REPO_ROOT / "model_coverage_mc5_calibration_runs.json"
CALIBRATOR_OUT_DIR = REPO_ROOT / "research" / "model_coverage_mc5"

@pytest.fixture(scope="module")
def runs() -> dict:
    return json.loads(MC5_RUNS.read_text())

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def test_mc5_calibration_runs_sidecar_valid() -> None:
    sha_path = Path(str(MC5_RUNS) + ".sha256")
    assert sha_path.exists()
    digest, rel_path = sha_path.read_text().strip().split()
    assert _sha256(REPO_ROOT / rel_path) == digest

def test_calibrators_constructed_and_reloadable(runs: dict) -> None:
    for run in runs["runs"]:
        sym = run["symbol"]
        if run["status"] == "CALIBRATED":
            cal_path = CALIBRATOR_OUT_DIR / sym / "calibrator.joblib"
            meta_path = CALIBRATOR_OUT_DIR / sym / "calibrator_metadata.json"
            
            assert cal_path.exists()
            assert meta_path.exists()
            
            pkg = joblib.load(cal_path)
            assert "calibrator" in pkg
            assert "metadata" in pkg
            
            meta = pkg["metadata"]
            assert meta["status"] == "CANDIDATE_CALIBRATOR"
            assert meta["qualification"] == "NOT_STARTED"
            assert meta["method"] == "PLATT_SIGMOID"
            
            # verify meta files match
            meta_file = json.loads(meta_path.read_text())
            assert meta_file["model_artifact_sha256"] == meta["model_artifact_sha256"]
            assert meta_file["calibration_dataset_sha256"] == meta["calibration_dataset_sha256"]
            assert meta_file["method"] == meta["method"]
