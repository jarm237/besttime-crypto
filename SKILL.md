# Multi-coin OHLCV Scraper & Analyzer - AI Agent Skill Guide

This file serves as a **Skill and Instructions Guide** for AI agents (such as Google Antigravity, Claude, or Copilot) interacting with this codebase. It provides system context, architecture details, and step-by-step workflows for maintaining, running, and expanding the project.

---

## 📋 Project Overview

A Python-based multi-coin OHLCV scraper, technical analyzer, AI analyst, and automated signal bot.

- **Data Source:** Binance Public API (`/api/v3/klines`) — no API key required.
- **Timeframes:** Primary 15m for signals; 1h / 4h / 1d fetched for Gemini AI multi-timeframe context.
- **Coins tracked:** Configurable via `btc_scraper/config.py` → `COINS` list.
- **Core Loop:** Two-track scheduler:
  1. **General scan (every 15 mins, offset +1 min after close):** Fetches all coins, computes all indicators, sends Telegram signal alert, enqueues Gemini AI analysis in background thread.
  2. **Focused scan (every 5 mins, interleaved):** Only fetches coins with open positions — evaluates TP/SL hits and reversal warnings without calling AI to save quota.
- **Robustness:** Auto-restart with exponential backoff (`BASE_BACKOFF=10s`, `MAX_BACKOFF=300s`, `MAX_RETRIES=5`) for network errors; scheduler crash recovery.
- **Reinforcement Learning:** Phase 4 RL Exit Manager added with gymnasium + stable-baselines3 for adaptive exit decisions.
- **Portfolio Optimization & Multi-Agent AI:** Phase 5 added with Mean-Variance Optimization, Risk Parity, and modular Agent system coordinated by AgentOrchestrator.

---

## 🛠️ Technology Stack & Dependencies

- **Runtime:** Python 3.10+
- **Key Packages** (`requirements.txt`):
  - `requests` — HTTP calls to Binance API.
  - `schedule` — Cron-style task scheduling.
  - `rich` — Beautiful terminal output rendering.
  - `python-dotenv` — `.env` file loading.
  - `google-genai` — Gemini AI (Flash model) integration.
  - `fastapi` + `uvicorn` — Backend REST API for Web Dashboard.
  - `pandas`, `scikit-learn`, `joblib`, `numpy` - Machine Learning & Adaptive Scoring.
  - `gymnasium`, `stable-baselines3`, `torch` - Reinforcement Learning exit manager.
  - `ccxt` — Integration with crypto exchanges (Binance Testnet).
  - *No `ta-lib` are used.* All technical indicators are implemented in pure Python within `btc_scraper/analysis.py` for maximum speed and simplicity.
- **Frontend:** React / Vite in `web/`, served at port 3000.

---

## 📁 Key Files & Modules

> **Đường dẫn theo môi trường:**
> - 🐧 **Ubuntu**: `/home/tran-huynh/Workspaces/Personal/besttime-crypto/`
> - 🪟 **Windows**: `d:/Workspaces/Vọc vạch/`

