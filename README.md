# besttime-crypto — AI Quant Trading Platform

Nền tảng giao dịch tiền điện tử tự động thế hệ mới, kết hợp **7 lớp lọc kỹ thuật**, **ML Ensemble**, **Reinforcement Learning Exit Manager** và **Causal World Model** — gửi cảnh báo thời gian thực qua Telegram và trực quan hoá qua Web Dashboard.

> **Phiên bản hiện tại**: Architecture v2.2 — Event-Driven Causal AI + runtime linkage/provenance
> **Đánh giá hệ thống**: cập nhật 2026-07-17 tại [`evaluations/system_evaluation_report.md`](evaluations/system_evaluation_report.md)
> **Trạng thái**: Production-ready cho signal research + paper trading; live trading vẫn bị chặn cho đến khi Gate A, shadow evidence window và Phase 5 readiness đạt.

---

## Tính năng chính

- **Quét đa coin tự động** (BTC, ETH, BNB, SOL, XRP...) mỗi 15 phút qua Binance WebSocket.
- **Phân tích kỹ thuật 7 lớp lọc** vectorized bằng Pandas/NumPy: ATR, RSI, EMA, SMA, MACD, Bollinger Bands, Chandelier Exit, Volume SMA, SFP.
- **Phân tích đa khung thời gian (MTF)**: Nến 15m / 1h / 4h / 1d — HTF Trend Summary và MTF Confluence Filter.
- **Causal World Model (Architecture v2.0)**:
  - `WorldState` — unified state object với 5 layers (Macro, Liquidity, Crypto, Sentiment, Risk).
  - `HybridContextProvider` — kết hợp Rule-based + Bayesian inference, điều chỉnh bởi `CAUSAL_ALPHA` env var.
  - `CausalGate` — CRITICAL risk override sang NEUTRAL, HIGH/MEDIUM risk warning trong `SignalGeneratorAgent`.
  - `CounterfactualEngine` — tự động phân tích lệnh thua, lưu `logs/counterfactual_log.json`.
- **ML Ensemble**: Meta Model v3.1 production, Adaptive RF canonical artifact và runtime prediction audit với model/schema/artifact traceability.
- **Reinforcement Learning Exit Manager (Recurrent PPO)**: observation contract 20D / 6 actions, đang ở shadow/advisory mode; active exit action vẫn bị guard.
- **Runtime Outcome Linkage**: stable lifecycle IDs, data contracts, calibration sample store, Gate A evidence tooling và shadow evidence governance.
- **Fear & Greed Index (Lớp 6)**: `alternative.me/fng`, cache 1h — tự động hạ cấp tín hiệu theo sentiment cực đoan.
- **Gemini AI Analyst**: Tổng hợp tín hiệu 15m + MTF + lịch sử giao dịch (RAG) → nhận định thị trường tiếng Việt.
- **Auto Trading (CCXT)**: Tự động đặt/đóng lệnh Market trên Binance Testnet/Mainnet. Hỗ trợ chế độ Dry Run.
- **Trade Provenance**: chuẩn hóa `order_creator` + `order_channel` để phân biệt system paper orders với user Telegram/UI/CLI orders.
- **Portfolio Optimization**: Mean-Variance Optimization (MVO) khi có ≥ 2 tín hiệu đồng thời.
- **Circuit Breaker**: Dừng tự động 24h sau 5 lệnh thua liên tiếp; giới hạn 5 lệnh/ngày.
- **Web Dashboard**: React/Vite tại `http://localhost:3000`:
  - `Tín Hiệu Thị Trường` — bảng signal, RSI, trend, meta confidence.
  - `Vị Thế Đang Mở` — quản lý position, mở/đóng lệnh, xem PnL.
  - `CCXT Auto Trading Monitor` — trạng thái AutoTrader, Circuit Breaker, audit log.
  - `Meta Model Analytics` — feature importance, calibration buckets.
  - `Gemini AI Insights` — báo cáo từ `data/latest_ai_analysis.json`.
