"""
Live Production Operations Entry Point
Validates environment configurations, checklist status, Phase 5 gates, and kill-switch state.
This entrypoint is fail-closed: it refuses to run unless all checks pass.
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

from btc_scraper.execution.live_checklist import LiveChecklist
from btc_scraper.execution.kill_switch import KillSwitch

BASE_DIR = Path(__file__).parent
PHASE5_REPORT_PATH = BASE_DIR / "data" / "execution" / "reports" / "phase5_report_latest.json"

def assert_live_authorized() -> None:
    print("[Live Production] Performing fail-closed validation checks...")

    # 1. Environment Variable Checks
    live_enabled = os.getenv("LIVE_TRADING_ENABLED", "false").lower()
    if live_enabled != "true":
        raise RuntimeError(
            "LIVE_TRADING_ENABLED is not set to 'true'. "
            "To enable live trading, you must explicitly set the environment variable: LIVE_TRADING_ENABLED=true"
        )

    dry_run = os.getenv("AUTO_TRADE_DRY_RUN", "true").lower()
    if dry_run != "false":
        raise RuntimeError(
            "AUTO_TRADE_DRY_RUN must explicitly be set to 'false' for live trading. "
            "To enable live trading, set: AUTO_TRADE_DRY_RUN=false"
        )

    auth_token = os.getenv("LIVE_AUTHORIZATION_TOKEN", "").strip()
    if not auth_token:
        raise RuntimeError(
            "LIVE_AUTHORIZATION_TOKEN is missing or empty. "
            "A valid non-empty live authorization token is required to start live operations."
        )

    # 2. Phase 5 Gate Check
    if not PHASE5_REPORT_PATH.exists():
        raise RuntimeError(
            f"Phase 5 Gate Report not found at {PHASE5_REPORT_PATH}. "
            "You must run Phase 5 validation and generate a passing report before running live."
        )
    
    try:
        report_data = json.loads(PHASE5_REPORT_PATH.read_text(encoding="utf-8"))
        gate_passed = report_data.get("live_readiness_gate", {}).get("passed", False)
        if not gate_passed:
            raise RuntimeError(
                "Phase 5 Live Readiness Gate has not passed. "
                "Check data/execution/reports/phase5_report_latest.json for details."
            )
    except json.JSONDecodeError:
        raise RuntimeError(f"Phase 5 Gate Report at {PHASE5_REPORT_PATH} is malformed.")

    # 3. Live Checklist Check
    ack_items_str = os.getenv("LIVE_ACKNOWLEDGED_MANUAL_ITEMS", "")
    acknowledged_items = [item.strip() for item in ack_items_str.split(",") if item.strip()]
    
    checklist = LiveChecklist(acknowledged_manual_items=acknowledged_items)
    checklist_res = checklist.run()
    if not checklist_res.passed:
        blocking_items = [item.name for item in checklist_res.items if item.status == "FAIL"]
        pending_manual = checklist_res.manual_pending
        raise RuntimeError(
            f"Live Readiness Checklist has failed. "
            f"Blocking items: {blocking_items}. "
            f"Unacknowledged manual items: {pending_manual}. "
            "To acknowledge manual verification items, set the environment variable: "
            "LIVE_ACKNOWLEDGED_MANUAL_ITEMS=item1,item2"
        )

    # 4. Kill-Switch state check
    ks = KillSwitch()
    if not ks.is_armed():
        raise RuntimeError(
            f"Kill-Switch is in non-ARMED state: {ks.state}. "
            "Reset the kill-switch state before starting live operations."
        )

    print("[Live Production] All validation checks passed! Live mode authorized.")

from main import main

if __name__ == "__main__":
    try:
        assert_live_authorized()
        print("[Live Production] Starting main trading loop in LIVE mode...")
        main()
    except Exception as exc:
        print(f"\n[FATAL ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
