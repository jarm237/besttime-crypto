#!/usr/bin/env python3
"""Run one paper canary until its evidence is safe to review for sealing.

The runner never changes or seals an evidence epoch.  It starts ``main.py`` with
the active epoch's immutable lineage, continuously checks the production
evidence chain, and stops the child in either of these cases:

* success: a production-linked paper position has closed, has exactly one
  canonical outcome, and remains idempotent through a controlled restart;
* fail closed: evidence, risk, lineage, universe, or execution integrity breaks.

Exit codes:
    0  Seal-ready conditions passed; the epoch is still ACTIVE.
    1  Configuration, startup, or child-process failure.
    2  A runtime invariant failed; the child was stopped.
    130 Interrupted by SIGINT/SIGTERM; the child was stopped.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import certifi
from pymongo import MongoClient
from pymongo.errors import PyMongoError


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.core.config import MONGODB_URI  # noqa: E402
from btc_scraper.core.runtime_pause import (  # noqa: E402
    ExternalDependencyUnavailable,
    RuntimePauseController,
    RuntimePausePolicy,
)
from btc_scraper.ml_engine.artifact_resolver import ArtifactResolver  # noqa: E402
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore  # noqa: E402


TRADE_ACTIONS = {"BUY", "SELL", "TRADE", "AUTHORIZED", "SUBMITTED", "FILLED"}
LINEAGE_FIELDS = {
    "deployment_id": "deployment_id",
    "model_version": "model_version",
    "artifact_sha256": "artifact_sha256",
    "feature_schema_version": "feature_schema_version",
}


class CanaryInvariantError(RuntimeError):
    """Raised when continuing the canary would make its cohort unsafe."""


class CanaryInterrupted(RuntimeError):
    """Raised internally when the supervisor receives a stop signal."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epoch-id", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument(
        "--evidence-path",
        type=Path,
        help="Defaults to runtime/production/<deployment>/logs/runtime_evidence.sqlite",
    )
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument(
        "--terminal-decision-grace-seconds",
        type=float,
        default=120.0,
        help="Maximum age of an eligible prediction without a terminal decision.",
    )
    parser.add_argument(
        "--restart-observation-seconds",
        type=float,
        default=90.0,
        help="Stability window after the controlled restart.",
    )
    parser.add_argument(
        "--outcome-link-max-delay-seconds",
        type=float,
        default=60.0,
        help="Maximum close-to-outcome evidence delay accepted as immediate.",
    )
    parser.add_argument(
        "--mongo-timeout-ms",
        type=int,
        default=5000,
        help="MongoDB server selection timeout; an outage fails closed.",
    )
    parser.add_argument(
        "--child-stop-timeout-seconds",
        type=float,
        default=20.0,
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Evaluate current state without starting main.py.",
    )
    parser.add_argument(
        "--record-check-result",
        action="store_true",
        help="Explicitly persist a failed check result; off by default.",
    )
    return parser


def _iso(value: Any, *, naive_is_local: bool = False) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        assumed_timezone = (
            datetime.now().astimezone().tzinfo if naive_is_local else timezone.utc
        )
        parsed = parsed.replace(tzinfo=assumed_timezone)
    return parsed.astimezone(timezone.utc)


def _artifact(row: Mapping[str, Any]) -> str:
    return str(row.get("artifact_sha256") or row.get("model_artifact_sha256") or "")


def _read_jsonl(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(paths):
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise CanaryInvariantError(
                        f"corrupt_jsonl:{path}:{line_number}"
                    ) from exc
                if isinstance(payload, dict):
                    rows.append(payload)
    return rows


def _reservation_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='reservations'"
            ).fetchone()
            if not table:
                return []
            return [dict(row) for row in connection.execute("SELECT * FROM reservations")]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise CanaryInvariantError(f"reservation_store_unavailable:{type(exc).__name__}") from exc


def _outcome_written_at(store: RuntimeEvidenceStore) -> dict[str, str]:
    return {
        str(outcome_id): str(written_at)
        for outcome_id, written_at in store._all_rows(  # noqa: SLF001
            "outcome_links", "outcome_id, written_at"
        )
    }