- **Backend API**: FastAPI `api/server.py` (port 8000) phục vụ Dashboard.
- **Telegram Alerts**: Bảng tín hiệu + AI report + Causal risk level sau mỗi chu kỳ.
- **Alternative Data Layer (Phase 7)**:
  - 12+ features on-chain/macro/sentiment: `etf_flow`, `exchange_netflow`, `whale_score`, `stablecoin_supply`, `funding_pressure`, `macro_pressure`, `risk_on_score`, v.v.
  - `ParsebotFarsideETFCollector` thu thập ETF flow BTC/ETH/SOL, lưu MongoDB (`alternative_data_etf_flows`).
  - `AlternativeDataScheduler` tự động kích hoạt Parse.bot jobs theo múi giờ VN (`Asia/Ho_Chi_Minh`).
  - `CollectorHealthMonitor.check_etf_alert_conditions()` cảnh báo Telegram khi data stale >36h hoặc fail >2 ngày.
  - Confidence-weighted features: `effective_etf_momentum`, `effective_stablecoin_momentum`, `effective_risk_on_score` trong `causal_context_bridge.py`.

---

## Luồng chính phát hiện và chấm điểm tín hiệu

Hệ thống hiện chạy theo pipeline multi-agent:

```text
Binance WebSocket / REST
  -> MarketAnalystAgent
  -> analyze_market() 15m + MTF 1h/4h/1d
  -> rule signal label: BUY / SELL / WEAK / STRONG / NEUTRAL
  -> score_signal(): score nội bộ 0-100 + meta_confidence + position_size
  -> CausalContextBridge + CausalGate
  -> RiskManagerAgent + PortfolioManagerAgent
  -> AutoTrader.should_trade()
  -> ExecutionEngine guard path
  -> Telegram + Dashboard + shadow/counterfactual logs
```

Các điểm cần hiểu đúng:

- `analysis/core.py` phát hiện tín hiệu từ RSI reversal, EMA crossover, SFP, pullback SMA50/EMA21, break SMA50, Chandelier, ADX/Choppiness, volume và Fear & Greed.
- `signal_score.py` dùng score nội bộ: `0 = strong SELL`, `50 = NEUTRAL`, `100 = strong BUY`; đồng thời trả `strength` side-agnostic để AutoTrader so threshold công bằng cho BUY và SELL.
- MTF confluence điều chỉnh score theo 1h/4h/1d; 1h ngược chiều bị phạt mạnh nhất.
- AutoTrader không vào lệnh nếu thiếu `meta_confidence`, tín hiệu là `WEAK`, coin không được whitelist, score/meta dưới ngưỡng, trùng vị thế, vượt tương quan, hoặc bị circuit breaker/exposure guard.
- Causal layer mặc định `CAUSAL_ALPHA=0.0` ở safe mode; `CRITICAL` risk đổi `signal_score.action` về `NEUTRAL` và AutoTrader hiện tôn trọng action này nếu được set trước execution; `HIGH/MEDIUM` gắn warning.

Đánh giá hiện tại:

```text
Signal detection: PASS
Signal scoring: PASS - đã thêm `strength` để sửa ngưỡng SELL/BUY
Paper auto-trade gating: PASS
Runtime linkage framework: IMPLEMENTED
Gate A runtime evidence: PENDING
Shadow evidence window: NOT STARTED
Live execution readiness: BLOCKED
Maintainability: analysis/core.py cần tách nhỏ dần
```

Trạng thái vận hành mới nhất nằm tại [`docs/remediation/System_Status_Report_2026-07-17.md`](docs/remediation/System_Status_Report_2026-07-17.md) và [`docs/remediation/System_Operational_Update_2026-07-17.md`](docs/remediation/System_Operational_Update_2026-07-17.md).

---

## P0 — Existing Risk Flow Integrity & Paper Execution Correctness

> **Ghi chú kiến trúc (2026-11-09):** Sự tồn tại của các module risk, portfolio và sizing chưa đủ chứng minh chúng đang chi phối lệnh cuối. Audit hiện tại phát hiện `RiskManagerAgent` và `PortfolioManagerAgent` cập nhật `signals_info`, trong khi đường thực thi có thể tiếp tục đọc `analysis`. Vì vậy, risk block và portfolio weight cần được chứng minh xuyên suốt đến paper order bằng test end-to-end.

Phạm vi P0 chỉ tập trung vào tính đúng đắn, hiệu năng và khả năng đánh giá kinh tế của **paper/demo trading**; không mở rộng chức năng real trading.

