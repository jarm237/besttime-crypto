"""H14.2 prospective validation-design observer.

This module is intentionally append-only and side-effect narrow: it writes H14
research stream artifacts only. It must not create orders, reservations,
positions, governed evidence rows, or policy mutations.
"""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from btc_scraper.core.paths import build_repo_path
from btc_scraper.core.utils import write_atomic


H14_PROSPECTIVE_START_TIMESTAMP = "2026-08-13T08:50:07Z"
H14_DEFAULT_ROOT = build_repo_path(
    "historical-h14-prospective-validation-design-discrimination"
)
H14_ACTIONABLE_ACTIONS = {"BUY", "SELL"}


@dataclass(frozen=True)
class H14ObserverResult:
    status: str
    health: str
    prospective_analysis_id: str | None
    analysis_rows: int
    decision_rows: int
    divergence_rows: int
    duplicate_count: int
    incomplete_accounting: int


def observe_h14_prospective_analysis(
    analysis: Mapping[str, Any],
    *,
    root: str | Path | None = None,
) -> H14ObserverResult:
    """Append one post-boundary analysis into the H14.2 observer stream."""
    return H14ProspectiveObserver(root=root).observe(analysis)


class H14ProspectiveObserver:
    def __init__(self, *, root: str | Path | None = None) -> None:
        env_root = os.getenv("BTC_H14_OBSERVER_ROOT")
        self.root = Path(root or env_root or H14_DEFAULT_ROOT)
        self.data_dir = self.root / "data"
        self.reports_dir = self.root / "reports"
        self.analysis_path = self.data_dir / "h14_1_prospective_analysis_stream.jsonl"
        self.decision_path = self.data_dir / "h14_1_prospective_design_decisions.jsonl"
        self.schedule_path = self.data_dir / "h14_1_design_membership_schedules.jsonl"
        self.divergence_path = self.data_dir / "h14_2_decision_divergence_accounting.jsonl"
        self.transition_path = self.data_dir / "h14_2_mf2_membership_transitions.jsonl"
        self.checkpoint_path = self.reports_dir / "h14_2_stream_checkpoint.json"
        self.lock_path = self.data_dir / ".h14_2_observer.lock"

    def observe(self, analysis: Mapping[str, Any]) -> H14ObserverResult:
        timestamp = _analysis_timestamp(analysis)
        if timestamp is None:
            return self._result("SKIPPED_MISSING_TIMESTAMP", None, "PASS")
        if timestamp < _parse_timestamp(H14_PROSPECTIVE_START_TIMESTAMP):
            return self._result("SKIPPED_PRE_BOUNDARY", None, "PASS")

        self._ensure_files()
        with self._locked():
            schedules = self._load_schedules()
            canonical = self._canonical_record(analysis, timestamp)
            analysis_created = self._append_unique(
                self.analysis_path,
                canonical,
                key="prospective_analysis_id",
            )
            if not analysis_created:
                canonical = self._existing_row(
                    self.analysis_path,
                    "prospective_analysis_id",
                    canonical["prospective_analysis_id"],
                ) or canonical

            missing_designs = self._missing_designs(canonical["prospective_analysis_id"])
            incomplete = 1 if not analysis_created and missing_designs else 0
            for design_id in missing_designs:
                decision = self._design_decision(canonical, schedules[design_id])
                self._append_unique(
                    self.decision_path,
                    decision,
                    key="decision_hash",
                )

            if missing_designs or not self._has_divergence_row(
                canonical["prospective_analysis_id"]
            ):
                decisions = self._decisions_for(canonical["prospective_analysis_id"])
                if {"MF2", "MF4"}.issubset(decisions):
                    self._append_unique(
                        self.divergence_path,
                        self._divergence_row(canonical, decisions),
                        key="prospective_analysis_id",
                    )

            checkpoint = self._write_checkpoint(incomplete_accounting=incomplete)
            health = "DEGRADED_RECOVERED" if incomplete else "PASS"
            status = "APPENDED" if analysis_created else "NO_OP"
            return H14ObserverResult(
                status=status,
                health=health,
                prospective_analysis_id=canonical["prospective_analysis_id"],
                analysis_rows=checkpoint["analysis_stream_rows"],
                decision_rows=checkpoint["decision_stream_rows"],
                divergence_rows=checkpoint["divergence_rows"],
                duplicate_count=checkpoint["canonical_analysis_duplicates"],
                incomplete_accounting=checkpoint["incomplete_accounting"],
            )

    def _canonical_record(
        self,
        analysis: Mapping[str, Any],
        timestamp: datetime,
    ) -> dict[str, Any]:
        symbol = _normalize_symbol(analysis.get("symbol") or analysis.get("coin"))
        cycle_timestamp = _format_timestamp(timestamp)
        signal_score = analysis.get("signal_score") if isinstance(analysis.get("signal_score"), Mapping) else {}
        final_decision = (
            analysis.get("causal_decision")
            if isinstance(analysis.get("causal_decision"), Mapping)
            else {}
        )
        action = _action_from(analysis, signal_score, final_decision)
        base = {
            "prospective_analysis_id": "",
            "symbol": symbol,
            "cycle_timestamp": cycle_timestamp,
            "release_sha": str(
                analysis.get("release_sha")
                or analysis.get("deployment_id")
                or signal_score.get("deployment_id")
                or ""
            ),
            "model_version": str(
                analysis.get("model_version") or signal_score.get("model_version") or ""
            ),
            "artifact_sha256": str(
                analysis.get("artifact_sha256")
                or analysis.get("model_artifact_sha256")
                or signal_score.get("artifact_sha256")
                or signal_score.get("model_artifact_sha256")
                or ""
            ),
            "feature_schema": str(
                analysis.get("feature_schema")
                or analysis.get("feature_schema_version")
                or signal_score.get("feature_schema_version")
                or ""
            ),
            "feature_snapshot_hash": str(
                analysis.get("feature_snapshot_hash")
                or analysis.get("feature_hash")
                or signal_score.get("feature_hash")
                or ""
            ),
            "regime_snapshot_hash": _hash_value(
                analysis.get("regime_snapshot") or analysis.get("regime") or {}
            ),
            "raw_direction": _raw_direction(analysis, signal_score),
            "signal_score": _score_value(analysis, signal_score),
            "buy_posterior": _buy_posterior(analysis, signal_score, final_decision),
            "sell_posterior": _sell_posterior(analysis, signal_score, final_decision),
            "meta_confidence": _meta_confidence(analysis, signal_score, final_decision),
            "current_policy_action": action,
        }
        identity = {
            "symbol": base["symbol"],
            "cycle_timestamp": base["cycle_timestamp"],
            "signal_id": analysis.get("signal_id") or signal_score.get("signal_id"),
            "prediction_id": analysis.get("prediction_id") or signal_score.get("prediction_id"),
            "artifact_sha256": base["artifact_sha256"],
            "feature_snapshot_hash": base["feature_snapshot_hash"],
        }
        base["prospective_analysis_id"] = f"h14pa-{_sha256(identity)[:24]}"
        base["record_hash"] = _sha256(base)
        return base

    def _design_decision(
        self,
        canonical: Mapping[str, Any],
        schedule: Mapping[str, Any],
    ) -> dict[str, Any]:
        design_id = str(schedule["design_id"])
        subset = {_normalize_symbol(symbol) for symbol in schedule["current_symbol_subset"]}
        symbol_eligible = canonical["symbol"] in subset
        regime_eligible = True
        action = str(canonical.get("current_policy_action") or "HOLD").upper()
        if not symbol_eligible or not regime_eligible or action not in H14_ACTIONABLE_ACTIONS:
            shadow_action = "HOLD"
            shadow_side = None
        else:
            shadow_action = action
            shadow_side = action
        row = {
            "design_id": design_id,
            "prospective_analysis_id": canonical["prospective_analysis_id"],
            "cycle_timestamp": canonical["cycle_timestamp"],
            "symbol": canonical["symbol"],
            "membership_schedule_hash": str(
                schedule.get("prospective_membership_schedule_hash")
                or schedule.get("membership_schedule_hash")
                or ""
            ),
            "symbol_eligible": symbol_eligible,
            "regime_eligible": regime_eligible,
            "shadow_action": shadow_action,
            "shadow_side": shadow_side,
        }
        row["decision_hash"] = _sha256(row)
        return row

    def _divergence_row(
        self,
        canonical: Mapping[str, Any],
        decisions: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        mf2 = decisions["MF2"]
        mf4 = decisions["MF4"]
        mf2_action = str(mf2.get("shadow_action") or "HOLD").upper()
        mf4_action = str(mf4.get("shadow_action") or "HOLD").upper()
        mf2_actionable = mf2_action in H14_ACTIONABLE_ACTIONS
        mf4_actionable = mf4_action in H14_ACTIONABLE_ACTIONS
        if mf2_actionable and mf4_actionable:
            bucket = "SHARED_ACTIONABLE"
        elif mf2_actionable:
            bucket = "MF2_ONLY_ACTIONABLE"
        elif mf4_actionable:
            bucket = "MF4_ONLY_ACTIONABLE"
        else:
            bucket = "NEITHER_ACTIONABLE"
        row = {
            "prospective_analysis_id": canonical["prospective_analysis_id"],
            "cycle_timestamp": canonical["cycle_timestamp"],
            "symbol": canonical["symbol"],
            "bucket": bucket,
            "mf2_action": mf2_action,
            "mf4_action": mf4_action,
            "action_conflict": (
                mf2_actionable
                and mf4_actionable
                and mf2_action != mf4_action
            ),
            "membership_equal": bool(mf2.get("symbol_eligible")) == bool(mf4.get("symbol_eligible")),
            "membership_different": bool(mf2.get("symbol_eligible")) != bool(mf4.get("symbol_eligible")),
            "decision_equal": mf2_action == mf4_action,
            "decision_different": mf2_action != mf4_action,
        }
        row["divergence_hash"] = _sha256(row)
        return row

    def _load_schedules(self) -> dict[str, Mapping[str, Any]]:
        rows = _read_jsonl(self.schedule_path)
        by_design = {str(row.get("design_id")): row for row in rows}
        missing = {"MF2", "MF4"} - set(by_design)
        if missing:
            raise RuntimeError(f"h14_observer_missing_membership_schedules:{','.join(sorted(missing))}")
        return by_design

    def _ensure_files(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        for path in (
            self.analysis_path,
            self.decision_path,
            self.divergence_path,
            self.transition_path,
        ):
            path.touch(exist_ok=True)

    @contextmanager
    def _locked(self) -> Iterable[None]:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            try:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                yield
            finally:
                try:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass

    def _append_unique(self, path: Path, row: Mapping[str, Any], *, key: str) -> bool:
        wanted = str(row[key])
        for existing in _read_jsonl(path):
            if str(existing.get(key)) == wanted:
                return False
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(row), sort_keys=True, separators=(",", ":")) + "\n")
        return True

    def _existing_row(self, path: Path, key: str, value: str) -> dict[str, Any] | None:
        for row in _read_jsonl(path):
            if str(row.get(key)) == str(value):
                return row
        return None

    def _missing_designs(self, prospective_analysis_id: str) -> list[str]:
        present = {
            str(row.get("design_id"))
            for row in _read_jsonl(self.decision_path)
            if row.get("prospective_analysis_id") == prospective_analysis_id
        }
        return [design_id for design_id in ("MF2", "MF4") if design_id not in present]

    def _decisions_for(self, prospective_analysis_id: str) -> dict[str, Mapping[str, Any]]:
        result: dict[str, Mapping[str, Any]] = {}
        for row in _read_jsonl(self.decision_path):
            if row.get("prospective_analysis_id") == prospective_analysis_id:
                result[str(row.get("design_id"))] = row
        return result

    def _has_divergence_row(self, prospective_analysis_id: str) -> bool:
        return any(
            row.get("prospective_analysis_id") == prospective_analysis_id
            for row in _read_jsonl(self.divergence_path)
        )

    def _write_checkpoint(self, *, incomplete_accounting: int) -> dict[str, Any]:
        analysis_rows = _read_jsonl(self.analysis_path)
        decision_rows = _read_jsonl(self.decision_path)
        divergence_rows = _read_jsonl(self.divergence_path)
        transition_rows = _read_jsonl(self.transition_path)
        analysis_ids = [str(row.get("prospective_analysis_id")) for row in analysis_rows]
        duplicate_count = len(analysis_ids) - len(set(analysis_ids))
        pre_boundary = sum(
            1
            for row in analysis_rows
            if _parse_timestamp(str(row.get("cycle_timestamp"))) < _parse_timestamp(H14_PROSPECTIVE_START_TIMESTAMP)
        )
        bucket_counts = {
            "SHARED_ACTIONABLE": 0,
            "MF2_ONLY_ACTIONABLE": 0,
            "MF4_ONLY_ACTIONABLE": 0,
            "NEITHER_ACTIONABLE": 0,
        }
        for row in divergence_rows:
            bucket = str(row.get("bucket"))
            if bucket in bucket_counts:
                bucket_counts[bucket] += 1
        actionable_denominator = (
            bucket_counts["SHARED_ACTIONABLE"]
            + bucket_counts["MF2_ONLY_ACTIONABLE"]
            + bucket_counts["MF4_ONLY_ACTIONABLE"]
        )
        if actionable_denominator:
            overlap: float | str = bucket_counts["SHARED_ACTIONABLE"] / actionable_denominator
        else:
            overlap = "NOT_ESTIMABLE_ZERO_ACTIONABLE"

        checkpoint = {
            "checkpoint_sequence": _next_checkpoint_sequence(self.checkpoint_path),
            "checkpoint_timestamp": _format_timestamp(datetime.now(timezone.utc)),
            "analysis_stream_rows": len(analysis_rows),
            "analysis_stream_sha256": _file_sha256(self.analysis_path),
            "analysis_first_timestamp": analysis_rows[0]["cycle_timestamp"] if analysis_rows else None,
            "analysis_last_timestamp": analysis_rows[-1]["cycle_timestamp"] if analysis_rows else None,
            "decision_stream_rows": len(decision_rows),
            "decision_stream_sha256": _file_sha256(self.decision_path),
            "divergence_rows": len(divergence_rows),
            "divergence_sha256": _file_sha256(self.divergence_path),
            "mf2_transition_rows": len(transition_rows),
            "mf2_transition_sha256": _file_sha256(self.transition_path),
            "previous_checkpoint_hash": _previous_checkpoint_hash(self.checkpoint_path),
            "canonical_analysis_duplicates": duplicate_count,
            "pre_boundary_analysis": pre_boundary,
            "incomplete_accounting": incomplete_accounting,
            "observer_health": "DEGRADED" if incomplete_accounting else "PASS",
            "decision_set_overlap_rate": overlap,
            "governed_runtime_mutation": 0,
            "order_created": 0,
            "reservation_created": 0,
            "position_created": 0,
            "governed_evidence_write": 0,
            "market_replay_v2_used": "NO",
            "prospective_quality_evaluation_started": "NO",
            "policy_search": "CLOSED",
            "production_change": "BLOCKED",
            **bucket_counts,
        }
        checkpoint["checkpoint_hash"] = _sha256(checkpoint)
        write_atomic(str(self.checkpoint_path), checkpoint)
        return checkpoint

    def _result(
        self,
        status: str,
        prospective_analysis_id: str | None,
        health: str,
    ) -> H14ObserverResult:
        return H14ObserverResult(
            status=status,
            health=health,
            prospective_analysis_id=prospective_analysis_id,
            analysis_rows=0,
            decision_rows=0,
            divergence_rows=0,
            duplicate_count=0,
            incomplete_accounting=0,
        )


