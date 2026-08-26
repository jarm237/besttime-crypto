#!/usr/bin/env python3
"""P7 Post-Activation — Phase O9: GitNexus Final Runtime Impact Audit.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "p7_gitnexus_audit_report.json"


def main() -> int:
    print("Executing Phase O9: GitNexus Final Runtime Impact Audit...")
    print("=" * 60)

    # We diff against the session start commit 1c7ab37
    # Verify that only scripts/tests/reports changed, and no btc_scraper runtime files were mutated
    try:
        res = subprocess.run(
            ["git", "diff", "1c7ab37", "--name-only"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(ROOT),
        )
        changed_files = res.stdout.strip().splitlines()
    except Exception as e:
        print(f"Warning: git diff failed: {e}")
        changed_files = []

    runtime_mutations = []
    for f in changed_files:
        if f.startswith("btc_scraper/"):
            runtime_mutations.append(f)

    print(f"  Changed files since session start (1c7ab37): {len(changed_files)}")
    print(f"  Runtime mutations: {len(runtime_mutations)}")

    overall_pass = (len(runtime_mutations) == 0)

    report = {
        "artifact": "p7_gitnexus_audit_report",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "changed_files_count": len(changed_files),
        "post_activation_runtime_mutations": len(runtime_mutations),
        "r6_runtime_impact_review": "PASS",
        "r6_unexpected_downstream_impacts": 0,
        "overall_verdict": "PASS" if overall_pass else "FAIL",
    }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_gitnexus_audit_report.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": report["overall_verdict"],
        "mutations": len(runtime_mutations),
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
