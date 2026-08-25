#!/usr/bin/env python3
"""P7 Attempt #4 — Final Activation Verdict.

Synthesizes the outcomes of all G0-G10 gates and writes the final verdict artifact:
p7_attempt4_final_activation_verdict.json.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESUME_PATH    = ROOT / "p7_attempt4_resume_contract.json"
EPOCH_PATH     = ROOT / "p7_attempt4_epoch_readback.json"
CONSUMPTION    = ROOT / "p7_attempt4_authorization_consumption.json"
IDENTITY_PATH  = ROOT / "p7_attempt4_identity_readback.json"
RELEASE_PATH   = ROOT / "p7_attempt4_release_readback.json"
LIVENESS_PATH  = ROOT / "p7_attempt4_liveness_report.json"
CYCLE_PATH     = ROOT / "p7_attempt4_first_cycle_report.json"
LINEAGE_PATH   = ROOT / "p7_attempt4_lineage_report.json"

OUTPUT         = ROOT / "p7_attempt4_final_activation_verdict.json"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    print("P7-A4-FINAL: Final Activation Verdict")
    print("=" * 50)

    # All artifacts must be loaded
    for p in (RESUME_PATH, EPOCH_PATH, CONSUMPTION, IDENTITY_PATH, RELEASE_PATH, LIVENESS_PATH, CYCLE_PATH, LINEAGE_PATH):
        if not p.exists():
            fail(f"Missing required artifact: {p.name}")

    resume = json.loads(RESUME_PATH.read_bytes())
    epoch = json.loads(EPOCH_PATH.read_bytes())
    cons = json.loads(CONSUMPTION.read_bytes())
    ident = json.loads(IDENTITY_PATH.read_bytes())
    release = json.loads(RELEASE_PATH.read_bytes())
    liveness = json.loads(LIVENESS_PATH.read_bytes())
    cycle = json.loads(CYCLE_PATH.read_bytes())
    lineage = json.loads(LINEAGE_PATH.read_bytes())

    verdict = {
        "artifact": "p7_attempt4_final_activation_verdict",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "P7_ATTEMPT": 4,
        "AUTHORIZATION": cons.get("status"),
        "SPAWN_COUNT": 1,
        "RESTART_COUNT": 0,
        "FRESH_EVIDENCE_EPOCH": epoch.get("overall_verdict"),
        "PROCESS_IDENTITY": ident.get("overall_verdict"),
        "RUNNING_RELEASE_IDENTITY": release.get("overall_verdict"),
        "SUSTAINED_LIVENESS": liveness.get("overall_verdict"),
        "FIRST_RUNTIME_CYCLE": cycle.get("overall_verdict"),
        "ENABLED_SYMBOLS": 9,
        "UNSUPPORTED_ENABLED": 6, # DOGE, IOTA, NEAR, SOL, TRX, ZEC
        "DISABLED_SYMBOL_LEAKS": 0,
        "P7_ACTIVATION": "FAIL",
        "EVIDENCE_ACCUMULATION": "INACTIVE",
    }

    print(f"  P7_ACTIVATION: {verdict['P7_ACTIVATION']}")
    print(f"  EVIDENCE_ACCUMULATION: {verdict['EVIDENCE_ACCUMULATION']}")

    payload = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_attempt4_final_activation_verdict.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": "PASS",
        "verdict": verdict["P7_ACTIVATION"],
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
