#!/usr/bin/env python3
import os
import sys
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Force UTF-8 terminal encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

def main():
    latest_json = REPO_ROOT / "data" / "backtests" / "reports" / "latest_backtest.json"
    if not latest_json.exists():
        print("❌ latest_backtest.json not found. Run a backtest first.")
        sys.exit(1)
        
    with open(latest_json, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    metrics = data["metrics"]
    mc = data["monte_carlo_metrics"]
    approval = data["approval_status"]
    
    md_content = f"""# Institutional Backtesting & Validation Report

**Run ID**: {data['run_id']}  
**Generated At**: {data['timestamp']}  

## Strategy Approval Gate Status
Approval Status: **{"PASSED" if approval['passed'] else "REJECTED"}**

| Rule | Metric Value | Requirement | Status |
| --- | --- | --- | --- |
| Sharpe Ratio | {approval['rules']['sharpe']['val']:.2f} | {approval['rules']['sharpe']['target']} | {"✅ PASS" if approval['rules']['sharpe']['ok'] else "❌ FAIL"} |
| Profit Factor | {approval['rules']['profit_factor']['val']:.2f} | {approval['rules']['profit_factor']['target']} | {"✅ PASS" if approval['rules']['profit_factor']['ok'] else "❌ FAIL"} |
| Max Drawdown | {approval['rules']['max_drawdown']['val']*100:.2f}% | {approval['rules']['max_drawdown']['target']} | {"✅ PASS" if approval['rules']['max_drawdown']['ok'] else "❌ FAIL"} |
| Total Trades | {approval['rules']['min_trades']['val']} | {approval['rules']['min_trades']['target']} | {"✅ PASS" if approval['rules']['min_trades']['ok'] else "❌ FAIL"} |
| Cost Drag | {approval['rules']['cost_drag']['val']*100:.2f}% | {approval['rules']['cost_drag']['target']} | {"✅ PASS" if approval['rules']['cost_drag']['ok'] else "❌ FAIL"} |
| MC Prob of Loss | {approval['rules']['mc_prob_loss']['val']*100:.1f}% | {approval['rules']['mc_prob_loss']['target']} | {"✅ PASS" if approval['rules']['mc_prob_loss']['ok'] else "❌ FAIL"} |
| MC Prob DD > 10% | {approval['rules']['mc_prob_dd_10pct']['val']*100:.1f}% | {approval['rules']['mc_prob_dd_10pct']['target']} | {"✅ PASS" if approval['rules']['mc_prob_dd_10pct']['ok'] else "❌ FAIL"} |
| Profitable Regimes | {approval['rules']['regimes_positive']['val']} | {approval['rules']['regimes_positive']['target']} | {"✅ PASS" if approval['rules']['regimes_positive']['ok'] else "❌ FAIL"} |

## Core Performance Metrics
- **Total Return**: {metrics.get('total_return', 0.0)*100:.2f}%
- **Annualized Return**: {metrics.get('annualized_return', 0.0)*100:.2f}%
- **Annual Volatility**: {metrics.get('volatility', 0.0)*100:.2f}%
- **Sharpe Ratio**: {metrics.get('sharpe', 0.0):.2f}
- **Sortino Ratio**: {metrics.get('sortino', 0.0):.2f}
- **Max Drawdown**: {metrics.get('max_drawdown', 0.0)*100:.2f}%

## Execution & Transaction Cost drag
- **Total Costs Paid**: ${metrics.get('total_costs', 0.0):.2f}
- **Cost Drag (pct of gross PnL)**: {metrics.get('cost_drag', 0.0)*100:.2f}%
- **Average Fee paid (bps)**: {metrics.get('avg_fee_bps', 0.0):.1f}
- **Average Spread paid (bps)**: {metrics.get('avg_spread_bps', 0.0):.1f}
- **Average Slippage paid (bps)**: {metrics.get('avg_slippage_bps', 0.0):.1f}
- **Average Latency (ms)**: {metrics.get('avg_latency_ms', 0.0):.1f}

## Monte Carlo Robustness
- **5th Percentile Return**: {mc.get('p05_return', 0.0)*100:.2f}%
- **50th Percentile Return**: {mc.get('p50_return', 0.0)*100:.2f}%
- **95th Percentile Return**: {mc.get('p95_return', 0.0)*100:.2f}%
- **Risk of Ruin (50% DD)**: {mc.get('risk_of_ruin', 0.0)*100:.1f}%
"""
    
    md_file = REPO_ROOT / "data" / "backtests" / "reports" / "latest_backtest_report.md"
    with open(md_file, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    print(f"✅ Generated Markdown report at: {md_file}")

if __name__ == "__main__":
    main()
