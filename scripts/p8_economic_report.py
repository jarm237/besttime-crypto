#!/usr/bin/env python3
"""P8 — Economic Effectiveness Evaluation Report Tool.

Analyzes trade-level economics and funnel rates, generates JSON and Markdown
reports based on the frozen contract.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

# Ensure btc_scraper is in import path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from btc_scraper.ml_engine.p8_governance import (
    ABSOLUTE_USD_TOLERANCE,
    MIN_COST_COVERAGE_RATIO,
    MIN_RATE_COVERAGE_RATIO,
    EXPECTED_DEPLOYMENT_ID,
    EXPECTED_EPOCH_ID,
    EXPECTED_PAPER_RUN_ID,
    EXPECTED_UNIVERSE_HASH,
    SEALED_ARTIFACT_SHA,
    SEALED_COMMIT_SHA,
    AttestationResult,
    GovernanceError,
    P8AttestationPolicy,
    P8CostPolicy,
    calculate_store_content_hash,
    calculate_store_manifest_hash,
    check_runtime_lock_owner,
    get_cost_policy_metadata,
)
from btc_scraper.ml_engine.p8_economic_extractor import (
    ACTIVE_SYMBOLS,
    extract_closed_trades,
    run_funnel_analysis,
)
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore

AUTHORIZED_ECONOMIC_VERDICTS = {
    "ECONOMICALLY_PROMISING",
    "CONTINUE_OBSERVATION",
    "ALPHA_FAILURE",
    "ECONOMIC_INFEASIBILITY_UNDER_CURRENT_EXECUTION",
    "MODEL_ROUTE_REVIEW",
    "DECISION_POLICY_REVIEW",
    "UNIVERSE_REVIEW",
}


def safe_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def safe_median(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n % 2 == 1:
        return sorted_vals[n // 2]
    return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0


def calculate_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate key economic metrics separating Rate metrics (bps) and Accounting metrics (USD)."""
    if not trades:
        return {
            "sample_size": 0,
            "rate_coverage_n": 0,
            "cost_coverage_n": 0,
            "mean_net_return_bps": 0.0,
            "median_net_return_bps": 0.0,
            "mean_gross_return_bps": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_net_pnl_usd": 0.0,
            "total_gross_pnl_usd": 0.0,
            "total_fees_usd": 0.0,
        }

    # 1. Rate Metrics (bps)
    rate_trades = [t for t in trades if isinstance(t.get("net_return_bps"), (int, float))]
    rate_coverage_n = len(rate_trades)

    net_bps_list = [float(t["net_return_bps"]) for t in rate_trades]
    gross_bps_list = [float(t.get("gross_return_bps", t["net_return_bps"])) for t in rate_trades]

    wins = [r for r in net_bps_list if r > 0]
    losses = [abs(r) for r in net_bps_list if r < 0]
    win_rate = len(wins) / len(net_bps_list) if net_bps_list else 0.0
    profit_factor = sum(wins) / sum(losses) if sum(losses) > 0 else (999.0 if sum(wins) > 0 else 0.0)

    # 2. Accounting Metrics (USD using Decimal)
    cost_trades = [t for t in trades if t.get("cost_coverage_complete") is True and isinstance(t.get("actual_net_pnl_usd"), (int, float))]
    cost_coverage_n = len(cost_trades)

    total_net_usd = Decimal("0.00")
    total_gross_usd = Decimal("0.00")
    total_fees_usd = Decimal("0.00")

    for t in cost_trades:
        if t.get("actual_net_pnl_usd") is not None:
            total_net_usd += Decimal(str(t["actual_net_pnl_usd"]))
        if t.get("actual_gross_pnl_usd") is not None:
            total_gross_usd += Decimal(str(t["actual_gross_pnl_usd"]))
        if t.get("actual_fee_usd") is not None:
            total_fees_usd += Decimal(str(t["actual_fee_usd"]))

    return {
        "sample_size": len(trades),
        "rate_coverage_n": rate_coverage_n,
        "cost_coverage_n": cost_coverage_n,
        "mean_net_return_bps": safe_mean(net_bps_list),
        "median_net_return_bps": safe_median(net_bps_list),
        "mean_gross_return_bps": safe_mean(gross_bps_list),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_net_pnl_usd": float(total_net_usd),
        "total_gross_pnl_usd": float(total_gross_usd),
        "total_fees_usd": float(total_fees_usd),
    }


