#!/usr/bin/env python3
import os
import sys
import json
import argparse
from pathlib import Path
import pandas as pd

# Insert project path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Force UTF-8 terminal encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from btc_scraper.backtesting.config import BacktestConfig
from btc_scraper.backtesting.engine import BacktestEngine
from scripts.generate_triple_barrier_labels import load_candles_for_coin

def run_backtest_pipeline(config_data: dict = None, output_path: str = None) -> dict:
    # 1. Load config
    if config_data is None:
        config_file = REPO_ROOT / "backtest_config.json"
        if config_file.exists():
            config_data = json.loads(config_file.read_text(encoding="utf-8")).get("backtest", {})
        else:
            config_data = {}
            
    config = BacktestConfig.from_dict(config_data)
    
    # 2. Load signals
    signals_file = REPO_ROOT / "logs" / "adaptive_signals_v2.json"
    if not signals_file.exists():
        signals_file = REPO_ROOT / "data" / "latest_signals.json"
        
    if not signals_file.exists():
        print("❌ Cannot find any historical signals file. Run pipeline first.")
        sys.exit(1)
        
    print(f"Loading signals from {signals_file}...")
    try:
        if signals_file.suffix == ".json":
            with open(signals_file, "r", encoding="utf-8") as f:
                signals_data = json.load(f)
            # Ensure it is a list of records
            if isinstance(signals_data, dict) and "records" in signals_data:
                signals_data = signals_data["records"]
            elif isinstance(signals_data, dict):
                # Maybe map of coins
                signals_data = list(signals_data.values())
        else:
            df_sigs = pd.read_parquet(signals_file)
            signals_data = df_sigs.to_dict(orient="records")
    except Exception as e:
        print(f"❌ Error loading signals: {e}")
        sys.exit(1)
        
    # Limit coins to config
    coins = config.coins
    signals_data = [s for s in signals_data if s["coin"] in coins]
    if not signals_data:
        print(f"❌ No signals matching coins: {coins}")
        sys.exit(1)
        
    # 3. Load historical candles
    data_dir = REPO_ROOT / "data" / "fresh_training_data_2023_2026"
    candles_dict = {}
    print(f"Loading candles for coins: {coins} from {data_dir}...")
    
    for coin in coins:
        df_candles = load_candles_for_coin(data_dir, coin, config.timeframe)
        if df_candles.empty:
            # try data root
            df_candles = load_candles_for_coin(REPO_ROOT / "data", coin, config.timeframe)
            
        if not df_candles.empty:
            # Convert to list of dicts with standard keys
            candles_dict[coin] = df_candles.rename(columns={"timestamp": "time"}).to_dict(orient="records")
            print(f"  ↳ {coin}: Loaded {len(candles_dict[coin])} candles")
        else:
            print(f"  ⚠️ Warning: No candles found for {coin}")
            
    if not candles_dict:
        print("❌ No historical candles loaded. Exiting.")
        sys.exit(1)
        
    # 4. Instantiate and run engine
    print("\n🚀 Running institutional backtest engine...")
    engine = BacktestEngine(config)
    res = engine.run(candles_dict, signals_data)
    
    # 5. Persist run result
    run_dir = REPO_ROOT / "data" / "backtests" / "runs"
    report_dir = REPO_ROOT / "data" / "backtests" / "reports"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    
    result_dict = res.to_dict()
    
    run_file = run_dir / f"run_{res.run_id}.json"
    with open(run_file, "w", encoding="utf-8") as f:
        json.dump(result_dict, f, default=str, indent=2)
        
    latest_report_file = report_dir / "latest_backtest.json"
    with open(latest_report_file, "w", encoding="utf-8") as f:
        json.dump(result_dict, f, default=str, indent=2)
        
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result_dict, f, default=str, indent=2)

    print(f"✅ Backtest completed successfully. Run ID: {res.run_id}")
    print(f"   Saved details to: {run_file}")
    print(f"   Saved latest to: {latest_report_file}")
    
    print("\n--- RESULTS SUMMARY ---")
    metrics = res.metrics
    print(f"Total Return:       {metrics.get('total_return', 0.0)*100:.2f}%")
    print(f"Annualized Return:  {metrics.get('annualized_return', 0.0)*100:.2f}%")
    print(f"Max Drawdown:       {metrics.get('max_drawdown', 0.0)*100:.2f}%")
    print(f"Sharpe Ratio:       {metrics.get('sharpe', 0.0):.2f}")
    print(f"Profit Factor:      {metrics.get('profit_factor', 0.0):.2f}")
    print(f"Total Trades:       {metrics.get('n_trades', 0)}")
    print(f"Cost Drag:          {metrics.get('cost_drag', 0.0)*100:.2f}%")
    print(f"Approval Status:    {'PASSED ✅' if res.approval_status.get('passed') else 'REJECTED ❌'}")
    
    return result_dict

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Phase 9 Institutional Backtest")
    parser.add_argument("--config", help="JSON string config override")
    parser.add_argument("--output", help="Path to save output JSON")
    args = parser.parse_args()
    
    config_override = None
    if args.config:
        try:
            config_override = json.loads(args.config)
        except Exception as e:
            print(f"Failed to parse override config: {e}")
            
    run_backtest_pipeline(config_data=config_override, output_path=args.output)
