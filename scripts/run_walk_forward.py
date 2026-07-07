#!/usr/bin/env python3
import os
import sys
import json
import argparse
from pathlib import Path
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Force UTF-8 terminal encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from btc_scraper.backtesting.config import BacktestConfig
from btc_scraper.backtesting.walk_forward import WalkForwardValidator

def main():
    config_file = REPO_ROOT / "backtest_config.json"
    if config_file.exists():
        config_data = json.loads(config_file.read_text(encoding="utf-8")).get("backtest", {})
    else:
        config_data = {}
        
    config = BacktestConfig.from_dict(config_data)
    
    signals_file = REPO_ROOT / "logs" / "adaptive_signals_v2.json"
    if not signals_file.exists():
        signals_file = REPO_ROOT / "data" / "latest_signals.json"
        
    if not signals_file.exists():
        print("❌ Cannot find any historical signals file.")
        sys.exit(1)
        
    print(f"Loading data from {signals_file}...")
    try:
        if signals_file.suffix == ".json":
            df = pd.read_json(signals_file)
        else:
            df = pd.read_parquet(signals_file)
    except Exception as e:
        print(f"❌ Error loading data: {e}")
        sys.exit(1)
        
    # Walk-forward setup
    print("\n🚀 Starting Walk-Forward validation...")
    wf_config = config.walk_forward
    validator = WalkForwardValidator(wf_config)
    results = validator.run_validation(df)
    
    # Save results
    out_dir = REPO_ROOT / "data" / "backtests" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "walk_forward_report.json"
    
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        
    print(f"✅ Walk-Forward completed. Saved report to: {out_file}")
    
    print("\n--- WALK FORWARD RESULTS ---")
    for r in results:
        print(f"Window {r['window_id']}: Train [{r['train_start']} to {r['train_end']}] | Test [{r['test_start']} to {r['test_end']}]")
        print(f"  Trades: {r['n_test']} samples | Win Rate: {r['win_rate']*100:.1f}% | PF: {r['profit_factor']:.2f} | PnL: {r['total_return']*100:.2f}%")

if __name__ == "__main__":
    main()