def bucket_trades(trades: list[dict[str, Any]], num_buckets: int = 5) -> dict[str, list[dict[str, Any]]]:
    if not trades:
        return {}
    
    valid_trades = [t for t in trades if isinstance(t.get("model_score"), (int, float))]
    if not valid_trades:
        return {}

    sorted_trades = sorted(valid_trades, key=lambda x: x["model_score"])
    n = len(sorted_trades)
    bucket_size = math.ceil(n / num_buckets)

    buckets = {}
    for i in range(num_buckets):
        start_idx = i * bucket_size
        end_idx = min((i + 1) * bucket_size, n)
        if start_idx >= n:
            break
        b_name = f"bucket_{i+1}"
        buckets[b_name] = sorted_trades[start_idx:end_idx]

    return buckets


def calculate_population_report(trades: list[dict[str, Any]]) -> dict[str, Any]:
    overall = calculate_metrics(trades)
    
    routes = ["LEGACY", "MC5_QUALIFIED"]
    route_metrics = {}
    for r in routes:
        route_trades = [t for t in trades if t["route"] == r]
        route_metrics[r] = calculate_metrics(route_trades)

    symbol_metrics = {}
    for sym in ACTIVE_SYMBOLS:
        sym_trades = [t for t in trades if t["symbol"].split("/")[0].split("USDT")[0] == sym]
        symbol_metrics[sym] = calculate_metrics(sym_trades)

    side_metrics = {}
    for side in ["LONG", "SHORT"]:
        side_trades = [t for t in trades if t["side"] == side]
        side_metrics[side] = calculate_metrics(side_trades)

    buckets = bucket_trades(trades, 5)
    bucket_summary = {}
    for b_name, b_trades in buckets.items():
        bucket_summary[b_name] = {
            "trade_count": len(b_trades),
            "mean_net_return_bps": safe_mean([t["net_return_bps"] for t in b_trades if isinstance(t.get("net_return_bps"), (int, float))]),
            "median_net_return_bps": safe_median([t["net_return_bps"] for t in b_trades if isinstance(t.get("net_return_bps"), (int, float))]),
            "win_rate": calculate_metrics(b_trades)["win_rate"],
            "profit_factor": calculate_metrics(b_trades)["profit_factor"],
        }
        
    return {
        "overall_portfolio_economics": overall,
        "route_attribution": route_metrics,
        "symbol_attribution": symbol_metrics,
        "side_attribution": side_metrics,
        "confidence_buckets": bucket_summary,
    }


def attest_canonical_store(
    evidence_path: Path,
    reservation_path: Path | None = None,
) -> AttestationResult:
    """Expose structured attestation result."""
    policy = P8AttestationPolicy()
    return policy.attest_store(evidence_path, reservation_path)


def validate_canonical_store_identity(
    evidence_path: Path,
    store: RuntimeEvidenceStore | None = None,
    reservation_path: Path | None = None,
) -> bool:
    """Backward compatibility wrapper delegating to P8AttestationPolicy returning boolean."""
    policy = P8AttestationPolicy()
    if not policy.validate_store_paths(evidence_path, reservation_path):
        return False
    att = policy.attest_store(evidence_path, reservation_path)
    return att.is_valid


def determine_verdict(
    canary_n: int,
    overall_metrics: dict[str, Any],
    route_attribution: dict[str, Any],
    funnel: dict[str, Any],
    *,
    allow_non_eligible: bool = False,
) -> tuple[str, str]:
    if not allow_non_eligible:
        return "DIAGNOSTIC", "UNAUTHORIZED_POPULATION_VERDICT_NOT_PERMITTED"

    if canary_n < 30:
        return "CONTINUE", "CANARY_POPULATION_ACCUMULATING"

    mean_net_bps = overall_metrics.get("mean_net_return_bps", 0.0)
    win_rate = overall_metrics.get("win_rate", 0.0)

    if mean_net_bps > 10.0 and win_rate >= 0.52:
        return "CONTINUE", "ECONOMICALLY_PROMISING"

    if mean_net_bps < -20.0:
        return "STOP", "ALPHA_FAILURE"

    if mean_net_bps < 0.0:
        return "MODIFY", "ECONOMIC_INFEASIBILITY_UNDER_CURRENT_EXECUTION"

    return "CONTINUE", "CONTINUE_OBSERVATION"