Luồng mục tiêu, bám theo các contract hiện có:

```text
Market Analysis / Raw Signal
  -> RiskManagerAgent
  -> PortfolioManagerAgent
  -> AutoTrader.build_entry_decision()
  -> EntryDecision                 # canonical final decision, immutable
  -> ExecutionAgent
  -> ExecutionEngine.submit_paper()
       -> execution-time risk recheck
       -> ExecutionRecord          # attempt/rejection/fill linked by decision_id
```

Các nguyên tắc bắt buộc:

- Giữ raw signal và prediction không đổi để bảo toàn lineage; không ghi đè tùy ý từ `signals_info` về `analysis`.
- Dùng `EntryDecision` hiện có làm quyết định entry cuối duy nhất; không tạo thêm `FinalEntryDecision` trùng vai trò.
- Risk block phải tạo **0 new paper entry**; thay đổi portfolio weight phải làm final quantity thay đổi đúng sau các giới hạn sizing.
- `EventRiskDecision` phải tách `risk_level`, `entry_permission`, `position_action`, risk multiplier, state/policy version và timestamp.
- `submit_paper()` phải kiểm tra snapshot tồn tại, TTL, policy compatibility, mức hạn chế mới và remaining risk budget; entry policy không được chặn exit/reduce.
- Giữ final-decision evidence bất biến trong `RuntimeEvidenceStore`; dùng `ExecutionRecord` hiện có cho từng execution attempt và liên kết bằng `decision_id`.
- Mọi thay đổi làm đổi eligibility, sizing hoặc execution semantics phải chạy trên successor release/evidence epoch, không sửa ý nghĩa của epoch đã khóa.

Điều kiện đóng P0 là test xuyên suốt chứng minh risk/portfolio thật sự thay đổi kết quả từ `Market Analysis` đến `submit_paper()` và paper outcome. News Intelligence, event data lịch sử và chiến lược MTF độc lập chỉ được ưu tiên sau khi đường truyền quyết định này được xác nhận.

---

## Backtest & Hiệu năng ML

Trên bộ dữ liệu lịch sử **18 tháng** (01/2025 - 06/2026) với **18,904 mẫu giao dịch đóng**:

| Metric | Adaptive RF | Meta Model v3.1 |
|--------|--------------------|-----------------------|
| **Time-Series CV ROC-AUC** | `0.620 ± 0.010` | `0.6355 ± 0.0081` |
| **Holdout ROC-AUC** | `0.642` | — |
| **Accuracy** | 62% | — |
| **Calibration** | — | Isotonic; tail buckets vẫn bị clamp khi thiếu runtime evidence |

Ghi chú vận hành 2026-07-17:

```text
Adaptive RF artifact path: canonicalized at logs/adaptive_model.joblib
Meta Model runtime calibration: blocked until linked runtime outcomes are sufficient
RL Exit: shadow/advisory; no live autonomous exit action
Live trading: disabled
```

### Backtest tín hiệu (8,000 nến):

| Nhóm tín hiệu | Hold tối ưu | Win Rate | Profit Factor |
|---------------|------------|---------|---------------|
| **STRONG BUY** | 1h (4 nến) | **70.5%** | **2.95** |
| **STRONG SELL** | 6h (24 nến) | **66.4%** | **2.92** |
| WEAK BUY | — | ~35% | 0.24 |
| WEAK SELL | — | ~25% | 0.54 |

---

## Cài đặt và Khởi chạy

Hệ thống gồm 3 thành phần chạy song song:

1. **Bot cốt lõi** (`main.py`) — Quét tín hiệu, Causal AI, giao dịch tự động.
2. **Backend API** (`api/server.py`) — FastAPI (port 8000).
3. **Web Dashboard** (`web/`) — React/Vite (port 3000).

