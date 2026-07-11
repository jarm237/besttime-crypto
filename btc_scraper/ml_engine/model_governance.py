"""Auditable model registry, promotion gate, rollback and shadow monitoring."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable


@dataclass(frozen=True)
class PromotionPolicy:
    min_samples: int = 1000
    min_cv_auc: float = .58
    min_holdout_auc: float = .56
    max_calibration_error: float = .10
    max_cv_holdout_gap: float = .05


@dataclass
class PromotionDecision:
    status: str
    reasons: list[str] = field(default_factory=list)


def schema_hash(features: Iterable[str]) -> str:
    """Stable, order-sensitive schema fingerprint used at train and load time."""
    return hashlib.sha256(json.dumps(list(features), separators=(",", ":")).encode()).hexdigest()


def artifact_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evaluate_promotion(metrics: dict[str, Any], policy: PromotionPolicy = PromotionPolicy()) -> PromotionDecision:
    reasons: list[str] = []
    samples = int(metrics.get("n_samples", 0) or 0)
    cv_auc = metrics.get("cv_auc")
    holdout_auc = metrics.get("holdout_auc")
    calibration_error = metrics.get("calibration_error")
    if samples < policy.min_samples: reasons.append(f"n_samples {samples} < {policy.min_samples}")
    if cv_auc is None or float(cv_auc) < policy.min_cv_auc: reasons.append(f"cv_auc {cv_auc} < {policy.min_cv_auc}")
    if holdout_auc is None or float(holdout_auc) < policy.min_holdout_auc: reasons.append(f"holdout_auc {holdout_auc} < {policy.min_holdout_auc}")
    if calibration_error is None or float(calibration_error) > policy.max_calibration_error: reasons.append("calibration_error exceeds limit")
    if cv_auc is None or holdout_auc is None or abs(float(cv_auc) - float(holdout_auc)) > policy.max_cv_holdout_gap:
        reasons.append("cv_holdout_gap exceeds limit")
    return PromotionDecision("PROMOTED" if not reasons else "REJECTED", reasons)


def calibration_metrics(probabilities: Iterable[float], labels: Iterable[int], bins: int = 10) -> dict[str, Any]:
    pairs = [(float(p), int(y)) for p, y in zip(probabilities, labels)]
    if not pairs: return {"n_samples": 0, "ece": None, "brier_score": None, "reliability": [], "high_confidence": None}
    n = len(pairs)
    brier = sum((p - y) ** 2 for p, y in pairs) / n
    rows, ece = [], 0.0
    for index in range(bins):
        lo, hi = index / bins, (index + 1) / bins
        bucket = [(p, y) for p, y in pairs if lo <= p < hi or (index == bins - 1 and p == hi)]
        if not bucket: continue
        confidence = sum(p for p, _ in bucket) / len(bucket)
        accuracy = sum(y for _, y in bucket) / len(bucket)
        ece += len(bucket) / n * abs(confidence - accuracy)
        rows.append({"lower": lo, "upper": hi, "count": len(bucket), "confidence": confidence, "accuracy": accuracy, "error": abs(confidence - accuracy)})
    high = [(p, y) for p, y in pairs if p >= .8]
    return {"n_samples": n, "ece": ece, "brier_score": brier, "reliability": rows,
            "high_confidence": None if not high else {"count": len(high), "confidence": sum(p for p, _ in high)/len(high), "accuracy": sum(y for _, y in high)/len(high)}}


class ModelRegistry:
    """File registry with immutable versions and atomic production pointers."""
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = RLock()
        for state in ("production", "challenger", "archive", "rejected", "shadow"):
            (self.root / state).mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "registry.json"
        if not self.index_path.exists(): self._write_index({"models": {}, "production": None, "rollback_history": []})

    def register(self, artifact: str | Path, *, version: str, features: Iterable[str], metrics: dict[str, Any], state: str = "challenger") -> dict[str, Any]:
        if state not in {"challenger", "rejected"}: raise ValueError("new artifacts must be challenger or rejected")
        source = Path(artifact)
        if not source.is_file(): raise FileNotFoundError(source)
        record = {"version": version, "state": state, "artifact_hash": artifact_hash(source), "feature_schema_hash": schema_hash(features),
                  "features": list(features), "metrics": metrics, "created_at": datetime.now(timezone.utc).isoformat()}
        with self._lock:
            target = self.root / state / f"{version}{source.suffix or '.artifact'}"
            self._atomic_copy(source, target)
            record["artifact"] = str(target.relative_to(self.root))
            index = self._read_index(); index["models"][version] = record; self._write_index(index)
        return record

    def promote(self, version: str, policy: PromotionPolicy = PromotionPolicy()) -> PromotionDecision:
        with self._lock:
            index = self._read_index(); record = index["models"].get(version)
            if not record: raise KeyError(version)
            decision = evaluate_promotion(record["metrics"], policy)
            if decision.status != "PROMOTED":
                record["state"] = "rejected"; record["decision"] = asdict(decision); self._move(record, "rejected"); self._write_index(index); return decision
            source = self.root / record["artifact"]
            if not source.exists() or artifact_hash(source) != record["artifact_hash"]:
                return PromotionDecision("REJECTED", ["corrupt_artifact"])
            previous = index.get("production")
            if previous:
                previous_record = index["models"][previous]; self._move(previous_record, "archive"); previous_record["state"] = "archive"
            self._move(record, "production"); record["state"] = "production"; record["decision"] = asdict(decision)
            index["production"] = version; self._write_index(index); return decision

    def rollback(self, version: str) -> None:
        with self._lock:
            index = self._read_index(); target = index["models"].get(version)
            if not target or target.get("state") != "archive": raise ValueError("rollback target must be archived")
            current = index.get("production")
            if current: self._move(index["models"][current], "archive"); index["models"][current]["state"] = "archive"
            self._move(target, "production"); target["state"] = "production"; index["production"] = version
            index["rollback_history"].append({"to": version, "at": datetime.now(timezone.utc).isoformat()}); self._write_index(index)

    def load_production(self, features: Iterable[str]) -> Path:
        index = self._read_index(); version = index.get("production")
        if not version: raise FileNotFoundError("no production model")
        record = index["models"][version]
        if record["feature_schema_hash"] != schema_hash(features): raise ValueError("feature_schema_mismatch")
        path = self.root / record["artifact"]
        if not path.exists() or artifact_hash(path) != record["artifact_hash"]: raise ValueError("corrupt_artifact")
        return path

    def record_shadow(self, production_probability: float, challenger_probability: float, outcome: int | None = None, pnl_impact: float | None = None) -> None:
        path = self.root / "shadow" / "decisions.jsonl"
        row = {"at": datetime.now(timezone.utc).isoformat(), "production_probability": production_probability, "challenger_probability": challenger_probability, "disagreed": (production_probability >= .5) != (challenger_probability >= .5), "outcome": outcome, "pnl_impact": pnl_impact}
        with path.open("a", encoding="utf-8") as out: out.write(json.dumps(row) + "\n")

    def dashboard(self) -> dict[str, Any]:
        index = self._read_index(); rows = []
        shadow = self.root / "shadow" / "decisions.jsonl"
        if shadow.exists(): rows = [json.loads(line) for line in shadow.read_text(encoding="utf-8").splitlines() if line]
        completed = [row for row in rows if row.get("outcome") is not None]
        return {"current_model": index.get("production"), "latest_challenger": next((v for v, r in reversed(list(index["models"].items())) if r["state"] == "challenger"), None), "models": index["models"], "rollback_history": index["rollback_history"], "shadow": {"decisions": len(rows), "disagreements": sum(r["disagreed"] for r in rows), "pnl_impact": sum(r.get("pnl_impact") or 0 for r in rows), "calibration": calibration_metrics([r["challenger_probability"] for r in completed], [r["outcome"] for r in completed])}}

    def _move(self, record: dict[str, Any], state: str) -> None:
        old = self.root / record["artifact"]; new = self.root / state / old.name
        new.parent.mkdir(parents=True, exist_ok=True); os.replace(old, new); record["artifact"] = str(new.relative_to(self.root))
    def _atomic_copy(self, source: Path, target: Path) -> None:
        temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp"); shutil.copyfile(source, temp); os.replace(temp, target)
    def _read_index(self) -> dict[str, Any]: return json.loads(self.index_path.read_text(encoding="utf-8"))
    def _write_index(self, value: dict[str, Any]) -> None:
        temp = self.index_path.with_suffix(".tmp"); temp.write_text(json.dumps(value, indent=2), encoding="utf-8"); os.replace(temp, self.index_path)
