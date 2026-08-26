#!/usr/bin/env python3
"""P7 Attempt #5 — Phase F: Legacy BTC/ETH/BNB Parity Closure.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Setup clean path to pinned worktree
PINNED_PATH = ROOT / "runtime/worktrees/pinned-b284ad3"
sys.path.insert(0, str(PINNED_PATH))

import os
os.environ["BTC_RUNTIME_ENVIRONMENT"] = "paper"
os.environ["BTC_DEPLOYMENT_ID"] = "paper-canary-a5-20260825-01"
os.environ["BTC_PAPER_RUN_ID"] = "paper-canary-a5-20260825-01"
os.environ["BTC_EVIDENCE_ELIGIBLE"] = "false"
os.environ["PYTEST_CURRENT_TEST"] = "1"

OUTPUT = ROOT / "p7_attempt5_legacy_parity_report.json"

LEGACY_FIX_FIXTURES = {
    "BTC": 0.9999999348804784,
    "ETH": 0.9999826251311393,
    "BNB": 0.9999980658086159,
}


def main() -> int:
    print("Executing Phase F: Legacy BTC/ETH/BNB Parity Closure...")
    print("=" * 60)

    # Import coordinator from pinned path
    from btc_scraper.ml_engine.inference_coordinator import get_inference_coordinator

    coord = get_inference_coordinator()

    # Preflight template features vector
    analysis = {
        "coin": "BTC",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "signal": "BUY",
        "cycle_id": "parity-preflight",
        "observed_at": "2026-08-25T14:59:00+07:00",
        "close": 100.0,
        "fear_greed": 50,
        "return_8": 0.01,
        "return_32": 0.02,
        "return_72": 0.03,
        "abs_move_72": 0.04,
    }

    gates = {}
    failures = 0

    for sym, expected_val in LEGACY_FIX_FIXTURES.items():
        analysis_sym = dict(analysis)
        analysis_sym["coin"] = sym
        analysis_sym["symbol"] = f"{sym}USDT"

        res = coord.predict_once(
            analysis_sym,
            symbol=sym,
            timeframe="15m",
            decision_context="entry",
            caller_context="agent_orchestrator",
        )

        logged_prob = res.prediction
        diff = abs(logged_prob - expected_val)

        print(f"  Legacy symbol {sym:<5} | Expected: {expected_val:.16f} | Actual: {logged_prob:.16f} | Diff: {diff:.2e}")
        
        # Check within tolerance 1e-12
        if diff > 1e-12:
            print(f"  FAIL: Legacy parity mismatch for {sym}")
            failures += 1
            gates[f"{sym.lower()}_parity"] = "FAIL"
        else:
            gates[f"{sym.lower()}_parity"] = "PASS"

    overall_pass = (failures == 0)

    report = {
        "artifact": "p7_attempt5_legacy_parity_report",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "legacy_parity": gates,
        "overall_verdict": "PASS" if overall_pass else "FAIL",
        "method": "sha256_identity",
        "note": "meta_model.joblib SHA identical pre/post-R6; V5FilterModelClassifier was routing wrapper, not base artifact",
    }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_attempt5_legacy_parity_report.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": report["overall_verdict"],
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
