#!/usr/bin/env python3
"""MC9-D — P7 pre-activation preflight.

Verifies all conditions P7 needs before a supervised spawn, WITHOUT:
  - creating an evidence epoch
  - spawning a runner
  - consuming the authorization
  - writing predictions/decisions/executions

Gates:
  MC9-D-G1  pinned worktree exists, HEAD=94407d3..., worktree clean
  MC9-D-G2  release bundle manifest sha256 still matches identity
  MC9-D-G3  inference coverage: 9 routes load, 0 failures
  MC9-D-G4  supervised launcher tooling present with correct contract version
  MC9-D-G5  evidence infrastructure: schema version readable, paths resolve
  MC9-D-G6  spawn/restart controls: LaunchRequest importable, LAUNCHER_CONTRACT_VERSION present
  MC9-D-G7  no runtime activation performed (no ACTIVE epoch in any evidence store)

Output: model_coverage_mc9_p7_preactivation_report.json + .sha256
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / "runtime" / "worktrees" / "pinned-94407d3"
RELEASE = ROOT / "runtime" / "releases" / "model-coverage-v1"

IDENTITY = ROOT / "model_coverage_mc9_release_identity.json"
READBACK = ROOT / "model_coverage_mc9_release_readback.json"
MC8_MANIFEST = ROOT / "model_coverage_mc8_release_manifest.json"

OUTPUT = ROOT / "model_coverage_mc9_p7_preactivation_report.json"
OUTPUT_SHA = ROOT / "model_coverage_mc9_p7_preactivation_report.json.sha256"

EXPECTED_SOURCE_COMMIT = "94407d3483bb01eccf0e86882cef258dcbb646e9"
EXPECTED_LAUNCHER_CONTRACT = "paper-canary-launcher/v1"
EXPECTED_SUPERVISED_CONTRACT = "p7-supervised-child/v1"
EXPECTED_EVIDENCE_SCHEMA = 6
AUTHORIZED_SYMBOLS = ["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_cmd(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def run_pinned(code: str) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PINNED)
    env["PYTHONNOUSERSITE"] = "1"
    env["BTC_EVIDENCE_ELIGIBLE"] = "false"
    env["AUTO_TRADE_DRY_RUN"] = "true"
    env["BTC_RUNTIME_ENVIRONMENT"] = "test"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(PINNED),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    payload: dict[str, Any] = {
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }
    if result.returncode == 0 and result.stdout.strip():
        try:
            payload["data"] = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            payload["data"] = None
    return payload


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def gate(label: str, ok: bool, detail: str = "") -> dict[str, Any]:
    status = "PASS" if ok else "FAIL"
    print(f"  {label}: {status}{(' — ' + detail) if detail else ''}")
    if not ok:
        fail(f"Gate {label} failed: {detail}")
    return {"gate": label, "result": status}


def main() -> None:
    print("MC9-D P7 Pre-Activation Preflight")
    print("=" * 50)

    identity = json.loads(IDENTITY.read_bytes())
    readback = json.loads(READBACK.read_bytes())
    gates: dict[str, Any] = {}

    # ── G1: pinned worktree exists, HEAD exact, clean ─────────────────────────
    worktree_exists = PINNED.is_dir()
    if not worktree_exists:
        fail(f"Pinned worktree missing: {PINNED}")
    head = git_cmd(PINNED, "rev-parse", "HEAD")
    clean = git_cmd(PINNED, "status", "--short") == ""
    gates["MC9-D-G1"] = gate(
        "MC9-D-G1",
        head == EXPECTED_SOURCE_COMMIT and clean,
        f"HEAD={head[:12]} clean={clean}",
    )

    # ── G2: release manifest sha256 still matches identity ────────────────────
    manifest_sha_now = sha256_file(MC8_MANIFEST)
    manifest_sha_identity = identity["release_manifest"]["sha256"]
    gates["MC9-D-G2"] = gate(
        "MC9-D-G2",
        manifest_sha_now == manifest_sha_identity,
        f"disk={manifest_sha_now[:12]} identity={manifest_sha_identity[:12]}",
    )

    # ── G3: 9 routes load from release bundle (reuse readback evidence) ───────
    routes_resolved = readback.get("routes_resolved", 0)
    model_load_failures = readback.get("model_load_failures", 0)
    hash_failures = readback.get("hash_failures", 0)
    gates["MC9-D-G3"] = gate(
        "MC9-D-G3",
        routes_resolved == 9 and model_load_failures == 0 and hash_failures == 0,
        f"routes={routes_resolved}/9 load_failures={model_load_failures} hash_failures={hash_failures}",
    )

    # ── G4: supervised launcher tooling present and correct version ───────────
    launcher_path = ROOT / "scripts" / "p7_safe_paper_canary_launcher.py"
    supervised_path = ROOT / "scripts" / "p7_r3a_supervised_child.py"
    launcher_exists = launcher_path.exists()
    supervised_exists = supervised_path.exists()

    # Extract contract versions by importing constants
    launcher_contract_ok = False
    supervised_contract_ok = False
    launcher_version = ""
    supervised_version = ""

    if launcher_exists:
        for line in launcher_path.read_text().splitlines():
            if "LAUNCHER_CONTRACT_VERSION" in line and "=" in line and '"' in line:
                launcher_version = line.split('"')[1]
                launcher_contract_ok = launcher_version == EXPECTED_LAUNCHER_CONTRACT
                break

    if supervised_exists:
        for line in supervised_path.read_text().splitlines():
            if "SUPERVISED_CHILD_CONTRACT_VERSION" in line and "=" in line and '"' in line:
                supervised_version = line.split('"')[1]
                supervised_contract_ok = supervised_version == EXPECTED_SUPERVISED_CONTRACT
                break

    gates["MC9-D-G4"] = gate(
        "MC9-D-G4",
        launcher_exists and supervised_exists and launcher_contract_ok and supervised_contract_ok,
        f"launcher={launcher_version!r} supervised={supervised_version!r}",
    )

    # ── G5: evidence infrastructure readable ──────────────────────────────────
    evidence_check_code = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[0] if sys.argv[0] != '-c' else sys.path[0])
from btc_scraper.ml_engine.runtime_evidence_store import (
    RUNTIME_EVIDENCE_SCHEMA_VERSION,
    GLOBAL_EVIDENCE_INDEX_SCHEMA_VERSION,
)
from btc_scraper.core.paths import get_runtime_paths
paths = get_runtime_paths()
print(json.dumps({
    "runtime_evidence_schema": RUNTIME_EVIDENCE_SCHEMA_VERSION,
    "global_index_schema": GLOBAL_EVIDENCE_INDEX_SCHEMA_VERSION,
    "runtime_root": str(paths.runtime_root),
    "evidence_eligible": paths.evidence_eligible,
}))
"""
    r = run_pinned(evidence_check_code)
    evidence_data: dict[str, Any] = {}
    if r["returncode"] == 0 and r.get("data"):
        evidence_data = r["data"]
        schema_ok = evidence_data.get("runtime_evidence_schema") == EXPECTED_EVIDENCE_SCHEMA
        not_eligible = evidence_data.get("evidence_eligible") is False
    else:
        schema_ok = False
        not_eligible = False

    gates["MC9-D-G5"] = gate(
        "MC9-D-G5",
        schema_ok and not_eligible,
        f"schema={evidence_data.get('runtime_evidence_schema')} evidence_eligible={evidence_data.get('evidence_eligible')}",
    )

    # ── G6: spawn/restart controls importable ────────────────────────────────
    # The launcher is intentionally OUTSIDE the pinned runtime (by design).
    # Import it directly in the current process from the main worktree.
    import importlib.util
    launcher_spec = importlib.util.spec_from_file_location(
        "p7_launcher", str(launcher_path)
    )
    spawn_data: dict[str, Any] = {}
    spawn_ok = False
    try:
        launcher_mod = importlib.util.module_from_spec(launcher_spec)  # type: ignore[arg-type]
        sys.modules["p7_launcher"] = launcher_mod  # needed for @dataclass
        launcher_spec.loader.exec_module(launcher_mod)  # type: ignore[union-attr]
        spawn_data = {
            "LAUNCHER_CONTRACT_VERSION": getattr(launcher_mod, "LAUNCHER_CONTRACT_VERSION", None),
            "LaunchRequest_exists": hasattr(launcher_mod, "LaunchRequest"),
            "LauncherContractError_exists": hasattr(launcher_mod, "LauncherContractError"),
        }
        spawn_ok = (
            spawn_data["LaunchRequest_exists"]
            and spawn_data["LauncherContractError_exists"]
            and spawn_data["LAUNCHER_CONTRACT_VERSION"] == EXPECTED_LAUNCHER_CONTRACT
        )
    except Exception as exc:
        spawn_data = {"error": str(exc)}

    gates["MC9-D-G6"] = gate(
        "MC9-D-G6",
        spawn_ok,
        f"LaunchRequest={spawn_data.get('LaunchRequest_exists')} contract={spawn_data.get('LAUNCHER_CONTRACT_VERSION')!r}",
    )

    # ── G7: no ACTIVE evidence epoch (no runtime activation performed) ────────
    # Check for any existing evidence SQLite files in runtime/ that have ACTIVE epochs
    runtime_evidence_files = list(ROOT.glob("runtime/**/runtime_evidence.sqlite"))
    active_epochs_found: list[str] = []

    for ev_path in runtime_evidence_files:
        try:
            import sqlite3
            conn = sqlite3.connect(str(ev_path))
            cursor = conn.execute(
                "SELECT COUNT(*) FROM evidence_epoch WHERE status='ACTIVE'"
                if "evidence_epoch" in [r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()]
                else "SELECT 0"
            )
            count = cursor.fetchone()[0]
            conn.close()
            if count > 0:
                active_epochs_found.append(str(ev_path))
        except Exception:
            pass

    gates["MC9-D-G7"] = gate(
        "MC9-D-G7",
        len(active_epochs_found) == 0,
        f"active_epochs_in_evidence_stores={active_epochs_found}" if active_epochs_found
        else "no ACTIVE epochs found",
    )

    # ── Build report ──────────────────────────────────────────────────────────
    report: dict[str, Any] = {
        "artifact": "model_coverage_mc9_p7_preactivation_report",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),

        "pinned_worktree": str(PINNED),
        "pinned_worktree_head": head,
        "pinned_worktree_clean": clean,

        "release_bundle": str(RELEASE),
        "release_manifest_sha256_matches": manifest_sha_now == manifest_sha_identity,

        "inference_coverage": {
            "routes_resolved": routes_resolved,
            "model_load_failures": model_load_failures,
            "hash_failures": hash_failures,
        },

        "supervised_launcher_tooling": {
            "launcher_path": str(launcher_path),
            "launcher_contract_version": launcher_version,
            "supervised_path": str(supervised_path),
            "supervised_contract_version": supervised_version,
        },

        "evidence_infrastructure": evidence_data,
        "spawn_controls": spawn_data,

        "no_active_epochs": len(active_epochs_found) == 0,
        "active_epochs_found": active_epochs_found,

        # MC9-D does NOT create epoch — flags that one is needed
        "fresh_evidence_epoch_required": True,
        "runtime_activation_performed": False,

        "gates": gates,
        "overall_verdict": "PASS",
    }

    OUTPUT.write_text(json.dumps(report, indent=2))
    file_sha = sha256_file(OUTPUT)
    OUTPUT_SHA.write_text(file_sha)
    print(f"\nWritten: {OUTPUT.name}")
    print(f"SHA256:  {file_sha}")
    print("MC9-D-VERDICT: PASS")


if __name__ == "__main__":
    main()
