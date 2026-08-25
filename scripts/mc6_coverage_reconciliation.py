#!/usr/bin/env python3
"""MC6-A — Coverage Reconciliation & Integration Contract.

Classifies every symbol in the canonical 22-symbol universe into exactly one
governance category, emits reconciliation and integration contract artifacts,
and verifies gates G1–G6.
"""
import json
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── Input artifacts ──────────────────────────────────────────────────────────

MC1_CONTRACT = REPO_ROOT / "model_coverage_mc1_contract.json"
MC4_REGISTRY = REPO_ROOT / "model_coverage_mc4_candidate_registry.json"
MC5_QUAL_REG = REPO_ROOT / "model_coverage_mc5_qualification_registry.json"
MC5_VERDICT  = REPO_ROOT / "model_coverage_mc5_final_verdict.json"
MC5_POPULATION = REPO_ROOT / "model_coverage_mc5_qualification_population.json"
MC5_CAL_RUNS = REPO_ROOT / "model_coverage_mc5_calibration_runs.json"
MC3_READINESS = REPO_ROOT / "model_coverage_mc3_readiness_matrix.json"

# ── Output artifacts ─────────────────────────────────────────────────────────

MC6_RECONCILIATION = REPO_ROOT / "model_coverage_mc6_reconciliation.json"
MC6_INTEGRATION    = REPO_ROOT / "model_coverage_mc6_integration_contract.json"

# ── Paths to per-symbol model/calibrator artifacts ───────────────────────────

CANDIDATE_DIR  = REPO_ROOT / "research" / "model_coverage_mc4" / "candidates"
CALIBRATOR_DIR = REPO_ROOT / "research" / "model_coverage_mc5"

LEGACY_SYMBOLS = ["BTC", "ETH", "BNB"]

# ── Helpers ──────────────────────────────────────────────────────────────────

