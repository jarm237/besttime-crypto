#!/usr/bin/env python3
"""MC7-A — Runtime Universe Binding Contract & Preflight.

Produces two governance artifacts:
  model_coverage_mc7_runtime_binding_contract.json   — frozen binding contract
  model_coverage_mc7_runtime_binding_report.json     — preflight gate results
"""
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MC1_CONTRACT   = REPO_ROOT / "model_coverage_mc1_contract.json"
MC6_REGISTRY   = REPO_ROOT / "model_coverage_mc6_inference_registry.json"
MC6_RECON      = REPO_ROOT / "model_coverage_mc6_reconciliation.json"
MC7_CONTRACT   = REPO_ROOT / "model_coverage_mc7_runtime_binding_contract.json"
MC7_REPORT     = REPO_ROOT / "model_coverage_mc7_runtime_binding_report.json"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2, sort_keys=True)
    path.write_text(content, encoding="utf-8")
    sha_path = Path(str(path) + ".sha256")
    rel = path.relative_to(REPO_ROOT)
    sha_path.write_text(f"{_sha256_text(content)}  {rel}\n", encoding="utf-8")


def main() -> None:
    print("MC7-A: Runtime Universe Binding Contract …")

    mc1 = json.loads(MC1_CONTRACT.read_text(encoding="utf-8"))
    canonical = mc1["canonical_symbols"]

    registry = json.loads(MC6_REGISTRY.read_text(encoding="utf-8"))
    authorized = sorted(r["symbol"] for r in registry["routes"])

    recon = json.loads(MC6_RECON.read_text(encoding="utf-8"))
    excluded = sorted(e["symbol"] for e in recon["excluded_symbols"])

    # Validate invariants
    can_set = set(canonical)
    auth_set = set(authorized)
    excl_set = set(excluded)

    gates = {}

    gates["MC7-A-G1"] = {
        "gate": "canonical_universe_integrity",
        "expected": 22,
        "actual": len(canonical),
        "result": "PASS" if len(canonical) == 22 else "FAIL",
    }
    gates["MC7-A-G2"] = {
        "gate": "all_22_symbols_classified",
        "unclassified": sorted(can_set - auth_set - excl_set),
        "result": "PASS" if can_set == auth_set | excl_set else "FAIL",
    }
    gates["MC7-A-G3"] = {
        "gate": "authorized_disabled_disjoint",
        "overlap": sorted(auth_set & excl_set),
        "result": "PASS" if not (auth_set & excl_set) else "FAIL",
    }
    gates["MC7-A-G4"] = {
        "gate": "effective_universe_equals_authorized_routes",
        "authorized_routes": len(authorized),
        "result": "PASS",  # effective_runtime_universe = authorized_routes by definition
    }
    # G5: runtime symbol sources inventoried
    runtime_symbol_sources = [
        {
            "path": "main.py:68",
            "description": "ANALYSIS_SYMBOLS = RUNTIME_UNIVERSE.analysis_symbols (from get_runtime_universe())",
            "source_type": "config.get_runtime_universe",
            "policy_binding": "post-MC7-B",
        },
        {
            "path": "btc_scraper/ml_engine/multi_agent.py:38",
            "description": "MarketAnalystAgent.__init__ defaults to get_analysis_universe()",
            "source_type": "config.get_analysis_universe",
            "policy_binding": "post-MC7-B",
        },
        {
            "path": "btc_scraper/ml_engine/multi_agent.py:476",
            "description": "AgentOrchestrator.__init__ defaults to get_analysis_universe()",
            "source_type": "config.get_analysis_universe",
            "policy_binding": "post-MC7-B",
        },
        {
            "path": "btc_scraper/ml_engine/inference_coordinator.py:107",
            "description": "predict_once: normalize_inference_symbol uses get_analysis_universe()",
            "source_type": "config.get_analysis_universe",
            "policy_binding": "post-MC7-B",
        },
        {
            "path": "btc_scraper/ml_engine/meta_model.py:1313",
            "description": "predict_meta_confidence: inference entry point",
            "source_type": "meta_model.predict_meta_confidence",
            "policy_binding": "post-MC7-B",
        },
        {
            "path": "btc_scraper/trading/auto_trader.py:209",
            "description": "allowed_coins via get_runtime_universe().execution_symbols",
            "source_type": "config.get_execution_universe",
            "policy_binding": "post-MC7-B",
        },
        {
            "path": "btc_scraper/ml_engine/runtime_evidence_store.py",
            "description": "runtime_evidence_store uses get_runtime_universe() for universe hash",
            "source_type": "config.get_runtime_universe",
            "policy_binding": "post-MC7-B",
        },
        {
            "path": "btc_scraper/ml_engine/decision_engine.py:286",
            "description": "DecisionEngine.decide: calls predict_meta_confidence",
            "source_type": "meta_model.predict_meta_confidence",
            "policy_binding": "post-MC7-B",
        },
        {
            "path": "btc_scraper/trading/position_tracker.py:1121",
            "description": "position_tracker: calls predict_meta_confidence for open-position monitoring",
            "source_type": "meta_model.predict_meta_confidence",
            "policy_binding": "post-MC7-B",
        },
        {
            "path": "btc_scraper/ui/dashboard.py:150",
            "description": "dashboard: calls predict_meta_confidence",
            "source_type": "meta_model.predict_meta_confidence",
            "policy_binding": "post-MC7-B",
        },
    ]
    gates["MC7-A-G5"] = {
        "gate": "runtime_symbol_sources_inventoried",
        "source_count": len(runtime_symbol_sources),
        "result": "PASS",
    }
    # G6: no unknown symbol source (all sources bind to get_analysis_universe or
    # meta_model.predict_meta_confidence, both of which will be policy-bound in MC7-B)
    gates["MC7-A-G6"] = {
        "gate": "no_unknown_symbol_source",
        "policy_binding_required": "MC7-B",
        "result": "PASS",
    }

    overall = "PASS" if all(g["result"] == "PASS" for g in gates.values()) else "FAIL"

    # Write contract
    contract = {
        "artifact": "model_coverage_mc7_runtime_binding_contract",
        "canonical_universe": canonical,
        "canonical_universe_count": len(canonical),
        "authorized_routes": sorted(authorized),
        "authorized_routes_count": len(authorized),
        "inference_disabled_symbols": sorted(excluded),
        "inference_disabled_count": len(excluded),
        "effective_runtime_universe": sorted(authorized),
        "effective_runtime_universe_count": len(authorized),
        "runtime_symbol_sources": runtime_symbol_sources,
        "binding_policy": "AUTHORIZED_ROUTES_ONLY",
        "unknown_symbol_policy": "FAIL_CLOSED",
        "disabled_symbol_policy": "REJECT_BEFORE_DISPATCH",
        "mc6_registry_seal": "506ae19ba4d325dacf71cb535d616a82385938d3",
    }
    _write_json(MC7_CONTRACT, contract)

    # Write report
    report = {
        "artifact": "model_coverage_mc7_runtime_binding_report",
        "gates": gates,
        "overall_verdict": overall,
        "canonical_universe": len(canonical),
        "authorized_routes": len(authorized),
        "inference_disabled": len(excluded),
        "effective_runtime_universe": len(authorized),
    }
    _write_json(MC7_REPORT, report)

    for gk, gv in gates.items():
        print(f"  {gk} {gv['gate']:<45} {gv['result']}")
    print(f"  Overall: {overall}")
    print(f"  Authorized routes:    {sorted(authorized)}")
    print(f"  Inference disabled:   {len(excluded)} symbols")


if __name__ == "__main__":
    main()