### Bước 1: Cài đặt môi trường

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Node.js dependencies (Web Dashboard)
cd web && npm install && cd ..
```

### Bước 2: Cấu hình `.env`

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
TELEGRAM_ALLOWED_CHAT_IDS=optional_chat_id_1,optional_chat_id_2

# Gemini AI — hỗ trợ nhiều key round-robin
GEMINI_API_KEY_1=your_gemini_api_key
GEMINI_API_KEY_2=optional_second_key

# MongoDB Atlas
MONGODB_URI=mongodb+srv://...
MONGODB_DB_NAME=besttime_crypto

# Auto-Trading (CCXT)
AUTO_TRADE_DRY_RUN=true
AUTO_TRADE_BINANCE_API_KEY=your_binance_testnet_api_key
AUTO_TRADE_BINANCE_API_SECRET=your_binance_testnet_api_secret
AUTO_TRADE_BINANCE_TESTNET=true

# Causal World Model
CAUSAL_ALPHA=0.0      # 0.0=rule-only (safe), 0.1+ cần shadow mode validation
```

### Bước 3: Khởi chạy

```bash
# Khởi chạy tất cả cùng lúc
./start.sh
# Windows: .\start.ps1

# Hoặc từng phần:
python main.py             # Bot cốt lõi
python api/server.py       # Backend API (port 8000)
cd web && npm run dev -- --port 3000 --host   # Dashboard
```

Truy cập: **http://localhost:3000**

---

## Quản lý Vị thế (CLI)

```bash
./pos add BTC 68000 -n "Mua Spot tích luỹ"          # Thêm LONG
./pos add ETH 3500 SHORT -n "Tín hiệu SFP bắt đỉnh"  # Thêm SHORT
./pos add BNB 595 --usdt 200                          # Với số vốn thực tế
./pos list                                            # Xem vị thế đang mở
./pos close BTC 70000                                 # Đóng và ghi PnL
./pos perf                                            # Tổng hợp hiệu suất
```

---

## Huấn luyện Mô hình AI

```bash
# Huấn luyện Adaptive Model + Meta Confidence (Ensemble)
python train_april_model.py
python -m btc_scraper.ml_engine.meta_model --train

# Huấn luyện RL Exit Manager (PPO)
python train_rl_exit_manager.py --algo ppo --train --steps 100000

# Đánh giá RL vs rule-based exit
python evaluate_rl_phase4.py

# Chạy CausalDiscoveryEngine (khuyến nghị hàng tuần)
python -c "from btc_scraper.ml_engine.causal_discovery import CausalDiscoveryEngine; e=CausalDiscoveryEngine(); e.discover()"
```

---

## Chạy Unit Test

```bash
# Toàn bộ test suite (246 tests)
pytest

# Riêng từng nhóm
pytest tests/test_causal_context_bridge.py   # Phase A-D integration
pytest tests/test_phase21_integration.py      # Phase 2.1 (18 tests)
pytest tests/test_phase30_learning.py         # Phase 3.0 (33 tests)
pytest tests/test_decision_engine.py          # MetaDecisionEngine
pytest tests/test_auto_trader.py              # AutoTrader
pytest tests/test_portfolio_manager.py        # Portfolio MVO
pytest tests/test_phase7_sprint7.py           # Phase 7 Alternative Data (29 tests)
```

---

## Chuẩn bị Dữ liệu ML

```bash
# Cào dữ liệu lịch sử
python fetch_historical_range.py

# Xuất dataset ML + RAG context
python scripts/prepare_ml_data.py
python scripts/generate_rag_prompts.py

# Parallel build per-coin + merge + train
python scripts/build_coins_parallel.py --jobs 8
python scripts/merge_adaptive_signals.py
python scripts/build_and_train.py --skip-build --n 200
```

---

## Chạy Backtest

```bash
# Đánh giá chất lượng tín hiệu
python -X utf8 backtest_eval.py

# Backtest đầy đủ PnL
python backtest.py
```

---

## Cấu trúc Dự án

