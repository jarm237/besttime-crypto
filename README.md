# besttime-crypto

Hệ thống Bot tự động cào dữ liệu tiền điện tử, phân tích tín hiệu kỹ thuật qua **6 lớp lọc thuật toán**, kết hợp **Gemini AI** để đưa ra nhận định thị trường đa khung thời gian, tích hợp **Fear & Greed Index** và **RAG từ lịch sử giao dịch** — gửi cảnh báo qua Telegram theo thời gian thực.

## Tính năng

- **Quét đa coin tự động** cho danh sách cấu hình (BTC, ETH, BNB, SOL, XRP...) mỗi 15 phút.
- **Phân tích kỹ thuật 6 lớp lọc** bằng Python thuần: RSI, EMA, SMA, MACD, Bollinger Bands, ATR, Chandelier Exit, Volume SMA, SFP.
- **Phân tích đa khung thời gian (MTF)**: Thu thập thêm nến 1h / 4h / 1d để gửi cho Gemini AI đánh giá xu hướng lớn hơn.
- **Fear & Greed Index (Lớp 6)**: Lấy từ `alternative.me/fng`, cache 1h. Tự động hạ cấp tín hiệu BUY khi Extreme Fear, hạ cấp SELL khi Extreme Greed.
- **Gemini AI Analyst**: Tổng hợp toàn bộ tín hiệu 15m + MTF + sentiment + lịch sử giao dịch (RAG) để đưa ra nhận định thị trường bằng tiếng Việt.
- **Quản lý vị thế thủ công (Position Tracker)**: Nhập lệnh đã khớp, bot tự động giám sát và gửi khuyến nghị Chốt Lời / Cắt Lỗ qua Telegram mỗi 5 phút.
- **Tự động đặt lệnh (Auto Trading - CCXT)**: Khi mô hình ML chấm điểm xác suất thắng đạt ngưỡng tin cậy cao (≥ 85%), bot tự động đặt lệnh Market trên Binance Testnet/Sandbox. Hỗ trợ chế độ chạy mô phỏng an toàn (`DRY_RUN=true`).
- **Tự động đóng vị thế (Auto Close)**: Bot tự động đặt lệnh đóng vị thế trên sàn Binance Testnet khi vị thế chạm mức SL/TP khuyến nghị.
- **Cơ chế bảo vệ (Circuit Breaker)**: Tự động dừng giao dịch 24h nếu gặp chuỗi 5 lệnh thua liên tiếp và giới hạn tần suất tối đa 5 lệnh/ngày.
- **Web Dashboard**: Giao diện React / Vite tại `http://localhost:3000`, bao gồm các tab:
  - `Tín Hiệu Thị Trường` — bảng signal, RSI, trend, inter-market context và meta confidence.
  - `Vị Thế Đang Mở` — quản lý position, thêm lệnh mới, đóng lệnh và xem PnL hiện tại.
  - `CCXT Auto Trading Monitor` — trạng thái AutoTrader, Circuit Breaker, daily trade limit và audit log.
  - `Meta Model Analytics` — load metrics, feature importance và calibration buckets.
  - `Gemini AI Insights` — hiển thị báo cáo Gemini AI từ `data/latest_ai_analysis.json`.
- **Backend API**: `api/server.py` phục vụ dữ liệu cho Dashboard qua các endpoint `/api/market-signals`, `/api/positions`, `/api/performance`, `/api/ai-analysis`, `/api/auto-trade/status`, `/api/auto-trade/logs`, `/api/meta-model`, v.v.
- **Backtest**: Script `backtest_eval.py` đánh giá chất lượng tín hiệu theo win rate, Profit Factor và hold period tối ưu.
- **Telegram Alerts**: Gửi bảng tín hiệu + AI report tự động sau mỗi chu kỳ quét.

---

## Backtest & Hiệu năng ML (Kết quả đã xác minh)

Trên bộ dữ liệu lịch sử **18 tháng** (Tháng 1/2025 - Tháng 6/2026) với **18,904 mẫu giao dịch đóng**:

- **Mô hình Adaptive (Random Forest):**
  - **Time-Series CV ROC-AUC:** `0.620 ± 0.010` (Rất ổn định qua các chu kỳ)
  - **Holdout ROC-AUC:** `0.642`
  - **Accuracy:** `62%`
- **Mô hình Meta Confidence:**
  - **CV ROC-AUC:** `0.6355 ± 0.0081`
  - **Hiệu chuẩn xác suất (Platt Sigmoid):** Đã áp dụng thành công cho các bucket xác suất dự đoán (sai số <10%).

---

## Quản lý Vị thế (Position Tracker)

Công cụ CLI `./pos` giúp ghi nhận và theo dõi vị thế giao dịch. Bot tự động kiểm tra TP/SL và tín hiệu đảo chiều sau mỗi lần quét.

### Cú pháp CLI

