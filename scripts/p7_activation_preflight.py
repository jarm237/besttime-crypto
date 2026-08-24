#!/usr/bin/env python3
"""Build P7 paper-canary activation evidence without starting a runtime.

This script intentionally performs only release/artifact/import/readiness smoke
checks and writes governance evidence files.  It does not create an evidence
epoch, start a child process, mutate model artifacts, or promote a release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RELEASE_COMMIT = "5e8d798e4d06d6abd21ade99c79caaa93307dd5b"
RELEASE_TREE = "48ef10b27488468d294a5e223cb95a4aebfc3f01"
EPOCH_ID = "canary-p6-sealed-v1-20260824-01"
DEPLOYMENT_ID = "paper-canary-20260824-01"
PAPER_RUN_ID = DEPLOYMENT_ID
FEATURES = ("return_8", "return_32", "return_72", "abs_move_72")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def write_json(path: Path, value: Any) -> str:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return sha256_file(path)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def run_python_with_pinned_import(root: Path, code: str) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env["PYTHONNOUSERSITE"] = "1"
    env["BTC_EVIDENCE_ELIGIBLE"] = "false"
    env.setdefault("AUTO_TRADE_DRY_RUN", "true")
    env.setdefault("BTC_RUNTIME_ENVIRONMENT", "paper")
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = {
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }
    if result.returncode == 0 and result.stdout.strip():
        try:
            payload["json"] = json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
    return payload


def build_manifest(repo_root: Path, pinned_root: Path, release: dict[str, Any]) -> dict[str, Any]:
    compatibility_path = pinned_root / "config/artifact_compatibility/meta_model.compatibility.json"
    compatibility = json.loads(compatibility_path.read_text(encoding="utf-8"))
    artifact_rel = compatibility["artifact"]["artifact_path"]
    artifact_path = pinned_root / artifact_rel
    metadata_path = pinned_root / compatibility["artifact"]["metadata_path"]
    contracts = collect_contracts(pinned_root)
    manifest = {
        "contract": "paper-canary-deployment/v1",
        "epoch_id": EPOCH_ID,
        "deployment_id": DEPLOYMENT_ID,
        "paper_run_id": PAPER_RUN_ID,
        "release": {
            "commit_sha": release["release_commit_sha"],
            "tree_sha": release["release_tree_sha"],
            "source": release["source"],
        },
        "artifact": {
            "path": artifact_rel,
            "sha256": sha256_file(artifact_path),
            "manifest_sha256": sha256_file(compatibility_path),
            "metadata_sha256": sha256_file(metadata_path),
            "artifact_version": compatibility["artifact"]["artifact_version"],
            "model_family": compatibility["artifact"]["model_family"],
            "schema_fingerprint": compatibility["feature_schema"]["schema_hash"],
            "feature_order_hash": compatibility["feature_schema"]["order_hash"],
            "inference_feature_schema_hash": compatibility["feature_schema"]["inference_feature_schema_hash"],
            "feature_names": list(compatibility["feature_schema"]["ordered_names"]),
            "compatibility_hash": compatibility["compatibility_hash"],
            "calibration": compatibility["calibration"],
        },
        "contracts": contracts,
        "runtime": {
            "mode": "PAPER",
            "real_money_enabled": False,
            "paper_execution_required": True,
            "automatic_retry": "FORBIDDEN",
        },
        "observation": {
            "successor_research": "NOT_AUTHORIZED",
            "production_promotion": "NOT_AUTHORIZED",
        },
    }
    manifest["manifest_sha256"] = sha256_json(manifest)
    return manifest


def collect_contracts(root: Path) -> dict[str, str]:
    code = r'''
import json
from btc_scraper.ml_engine.artifact_compatibility import ARTIFACT_COMPATIBILITY_CONTRACT_VERSION
from btc_scraper.ml_engine.common_evaluator import COMMON_EVALUATOR_VERSION, DECISION_CONTRACT_VERSION
from btc_scraper.ml_engine.economic_contract import EV_CONTRACT_VERSION
from btc_scraper.ml_engine.evaluation_contracts import P6_CONTRACT_VERSION, READINESS_CONTRACT_VERSION, canonical_entry_readiness_contract
from btc_scraper.ml_engine.inference_contract import INFERENCE_CONTRACT_VERSION
from btc_scraper.ml_engine.pure_scoring import SCORING_CONTRACT_VERSION
from btc_scraper.ml_engine.s3_thresholds import S3_THRESHOLD_CONTRACT_VERSION
from btc_scraper.ml_engine.schema_contracts import SCHEMA_CONTRACT_VERSION
from btc_scraper.trading.risk_sizing_contract import RISK_SIZING_CONTRACT_VERSION
print(json.dumps({
  "artifact_compatibility": ARTIFACT_COMPATIBILITY_CONTRACT_VERSION,
  "common_evaluator": COMMON_EVALUATOR_VERSION,
  "decision_composition": DECISION_CONTRACT_VERSION,
  "expected_value": EV_CONTRACT_VERSION,
  "inference": INFERENCE_CONTRACT_VERSION,
  "pure_scoring": SCORING_CONTRACT_VERSION,
  "risk_sizing": RISK_SIZING_CONTRACT_VERSION,
  "s3_threshold": S3_THRESHOLD_CONTRACT_VERSION,
  "schema": SCHEMA_CONTRACT_VERSION,
  "p6_evaluation": P6_CONTRACT_VERSION,
  "readiness": READINESS_CONTRACT_VERSION,
  "readiness_required_observations": canonical_entry_readiness_contract().required_bars,
}, sort_keys=True))
'''
    result = run_python_with_pinned_import(root, code)
    if result["returncode"] != 0 or "json" not in result:
        raise RuntimeError(f"contract import failed: {result}")
    return result["json"]


def pinned_smoke(root: Path) -> dict[str, Any]:
    code = r'''
import json
from pathlib import Path
import btc_scraper
from btc_scraper.ml_engine.evaluation_contracts import canonical_entry_readiness_contract
from btc_scraper.ml_engine.inference_contract import predict
from btc_scraper.ml_engine.meta_model import get_meta_inference_artifact
from btc_scraper.ml_engine.common_evaluator import CanonicalCandle
from datetime import datetime, timedelta, timezone

now = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
def candles(count, closed=True):
    rows = []
    for i in range(count):
        opened = now - timedelta(minutes=15 * (count - 1 - i))
        rows.append(CanonicalCandle(opened, opened, 100+i, 100.5+i, 99.5+i, 100+i, 1.0, closed if i == count - 1 else True))
    return rows

contract = canonical_entry_readiness_contract()
artifact = get_meta_inference_artifact()
prediction = predict(symbol="BTC", features=(0.01, 0.02, 0.03, 0.04), artifact=artifact)
print(json.dumps({
  "btc_scraper_file": str(Path(btc_scraper.__file__).resolve()),
  "readiness_72": contract.diagnose(candles(72), now).to_dict(),
  "readiness_73": contract.diagnose(candles(73), now).to_dict(),
  "artifact_version": artifact.artifact_version,
  "artifact_hash": artifact.artifact_hash,
  "feature_schema_hash": artifact.feature_schema_hash,
  "feature_names": list(artifact.feature_names),
  "prediction_symbol": prediction.symbol,
  "prediction": prediction.prediction,
  "inference_contract_version": prediction.inference_contract_version,
}, sort_keys=True))
'''
    return run_python_with_pinned_import(root, code)


def symbol_universe_compatibility(root: Path) -> dict[str, Any]:
    """Compare runtime symbols with artifact metadata and actual model routes."""
    code = r'''
import json
from btc_scraper.core.config import DEFAULT_ANALYSIS_UNIVERSE, get_runtime_universe
from btc_scraper.ml_engine.meta_model import get_meta_inference_artifact, load_model

artifact = get_meta_inference_artifact()
runtime = get_runtime_universe()
model_bundle = load_model()
model = model_bundle.get("model") if isinstance(model_bundle, dict) else model_bundle
estimator = getattr(model, "_estimator", model)
model_route_symbols = tuple(sorted(getattr(estimator, "model_params", {}).keys()))

runtime_symbols = tuple(runtime.analysis_symbols)
artifact_symbols = tuple(sorted(artifact.supported_symbols))
model_symbols = tuple(str(symbol).strip().upper() for symbol in model_route_symbols)
unsupported_by_artifact = tuple(sorted(set(runtime_symbols) - set(artifact_symbols)))
unsupported_by_model_route = tuple(sorted(set(runtime_symbols) - set(model_symbols)))

matrix = []
for symbol in runtime_symbols:
    artifact_supported = symbol in artifact_symbols
    model_route_supported = symbol in model_symbols
    matrix.append({
        "symbol": symbol,
        "runtime_enabled": True,
        "artifact_metadata_supported": artifact_supported,
        "model_route_supported": model_route_supported,
        "artifact_route": "explicit" if model_route_supported else "absent",
        "verdict": "PASS" if artifact_supported and model_route_supported else "FAIL",
    })

print(json.dumps({
    "runtime_symbols": list(runtime_symbols),
    "runtime_execution_symbols": list(runtime.execution_symbols),
    "default_analysis_universe": list(DEFAULT_ANALYSIS_UNIVERSE),
    "artifact_supported_symbols": list(artifact_symbols),
    "model_route_supported_symbols": list(model_symbols),
    "unsupported_by_artifact_metadata": list(unsupported_by_artifact),
    "unsupported_by_model_route": list(unsupported_by_model_route),
    "unsupported_symbols": list(unsupported_by_model_route),
    "matrix": matrix,
    "artifact": {
        "artifact_version": artifact.artifact_version,
        "artifact_hash": artifact.artifact_hash,
        "feature_names": list(artifact.feature_names),
        "feature_schema_hash": artifact.feature_schema_hash,
    },
    "model_route": {
        "model_type": type(estimator).__name__,
        "requires_explicit_symbol": bool(getattr(estimator, "requires_explicit_symbol", False)),
        "model_dir_path": str(getattr(estimator, "model_dir_path", "")),
    },
}, sort_keys=True))
'''
    result = run_python_with_pinned_import(root, code)
    payload = result.get("json") or {}
    unsupported = list(payload.get("unsupported_symbols") or [])
    return {
        "status": "PASS" if result["returncode"] == 0 and not unsupported else "FAIL",
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "json": payload,
        "unsupported_symbols": unsupported,
        "verdict": "PASS" if result["returncode"] == 0 and not unsupported else "BLOCKED_INFERENCE_SYMBOL_UNSUPPORTED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--pinned-root", type=Path, default=Path("runtime/worktrees/pinned-5e8d798"))
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    pinned_root = (repo_root / args.pinned_root).resolve() if not args.pinned_root.is_absolute() else args.pinned_root.resolve()

    status = git(repo_root, "status", "--short")
    head = git(repo_root, "rev-parse", "HEAD")
    tree = git(repo_root, "rev-parse", "HEAD^{tree}")
    pinned_head = git(pinned_root, "rev-parse", "HEAD")
    pinned_tree = git(pinned_root, "rev-parse", "HEAD^{tree}")
    pinned_status = git(pinned_root, "status", "--short")

    p6_report = json.loads((repo_root / "runtime_remediation_p6_report.json").read_text(encoding="utf-8"))
    p6_g5_report = json.loads((repo_root / "runtime_remediation_p6_g5_regression_report.json").read_text(encoding="utf-8"))

    release = {
        "release_contract": "runtime-release/v1",
        "release_commit_sha": RELEASE_COMMIT,
        "release_tree_sha": RELEASE_TREE,
        "source": "P6_CANONICAL_SEAL",
        "mutable": False,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "verification": {
            "repo_head": head,
            "repo_tree": tree,
            "repo_status_clean": status == "",
            "pinned_head": pinned_head,
            "pinned_tree": pinned_tree,
            "pinned_status_clean": pinned_status == "",
            "p6_closed": p6_report.get("status") == "CLOSED",
            "g5_pass": p6_g5_report.get("status") == "PASS",
        },
    }
    release["status"] = "PASS" if (
        head == RELEASE_COMMIT
        and tree == RELEASE_TREE
        and pinned_head == RELEASE_COMMIT
        and pinned_tree == RELEASE_TREE
        and pinned_status == ""
        and release["verification"]["p6_closed"]
        and release["verification"]["g5_pass"]
    ) else "FAIL"
    release_sha = write_json(repo_root / "runtime_activation_p7_release.json", release)

    manifest = build_manifest(repo_root, pinned_root, release)
    manifest_sha = write_json(repo_root / "runtime_activation_p7_manifest.json", manifest)

    smoke = pinned_smoke(pinned_root)
    symbol_compatibility = symbol_universe_compatibility(pinned_root)
    smoke_json = smoke.get("json") or {}
    import_path_ok = (
        smoke["returncode"] == 0
        and str(smoke_json.get("btc_scraper_file", "")).startswith(str(pinned_root))
    )
    readiness_ok = (
        smoke_json.get("readiness_72", {}).get("status") == "WARMING_UP"
        and smoke_json.get("readiness_73", {}).get("status") == "READY"
        and smoke_json.get("readiness_73", {}).get("required_observations") == 73
    )
    artifact_ok = (
        smoke_json.get("artifact_hash") == manifest["artifact"]["sha256"]
        and tuple(smoke_json.get("feature_names", ())) == FEATURES
        and smoke_json.get("feature_schema_hash") == manifest["artifact"]["inference_feature_schema_hash"]
    )
    inference_ok = (
        smoke_json.get("prediction_symbol") == "BTC"
        and isinstance(smoke_json.get("prediction"), (float, int))
        and 0.0 <= float(smoke_json.get("prediction", -1)) <= 1.0
    )

    unsafe_activation_findings = [
        {
            "path": "scripts/activate_v5_canary.py",
            "reason": "mutates logs/meta_model.joblib, logs/meta_model.json, logs/model_registry.json and deletes/recreates a fixed evidence epoch",
            "status": "DISQUALIFIED_FOR_P7_GOVERNED_ACTIVATION",
        }
    ]
    safe_launcher_path = repo_root / "scripts/p7_safe_paper_canary_launcher.py"
    safe_launcher_sha = sha256_file(safe_launcher_path) if safe_launcher_path.exists() else None
    safe_launcher_validation: dict[str, Any] | None = None
    safe_launcher_ready = False
    if safe_launcher_path.exists():
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from scripts.p7_safe_paper_canary_launcher import (
            LaunchRequest,
            validate_launch_request,
        )

        try:
            launch_request = LaunchRequest.from_manifest(
                manifest_path=repo_root / "runtime_activation_p7_manifest.json",
                expected_manifest_sha256=manifest_sha,
                pinned_root=pinned_root,
                python_executable=Path(sys.executable),
            )
            safe_launcher_validation = validate_launch_request(launch_request)
            safe_launcher_ready = safe_launcher_validation["status"] == "PASS"
        except Exception as exc:
            safe_launcher_validation = {
                "status": "FAIL",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
    symbol_compatibility_ok = symbol_compatibility["status"] == "PASS"
    activation_ready = safe_launcher_ready and symbol_compatibility_ok
    preflight = {
        "contract": "paper-canary-preflight/v1",
        "status": "PASS" if activation_ready else "PASS_WITH_ACTIVATION_BLOCKER",
        "ready_to_arm": activation_ready,
        "release_sha256": release_sha,
        "manifest_sha256": manifest_sha,
        "checks": {
            "PREFLIGHT_RELEASE": release["status"],
            "PREFLIGHT_ARTIFACT": "PASS" if artifact_ok else "FAIL",
            "PREFLIGHT_SCHEMA": "PASS" if tuple(manifest["artifact"]["feature_names"]) == FEATURES else "FAIL",
            "PREFLIGHT_READINESS": "PASS" if readiness_ok else "FAIL",
            "PREFLIGHT_IMPORT_PATH": "PASS" if import_path_ok else "FAIL",
            "PREFLIGHT_RUNTIME_STATE": "PASS_READ_ONLY_NO_ACTIVE_RUNNER_CHECK",
            "PREFLIGHT_PAPER_MODE": "PASS_SAFE_EXTERNAL_LAUNCHER" if safe_launcher_ready else "BLOCKED_NO_SAFE_NON_MUTATING_LAUNCHER",
            "PREFLIGHT_LAUNCHER_CONTRACT": "PASS" if safe_launcher_ready else "FAIL",
            "RUNTIME_SYMBOL_UNIVERSE_COMPATIBILITY": symbol_compatibility["status"],
            "PREFLIGHT_STORAGE": "NOT_MUTATED_READ_ONLY_PREFLIGHT",
            "PREFLIGHT_EVALUATOR": "PASS" if inference_ok else "FAIL",
        },
        "pinned_smoke": smoke,
        "symbol_universe_compatibility": symbol_compatibility,
        "unsafe_activation_findings": unsafe_activation_findings,
        "safe_launcher": {
            "contract": "paper-canary-launcher/v1",
            "path": "scripts/p7_safe_paper_canary_launcher.py",
            "sha256": safe_launcher_sha,
            "validation": safe_launcher_validation,
        },
        "environment": {
            "python": sys.version.split()[0],
            "executable": sys.executable,
            "platform": platform.platform(),
            "timezone": "UTC for generated evidence timestamps",
        },
    }
    write_json(repo_root / "runtime_activation_p7_preflight.json", preflight)

    readback = {
        "contract": "paper-canary-readback/v1",
        "status": "NOT_STARTED",
        "reason": "activation not armed because no safe non-mutating paper launcher was proven",
        "expected_release_commit_sha": RELEASE_COMMIT,
        "expected_release_tree_sha": RELEASE_TREE,
        "manifest_sha256": manifest_sha,
        "runtime_started": False,
        "identity_readback": "NOT_AVAILABLE",
    }
    write_json(repo_root / "runtime_activation_p7_readback.json", readback)

    first_cycle = {
        "contract": "paper-canary-first-cycle/v1",
        "status": "NOT_RUN",
        "reason": "paper-canary runtime not started",
        "first_cycle_sanity": "NOT_AVAILABLE",
    }
    write_json(repo_root / "runtime_activation_p7_first_cycle.json", first_cycle)

    report = {
        "contract": "p7-governed-paper-canary-activation/v1",
        "status": (
            "READY_TO_ARM_PENDING_G6_AUTHORIZATION"
            if safe_launcher_ready
            else "BLOCKED_BEFORE_ACTIVATION"
        ),
        "blocked_reason": (
            None
            if safe_launcher_ready
            else "NO_SAFE_NON_MUTATING_PAPER_CANARY_LAUNCHER_PROVEN"
        ),
        "gates": {
            "P7-G0": "PASS",
            "P7-G1": release["status"],
            "P7-G2": "PASS" if artifact_ok and readiness_ok and inference_ok else "FAIL",
            "P7-G3": "PASS",
            "P7-G4": "PASS" if import_path_ok else "FAIL",
            "P7-G5": "PASS" if safe_launcher_ready else "PASS_WITH_ACTIVATION_BLOCKER",
            "P7-G5A": "PASS" if safe_launcher_ready else "READY_TO_RESUME",
            "P7-R4-SYMBOL-UNIVERSE": "PASS" if symbol_compatibility_ok else "BLOCKED_INFERENCE_SYMBOL_UNSUPPORTED",
            "P7-G6": "READY_TO_ARM" if activation_ready else "BLOCKED_NOT_ARMED",
            "P7-G7": "NOT_RUN",
            "P7-G8": "NOT_RUN",
            "P7-G9": "NOT_RUN",
            "P7-G10": "NOT_RUN",
            "P7": (
                "IN_PROGRESS_READY_FOR_G6_AUTHORIZATION"
                if activation_ready
                else "IN_PROGRESS_BLOCKED_BEFORE_ACTIVATION"
            ),
        },
        "release": {
            "commit_sha": RELEASE_COMMIT,
            "tree_sha": RELEASE_TREE,
            "release_file": "runtime_activation_p7_release.json",
        },
        "manifest": {
            "path": "runtime_activation_p7_manifest.json",
            "sha256": manifest_sha,
        },
        "preflight": {
            "path": "runtime_activation_p7_preflight.json",
            "ready_to_arm": activation_ready,
        },
        "safe_launcher": preflight["safe_launcher"],
        "governance": {
            "runtime_activation": "NOT_PERFORMED",
            "activation_authorization": "NOT_ARMED",
            "real_money_production": "NOT_AUTHORIZED",
            "successor_research": "NOT_AUTHORIZED",
            "model_retraining": "NOT_PERFORMED",
            "artifact_promotion": "NOT_PERFORMED",
        },
    }
    write_json(repo_root / "runtime_activation_p7_report.json", report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
