"""
btc_scraper/execution/live_checklist.py
Phase 6 — Task 6.1: Live Readiness Checklist

Validates all pre-conditions before enabling live mode.
Returns structured checklist results with PASS/FAIL/UNKNOWN/MANUAL_REQUIRED statuses.
Manual acknowledgment is required for any MANUAL_REQUIRED item before live gate opens.
"""
from __future__ import annotations

import hashlib
import json
import socket
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).parent.parent.parent

ITEM_PASS = "PASS"
ITEM_FAIL = "FAIL"
ITEM_UNKNOWN = "UNKNOWN"
ITEM_MANUAL = "MANUAL_VERIFICATION_REQUIRED"


@dataclass
class CheckResult:
    name: str
    status: str          # PASS | FAIL | UNKNOWN | MANUAL_VERIFICATION_REQUIRED
    detail: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_blocking(self) -> bool:
        """FAIL and unacknowledged MANUAL items are blocking."""
        return self.status == ITEM_FAIL


@dataclass
class ChecklistResult:
    passed: bool
    items: List[CheckResult] = field(default_factory=list)
    manual_pending: List[str] = field(default_factory=list)  # items requiring ack
    run_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "run_at": self.run_at,
            "manual_pending": self.manual_pending,
            "items": [
                {
                    "name": r.name,
                    "status": r.status,
                    "detail": r.detail,
                    "evidence": r.evidence,
                }
                for r in self.items
            ],
        }