```bash
# Thêm vị thế LONG (Spot) — nhập coin và giá mua
./pos add BTC 68000 -n "Mua Spot tích luỹ"

# Thêm vị thế SHORT (Futures)
./pos add ETH 3500 SHORT -n "Tín hiệu SFP bắt đỉnh"

# Thêm vị thế kèm số vốn thực tế (để tính PnL USD chính xác)
./pos add BNB 595 --usdt 200

# Xem danh sách vị thế đang mở
./pos list

# Đóng vị thế và ghi nhận PnL
./pos close BTC 70000

# Xem tổng hợp hiệu suất chiến lược (Win Rate, Profit Factor, R)
./pos perf
```

Sau khi lưu vị thế, bot sẽ gửi cảnh báo Telegram ngay khi:

- 🚨 Giá chạm **Stop Loss**
- 🎯 Giá đạt **TP1 hoặc TP2**
- ⚠️ Xuất hiện **tín hiệu đảo chiều** ngược hướng vị thế

Các thông số bao gồm: `Win Rate`, `Profit Factor`, `Max Consecutive Losses` và `Tổng P&L`. Lưu ý: Việc đóng lệnh sẽ tự động ghi dữ liệu vào hệ thống AI để huấn luyện (Adaptive Scoring).

#### 5. Huấn luyện Mô hình AI (Adaptive, Meta & RL)

Bot tích hợp mô hình Machine Learning và Reinforcement Learning để đánh giá tín hiệu và quản lý thoát lệnh:

- Để huấn luyện lại mô hình Adaptive & xuất signals log từ dữ liệu lịch sử (18 tháng):
  ```bash
  python train_april_model.py
  ```
- Để huấn luyện lại mô hình Meta Confidence & ensemble với walk-forward validation:
  ```bash
  python -m btc_scraper.meta_model --train
  ```
  Ghi chú: Phiên bản mới `v2.0-ensemble` hỗ trợ huấn luyện ensemble (RandomForest + LightGBM/CatBoost/XGBoost nếu được cài) và walk-forward evaluation.
  ```bash
  pip install lightgbm catboost xgboost
  ```
- Để huấn luyện mô hình RL Exit Manager (Phase 4):
  ```bash
  python train_rl_exit_manager.py --algo ppo --train --steps 100000 --n-trades 500
  ```
- Để đánh giá kết quả RL và so sánh rule-based exit:
  ```bash
  python evaluate_rl_phase4.py
  ```
- **Hệ thống đa tác nhân & Tối ưu danh mục (Phase 5):**
  Hệ thống chạy qua `AgentOrchestrator` trong `btc_scraper/multi_agent.py`. Bạn có thể chạy unit tests để kiểm tra logic phân bổ danh mục (MVO & Risk Parity):
  ```bash
  pytest tests/test_portfolio_manager.py
  ```

---

## Cài đặt và Khởi chạy

Hệ thống gồm 3 thành phần chạy song song:

1. **Bot cốt lõi** (`main.py`) — Quét tín hiệu, gọi AI, gửi Telegram, giao dịch tự động.
2. **Backend API** (`api/server.py`) — FastAPI phục vụ dữ liệu cho Web Dashboard (cổng 8000).
3. **Web Dashboard** (`web/`) — Giao diện React / Vite (cổng 3000).

### Bước 1: Cài đặt môi trường

```bash
# Python dependencies (Bot + API)
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Node.js dependencies (Web Dashboard)
cd web
npm install
cd ..
```

### Bước 2: Cấu hình `.env`

Tạo file `.env` ở thư mục gốc:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Gemini AI — hỗ trợ nhiều key để round-robin tránh hết quota
GEMINI_API_KEY_1=your_gemini_api_key
GEMINI_API_KEY_2=optional_second_key
GEMINI_API_KEY_3=optional_third_key

# ── Auto-Trading (CCXT) ──────────────────────────────────────────────────────
AUTO_TRADE_DRY_RUN=true                # true = chỉ mô phỏng, false = live testnet
AUTO_TRADE_BINANCE_API_KEY=your_binance_testnet_api_key
AUTO_TRADE_BINANCE_API_SECRET=your_binance_testnet_api_secret
AUTO_TRADE_BINANCE_TESTNET=true        # true = testnet, false = mainnet
```

### Bước 3: Khởi chạy toàn bộ hệ thống

**Cách nhanh nhất** — chạy cả 3 dịch vụ bằng một lệnh:

```bash
./start.sh
# Windows: .\start.ps1
```

Nhấn `Ctrl + C` để tắt toàn bộ.

Sau khi chạy, truy cập Web Dashboard:

```bash
http://localhost:3000
```

Hoặc khởi động riêng từng phần:

- **Backend API:** `python api/server.py` (port 8000)
- **Web Dashboard:** `cd web && npm run dev -- --port 3000 --host`

---

### Chạy thủ công từng phần

**Tab 1 — Bot cốt lõi:**

```bash
python main.py
```

- **Gửi báo cáo phân tích tự động qua tin nhắn Telegram.**
- **AI RAG & Machine Learning**: Đánh giá độ tin cậy của tín hiệu dựa trên mô hình học máy Adaptive. Tự động tính kích thước vị thế (Position Sizing).
- Quét tổng quát mỗi 15 phút: lấy dữ liệu, phân tích, gọi AI, gửi Telegram.
- Quét khẩn cấp mỗi 5 phút: chỉ theo dõi coin đang có vị thế mở.
- **Continuous Learning & Báo cáo Tuần**: Tự động tải lại dữ liệu thị trường và huấn luyện lại AI vào 23:30 Chủ Nhật hàng tuần, kèm theo báo cáo tổng kết tuần lúc 23:45.

**Tab 2 — Backend API:**

```bash
python api/server.py
```

**Tab 3 — Web Dashboard:**

```bash
cd web
npm run dev -- --port 3000 --host
```

Truy cập: **[http://localhost:3000](http://localhost:3000)**

---

## Chạy Backtest

```bash
# Đánh giá chất lượng tín hiệu (win rate, profit factor, hold period)
python -X utf8 backtest_eval.py

