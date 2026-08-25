#!/usr/bin/env python3
"""MC6-E — Full Universe Static Preflight.

Iterates every symbol in the canonical 22-symbol runtime universe through
the MC6 inference router and verifies complete coverage without launching
any paper canary or runtime process.
"""
import json
import hashlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.ml_engine.inference_router import (
    InferenceRouter,
    InferenceSymbolUnsupported,
    InferenceRouteIntegrityError,
)

MC1_CONTRACT       = REPO_ROOT / "model_coverage_mc1_contract.json"
MC6_INF_REGISTRY   = REPO_ROOT / "model_coverage_mc6_inference_registry.json"
MC6_RECONCILIATION = REPO_ROOT / "model_coverage_mc6_reconciliation.json"
MC6_PREFLIGHT      = REPO_ROOT / "model_coverage_mc6_universe_preflight.json"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, data: dict) -> None:
    content = json.dumps(data, indent=2, sort_keys=True)
    path.write_text(content, encoding="utf-8")
    sha_path = Path(str(path) + ".sha256")
    rel = path.relative_to(REPO_ROOT)
    sha_path.write_text(f"{_sha256_text(content)}  {rel}\n", encoding="utf-8")


def main() -> None:
    print("MC6-E: Full Universe Static Preflight …")

    mc1 = json.loads(MC1_CONTRACT.read_text(encoding="utf-8"))
    canonical = mc1["canonical_symbols"]

    recon = json.loads(MC6_RECONCILIATION.read_text(encoding="utf-8"))
    excluded_set = {e["symbol"] for e in recon["excluded_symbols"]}
    excluded_map = {e["symbol"]: e for e in recon["excluded_symbols"]}

    router = InferenceRouter(MC6_INF_REGISTRY, REPO_ROOT)

    results = []
    routable_ok = 0
    excluded_ok = 0
    ambiguous = 0
    integrity_fail = 0
    schema_fail = 0
    unsupported_enabled = 0

    for sym in canonical:
        entry: dict = {"symbol": sym}

        if sym in excluded_set:
            # Verify it's properly rejected
            try:
                router.resolve(sym)
                entry["status"] = "ERROR_EXCLUDED_BUT_ROUTABLE"
                ambiguous += 1
            except InferenceSymbolUnsupported:
                entry["status"] = "EXCLUDED_VERIFIED"
                entry["exclusion_class"] = excluded_map[sym]["exclusion_class"]
                excluded_ok += 1
            results.append(entry)
            continue

        # Symbol should be routable
        try:
            route = router.resolve(sym)
        except InferenceSymbolUnsupported:
            entry["status"] = "ERROR_ENABLED_BUT_NO_ROUTE"
            unsupported_enabled += 1
            results.append(entry)
            continue

        # Validate artifacts
        try:
            router.validate_route(route)
        except InferenceRouteIntegrityError as e:
            entry["status"] = "INTEGRITY_FAILURE"
            entry["detail"] = str(e)
            integrity_fail += 1
            results.append(entry)
            continue

        # Validate schema
        try:
            router.validate_schema(route)
        except InferenceRouteIntegrityError as e:
            entry["status"] = "SCHEMA_FAILURE"
            entry["detail"] = str(e)
            schema_fail += 1
            results.append(entry)
            continue

        entry["status"] = "ROUTABLE_OK"
        entry["route_type"] = route.route_type
        entry["route_version"] = route.route_version
        routable_ok += 1
        results.append(entry)

    preflight = {
        "artifact": "model_coverage_mc6_universe_preflight",
        "runtime_symbols": len(canonical),
        "accounted_symbols": len(canonical),
        "routable_enabled_symbols": routable_ok,
        "excluded_symbols": excluded_ok,
        "unsupported_enabled_symbols": unsupported_enabled,
        "ambiguous_routes": ambiguous,
        "artifact_integrity_failures": integrity_fail,
        "schema_failures": schema_fail,
        "preflight_verdict": "PASS" if (
            unsupported_enabled == 0
            and ambiguous == 0
            and integrity_fail == 0
            and schema_fail == 0
            and routable_ok + excluded_ok == len(canonical)
        ) else "FAIL",
        "results": results,
    }

    _write_json(MC6_PREFLIGHT, preflight)

    print(f"  Runtime symbols:             {len(canonical)}")
    print(f"  Accounted symbols:           {len(canonical)}")
    print(f"  Routable enabled symbols:    {routable_ok}")
    print(f"  Excluded symbols:            {excluded_ok}")
    print(f"  Unsupported enabled symbols: {unsupported_enabled}")
    print(f"  Ambiguous routes:            {ambiguous}")
    print(f"  Artifact integrity failures: {integrity_fail}")
    print(f"  Schema failures:             {schema_fail}")
    print(f"  Preflight verdict:           {preflight['preflight_verdict']}")


if __name__ == "__main__":
    main()