def _assert_lineage(
    label: str,
    row: Mapping[str, Any],
    *,
    deployment_id: str,
    model_version: str,
    artifact_sha256: str,
    feature_schema_version: str,
) -> None:
    actual = {
        "deployment_id": str(row.get("deployment_id") or ""),
        "model_version": str(row.get("model_version") or ""),
        "artifact_sha256": _artifact(row),
        "feature_schema_version": str(row.get("feature_schema_version") or ""),
    }
    expected = {
        "deployment_id": deployment_id,
        "model_version": model_version,
        "artifact_sha256": artifact_sha256,
        "feature_schema_version": feature_schema_version,
    }
    mismatches = {
        key: {"expected": expected[key], "actual": actual[key]}
        for key in LINEAGE_FIELDS
        if actual[key] != expected[key]
    }
    if mismatches:
        raise CanaryInvariantError(f"mixed_lineage:{label}:{json.dumps(mismatches, sort_keys=True)}")


def _ledger_conflicts(runtime_root: Path) -> int:
    conflicts = 0
    for path in runtime_root.rglob("order_fill_ledger.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CanaryInvariantError(f"ledger_unavailable:{path}") from exc
        conflicts += len(payload.get("conflicts") or {})
    return conflicts


def _runtime_files(runtime_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    execution_root = runtime_root / "data" / "execution"
    reservations = _reservation_rows(execution_root / "reservations.db")
    fills = _read_jsonl((execution_root / "fills" / "paper").glob("fills_*.jsonl"))
    return reservations, fills


def _mongo_client(timeout_ms: int) -> MongoClient:
    uri = MONGODB_URI or "mongodb://localhost:27017/"
    kwargs: dict[str, Any] = {"serverSelectionTimeoutMS": timeout_ms}
    if "mongodb+srv://" in uri or "mongodb.net" in uri:
        kwargs.update({"tls": True, "tlsCAFile": certifi.where()})
    client = MongoClient(uri, **kwargs)
    client.admin.command("ping")
    return client


def _risk_metrics(database: Any) -> dict[str, Any]:
    # Import lazily because risk_manager owns the application's Mongo singleton;
    # commands such as --help must not establish external connections.
    from btc_scraper.trading.risk_manager import calculate_risk_metrics

    trades = list(database["closed_positions"].find({}, {"_id": 0}).sort("_id", 1))
    return calculate_risk_metrics(trades_cache=trades)


def _validate_static_invariants(
    *,
    store: RuntimeEvidenceStore,
    rows: Mapping[str, list[dict[str, Any]]],
    epoch: Any,
    reservations: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    mongo_positions: list[dict[str, Any]],
    mongo_closed: list[dict[str, Any]],
    risk: Mapping[str, Any],
    runtime_root: Path,
    terminal_decision_grace: float,
    read_only: bool = False,
    pause_controller: RuntimePauseController | None = None,
) -> dict[str, Any]:
    health = store.health(quarantine_corrupt=not read_only)
    if health.get("status") != "healthy" or health.get("severity") != "HEALTHY":
        raise CanaryInvariantError(f"evidence_health:{json.dumps(health, sort_keys=True)}")
    if str(risk.get("status")) != "HEALTHY" or bool(risk.get("blocked")):
        raise CanaryInvariantError(f"risk_health:{json.dumps(dict(risk), sort_keys=True)}")
    if _ledger_conflicts(runtime_root):
        raise CanaryInvariantError("semantic_conflict:order_fill_ledger")

    predictions = rows["predictions"]
    eligible_predictions = [row for row in predictions if bool(row.get("evidence_eligible"))]
    universe = set(epoch.analysis_universe)
    outside = [
        row.get("prediction_id")
        for row in eligible_predictions
        if str(row.get("symbol") or "").removesuffix("USDT").upper() not in universe
    ]
    if outside:
        raise CanaryInvariantError(f"eligible_symbol_outside_universe:{outside}")

    activated_at = _iso(epoch.activated_at)
    preactivation = [
        row.get("prediction_id")
        for row in eligible_predictions
        if _iso(row.get("timestamp") or row.get("predicted_at")) < activated_at
    ]
    if preactivation:
        raise CanaryInvariantError(f"preactivation_prediction_eligible:{preactivation}")

    decision_prediction_ids = {
        str(row.get("prediction_id"))
        for row in rows["final_decisions"]
        if row.get("prediction_id")
    }
    now = datetime.now(timezone.utc)
    def effective_age(timestamp: Any, *, naive_is_local: bool = False) -> float:
        started = _iso(timestamp, naive_is_local=naive_is_local)
        elapsed = (now - started).total_seconds()
        if pause_controller is not None:
            elapsed -= pause_controller.excluded_seconds_between(started, now)
        return max(0.0, elapsed)

    stale_missing_decisions = [
        str(row.get("prediction_id"))
        for row in eligible_predictions
        if (
            str(row.get("prediction_id")) not in decision_prediction_ids
            and effective_age(row.get("timestamp") or row.get("predicted_at"))
            >= terminal_decision_grace
        )
    ]
    if stale_missing_decisions:
        raise CanaryInvariantError(
            f"missing_final_decision:{stale_missing_decisions}"
        )

    trade_decisions = {
        str(row.get("prediction_id")): row
        for row in rows["final_decisions"]
        if (
            row.get("prediction_id")
            and str(row.get("action") or "").upper() in {"BUY", "SELL"}
            and str(row.get("terminal_status") or "").upper() == "TRADE"
            and bool(row.get("eligible"))
        )
    }
    accepted_trade_ids = {
        str(row.get("prediction_id"))
        for row in reservations
        if row.get("prediction_id")
    }
    rejected_trade_ids = {
        str(row.get("prediction_id"))
        for row in rows.get("audit_events", [])
        if (
            str(row.get("event_type") or "") == "execution_quarantined"
            and row.get("prediction_id")
        )
    }
    prediction_times = {
        str(row.get("prediction_id")): _iso(
            row.get("timestamp") or row.get("predicted_at")
        )
        for row in eligible_predictions
        if row.get("prediction_id")
    }
    unexecuted_trade_ids = set(trade_decisions) - accepted_trade_ids
    stale_unexecuted_trade_ids = sorted(
        prediction_id
        for prediction_id in unexecuted_trade_ids
        if (
            prediction_id not in prediction_times
            or effective_age(prediction_times[prediction_id]) >= terminal_decision_grace
        )
    )
    if stale_unexecuted_trade_ids:
        raise CanaryInvariantError(
            "trade_execution_acceptance_gate:"
            + json.dumps({
                "trade_decisions": len(trade_decisions),
                "execution_accepted": len(accepted_trade_ids & set(trade_decisions)),
                "execution_rejected": len(rejected_trade_ids & set(trade_decisions)),
                "unexecuted_trade_decisions": stale_unexecuted_trade_ids,
            }, sort_keys=True)
        )

    decisions_by_prediction = {
        str(row.get("prediction_id")): row
        for row in rows["final_decisions"]
        if row.get("prediction_id")
    }
    outcomes_by_prediction = {
        str(row.get("prediction_id")): row
        for row in rows["outcomes"]
        if row.get("prediction_id")
    }
    stale_closed_without_outcome: list[str] = []
    for closed in mongo_closed:
        prediction_id = str(closed.get("prediction_id") or "")
        if not prediction_id or prediction_id in outcomes_by_prediction:
            continue
        closed_at = (
            closed.get("closed_at")
            or closed.get("exit_time")
            or closed.get("close_time")
        )
        try:
            is_stale = (
                closed_at is None
                or effective_age(closed_at, naive_is_local=True)
                >= terminal_decision_grace
            )
        except (TypeError, ValueError):
            is_stale = True
        if is_stale:
            stale_closed_without_outcome.append(prediction_id)
    if stale_closed_without_outcome:
        raise CanaryInvariantError(
            "closed_position_outcome_gate:"
            + json.dumps(sorted(stale_closed_without_outcome))
        )
    for closed in mongo_closed:
        prediction_id = str(closed.get("prediction_id") or "")
        if not prediction_id:
            continue
        decision = decisions_by_prediction.get(prediction_id)
        if (
            decision is None
            or str(decision.get("action") or "").upper() not in {"BUY", "SELL"}
            or str(decision.get("terminal_status") or "").upper() != "TRADE"
            or not bool(decision.get("eligible"))
        ):
            raise CanaryInvariantError(
                f"execution_with_non_executable_decision:{prediction_id}"
            )
        chain_rows = [
            row for row in reservations + fills + mongo_positions + [closed]
            if str(row.get("prediction_id") or "") == prediction_id
        ]
        outcome = outcomes_by_prediction.get(prediction_id)
        if outcome is not None:
            chain_rows.append(outcome)
        expected_cycle = str(
            next(
                (
                    prediction.get("cycle_id")
                    for prediction in eligible_predictions
                    if str(prediction.get("prediction_id")) == prediction_id
                ),
                "",
            )
            or ""
        )
        if (
            not expected_cycle
            or any(str(row.get("cycle_id") or "") != expected_cycle for row in chain_rows)
        ):
            raise CanaryInvariantError(
                f"mixed_lineage:cycle_id:{prediction_id}"
            )
        if any(
            str(row.get("paper_run_id") or "") != epoch.deployment_id
            for row in chain_rows
        ):
            raise CanaryInvariantError(
                f"paper_run_lineage_mismatch:{prediction_id}"
            )

    failed_risk_predictions = {
        str(row.get("prediction_id"))
        for row in rows["final_decisions"]
        if bool(row.get("risk_blocked")) or str(row.get("risk_status") or "").upper() != "HEALTHY"
    }
    semantic_risk_conflicts = [
        str(row.get("prediction_id"))
        for row in rows["final_decisions"]
        if (
            bool(row.get("evidence_eligible"))
            and (
                bool(row.get("risk_blocked"))
                or str(row.get("risk_status") or "").upper() != "HEALTHY"
            )
            and str(row.get("action") or "").upper() != "BLOCK_ENTRY"
        )
    ]
    if semantic_risk_conflicts:
        raise CanaryInvariantError(
            f"semantic_conflict:risk_failure_not_block_entry:{semantic_risk_conflicts}"
        )

    entered_prediction_ids = {
        str(row.get("prediction_id"))
        for row in reservations + fills + mongo_positions + mongo_closed + rows["outcomes"]
        if row.get("prediction_id")
    }
    unsafe_entries = sorted(failed_risk_predictions & entered_prediction_ids)
    if unsafe_entries:
        raise CanaryInvariantError(f"risk_failure_created_entry:{unsafe_entries}")
    eligible_risk_failures = sorted(
        failed_risk_predictions
        & {
            str(row.get("prediction_id"))
            for row in rows["final_decisions"]
            if bool(row.get("evidence_eligible"))
        }
    )
    if eligible_risk_failures:
        raise CanaryInvariantError(
            f"historical_risk_health_not_maintained:{eligible_risk_failures}"
        )

    return {
        "health": health,
        "risk": dict(risk),
        "eligible_predictions": len(eligible_predictions),
        "eligible_symbols": dict(Counter(str(row.get("symbol")) for row in eligible_predictions)),
        "trade_decisions": len(trade_decisions),
        "execution_accepted": len(accepted_trade_ids & set(trade_decisions)),
        "execution_rejected": len(rejected_trade_ids & set(trade_decisions)),
        "unexecuted_trade_decisions": len(unexecuted_trade_ids),
        "closed_positions_missing_outcome": 0,
    }


def _candidate_for_closed_trade(
    *,
    rows: Mapping[str, list[dict[str, Any]]],
    epoch: Any,
    deployment_id: str,
    reservations: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    mongo_positions: list[dict[str, Any]],
    mongo_closed: list[dict[str, Any]],
    outcome_written_at: Mapping[str, str],
    max_outcome_delay: float,
) -> dict[str, Any] | None:
    predictions = {str(row.get("prediction_id")): row for row in rows["predictions"]}
    decisions = {
        str(row.get("prediction_id")): row
        for row in rows["final_decisions"]
        if row.get("prediction_id")
    }
    outcomes_by_position: dict[str, list[dict[str, Any]]] = {}
    for outcome in rows["outcomes"]:
        outcomes_by_position.setdefault(str(outcome.get("position_id") or ""), []).append(outcome)

    expected = {
        "deployment_id": deployment_id,
        "model_version": str(epoch.model_version),
        "artifact_sha256": str(epoch.artifact_sha256),
        "feature_schema_version": str(epoch.feature_schema_version),
    }
    for closed in mongo_closed:
        position_id = str(closed.get("id") or closed.get("position_id") or "")
        prediction_id = str(closed.get("prediction_id") or "")
        if not position_id or not prediction_id:
            continue
        if (
            str(closed.get("deployment_id") or "") != deployment_id
            or str(closed.get("paper_run_id") or "") != deployment_id
            or str(closed.get("trade_origin") or "") != "paper_mode"
            or str(closed.get("execution_mode") or "") != "paper"
            or str(closed.get("fill_source") or "") != "real_paper"
        ):
            continue

        prediction = predictions.get(prediction_id)
        decision = decisions.get(prediction_id)
        if prediction is None or decision is None:
            raise CanaryInvariantError(f"closed_trade_missing_prediction_or_decision:{position_id}")
        if str(prediction.get("epoch_id") or "") != str(epoch.epoch_id):
            raise CanaryInvariantError(f"mixed_epoch:{position_id}")
        if not bool(prediction.get("evidence_eligible")) or not bool(decision.get("evidence_eligible")):
            raise CanaryInvariantError(f"ineligible_closed_trade:{position_id}")
        if str(decision.get("action") or "").upper() not in TRADE_ACTIONS:
            raise CanaryInvariantError(f"closed_trade_without_trade_decision:{position_id}")
        if bool(decision.get("risk_blocked")) or str(decision.get("risk_status") or "") != "HEALTHY":
            raise CanaryInvariantError(f"closed_trade_with_failed_risk:{position_id}")
        if str(decision.get("prediction_id") or "") != prediction_id:
            raise CanaryInvariantError(f"decision_prediction_mismatch:{position_id}")

        for label, row in (
            ("prediction", prediction),
            ("decision", decision),
            ("closed_position", closed),
        ):
            _assert_lineage(label, row, **expected)

        matching_positions = [
            row for row in mongo_positions
            if str(row.get("id") or "") == position_id and str(row.get("status") or "") == "closed"
        ]
        matching_closed = [
            row for row in mongo_closed
            if str(row.get("id") or row.get("position_id") or "") == position_id
        ]
        if len(matching_positions) != 1 or len(matching_closed) != 1:
            raise CanaryInvariantError(
                f"position_close_cardinality:{position_id}:positions={len(matching_positions)}:"
                f"closed={len(matching_closed)}"
            )

        matching_reservations = [
            row for row in reservations
            if str(row.get("prediction_id") or "") == prediction_id
            and str(row.get("deployment_id") or "") == deployment_id
        ]
        if len(matching_reservations) != 1:
            raise CanaryInvariantError(
                f"reservation_cardinality:{position_id}:{len(matching_reservations)}"
            )
        reservation = matching_reservations[0]
        if str(reservation.get("status") or "").lower() != "committed":
            raise CanaryInvariantError(f"reservation_not_committed:{position_id}")
        _assert_lineage("reservation", reservation, **expected)

        reservation_id = str(reservation.get("reservation_id") or "")
        matching_fills = [
            row for row in fills
            if str(row.get("prediction_id") or "") == prediction_id
            and str(row.get("reservation_id") or "") == reservation_id
            and str(row.get("status") or "") == "FILLED"
        ]
        if len(matching_fills) != 1:
            raise CanaryInvariantError(f"fill_cardinality:{position_id}:{len(matching_fills)}")
        fill = matching_fills[0]
        if (
            str(fill.get("execution_mode") or "") != "paper"
            or str(fill.get("fill_source") or "") != "real_paper"
            or str(fill.get("paper_run_id") or "") != deployment_id
            or not bool(fill.get("evidence_eligible"))
            or not list(fill.get("fills") or [])
        ):
            raise CanaryInvariantError(f"invalid_paper_fill:{position_id}")
        _assert_lineage("fill", fill, **expected)

        for label, row in (("position", matching_positions[0]),):
            _assert_lineage(label, row, **expected)
        chain_fields = ("prediction_id", "reservation_id", "idempotency_key", "client_order_id")
        for field in chain_fields:
            expected_value = str(closed.get(field) or "")
            if not expected_value:
                raise CanaryInvariantError(f"missing_chain_field:{position_id}:{field}")
            for label, row in (
                ("position", matching_positions[0]),
                ("reservation", reservation),
                ("fill", fill),
            ):
                if str(row.get(field) or "") != expected_value:
                    raise CanaryInvariantError(
                        f"chain_mismatch:{position_id}:{field}:{label}"
                    )

        outcomes = outcomes_by_position.get(position_id, [])
        if len(outcomes) != 1:
            if len(outcomes) > 1:
                raise CanaryInvariantError(f"duplicate_outcome:{position_id}:{len(outcomes)}")
            continue
        outcome = outcomes[0]
        if (
            str(outcome.get("prediction_id") or "") != prediction_id
            or int(outcome.get("outcome_revision") or 0) != 1
        ):
            raise CanaryInvariantError(f"invalid_outcome_link:{position_id}")
        _assert_lineage("outcome", outcome, **expected)

        outcome_id = str(outcome.get("outcome_id") or "")
        written_at = outcome_written_at.get(outcome_id)
        closed_at = closed.get("closed_at")
        if not written_at or not closed_at:
            raise CanaryInvariantError(f"outcome_timing_missing:{position_id}")
        # position_tracker currently emits a naive local-time closed_at, while
        # evidence written_at is timezone-aware UTC.
        delay = (
            _iso(written_at) - _iso(closed_at, naive_is_local=True)
        ).total_seconds()
        if delay < -1.0 or delay > max_outcome_delay:
            raise CanaryInvariantError(f"outcome_not_immediate:{position_id}:{delay:.3f}s")

        return {
            "position_id": position_id,
            "prediction_id": prediction_id,
            "decision_id": str(decision.get("decision_id") or ""),
            "reservation_id": reservation_id,
            "fill_id": str((fill.get("fills") or [{}])[0].get("fill_id") or ""),
            "outcome_id": outcome_id,
            "outcome_revision": 1,
            "closed_at": str(closed_at),
            "outcome_delay_seconds": round(delay, 6),
        }
    return None


def _evaluate(
    *,
    store: RuntimeEvidenceStore,
    epoch: Any,
    deployment_id: str,
    runtime_root: Path,
    mongo_database: Any,
    max_outcome_delay: float,
    terminal_decision_grace: float,
    read_only: bool = False,
    pause_controller: RuntimePauseController | None = None,
) -> dict[str, Any]:
    rows = store.shadow_evidence_rows()
    reservations, fills = _runtime_files(runtime_root)
    try:
        mongo_database.client.admin.command("ping")
        mongo_positions = list(
            mongo_database["positions"].find({"deployment_id": deployment_id}, {"_id": 0})
        )
        mongo_closed = list(
            mongo_database["closed_positions"].find({"deployment_id": deployment_id}, {"_id": 0})
        )
        risk = _risk_metrics(mongo_database)
    except PyMongoError as exc:
        raise ExternalDependencyUnavailable(
            "RUNTIME_PAUSED_MONGODB_UNAVAILABLE",
            f"{type(exc).__name__}:{exc}",
        ) from exc
    summary = _validate_static_invariants(
        store=store,
        rows=rows,
        epoch=epoch,
        reservations=reservations,
        fills=fills,
        mongo_positions=mongo_positions,
        mongo_closed=mongo_closed,
        risk=risk,
        runtime_root=runtime_root,
        terminal_decision_grace=terminal_decision_grace,
        read_only=read_only,
        pause_controller=pause_controller,
    )
    candidate = _candidate_for_closed_trade(
        rows=rows,
        epoch=epoch,
        deployment_id=deployment_id,
        reservations=reservations,
        fills=fills,
        mongo_positions=mongo_positions,
        mongo_closed=mongo_closed,
        outcome_written_at=_outcome_written_at(store),
        max_outcome_delay=max_outcome_delay,
    )
    summary.update({
        "predictions": len(rows["predictions"]),
        "decisions": len(rows["final_decisions"]),
        "outcomes": len(rows["outcomes"]),
        "reservations": len(reservations),
        "paper_fills": len(fills),
        "mongo_positions": len(mongo_positions),
        "mongo_closed_positions": len(mongo_closed),
        "candidate": candidate,
    })
    return summary


def _child_environment(epoch: Any, deployment_id: str) -> dict[str, str]:
    universe = ",".join(epoch.analysis_universe)
    environment = os.environ.copy()
    environment.update({
        "BTC_RUNTIME_ENVIRONMENT": "production",
        "BTC_DEPLOYMENT_ID": deployment_id,
        "BTC_PAPER_RUN_ID": deployment_id,
        "BTC_ANALYSIS_UNIVERSE": universe,
        "AUTO_TRADE_COINS": universe,
        "LIVE_TRADING_ENABLED": "false",
        "AUTO_TRADE_DRY_RUN": "true",
        "AUTO_TRADE_BINANCE_TESTNET": "true",
        "BTC_EVIDENCE_ELIGIBLE": "true",
    })
    return environment


def _start_child(environment: Mapping[str, str]) -> subprocess.Popen[Any]:
    print("[runner] starting main.py", flush=True)
    return subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "main.py")],
        cwd=REPO_ROOT,
        env=dict(environment),
        start_new_session=True,
    )