| File | 🐧 Ubuntu | 🪟 Windows | Purpose |
|------|-----------|-----------|---------|
| `main.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/main.py) | [Windows](file:///d:/Workspaces/Vọc vạch/main.py) | Entry point, scheduler, AI worker thread, position evaluation loop, and auto-trade programmatic close loop |
| `btc_scraper/config.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/config.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/config.py) | `COINS`, `INTERVAL`, `LIMIT`, API keys (round-robin Gemini keys) |
| `btc_scraper/analysis.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/analysis.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/analysis.py) | All indicator math + 6-layer signal logic + TP/SL formula |
| `btc_scraper/sentiment.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/sentiment.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/sentiment.py) | Fear & Greed Index from alternative.me (cached 1h) |
| `btc_scraper/ai_analyst.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/ai_analyst.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/ai_analyst.py) | Gemini AI prompt builder — MTF data, sentiment, RAG from closed trades |
| `btc_scraper/position_tracker.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/position_tracker.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/position_tracker.py) | Tracks manual open/closed positions and generates trade recommendations. |
| `btc_scraper/auto_trader.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/auto_trader.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/auto_trader.py) | Auto-trading decision engine (risk management, circuit breaker, daily caps) |
| `btc_scraper/rl_trading_env.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/rl_trading_env.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/rl_trading_env.py) | Gymnasium environment for RL exit management |
| `train_rl_exit_manager.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/train_rl_exit_manager.py) | [Windows](file:///d:/Workspaces/Vọc vạch/train_rl_exit_manager.py) | RL training script (PPO/DQN/A2C) |
| `evaluate_rl_phase4.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/evaluate_rl_phase4.py) | [Windows](file:///d:/Workspaces/Vọc vạch/evaluate_rl_phase4.py) | RL evaluation and rule-based comparison |
| `PHASE_4_RL_DOCUMENTATION.md` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/PHASE_4_RL_DOCUMENTATION.md) | [Windows](file:///d:/Workspaces/Vọc vạch/PHASE_4_RL_DOCUMENTATION.md) | Phase 4 RL implementation summary |
| `btc_scraper/portfolio_manager.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/portfolio_manager.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/portfolio_manager.py) | Portfolio Manager (MVO, Risk Parity) |
| `btc_scraper/multi_agent.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/multi_agent.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/multi_agent.py) | Multi-Agent AI system and Orchestrator |
| `tests/test_portfolio_manager.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/tests/test_portfolio_manager.py) | [Windows](file:///d:/Workspaces/Vọc vạch/tests/test_portfolio_manager.py) | Unit tests for portfolio allocation |
| `btc_scraper/ccxt_client.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/ccxt_client.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/ccxt_client.py) | CCXT exchange abstraction layer for Binance Testnet (Spot) |
| `btc_scraper/meta_model.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/meta_model.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/meta_model.py) | Trains the Meta Confidence model and calculates sigmoid probability calibration buckets |
| `btc_scraper/adaptive_scoring.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/adaptive_scoring.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/adaptive_scoring.py) | Machine Learning pipeline for training win probability models. |
| `btc_scraper/signal_score.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/signal_score.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/signal_score.py) | Fuzzy logic and ML inference to assign live probability and dynamic position sizing. |
| `btc_scraper/exchanges/binance.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/exchanges/binance.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/exchanges/binance.py) | Binance OHLCV fetcher (`fetch_ohlcv`, `fetch_ohlcv_tf`, `fetch_ohlcv_multi_tf`) |
| `btc_scraper/telegram_bot.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/telegram_bot.py) | [Windows](file:///d:/Workspaces/Vọc vạch/btc_scraper/telegram_bot.py) | Telegram broadcaster (signals, AI report, position recommendations) |
| `api/server.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/api/server.py) | [Windows](file:///d:/Workspaces/Vọc vạch/api/server.py) | FastAPI REST backend — serves signals, positions, performance, and auto-trade logs/status |
| `train_april_model.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/train_april_model.py) | [Windows](file:///d:/Workspaces/Vọc vạch/train_april_model.py) | Trains the Random Forest Adaptive Model on 18-month historical data |
| `fetch_historical_range.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/fetch_historical_range.py) | [Windows](file:///d:/Workspaces/Vọc vạch/fetch_historical_range.py) | Scrapes custom range of historical data from Binance (e.g. 18-month data) |
| `backtest.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/backtest.py) | [Windows](file:///d:/Workspaces/Vọc vạch/backtest.py) | Full vectorized backtesting with custom filters and PnL reporting |
| `backtest_eval.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/backtest_eval.py) | [Windows](file:///d:/Workspaces/Vọc vạch/backtest_eval.py) | Signal quality evaluator: win rate × hold period × parameter variants |
| `scripts/manage_positions.py` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/scripts/manage_positions.py) | [Windows](file:///d:/Workspaces/Vọc vạch/scripts/manage_positions.py) | CLI backend for ./pos add/list/close/perf |
| `data/positions.json` | — | — | Live positions store (open + closed) |
| `data/latest_signals.json` | — | — | Latest analysis snapshot per coin (read by Web Dashboard) |
| `data/latest_ai_analysis.json` | — | — | Latest Gemini AI report (read by Web Dashboard) |
| `logs/closed_positions.json` | — | — | Append-only closed trade log (RAG source for AI prompts) |
| `logs/auto_trade_log.json` | — | — | CCXT auto-trading audit logs (success, error, skips) |
| `logs/auto_trade_circuit.json` | — | — | State storage for consecutive losses and daily trade counters |
| `trading_strategies_summary.md` | [Ubuntu](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/trading_strategies_summary.md) | [Windows](file:///d:/Workspaces/Vọc vạch/trading_strategies_summary.md) | Full indicator formulas and signal logic documentation |

---

## 📈 Technical Analysis & Signal Logic (`analysis.py`)

The bot uses a **6-Layer Filtering Strategy** inside `analyze_market(candles)`.
All indicators are pure Python — no external libraries.

### Indicators Computed
| Indicator | Params | Algorithm |
|-----------|--------|-----------|
| ATR | period=14 | Wilder's Smoothing |
| RSI | period=14 | Wilder's Smoothing |
| EMA | 9, 21 | Standard EMA (`k = 2/(N+1)`) |
| SMA | 50, 200 | Sliding window O(N) |
| MACD | 12, 26, 9 | EMA(12) − EMA(26), Signal=EMA(9) |
| Bollinger Bands | period=20, std=2 | Population std dev |
| Volume SMA | period=20 | SMA of volume |
| Chandelier Exit | period=22, mult=3.0 | ATR-based trend filter |

### 6-Layer Signal Decision
1. **SMA 200 Trend Filter** — Bull (`Close > SMA200`) vs Bear
2. **SMA 50 Pullback Zone** — BUY when price dips into EMA21–SMA50 band on uptrend
3. **EMA 9/21 Crossover** — Golden/Death Cross with SMA200 confirmation
4. **Chandelier Exit** — Blocks BUY when state = BEAR
5. **Volume Spike + SFP** — Volume > 1.3× SMA20; Sweep False Pivot on 50-bar S/R
6. **Fear & Greed Sentiment** — Extreme Fear (<−0.6) downgrades STRONG BUY → WEAK; Extreme Greed (>+0.6) downgrades STRONG SELL → WEAK

### Backtest-Verified Performance (8,000 candles, 10 coins, 15m)
| Signal Type | Win Rate | Profit Factor | Best Hold |
|-------------|---------|---------------|-----------|
| STRONG BUY | 70.5% | 2.95 | 1h (4 candles) |
| STRONG SELL | 66.4% | 2.92 | 6h (24 candles) |
| WEAK BUY | ~35% | 0.24 | ❌ No edge |
| WEAK SELL | ~25% | 0.54 | ❌ Use as warning only |

### Machine Learning & Meta Confidence Performance (18-Month Dataset: Jan 2025 - Jun 2026, 18,908 samples)
- **Adaptive Model (Random Forest):**
  - **TimeSeriesSplit CV ROC-AUC:** `0.620 ± 0.010` (Highly stable across cycles)
  - **Holdout ROC-AUC:** `0.642`
  - **Accuracy:** `62%`
- **Meta Confidence Model (Probability Calibration):**
  - **CV ROC-AUC:** `0.6355 ± 0.0081`
  - **Probability Calibration (Platt Sigmoid):** Successfully mapped and verified across 5 bins (error <10%).

### TP/SL Formula
- **SL (BUY):** `max(Entry − 1.2×ATR, Support × 0.998)`
- **TP1 (BUY):** `min(BB_Middle, Entry + 3.5×ATR)` ← currently being evaluated for reduction to 2.0×
- **TP2 (BUY):** `min(Resistance×0.998, BB_Upper×0.998, Entry + 7.0×ATR)`
- Mirror logic for SELL.

---

## 🤖 Gemini AI Integration (`ai_analyst.py`)

The AI analyst receives a rich prompt including:
1. **15m signal table** for all coins (signal, RSI, EMA, support/resistance, TP/SL)
2. **Multi-timeframe analysis** (1h, 4h, 1d signals for each coin)
3. **Sentiment string** — Fear & Greed raw value + label
4. **RAG block** — Recent closed trades per coin: Win Rate, Avg PnL, last 3 trades, directional stats
5. **Open positions** — Current LONG/SHORT positions and their PnL status

Output: A structured Vietnamese-language market analysis report sent to Telegram.

---

## 🚀 How-to Guide (AI Tasks)

### Running the Bot
```bash
python main.py          # Continuous daemon mode
python main.py --once   # Single scan then exit
```

### Running Backtest Evaluation
```bash
python -X utf8 backtest_eval.py   # Signal quality evaluation (win rate, PF per type)
python backtest.py                 # Full historical backtest with PnL report
```

### Training ML Models
```bash
# 1. Fetch historical data range (configurable in python script)
python fetch_historical_range.py

# 2. Train the Random Forest Adaptive Model on 18-month data
python train_april_model.py

# 3. Train the Meta Confidence model (with sigmoid probability calibration)
python -m btc_scraper.meta_model --train

# 4. Train the RL Exit Manager (Phase 4)
python train_rl_exit_manager.py --algo ppo --train --steps 100000 --n-trades 500
```

### Evaluating RL Exit Performance
```bash
python evaluate_rl_phase4.py
```

### Running Portfolio Allocation Tests (Phase 5)
```bash
python -m pytest tests/test_portfolio_manager.py
```

### Environment Variables (`.env`)
```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
GEMINI_API_KEY_1=your_gemini_api_key
GEMINI_API_KEY_2=optional_second_key    # Round-robin for quota management
GEMINI_API_KEY_3=optional_third_key

# ── Auto-Trading (CCXT) ──────────────────────────────────────────────────────
AUTO_TRADE_DRY_RUN=true                # true = only log predictions, false = place orders
AUTO_TRADE_BINANCE_API_KEY=your_binance_testnet_api_key
AUTO_TRADE_BINANCE_API_SECRET=your_binance_testnet_api_secret
AUTO_TRADE_BINANCE_TESTNET=true        # true = testnet, false = mainnet
```

### Position Management CLI
```bash
./pos add BTC 68000            # Add LONG position (Spot)
./pos add ETH 3500 SHORT       # Add SHORT position
./pos list                     # List open positions
./pos close BTC 70000          # Close position and record PnL
./pos perf                     # Performance summary (Win Rate, Profit Factor, R)
```

### Adding New Coins
Edit `COINS` list in [`btc_scraper/config.py`](file:///d:/Workspaces/Vọc vạch/btc_scraper/config.py). Coins must have a `USDT` pair on Binance.

### Running Tests
```bash
pytest                                 # Run all unit tests
pytest tests/test_auto_trader.py -v    # Run auto-trader tests
```

---

## ⚠️ Code Standards & Constraints

- **No pandas / ta-lib** — keep all indicators in pure Python.
- **No new network dependencies** — use `urllib` or `requests` only (already in requirements).
- **Preserve auto-restart wrappers** in `main.py` when modifying the run loop.
- **UTF-8 everywhere** — `sys.stdout.reconfigure(encoding='utf-8')` is at the top of `main.py`. When running inline Python scripts, use `python -X utf8 script.py`.
- **Sentiment cache** — `sentiment.py` caches the F&G result for 1h to avoid hammering the API.
- **Positions file** — `data/positions.json` stores both open and closed entries. `logs/closed_positions.json` is the append-only closed log used for RAG.
