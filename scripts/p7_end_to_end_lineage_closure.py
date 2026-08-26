#!/usr/bin/env python3
"""P7 end-to-end lineage closure contract.

This verifier is intentionally event-driven. It stays READY while O3-O6 are
waiting, and only emits PASS after one machine-linked causal chain exists.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "p7_end_to_end_lineage_closure.json"

REPORTS = {
    "O3": ROOT / "p7_first_actionable_decision_report.json",
    "O4": ROOT / "p7_first_execution_attempt_report.json",
    "O5": ROOT / "p7_first_fill_report.json",
    "O6": ROOT / "p7_first_outcome_report.json",
}
BASELINE = ROOT / "p7_postseal_observation_baseline.json"


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    d = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            d.update(block)
    return d.hexdigest()


def _sidecar_ok(path: Path) -> bool:
    sidecar = Path(str(path) + ".sha256")
    return path.exists() and sidecar.exists() and sidecar.read_text(encoding="utf-8").strip() == _sha256_file(path)


def _status(report: dict) -> str:
    return str(report.get("status") or "MISSING")


def main() -> int:
    baseline = _json(BASELINE)
    reports = {name: _json(path) for name, path in REPORTS.items()}
    statuses = {name: _status(report) for name, report in reports.items()}
    sidecars = {name: _sidecar_ok(path) for name, path in REPORTS.items()}

    blockers = []
    if baseline.get("overall_verdict") != "PASS":
        blockers.append("post-seal observation baseline is not PASS")
    for name, ok in sidecars.items():
        if not ok:
            blockers.append(f"{name} report sidecar missing or mismatched")
    for name, report in reports.items():
        if report.get("overall_verdict") not in ("PASS", None):
            blockers.append(f"{name} verifier is not PASS")

    waiting = [name for name, status in statuses.items() if status == "WAITING_FOR_NATURAL_EVENT"]
    complete = {
        "O3": statuses.get("O3") == "DECISION_LOGGED",
        "O4": statuses.get("O4") == "ORDER_ATTEMPTED",
        "O5": statuses.get("O5") == "ORDER_FILLED",
        "O6": statuses.get("O6") == "POSITION_CLOSED",
    }

    chain = {
        "prediction_id": reports["O3"].get("first_actionable_decision", {}).get("prediction_id"),
        "decision_id": reports["O3"].get("first_actionable_decision", {}).get("decision_id"),
        "execution_decision_id": reports["O4"].get("first_order", {}).get("decision_id"),
        "order_id": reports["O4"].get("first_order", {}).get("order_id"),
        "fill_order_id": reports["O5"].get("first_fill", {}).get("order_id"),
        "fill_id": reports["O5"].get("first_fill", {}).get("fill_id"),
        "position_fill_id": reports["O6"].get("first_position", {}).get("fill_id"),
        "position_id": reports["O6"].get("first_position", {}).get("position_id"),
    }

    same_chain = (
        complete == {"O3": True, "O4": True, "O5": True, "O6": True}
        and chain["decision_id"] is not None
        and chain["decision_id"] == chain["execution_decision_id"]
        and chain["order_id"] is not None
        and chain["order_id"] == chain["fill_order_id"]
        and chain["fill_id"] is not None
        and chain["fill_id"] == chain["position_fill_id"]
    )

    if not same_chain and not waiting:
        blockers.append("O3-O6 evidence does not form one machine-linked causal chain")

    if blockers:
        verdict = "FAIL"
    elif waiting:
        verdict = "READY"
    elif same_chain:
        verdict = "PASS"
    else:
        verdict = "FAIL"

    report = {
        "artifact": "p7_end_to_end_lineage_closure",
        "generated_at": _utc_now(),
        "observation_mode": "EVENT_DRIVEN",
        "runtime_change_policy": "FROZEN",
        "synthetic_trades": "NOT_AUTHORIZED",
        "status": "WAITING_FOR_NATURAL_EVENT" if waiting else "CHAIN_VERIFIED",
        "overall_verdict": verdict,
        "end_to_end_execution_lineage": "PASS" if same_chain else "WAITING_FOR_NATURAL_EVENT" if waiting else "FAIL",
        "same_causal_chain_required": True,
        "mixed_trade_evidence_rejected": True,
        "baseline_sha256": _sha256_file(BASELINE),
        "report_statuses": statuses,
        "report_sha256": {name: _sha256_file(path) for name, path in REPORTS.items()},
        "chain": chain,
        "waiting_for": waiting,
        "blockers": blockers,
    }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    Path(str(OUTPUT) + ".sha256").write_text(digest + "\n", encoding="utf-8")

    print(json.dumps({"status": report["overall_verdict"], "state": report["status"], "output": str(OUTPUT), "sha256": digest}, indent=2))
    return 0 if report["overall_verdict"] in ("PASS", "READY") else 1


if __name__ == "__main__":
    sys.exit(main())