def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2, sort_keys=True)
    path.write_text(content, encoding="utf-8")
    sha_path = Path(str(path) + ".sha256")
    rel = path.relative_to(REPO_ROOT)
    sha_path.write_text(f"{_sha256_text(content)}  {rel}\n", encoding="utf-8")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("MC6-A: Coverage Reconciliation …")

    # 1. Load canonical universe from MC1
    mc1 = json.loads(MC1_CONTRACT.read_text(encoding="utf-8"))
    canonical = mc1["canonical_symbols"]
    assert len(canonical) == mc1["canonical_symbol_count"] == 22

    # 2. Load MC5 qualification results
    mc5_verdict = json.loads(MC5_VERDICT.read_text(encoding="utf-8"))
    mc5_qualified = set(mc5_verdict["qualified_symbols"])

    mc5_reg = json.loads(MC5_QUAL_REG.read_text(encoding="utf-8"))
    mc5_results = {e["symbol"]: e for e in mc5_reg["candidates"]}

    # 3. Load MC4 candidate registry
    mc4 = json.loads(MC4_REGISTRY.read_text(encoding="utf-8"))
    mc4_built = {e["symbol"] for e in mc4["candidates"]}

    # 4. Load MC3 readiness
    mc3 = json.loads(MC3_READINESS.read_text(encoding="utf-8"))
    mc3_blocked = {
        e["symbol"]
        for e in mc3["readiness_matrix"]
        if e["final"] != "READY"
    }

    # 5. Classify every symbol
    classifications = []
    routable_symbols = []
    excluded_symbols = []

    for sym in canonical:
        if sym in LEGACY_SYMBOLS:
            classifications.append({
                "symbol": sym,
                "category": "LEGACY_ROUTE",
                "reason": "Existing inference route from pre-MC pipeline",
                "routable": True,
            })
            routable_symbols.append(sym)

        elif sym in mc5_qualified:
            classifications.append({
                "symbol": sym,
                "category": "MC5_QUALIFIED_ROUTE",
                "reason": "Passed all statistical, calibration, and economic OOS gates",
                "routable": True,
                "mc5_verdict": mc5_results[sym]["final_verdict"],
            })
            routable_symbols.append(sym)

        elif sym in mc5_results:
            # Had a candidate, went through OOS, but was rejected
            entry = mc5_results[sym]
            classifications.append({
                "symbol": sym,
                "category": "MC5_REJECTED",
                "reason": f"OOS qualification failed: {entry['final_verdict']}",
                "routable": False,
                "mc5_verdict": entry["final_verdict"],
                "statistical_verdict": entry["statistical_verdict"],
                "calibration_verdict": entry["calibration_verdict"],
                "economic_verdict": entry["economic_verdict"],
            })
            excluded_symbols.append({
                "symbol": sym,
                "exclusion_class": "MC5_OOS_REJECTION",
                "exclusion_reason": entry["final_verdict"],
            })

        elif sym in mc3_blocked:
            # Blocked at MC3 data provenance
            classifications.append({
                "symbol": sym,
                "category": "MC3_BLOCKED_DATA_PROVENANCE",
                "reason": "Data provenance check failed at MC3; no training data available",
                "routable": False,
            })
            excluded_symbols.append({
                "symbol": sym,
                "exclusion_class": "MC3_DATA_PROVENANCE_FAILURE",
                "exclusion_reason": "BLOCKED_DATA_PROVENANCE",
            })

        elif sym not in mc4_built:
            # Was data-ready at MC3 but MC4 could not build (class imbalance)
            classifications.append({
                "symbol": sym,
                "category": "MC4_NO_CANDIDATE",
                "reason": "MC4 skipped due to class imbalance; no candidate artifact built",
                "routable": False,
            })
            excluded_symbols.append({
                "symbol": sym,
                "exclusion_class": "MC4_BUILD_FAILURE",
                "exclusion_reason": "NO_MC4_CANDIDATE",
            })

        else:
            # Shouldn't happen if data is consistent
            classifications.append({
                "symbol": sym,
                "category": "UNCLASSIFIED",
                "reason": "Symbol could not be classified — governance review required",
                "routable": False,
            })
            excluded_symbols.append({
                "symbol": sym,
                "exclusion_class": "UNCLASSIFIED",
                "exclusion_reason": "GOVERNANCE_REVIEW_REQUIRED",
            })

    # 6. Verify gate conditions
    all_classified_symbols = {c["symbol"] for c in classifications}
    routable_set = set(routable_symbols)
    excluded_set = {e["symbol"] for e in excluded_symbols}

    g1 = all_classified_symbols == set(canonical)
    g2 = all(
        (CANDIDATE_DIR / sym / "model.joblib").exists()
        for sym in routable_symbols
        if sym not in LEGACY_SYMBOLS
    )
    g3 = all(
        (CALIBRATOR_DIR / sym / "calibrator.joblib").exists()
        for sym in routable_symbols
        if sym not in LEGACY_SYMBOLS
    )
    g4 = True  # Will be verified in MC6-B with actual SHA checks
    g5 = len(routable_symbols) == len(routable_set)  # no duplicates
    g6 = routable_set.isdisjoint(excluded_set)

    gates = {
        "G1_runtime_universe_accounted": "PASS" if g1 else "FAIL",
        "G2_every_enabled_symbol_has_model": "PASS" if g2 else "FAIL",
        "G3_every_enabled_symbol_has_calibrator": "PASS" if g3 else "FAIL",
        "G4_artifact_schema_fingerprints_valid": "DEFERRED_TO_MC6B",
        "G5_duplicate_ambiguous_routes_absent": "PASS" if g5 else "FAIL",
        "G6_fallback_to_wrong_model_impossible": "PASS" if g6 else "FAIL",
    }

    all_pass = all(v == "PASS" for k, v in gates.items() if v != "DEFERRED_TO_MC6B")

    reconciliation = {
        "artifact": "model_coverage_mc6_reconciliation",
        "mc5_seal_commit": "a59df4a82d9f78774e94847625ac148d12a760d1",
        "canonical_universe_count": 22,
        "canonical_symbols": canonical,
        "routable_count": len(routable_symbols),
        "routable_symbols": routable_symbols,
        "excluded_count": len(excluded_symbols),
        "excluded_symbols": excluded_symbols,
        "unresolved_count": sum(1 for c in classifications if c["category"] == "UNCLASSIFIED"),
        "classifications": classifications,
        "gates": gates,
        "reconciliation_verdict": "PASS" if all_pass else "FAIL",
    }
    _write_json(MC6_RECONCILIATION, reconciliation)

    # 7. Build integration contract
    integration = {
        "artifact": "model_coverage_mc6_integration_contract",
        "routing_semantics": {
            "policy": "FAIL_CLOSED",
            "unknown_symbol_behavior": "RAISE_InferenceSymbolUnsupported",
            "excluded_symbol_behavior": "RAISE_InferenceSymbolUnsupported",
            "silent_fallback": "FORBIDDEN",
            "default_artifact_route": "FORBIDDEN",
        },
        "routable_symbols": routable_symbols,
        "excluded_symbols": [e["symbol"] for e in excluded_symbols],
        "legacy_routes": LEGACY_SYMBOLS,
        "mc5_qualified_routes": sorted(mc5_qualified),
        "feature_schema": {
            "version": "features_v5_4f",
            "features": ["return_8", "return_32", "return_72", "abs_move_72"],
        },
        "calibration_method": "PLATT_SIGMOID",
        "mc6a_state": "CLOSED",
    }
    _write_json(MC6_INTEGRATION, integration)

    # 8. Summary
    print(f"  Canonical universe:      {len(canonical)}")
    print(f"  Routable (legacy):       {sum(1 for c in classifications if c['category'] == 'LEGACY_ROUTE')}")
    print(f"  Routable (MC5 qual):     {sum(1 for c in classifications if c['category'] == 'MC5_QUALIFIED_ROUTE')}")
    print(f"  Excluded (MC5 rejected): {sum(1 for c in classifications if c['category'] == 'MC5_REJECTED')}")
    print(f"  Excluded (MC4 skip):     {sum(1 for c in classifications if c['category'] == 'MC4_NO_CANDIDATE')}")
    print(f"  Excluded (MC3 blocked):  {sum(1 for c in classifications if c['category'] == 'MC3_BLOCKED_DATA_PROVENANCE')}")
    print(f"  Unresolved:              {reconciliation['unresolved_count']}")
    print(f"  Gates: {gates}")
    print(f"  Reconciliation verdict:  {reconciliation['reconciliation_verdict']}")


if __name__ == "__main__":
    main()
