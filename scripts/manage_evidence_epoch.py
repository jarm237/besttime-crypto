#!/usr/bin/env python3
"""Create and transition persistent evidence epochs without touching evidence rows."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_REPO_ROOT))

from btc_scraper.core.config import analysis_universe_hash, parse_runtime_symbols
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
        "--analysis-universe",
        required=True,
        help="Comma-separated base symbols, for example BTC,ETH,BNB",
    )
    create.add_argument(
        "--started-at",
        default=None,
        help="ISO-8601 UTC timestamp; defaults to now",
    )
    for command in (
        "activate", "block-seal", "ready-to-seal", "seal", "quarantine",
        "invalidate",
    ):
        transition = subparsers.add_parser(command)
        transition.add_argument("epoch_id")
    return parser


def main() -> int:
    args = _parser().parse_args()
    store = RuntimeEvidenceStore(args.evidence_path)
    if args.command == "create":
        analysis_universe = parse_runtime_symbols(
            args.analysis_universe,
            field_name="--analysis-universe",
        )
        result = store.create_evidence_epoch(EvidenceEpoch(
            epoch_id=args.epoch_id,
            deployment_id=args.deployment_id,
            started_at=args.started_at or datetime.now(timezone.utc).isoformat(),
            code_commit_sha=args.code_commit_sha,
            model_version=args.model_version,
            artifact_sha256=args.artifact_sha256,
            feature_schema_version=args.feature_schema_version,
            analysis_universe=analysis_universe,
            analysis_universe_hash=analysis_universe_hash(analysis_universe),
        ))
    elif args.command == "status":
        result = store.get_active_evidence_epoch()
    else:
        target = {
            "activate": "ACTIVE",
            "block-seal": "SEAL_BLOCKED",
            "ready-to-seal": "SEAL_READY",
            "seal": "SEALED",
            "quarantine": "QUARANTINED",
            "invalidate": "INVALIDATED",
        }[args.command]
        if target in {"ACTIVE", "SEALED"}:
            epoch = store.get_evidence_epoch(args.epoch_id)
            if epoch is None:
                raise RuntimeError(f"evidence epoch not found: {args.epoch_id}")
            universe = ",".join(epoch.analysis_universe)
            os.environ["BTC_DEPLOYMENT_ID"] = epoch.deployment_id
            os.environ["BTC_PAPER_RUN_ID"] = epoch.deployment_id
            os.environ["BTC_ANALYSIS_UNIVERSE"] = universe
            os.environ["AUTO_TRADE_COINS"] = universe
            os.environ.setdefault("BTC_EVIDENCE_ELIGIBLE", "true")
        result = store.transition_evidence_epoch(args.epoch_id, target)
    print(json.dumps(result.to_dict() if result else None, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
