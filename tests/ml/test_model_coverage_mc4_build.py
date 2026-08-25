import json
import hashlib
from pathlib import Path
import pytest
import joblib

REPO_ROOT = Path(__file__).resolve().parents[2]
MC4_CANDIDATE_REGISTRY = REPO_ROOT / "model_coverage_mc4_candidate_registry.json"
MC4_RUNS = REPO_ROOT / "model_coverage_mc4_build_runs.json"
MC4_FINAL_VERDICT = REPO_ROOT / "model_coverage_mc4_final_verdict.json"
CANDIDATE_OUT_DIR = REPO_ROOT / "research" / "model_coverage_mc4" / "candidates"

@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(MC4_CANDIDATE_REGISTRY.read_text())

@pytest.fixture(scope="module")
def verdict() -> dict:
    return json.loads(MC4_FINAL_VERDICT.read_text())

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def test_mc4_b_sha_sidecars_valid() -> None:
    for path in [MC4_CANDIDATE_REGISTRY, MC4_RUNS, MC4_FINAL_VERDICT]:
        sha_path = Path(str(path) + ".sha256")
        assert sha_path.exists()
        digest, rel_path = sha_path.read_text().strip().split()
        assert _sha256(REPO_ROOT / rel_path) == digest

def test_candidate_registry_contains_symbols(registry: dict) -> None:
    mc3_mat = json.loads((REPO_ROOT / "model_coverage_mc3_readiness_matrix.json").read_text())
    ready = [x["symbol"] for x in mc3_mat["readiness_matrix"] if x["final"] == "READY"]
    
    # SOPH, TRUMP, XPL are skipped due to lack of class balance (15 built candidates out of 18 ready)
    registered_symbols = [x["symbol"] for x in registry["candidates"]]
    assert len(registered_symbols) <= len(ready)
    for sym in registered_symbols:
        assert sym in ready

def test_artifacts_exist_and_marked_correctly(registry: dict) -> None:
    for cand in registry["candidates"]:
        sym = cand["symbol"]
        model_path = CANDIDATE_OUT_DIR / sym / "model.joblib"
        metadata_path = CANDIDATE_OUT_DIR / sym / "metadata.json"
        
        assert model_path.exists()
        assert metadata_path.exists()
        
        art = joblib.load(model_path)
        meta = art["metadata"]
        assert meta["artifact_status"] == "CANDIDATE"
        assert meta["qualification_status"] == "NOT_EVALUATED_MC5"
        
        meta_file = json.loads(metadata_path.read_text())
        assert meta_file["artifact_status"] == "CANDIDATE"
        assert meta_file["qualification_status"] == "NOT_EVALUATED_MC5"

def test_verdict_final_state(verdict: dict) -> None:
    assert verdict["mc4_state"] == "CLOSED"
    assert verdict["calibration"] == "NOT_STARTED"
    assert verdict["final_oos_qualification"] == "NOT_STARTED"
    assert verdict["runtime_routing"] == "UNCHANGED"
    assert verdict["activation"] == "NOT_AUTHORIZED"