def _stop_child(child: subprocess.Popen[Any] | None, timeout: float) -> None:
    if child is None or child.poll() is not None:
        return
    print(f"[runner] stopping child pid={child.pid}", flush=True)
    try:
        os.killpg(child.pid, signal.SIGTERM)
        child.wait(timeout=timeout)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        print(f"[runner] child did not stop in {timeout}s; sending SIGKILL", flush=True)
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=5)


def _assert_epoch_and_code(store: RuntimeEvidenceStore, epoch_id: str, deployment_id: str) -> Any:
    epoch = store.get_evidence_epoch(epoch_id)
    if epoch is None:
        raise CanaryInvariantError(f"epoch_not_found:{epoch_id}")
    if epoch.status != "ACTIVE":
        raise CanaryInvariantError(f"epoch_not_active:{epoch.status}")
    if epoch.deployment_id != deployment_id:
        raise CanaryInvariantError(
            f"epoch_deployment_mismatch:{epoch.deployment_id}:{deployment_id}"
        )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if head != epoch.code_commit_sha:
        raise CanaryInvariantError(f"code_commit_mismatch:{head}:{epoch.code_commit_sha}")
    resolver = ArtifactResolver()
    matching_artifact = False
    for model_name in resolver.config:
        resolved = resolver.resolve(model_name, require_metadata=True)
        if resolved.healthy and str(resolved.sha256 or "") == epoch.artifact_sha256:
            matching_artifact = True
            break
    if not matching_artifact:
        raise CanaryInvariantError(
            f"model_artifact_hash_mismatch:{epoch.artifact_sha256}"
        )
    return epoch


