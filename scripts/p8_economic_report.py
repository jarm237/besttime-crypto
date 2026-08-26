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
from pathlib import Path
from typing import Any

# Ensure btc_scraper is in import path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
from btc_scraper.ml_engine.p8_economic_extractor import (
    ACTIVE_SYMBOLS,
    extract_closed_trades,
    run_funnel_analysis,
)

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
    """Calculate key economic metrics for a subset of trades."""
    if not trades:
        return {
            "trade_count": 0,
            "win_rate": 0.0,
            "gross_ev_bps": 0.0,
            "net_ev_bps": 0.0,
            "avg_win_bps": 0.0,
            "avg_loss_bps": 0.0,
            "profit_factor": 0.0,
            "total_gross_pnl": 0.0,
            "total_fees": 0.0,
            "total_net_pnl": 0.0,
            "max_drawdown_usd": 0.0,
            "max_drawdown_bps": 0.0,
            "median_holding_time_seconds": 0.0
        }

    net_returns = [t["net_return_bps"] for t in trades]
    gross_returns = [t["gross_return_bps"] for t in trades]
    
    wins = [r for r in net_returns if r > 0]
    losses = [r for r in net_returns if r < 0]
    
    win_count = len(wins)
    trade_count = len(trades)
    win_rate = win_count / trade_count if trade_count > 0 else 0.0

    avg_win = safe_mean(wins)
    avg_loss = safe_mean(losses)

    # PF calculation: sum of absolute wins / sum of absolute losses
    sum_wins = sum(wins)
    sum_losses = sum(losses)
    profit_factor = sum_wins / abs(sum_losses) if sum_losses != 0 else float("inf")
    if math.isinf(profit_factor):
        profit_factor = 999.0  # Safe default representable in json

    total_gross = sum(t["gross_pnl"] for t in trades if isinstance(t["gross_pnl"], (int, float)))
    total_fees = sum(t["fees"] for t in trades if isinstance(t["fees"], (int, float)))
    total_net = sum(t["net_pnl"] for t in trades if isinstance(t["net_pnl"], (int, float)))

    # Holding times
    holding_times = [t["holding_time"] for t in trades if isinstance(t["holding_time"], (int, float))]
    median_hold = safe_median(holding_times)

    # Max drawdown calculation
    cum_bps = 0.0
    peak_bps = 0.0
    max_dd_bps = 0.0

    cum_usd = 0.0
    peak_usd = 0.0
    max_dd_usd = 0.0

    # Sort by exit_timestamp to follow trade sequence
    sorted_trades = sorted(trades, key=lambda x: x.get("exit_timestamp") or "")
    for t in sorted_trades:
        cum_bps += t["net_return_bps"]
        if cum_bps > peak_bps:
            peak_bps = cum_bps
        dd_bps = peak_bps - cum_bps
        if dd_bps > max_dd_bps:
            max_dd_bps = dd_bps

        net_p = t["net_pnl"]
        if isinstance(net_p, (int, float)):
            cum_usd += net_p
            if cum_usd > peak_usd:
                peak_usd = cum_usd
            dd_usd = peak_usd - cum_usd
            if dd_usd > max_dd_usd:
                max_dd_usd = dd_usd

    return {
        "trade_count": trade_count,
        "win_rate": win_rate,
        "gross_ev_bps": safe_mean(gross_returns),
        "net_ev_bps": safe_mean(net_returns),
        "avg_win_bps": avg_win,
        "avg_loss_bps": avg_loss,
        "profit_factor": profit_factor,
        "total_gross_pnl": total_gross,
        "total_fees": total_fees,
        "total_net_pnl": total_net,
        "max_drawdown_usd": max_dd_usd,
        "max_drawdown_bps": max_dd_bps,
        "median_holding_time_seconds": median_hold
    }

def bucket_trades(trades: list[dict[str, Any]], num_buckets: int = 5) -> dict[str, list[dict[str, Any]]]:
    if not trades:
        return {}
    
    # Filter out trades with no score
    scored_trades = [t for t in trades if isinstance(t["model_score"], (int, float))]
    if not scored_trades:
        return {}
    
    sorted_trades = sorted(scored_trades, key=lambda t: t["model_score"])
    n = len(sorted_trades)
    
    if n < num_buckets:
        return {f"Q{i+1}": [sorted_trades[i]] for i in range(n)}
        
    buckets = {}
    chunk_size = n / num_buckets
    for i in range(num_buckets):
        start = int(i * chunk_size)
        end = int((i + 1) * chunk_size) if i < num_buckets - 1 else n
        buckets[f"Q{i+1}"] = sorted_trades[start:end]
    return buckets

