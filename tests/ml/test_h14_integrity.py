from __future__ import annotations

import copy
import json
from pathlib import Path

from btc_scraper.ml_engine.h14_integrity import (
    classify_provenance,
    reconstitute,
    semantic_analysis_key,
)


ROOT = Path("historical-h14-prospective-validation-design-discrimination")


def _contract() -> dict:
    return json.loads((ROOT / "contracts/h14_2_provenance_purity_contract_v1.json").read_text(encoding="utf-8"))


def _raw(**overrides) -> dict:
    row = {
        "prospective_analysis_id": "id-1",
        "symbol": "BNBUSDT",
        "cycle_timestamp": "2026-08-17T22:45:00Z",
        "release_sha": "local-production",
        "artifact_sha256": "dbf0a08241dae01241539ef3f48c6a0b13da9b13a5b128de259aac06d267241c",
        "feature_snapshot_hash": "feature-1",
        "buy_posterior": 0.4,
        "sell_posterior": 0.6,
        "record_hash": "source-hash",
    }
    row.update(overrides)
    return row


def test_provenance_classifier_separates_authoritative_test_and_unknown():
    contract = _contract()
    assert classify_provenance(_raw(), contract)["classification"] == "AUTHORITATIVE"
    dummy = _raw(release_sha="dummy-dep", feature_snapshot_hash="dummy-hash")
    assert classify_provenance(dummy, contract)["classification"] == "QUARANTINED_TEST"
    assert classify_provenance(_raw(release_sha="mystery"), contract)["classification"] == "QUARANTINED_UNKNOWN_LINEAGE"


def test_reconstitution_is_pure_and_quarantines_entire_semantic_collision():
    analyses = [_raw(), _raw(prospective_analysis_id="id-2", feature_snapshot_hash="feature-2")]
    original = copy.deepcopy(analyses)
    decisions = [
        {"prospective_analysis_id": row["prospective_analysis_id"], "design_id": design, "symbol": "BNBUSDT", "decision_hash": f"{row['prospective_analysis_id']}-{design}"}
        for row in analyses for design in ("MF2", "MF4")
    ]
    accounting = [{"prospective_analysis_id": row["prospective_analysis_id"], "symbol": "BNBUSDT", "divergence_hash": row["prospective_analysis_id"]} for row in analyses]

    result = reconstitute(analyses, decisions, accounting, _contract(), checkpoint_generated_at="2026-08-19T12:01:03Z")

    assert analyses == original
    assert result["analyses"] == []
    assert result["summary"]["canonical_collision_count"] == 1
    assert result["summary"]["canonical_collision_rows"] == 2
    assert result["quarantine"][0]["record_ids"] == ["id-1", "id-2"]


def test_semantic_key_uses_contract_encoding():
    assert semantic_analysis_key("epoch", "BTCUSDT", "2026-01-01T00:00:00Z") == (
        "11de736ebed9fec090884c26d4b654acb23ec9239defbd6cd7fa82f17ffc2c30"
    )


def test_checkpoint_681_reconstitution_is_deterministic_and_complete():
    from scripts.reconstitute_h14_evidence import build

    first = build(ROOT)
    second = build(ROOT)
    assert first["checkpoint"] == second["checkpoint"]
    assert first["streams"] == second["streams"]
    assert first["result"]["summary"] == {
        "raw_analysis_rows": 652,
        "authoritative_analysis_rows": 647,
        "quarantined_analysis_rows": 5,
        "timestamp_corrected_count": 649,
        "test_quarantine_count": 3,
        "invalid_lineage_count": 0,
        "unknown_lineage_count": 0,
        "duplicate_identical_count": 0,
        "canonical_collision_count": 1,
        "canonical_collision_rows": 2,
        "future_authoritative_rows": 0,
        "timezone_ambiguous_authoritative_rows": 0,
        "cardinality_violations": 0,
        "posterior_violations": 0,
        "classification_hash": "d03008f727d1f0122839dcb56e805fd0a4022389b5060befc9e7dfa00378c1d7",
    }
