import json
import hashlib
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MC3_CONTRACT = REPO_ROOT / "model_coverage_mc3_contract.json"
MC4_POPULATION = REPO_ROOT / "model_coverage_mc4_build_population.json"
MC4_ARCH_CONTRACT = REPO_ROOT / "model_coverage_mc4_architecture_contract.json"
MC4_TRAINING_CONTRACT = REPO_ROOT / "model_coverage_mc4_training_contract.json"
MC4_BASELINE_CONTRACT = REPO_ROOT / "model_coverage_mc4_baseline_contract.json"
MC4_SEARCH_CONTRACT = REPO_ROOT / "model_coverage_mc4_search_contract.json"
MC4_ARTIFACT_CONTRACT = REPO_ROOT / "model_coverage_mc4_artifact_contract.json"
MC4_AUTH = REPO_ROOT / "model_coverage_mc4_build_authorization.json"

ALL_MC4_CONTRACTS = [
    MC4_POPULATION, MC4_ARCH_CONTRACT, MC4_TRAINING_CONTRACT,
    MC4_BASELINE_CONTRACT, MC4_SEARCH_CONTRACT, MC4_ARTIFACT_CONTRACT, MC4_AUTH
]

@pytest.fixture(scope="module")
def pop() -> dict:
    return json.loads(MC4_POPULATION.read_text())

@pytest.fixture(scope="module")
def auth() -> dict:
    return json.loads(MC4_AUTH.read_text())

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def test_mc4_sha_sidecars_valid() -> None:
    for path in ALL_MC4_CONTRACTS:
        sha_path = Path(str(path) + ".sha256")
        assert sha_path.exists()
        digest, rel_path = sha_path.read_text().strip().split()
        assert _sha256(REPO_ROOT / rel_path) == digest

def test_mc4_base_lineage_correct(auth: dict) -> None:
    assert auth["mc4_base_commit"] == "73633f3"
    assert auth["mc3_contract_hash"] == _sha256(MC3_CONTRACT)

def test_build_population_exactly_mc3_ready(pop: dict) -> None:
    mc3_mat = json.loads((REPO_ROOT / "model_coverage_mc3_readiness_matrix.json").read_text())
    ready = [x["symbol"] for x in mc3_mat["readiness_matrix"] if x["final"] == "READY"]
    assert sorted(pop["mc3_ready_subset"]) == sorted(ready)

def test_blocked_mc3_symbol_not_included(pop: dict) -> None:
    mc3_mat = json.loads((REPO_ROOT / "model_coverage_mc3_readiness_matrix.json").read_text())
    blocked = [x["symbol"] for x in mc3_mat["readiness_matrix"] if x["final"] != "READY"]
    assert len(blocked) > 0
    for sym in blocked:
        assert sym not in pop["mc3_ready_subset"]

def test_supported_major_coins_not_in_required_list(pop: dict) -> None:
    for sym in ["BTC", "ETH", "BNB"]:
        assert sym not in pop["mc3_ready_subset"]

def test_training_and_validation_splits_exist() -> None:
    split_c = json.loads((REPO_ROOT / "model_coverage_mc3_split_contract.json").read_text())
    splits = split_c["split_contract"]["splits"]
    assert "train" in splits
    assert "validation" in splits
    assert "calibration" in splits
    assert "OOS" in splits
