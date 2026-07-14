"""Append-only local model registry with atomic promotion and rollback."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_resolver import ROOT, sha256_file

REGISTRY_PATH = ROOT / "logs" / "model_registry.json"
VALID_STATUSES = {"candidate", "shadow", "production", "archive", "rejected", "disabled"}


class ModelRegistry:
    def __init__(self, path: Path | str = REGISTRY_PATH) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {"records": []}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) and isinstance(raw.get("records"), list) else {"records": []}

    def _write(self, data: dict[str, list[dict[str, Any]]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def register(self, record: dict[str, Any]) -> dict[str, Any]:
        name, version, status = record.get("model_name"), record.get("version"), record.get("status", "candidate")
        if not name or not version or status not in VALID_STATUSES:
            raise ValueError("model_name, version and valid status are required")
        result = dict(record)
        artifact_path = result.get("artifact_path")
        if artifact_path:
            artifact = (ROOT / artifact_path).resolve() if not Path(artifact_path).is_absolute() else Path(artifact_path)
            if not artifact.exists():
                raise FileNotFoundError(f"cannot register missing artifact: {artifact}")
            result["artifact_path"] = str(artifact.relative_to(ROOT))
            result.setdefault("sha256", sha256_file(artifact))
        result.setdefault("registered_at", datetime.now(timezone.utc).isoformat())
        data = self._read()
        if any(r.get("model_name") == name and r.get("version") == version for r in data["records"]):
            raise ValueError("model version already registered; artifacts are immutable")
        if status == "production":
            for existing in data["records"]:
                if existing.get("model_name") == name and existing.get("status") == "production":
                    existing["status"] = "archive"
                    existing["archived_at"] = result["registered_at"]
                    result.setdefault("previous_production_version", existing.get("version"))
        data["records"].append(result)
        self._write(data)
        return result

    def active(self, model_name: str, allowed_statuses: tuple[str, ...] = ("production",)) -> dict[str, Any] | None:
        records = [r for r in self._read()["records"] if r.get("model_name") == model_name and r.get("status") in allowed_statuses]
        return records[-1] if records else None

    def rollback(self, model_name: str, version: str) -> dict[str, Any]:
        data = self._read()
        target = next((r for r in data["records"] if r.get("model_name") == model_name and r.get("version") == version), None)
        if target is None:
            raise KeyError("rollback version not found")
        for item in data["records"]:
            if item.get("model_name") == model_name and item.get("status") == "production":
                item["status"] = "archive"
        target["status"] = "production"
        target["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
        self._write(data)
        return target

    def permits_artifact(self, model_name: str, artifact_path: Path, sha256: str | None,
                         allowed_statuses: tuple[str, ...] = ("production", "shadow")) -> bool:
        record = self.active(model_name, allowed_statuses)
        if record is None:
            return False
        expected_path = str(artifact_path.resolve().relative_to(ROOT)).replace("/", "\\")
        registered_path = str(record.get("artifact_path", "")).replace("/", "\\")
        return registered_path == expected_path and (not record.get("sha256") or record.get("sha256") == sha256)
