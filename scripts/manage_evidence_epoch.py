#!/usr/bin/env python3
"""Create and transition persistent evidence epochs without touching evidence rows."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from btc_scraper.ml_engine.evidence_epoch import EvidenceEpoch
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-path", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status")
    create = subparsers.add_parser("create")
    create.add_argument("--epoch-id", required=True)
    create.add_argument("--deployment-id", required=True)
    create.add_argument("--code-commit-sha", required=True)
    create.add_argument("--model-version", required=True)
    create.add_argument("--artifact-sha256", required=True)
    create.add_argument("--feature-schema-version", required=True)
    create.add_argument(
        "--started-at",
        default=None,
        help="ISO-8601 UTC timestamp; defaults to now",
    )
    for command in ("activate", "seal", "invalidate"):
        transition = subparsers.add_parser(command)
        transition.add_argument("epoch_id")
    return parser


def main() -> int:
    args = _parser().parse_args()
    store = RuntimeEvidenceStore(args.evidence_path)
    if args.command == "create":
        result = store.create_evidence_epoch(EvidenceEpoch(
            epoch_id=args.epoch_id,
            deployment_id=args.deployment_id,
            started_at=args.started_at or datetime.now(timezone.utc).isoformat(),
            code_commit_sha=args.code_commit_sha,
            model_version=args.model_version,
            artifact_sha256=args.artifact_sha256,
            feature_schema_version=args.feature_schema_version,
        ))
    elif args.command == "status":
        result = store.get_active_evidence_epoch()
    else:
        target = {
            "activate": "ACTIVE",
            "seal": "SEALED",
            "invalidate": "INVALIDATED",
        }[args.command]
        result = store.transition_evidence_epoch(args.epoch_id, target)
    print(json.dumps(result.to_dict() if result else None, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
