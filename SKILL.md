# Multi-coin OHLCV Scraper & Analyzer - AI Agent Skill Guide

This file serves as a **Skill and Instructions Guide** for AI agents (such as Google Antigravity, Claude Code, or Copilot) interacting with this codebase. It provides system context, architecture details, and step-by-step workflows for maintaining, running, and expanding the project.

---

## 📋 Project Overview

A Python-based multi-coin OHLCV scraper, technical analyzer, and automated signal bot.
- **Data Sources:** Binance (spot/spot-USDT pair by default).
- **Core Loop:** Scheduled updates running two tracks:
  1. **General scan (every 15 mins, e.g., 01, 16, 31, 46):** Fetches full market data, computes indicators, analyzes signals, runs Gemini AI analysis, and broadcasts general alerts.
  2. **Focused scan (every 5 mins, e.g., 06, 11, 21, 26):** Specifically tracks open positions to immediately alert on TP/SL hits or strong reversals without using AI quota.
- **Position Tracking:** Includes a manual position tracker (`./pos`) that monitors user's open trades and automatically alerts on SL, TP, or trend reversals.
- **Robustness:** Includes an auto-restart wrapper with exponential backoff for network drops, and scheduler recovery.
- **Backtesting:** Features an institutional-grade backtesting environment (`backtest.py`) with customizable filters, SL/TP multipliers, and detailed PnL/Expectancy reporting.

---

## 🛠️ Technology Stack & Dependencies

- **Runtime:** Python 3.10+
- **Key Packages:**
  - `schedule` - Task scheduling.
  - `rich` - Beautiful terminal output rendering.
  - `requests` / standard library modules (e.g., `math`, `time`).
  - *No Pandas or `ta-lib` are used.* All technical indicators are implemented in pure Python within `btc_scraper/analysis.py` for maximum speed and simplicity.

---

## 📈 Technical Analysis & Signals (`analysis.py`)

The bot implements a robust **5-Layer Filtering Strategy** inside `analyze_market(candles)`:

### Lớp -1: Chandelier Exit (ATR Filter)
- Calculated using ATR (period 22, multiplier 3.0).
- If Chandelier state is `BEAR`, all BUY orders are blocked (except emergency SFP).

### Lớp 0: RSI Reversal (Volume Confirmed)
- Triggers when RSI crosses the oversold threshold (`RSI < 30` cuts up) or overbought threshold (`RSI > 70` cuts down).
- Enhanced with **Volume Spike** confirmation (volume > 1.3x of 20-period SMA).

### Lớp 0.5: Swing Failure Pattern (SFP)
- Smart Money indicator: scans if the price sweeped the 50-period High/Low (liquidity grab) and closed inside the range.

### Lớp 1: EMA Crossover (SMA 200 Filtered)
- Golden/Death Cross of **EMA 9** and **EMA 21**.
- Executed only if confirmed by the major trend of **SMA 200** (above = Bull Market, below = Bear Market).

### Lớp 2: Pullback to SMA 50 Zone
- Activates when short-term trend is down (`EMA 9 < EMA 21`) but price pulls back into the buffer zone between `EMA 21` and `SMA 50` (up to -1% below SMA50) in an uptrend, confirmed by a bullish candle.
- **Trailing Stop:** Activates if the price closes below SMA 50 while SMA 50 is sloping downwards.

---

## ⚙️ Project Configuration & Files

- [main.py](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/main.py): App entry point, scheduling loop, and crash recovery.
- [btc_scraper/analysis.py](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/analysis.py): Pure Python technical indicator calculations (RSI, EMA, SMA, ATR, Bollinger Bands, MACD, Chandelier Exit) and signal logic.
- [btc_scraper/config.py](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/config.py): Config settings (`COINS`, `INTERVAL`, `LIMIT`).
- [btc_scraper/telegram_bot.py](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/telegram_bot.py): Telegram message broadcaster.
- [btc_scraper/ai_analyst.py](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/ai_analyst.py): Gemini AI prompts and integration.
- [btc_scraper/position_tracker.py](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/position_tracker.py): Tracks manual open/closed positions and generates trade recommendations.
- [scripts/manage_positions.py](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/scripts/manage_positions.py) (via `./pos`): CLI tool for users to add, close, and view positions, and check strategy performance.
- [backtest.py](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/backtest.py): Vectorized backtesting script to validate signals on historical data.

---

## 🚀 How to Guide (AI Tasks)

### 1. Running the Scraper
To run the bot in continuous daemon mode:
```bash
python main.py
```
To run it once and exit immediately (useful for testing/dry-runs):
```bash
python main.py --once
```

### 2. Environment Variables (.env)
Required keys in `.env` at the root of the project:
```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
GEMINI_API_KEY=your_gemini_api_key
```

### 3. Adding New Coins
Modify the list `COINS` in `btc_scraper/config.py`.

### 4. Position Tracking (Manual)
To manage positions tracked by the bot:
- Add: `./pos add BTC 68000` (defaults to LONG, used for Spot) or `./pos add ETH 3500 SHORT`
- List open: `./pos list`
- Close: `./pos close BTC 70000`
- View Performance: `./pos perf`

### 5. Running Backtests
To test signal logic against historical data:
```bash
python backtest.py
```
This will output a performance report (Win Rate, Drawdown, Profit Factor) and dump trade logs to `logs/backtest_trades.csv`.

### 6. Code Standards & Guidelines
- Do NOT introduce dependency on `pandas` or compiled `ta-lib` unless requested.
- Maintain error logs and Rich console alerts.
- Keep the auto-restart wrappers intact when modifying the main run loop.
