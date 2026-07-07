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

from btc_scraper.backtesting.config import BacktestConfig
from btc_scraper.backtesting.engine import BacktestEngine
from btc_scraper.backtesting.monte_carlo import MonteCarloEngine
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
            
    # Run a baseline backtest to collect trades
    print("\n🚀 Running baseline backtest to collect trade sequence...")
    engine = BacktestEngine(config)
    res = engine.run(candles_dict, signals_data)
    
    # Run Monte Carlo
    print(f"\n🚀 Running {config.monte_carlo.get('n_simulations', 1000)} Monte Carlo simulations...")
    mc_results = MonteCarloEngine.analyze(
        trade_log=res.trades,
        initial_capital=config.initial_capital,
        n_simulations=config.monte_carlo.get("n_simulations", 1000)
    )
    
    # Save results
    out_dir = REPO_ROOT / "data" / "backtests" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "monte_carlo_report.json"
    
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(mc_results, f, indent=2)
        
    print(f"✅ Monte Carlo completed. Saved report to: {out_file}")
    
    print("\n--- MONTE CARLO ROBUSTNESS ---")
    print(f"5th Percentile Return:  {mc_results['p05_return']*100:.2f}%")
    print(f"50th Percentile Return: {mc_results['p50_return']*100:.2f}%")
    print(f"95th Percentile Return: {mc_results['p95_return']*100:.2f}%")
    print(f"Probability of Loss:    {mc_results['probability_of_loss']*100:.1f}%")
    print(f"Prob. DD > 10%:         {mc_results['probability_max_dd_gt_10pct']*100:.1f}%")
    print(f"Expected Max Drawdown:  {mc_results['expected_max_drawdown']*100:.2f}%")
    print(f"Risk of Ruin (50% DD):  {mc_results['risk_of_ruin']*100:.1f}%")

if __name__ == "__main__":
    main()
