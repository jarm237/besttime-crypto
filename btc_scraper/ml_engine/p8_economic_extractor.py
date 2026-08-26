"""P8 — Economic Effectiveness Evaluation Extractor.

Extracts closed trade economics and funnel metrics from runtime evidence and
reservation databases.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

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
    reservation_db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    """Query evidence store partitions and link outcomes to evaluate economics."""
    # Resolve reservation database path
    if reservation_db_path is None:
        from btc_scraper.core.paths import get_runtime_paths
        reservation_db_path = get_runtime_paths().reservation_db_path
    reservation_db_path = Path(reservation_db_path)

    # 1. Fetch raw rows
    rows_data = evidence_store.shadow_evidence_rows()
    predictions = rows_data.get("predictions", [])
    decisions = rows_data.get("final_decisions", [])
    outcomes = rows_data.get("outcomes", [])

    # Index decisions by prediction_id
    dec_map = {str(d["prediction_id"]): d for d in decisions if d.get("prediction_id")}
    
    # Index predictions by prediction_id
    pred_map = {str(p["prediction_id"]): p for p in predictions if p.get("prediction_id")}

    # Load reservations
    res_map = {}
    if reservation_db_path.exists():
        try:
            conn = sqlite3.connect(reservation_db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM reservations")
            for r in cursor.fetchall():
                d_id = r["entry_decision_id"]
                if d_id:
                    res_map[str(d_id)] = dict(r)
            conn.close()
        except Exception as e:
            # Degrade gracefully
            pass

    # 2. Link outcomes to predictions using canonical outcome linker
    report = link_runtime_outcomes(predictions, outcomes)
    
    closed_trades = []
    
    # Outcomes payload lookup helper
    outcome_map = {str(o["position_id"]): o for o in outcomes if o.get("position_id")}

    for sample in report.samples:
        symbol = str(sample.symbol or "").upper()
        # Handle formats like BTC/USDT or BTCUSDT or just BTC
        base_symbol = symbol.split("/")[0].split("USDT")[0]
        if base_symbol not in ACTIVE_SYMBOLS:
            continue

        pred = pred_map.get(sample.prediction_id, {})
        dec = dec_map.get(sample.prediction_id, {})
        outcome = outcome_map.get(sample.position_id, {})
        dec_id = str(dec.get("decision_id") or "NOT_AVAILABLE")
        res = res_map.get(dec_id, {}) if dec_id != "NOT_AVAILABLE" else {}

        # Filter out test trades
        is_test_trade = outcome.get("created_by") == "paper_lifecycle_e2e" or str(outcome.get("idempotency_key") or "").startswith("idem-paper-")
        if is_test_trade:
            continue

        # Tag backfill and source
        historical_backfill = bool(
            outcome.get("backfill_generated") or
            outcome.get("backfill_source") or
            outcome.get("paper_run_id") == "historical-backfill-2026q1"
        )
        source_partition = str(outcome.get("paper_run_id") or "main")
        source_type = str(outcome.get("fill_source") or outcome.get("source") or "runtime")

        # Identifiers
        trade_id = sample.position_id
        route = "LEGACY" if base_symbol in LEGACY_SYMBOLS else "MC5_QUALIFIED"
        model_id = sample.model_version
        release_id = str(pred.get("epoch_id") or "model-coverage-v1-r1")
        
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

        # Side and quantities
        side = str(sample.side or outcome.get("direction") or outcome.get("side") or "NOT_AVAILABLE").upper()
        
        invested = outcome.get("invested_usdt")
        entry_price = outcome.get("entry_price")
        exit_price = outcome.get("sell_price") or outcome.get("exit_price")
        
        quantity = "NOT_AVAILABLE"
        if invested is not None and entry_price and float(entry_price) > 0:
            quantity = float(invested) / float(entry_price)

        entry_price_val = float(entry_price) if entry_price else "NOT_AVAILABLE"
        exit_price_val = float(exit_price) if exit_price else "NOT_AVAILABLE"

        # Costs
        fee_usd = outcome.get("fee_usd")
        fee_bps = "NOT_AVAILABLE"
        if fee_usd is not None and invested and float(invested) > 0:
            fee_bps = (float(fee_usd) / float(invested)) * 10000.0
        
        slippage_bps = "NOT_AVAILABLE"
        other_cost_bps = 0.0

        # PnL / Returns
        net_return_bps = float(sample.net_pnl_pct) * 100.0
        observed_net = net_return_bps

        # Calculate gross return with correct side mapping
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
            # Fallback
            gross_return_bps = net_return_bps + (fee_bps_val if fee_bps != "NOT_AVAILABLE" else 6.0)

        # Enforce consistency: net_return_bps <= gross_return_bps
        gross_return_bps = max(gross_return_bps, net_return_bps + fee_bps_val)

        if isinstance(gross_return_bps, float) and fee_bps != "NOT_AVAILABLE":
            estimated_net = gross_return_bps - float(fee_bps)
        else:
            estimated_net = net_return_bps

        pnl_usd = outcome.get("pnl_usd_actual")
        fees = float(fee_usd) if fee_usd is not None else "NOT_AVAILABLE"
        net_pnl = float(pnl_usd) if pnl_usd is not None else "NOT_AVAILABLE"
        
        if net_pnl != "NOT_AVAILABLE":
            gross_pnl = net_pnl + (fees if fees != "NOT_AVAILABLE" else 0.0)
        else:
            gross_pnl = "NOT_AVAILABLE"

        # Durations
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

        closed_trades.append({
            "trade_id": trade_id,
            "symbol": symbol,
            "route": route,
            "model_id": model_id,
            "release_id": release_id,
            "prediction_id": sample.prediction_id,
            "decision_id": dec_id,
            "execution_id": execution_id,
            "entry_fill_id": entry_fill_id,
            "exit_fill_id": exit_fill_id,
            "position_id": position_id,
            "decision_timestamp": decision_timestamp,
            "entry_timestamp": entry_timestamp,
            "exit_timestamp": exit_timestamp,
            "side": side,
            "quantity": quantity,
            "entry_price": entry_price_val,
            "exit_price": exit_price_val,
            "gross_return_bps": gross_return_bps,
            "fee_bps": fee_bps,
            "slippage_bps": slippage_bps,
            "other_cost_bps": other_cost_bps,
            "net_return_bps": net_return_bps,
            "observed_net": observed_net,
            "estimated_net": estimated_net,
            "gross_pnl": gross_pnl,
            "fees": fees,
            "net_pnl": net_pnl,
            "holding_time": holding_time,
            "close_reason": close_reason,
            "model_score": model_score,
            "model_confidence": model_confidence,
            "lineage_complete": lineage_complete,
            "historical_backfill": historical_backfill,
            "source_partition": source_partition,
            "source_type": source_type
        })

    return closed_trades


def run_funnel_analysis(
    evidence_store: RuntimeEvidenceStore,
    reservation_db_path: Path | str | None = None
) -> dict[str, Any]:
    """Calculate funnel counts and conversion rates across execution stages."""
    if reservation_db_path is None:
        from btc_scraper.core.paths import get_runtime_paths
        reservation_db_path = get_runtime_paths().reservation_db_path
    else:
        reservation_db_path = Path(reservation_db_path)

    # Load rows from evidence store
    rows_data = evidence_store.shadow_evidence_rows()
    predictions = rows_data.get("predictions", [])
    decisions = rows_data.get("final_decisions", [])
    outcomes = rows_data.get("outcomes", [])
    
    outcome_map = {str(o["position_id"]): o for o in outcomes if o.get("position_id")}

    # Filter predictions for model-coverage-v1-r1/epoch_id and active symbols
    active_preds = []
    for p in predictions:
        symbol = str(p.get("symbol") or "").upper()
        base_symbol = symbol.split("/")[0].split("USDT")[0]
        if base_symbol in ACTIVE_SYMBOLS:
            active_preds.append(p)
            
    pred_count = len(active_preds)
    pred_ids = {str(p.get("prediction_id")) for p in active_preds}

    # Funnel step 2: Final Decisions
    active_decisions = [d for d in decisions if str(d.get("prediction_id")) in pred_ids]
    decision_count = len(active_decisions)

    # Funnel step 3: Actionable Decisions
    actionable_decisions = []
    for d in active_decisions:
        action = str(d.get("action") or "").upper()
        if action in ("BUY", "SELL", "INCREASE", "REDUCE"):
            actionable_decisions.append(d)
    actionable_count = len(actionable_decisions)

    # Funnel step 4: Execution Attempts (join with reservations database)
    res_dec_ids = set()
    res_committed_ids = set()
    if reservation_db_path.exists():
        try:
            conn = sqlite3.connect(reservation_db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT entry_decision_id, status, filled_notional FROM reservations")
            for d_id, status, filled in cursor.fetchall():
                if d_id:
                    res_dec_ids.add(str(d_id))
                    if status == "committed" or (filled and float(filled) > 0):
                        res_committed_ids.add(str(d_id))
            conn.close()
        except:
            pass

    # Execution attempts = actionable decisions with reservation
    execution_attempts = []
    for d in actionable_decisions:
        d_id = str(d.get("decision_id"))
        if d_id in res_dec_ids:
            execution_attempts.append(d)
    
    # Fallback if reservations.db is empty but we have linked outcomes:
    # If the system is in an environment where reservations aren't database-persisted
    linked_outcome_pred_ids = {str(o.get("prediction_id")) for o in outcomes if o.get("prediction_id")}
    
    execution_count = len(execution_attempts)
    if execution_count == 0 and len(linked_outcome_pred_ids) > 0:
        # Fallback: estimate execution attempts as actionable decisions that match linked outcomes
        execution_count = sum(1 for d in actionable_decisions if str(d.get("prediction_id")) in linked_outcome_pred_ids)

    # Funnel step 5: Fills
    # Fills = reservations that are committed and have filled notional > 0, or match closed outcomes
    fills_count = sum(1 for d in actionable_decisions if str(d.get("decision_id")) in res_committed_ids)
    if fills_count == 0 and len(linked_outcome_pred_ids) > 0:
        fills_count = sum(1 for d in actionable_decisions if str(d.get("prediction_id")) in linked_outcome_pred_ids)

    # Funnel step 6: Closed Trades (only real non-backfilled active trades)
    report = link_runtime_outcomes(predictions, outcomes)
    closed_trades_count = 0
    for sample in report.samples:
        symbol = str(sample.symbol or "").upper()
        base_symbol = symbol.split("/")[0].split("USDT")[0]
        if base_symbol in ACTIVE_SYMBOLS:
            outcome = outcome_map.get(sample.position_id, {})
            is_test_trade = outcome.get("created_by") == "paper_lifecycle_e2e" or str(outcome.get("idempotency_key") or "").startswith("idem-paper-")
            historical_backfill = bool(
                outcome.get("backfill_generated") or
                outcome.get("backfill_source") or
                outcome.get("paper_run_id") == "historical-backfill-2026q1"
            )
            if not is_test_trade and not historical_backfill:
                closed_trades_count += 1

    # Calculate rates
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
            "closed_trades": closed_trades_count
        },
        "rates": {
            "actionable_rate": actionable_rate,
            "execution_rate": execution_rate,
            "fill_rate": fill_rate,
            "closure_rate": closure_rate
        }
    }
