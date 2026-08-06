"""Persistent evidence epoch contract for controlled paper-shadow cohorts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from btc_scraper.core.config import SUPPORTED_SYMBOLS, analysis_universe_hash
from btc_scraper.core.runtime_pause import RuntimePausePolicy


EVIDENCE_POLICY_VERSION = "evidence-v4"
RISK_POLICY_VERSION = "risk-fail-closed-v1"
RELEASE_MANIFEST_SCHEMA_VERSION = "evidence-manifest-v1"
EPOCH_STATUSES = {
    "DRAFT", "ACTIVE", "SEAL_BLOCKED", "SEAL_READY", "SEALED",
    "INVALIDATED", "QUARANTINED",
}


@dataclass(frozen=True)
class EvidenceEpoch:
    epoch_id: str
    deployment_id: str
    started_at: str
    code_commit_sha: str
    model_version: str
    artifact_sha256: str
    feature_schema_version: str
    analysis_universe: tuple[str, ...]
    analysis_universe_hash: str
    activated_at: str | None = None
    evidence_policy_version: str = EVIDENCE_POLICY_VERSION
    risk_policy_version: str = RISK_POLICY_VERSION
    runtime_schema_version: int = 6
    status: str = "DRAFT"
    paper_run_id: str = ""
    release_manifest: dict[str, Any] | None = None
    release_manifest_sha256: str = ""
    runtime_pause_policy: dict[str, Any] = field(
        default_factory=lambda: RuntimePausePolicy().to_dict()
    )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvidenceEpoch":
        payload = dict(value)
        payload.setdefault("started_at", datetime.now(timezone.utc).isoformat())
        payload.setdefault("paper_run_id", payload.get("deployment_id") or "")
        payload["analysis_universe"] = tuple(payload.get("analysis_universe") or ())
        payload["runtime_pause_policy"] = RuntimePausePolicy.from_mapping(
            payload.get("runtime_pause_policy")
        ).to_dict()
        return cls(**payload)

    def validate(self) -> None:
        required = (
            "epoch_id", "deployment_id", "started_at", "code_commit_sha",
            "model_version", "artifact_sha256", "feature_schema_version",
            "analysis_universe", "analysis_universe_hash",
            "evidence_policy_version", "risk_policy_version",
        )
        missing = [field for field in required if not str(getattr(self, field) or "").strip()]
        if missing:
            raise ValueError(f"evidence epoch missing fields: {','.join(missing)}")
        if self.status not in EPOCH_STATUSES:
            raise ValueError(f"invalid evidence epoch status: {self.status}")
        RuntimePausePolicy.from_mapping(self.runtime_pause_policy)
        if self.evidence_policy_version != EVIDENCE_POLICY_VERSION:
            raise ValueError("evidence policy version mismatch")
        if self.risk_policy_version != RISK_POLICY_VERSION:
            raise ValueError("risk policy version mismatch")
        normalized = tuple(str(symbol).strip().upper() for symbol in self.analysis_universe)
        if not normalized or normalized != self.analysis_universe:
            raise ValueError("evidence epoch analysis universe is invalid")
        if len(set(normalized)) != len(normalized):
            raise ValueError("evidence epoch analysis universe contains duplicates")
        unsupported = sorted(set(normalized) - SUPPORTED_SYMBOLS)
        if unsupported:
            raise ValueError(
                "evidence epoch analysis universe contains unsupported symbols: "
                + ",".join(unsupported)
            )
        if self.analysis_universe_hash != analysis_universe_hash(normalized):
            raise ValueError("evidence epoch analysis universe hash mismatch")
        if self.status == "DRAFT" and self.activated_at is not None:
            raise ValueError("draft evidence epoch cannot have activated_at")
        if self.status != "DRAFT" and not self.activated_at:
            raise ValueError("activated evidence epoch requires activated_at")
        paper_run_id = str(self.paper_run_id or "").strip()
        if not paper_run_id:
            raise ValueError("evidence epoch paper_run_id is invalid")
        if self.release_manifest is None:
            raise ValueError("evidence epoch release_manifest is required")
        if not isinstance(self.release_manifest, Mapping):
            raise ValueError("evidence epoch release_manifest must be a mapping")
        manifest = dict(self.release_manifest)
        required_manifest_fields = (
            "manifest_schema_version",
            "release_sha",
            "artifact_sha256",
            "metadata_sha256",
            "registry_sha256",
            "deployment_id",
            "paper_run_id",
            "feature_schema_version",
            "analysis_universe",
            "decision_contract",
            "probability_semantics",
        )
        missing_manifest_fields = [
            field_name for field_name in required_manifest_fields
            if not str(manifest.get(field_name) or "").strip()
        ]
        if missing_manifest_fields:
            raise ValueError("evidence epoch release_manifest missing fields: " + ",".join(missing_manifest_fields))
        if str(manifest.get("manifest_schema_version") or "") != RELEASE_MANIFEST_SCHEMA_VERSION:
            raise ValueError("evidence epoch release_manifest manifest_schema_version mismatch")
        if str(manifest.get("release_sha") or "") != str(self.code_commit_sha):
            raise ValueError("evidence epoch release_manifest release_sha mismatch")
        if str(manifest.get("artifact_sha256") or "") != str(self.artifact_sha256):
            raise ValueError("evidence epoch release_manifest artifact_sha256 mismatch")
        if str(manifest.get("deployment_id") or "") != str(self.deployment_id):
            raise ValueError("evidence epoch release_manifest deployment_id mismatch")
        if str(manifest.get("paper_run_id") or "") != paper_run_id:
            raise ValueError("evidence epoch release_manifest paper_run_id mismatch")
        if str(manifest.get("feature_schema_version") or "") != str(self.feature_schema_version):
            raise ValueError("evidence epoch release_manifest feature_schema_version mismatch")
        normalized_universe = ",".join(str(symbol).strip().upper() for symbol in self.analysis_universe)
        if str(manifest.get("analysis_universe") or "") != normalized_universe:
            raise ValueError("evidence epoch release_manifest analysis_universe mismatch")
        if str(manifest.get("decision_contract") or "") != "side-probability-v2":
            raise ValueError("evidence epoch release_manifest decision_contract mismatch")
        if str(manifest.get("probability_semantics") or "") != "P(up)":
            raise ValueError("evidence epoch release_manifest probability_semantics mismatch")
        if self.release_manifest_sha256:
            expected_manifest_hash = hashlib.sha256(
                json.dumps(
                    dict(manifest),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if self.release_manifest_sha256 != expected_manifest_hash:
                raise ValueError("evidence epoch release_manifest_sha256 mismatch")
        if int(self.runtime_schema_version) < 6:
            raise ValueError("runtime schema version mismatch")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