def _analysis_timestamp(analysis: Mapping[str, Any]) -> datetime | None:
    for key in ("cycle_timestamp", "input_end_time", "observed_at", "time", "timestamp"):
        value = analysis.get(key)
        if value:
            return _parse_timestamp(str(value))
    history = analysis.get("history")
    if isinstance(history, list) and history:
        tail = history[-1]
        if isinstance(tail, Mapping):
            for key in ("time", "timestamp"):
                value = tail.get(key)
                if value:
                    return _parse_timestamp(str(value))
    return None


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper().replace("/", "")
    if not raw:
        return ""
    return raw if raw.endswith("USDT") else f"{raw}USDT"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _hash_value(value: Any) -> str:
    return _sha256(value)


def _sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _previous_checkpoint_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload.get("checkpoint_hash")


def _next_checkpoint_sequence(path: Path) -> int:
    if not path.exists():
        return 1
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 1
    return int(payload.get("checkpoint_sequence") or 0) + 1


def _action_from(
    analysis: Mapping[str, Any],
    signal_score: Mapping[str, Any],
    final_decision: Mapping[str, Any],
) -> str:
    return str(
        final_decision.get("action")
        or signal_score.get("action")
        or analysis.get("action")
        or "HOLD"
    ).upper()


def _raw_direction(analysis: Mapping[str, Any], signal_score: Mapping[str, Any]) -> str:
    raw = signal_score.get("raw_direction") or analysis.get("raw_direction") or analysis.get("signal") or ""
    text = str(raw).upper()
    if "SELL" in text or "SHORT" in text:
        return "SELL"
    if "BUY" in text or "LONG" in text:
        return "BUY"
    return str(raw or "NEUTRAL").upper()


