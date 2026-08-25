#!/usr/bin/env python3
"""MC9-A — Freeze immutable release identity for model-coverage-v1.

Reads all upstream MC artifacts (MC6–MC8), verifies their SHA256 fingerprints
against disk, and writes a single canonical release identity document that
can be referenced by the P7 authorization in MC9-E.

Hard stop: any mismatch → non-zero exit, no output file written.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# ── constants ────────────────────────────────────────────────────────────────
EXPECTED_SOURCE_COMMIT = "94407d3483bb01eccf0e86882cef258dcbb646e9"
EXPECTED_RELEASE_VERSION = "model-coverage-v1"
AUTHORIZED_SYMBOLS = ["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"]
DISABLED_SYMBOLS = ["AEVO", "AR", "AVAX", "ENA", "SOPH", "TAO", "TRB", "TRUMP",
                    "WLD", "XAUT", "XLM", "XPL", "XRP"]
CANONICAL_UNIVERSE = 22
WORKTREE_PATH = ROOT / "runtime" / "worktrees" / "pinned-94407d3"
RELEASE_DIR = ROOT / "runtime" / "releases" / "model-coverage-v1"

# ── artifact paths ────────────────────────────────────────────────────────────
MC8_VERDICT = ROOT / "model_coverage_mc8_final_verdict.json"
MC8_CONTRACT = ROOT / "model_coverage_mc8_release_contract.json"
MC8_MANIFEST = ROOT / "model_coverage_mc8_release_manifest.json"
MC8_INVENTORY = ROOT / "model_coverage_mc8_artifact_inventory.json"
MC6_REGISTRY = ROOT / "model_coverage_mc6_inference_registry.json"
MC7_BINDING = ROOT / "model_coverage_mc7_runtime_binding_contract.json"
MC7_VERDICT = ROOT / "model_coverage_mc7_final_verdict.json"

OUTPUT = ROOT / "model_coverage_mc9_release_identity.json"
OUTPUT_SHA = ROOT / "model_coverage_mc9_release_identity.json.sha256"


# ── helpers ───────────────────────────────────────────────────────────────────
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_bytes())


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def gate(label: str, ok: bool, detail: str = "") -> dict[str, Any]:
    status = "PASS" if ok else "FAIL"
    print(f"  {label}: {status}{(' — ' + detail) if detail else ''}")
    if not ok:
        fail(f"Gate {label} failed: {detail}")
    return {"gate": label, "result": status}


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    print("MC9-A Release Identity Preflight")
    print("=" * 50)

    gates: dict[str, Any] = {}

    # ── G1: MC8 CLOSED ────────────────────────────────────────────────────────
    verdict = load_json(MC8_VERDICT)
    gates["MC9-A-G1"] = gate(
        "MC9-A-G1",
        verdict.get("mc8_verdict") == "CLOSED",
        f"mc8_verdict={verdict.get('mc8_verdict')}",
    )

    # ── G2: source commit exact ───────────────────────────────────────────────
    contract = load_json(MC8_CONTRACT)
    gates["MC9-A-G2"] = gate(
        "MC9-A-G2",
        contract["source_commit"] == EXPECTED_SOURCE_COMMIT,
        f"got {contract['source_commit'][:12]}",
    )

    # ── G3: release manifest sha256 matches disk ─────────────────────────────
    manifest_sha = sha256_file(MC8_MANIFEST)
    recorded_manifest_sha = contract["mc6_registry_sha256"]  # cross-ref via registry
    # The manifest sha is recorded in the pinned runtime report
    pinned_report = ROOT / "model_coverage_mc8_pinned_runtime_report.json"
    pinned = load_json(pinned_report)
    recorded_manifest_sha_from_pinned = pinned["manifest_sha256"]
    gates["MC9-A-G3"] = gate(
        "MC9-A-G3",
        manifest_sha == recorded_manifest_sha_from_pinned,
        f"disk={manifest_sha[:12]} pinned={recorded_manifest_sha_from_pinned[:12]}",
    )

    # ── G4: registry sha256 matches disk ─────────────────────────────────────
    registry_sha = sha256_file(MC6_REGISTRY)
    gates["MC9-A-G4"] = gate(
        "MC9-A-G4",
        registry_sha == contract["mc6_registry_sha256"],
        f"disk={registry_sha[:12]} contract={contract['mc6_registry_sha256'][:12]}",
    )

    # ── G5: runtime binding sha256 matches disk ───────────────────────────────
    binding_sha = sha256_file(MC7_BINDING)
    gates["MC9-A-G5"] = gate(
        "MC9-A-G5",
        binding_sha == contract["mc7_verdict_sha256"],
        f"disk={binding_sha[:12]} contract={contract['mc7_verdict_sha256'][:12]}",
    )

    # ── G6: all 9 route artifacts present and hash-verified in bundle ─────────
    manifest = load_json(MC8_MANIFEST)
    routes = manifest.get("routes", {})
    route_identities: dict[str, Any] = {}
    route_failures: list[str] = []

    for sym in AUTHORIZED_SYMBOLS:
        route = routes.get(sym, {})
        route_type = route.get("route_type", "UNKNOWN")
        model_sha = contract["model_fingerprints"].get(sym, "")
        calib_sha = contract["calibrator_fingerprints"].get(sym, "")

        # Verify model artifact in bundle (for MC5-qualified symbols)
        artifact_ok = True
        if route_type == "MC5_QUALIFIED":
            model_path_rel = f"research/model_coverage_mc4/candidates/{sym}/model.joblib"
            calib_path_rel = f"research/model_coverage_mc5/{sym}/calibrator.joblib"
            model_in_bundle = RELEASE_DIR / model_path_rel
            calib_in_bundle = RELEASE_DIR / calib_path_rel
            if not model_in_bundle.exists():
                route_failures.append(f"{sym}: model missing from bundle")
                artifact_ok = False
            elif sha256_file(model_in_bundle) != model_sha:
                route_failures.append(f"{sym}: model sha256 mismatch in bundle")
                artifact_ok = False
            if not calib_in_bundle.exists():
                route_failures.append(f"{sym}: calibrator missing from bundle")
                artifact_ok = False
            elif sha256_file(calib_in_bundle) != calib_sha:
                route_failures.append(f"{sym}: calibrator sha256 mismatch in bundle")
                artifact_ok = False
        elif route_type in ("LEGACY", "grandfathered_global", ""):
            # Legacy: model loaded from global logs/
            legacy_model = RELEASE_DIR / "logs" / "meta_model.joblib"
            artifact_ok = legacy_model.exists()
            if not artifact_ok:
                route_failures.append(f"{sym}: legacy model missing from bundle")

        route_identities[sym] = {
            "symbol": sym,
            "route_type": route_type if route_type else "LEGACY",
            "model_sha256": model_sha,
            "calibrator_sha256": calib_sha,
            "feature_schema_version": route.get("feature_schema_version", "grandfathered"),
            "feature_schema": route.get("feature_schema", []),
            "qualification_verdict": route.get("qualification_verdict", "GRANDFATHERED"),
            "artifact_verified": artifact_ok,
        }

    gates["MC9-A-G6"] = gate(
        "MC9-A-G6",
        len(route_failures) == 0,
        f"failures: {route_failures}" if route_failures else "all 9 routes verified",
    )

    # ── G7: universe accounting ───────────────────────────────────────────────
    auth_count = len(AUTHORIZED_SYMBOLS)
    dis_count = len(DISABLED_SYMBOLS)
    gates["MC9-A-G7"] = gate(
        "MC9-A-G7",
        auth_count + dis_count == CANONICAL_UNIVERSE,
        f"{auth_count} + {dis_count} = {auth_count + dis_count} (expected {CANONICAL_UNIVERSE})",
    )

    # ── G8: release bundle and worktree not mutated ───────────────────────────
    import subprocess
    worktree_clean = True
    bundle_registry_sha = sha256_file(RELEASE_DIR / "model_coverage_mc6_inference_registry.json")
    try:
        wt_status = subprocess.check_output(
            ["git", "-C", str(WORKTREE_PATH), "status", "--short"], text=True
        ).strip()
        worktree_clean = wt_status == ""
    except Exception as exc:
        worktree_clean = False
        wt_status = str(exc)

    bundle_registry_ok = bundle_registry_sha == contract["mc6_registry_sha256"]
    gates["MC9-A-G8"] = gate(
        "MC9-A-G8",
        worktree_clean and bundle_registry_ok,
        f"worktree_clean={worktree_clean} bundle_registry_ok={bundle_registry_ok}",
    )

    # ── Build identity document ───────────────────────────────────────────────
    identity: dict[str, Any] = {
        "artifact": "model_coverage_mc9_release_identity",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),

        "release_id": EXPECTED_RELEASE_VERSION,
        "branch": "model-coverage/22-symbol-v1",

        "mc7_seal_commit": verdict["mc7_seal_commit"],
        "mc8_seal_commit": verdict["mc8_source_commit"],
        "source_commit": EXPECTED_SOURCE_COMMIT,

        "release_manifest": {
            "path": str(MC8_MANIFEST.relative_to(ROOT)),
            "sha256": manifest_sha,
        },
        "inference_registry": {
            "path": str(MC6_REGISTRY.relative_to(ROOT)),
            "sha256": registry_sha,
        },
        "runtime_binding_contract": {
            "path": str(MC7_BINDING.relative_to(ROOT)),
            "sha256": binding_sha,
        },
        "artifact_inventory": {
            "path": str(MC8_INVENTORY.relative_to(ROOT)),
            "sha256": sha256_file(MC8_INVENTORY),
        },
        "mc8_final_verdict": {
            "path": str(MC8_VERDICT.relative_to(ROOT)),
            "sha256": sha256_file(MC8_VERDICT),
        },

        "canonical_universe_count": CANONICAL_UNIVERSE,
        "effective_runtime_count": len(AUTHORIZED_SYMBOLS),
        "disabled_symbol_count": len(DISABLED_SYMBOLS),

        "authorized_symbols": AUTHORIZED_SYMBOLS,
        "disabled_symbols": DISABLED_SYMBOLS,

        "route_identities": route_identities,

        "gates": gates,
        "overall_verdict": "PASS",
    }

    # ── Write output ──────────────────────────────────────────────────────────
    OUTPUT.write_text(json.dumps(identity, indent=2))
    file_sha = sha256_file(OUTPUT)
    OUTPUT_SHA.write_text(file_sha)

    print()
    print(f"Written: {OUTPUT.name}")
    print(f"SHA256:  {file_sha}")
    print("MC9-A-VERDICT: PASS")


if __name__ == "__main__":
    main()
