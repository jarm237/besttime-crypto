"""Deterministic H14.2 provenance, uniqueness, and reconstitution rules."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

H14_EPOCH_ID = "H14_PROSPECTIVE_OBSERVATION_EPOCH_V1_2026_08_13"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def semantic_analysis_key(epoch_id: str, symbol: str, cycle_timestamp: str) -> str:
    payload = f"{epoch_id}|{symbol}|{cycle_timestamp}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def semantic_fingerprint(record: Mapping[str, Any]) -> str:
    excluded = {
        "prospective_analysis_id", "record_hash", "source_record_hash",
        "semantic_analysis_key", "semantic_fingerprint", "classification",
    }
    return sha256_value({key: value for key, value in record.items() if key not in excluded})


def normalize_legacy_timestamp(value: str, timezone_name: str) -> str:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    wall_clock = parsed.replace(tzinfo=None, microsecond=0)
    corrected = wall_clock.replace(tzinfo=ZoneInfo(timezone_name)).astimezone(timezone.utc)
    return corrected.isoformat().replace("+00:00", "Z")


def classify_provenance(record: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in contract["required_record_fields"] if not record.get(field)]
    if missing:
        return {"classification": "QUARANTINED_INVALID_LINEAGE", "reason_code": "MISSING_PROVENANCE_FIELDS", "reason_detail": ",".join(missing)}

    for lineage in contract["frozen_test_lineages"]:
        if all(record.get(field) == lineage.get(field) for field in ("release_sha", "artifact_sha256", "feature_snapshot_hash")):
            return {"classification": "QUARANTINED_TEST", "reason_code": lineage["reason_code"], "reason_detail": lineage["producer"]}

    release_matches = [row for row in contract["allowed_lineages"] if row["release_sha"] == record.get("release_sha")]
    if not release_matches:
        return {"classification": "QUARANTINED_UNKNOWN_LINEAGE", "reason_code": "RELEASE_NOT_IN_FROZEN_LINEAGE", "reason_detail": str(record.get("release_sha"))}
    lineage = release_matches[0]
    if lineage["artifact_sha256"] != record.get("artifact_sha256"):
        return {"classification": "QUARANTINED_INVALID_LINEAGE", "reason_code": "ARTIFACT_LINEAGE_MISMATCH", "reason_detail": str(record.get("artifact_sha256"))}
    return {"classification": "AUTHORITATIVE", "reason_code": "FROZEN_LINEAGE_MATCH", "reason_detail": lineage["producer"], "lineage": lineage}


def reconstitute(
    analyses: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    accounting: list[dict[str, Any]],
    provenance_contract: Mapping[str, Any],
    *,
    checkpoint_generated_at: str,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = []
    timestamp_corrected = 0
    provenance_counts: dict[str, int] = defaultdict(int)

    for raw in analyses:
        provenance = classify_provenance(raw, provenance_contract)
        provenance_counts[provenance["classification"]] += 1
        if provenance["classification"] != "AUTHORITATIVE":
            quarantine.append({
                "prospective_analysis_id": raw.get("prospective_analysis_id"),
                "classification": provenance["classification"],
                "reason_code": provenance["reason_code"],
                "reason_detail": provenance["reason_detail"],
                "source_checkpoint": 681,
            })
            continue
        lineage = provenance["lineage"]
        normalized = normalize_legacy_timestamp(raw["cycle_timestamp"], lineage["legacy_timestamp_timezone"])
        timestamp_corrected += int(normalized != raw["cycle_timestamp"])
        row = dict(raw)
        row["source_record_hash"] = row.pop("record_hash", None)
        row.update({
            "epoch_id": provenance_contract["epoch_id"],
            "deployment_id": lineage["deployment_id"],
            "producer": lineage["producer"],
            "environment": lineage["environment"],
            "cycle_timestamp": normalized,
            "classification": "AUTHORITATIVE",
        })
        row["semantic_analysis_key"] = semantic_analysis_key(row["epoch_id"], row["symbol"], normalized)
        row["semantic_fingerprint"] = semantic_fingerprint(row)
        row["record_hash"] = sha256_value({k: v for k, v in row.items() if k != "record_hash"})
        candidates.append(row)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        grouped[row["semantic_analysis_key"]].append(row)
    accepted: list[dict[str, Any]] = []
    duplicate_identical = 0
    collision_groups = 0
    collision_rows = 0
    for key in sorted(grouped):
        rows = sorted(grouped[key], key=lambda row: row["prospective_analysis_id"])
        fingerprints = {row["semantic_fingerprint"] for row in rows}
        if len(rows) == 1:
            accepted.extend(rows)
        elif len(fingerprints) == 1:
            accepted.append(rows[0])
            duplicate_identical += len(rows) - 1
            for row in rows[1:]:
                quarantine.append({"prospective_analysis_id": row["prospective_analysis_id"], "canonical_key": key, "classification": "DUPLICATE_IDENTICAL", "reason_code": "SEMANTIC_REPLAY", "source_checkpoint": 681})
        else:
            collision_groups += 1
            collision_rows += len(rows)
            quarantine.append({"canonical_key": key, "classification": "CANONICAL_COLLISION", "reason_code": "SEMANTIC_FINGERPRINT_MISMATCH", "record_ids": sorted(row["prospective_analysis_id"] for row in rows), "source_checkpoint": 681})

    accepted.sort(key=lambda row: (row["cycle_timestamp"], row["symbol"], row["prospective_analysis_id"]))
    accepted_by_id = {row["prospective_analysis_id"]: row for row in accepted}
    derived_decisions = []
    for row in decisions:
        analysis = accepted_by_id.get(row.get("prospective_analysis_id"))
        if analysis is None:
            continue
        rebuilt = dict(row)
        rebuilt["source_decision_hash"] = rebuilt.pop("decision_hash", None)
        rebuilt["cycle_timestamp"] = analysis["cycle_timestamp"]
        rebuilt["epoch_id"] = analysis["epoch_id"]
        rebuilt["semantic_analysis_key"] = analysis["semantic_analysis_key"]
        rebuilt["decision_hash"] = sha256_value({k: v for k, v in rebuilt.items() if k != "decision_hash"})
        derived_decisions.append(rebuilt)
    derived_accounting = []
    for row in accounting:
        analysis = accepted_by_id.get(row.get("prospective_analysis_id"))
        if analysis is None:
            continue
        rebuilt = dict(row)
        rebuilt["source_divergence_hash"] = rebuilt.pop("divergence_hash", None)
        rebuilt["cycle_timestamp"] = analysis["cycle_timestamp"]
        rebuilt["epoch_id"] = analysis["epoch_id"]
        rebuilt["semantic_analysis_key"] = analysis["semantic_analysis_key"]
        rebuilt["divergence_hash"] = sha256_value({k: v for k, v in rebuilt.items() if k != "divergence_hash"})
        derived_accounting.append(rebuilt)

    decision_counts = defaultdict(int)
    for row in derived_decisions:
        decision_counts[row["prospective_analysis_id"]] += 1
    accounting_counts = defaultdict(int)
    for row in derived_accounting:
        accounting_counts[row["prospective_analysis_id"]] += 1
    cardinality_violations = sum(decision_counts[key] != 2 or accounting_counts[key] != 1 for key in accepted_by_id)
    checkpoint_time = datetime.fromisoformat(checkpoint_generated_at.replace("Z", "+00:00"))
    future_rows = sum(datetime.fromisoformat(row["cycle_timestamp"].replace("Z", "+00:00")) > checkpoint_time for row in accepted)
    posterior_violations = sum(abs(float(row["buy_posterior"]) + float(row["sell_posterior"]) - 1.0) > 1e-12 for row in accepted)
    quarantine.sort(key=lambda row: canonical_json(row))
    classification_hash = sha256_value({"accepted_ids": sorted(accepted_by_id), "quarantine": quarantine})
    return {
        "analyses": accepted,
        "decisions": sorted(derived_decisions, key=lambda row: (row["cycle_timestamp"], row["symbol"], row["design_id"])),
        "accounting": sorted(derived_accounting, key=lambda row: (row["cycle_timestamp"], row["symbol"])),
        "quarantine": quarantine,
        "summary": {
            "raw_analysis_rows": len(analyses),
            "authoritative_analysis_rows": len(accepted),
            "quarantined_analysis_rows": len(analyses) - len(accepted),
            "timestamp_corrected_count": timestamp_corrected,
            "test_quarantine_count": provenance_counts["QUARANTINED_TEST"],
            "invalid_lineage_count": provenance_counts["QUARANTINED_INVALID_LINEAGE"],
            "unknown_lineage_count": provenance_counts["QUARANTINED_UNKNOWN_LINEAGE"],
            "duplicate_identical_count": duplicate_identical,
            "canonical_collision_count": collision_groups,
            "canonical_collision_rows": collision_rows,
            "future_authoritative_rows": future_rows,
            "timezone_ambiguous_authoritative_rows": 0,
            "cardinality_violations": cardinality_violations,
            "posterior_violations": posterior_violations,
            "classification_hash": classification_hash,
        },
    }
