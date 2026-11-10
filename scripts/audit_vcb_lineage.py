import json
from pathlib import Path

# 1. Inspect oos_candidate_evaluation_report.json
print("=== 1. OOS CANDIDATE EVALUATION REPORT (VCB_V1) ===")
with open("research/historical_market_replay_v5/oos_candidate_evaluation_report.json", "r", encoding="utf-8") as f:
    oos_rep = json.load(f)

vcb1 = oos_rep.get("candidates", {}).get("VOL_COMPRESSION_BREAKOUT_V1", {})
for period, pdata in vcb1.get("periods", {}).items():
    m = pdata.get("metrics", {})
    print(f"Period: {period}")
    print(f"  Executed Trades: {m.get('executed_trades_count')}")
    print(f"  Net PnL USD: {m.get('total_net_pnl_usd')}")
    print(f"  Net PnL %: {m.get('total_net_pnl_pct')}%")
    print(f"  Profit Factor: {m.get('profit_factor')}")
    print(f"  Max Drawdown %: {m.get('max_drawdown_pct')}%")
    print(f"  Net Expectancy (bps): {m.get('net_expectancy_bps')}")

# 2. Inspect vcb_economic_decomposition.json
print("\n=== 2. VCB ECONOMIC DECOMPOSITION ===")
with open("research/historical_market_replay_v5/vcb_economic_decomposition.json", "r", encoding="utf-8") as f:
    decomp = json.load(f)
print("Decomposition pipeline:", decomp.get("pipeline_name"))
for k, v in decomp.items():
    if k != "pipeline_name" and isinstance(v, dict):
        print(f"Key: {k}")
        for subk, subv in v.items():
            if isinstance(subv, (int, float, str)):
                print(f"  {subk}: {subv}")

# 3. Inspect vcb_exploratory_variants.json
print("\n=== 3. VCB EXPLORATORY VARIANTS ===")
with open("research/historical_market_replay_v5/vcb_exploratory_variants.json", "r", encoding="utf-8") as f:
    variants = json.load(f)
print("Pipeline name:", variants.get("pipeline_name"))
variants_map = variants.get("variants", {})
for vname, vdata in variants_map.items():
    print(f"\nVariant: {vname}")
    print(f"  Admission: {vdata.get('admission_verdict')}")
    print(f"  Parameters: {vdata.get('parameters')}")
    print(f"  Failure reasons: {vdata.get('rejection_reasons')}")
    if "dev_metrics" in vdata:
        dm = vdata["dev_metrics"]
        print(f"  DEV Trades: {dm.get('executed_trades_count')}, Net PnL USD: {dm.get('total_net_pnl_usd')}, Net Exp bps: {dm.get('net_expectancy_bps')}")
    if "audit_metrics" in vdata:
        am = vdata["audit_metrics"]
        print(f"  AUDIT (2026-H1) Trades: {am.get('executed_trades_count')}, Net PnL USD: {am.get('total_net_pnl_usd')}, Net Exp bps: {am.get('net_expectancy_bps')}")
