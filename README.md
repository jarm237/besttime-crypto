# besttime-crypto

Hệ thống Bot tự động cào dữ liệu tiền điện tử, phân tích tín hiệu kỹ thuật qua **6 lớp lọc thuật toán**, kết hợp **Gemini AI** để đưa ra nhận định thị trường đa khung thời gian, tích hợp **Fear & Greed Index** và **RAG từ lịch sử giao dịch** — gửi cảnh báo qua Telegram theo thời gian thực.

## Tính năng

- **Quét đa coin tự động** cho danh sách cấu hình (BTC, ETH, BNB, SOL, XRP...) mỗi 15 phút.
- **Phân tích kỹ thuật 6 lớp lọc** bằng Python thuần: RSI, EMA, SMA, MACD, Bollinger Bands, ATR, Chandelier Exit, Volume SMA, SFP.
- **Phân tích đa khung thời gian (MTF)**: Thu thập thêm nến 1h / 4h / 1d để gửi cho Gemini AI đánh giá xu hướng lớn hơn.
- **Fear & Greed Index (Lớp 6)**: Lấy từ `alternative.me/fng`, cache 1h. Tự động hạ cấp tín hiệu BUY khi Extreme Fear, hạ cấp SELL khi Extreme Greed.
- **Gemini AI Analyst**: Tổng hợp toàn bộ tín hiệu 15m + MTF + sentiment + lịch sử giao dịch (RAG) để đưa ra nhận định thị trường bằng tiếng Việt.
- **Quản lý vị thế thủ công (Position Tracker)**: Nhập lệnh đã khớp, bot tự động giám sát và gửi khuyến nghị Chốt Lời / Cắt Lỗ qua Telegram mỗi 5 phút.
- **Web Dashboard**: Giao diện trực quan xem tín hiệu và AI report tại `http://localhost:3000`.
- **Backtest**: Script `backtest_eval.py` đánh giá chất lượng tín hiệu theo win rate, Profit Factor và hold period tối ưu.
- **Telegram Alerts**: Gửi bảng tín hiệu + AI report tự động sau mỗi chu kỳ quét.

---

## Backtest (Kết quả đã xác minh)

Trên **8.000 điểm dữ liệu** (1000 nến 15m × 10 coin):

| Loại tín hiệu | Win Rate | Profit Factor | Hold tối ưu |
|---------------|---------|---------------|------------|
| **STRONG BUY** | **70.5%** | **2.95** | **1h (4 nến)** |
| **STRONG SELL** | **66.4%** | **2.92** | **6h (24 nến)** |
| WEAK BUY | ~35% | 0.24 | ❌ Không có edge |

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

---

## Cài đặt và Khởi chạy

Hệ thống gồm 3 thành phần chạy song song:
1. **Bot cốt lõi** (`main.py`) — Quét tín hiệu, gọi AI, gửi Telegram.
2. **Backend API** (`api/server.py`) — FastAPI phục vụ dữ liệu cho Web Dashboard (cổng 8000).
3. **Web Dashboard** (`web/`) — Giao diện Vue 3 (cổng 3000).

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
```

### Bước 3: Khởi chạy toàn bộ hệ thống

**Cách nhanh nhất** — chạy cả 3 dịch vụ bằng một lệnh:

```bash
./start.sh
# Windows: .\start.ps1
```

Nhấn `Ctrl + C` để tắt toàn bộ.

---

### Chạy thủ công từng phần

**Tab 1 — Bot cốt lõi:**
```bash
python main.py
```
- Quét tổng quát mỗi 15 phút: lấy dữ liệu, phân tích, gọi AI, gửi Telegram.
- Quét khẩn cấp mỗi 5 phút: chỉ theo dõi coin đang có vị thế mở.

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
│   ├── telegram_bot.py         # Telegram broadcaster
│   ├── display.py              # Rich terminal table rendering
│   └── exchanges/
│       └── binance.py          # Binance OHLCV API
├── api/
│   └── server.py               # FastAPI backend (port 8000)
├── web/                        # Vue 3 / Vite frontend (port 3000)
├── data/
│   ├── positions.json          # Open + closed positions store
│   ├── latest_signals.json     # Latest analysis snapshot (read by Web)
│   └── latest_ai_analysis.json # Latest Gemini AI report (read by Web)
├── logs/
│   └── closed_positions.json   # Append-only closed trade log (RAG source)
├── scripts/
│   ├── manage_positions.py     # CLI backend for ./pos
│   ├── prepare_ml_data.py      # Export ML training data + RAG context
│   └── generate_rag_prompts.py # Generate RAG narratives for Gemini
├── tests/
│   └── test_analysis.py        # Unit tests
└── pos                         # ./pos CLI shortcut script
```

---

## Chuẩn bị Dữ liệu cho ML

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
