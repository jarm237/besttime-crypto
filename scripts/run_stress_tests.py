#!/usr/bin/env python3
import os
import sys
import json
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
from btc_scraper.backtesting.engine import BacktestEngine
from btc_scraper.backtesting.stress_test import StressTestEngine
from scripts.generate_triple_barrier_labels import load_candles_for_coin

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
        
    with open(signals_file, "r", encoding="utf-8") as f:
        signals_data = json.load(f)
    if isinstance(signals_data, dict) and "records" in signals_data:
        signals_data = signals_data["records"]
        
    # Limit coins
    coins = config.coins
    signals_data = [s for s in signals_data if s["coin"] in coins]
    
    # Load candles
    data_dir = REPO_ROOT / "data" / "fresh_training_data_2023_2026"
    candles_dict = {}
    for coin in coins:
        df_candles = load_candles_for_coin(data_dir, coin, config.timeframe)
        if not df_candles.empty:
            candles_dict[coin] = df_candles.rename(columns={"timestamp": "time"}).to_dict(orient="records")
            
    # Run Stress Tests
    print("\n🚀 Running Stress Tests (Historical & Synthetic Shocks)...")
    engine = BacktestEngine(config)
    results = StressTestEngine.analyze(engine, candles_dict, signals_data)
    
    # Save results
    out_dir = REPO_ROOT / "data" / "backtests" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "stress_tests_report.json"
    
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        
    print(f"✅ Stress tests completed. Saved report to: {out_file}")
    
    print("\n--- HISTORICAL STRESS WINDOWS ---")
    for name, stats in results["historical"].items():
        if stats.get("status") == "skipped":
            print(f"{name}: Skipped ({stats.get('reason')})")
        elif stats.get("status") == "completed":
            print(f"{name}: Return: {stats['total_return']*100:.2f}% | Max DD: {stats['max_drawdown']*100:.2f}% | Trades: {stats['n_trades']}")
            
    print("\n--- SYNTHETIC SHOCKS ---")
    for name, stats in results["synthetic"].items():
        if stats.get("status") == "completed":
            print(f"{name}: Return: {stats['total_return']*100:.2f}% | Max DD: {stats['max_drawdown']*100:.2f}% | Costs: ${stats['total_costs']:.2f}")

if __name__ == "__main__":
    main()
