#!/usr/bin/env python3
"""
[DISQUALIFIED / FAIL-CLOSED STUB]

reconcile_evidence_epoch_lineage.py has been disqualified and disabled by governance contract.
It indiscriminately modified historical/invalidated evidence epochs and rewrote release manifests, violating append-only governance.

Use scripts/repair_evidence_epoch_lineage.py instead for safe, non-destructive manifest hash repairs.
"""

import sys

def main():
    print("❌ ERROR: reconcile_evidence_epoch_lineage.py is DISQUALIFIED by governance contract.")
    print("Use 'python scripts/repair_evidence_epoch_lineage.py [--dry-run | --apply]' instead.")
    sys.exit(1)

if __name__ == "__main__":
    main()