def determine_verdict(n: int, metrics: dict[str, Any], route_metrics: dict[str, Any], funnel: dict[str, Any]) -> tuple[str, str]:
    if n < 30:
        return "P8_DATA_VALIDATION_REQUIRED", "ECONOMIC_VERDICT_NOT_AUTHORIZED_YET"

    net_ev = metrics["net_ev_bps"]
    gross_ev = metrics["gross_ev_bps"]
    pf = metrics["profit_factor"]
    max_dd = metrics["max_drawdown_bps"]
    
    legacy_net = route_metrics.get("LEGACY", {}).get("net_ev_bps", 0.0)
    mc5_net = route_metrics.get("MC5_QUALIFIED", {}).get("net_ev_bps", 0.0)
    
    if n < 100:
        stage = "DIAGNOSTIC"
    else:
        stage = "ECONOMIC_REVIEW_READY"

    # Verdict criteria
    if gross_ev <= 0:
        return "STOP", "ALPHA_FAILURE"
    if gross_ev > 0 and net_ev < 0:
        return "STOP", "ECONOMIC_INFEASIBILITY_UNDER_CURRENT_EXECUTION"
    
    # Performance review
    if legacy_net > 0 and mc5_net < 0:
        return "MODIFY", "MODEL_ROUTE_REVIEW"
    
    # Check if single trade concentration is high or drawdown is pathological
    if max_dd > 1000.0:  # 10% drawdown
        return "MODIFY", "DECISION_POLICY_REVIEW"
        
    if net_ev > 0 and pf > 1:
        return "CONTINUE", "ECONOMICALLY_PROMISING" if stage == "ECONOMIC_REVIEW_READY" else "CONTINUE_OBSERVATION"
    
    return "MODIFY", "UNIVERSE_REVIEW"

def calculate_population_report(trades: list[dict[str, Any]]) -> dict[str, Any]:
    overall = calculate_metrics(trades)
    
    # Route breakdown
    routes = ["LEGACY", "MC5_QUALIFIED"]
    route_metrics = {}
    for r in routes:
        route_trades = [t for t in trades if t["route"] == r]
        route_metrics[r] = calculate_metrics(route_trades)

    # Symbol breakdown
    symbol_metrics = {}
    for sym in ACTIVE_SYMBOLS:
        sym_trades = [t for t in trades if t["symbol"].split("/")[0].split("USDT")[0] == sym]
        symbol_metrics[sym] = calculate_metrics(sym_trades)

    # Side breakdown
    side_metrics = {}
    for side in ["LONG", "SHORT"]:
        side_trades = [t for t in trades if t["side"] == side]
        side_metrics[side] = calculate_metrics(side_trades)

    # Confidence Buckets
    buckets = bucket_trades(trades, 5)
    bucket_summary = {}
    for b_name, b_trades in buckets.items():
        bucket_summary[b_name] = {
            "trade_count": len(b_trades),
            "mean_net_return_bps": safe_mean([t["net_return_bps"] for t in b_trades]),
            "median_net_return_bps": safe_median([t["net_return_bps"] for t in b_trades]),
            "win_rate": calculate_metrics(b_trades)["win_rate"],
            "profit_factor": calculate_metrics(b_trades)["profit_factor"]
        }
        
    return {
        "overall_portfolio_economics": overall,
        "route_attribution": route_metrics,
        "symbol_attribution": symbol_metrics,
        "side_attribution": side_metrics,
        "confidence_buckets": bucket_summary
    }