```
besttime-crypto/
├── main.py                          # Entry point: WebSocket, scheduler, AI worker
├── btc_scraper/
│   ├── analysis/
│   │   ├── core.py                  # Signal detection engine: indicators, patterns, TP/SL
│   │   ├── indicators.py            # ATR, RSI, EMA, SMA, MACD, BB, Chandelier
│   │   ├── correlation.py           # MTF correlation matrix
│   │   └── structure.py             # Market structure (support/resistance)
│   ├── core/
│   │   ├── world_state.py           # WorldState — 5-layer unified state (v2.0)
│   │   ├── event_bus.py             # Pub/Sub Event Bus (v2.0)
│   │   ├── feature_snapshot.py      # Snapshot & Replay (v2.0)
│   │   ├── ccxt_client.py           # CCXT Binance async wrapper
│   │   ├── config.py                # COINS, INTERVAL, LIMIT
│   │   ├── db.py                    # MongoDB Atlas connection
│   │   ├── filters.py               # Signal filters
│   │   └── sentiment.py             # Fear & Greed Index (cached)
│   ├── ml_engine/
│   │   ├── meta_model.py            # Ensemble ML (RF + LightGBM + CatBoost + XGBoost)
│   │   ├── signal_score.py          # Adaptive scoring + Kelly fraction
│   │   ├── decision_engine.py       # MetaDecisionEngine (decide_with_provider)
│   │   ├── causal_context_bridge.py # Phase A: Singleton bridge + WorldState builder
│   │   ├── hybrid_context_provider.py # Phase 3.1: Alpha-blended Rule+Bayesian
│   │   ├── bayesian_context_provider.py # Phase 3.0: Gaussian inference
│   │   ├── rule_context_provider.py # Phase 2.0: Rule-based
│   │   ├── context_provider.py      # Abstract ContextProvider interface
│   │   ├── context_engine.py        # Multi-layer rule processor
│   │   ├── causal_discovery.py      # Granger causality discovery
│   │   ├── causal_graph.py          # Graph analysis (paths, influencers)
│   │   ├── causal_reasoning.py      # Explainable reasoning engine
│   │   ├── causal_simulator.py      # Do-calculus intervention simulator
│   │   ├── counterfactual_engine.py # Phase D: What-if trade analysis
│   │   ├── causal_monitoring.py     # Metrics & monitoring dashboard
│   │   ├── causal_startup.py        # Startup validation
│   │   ├── causal_event_handlers.py # Event Bus subscriptions
│   │   ├── world_model_predictor.py # Digital Twin state predictor
│   │   ├── causal_anomaly_detector.py # Structural break detection
│   │   ├── shadow_mode_tracker.py   # A/B shadow mode tracking
│   │   ├── ab_backtest.py           # A/B backtest comparator
│   │   ├── rl_trading_env.py        # Gymnasium RL environment (18D/6A)
│   │   ├── feature_extractor.py     # Feature extraction pipeline
│   │   ├── multi_agent.py           # AgentOrchestrator (6 agents)
│   │   ├── timegan.py               # TimeGAN synthetic data
│   │   └── agents/
│   │       ├── macro_agent.py       # Phase 6.0: DXY/Yields/FedRate watcher
│   │       ├── liquidity_agent.py   # Phase 6.0: Funding/OI/Orderbook watcher
│   │       ├── sentiment_agent.py   # Phase 6.0: Fear&Greed/social watcher
│   │       └── consensus_engine.py  # Phase 6.0: Causal Voting / Bayesian Fusion
│   ├── trading/
│   │   ├── auto_trader.py           # CCXT async auto-trading
│   │   ├── position_tracker.py      # Position management + RL inference
│   │   ├── portfolio_manager.py     # MVO + Risk Parity
│   │   ├── exposure_manager.py      # Exposure & drawdown limits
│   │   └── risk_manager.py          # Circuit breaker + loss streak
│   ├── collectors/
│   │   ├── macro_collector.py          # DXY, VIX, RealYield, BondYield fetcher (REST fallback)
│   │   ├── alternative_data.py         # Phase 7: Unified alternative data aggregator
│   │   ├── alternative_scheduler.py    # Phase 7: Thread-based scheduler + Parse.bot cron
│   │   ├── alternative_quality.py      # Phase 7: DataQualityDashboard + ETF alert monitor
│   │   ├── parsebot_farside_collector.py # Phase 7: ETF flow (MongoDB upsert)
│   │   ├── etf_collector.py            # Phase 7: ETF provider chain
│   │   ├── fred_collector.py           # Macro: FRED + Yahoo REST fallback
│   │   ├── yahoo_collector.py          # Macro: yfinance + REST fallback
│   │   ├── binance_collector.py        # Funding rate, OI
│   │   ├── defillama_collector.py      # Stablecoin supply, TVL
│   │   ├── reddit_collector.py         # Reddit OAuth sentiment
│   │   └── google_trends_collector.py  # Search interest (6h cache)
│   ├── telegram_bot/
│   │   └── alerts.py                # Telegram alert builders
│   ├── ai_analyst/
│   │   └── ...                      # Gemini AI RAG analyst
│   └── regime/                      # Market regime detection
├── api/
│   └── server.py                    # FastAPI backend (port 8000)
├── web/                             # React/Vite frontend (port 3000)
├── data/
│   ├── causal_graph.json            # Knowledge graph (v2.0)
│   ├── context_rules.json           # Context rules config (v2.0)
│   ├── latest_signals.json          # Latest analysis snapshot
│   └── latest_ai_analysis.json      # Latest Gemini AI report
├── logs/
│   ├── counterfactual_log.json      # Phase D: Counterfactual analysis results
│   ├── auto_trade_log.json          # Auto trade audit log
│   ├── auto_trade_circuit.json      # Circuit Breaker state
│   └── rl_models/                   # Trained PPO model checkpoints
├── scripts/
│   ├── fetch_parsebot_etf_jobs.py       # Phase 7: Parse.bot ETF job CLI (--dry-run)
│   ├── continuous_learning.py           # Weekly auto-retrain
│   ├── weekly_job.py                    # Weekly report generator
│   ├── build_coins_parallel.py          # Parallel per-coin build
│   ├── backtest.py / backtest_eval.py   # Backtesting scripts
│   ├── train_rl_exit_manager.py         # RL Exit Manager training
│   ├── evaluate_rl_phase4.py            # RL evaluation vs rule-based
│   └── ... (97 scripts total)
├── models/
│   ├── adversarial.pt               # TimeGAN adversarial checkpoint
│   ├── autoencoder.pt               # TimeGAN autoencoder checkpoint
│   └── supervisor.pt                # TimeGAN supervisor checkpoint
├── docs/
│   ├── ARCHITECTURE_v2.md           # Historical Architecture v2.x technical doc
│   ├── SYSTEM_DESIGN.md             # Current System Design Document (TDD)
│   ├── causal_implementation_plan.md# Causal AI roadmap & status
│   ├── trading_strategies_summary.md# Indicators & trading strategies
│   ├── phase7/                      # Phase 7 Alternative Data docs
│   └── phase8/                      # Phase 8 Feature Engineering docs
├── evaluations/
│   ├── signal_detection_and_scoring_assessment.md # Historical signal flow assessment
│   ├── system_evaluation_report.md  # Deep system evaluation report
│   └── ...                          # Module evaluation reports
└── tests/                               # 246 tests (100% PASS)
```

