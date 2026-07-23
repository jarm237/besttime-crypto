"""Fail-closed automated-live authorization gate for the ML engine."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .artifact_resolver import ROOT

READINESS_PATH = ROOT / "config" / "ml_engine_readiness.json"


def live_entry_authorized(path: Path | str = READINESS_PATH) -> tuple[bool, str]:
    try:
        readiness = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"readiness_config_unavailable:{type(exc).__name__}"
    if readiness.get("status") != "AUTHORIZED" or readiness.get("automated_live_entry") is not True:
        return False, str(readiness.get("reason") or "ml_engine_readiness_blocked")
    if os.getenv("ML_ENGINE_LIVE_AUTHORIZED", "false").lower() not in {"1", "true", "yes"}:
        return False, "manual_live_reauthorization_missing"
    return True, "authorized"
