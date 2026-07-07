# Walkthrough — Phase 9 — Institutional Backtesting & Validation

We have successfully implemented the **Phase 9 — Institutional Backtesting & Validation** framework. This framework introduces strict institutional-grade constraints to assess strategy alpha, including transaction fees, bid-ask spread costs, slippage, latency models, walk-forward chronological validations, purged cross-validation, historical stress windows, synthetic shocks, and Monte Carlo simulations.

## Key Changes Made

### 1. New Backtesting Subpackage (`btc_scraper/backtesting/`)
- [__init__.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/__init__.py): Exposes core components.
- [config.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/config.py): Defines default configurations, configurations dataclass, and strategic approval gate rules.
- [cost_model.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/cost_model.py): Implements taker/maker fee models and bid-ask spread adjustments.
- [slippage_model_v1.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/slippage_model_v1.py): Computes dynamic slippage based on ATR/volatility, spread, and ADV trade size.
- [latency_model.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/latency_model.py): Simulates execution delays by delaying fills and adding price penalties.
- [engine.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/engine.py): The main Event-driven Backtest Replay Engine, which simulates entries/exits, partial takes, and cost drags.
- [vectorized_engine.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/vectorized_engine.py): A vectorized backtester for fast scans.
- [walk_forward.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/walk_forward.py): Manages rolling out-of-sample window validations.
- [purged_kfold.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/purged_kfold.py) & [embargo.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/embargo.py): Implements Marcos Lopez de Prado's Purged K-Fold Cross Validation with Embargo to prevent info leakage.
- [regime_split.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/regime_split.py): Breaks down returns and win rates per market regime.
- [stress_test.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/stress_test.py): Computes performance during LUNA, FTX, and COVID crashes, and models synthetic cost/latency shocks.
- [monte_carlo.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/monte_carlo.py): Runs 10,000 bootstrap path simulations using NumPy vectors to analyze ruin risk.
- [attribution.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/attribution.py): Details breakdowns by coin, direction, regime, and confidence.
- [report_builder.py](file:///d:/Workspaces/Vọc%20vạch/btc_scraper/backtesting/report_builder.py): Assesses metrics against gate rules.

### 2. Automation Scripts & Configurations
- [run_backtest_v2.py](file:///d:/Workspaces/Vọc%20vạch/scripts/run_backtest_v2.py): Runs full backtesting sweeps.
- [run_walk_forward.py](file:///d:/Workspaces/Vọc%20vạch/scripts/run_walk_forward.py): Slices data for rolling validations.
- [run_stress_tests.py](file:///d:/Workspaces/Vọc%20vạch/scripts/run_stress_tests.py): Executes historical/synthetic crash benchmarks.
- [run_monte_carlo.py](file:///d:/Workspaces/Vọc%20vạch/scripts/run_monte_carlo.py): Sweeps bootstrap paths.
- [generate_backtest_report.py](file:///d:/Workspaces/Vọc%20vạch/scripts/generate_backtest_report.py): Assembles final markdown summaries.
- [backtest_config.json](file:///d:/Workspaces/Vọc%20vạch/backtest_config.json): Holds parameters config.

### 3. API & Web UI Integration
- [server.py](file:///d:/Workspaces/Vọc%20vạch/api/server.py): Adds backtesting execution endpoints and historical run endpoints.
- [App.jsx](file:///d:/Workspaces/Vọc%20vạch/web/src/App.jsx): Integrates a rich "Backtesting" tab into the React dashboard, offering configurator controls, run progress polling, checklist statuses, and metrics split tables.

---

## Verification Results

### 1. Automated Tests
We wrote a comprehensive test suite in [test_phase9_backtesting.py](file:///d:/Workspaces/Vọc%20vạch/tests/test_phase9_backtesting.py) covering fee models, spread fill, dynamic slippage calculations, latency price penalties, purged kfold overlaps, embargo filters, Monte Carlo bootstrap outputs, and report gate evaluations.

Running the tests completes successfully:
```powershell
.venv\Scripts\pytest tests/test_phase9_backtesting.py -v
```
All **7 tests passed** successfully.

### 2. Manual Execution Run
Running a backtest end-to-end:
```powershell
python scripts/run_backtest_v2.py
```
Outputs standard institutional summaries, performs 1,000 Monte Carlo bootstrap paths, sweeps LUNA/FTX/COVID stress windows, and saves the detailed result JSON reports under `data/backtests/runs/`.
