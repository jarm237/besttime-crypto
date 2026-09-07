"""P8 — Economic Effectiveness Evaluation Extractor.

Extracts closed trade economics and funnel metrics from runtime evidence and
reservation databases.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from btc_scraper.ml_engine.p8_governance import (
    ABSOLUTE_USD_TOLERANCE,
    GovernanceError,
    P8CostPolicy,
    _load_active_epoch_rows,
    _load_raw_partition_records,
    calculate_store_manifest_hash,
)
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
from btc_scraper.ml_engine.runtime_outcome_linker import link_runtime_outcomes

ACTIVE_SYMBOLS = {"BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"}
LEGACY_SYMBOLS = {"BTC", "ETH", "BNB"}
MC5_SYMBOLS = {"DOGE", "IOTA", "NEAR", "SOL", "TRX", "ZEC"}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            val_str = str(value)
            if val_str.endswith("Z"):
                val_str = val_str[:-1] + "+00:00"
            return datetime.fromisoformat(val_str)
        except ValueError:
            pass
    return None


def extract_closed_trades(
    evidence_store: RuntimeEvidenceStore,
    reservation_db_path: Path | str | None = None,
    *,
    target_epoch_id: str | None = None,
    require_evidence_eligible: bool = True,
    include_rejections: bool = False,
    cost_policy: P8CostPolicy = P8CostPolicy.V1_PAPER_ROUNDTRIP_FEE,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
    """Query evidence store partitions and link outcomes to evaluate economics."""
    if reservation_db_path is None:
        from btc_scraper.core.paths import get_runtime_paths
        reservation_db_path = get_runtime_paths().reservation_db_path
    reservation_db_path = Path(reservation_db_path)

    rejection_counts: dict[str, int] = {
        "missing_prediction": 0,
        "missing_decision": 0,
        "missing_outcome": 0,
        "eligibility_failed": 0,
        "prediction_id_mismatch": 0,
        "epoch_mismatch": 0,
        "deployment_mismatch": 0,
        "paper_run_mismatch": 0,
        "duplicate_conflict": 0,
        "test_trade_excluded": 0,
    }
    rejection_reasons: list[str] = []

    def _add_rejection(reason_code: str, sample_id: str):
        if len(rejection_reasons) < 50:
            rejection_reasons.append(f"{reason_code}:{sample_id}")

    # 1. Resolve active epoch if in strict mode and not explicitly provided
    active_epoch = None
    if require_evidence_eligible:
        try:
            active_epoch = evidence_store.get_active_evidence_epoch()
        except Exception as exc:
            if target_epoch_id is not None:
                raise GovernanceError(f"Failed to resolve active evidence epoch in strict mode: {exc}") from exc
            return ([], {"counts": rejection_counts, "reasons": [str(exc)]}) if include_rejections else []

        if active_epoch is None or active_epoch.status != "ACTIVE":
            err = "No ACTIVE evidence epoch found in evidence store"
            if target_epoch_id is not None:
                raise GovernanceError(err)
            return ([], {"counts": rejection_counts, "reasons": [err]}) if include_rejections else []

        if target_epoch_id is not None and active_epoch.epoch_id != target_epoch_id:
            err = f"Active epoch ID mismatch: store has {active_epoch.epoch_id}, target is {target_epoch_id}"
            raise GovernanceError(err)

    resolved_epoch_id = str(target_epoch_id or (active_epoch.epoch_id if active_epoch else ""))
    resolved_deployment_id = str(active_epoch.deployment_id if active_epoch else "")
    resolved_paper_run_id = str(active_epoch.paper_run_id if active_epoch else "")

    if require_evidence_eligible and (not resolved_epoch_id or not resolved_deployment_id or not resolved_paper_run_id):
        err = f"Incomplete target contract: epoch={resolved_epoch_id}, deployment={resolved_deployment_id}, paper_run={resolved_paper_run_id}"
        raise GovernanceError(err)

    # 2. Raw Partition Verification (check raw records before shadow_evidence_rows deduplication)
    raw_records = _load_raw_partition_records(evidence_store.path.parent)
    seen_payloads: dict[tuple[str, str], str] = {}
    for r in raw_records:
        rec_id = str(r.get("prediction_id") or r.get("decision_id") or r.get("position_id") or r.get("id") or "")
        tbl = r.get("_source_table", "")
        stored_hash = str(r.get("payload_sha256") or "")
        payload_text = str(r.get("payload") or "")

        if stored_hash and payload_text:
            key = (tbl, rec_id)
            if key in seen_payloads and seen_payloads[key] != stored_hash:
                rejection_counts["duplicate_conflict"] += 1
                _add_rejection("DUPLICATE_PAYLOAD_CONFLICT", f"{tbl}:{rec_id}")
            seen_payloads[key] = stored_hash

    # 3. Fetch raw rows from store
    rows_data = evidence_store.shadow_evidence_rows()
    predictions = rows_data.get("predictions", [])
    decisions = rows_data.get("final_decisions", [])
    outcomes = rows_data.get("outcomes", [])

    # Index decisions and predictions
    dec_map = {str(d["prediction_id"]): d for d in decisions if d.get("prediction_id")}
    pred_map = {str(p["prediction_id"]): p for p in predictions if p.get("prediction_id")}

    # Load reservations
    res_map = {}
    if reservation_db_path.exists():
        try:
            conn = sqlite3.connect(f"file:{reservation_db_path.resolve().as_posix()}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM reservations")
            for r in cursor.fetchall():
                d_id = r["entry_decision_id"]
                if d_id:
                    res_map[str(d_id)] = dict(r)
            conn.close()
        except Exception as exc:
            if require_evidence_eligible:
                raise GovernanceError(f"Failed to query reservation store at {reservation_db_path}: {exc}") from exc

    # 4. Link outcomes using canonical outcome linker
    report = link_runtime_outcomes(predictions, outcomes)
    closed_trades = []
    
    # Handle highest revision outcomes cleanly
    outcome_map: dict[str, dict[str, Any]] = {}
    for o in outcomes:
        pos_id = str(o.get("position_id") or "")
        if not pos_id:
            continue
        rev = int(o.get("outcome_revision") or 1)
        if pos_id not in outcome_map or rev > int(outcome_map[pos_id].get("outcome_revision") or 1):
            outcome_map[pos_id] = o

    for sample in report.samples:
        symbol = str(sample.symbol or "").upper()
        base_symbol = symbol.split("/")[0].split("USDT")[0]
        if base_symbol not in ACTIVE_SYMBOLS:
            continue

        pred = pred_map.get(sample.prediction_id, {})
        dec = dec_map.get(sample.prediction_id, {})
        outcome = outcome_map.get(sample.position_id, {})

        if not pred:
            rejection_counts["missing_prediction"] += 1
            _add_rejection("MISSING_PREDICTION", sample.prediction_id)
            continue
        if not dec:
            rejection_counts["missing_decision"] += 1
            _add_rejection("MISSING_DECISION", sample.prediction_id)
            continue
        if not outcome:
            rejection_counts["missing_outcome"] += 1
            _add_rejection("MISSING_OUTCOME", sample.position_id)
            continue

        if require_evidence_eligible:
            # Fail closed: prediction, decision, outcome must all exist and have evidence_eligible == True
            if pred.get("evidence_eligible") is not True or dec.get("evidence_eligible") is not True or outcome.get("evidence_eligible") is not True:
                rejection_counts["eligibility_failed"] += 1
                _add_rejection("ELIGIBILITY_FAILED", sample.position_id)
                continue

            # Strict prediction_id linkage check
            if str(dec.get("prediction_id") or "") != str(sample.prediction_id) or str(outcome.get("prediction_id") or "") != str(sample.prediction_id):
                rejection_counts["prediction_id_mismatch"] += 1
                _add_rejection("PREDICTION_ID_MISMATCH", sample.position_id)
                continue

            # Strict metadata lineage check across target epoch, deployment, and paper_run
            if resolved_epoch_id and str(pred.get("epoch_id") or "") != resolved_epoch_id:
                rejection_counts["epoch_mismatch"] += 1
                _add_rejection("EPOCH_MISMATCH", sample.prediction_id)
                continue

            dec_epoch = dec.get("epoch_id")
            if dec_epoch is not None and str(dec_epoch) != resolved_epoch_id:
                rejection_counts["epoch_mismatch"] += 1
                _add_rejection("EPOCH_MISMATCH", sample.prediction_id)
                continue

            outcome_epoch = outcome.get("epoch_id")
            if outcome_epoch is not None and str(outcome_epoch) != resolved_epoch_id:
                rejection_counts["epoch_mismatch"] += 1
                _add_rejection("EPOCH_MISMATCH", sample.position_id)
                continue

            if resolved_deployment_id:
                if str(pred.get("deployment_id") or "") != resolved_deployment_id or \
                   str(dec.get("deployment_id") or "") != resolved_deployment_id or \
                   str(outcome.get("deployment_id") or "") != resolved_deployment_id:
                    rejection_counts["deployment_mismatch"] += 1
                    _add_rejection("DEPLOYMENT_MISMATCH", sample.position_id)
                    continue

            if resolved_paper_run_id:
                if str(pred.get("paper_run_id") or "") != resolved_paper_run_id or \
                   str(dec.get("paper_run_id") or "") != resolved_paper_run_id or \
                   str(outcome.get("paper_run_id") or "") != resolved_paper_run_id:
                    rejection_counts["paper_run_mismatch"] += 1
                    _add_rejection("PAPER_RUN_MISMATCH", sample.position_id)
                    continue

        dec_id = str(dec.get("decision_id") or "NOT_AVAILABLE")
        res = res_map.get(dec_id, {}) if dec_id != "NOT_AVAILABLE" else {}

        # Filter out test trades
        is_test_trade = outcome.get("created_by") == "paper_lifecycle_e2e" or str(outcome.get("idempotency_key") or "").startswith("idem-paper-")
        if is_test_trade:
            rejection_counts["test_trade_excluded"] += 1
            _add_rejection("TEST_TRADE_EXCLUDED", sample.position_id)
            continue

        # Tag backfill and source
        historical_backfill = bool(
            getattr(sample, "historical_backfill", False) or
            pred.get("historical_backfill") or
            dec.get("historical_backfill") or
            outcome.get("historical_backfill")
        )
        trade_id = sample.position_id
        route = "LEGACY" if base_symbol in LEGACY_SYMBOLS else "MC5_QUALIFIED"
        model_id = sample.model_version
        release_id = str(pred.get("epoch_id") or resolved_epoch_id or "model-coverage-v1-r1")
        
        execution_id = str(
            res.get("client_order_id") or
            res.get("reservation_id") or
            outcome.get("client_order_id") or
            outcome.get("reservation_id") or
            "NOT_AVAILABLE"
        )
        entry_fill_id = str(outcome.get("fill_id") or "NOT_AVAILABLE")
        exit_fill_id = str(outcome.get("exit_fill_id") or "NOT_AVAILABLE")
        position_id = sample.position_id

        # Timestamps
        decision_timestamp = str(dec.get("written_at") or pred.get("timestamp") or pred.get("event_time") or "NOT_AVAILABLE")
        entry_timestamp = str(outcome.get("entry_time") or "NOT_AVAILABLE")
        exit_timestamp = str(sample.closed_at or outcome.get("closed_at") or outcome.get("exit_time") or "NOT_AVAILABLE")

        side = str(sample.side or outcome.get("direction") or outcome.get("side") or "NOT_AVAILABLE").upper()
        invested = outcome.get("invested_usdt")
        entry_price = outcome.get("entry_price")
        exit_price = outcome.get("sell_price") or outcome.get("exit_price")
        
        quantity = "NOT_AVAILABLE"
        if invested is not None and entry_price and float(entry_price) > 0:
            quantity = float(invested) / float(entry_price)

        entry_price_val = float(entry_price) if entry_price else "NOT_AVAILABLE"
        exit_price_val = float(exit_price) if exit_price else "NOT_AVAILABLE"

        # Financial Fields under P8CostPolicy.V1_PAPER_ROUNDTRIP_FEE
        fee_usd_raw = outcome.get("fee_usd")
        fee_usd_val = float(fee_usd_raw) if fee_usd_raw is not None else None
        
        pnl_usd_actual_raw = outcome.get("pnl_usd_actual")
        actual_gross_pnl_usd = float(pnl_usd_actual_raw) if pnl_usd_actual_raw is not None else None

        cost_coverage_complete = fee_usd_val is not None
        known_cost_net_pnl_usd = (actual_gross_pnl_usd - fee_usd_val) if (actual_gross_pnl_usd is not None and fee_usd_val is not None) else None
        actual_net_pnl_usd = known_cost_net_pnl_usd if cost_coverage_complete else None

        fee_bps = "NOT_AVAILABLE"
        if fee_usd_val is not None and invested and float(invested) > 0:
            fee_bps = (fee_usd_val / float(invested)) * 10000.0

        net_return_bps = float(sample.net_pnl_pct) * 100.0
        fee_bps_val = float(fee_bps) if fee_bps != "NOT_AVAILABLE" else 0.0
        is_long = side in ("LONG", "BUY")

        if entry_price and exit_price and float(entry_price) > 0:
            e_p = float(entry_price)
            ex_p = float(exit_price)
            if is_long:
                gross_return_bps = ((ex_p - e_p) / e_p) * 10000.0
            else:
                gross_return_bps = ((e_p - ex_p) / e_p) * 10000.0
        else:
            gross_return_bps = net_return_bps + fee_bps_val

        estimated_gross_return_bps = gross_return_bps
        estimated_net_return_bps = gross_return_bps - fee_bps_val if fee_bps != "NOT_AVAILABLE" else net_return_bps

        # USD estimated PnL populated ONLY if reserved_notional is explicitly known
        reserved_notional = res.get("reserved_notional")
        estimated_gross_pnl_usd = None
        estimated_net_pnl_usd = None
        if reserved_notional is not None:
            r_notional = float(reserved_notional)
            estimated_gross_pnl_usd = (estimated_gross_return_bps / 10000.0) * r_notional
            estimated_net_pnl_usd = (estimated_net_return_bps / 10000.0) * r_notional

        holding_time = "NOT_AVAILABLE"
        t_entry = _parse_time(entry_timestamp)
        t_exit = _parse_time(exit_timestamp)
        if t_entry and t_exit:
            holding_time = (t_exit - t_entry).total_seconds()
        elif outcome.get("hold_hours") is not None:
            holding_time = float(outcome["hold_hours"]) * 3600.0

        close_reason = str(outcome.get("close_reason") or outcome.get("result") or "NOT_AVAILABLE")
        model_score = float(sample.predicted_probability)
        model_confidence = pred.get("meta_probability") or pred.get("posterior_probability") or pred.get("calibrated_prediction")
        if model_confidence is not None:
            model_confidence = float(model_confidence)
        else:
            model_confidence = "NOT_AVAILABLE"

        lineage_complete = bool(
            dec_id != "NOT_AVAILABLE" and
            execution_id != "NOT_AVAILABLE" and
            entry_fill_id != "NOT_AVAILABLE"
        )
        source_partition = str(pred.get("source_partition") or outcome.get("paper_run_id") or "main")
        source_type = "SHADOW_CANARY" if not historical_backfill else "HISTORICAL_BACKFILL"

        closed_trades.append({
            "trade_id": f"trade-{sample.prediction_id}-{sample.position_id}",
            "prediction_id": sample.prediction_id,
            "decision_id": dec_id,
            "execution_id": execution_id,
            "entry_fill_id": entry_fill_id,
            "exit_fill_id": exit_fill_id,
            "symbol": symbol,
            "route": str(dec.get("route") or ("LEGACY" if base_symbol in LEGACY_SYMBOLS else "MC5_QUALIFIED")),
            "model_id": model_id,
            "model_version": str(pred.get("model_version") or "unknown"),
            "release_id": release_id,
            "position_id": position_id,
            "decision_timestamp": decision_timestamp,
            "entry_timestamp": entry_timestamp,
            "exit_timestamp": exit_timestamp,
            "side": side,
            "quantity": quantity,
            "entry_price": entry_price_val,
            "exit_price": exit_price_val,
            "estimated_gross_return_bps": estimated_gross_return_bps,
            "estimated_net_return_bps": estimated_net_return_bps,
            "gross_return_bps": estimated_gross_return_bps,
            "net_return_bps": estimated_net_return_bps,
            "fee_bps": fee_bps,
            "slippage_bps": "NOT_AVAILABLE",
            "other_cost_bps": 0.0,
            "observed_net": net_return_bps,
            "holding_time": holding_time,
            "close_reason": close_reason,
            "actual_gross_pnl_usd": actual_gross_pnl_usd,
            "actual_fee_usd": fee_usd_val,
            "known_cost_net_pnl_usd": known_cost_net_pnl_usd,
            "actual_net_pnl_usd": actual_net_pnl_usd,
            "cost_coverage_complete": cost_coverage_complete,
            "gross_pnl": actual_gross_pnl_usd if actual_gross_pnl_usd is not None else "NOT_AVAILABLE",
            "fees": fee_usd_val if fee_usd_val is not None else "NOT_AVAILABLE",
            "net_pnl": actual_net_pnl_usd if actual_net_pnl_usd is not None else "NOT_AVAILABLE",
            "estimated_gross_pnl_usd": estimated_gross_pnl_usd,
            "estimated_net_pnl_usd": estimated_net_pnl_usd,
            "model_score": model_score,
            "model_confidence": model_confidence,
            "lineage_complete": lineage_complete,
            "historical_backfill": historical_backfill,
            "source_partition": source_partition,
            "source_type": source_type,
        })

    if include_rejections:
        return closed_trades, {"counts": rejection_counts, "reasons": rejection_reasons}
    return closed_trades


def run_funnel_analysis(
    evidence_store: RuntimeEvidenceStore,
    reservation_db_path: Path | str | None = None,
    *,
    target_epoch_id: str | None = None,
    require_evidence_eligible: bool = True,
) -> dict[str, Any]:
    """Calculate funnel counts and conversion rates across execution stages."""
    if reservation_db_path is None:
        from btc_scraper.core.paths import get_runtime_paths
        reservation_db_path = get_runtime_paths().reservation_db_path
    reservation_db_path = Path(reservation_db_path)

    rejection_counts: dict[str, int] = {
        "predictions_rejected": 0,
        "decisions_rejected": 0,
        "outcomes_rejected": 0,
        "reservations_rejected": 0,
    }
    rejection_reasons: list[str] = []

    active_epoch = None
    if require_evidence_eligible:
        try:
            active_epoch = evidence_store.get_active_evidence_epoch()
        except Exception as exc:
            raise GovernanceError(f"Failed to resolve active evidence epoch for funnel analysis: {exc}") from exc

        if active_epoch is None or active_epoch.status != "ACTIVE":
            raise GovernanceError("No ACTIVE evidence epoch found for funnel analysis")

        if target_epoch_id is not None and active_epoch.epoch_id != target_epoch_id:
            raise GovernanceError(f"Funnel epoch mismatch: active={active_epoch.epoch_id}, target={target_epoch_id}")

    resolved_epoch_id = str(target_epoch_id or (active_epoch.epoch_id if active_epoch else ""))
    resolved_deployment_id = str(active_epoch.deployment_id if active_epoch else "")
    resolved_paper_run_id = str(active_epoch.paper_run_id if active_epoch else "")

    if require_evidence_eligible and (not resolved_epoch_id or not resolved_deployment_id or not resolved_paper_run_id):
        raise GovernanceError("Incomplete active epoch target contract for funnel analysis")

    # Load rows from evidence store
    rows_data = evidence_store.shadow_evidence_rows()
    predictions = rows_data.get("predictions", [])
    decisions = rows_data.get("final_decisions", [])
    outcomes = rows_data.get("outcomes", [])

    # Step 1: Active Predictions
    active_preds = []
    for p in predictions:
        if require_evidence_eligible:
            if p.get("evidence_eligible") is not True:
                rejection_counts["predictions_rejected"] += 1
                continue
            if str(p.get("epoch_id") or "") != resolved_epoch_id:
                rejection_counts["predictions_rejected"] += 1
                continue
            if str(p.get("deployment_id") or "") != resolved_deployment_id:
                rejection_counts["predictions_rejected"] += 1
                continue
            if str(p.get("paper_run_id") or "") != resolved_paper_run_id:
                rejection_counts["predictions_rejected"] += 1
                continue

        symbol = str(p.get("symbol") or "").upper()
        base_symbol = symbol.split("/")[0].split("USDT")[0]
        if base_symbol in ACTIVE_SYMBOLS:
            active_preds.append(p)

    pred_count = len(active_preds)
    pred_ids = {str(p.get("prediction_id")) for p in active_preds if p.get("prediction_id")}
    pred_map = {str(p.get("prediction_id")): p for p in active_preds if p.get("prediction_id")}

    # Step 2: Final Decisions
    active_decisions = []
    for d in decisions:
        p_id = str(d.get("prediction_id") or "")
        if p_id not in pred_ids:
            rejection_counts["decisions_rejected"] += 1
            continue
        if require_evidence_eligible:
            if d.get("evidence_eligible") is not True:
                rejection_counts["decisions_rejected"] += 1
                continue
            if str(d.get("deployment_id") or "") != resolved_deployment_id:
                rejection_counts["decisions_rejected"] += 1
                continue
            if str(d.get("paper_run_id") or "") != resolved_paper_run_id:
                rejection_counts["decisions_rejected"] += 1
                continue
            d_epoch = d.get("epoch_id")
            if d_epoch is not None and str(d_epoch) != resolved_epoch_id:
                rejection_counts["decisions_rejected"] += 1
                continue

        active_decisions.append(d)
    decision_count = len(active_decisions)
    dec_map = {str(d.get("decision_id")): d for d in active_decisions if d.get("decision_id")}

    # Step 3: Actionable Decisions
    actionable_decisions = []
    for d in active_decisions:
        action = str(d.get("action") or "").upper()
        if action in ("BUY", "SELL", "INCREASE", "REDUCE"):
            actionable_decisions.append(d)
    actionable_count = len(actionable_decisions)
    actionable_dec_ids = {str(d.get("decision_id")) for d in actionable_decisions if d.get("decision_id")}

    # Step 4: Execution Attempts
    res_dec_ids = set()
    res_committed_ids = set()

    if reservation_db_path.exists():
        try:
            conn = sqlite3.connect(f"file:{reservation_db_path.resolve().as_posix()}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM reservations")
            for row in cursor.fetchall():
                d_id = str(row["entry_decision_id"] or "")
                if not d_id or d_id not in dec_map:
                    rejection_counts["reservations_rejected"] += 1
                    continue

                parent_dec = dec_map[d_id]
                parent_pred = pred_map.get(str(parent_dec.get("prediction_id") or ""), {})

                if require_evidence_eligible:
                    if str(row["deployment_id"] or "") != resolved_deployment_id or \
                       str(row["paper_run_id"] or "") != resolved_paper_run_id:
                        rejection_counts["reservations_rejected"] += 1
                        continue

                    res_keys = row.keys()
                    if "prediction_id" in res_keys and row["prediction_id"]:
                        if str(row["prediction_id"]) != str(parent_dec.get("prediction_id")):
                            rejection_counts["reservations_rejected"] += 1
                            continue

                    if "epoch_id" in res_keys and row["epoch_id"]:
                        if str(row["epoch_id"]) != resolved_epoch_id:
                            rejection_counts["reservations_rejected"] += 1
                            continue

                res_dec_ids.add(d_id)
                if row["status"] == "committed" or (row["filled_notional"] and float(row["filled_notional"]) > 0):
                    res_committed_ids.add(d_id)
            conn.close()
        except Exception as exc:
            if require_evidence_eligible:
                raise GovernanceError(f"Failed to query reservation store at {reservation_db_path}: {exc}") from exc

    # Filter eligible outcomes
    eligible_outcomes = []
    for o in outcomes:
        p_id = str(o.get("prediction_id") or "")
        if p_id not in pred_ids:
            rejection_counts["outcomes_rejected"] += 1
            continue
        if require_evidence_eligible:
            if o.get("evidence_eligible") is not True:
                rejection_counts["outcomes_rejected"] += 1
                continue
            if str(o.get("deployment_id") or "") != resolved_deployment_id or \
               str(o.get("paper_run_id") or "") != resolved_paper_run_id:
                rejection_counts["outcomes_rejected"] += 1
                continue
            o_epoch = o.get("epoch_id")
            if o_epoch is not None and str(o_epoch) != resolved_epoch_id:
                rejection_counts["outcomes_rejected"] += 1
                continue
        eligible_outcomes.append(o)

    linked_outcome_pred_ids = {str(o.get("prediction_id")) for o in eligible_outcomes if o.get("prediction_id")}

    direct_exec_dec_ids = {d_id for d_id in actionable_dec_ids if d_id in res_dec_ids}
    fallback_exec_dec_ids = {d.get("decision_id") for d in actionable_decisions if str(d.get("prediction_id")) in linked_outcome_pred_ids}
    execution_attempts_ids = direct_exec_dec_ids | fallback_exec_dec_ids
    execution_count = len(execution_attempts_ids)

    direct_fill_dec_ids = {d_id for d_id in actionable_dec_ids if d_id in res_committed_ids}
    fills_dec_ids = direct_fill_dec_ids | fallback_exec_dec_ids
    fills_count = len(fills_dec_ids)

    closed_trades = extract_closed_trades(
        evidence_store,
        reservation_db_path,
        target_epoch_id=resolved_epoch_id,
        require_evidence_eligible=require_evidence_eligible,
    )
    closed_trades_count = len(closed_trades)

    actionable_rate = actionable_count / decision_count if decision_count > 0 else 0.0
    execution_rate = execution_count / actionable_count if actionable_count > 0 else 0.0
    fill_rate = fills_count / execution_count if execution_count > 0 else 0.0
    closure_rate = closed_trades_count / fills_count if fills_count > 0 else 0.0

    return {
        "counts": {
            "predictions": pred_count,
            "final_decisions": decision_count,
            "actionable_decisions": actionable_count,
            "execution_attempts": execution_count,
            "fills": fills_count,
            "closed_trades": closed_trades_count,
        },
        "rates": {
            "actionable_rate": actionable_rate,
            "execution_rate": execution_rate,
            "fill_rate": fill_rate,
            "closure_rate": closure_rate,
        },
        "rejection_counts": rejection_counts,
        "rejection_reasons": rejection_reasons,
    }