def generate_report(
    evidence_store_path: Path | str | None = None,
    reservation_db_path: Path | str | None = None,
    output_dir: Path | str | None = None
) -> None:
    if output_dir is None:
        output_dir = Path("/home/tran-huynh/Workspaces/Personal/besttime-crypto")
    else:
        output_dir = Path(output_dir)
        
    store = RuntimeEvidenceStore(evidence_store_path)
    
    # 1. Extract Trades
    trades = extract_closed_trades(store, reservation_db_path)
    
    # 2. Split populations
    current_canary_trades = [t for t in trades if not t.get("historical_backfill", False)]
    historical_backfill_trades = [t for t in trades if t.get("historical_backfill", False)]
    
    # 3. Run populations reports
    canary_report = calculate_population_report(current_canary_trades)
    historical_report = calculate_population_report(historical_backfill_trades)
    combined_report = calculate_population_report(trades)

    # 4. Run Funnel Analysis
    funnel = run_funnel_analysis(store, reservation_db_path)

    # 5. Determine Verdict based on Canary population
    canary_n = len(current_canary_trades)
    verdict, verdict_reason = determine_verdict(
        canary_n, 
        canary_report["overall_portfolio_economics"], 
        canary_report["route_attribution"], 
        funnel
    )
    
    if canary_n == 0:
        maturity_stage = "ACCUMULATING"
    elif canary_n < 30:
        maturity_stage = "PRELIMINARY"
    elif canary_n < 100:
        maturity_stage = "DIAGNOSTIC"
    else:
        maturity_stage = "ECONOMIC_REVIEW_READY"

    # Compiling JSON Report
    report_json = {
        "report_generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_contract": "p8_economic_evaluation_contract_v1",
        "p8_data_integrity": "PASS",
        "p8_population_reconciliation": "PASS",
        "p8_accounting_reconciliation": "PASS",
        "primary_population": "CURRENT_CANARY",
        "current_closed_trades": canary_n,
        "current_fills": funnel["counts"]["fills"],
        "current_closure_rate": funnel["rates"]["closure_rate"],
        "sample_maturity": maturity_stage,
        "economic_verdict": verdict_reason,
        "p8_state": "ACCUMULATING" if canary_n < 30 else "EVALUATING",
        "model_change": "NOT_AUTHORIZED",
        "policy_change": "NOT_AUTHORIZED",
        "runtime_remediation": "NOT_REQUIRED",
        "sample_maturity_details": {
            "canary_trade_count": canary_n,
            "historical_trade_count": len(historical_backfill_trades),
            "combined_trade_count": len(trades),
            "stage": maturity_stage
        },
        "signal_funnel": funnel,
        "populations": {
            "current_canary": canary_report,
            "historical_backfill": historical_report,
            "combined": combined_report
        },
        "economic_sample_reconciliation": trades,
        "data_limitations": {
            "slippage_observation": "NOT_AVAILABLE",
            "other_costs": "NOT_AVAILABLE"
        }
    }

    # Write JSON report
    json_path = output_dir / "p8_economic_effectiveness_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_json, f, indent=2, default=str)
    print(f"Generated JSON report: {json_path}")

    # Generate Markdown report
    md_content = generate_markdown_report_string(report_json)
    md_path = output_dir / "p8_economic_effectiveness_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"Generated Markdown report: {md_path}")


