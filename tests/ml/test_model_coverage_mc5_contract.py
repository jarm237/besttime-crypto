import json
import hashlib
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MC4_FINAL_VERDICT = REPO_ROOT / "model_coverage_mc4_final_verdict.json"
MC5_POPULATION = REPO_ROOT / "model_coverage_mc5_qualification_population.json"
MC5_CONTRACT = REPO_ROOT / "model_coverage_mc5_qualification_contract.json"
MC5_AUTH = REPO_ROOT / "model_coverage_mc5_qualification_authorization.json"

ALL_MC5_CONTRACTS = [
    MC5_POPULATION, MC5_CONTRACT, MC5_AUTH
]

@pytest.fixture(scope="module")
def pop() -> dict:
    return json.loads(MC5_POPULATION.read_text())

@pytest.fixture(scope="module")
def auth() -> dict:
    return json.loads(MC5_AUTH.read_text())

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def test_mc5_sha_sidecars_valid() -> None:
    for path in ALL_MC5_CONTRACTS:
        sha_path = Path(str(path) + ".sha256")
        assert sha_path.exists()
        digest, rel_path = sha_path.read_text().strip().split()
        assert _sha256(REPO_ROOT / rel_path) == digest

def test_mc5_base_lineage_correct(auth: dict) -> None:
    assert auth["mc5_base_commit"] == "e31e73abb1b99d47ea6879f6b3ab5943e548b81e"
    assert auth["mc4_verdict_hash"] == _sha256(MC4_FINAL_VERDICT)

def test_qualification_population_exactly_15_symbols(pop: dict) -> None:
    mc4_reg = json.loads((REPO_ROOT / "model_coverage_mc4_candidate_registry.json").read_text())
    candidates = [x["symbol"] for x in mc4_reg["candidates"]]
    
    pop_symbols = [x["symbol"] for x in pop["population"]]
    assert len(pop_symbols) == 15
    assert sorted(pop_symbols) == sorted(candidates)

def test_excluded_symbols_not_in_population(pop: dict) -> None:
    pop_symbols = [x["symbol"] for x in pop["population"]]
    for forbidden in ["SOPH", "TRUMP", "XPL", "BTC", "ETH", "BNB"]:
        assert forbidden not in pop_symbols