def _print_state(phase: str, state: Mapping[str, Any]) -> None:
    payload = {
        "phase": phase,
        "predictions": state["predictions"],
        "decisions": state["decisions"],
        "outcomes": state["outcomes"],
        "reservations": state["reservations"],
        "paper_fills": state["paper_fills"],
        "mongo_positions": state["mongo_positions"],
        "mongo_closed_positions": state["mongo_closed_positions"],
        "risk_status": state["risk"].get("status"),
        "evidence_health": state["health"].get("severity"),
        "candidate": state["candidate"],
        "trade_decisions": state.get("trade_decisions", 0),
        "execution_accepted": state.get("execution_accepted", 0),
        "execution_rejected": state.get("execution_rejected", 0),
        "unexecuted_trade_decisions": state.get("unexecuted_trade_decisions", 0),
    }
    print(f"[runner] {json.dumps(payload, sort_keys=True)}", flush=True)


def _record_seal_blocked(
    store: RuntimeEvidenceStore,
    epoch: Any,
    *,
    epoch_id: str,
    deployment_id: str,
    reason: str,
) -> None:
    """Persist a blocked result only with registry-derived epoch lineage."""
    if epoch is None:
        raise RuntimeError("epoch lineage unavailable")
    store.append_audit_event({
        "event_type": "seal_blocked",
        "epoch_id": epoch_id,
        "deployment_id": deployment_id,
        "reason": reason,
        "reason_code": "EPOCH_NOT_SEALABLE",
        "runner_state": "SEAL_BLOCKED",
        "paper_run_id": epoch.deployment_id,
        "model_version": epoch.model_version,
        "artifact_sha256": epoch.artifact_sha256,
        "feature_schema_version": epoch.feature_schema_version,
        "analysis_universe": list(epoch.analysis_universe),
        "analysis_universe_hash": epoch.analysis_universe_hash,
        "activated_at": epoch.activated_at,
    })


