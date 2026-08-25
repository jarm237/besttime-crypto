import json
import hashlib
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MC5_REGISTRY = REPO_ROOT / "model_coverage_mc5_qualification_registry.json"
MC5_REPORT = REPO_ROOT / "model_coverage_mc5_oos_report.json"
MC5_VERDICT = REPO_ROOT / "model_coverage_mc5_final_verdict.json"

ALL_MC5_OOS_FILES = [
    MC5_REGISTRY, MC5_REPORT, MC5_VERDICT
]

@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(MC5_REGISTRY.read_text())

@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(MC5_REPORT.read_text())

@pytest.fixture(scope="module")
def verdict() -> dict:
    return json.loads(MC5_VERDICT.read_text())

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def test_mc5_oos_sha_sidecars_valid() -> None:
    for path in ALL_MC5_OOS_FILES:
        sha_path = Path(str(path) + ".sha256")
        assert sha_path.exists()
        digest, rel_path = sha_path.read_text().strip().split()
        assert _sha256(REPO_ROOT / rel_path) == digest

def test_qualification_registry_contains_symbols(registry: dict) -> None:
    mc5_pop = json.loads((REPO_ROOT / "model_coverage_mc5_qualification_population.json").read_text())
    pop_symbols = [x["symbol"] for x in mc5_pop["population"]]
    
    registered_symbols = [x["symbol"] for x in registry["candidates"]]
    assert len(registered_symbols) == len(pop_symbols)
    for sym in pop_symbols:
        assert sym in registered_symbols

def test_final_verdict_closed(verdict: dict) -> None:
    assert verdict["mc5_state"] == "CLOSED"
    assert verdict["final_oos_qualification"] == "COMPLETED"
    assert verdict["runtime_routing"] == "UNCHANGED"
    assert verdict["activation"] == "NOT_AUTHORIZED"

def test_report_contains_metrics(report: dict) -> None:
    for entry in report["reports"]:
        metrics = entry["metrics"]
        assert "roc_auc" in metrics
        assert "pr_auc" in metrics
        assert "brier_score" in metrics
        assert "log_loss" in metrics
        assert "ece" in metrics
        assert "trade_count" in metrics
        assert "gross_ev" in metrics
        assert "net_ev" in metrics