def _score_value(analysis: Mapping[str, Any], signal_score: Mapping[str, Any]) -> float | None:
    value = signal_score.get("score", analysis.get("signal_score_value"))
    try:
        return float(value) if value is not None else None
    except Exception:
        return None


def _meta_confidence(
    analysis: Mapping[str, Any],
    signal_score: Mapping[str, Any],
    final_decision: Mapping[str, Any],
) -> float | None:
    for value in (
        final_decision.get("meta_probability"),
        signal_score.get("meta_confidence"),
        signal_score.get("meta_probability"),
        analysis.get("meta_confidence"),
    ):
        if value is not None:
            try:
                return float(value)
            except Exception:
                continue
    return None


def _buy_posterior(
    analysis: Mapping[str, Any],
    signal_score: Mapping[str, Any],
    final_decision: Mapping[str, Any],
) -> float | None:
    for value in (
        analysis.get("buy_posterior"),
        signal_score.get("buy_posterior"),
    ):
        if value is not None:
            return float(value)
    posterior = final_decision.get("posterior_probability")
    if posterior is not None:
        return float(posterior)
    return None


def _sell_posterior(
    analysis: Mapping[str, Any],
    signal_score: Mapping[str, Any],
    final_decision: Mapping[str, Any],
) -> float | None:
    for value in (
        analysis.get("sell_posterior"),
        signal_score.get("sell_posterior"),
    ):
        if value is not None:
            return float(value)
    posterior = final_decision.get("posterior_probability")
    if posterior is not None:
        return 1.0 - float(posterior)
    return None
