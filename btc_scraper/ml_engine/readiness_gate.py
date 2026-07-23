"""Fail-closed automated-live authorization gate for the ML engine."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .artifact_resolver import ROOT

READINESS_PATH = ROOT / "config" / "ml_engine_readiness.json"

FOUNDATION_GATES = (
    "implementation_gate",
    "offline_regression_gate",
    "decision_correctness_gate",
    "calibration_methodology_gate",
    "artifact_governance_gate",
    "runtime_evidence_gate",
)


def derive_readiness(
    readiness: dict[str, Any],
    *,
    shadow_validation_passed: bool | None = None,
) -> dict[str, Any]:
    """Return a normalized readiness document with a non-editable derived result."""
    gates = {name: readiness.get(name) is True for name in FOUNDATION_GATES}
    rl_required = readiness.get("rl_policy_required_for_live_entry") is True
    gates["rl_policy_gate"] = (
        readiness.get("rl_policy_gate") is True
        if rl_required
        else readiness.get("rl_policy_enabled") is not True
    )
    gates["shadow_validation_gate"] = (
        shadow_validation_passed
        if shadow_validation_passed is not None
        else readiness.get("shadow_validation_gate") is True
    )
    gates["manual_authorization_gate"] = readiness.get("manual_authorization_gate") is True
    live_ready = all(gates.values())
    result = dict(readiness)
    result.update(gates)
    result["live_ready"] = live_ready
    result["automated_live_entry"] = live_ready
    result["status"] = "AUTHORIZED" if live_ready else "BLOCKED"
    if not live_ready:
        result["failed_gates"] = [name for name, passed in gates.items() if not passed]
    else:
        result["failed_gates"] = []
    return result


def live_entry_authorized(path: Path | str = READINESS_PATH) -> tuple[bool, str]:
    try:
        readiness = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"readiness_config_unavailable:{type(exc).__name__}"
    try:
        from .shadow_validation import cached_shadow_validation
        shadow_evidence = cached_shadow_validation()
        shadow_passed = shadow_evidence["passed"] is True
    except Exception:
        shadow_passed = False
    readiness = derive_readiness(readiness, shadow_validation_passed=shadow_passed)
    if not readiness["live_ready"]:
        failed = ",".join(readiness["failed_gates"])
        return False, f"ml_engine_readiness_blocked:{failed}"
    if os.getenv("ML_ENGINE_LIVE_AUTHORIZED", "false").lower() not in {"1", "true", "yes"}:
        return False, "manual_live_reauthorization_missing"
    return True, "authorized"