---

## Tài liệu Kỹ thuật

| Tài liệu | Mô tả |
|----------|-------|
| [SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) | Technical Design Document — kiến trúc, data pipeline, XAI, RL |
| [signal_detection_and_scoring_assessment.md](evaluations/signal_detection_and_scoring_assessment.md) | Đánh giá luồng phát hiện tín hiệu, score, CausalGate và AutoTrader gate hiện tại |
| [ARCHITECTURE_v2.md](docs/ARCHITECTURE_v2.md) | Causal World Model v2.1 — Event-Driven Architecture |
| [causal_implementation_plan.md](docs/causal_implementation_plan.md) | Roadmap & status chi tiết Phase 2.1 → Phase D |
| [trading_strategies_summary.md](docs/trading_strategies_summary.md) | Công thức kỹ thuật, signal layers, TP/SL, RL |
| [system_evaluation_report.md](evaluations/system_evaluation_report.md) | Đánh giá sâu hệ thống (02/07/2026) |
| [ML_DATA_GUIDE.md](docs/ML_DATA_GUIDE.md) | Hướng dẫn chuẩn bị data ML |
| [Phase7_Alternative_Data_Implementation_Plan_UPDATED.md](docs/phase7/Phase7_Alternative_Data_Implementation_Plan_UPDATED.md) | Phase 7 Alternative Data — Sprint 9 COMPLETE |
| [Phase7_Parsebot_Farside_ETF_Flow_Frequency_Improvement_Plan.md](docs/phase7/Phase7_Parsebot_Farside_ETF_Flow_Frequency_Improvement_Plan.md) | ETF Flow cron schedule & MongoDB storage |
| [scripts/SCHEDULE.md](scripts/SCHEDULE.md) | Hướng dẫn cron scheduling + Parse.bot ETF jobs |