def main() -> int:
    args = _parser().parse_args()
    if args.poll_seconds <= 0 or args.restart_observation_seconds < 0:
        print("poll/restart observation values must be non-negative", file=sys.stderr)
        return 1

    evidence_path = args.evidence_path or (
        REPO_ROOT / "runtime" / "production" / args.deployment_id
        / "logs" / "runtime_evidence.sqlite"
    )
    runtime_root = evidence_path.resolve().parents[1]
    store = RuntimeEvidenceStore(evidence_path)
    child: subprocess.Popen[Any] | None = None
    mongo: MongoClient | None = None
    pause_controller: RuntimePauseController | None = None
    interrupted = False

    def request_stop(signum: int, _frame: Any) -> None:
        nonlocal interrupted
        interrupted = True
        print(f"[runner] received signal {signum}", flush=True)

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        epoch = _assert_epoch_and_code(store, args.epoch_id, args.deployment_id)
        environment = _child_environment(epoch, args.deployment_id)
        mongo = _mongo_client(args.mongo_timeout_ms)
        database = mongo["besttime_crypto"]

        pause_controller = RuntimePauseController(
            runtime_root / "state" / "canary_runner",
            policy=RuntimePausePolicy.from_mapping(
                getattr(epoch, "runtime_pause_policy", None)
            ),
        )

        def evaluate_with_recovery(*, read_only: bool = False) -> dict[str, Any]:
            nonlocal child, epoch
            while not interrupted:
                clock_gap = pause_controller.heartbeat()
                if (
                    clock_gap
                    > pause_controller.policy.maximum_clock_gap_before_recovery_seconds
                ):
                    _stop_child(child, args.child_stop_timeout_seconds)
                    child = None
                try:
                    epoch = _assert_epoch_and_code(
                        store, args.epoch_id, args.deployment_id
                    )
                    state = _evaluate(
                        store=store,
                        epoch=epoch,
                        deployment_id=args.deployment_id,
                        runtime_root=runtime_root,
                        mongo_database=database,
                        max_outcome_delay=args.outcome_link_max_delay_seconds,
                        terminal_decision_grace=args.terminal_decision_grace_seconds,
                        read_only=read_only,
                        pause_controller=pause_controller,
                    )
                except ExternalDependencyUnavailable as exc:
                    pause_controller.pause(
                        exc.reason_code,
                        detail=exc.detail,
                        context={
                            "epoch_id": args.epoch_id,
                            "deployment_id": args.deployment_id,
                        },
                    )
                    _stop_child(child, args.child_stop_timeout_seconds)
                    child = None
                    print(
                        f"[runner] PAUSED_EXTERNAL {exc}; epoch remains ACTIVE",
                        file=sys.stderr,
                        flush=True,
                    )
                    if read_only:
                        raise
                    time.sleep(pause_controller.recovery_probe_delay())
                    continue
                if pause_controller.runtime_state == "STARTING":
                    pause_controller.mark_running()
                elif pause_controller.is_paused:
                    if not pause_controller.observe_recovery_probe(
                        True,
                        detail="epoch_artifact_evidence_mongodb_preflight_healthy",
                    ):
                        time.sleep(pause_controller.recovery_probe_delay())
                        continue
                    if child is None and not read_only:
                        child = _start_child(environment)
                return state
            raise CanaryInterrupted

        initial = evaluate_with_recovery(read_only=args.check_only)
        _print_state("preflight", initial)
        if args.check_only:
            return 0 if initial["candidate"] else 1

        if child is None:
            child = _start_child(environment)
        phase = "waiting_for_closed_trade"
        last_signature: tuple[Any, ...] | None = None
        candidate: dict[str, Any] | None = None
        while not interrupted:
            state = evaluate_with_recovery()
            if child.poll() is not None:
                print(f"[runner] child exited unexpectedly rc={child.returncode}", file=sys.stderr)
                return 1
            signature = (
                state["predictions"], state["decisions"], state["outcomes"],
                state["reservations"], state["paper_fills"],
                state["mongo_positions"], state["mongo_closed_positions"],
                (state["candidate"] or {}).get("outcome_id"),
            )
            if signature != last_signature:
                _print_state(phase, state)
                last_signature = signature
            if state["candidate"]:
                candidate = dict(state["candidate"])
                break
            time.sleep(args.poll_seconds)

        if interrupted:
            return 130
        assert candidate is not None

        _stop_child(child, args.child_stop_timeout_seconds)
        child = _start_child(environment)
        phase = "restart_stability"
        stable_until = time.monotonic() + args.restart_observation_seconds
        while not interrupted and time.monotonic() < stable_until:
            state = evaluate_with_recovery()
            if child.poll() is not None:
                print(f"[runner] restart child exited unexpectedly rc={child.returncode}", file=sys.stderr)
                return 1
            current = state.get("candidate")
            if not current or any(
                current.get(field) != candidate.get(field)
                for field in ("position_id", "prediction_id", "reservation_id", "outcome_id")
            ):
                raise CanaryInvariantError("restart_changed_canonical_lifecycle")
            signature = (
                state["predictions"], state["decisions"], state["outcomes"],
                state["reservations"], state["paper_fills"],
                state["mongo_positions"], state["mongo_closed_positions"],
                current.get("outcome_id"),
            )
            if signature != last_signature:
                _print_state(phase, state)
                last_signature = signature
            time.sleep(args.poll_seconds)

        if interrupted:
            return 130
        final_state = evaluate_with_recovery()
        _print_state("seal_ready", final_state)
        print(
            "[runner] SEAL_READY "
            + json.dumps(final_state["candidate"], sort_keys=True),
            flush=True,
        )
        return 0
    except CanaryInterrupted:
        return 130
    except ExternalDependencyUnavailable as exc:
        print(
            f"[runner] PAUSED_EXTERNAL {exc}; epoch remains ACTIVE",
            file=sys.stderr,
            flush=True,
        )
        return 3
    except CanaryInvariantError as exc:
        try:
            if not args.check_only or args.record_check_result:
                _record_seal_blocked(
                    store,
                    store.get_evidence_epoch(args.epoch_id),
                    epoch_id=args.epoch_id,
                    deployment_id=args.deployment_id,
                    reason=str(exc),
                )
        except Exception:
            pass
        print(f"[runner] SEAL_BLOCKED {exc}", file=sys.stderr, flush=True)
        return 2
    except Exception as exc:
        print(f"[runner] FAILED {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        _stop_child(child, args.child_stop_timeout_seconds)
        if mongo is not None:
            mongo.close()


if __name__ == "__main__":
    raise SystemExit(main())
