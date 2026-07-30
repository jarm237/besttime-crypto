"""Persistent evidence epoch contract for controlled paper-shadow cohorts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


EVIDENCE_POLICY_VERSION = "evidence-v4"
RISK_POLICY_VERSION = "risk-fail-closed-v1"
EPOCH_STATUSES = {"DRAFT", "ACTIVE", "SEALED", "INVALIDATED"}


@dataclass(frozen=True)
class EvidenceEpoch:
    epoch_id: str
    deployment_id: str
    started_at: str
    code_commit_sha: str
    model_version: str
    artifact_sha256: str
    feature_schema_version: str
    evidence_policy_version: str = EVIDENCE_POLICY_VERSION
    risk_policy_version: str = RISK_POLICY_VERSION
    runtime_schema_version: int = 4
    status: str = "DRAFT"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "EvidenceEpoch":
        payload = dict(value)
        payload.setdefault("started_at", datetime.now(timezone.utc).isoformat())
        return cls(**payload)

    def validate(self) -> None:
        required = (
            "epoch_id", "deployment_id", "started_at", "code_commit_sha",
            "model_version", "artifact_sha256", "feature_schema_version",
            "evidence_policy_version", "risk_policy_version",
        )
        missing = [field for field in required if not str(getattr(self, field) or "").strip()]
        if missing:
            raise ValueError(f"evidence epoch missing fields: {','.join(missing)}")
        if self.status not in EPOCH_STATUSES:
            raise ValueError(f"invalid evidence epoch status: {self.status}")
        if self.evidence_policy_version != EVIDENCE_POLICY_VERSION:
            raise ValueError("evidence policy version mismatch")
        if self.risk_policy_version != RISK_POLICY_VERSION:
            raise ValueError("risk policy version mismatch")
        if int(self.runtime_schema_version) < 4:
            raise ValueError("runtime schema version mismatch")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