def generate_report(
    evidence_store_path: Path | str | None = None,
    reservation_db_path: Path | str | None = None,
    output_dir: Path | str | None = None,
    *,
    require_evidence_eligible: bool = True,
    governed_mode: bool = False,
) -> dict[str, Any]:
    if output_dir is None:
        output_dir = Path(__file__).resolve().parents[1]
    else:
        output_dir = Path(output_dir)

    if evidence_store_path is not None:
        evidence_logical_path = Path(evidence_store_path)
    else:
        from btc_scraper.core.paths import get_runtime_paths
        evidence_logical_path = Path(get_runtime_paths().runtime_evidence_path)

    logs_dir = evidence_logical_path.parent

    if governed_mode:
        check_runtime_lock_owner(logs_dir)

    pre_manifest_hash = calculate_store_manifest_hash(logs_dir)
    pre_content_hash = calculate_store_content_hash(logs_dir)

    global_index_path = logs_dir / "global_evidence_index.sqlite"
    pattern = f"{evidence_logical_path.stem}_????-??-??{evidence_logical_path.suffix}"
    partition_files = list(logs_dir.glob(pattern))

    evidence_exists = (
        evidence_logical_path.exists() or 
        global_index_path.exists() or 
        len(partition_files) > 0
    )

    if not evidence_exists:
        err_msg = f"Expected evidence database not found at logical path: {evidence_logical_path}"
        if governed_mode:
            raise GovernanceError(err_msg)
        print(f"ERROR: {err_msg}", file=sys.stderr)
        sys.exit(1)

    if reservation_db_path is not None:
        res_path = Path(reservation_db_path)
    else:
        from btc_scraper.core.paths import get_runtime_paths
        res_path = Path(get_runtime_paths().reservation_db_path)

    if not res_path.exists():
        err_msg = f"Expected reservation database not found at: {res_path}"
        if governed_mode:
            raise GovernanceError(err_msg)
        print(f"ERROR: {err_msg}", file=sys.stderr)
        sys.exit(1)

    policy = P8AttestationPolicy()
    attestation = policy.attest_store(evidence_logical_path, res_path)
    is_canonical = attestation.is_valid

    if governed_mode and (not is_canonical or not require_evidence_eligible):
        raise GovernanceError(
            f"Governed P8 execution failure: attestation errors: {attestation.attestation_errors}"
        )

    store = RuntimeEvidenceStore(evidence_logical_path)

    # 1. Extract Trades
    trades, rejection_info = extract_closed_trades(
        store,
        res_path,
        require_evidence_eligible=require_evidence_eligible,
        include_rejections=True,
    )

    # Post snapshot & content verification
    post_manifest_hash = calculate_store_manifest_hash(logs_dir)
    post_content_hash = calculate_store_content_hash(logs_dir)
    if pre_manifest_hash != post_manifest_hash or pre_content_hash != post_content_hash:
        raise GovernanceError(
            f"Store partition mutated during evaluation: "
            f"manifest ({pre_manifest_hash} vs {post_manifest_hash}), "
            f"content ({pre_content_hash} vs {post_content_hash})"
        )

    # 2. Split populations
    current_canary_trades = [t for t in trades if not t.get("historical_backfill", False)]
    historical_backfill_trades = [t for t in trades if t.get("historical_backfill", False)]
    
    # 3. Run population reports
    canary_report = calculate_population_report(current_canary_trades)
    historical_report = calculate_population_report(historical_backfill_trades)
    combined_report = calculate_population_report(trades)

    # 4. Run Funnel Analysis
    funnel = run_funnel_analysis(store, res_path, require_evidence_eligible=require_evidence_eligible)

    # 5. Determine Verdict
    canary_n = len(current_canary_trades)
    stage, verdict_reason = determine_verdict(
        canary_n, 
        canary_report["overall_portfolio_economics"], 
        canary_report["route_attribution"], 
        funnel,
        allow_non_eligible=require_evidence_eligible and is_canonical,
    )

    # 6. Evaluate Data Integrity & Reconciliations
    p8_data_integrity = "PASS" if (
        evidence_exists and
        is_canonical and
        attestation.is_valid and
        rejection_info["counts"].get("duplicate_conflict", 0) == 0 and
        rejection_info["counts"].get("prediction_id_mismatch", 0) == 0 and
        rejection_info["counts"].get("epoch_mismatch", 0) == 0 and
        rejection_info["counts"].get("deployment_mismatch", 0) == 0 and
        rejection_info["counts"].get("paper_run_mismatch", 0) == 0
    ) else "FAIL"

    # Pairwise Disjoint Population Set Reconciliation
    closed_ids = {t["prediction_id"] for t in current_canary_trades if t.get("prediction_id")}
    rows_data = store.shadow_evidence_rows()
    decisions = rows_data.get("final_decisions", [])
    non_actionable_ids = {
        str(d.get("prediction_id")) for d in decisions
        if d.get("prediction_id") and str(d.get("action", "")).upper() not in ("BUY", "SELL", "INCREASE", "REDUCE")
    }
    rejected_ids = set()
    for reason in rejection_info.get("reasons", []):
        if ":" in reason:
            _, sample_id = reason.split(":", 1)
            rejected_ids.add(sample_id)

    disjoint_valid = (
        len(closed_ids & non_actionable_ids) == 0 and
        len(closed_ids & rejected_ids) == 0 and
        len(non_actionable_ids & rejected_ids) == 0
    )
    p8_population_reconciliation = "PASS" if (disjoint_valid and canary_n == funnel["counts"]["closed_trades"]) else "FAIL"

    # Independent Accounting Reconciliation (2-cent Decimal tolerance & fee check)
    accounting_mismatches = 0
    for t in current_canary_trades:
        act_net = t.get("actual_net_pnl_usd")
        act_gross = t.get("actual_gross_pnl_usd")
        act_fee = t.get("actual_fee_usd")
        if act_net is not None and act_gross is not None and act_fee is not None:
            # Identity check
            calc_net = Decimal(str(act_gross)) - Decimal(str(act_fee))
            if abs(calc_net - Decimal(str(act_net))) > ABSOLUTE_USD_TOLERANCE:
                accounting_mismatches += 1

            # Independent fee policy recomputation if invested is present
            invested = t.get("invested_usdt") or t.get("invested")
            if invested is not None and float(invested) > 0:
                expected_entry_fee = Decimal(str(invested)) * Decimal("0.001")
                expected_gross_received = Decimal(str(invested)) + Decimal(str(act_gross))
                expected_exit_fee = expected_gross_received * Decimal("0.001")
                expected_fee_usd = expected_entry_fee + expected_exit_fee

                if abs(expected_fee_usd - Decimal(str(act_fee))) > ABSOLUTE_USD_TOLERANCE:
                    accounting_mismatches += 1

    p8_accounting_reconciliation = "PASS" if accounting_mismatches == 0 else "FAIL"

    overall_econ = canary_report["overall_portfolio_economics"]
    rate_coverage_ratio = (overall_econ["rate_coverage_n"] / canary_n) if canary_n > 0 else 1.0
    cost_coverage_ratio = (overall_econ["cost_coverage_n"] / canary_n) if canary_n > 0 else 1.0

    diagnostic_warnings: list[str] = []
    if not require_evidence_eligible:
        diagnostic_warnings.append("Report contains diagnostic non-eligible data (BTC_EVIDENCE_ELIGIBLE=false).")
    if not is_canonical:
        diagnostic_warnings.append("Report was generated from an unsealed or non-canonical evidence store.")

    if not require_evidence_eligible and not is_canonical:
        population_type = "DIAGNOSTIC_NON_CANONICAL_AND_NON_ELIGIBLE"
        maturity_stage = "DIAGNOSTIC_ONLY"
        verdict_authorized = False
    elif not require_evidence_eligible:
        population_type = "DIAGNOSTIC_NON_ELIGIBLE_INCLUDED"
        maturity_stage = "DIAGNOSTIC_ONLY"
        verdict_authorized = False
    elif not is_canonical:
        population_type = "DIAGNOSTIC_NON_CANONICAL"
        maturity_stage = "DIAGNOSTIC_ONLY"
        verdict_authorized = False
    else:
        population_type = "CANONICAL_SEALED_ELIGIBLE"
        verdict_authorized = (
            is_canonical and
            require_evidence_eligible and
            canary_n >= 100 and
            stage in {"CONTINUE", "MODIFY", "STOP"} and
            verdict_reason in AUTHORIZED_ECONOMIC_VERDICTS and
            p8_data_integrity == "PASS" and
            p8_population_reconciliation == "PASS" and
            p8_accounting_reconciliation == "PASS" and
            rate_coverage_ratio >= MIN_RATE_COVERAGE_RATIO and
            cost_coverage_ratio >= MIN_COST_COVERAGE_RATIO
        )
        if canary_n == 0:
            maturity_stage = "ACCUMULATING"
        elif canary_n < 30:
            maturity_stage = "PRELIMINARY"
        elif canary_n < 100:
            maturity_stage = "DIAGNOSTIC"
        else:
            maturity_stage = "ECONOMIC_REVIEW_READY"

    data_source = "CANONICAL_PRODUCTION" if is_canonical else "DEV_WORKSPACE"
    canonical_evidence_status = "PRESENT" if (is_canonical and canary_n > 0) else ("ACCUMULATING" if is_canonical else "NOT_PRESENT")

    cost_policy_meta = get_cost_policy_metadata(P8CostPolicy.V1_PAPER_ROUNDTRIP_FEE)

    report_json = {
        "report_generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_contract": "p8_economic_evaluation_contract_v1",
        "population_type": population_type,
        "verdict_authorized": verdict_authorized,
        "diagnostic_warnings": diagnostic_warnings,
        "p8_data_integrity": p8_data_integrity,
        "p8_population_reconciliation": p8_population_reconciliation,
        "p8_accounting_reconciliation": p8_accounting_reconciliation,
        "evaluation_cutoff_utc": datetime.now(timezone.utc).isoformat(),
        "source_store_manifest_hash": post_manifest_hash,
        "snapshot_content_hash": post_content_hash,
        "cost_policy": cost_policy_meta,
        "cost_basis": cost_policy_meta["cost_basis"],
        "economic_verdict_scope": cost_policy_meta["economic_verdict_scope"],
        "policy_cost_coverage_ratio": cost_policy_meta["policy_cost_coverage_ratio"],
        "primary_population": "CURRENT_CANARY",
        "data_source": data_source,
        "canonical_runtime_evidence": canonical_evidence_status,
        "current_closed_trades": canary_n,
        "current_fills": funnel["counts"]["fills"],
        "current_closure_rate": funnel["rates"]["closure_rate"],
        "sample_maturity": maturity_stage,
        "economic_verdict": verdict_reason,
        "p8_state": "ACCUMULATING" if canary_n < 30 else "EVALUATING",
        "model_change": "NOT_AUTHORIZED",
        "funnel_analysis": funnel,
        "canary_population_report": canary_report,
        "historical_backfill_report": historical_report,
        "combined_population_report": combined_report,
        "attestation_details": attestation.metadata,
        "rejection_counts": rejection_info["counts"],
        "rejection_reasons": rejection_info["reasons"],
    }

    report_path = output_dir / "p8_economic_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_json, f, indent=2)

    return report_json


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="P8 Economic Report Generator")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--governed", action="store_true", help="Governed mode")
    mode_group.add_argument("--diagnostic", action="store_true", help="Diagnostic mode")
    parser.add_argument("--evidence-db", type=str, help="Evidence DB path")
    parser.add_argument("--reservation-db", type=str, help="Reservation DB path")
    parser.add_argument("--output-dir", type=str, help="Output directory")

    args = parser.parse_args()

    try:
        generate_report(
            evidence_store_path=args.evidence_db,
            reservation_db_path=args.reservation_db,
            output_dir=args.output_dir,
            require_evidence_eligible=args.governed or not args.diagnostic,
            governed_mode=args.governed,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
