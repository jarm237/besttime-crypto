#!/usr/bin/env python3
"""Rebuild H14.2 authoritative evidence without mutating checkpoint #681."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.ml_engine.h14_integrity import canonical_json, read_jsonl, reconstitute, sha256_value


DEFAULT_ROOT = Path("historical-h14-prospective-validation-design-discrimination")


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(canonical_json(row) + "\n" for row in rows)


def build(root: Path) -> dict[str, Any]:
    data = root / "data"
    reports = root / "reports"
    contracts = root / "contracts"
    source_checkpoint_path = reports / "h14_2_stream_checkpoint.json"
    source_checkpoint = json.loads(source_checkpoint_path.read_text(encoding="utf-8"))
    provenance = json.loads((contracts / "h14_2_provenance_purity_contract_v1.json").read_text(encoding="utf-8"))

    analysis_file = data / "h14_1_prospective_analysis_stream.jsonl"
    decisions_file = data / "h14_1_prospective_design_decisions.jsonl"
    accounting_file = data / "h14_2_decision_divergence_accounting.jsonl"

    for file_path, expected_sha_key in [
        (analysis_file, "analysis_stream_sha256"),
        (decisions_file, "decision_stream_sha256"),
        (accounting_file, "divergence_sha256"),
    ]:
        if not file_path.is_file() or file_path.stat().st_size == 0:
            raise RuntimeError(f"raw_stream_mutation_forbidden: raw prospective input stream missing or empty ({file_path.name})")
        actual_sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
        expected_sha = source_checkpoint[expected_sha_key]
        if actual_sha != expected_sha:
            raise RuntimeError(f"raw_stream_mutation_forbidden: raw prospective stream {file_path.name} sha256 mismatch (expected {expected_sha}, got {actual_sha})")

    result = reconstitute(
        read_jsonl(analysis_file),
        read_jsonl(decisions_file),
        read_jsonl(accounting_file),
        provenance,
        checkpoint_generated_at=source_checkpoint["checkpoint_timestamp"],
    )
    streams = {
        "analysis": _jsonl(result["analyses"]),
        "decisions": _jsonl(result["decisions"]),
        "accounting": _jsonl(result["accounting"]),
    }
    hashes = {name: hashlib.sha256(payload.encode("utf-8")).hexdigest() for name, payload in streams.items()}
    summary = result["summary"]
    gates = {
        "G1_TIMESTAMP_CONTRACT": "PASS" if summary["future_authoritative_rows"] == 0 and summary["timezone_ambiguous_authoritative_rows"] == 0 else "FAIL",
        "G2_PROVENANCE_PURITY": "PASS" if summary["invalid_lineage_count"] == 0 and summary["unknown_lineage_count"] == 0 else "FAIL",
        "G3_CANONICAL_SEMANTIC_UNIQUENESS": "PASS" if summary["cardinality_violations"] == 0 and summary["posterior_violations"] == 0 else "FAIL",
        "H14_3": "BLOCKED",
    }
    manifest = {
        "manifest_id": "h14_2_quarantine_manifest_v1",
        "source_checkpoint_sequence": 681,
        "source_analysis_sha256": source_checkpoint["analysis_stream_sha256"],
        "policy": "excluded_from_authoritative_derived_streams; raw source unchanged",
        "entries": result["quarantine"],
        "record_level_quarantine_count": summary["quarantined_analysis_rows"],
    }
    report = {
        "report_id": "h14_2_authoritative_rebuild_report_v1",
        "source_checkpoint_sequence": 681,
        "source_checkpoint_sha256": hashlib.sha256(source_checkpoint_path.read_bytes()).hexdigest(),
        "summary": summary,
        "derived_stream_sha256": hashes,
        "gates": gates,
        "quality_evaluation": "BLOCKED",
        "pnl_evaluation": "BLOCKED",
    }
    checkpoint = {
        "checkpoint_id": "h14_2_stream_checkpoint_r2",
        "source_checkpoint_sequence": 681,
        "source_checkpoint_sha256": report["source_checkpoint_sha256"],
        "source_analysis_rows": source_checkpoint["analysis_stream_rows"],
        "source_analysis_sha256": source_checkpoint["analysis_stream_sha256"],
        "authoritative_analysis_rows": len(result["analyses"]),
        "authoritative_decision_rows": len(result["decisions"]),
        "authoritative_accounting_rows": len(result["accounting"]),
        "derived_stream_sha256": hashes,
        "quarantine_manifest_sha256": sha256_value(manifest),
        "classification_hash": summary["classification_hash"],
        "gates": gates,
        "raw_checkpoint_681_mutated": False,
        "quality_evaluation": "BLOCKED",
        "pnl_evaluation": "BLOCKED",
    }
    return {"result": result, "streams": streams, "manifest": manifest, "report": report, "checkpoint": checkpoint}


def materialize(root: Path, built: dict[str, Any]) -> None:
    data = root / "data"
    reports = root / "reports"
    _atomic_text(data / "h14_2_authoritative_analysis_stream.jsonl", built["streams"]["analysis"])
    _atomic_text(data / "h14_2_authoritative_design_decisions.jsonl", built["streams"]["decisions"])
    _atomic_text(data / "h14_2_authoritative_divergence_accounting.jsonl", built["streams"]["accounting"])
    _atomic_text(reports / "h14_2_quarantine_manifest.json", json.dumps(built["manifest"], indent=2, sort_keys=True) + "\n")
    _atomic_text(reports / "h14_2_authoritative_rebuild_report.json", json.dumps(built["report"], indent=2, sort_keys=True) + "\n")
    report = built["report"]
    summary = report["summary"]
    markdown = (
        "# H14.2 authoritative evidence rebuild\n\n"
        f"Source checkpoint: #681 (unchanged)\n\n"
        f"Authoritative analyses: {summary['authoritative_analysis_rows']}\n\n"
        f"Quarantined source records: {summary['quarantined_analysis_rows']} "
        f"(test={summary['test_quarantine_count']}, collision={summary['canonical_collision_rows']})\n\n"
        f"G1: {report['gates']['G1_TIMESTAMP_CONTRACT']}; "
        f"G2: {report['gates']['G2_PROVENANCE_PURITY']}; "
        f"G3: {report['gates']['G3_CANONICAL_SEMANTIC_UNIQUENESS']}; H14.3: BLOCKED.\n"
    )
    _atomic_text(reports / "h14_2_authoritative_rebuild_report.md", markdown)
    _atomic_text(reports / "h14_2_stream_checkpoint_r2.json", json.dumps(built["checkpoint"], indent=2, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--materialize", action="store_true")
    args = parser.parse_args()
    built = build(args.root)
    if args.materialize:
        materialize(args.root, built)
    print(canonical_json({"checkpoint": built["checkpoint"], "summary": built["result"]["summary"]}))


if __name__ == "__main__":
    main()