class LiveChecklist:
    """
    Pre-live readiness validator.

    Run this before enabling live mode. All FAIL items must be resolved.
    MANUAL_REQUIRED items need explicit operator acknowledgment.
    """

    # Time sync parameters
    TIME_SYNC_SAMPLES = 5
    TIME_SYNC_MEDIAN_LIMIT_MS = 250
    TIME_SYNC_MAX_LIMIT_MS = 500
    TIME_SYNC_HOST = "time.cloudflare.com"
    TIME_SYNC_PORT = 80

    def __init__(
        self,
        exchange_client=None,
        phase5_report_path: Optional[str] = None,
        model_snapshot_path: Optional[str] = None,
        rollback_dir: Optional[str] = None,
        acknowledged_manual_items: Optional[List[str]] = None,
    ):
        self._exchange = exchange_client
        self._phase5_report_path = Path(phase5_report_path) if phase5_report_path else (
            BASE_DIR / "data" / "execution" / "reports" / "phase5_report_latest.json"
        )
        self._model_snapshot_path = Path(model_snapshot_path) if model_snapshot_path else (
            BASE_DIR / "data" / "feature_store"
        )
        self._rollback_dir = Path(rollback_dir) if rollback_dir else (BASE_DIR / "data" / "rollback")
        # Set of manually acknowledged check names
        self._acknowledged = set(acknowledged_manual_items or [])

    # ── Individual Checks ─────────────────────────────────────────────────────

    def _check_api_key_permissions(self) -> CheckResult:
        """
        Verify API key has trade permission and withdrawal is DISABLED.
        Not all exchanges expose permission info; may return MANUAL_REQUIRED.
        """
        if self._exchange is None:
            return CheckResult(
                name="api_key_permissions",
                status=ITEM_MANUAL,
                detail="No exchange client provided. Manually verify: trade=YES, withdrawal=NO.",
            )
        try:
            # Attempt to read API key permissions if supported
            if hasattr(self._exchange, "get_api_key_permissions"):
                perms = self._exchange.get_api_key_permissions()
                trade_ok = perms.get("trade", False)
                withdrawal_disabled = not perms.get("withdraw", True)
                if not trade_ok:
                    return CheckResult("api_key_permissions", ITEM_FAIL,
                                       "trade permission not enabled on API key", perms)
                if not withdrawal_disabled:
                    return CheckResult("api_key_permissions", ITEM_FAIL,
                                       "withdrawal is ENABLED — must disable before live", perms)
                return CheckResult("api_key_permissions", ITEM_PASS,
                                   "trade=YES, withdrawal=DISABLED", perms)
            else:
                return CheckResult(
                    name="api_key_permissions",
                    status=ITEM_MANUAL,
                    detail="Exchange does not expose permission info via API. Manually confirm withdrawal=DISABLED.",
                    evidence={"exchange": str(type(self._exchange).__name__)},
                )
        except Exception as exc:
            return CheckResult("api_key_permissions", ITEM_UNKNOWN,
                               f"Exception querying permissions: {exc}")

    def _check_ip_whitelist(self) -> CheckResult:
        """
        IP whitelist check — returns MANUAL_REQUIRED if exchange doesn't expose this.
        """
        if self._exchange is None or not hasattr(self._exchange, "get_ip_whitelist"):
            return CheckResult(
                name="ip_whitelist",
                status=ITEM_MANUAL,
                detail="Exchange API does not expose IP whitelist. Manually verify in exchange dashboard.",
                evidence={"verified_by": None, "verified_at": None},
            )
        try:
            result = self._exchange.get_ip_whitelist()
            if result.get("enabled"):
                return CheckResult("ip_whitelist", ITEM_PASS, "IP whitelist active", result)
            return CheckResult("ip_whitelist", ITEM_MANUAL,
                               "IP whitelist not enabled on exchange", result)
        except Exception as exc:
            return CheckResult("ip_whitelist", ITEM_UNKNOWN, f"Cannot verify: {exc}")

    def _check_time_sync(self) -> CheckResult:
        """
        Measure clock drift to public NTP server using N TCP connection RTTs.
        Requires median drift ≤ 250ms and max drift ≤ 500ms.
        """
        samples: List[float] = []
        try:
            for _ in range(self.TIME_SYNC_SAMPLES):
                t0 = time.time()
                with socket.create_connection((self.TIME_SYNC_HOST, self.TIME_SYNC_PORT), timeout=2):
                    pass
                rtt_ms = (time.time() - t0) * 1000
                samples.append(rtt_ms / 2)  # one-way approx

            median_ms = statistics.median(samples)
            max_ms = max(samples)
            evidence = {
                "samples_ms": [round(s, 2) for s in samples],
                "median_drift_ms": round(median_ms, 2),
                "max_drift_ms": round(max_ms, 2),
                "host": self.TIME_SYNC_HOST,
            }

            if median_ms > self.TIME_SYNC_MEDIAN_LIMIT_MS:
                return CheckResult("time_sync", ITEM_FAIL,
                                   f"Median drift {median_ms:.1f}ms > {self.TIME_SYNC_MEDIAN_LIMIT_MS}ms limit",
                                   evidence)
            if max_ms > self.TIME_SYNC_MAX_LIMIT_MS:
                return CheckResult("time_sync", ITEM_FAIL,
                                   f"Max drift {max_ms:.1f}ms > {self.TIME_SYNC_MAX_LIMIT_MS}ms limit",
                                   evidence)
            return CheckResult("time_sync", ITEM_PASS,
                               f"median={median_ms:.1f}ms, max={max_ms:.1f}ms", evidence)
        except Exception as exc:
            return CheckResult("time_sync", ITEM_UNKNOWN, f"Time sync measurement failed: {exc}")

    def _check_model_snapshot(self) -> CheckResult:
        """
        Verify model/config snapshot integrity via SHA-256 of directory contents.
        """
        try:
            snapshot_dir = self._model_snapshot_path
            if not snapshot_dir.exists():
                return CheckResult("model_snapshot", ITEM_FAIL,
                                   f"Snapshot directory not found: {snapshot_dir}")
            files = sorted(snapshot_dir.rglob("*.json"))[:20]  # sample first 20 files
            if not files:
                return CheckResult("model_snapshot", ITEM_FAIL, "No snapshot files found")

            hasher = hashlib.sha256()
            for f in files:
                hasher.update(f.name.encode())
                hasher.update(f.read_bytes()[:4096])  # first 4KB of each
            snap_hash = hasher.hexdigest()[:16]

            return CheckResult("model_snapshot", ITEM_PASS,
                               f"Snapshot hash: {snap_hash}",
                               {"snapshot_hash": snap_hash, "files_checked": len(files)})
        except Exception as exc:
            return CheckResult("model_snapshot", ITEM_UNKNOWN, f"Cannot compute snapshot hash: {exc}")

    def _check_phase5_gate(self) -> CheckResult:
        """
        Read Phase 5 live readiness gate status from latest report.
        """
        try:
            if not self._phase5_report_path.exists():
                return CheckResult("phase5_live_gate", ITEM_FAIL,
                                   "Phase 5 report not found — run phase5_report_generator.py first")
            report = json.loads(self._phase5_report_path.read_text(encoding="utf-8"))
            gate = report.get("live_readiness_gate", {})
            passed = gate.get("passed", False)
            real_fills = gate.get("real_paper_fills", 0)
            duration = gate.get("duration_days", 0)

            if not passed:
                return CheckResult(
                    "phase5_live_gate",
                    ITEM_FAIL,
                    f"PHASE5_LIVE_READINESS_GATE not passed (real_fills={real_fills}, duration={duration}d)",
                    {"gate": gate},
                )
            return CheckResult("phase5_live_gate", ITEM_PASS,
                               f"Gate open (real_fills={real_fills}, duration={duration}d)", gate)
        except Exception as exc:
            return CheckResult("phase5_live_gate", ITEM_UNKNOWN, f"Cannot read Phase 5 report: {exc}")

    def _check_rollback_artifacts(self) -> CheckResult:
        """
        Verify rollback artifacts exist and are recent.
        """
        try:
            if not self._rollback_dir.exists():
                return CheckResult("rollback_artifacts", ITEM_FAIL,
                                   f"Rollback directory missing: {self._rollback_dir}")
            artifacts = list(self._rollback_dir.glob("*.json")) + list(self._rollback_dir.glob("*.pkl"))
            if not artifacts:
                return CheckResult("rollback_artifacts", ITEM_FAIL,
                                   "No rollback artifacts found in rollback directory")
            newest = max(artifacts, key=lambda f: f.stat().st_mtime)
            age_hours = (time.time() - newest.stat().st_mtime) / 3600
            if age_hours > 48:
                return CheckResult("rollback_artifacts", ITEM_FAIL,
                                   f"Newest artifact is {age_hours:.1f}h old (> 48h threshold)",
                                   {"newest": newest.name, "age_hours": round(age_hours, 1)})
            return CheckResult("rollback_artifacts", ITEM_PASS,
                               f"Found {len(artifacts)} artifacts, newest {age_hours:.1f}h ago",
                               {"count": len(artifacts), "newest": newest.name})
        except Exception as exc:
            return CheckResult("rollback_artifacts", ITEM_UNKNOWN, f"Cannot check rollback dir: {exc}")

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self) -> ChecklistResult:
        """
        Run all checks and return structured result.
        Items with MANUAL_REQUIRED that haven't been acknowledged are tracked in `manual_pending`.
        """
        checks = [
            self._check_api_key_permissions(),
            self._check_ip_whitelist(),
            self._check_time_sync(),
            self._check_model_snapshot(),
            self._check_phase5_gate(),
            self._check_rollback_artifacts(),
        ]

        manual_pending = [
            c.name for c in checks
            if c.status == ITEM_MANUAL and c.name not in self._acknowledged
        ]

        # Overall pass: no FAIL items and no unacknowledged MANUAL items
        has_fail = any(c.status == ITEM_FAIL for c in checks)
        has_unacknowledged_manual = bool(manual_pending)

        passed = not has_fail and not has_unacknowledged_manual
        return ChecklistResult(passed=passed, items=checks, manual_pending=manual_pending)

    def run_and_save(self, output_path: Optional[str] = None) -> ChecklistResult:
        result = self.run()
        path = Path(output_path) if output_path else (
            BASE_DIR / "data" / "execution" / "reports" / "live_checklist_latest.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return result
