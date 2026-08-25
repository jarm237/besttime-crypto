#!/usr/bin/env python3
"""MC6-B — Immutable Inference Registry Construction.

Builds a deterministic, content-addressed inference registry mapping each
routable symbol to its exact model artifact, calibrator, feature schema,
and full provenance chain.
"""
import json
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── Input artifacts ──────────────────────────────────────────────────────────

MC6_RECONCILIATION = REPO_ROOT / "model_coverage_mc6_reconciliation.json"
MC6_INTEGRATION    = REPO_ROOT / "model_coverage_mc6_integration_contract.json"
MC4_REGISTRY       = REPO_ROOT / "model_coverage_mc4_candidate_registry.json"
MC5_QUAL_REG       = REPO_ROOT / "model_coverage_mc5_qualification_registry.json"
MC5_CAL_RUNS       = REPO_ROOT / "model_coverage_mc5_calibration_runs.json"
MC5_POPULATION     = REPO_ROOT / "model_coverage_mc5_qualification_population.json"

# ── Output ───────────────────────────────────────────────────────────────────

MC6_INF_REGISTRY = REPO_ROOT / "model_coverage_mc6_inference_registry.json"

# ── Paths ────────────────────────────────────────────────────────────────────

CANDIDATE_DIR  = REPO_ROOT / "research" / "model_coverage_mc4" / "candidates"
CALIBRATOR_DIR = REPO_ROOT / "research" / "model_coverage_mc5"

LEGACY_SYMBOLS = {"BTC", "ETH", "BNB"}

FEATURE_SCHEMA = ["return_8", "return_32", "return_72", "abs_move_72"]
FEATURE_SCHEMA_VERSION = "features_v5_4f"


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
    print("MC6-B: Building Immutable Inference Registry …")

    recon = json.loads(MC6_RECONCILIATION.read_text(encoding="utf-8"))
    assert recon["reconciliation_verdict"] == "PASS"

    mc4 = json.loads(MC4_REGISTRY.read_text(encoding="utf-8"))
    mc4_map = {e["symbol"]: e for e in mc4["candidates"]}

    mc5_reg = json.loads(MC5_QUAL_REG.read_text(encoding="utf-8"))
    mc5_map = {e["symbol"]: e for e in mc5_reg["candidates"]}

    mc5_pop = json.loads(MC5_POPULATION.read_text(encoding="utf-8"))
    mc5_pop_map = {e["symbol"]: e for e in mc5_pop["population"]}

    mc5_cal = json.loads(MC5_CAL_RUNS.read_text(encoding="utf-8"))
    mc5_cal_map = {e["symbol"]: e for e in mc5_cal["runs"]}

    routes = []
    integrity_failures = []

    for sym in recon["routable_symbols"]:
        if sym in LEGACY_SYMBOLS:
            # Legacy route — reference existing meta_model artifact
            routes.append({
                "symbol": sym,
                "route_type": "LEGACY",
                "route_version": "legacy-v1",
                "model_artifact_path": None,
                "model_sha256": None,
                "calibrator_artifact_path": None,
                "calibrator_sha256": None,
                "feature_schema": FEATURE_SCHEMA,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "training_contract": "pre-mc-pipeline",
                "qualification_contract": "pre-mc-pipeline",
                "qualification_verdict": "LEGACY_GRANDFATHERED",
            })
            continue

        # MC5 qualified symbol
        model_path = CANDIDATE_DIR / sym / "model.joblib"
        calibrator_path = CALIBRATOR_DIR / sym / "calibrator.joblib"

        if not model_path.exists():
            integrity_failures.append(f"{sym}: model artifact missing at {model_path}")
            continue
        if not calibrator_path.exists():
            integrity_failures.append(f"{sym}: calibrator missing at {calibrator_path}")
            continue

        model_sha = _sha256_file(model_path)
        cal_sha = _sha256_file(calibrator_path)

        # Cross-check SHA against MC4 registry
        mc4_entry = mc4_map.get(sym, {})
        mc4_expected_sha = mc4_entry.get("artifact_sha256")
        if mc4_expected_sha and mc4_expected_sha != model_sha:
            integrity_failures.append(
                f"{sym}: model SHA mismatch — registry {mc4_expected_sha}, disk {model_sha}"
            )

        # Cross-check calibrator SHA against MC5 calibration runs
        cal_entry = mc5_cal_map.get(sym, {})
        cal_expected_sha = cal_entry.get("calibrator_sha256")
        if cal_expected_sha and cal_expected_sha != cal_sha:
            integrity_failures.append(
                f"{sym}: calibrator SHA mismatch — registry {cal_expected_sha}, disk {cal_sha}"
            )

        mc5_entry = mc5_map.get(sym, {})

        routes.append({
            "symbol": sym,
            "route_type": "MC5_QUALIFIED",
            "route_version": "mc5-v1",
            "model_artifact_path": str(model_path.relative_to(REPO_ROOT)),
            "model_sha256": model_sha,
            "calibrator_artifact_path": str(calibrator_path.relative_to(REPO_ROOT)),
            "calibrator_sha256": cal_sha,
            "feature_schema": FEATURE_SCHEMA,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "training_contract": "model-coverage-mc4/v1",
            "qualification_contract": "model-coverage-mc5/v1",
            "qualification_verdict": mc5_entry.get("final_verdict", "UNKNOWN"),
            "mc4_artifact_id": mc4_entry.get("artifact_id"),
            "mc5_calibrator_id": mc5_entry.get("calibrator_id"),
        })

    if integrity_failures:
        print("INTEGRITY FAILURES:")
        for f in integrity_failures:
            print(f"  ✗ {f}")
        sys.exit(1)

    # Compute whole-registry hash for determinism verification
    feature_schema_content = json.dumps(FEATURE_SCHEMA, sort_keys=True)
    feature_schema_sha = _sha256_text(feature_schema_content)

    registry_data = {
        "artifact": "model_coverage_mc6_inference_registry",
        "registry_version": "mc6-v1",
        "routes": routes,
        "feature_schema_sha256": feature_schema_sha,
        "routable_count": len(routes),
        "legacy_count": sum(1 for r in routes if r["route_type"] == "LEGACY"),
        "mc5_qualified_count": sum(1 for r in routes if r["route_type"] == "MC5_QUALIFIED"),
        "integrity_failures": integrity_failures,
    }

    # Compute registry hash
    canonical_content = json.dumps(registry_data, indent=2, sort_keys=True)
    registry_data["registry_sha256"] = _sha256_text(canonical_content)

    _write_json(MC6_INF_REGISTRY, registry_data)

    print(f"  Routes:            {len(routes)}")
    print(f"  Legacy:            {registry_data['legacy_count']}")
    print(f"  MC5 qualified:     {registry_data['mc5_qualified_count']}")
    print(f"  Integrity failures: {len(integrity_failures)}")
    print("MC6-B: Inference registry built successfully.")


if __name__ == "__main__":
    main()