# Backtest đầy đủ với báo cáo PnL chi tiết
python backtest.py
```

---

## Chạy Unit Test

```bash
pytest
pytest tests/test_analysis.py   # Chỉ test module phân tích
```

---

## Cấu trúc Dự án

```
besttime-crypto/
├── main.py                      # Entry point + scheduler + AI worker thread
├── backtest.py                  # Full historical backtest
├── backtest_eval.py             # Signal quality evaluator (win rate × hold period)
├── trading_strategies_summary.md # Tài liệu công thức và chiến lược kỹ thuật
├── requirements.txt
├── .env                         # API keys (không commit)
├── btc_scraper/
│   ├── config.py               # COINS, INTERVAL, LIMIT, API keys
│   ├── analysis.py             # Indicators + 6-layer signal logic + TP/SL
│   ├── sentiment.py            # Fear & Greed Index (cached)
│   ├── ai_analyst.py           # Gemini AI prompt builder (MTF + RAG)
│   ├── position_tracker.py     # Position management + performance metrics
│   ├── auto_trader.py          # Đặt lệnh tự động và ngắt mạch (Circuit Breaker)
│   ├── ccxt_client.py          # Wrapper tương tác Binance Testnet bằng CCXT
│   ├── telegram_bot.py         # Telegram broadcaster
│   ├── display.py              # Rich terminal table rendering
│   └── exchanges/
│       └── binance.py          # Binance OHLCV API
├── api/
│   └── server.py               # FastAPI backend (port 8000)
├── web/                        # React / Vite frontend (port 3000)
├── data/
│   ├── positions.json          # Open + closed positions store
│   ├── latest_signals.json     # Latest analysis snapshot (read by Web)
│   └── latest_ai_analysis.json # Latest Gemini AI report (read by Web)
├── logs/
│   ├── closed_positions.json   # Append-only closed trade log (RAG source)
│   ├── auto_trade_log.json     # Nhật ký giao dịch tự động (Audit Log)
│   └── auto_trade_circuit.json # Trạng thái Circuit Breaker
├── scripts/
│   ├── manage_positions.py     # CLI backend for ./pos
│   ├── prepare_ml_data.py      # Export ML training data + RAG context
│   ├── generate_rag_prompts.py # Generate RAG narratives for Gemini
│   ├── continuous_learning.py  # Retrain Adaptive Model tự động hàng tuần
│   └── weekly_job.py           # Sinh Weekly Report tự động hàng tuần
├── tests/
│   ├── test_analysis.py        # Kiểm thử module phân tích
│   ├── test_auto_trader.py     # Kiểm thử AutoTrader
│   └── test_filters.py         # Kiểm thử các bộ lọc
└── pos                         # ./pos CLI shortcut script
```

---

## Chuẩn bị Dữ liệu cho ML

Để cào dữ liệu lịch sử trên diện rộng phục vụ huấn luyện mô hình:

```bash
# Cào dữ liệu lịch sử theo tháng (cấu hình trong fetch_historical_range.py)
python fetch_historical_range.py
```

Để sử dụng lịch sử giao dịch thực tế cho machine learning, chạy:

```bash
# Xuất dataset ML + RAG context từ lịch sử giao dịch
python scripts/prepare_ml_data.py

# Sinh narratives RAG cho Gemini AI
python scripts/generate_rag_prompts.py
```

**Output:**

- `data/ml_training_data.csv` — Dataset 30+ cột cho model training
- `data/ml_rag_context.json` — Structured RAG context (win rate, directional stats, scenarios)
- `data/rag_prompts.md` — Markdown narratives để tích hợp vào Gemini prompt

**Xem chi tiết:** [ML_DATA_GUIDE.md](ML_DATA_GUIDE.md)

---

## Tài liệu Thiết kế Hệ thống (System Design)

Để xem chi tiết kiến trúc tổng thể, luồng dữ liệu, tính năng Explainable AI, Dynamic Position Sizing và định hướng phát triển từ một Signal Bot thành nền tảng **AI Quant Trading Platform** hoàn chỉnh, vui lòng tham khảo:

**👉 [SYSTEM DESIGN DOCUMENT (TDD)](SYSTEM_DESIGN.md)**