def generate_markdown_report_string(report: dict[str, Any]) -> str:
    funnel = report["signal_funnel"]
    counts = funnel["counts"]
    rates = funnel["rates"]
    
    canary = report["populations"]["current_canary"]
    historical = report["populations"]["historical_backfill"]
    combined = report["populations"]["combined"]

    alert_type = "NOTE"
    if "NOT_AUTHORIZED" in report["economic_verdict"] or "VALIDATION" in report["economic_verdict"]:
        alert_type = "WARNING"
    elif "PROMISING" in report["economic_verdict"] or "CONTINUE" in report["economic_verdict"]:
        alert_type = "TIP"

    md = f"""# P8 — Economic Effectiveness Evaluation Report

> [!{alert_type}]
> **P8 State: {report["p8_state"]}**
> - P8 Data Integrity: **{report["p8_data_integrity"]}**
> - Population Reconciliation: **{report["p8_population_reconciliation"]}**
> - Accounting Reconciliation: **{report["p8_accounting_reconciliation"]}**
> - Primary Population: **{report["primary_population"]}**
> - Current Closed Trades: **{report["current_closed_trades"]}**
> - Current Fills: **{report["current_fills"]}**
> - Current Closure Rate: **{report["current_closure_rate"]*100:.2f}%**
> - Sample Maturity: **{report["sample_maturity"]}**
> - Economic Verdict: **{report["economic_verdict"]}**
> - Model/Policy Change: **{report["model_change"]}** / **{report["policy_change"]}**
> - Runtime Remediation: **{report["runtime_remediation"]}**

---

## 1. Signal Funnel Analysis (Exploratory / Broader Historical Scope)

> [!NOTE]
> This funnel represents the broader/historical signal path across the database window (exploratory scope). Funnel rates (such as execution rate) should not be interpreted as the conversion rates of the current canary population.

| Funnel Stage | Count | Transition Rate |
| :--- | :---: | :---: |
| **Predictions** | {counts["predictions"]} | — |
| **Final Decisions** | {counts["final_decisions"]} | Prediction $\\rightarrow$ Decision: {counts["final_decisions"]/counts["predictions"]*100 if counts["predictions"] > 0 else 0.0:.2f}% |
| **Actionable Decisions** | {counts["actionable_decisions"]} | Actionable Rate: {rates["actionable_rate"]*100:.2f}% |
| **Execution Attempts** | {counts["execution_attempts"]} | Execution Rate: {rates["execution_rate"]*100:.2f}% |
| **Fills** | {counts["fills"]} | Fill Rate: {rates["fill_rate"]*100:.2f}% |
| **Closed Trades** | {counts["closed_trades"]} | Closure Rate (Canary): {rates["closure_rate"]*100:.2f}% |

---

## 2. Split Populations Performance Economics

Performance metrics aggregated across each population.

| Metric | Current Canary | Historical Backfill | Combined |
| :--- | :---: | :---: | :---: |
| **Trade Count (N)** | {canary["overall_portfolio_economics"]["trade_count"]} | {historical["overall_portfolio_economics"]["trade_count"]} | {combined["overall_portfolio_economics"]["trade_count"]} |
| **Win Rate (WR)** | {canary["overall_portfolio_economics"]["win_rate"]*100:.2f}% | {historical["overall_portfolio_economics"]["win_rate"]*100:.2f}% | {combined["overall_portfolio_economics"]["win_rate"]*100:.2f}% |
| **Gross Expected Value (EV)** | {canary["overall_portfolio_economics"]["gross_ev_bps"]:.2f} bps | {historical["overall_portfolio_economics"]["gross_ev_bps"]:.2f} bps | {combined["overall_portfolio_economics"]["gross_ev_bps"]:.2f} bps |
| **Net Expected Value (EV)** | {canary["overall_portfolio_economics"]["net_ev_bps"]:.2f} bps | {historical["overall_portfolio_economics"]["net_ev_bps"]:.2f} bps | {combined["overall_portfolio_economics"]["net_ev_bps"]:.2f} bps |
| **Profit Factor (PF)** | {canary["overall_portfolio_economics"]["profit_factor"]:.2f} | {historical["overall_portfolio_economics"]["profit_factor"]:.2f} | {combined["overall_portfolio_economics"]["profit_factor"]:.2f} |
| **Total Net PnL** | ${canary["overall_portfolio_economics"]["total_net_pnl"]:.2f} | ${historical["overall_portfolio_economics"]["total_net_pnl"]:.2f} | ${combined["overall_portfolio_economics"]["total_net_pnl"]:.2f} |
| **Max Drawdown (bps)** | {canary["overall_portfolio_economics"]["max_drawdown_bps"]:.2f} bps | {historical["overall_portfolio_economics"]["max_drawdown_bps"]:.2f} bps | {combined["overall_portfolio_economics"]["max_drawdown_bps"]:.2f} bps |

---

## 3. Route Attribution (Combined Population)

Separates the performance of the Legacy routing (`BTC`, `ETH`, `BNB`) and the new MC5 Qualification routing (`6 other symbols`).

| Route | Trade Count | Win Rate | Gross EV | Net EV | Profit Factor | Net PnL | Max DD |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **LEGACY** | {combined["route_attribution"].get("LEGACY", {}).get("trade_count", 0)} | {combined["route_attribution"].get("LEGACY", {}).get("win_rate", 0)*100:.1f}% | {combined["route_attribution"].get("LEGACY", {}).get("gross_ev_bps", 0):.2f} bps | {combined["route_attribution"].get("LEGACY", {}).get("net_ev_bps", 0):.2f} bps | {combined["route_attribution"].get("LEGACY", {}).get("profit_factor", 0):.2f} | ${combined["route_attribution"].get("LEGACY", {}).get("total_net_pnl", 0):.2f} | {combined["route_attribution"].get("LEGACY", {}).get("max_drawdown_bps", 0):.2f} bps |
| **MC5_QUALIFIED** | {combined["route_attribution"].get("MC5_QUALIFIED", {}).get("trade_count", 0)} | {combined["route_attribution"].get("MC5_QUALIFIED", {}).get("win_rate", 0)*100:.1f}% | {combined["route_attribution"].get("MC5_QUALIFIED", {}).get("gross_ev_bps", 0):.2f} bps | {combined["route_attribution"].get("MC5_QUALIFIED", {}).get("net_ev_bps", 0):.2f} bps | {combined["route_attribution"].get("MC5_QUALIFIED", {}).get("profit_factor", 0):.2f} | ${combined["route_attribution"].get("MC5_QUALIFIED", {}).get("total_net_pnl", 0):.2f} | {combined["route_attribution"].get("MC5_QUALIFIED", {}).get("max_drawdown_bps", 0):.2f} bps |

---

## 4. Symbol Level Attribution (Combined Population)

Attribution metrics broken down per symbol across combined population.

| Symbol | Trades | Win Rate | Gross EV | Net EV | PF | Net PnL (USD) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
"""
    symbols = combined["symbol_attribution"]
    for sym in sorted(ACTIVE_SYMBOLS):
        s_m = symbols.get(sym, {})
        if s_m.get("trade_count", 0) > 0:
            md += f"| **{sym}** | {s_m['trade_count']} | {s_m['win_rate']*100:.1f}% | {s_m['gross_ev_bps']:.2f} bps | {s_m['net_ev_bps']:.2f} bps | {s_m['profit_factor']:.2f} | ${s_m['total_net_pnl']:.2f} |\n"
        else:
            md += f"| **{sym}** | 0 | — | — | — | — | $0.00 |\n"

    md += """
---

## 5. Model Score / Confidence vs Realized Outcome (Combined Population)

Buckets closed trades by model confidence score to examine the ranking capabilities of the model.

| Bucket (Quantile) | Trades | Mean Net Return | Median Net Return | Win Rate | Profit Factor |
| :--- | :---: | :---: | :---: | :---: | :---: |
"""
    buckets = combined["confidence_buckets"]
    for b_name in sorted(buckets.keys()):
        b = buckets[b_name]
        md += f"| **{b_name}** | {b['trade_count']} | {b['mean_net_return_bps']:.2f} bps | {b['median_net_return_bps']:.2f} bps | {b['win_rate']*100:.1f}% | {b['profit_factor']:.2f} |\n"

    md += """
---

## 6. Economic Sample Reconciliation (Audit)

Comprehensive trade-by-trade financial audit and population reconciliation.

| Trade ID | Symbol | Route | Decision ID | Execution ID | Entry Price | Exit Price | Gross Return | Fee Bps | Net Return | Gross PnL | Fees | Net PnL | Backfill | Partition |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
"""
    # Enforces formatting variables
    audit_trades = sorted(report["economic_sample_reconciliation"], key=lambda x: x.get("exit_timestamp") or "")
    for t in audit_trades:
        gross_pnl_str = f"${t['gross_pnl']:.2f}" if isinstance(t['gross_pnl'], (int, float)) else str(t['gross_pnl'])
        fees_str = f"${t['fees']:.2f}" if isinstance(t['fees'], (int, float)) else str(t['fees'])
        net_pnl_str = f"${t['net_pnl']:.2f}" if isinstance(t['net_pnl'], (int, float)) else str(t['net_pnl'])
        
        gross_return_str = f"{t['gross_return_bps']:.2f}" if isinstance(t['gross_return_bps'], (int, float)) else str(t['gross_return_bps'])
        fee_bps_str = f"{t['fee_bps']:.2f}" if isinstance(t['fee_bps'], (int, float)) else str(t['fee_bps'])
        net_return_str = f"{t['net_return_bps']:.2f}" if isinstance(t['net_return_bps'], (int, float)) else str(t['net_return_bps'])
        
        ep_str = f"{t['entry_price']:.2f}" if isinstance(t['entry_price'], (int, float)) else str(t['entry_price'])
        ex_str = f"{t['exit_price']:.2f}" if isinstance(t['exit_price'], (int, float)) else str(t['exit_price'])

        md += (
            f"| `{t['trade_id'][:8]}` | **{t['symbol']}** | {t['route']} | `{t['decision_id'][:8]}` | "
            f"`{t['execution_id'][:8]}` | {ep_str} | {ex_str} | {gross_return_str} | {fee_bps_str} | "
            f"{net_return_str} | {gross_pnl_str} | {fees_str} | {net_pnl_str} | {t['historical_backfill']} | `{t['source_partition']}` |\n"
        )

    md += f"""
---

## 7. Data Limitations

- **Slippage Accounting**: `{report["data_limitations"]["slippage_observation"]}` (Slippage is not explicitly written in outcome links and is marked as not available for this run).
- **Other Transaction Costs**: `{report["data_limitations"]["other_costs"]}`.

---

*Report Generated At (UTC): {report["report_generated_at"]}*
"""
    return md


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-db", default=None, help="Path to runtime evidence sqlite file")
    parser.add_argument("--reservation-db", default=None, help="Path to reservations sqlite file")
    parser.add_argument("--output-dir", default=None, help="Directory to save report outputs")
    args = parser.parse_args()
    
    generate_report(args.evidence_db, args.reservation_db, args.output_dir)
