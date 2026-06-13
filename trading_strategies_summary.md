# CHIẾN LƯỢC GIAO DỊCH & CÔNG THỨC TOÁN HỌC ĐANG SỬ DỤNG

Tài liệu này tổng hợp toàn bộ các chỉ báo kỹ thuật, công thức tính toán, quy tắc xác định tín hiệu (6 lớp lọc) và logic quản lý vị thế hiện tại trong hệ thống bot giao dịch Crypto.

> **Cập nhật lần cuối**: 14/06/2026 — Thêm Phase 4 RL Exit Manager và cập nhật ML workflow

---
## 0. Web Dashboard & UI

- **React / Vite dashboard** tại `http://localhost:3000` kết nối với backend `api/server.py`.
- **Tab chính**:
  - `Tín Hiệu Thị Trường`: Live market signals, RSI, trend, chandelier, meta confidence.
  - `Vị Thế Đang Mở`: Quản lý vị thế, mở/đóng lệnh, xem PnL, SL, TP.
  - `CCXT Auto Trading Monitor`: Hiển thị chế độ Dry Run / Live, Circuit Breaker, daily trade limit, audit logs.
  - `Meta Model Analytics`: Metrics huấn luyện, feature importance, calibration buckets.
  - `Gemini AI Insights`: Báo cáo phân tích AI từ `data/latest_ai_analysis.json`.
- **Chức năng UI**: thêm lệnh mới, đóng lệnh hiện tại, xem trạng thái auto-trading và phân tích model.
## 1. Các Chỉ báo Kỹ thuật & Công thức Toán học

Hệ thống được lập trình hoàn toàn bằng Python thuần (không phụ thuộc vào thư viện bên ngoài như `pandas` hay `ta`).

### 1.1. Average True Range (ATR - 14)
* **Mục đích**: Đo lường độ biến động của giá — là nền tảng tính Stop Loss và Take Profit.
* **Công thức**:
  1. **True Range (TR)**:
     $$TR = \max(High - Low, |High - Close_{prev}|, |Low - Close_{prev}|)$$
  2. Khởi tạo ATR bằng SMA của 14 phiên đầu:
     $$ATR_{14} = \frac{1}{14} \sum_{i=1}^{14} TR_i$$
  3. Các phiên tiếp theo dùng **Wilder's Smoothing** ($\alpha = 1/14$):
     $$ATR_{t} = \frac{ATR_{t-1} \times 13 + TR_t}{14}$$

### 1.2. Relative Strength Index (RSI - 14)
* **Mục đích**: Đo động lượng — xác định vùng quá mua (Overbought > 70) và quá bán (Oversold < 30).
* **Công thức**:
  1. Gains/Losses mỗi phiên; khởi tạo bằng SMA 14 phiên đầu.
  2. Wilder's Smoothing tiếp theo:
     $$AvgGain_t = \frac{AvgGain_{t-1} \times 13 + Gain_t}{14}$$
  3. $RS = AvgGain / AvgLoss$; $RSI = 100 - \frac{100}{1 + RS}$

### 1.3. Exponential Moving Average (EMA - 9 & 21)
* **Mục đích**: Xu hướng ngắn hạn và điểm giao cắt tín hiệu.
* **Công thức**: $k = \frac{2}{N+1}$; $EMA_t = (Close_t - EMA_{t-1}) \times k + EMA_{t-1}$

### 1.4. Simple Moving Average (SMA - 50 & 200)
* **Mục đích**: Xu hướng trung hạn (SMA 50) và dài hạn / "Bull/Bear Market line" (SMA 200).
* **Công thức**: $SMA_N = \frac{1}{N} \sum_{i=0}^{N-1} Close_{t-i}$ — sliding window O(N).

### 1.5. MACD (12, 26, 9)
* **Mục đích**: Đánh giá động lượng và độ mạnh yếu xu hướng (dùng trong AI prompt, hiển thị Dashboard).
* **Công thức**:
  * MACD Line = $EMA_{12} - EMA_{26}$
  * Signal Line = $EMA_9(MACD\_Line)$
  * Histogram = $MACD\_Line - Signal\_Line$

### 1.6. Bollinger Bands (BB - 20, std=2)
* **Mục đích**: Xác định biên độ dao động tiêu chuẩn — TP1 (Middle Band) và TP2 (Upper/Lower Band).
* **Công thức**: Middle = $SMA_{20}$; $\sigma = \sqrt{\frac{1}{20}\sum(Close - Middle)^2}$; Upper/Lower = Middle ± 2σ

### 1.7. Chandelier Exit (22, 3.0)
* **Mục đích**: Lọc xu hướng ATR-based — bảo vệ khỏi downtrend mà MA phản ứng chậm.
* **Công thức**:
  * $LongStop = Highest\_High_{22} - 3.0 \times ATR_{22}$ → nếu Close < LongStop: **BEAR** (cấm BUY)
  * $ShortStop = Lowest\_Low_{22} + 3.0 \times ATR_{22}$ → nếu Close > ShortStop: **BULL** (cho phép BUY)
  * Vùng trung gian: giữ nguyên trạng thái trước đó.

### 1.8. Volume SMA (20) & Volume Spike
* **Công thức**: VolumeSpike = ($Volume_{current} > 1.3 \times VolumeSMA_{20}$)

---

## 2. Chiến lược Tín hiệu (6 Lớp Lọc Quyết Định)

```
Nến đóng cửa
    → [L1] SMA200 Trend Filter  (Bull/Bear context)
    → [L2] SMA50 Pullback Zone  (BUY Pullback entry)
    → [L3] EMA 9/21 Crossover   (Golden/Death Cross)
    → [L4] Chandelier Exit      (Block BUY khi BEAR)
    → [L5] Volume + SFP Sweep   (Confirm momentum)
    → [L6] Fear & Greed Sentiment (Downgrade extreme)
    → [L7] Machine Learning Scoring (Logistic Regression - Tự động điều chỉnh)
    → OUTPUT: BUY / SELL / WEAK / NEUTRAL (kèm Score 0-100% và Position Size)
```

### Lớp 1 — SMA 200 Trend Filter
* Bull Market: $Close > SMA_{200}$ → cho phép BUY
* Bear Market: $Close < SMA_{200}$ → chỉ cho phép SELL

### Lớp 2 — SMA 50 Pullback Zone
* **BUY (Pullback-Zone)**: Kích hoạt khi:
  * EMA9 < EMA21 (short-term pullback)
  * $SMA_{50} \times 0.99 \leq Close \leq EMA_{21}$ (trong vùng pullback)
  * Mới bước vào zone (tránh spam)
  * Nến xanh (Close > Open)
  * SMA50 đang dốc lên
  * Close > SMA200 (bull market)
  * Chandelier = BULL
  * RSI < 55

### Lớp 3 — EMA Crossover Matrix
* **Golden Cross**: prev_EMA9 ≤ prev_EMA21 AND curr_EMA9 > curr_EMA21 → BUY/WEAK BUY
* **Death Cross**: prev_EMA9 ≥ prev_EMA21 AND curr_EMA9 < curr_EMA21 → SELL/WEAK SELL
* SMA200 xác nhận: Trên SMA200 → BUY mạnh; Dưới SMA200 → WEAK BUY (cảnh báo bull trap)

### Lớp 4 — Chandelier Exit Filter
* Chandelier = BEAR → Block tất cả BUY → hạ cấp xuống WEAK BUY (Crossover-Blocked)

### Lớp 5 — Volume Spike & SFP
* **SFP Bullish** (BUY): Low < Support₅₀ AND Close > Support₅₀ AND RSI < 45
  * Support = min(Low) của 50 nến trước (không kể nến hiện tại)
* **SFP Bearish** (SELL): High > Resistance₅₀ AND Close < Resistance₅₀ AND RSI > 55 AND below SMA200
* **RSI Turning Up** (STRONG BUY): prev_RSI ≤ 30 AND curr_RSI > 30
* **RSI Turning Down** (STRONG SELL): prev_RSI ≥ 70 AND curr_RSI < 70
* **Break SMA50** (SELL): prev_Close > prev_SMA50 AND curr_Close < curr_SMA50 AND SMA50 downtrend AND below SMA200

### Lớp 6 — Fear & Greed Sentiment (mới — Level 1 AI)
* Nguồn: `alternative.me/fng` API, cache 1 giờ.
* Mapping: raw 0–100 → score [-1.0, +1.0] (tuyến tính, trừ 50, chia 50)
* **Extreme Fear** (score < −0.6): Hạ cấp STRONG BUY → WEAK BUY (Sentiment-Blocked)
* **Extreme Greed** (score > +0.6): Hạ cấp STRONG SELL → WEAK SELL (Sentiment-Blocked)

### Lớp 7 — Machine Learning / Adaptive Scoring
* **Mục đích**: Chấm điểm động xác suất thắng thực tế của tín hiệu (`meta_confidence`) bằng mô hình Machine Learning được huấn luyện trên dữ liệu lịch sử giao dịch.
* **Mô hình triển khai**: **RandomForestClassifier** (`btc_scraper/meta_model.py`) với **14 đặc trưng kỹ thuật** cố định (`btc_scraper/feature_extractor.py`).
* **Hiệu chuẩn Platt**: Đầu ra được hiệu chuẩn bằng hàm Sigmoid (Platt scaling) để dự đoán xác suất chính xác thay vì chỉ dự đoán nhị phân (WIN/LOSS).
* **Đầu ra**: 
  - `meta_confidence` (0.0-1.0): Xác suất thắng dự báo của tín hiệu. Ngưỡng giao dịch tự động mặc định là ≥ 85%.
  - Tự động hạ cấp / bỏ qua tín hiệu nếu xác suất thắng thấp.
* **Cơ chế tự học (Continuous Learning)**:
  - Lệnh đóng được tự động đồng bộ hóa và lưu trữ làm mẫu dữ liệu huấn luyện.
  - Hàng tuần vào lúc 23:30 Chủ Nhật, bot chạy pipeline tự động tải dữ liệu OHLCV, backtest tự gán nhãn và huấn luyện lại mô hình, đồng thời đánh giá Concept Drift (nếu CV ROC-AUC ≥ 0.55 thì tự động ghi đè mô hình mới lên `adaptive_model.joblib`).

---

## 3. Công thức Entry, Stop Loss (SL) & Take Profit (TP)

Tham số mặc định: `atr_sl_mult = 1.2`, `atr_tp_mult = 3.5`

### 3.1. Lệnh BUY (Long)

| Level | Công thức | Logic |
|-------|-----------|-------|
| **Entry** | $Close$ | Giá đóng cửa hiện tại |
| **SL** | $\max(Entry - 1.2 \times ATR,\ Support \times 0.998)$ | Chọn mức **gần** giá hơn (thắt chặt rủi ro). Fallback về ATR nếu SL ≥ Entry |
| **TP1** | $\min(BB\_Middle,\ Entry + 3.5 \times ATR)$ | Mục tiêu bảo thủ — BB Middle hoặc ATR×3.5 |
| **TP2** | $\min([Resistance \times 0.998,\ BB\_Upper \times 0.998,\ Entry + 7.0 \times ATR])$ | Chỉ xét ứng viên > TP1 |

### 3.2. Lệnh SELL (Short)

| Level | Công thức | Logic |
|-------|-----------|-------|
| **Entry** | $Close$ | Giá đóng cửa hiện tại |
| **SL** | $\min(Entry + 1.2 \times ATR,\ Resistance \times 1.002)$ | Chọn mức **gần** giá hơn. Fallback về ATR nếu SL ≤ Entry |
| **TP1** | $\max(BB\_Middle,\ Entry - 3.5 \times ATR)$ | Mục tiêu bảo thủ — BB Middle hoặc ATR×3.5 |
| **TP2** | $\max([Support \times 1.002,\ BB\_Lower \times 1.002,\ Entry - 7.0 \times ATR])$ | Chỉ xét ứng viên < TP1 |

### 3.3. Kết quả Backtest về TP/SL (8.000 nến)

| Tham số TP1 | WR BUY | TP1 Hit Rate | Ghi chú |
|-------------|--------|-------------|---------|
| ATR × 3.5 (hiện tại) | 70.5% | 27% | TP1 xa, nhiều TIMEOUT |
| ATR × 2.0 (đề xuất) | ~75% est | ~45% est | Bắt move ngắn tốt hơn |

---

## 4. Quy tắc Quản lý Vị thế

### 4.1. Khuyến nghị tự động (evaluate_positions)

| Tình huống | Khuyến nghị | Urgency |
|-----------|------------|---------|
| Close ≤ SL (LONG) hoặc Close ≥ SL (SHORT) | 🚨 CẮT LỖ NGAY | HIGH |
| Close ≥ TP2 (LONG) hoặc Close ≤ TP2 (SHORT) | 🎯 CHỐT LỜI TP2 | HIGH |
| Close ≥ TP1 (LONG) hoặc Close ≤ TP1 (SHORT) | ✅ Xem xét CHỐT TP1 (50%) | MEDIUM |
| Xuất hiện tín hiệu đảo chiều ngược hướng vị thế | ⚠️ XEM XÉT ĐÓNG LỆNH | MEDIUM |
| PnL < −3% | ⚠️ CẢNH BÁO LỖ | MEDIUM |
| Còn lại | 💤 GIỮ LỆNH | LOW |

### 4.2. Công thức Hiệu suất

$$PnL\%_{LONG} = \frac{ExitPrice - EntryPrice}{EntryPrice} \times 100$$
$$PnL\%_{SHORT} = \frac{EntryPrice - ExitPrice}{EntryPrice} \times 100$$
$$R = \frac{PnL\%}{Risk\%}, \quad Risk\% = \frac{|Entry - SL|}{Entry} \times 100$$

**Phí giao dịch** (giả định 0.1% mỗi chiều — Binance Spot):
$$Fee = Invested \times 0.001 + (Invested + PnL_{USD}) \times 0.001$$
$$NetReceived = Invested + PnL_{USD} - Fee$$

---

## 5. Reinforcement Learning Exit Manager (Phase 4)

### Mục tiêu
- Tự học chiến lược đóng lệnh tối ưu thay vì dùng ngưỡng tĩnh TP/SL.
- Cân bằng lợi nhuận và tổn thất với penalty drawdown và bonus cho việc thoát gần đỉnh PnL.

### Môi trường RL
- **State:** 18 feature bao gồm RSI, MACD Histogram, ATR%, ADX, meta_confidence, regime one-hot, pnl_pct, hold_time, fear_greed, volume_ratio, BB width.
- **Actions:** HOLD, PARTIAL_CLOSE_50, MOVE_SL_TO_BREAKEVEN, TAKE_PROFIT, EXIT.
- **Reward:** PnL thực tế ± penalty/bonus.
- **Mục tiêu:** Phát triển exit manager có khả năng đóng vị thế chính xác hơn rule-based và tối ưu hóa tỷ lệ thắng / lợi nhuận ròng.

### File liên quan
- `btc_scraper/rl_trading_env.py` — Gymnasium environment.
- `train_rl_exit_manager.py` — Huấn luyện RL với PPO/DQN/A2C.
- `evaluate_rl_phase4.py` — So sánh với rule-based exit.
- `PHASE_4_RL_DOCUMENTATION.md` — Tài liệu chi tiết Phase 4.

### Kết quả ban đầu
- Đã huấn luyện thành công đường PPO/DQN/A2C với reward ổn định `0.50` sau 20k steps.
- Mô hình RL đã sẵn sàng để thử nghiệm A/B so với thuật toán đóng lệnh cũ.

---

## 6. Kết quả Backtest v2 (Tham khảo)

Chạy `python -X utf8 backtest_eval.py` để tái tạo kết quả:

| Nhóm tín hiệu | Hold tối ưu | Win Rate | Profit Factor | Kết luận |
|---------------|------------|---------|---------------|---------|
| **STRONG BUY** | 1h (4 nến) | **70.5%** | **2.95** | ✅ Dùng được |
| **STRONG SELL** | 6h (24 nến) | **66.4%** | **2.92** | ✅ Cần hold đủ dài |
| WEAK BUY | bất kỳ | ~35% | 0.24 | ❌ Không có edge — bỏ qua |
| WEAK SELL | bất kỳ | ~25% | 0.54 | ⚠️ Dùng làm cảnh báo thôi |

**Sub-type hiệu quả nhất**:
* BUY — **RSI Reversal** (72.4% WR, hold 1h): 86% tổng tín hiệu BUY
* SELL — **EMA Death Cross** (87.1% WR, hold 4h) và **Break SMA50** (87.1% WR, hold 6h)

---

## 6. Giao dịch Tự động (Auto-Trading CCXT) & Quản lý Rủi ro

Hệ thống tích hợp thư viện CCXT để tự động khớp lệnh trên sàn giao dịch Binance Spot (mặc định sử dụng Sandbox/Testnet để đảm bảo an toàn).

### 6.1. Điều kiện Kích hoạt Lệnh đặt tự động (`should_trade`)
Mỗi chu kỳ quét 15 phút, tín hiệu mới sinh ra phải thỏa mãn:
1. Coin nằm trong danh sách whitelist (`AUTO_TRADE_COINS`).
2. Tín hiệu là BUY hoặc SELL rõ ràng (loại bỏ tín hiệu WEAK và NEUTRAL).
3. **Độ tin cậy của Meta Model (`meta_confidence`)** $\geq$ **ngưỡng cấu hình** (mặc định **85%**).
4. **Signal score** $\geq$ **ngưỡng phụ** (mặc định **75**).
5. Không có vị thế đang mở cùng cặp tiền và cùng chiều giao dịch để tránh nhồi lệnh vô kỷ luật.
6. Hệ thống ngắt mạch (Circuit Breaker) và giới hạn ngày ở trạng thái bình thường.

### 6.2. Tính toán Quy mô Vị thế (Fixed-Fractional Risk Sizing)
Sử dụng phương pháp quản lý vốn dựa trên khoảng cách dừng lỗ để giữ cho mức rủi ro cố định ở mức **2%** tài khoản mỗi lệnh:
$$Risk\_USDT = Account\_USDT \times Risk\_Pct$$
$$SL\_Distance\_Pct = \frac{|Entry\_Price - SL\_Price|}{Entry\_Price}$$
$$Position\_Sizing\_USDT = \frac{Risk\_USDT}{SL\_Distance\_Pct}$$

*Cơ chế ràng buộc (Caps)*:
- Giới hạn tối thiểu (`AUTO_TRADE_MIN_TRADE_USDT`): Mặc định **10 USDT** (Ngưỡng tối thiểu Binance Notional).
- Giới hạn tối đa (`AUTO_TRADE_MAX_TRADE_USDT`): Mặc định **100 USDT** (Tránh oversizing khi khoảng cách SL quá hẹp).

### 6.3. Cơ chế Bảo vệ tài khoản (Circuit Breaker & Limits)
- **Daily Trade Limit**: Không đặt quá số lượng lệnh quy định trong ngày (mặc định tối đa **5 lệnh/ngày**).
- **Circuit Breaker**: Tự động ngắt kết nối giao dịch tự động trong **24 giờ** nếu hệ thống gặp **5 lệnh thua liên tiếp** (`consecutive_losses` $\geq 5$). Để tiếp tục giao dịch sau khi hết hạn, Circuit Breaker tự động reset hoặc khởi động lại bot.
- **Dry-run Mode (`AUTO_TRADE_DRY_RUN=true`)**: Mặc định luôn bật. Ở chế độ này, mọi lệnh đặt/đóng đều chỉ được ghi nhận vào `logs/auto_trade_log.json` và thông báo qua Telegram mà không tạo lệnh thực tế trên sàn.

### 6.4. Cơ chế tự động đóng lệnh (Auto Close)
Mỗi chu kỳ quét khẩn cấp 5 phút (`fetch_and_analyze_open_positions_only`), bot tự động đối chiếu giá thị trường hiện tại của các vị thế mở được tạo bởi bot (`[AUTO-...`):
- Nếu chạm dừng lỗ khuyến nghị: Tự động đặt lệnh Market đóng vị thế, ghi nhận kết quả `"LOSS"` vào Circuit Breaker và gửi cảnh báo Telegram.
- Nếu chạm mức chốt lời 2 (`TP2`): Tự động đặt lệnh Market đóng vị thế, ghi nhận kết quả `"WIN"` vào Circuit Breaker và gửi thông báo Telegram.
- Nếu người dùng đóng vị thế thủ công trên Dashboard, API backend sẽ tự động đồng bộ đóng vị thế trên Binance Testnet qua CCXT.

---

## 7. Portfolio Optimization & Multi-Agent AI (Phase 5)

### 7.1. Tối ưu hóa danh mục (Portfolio Sizing)
Khi xuất hiện từ 2 tín hiệu BUY/SELL đồng thời trở lên, hệ thống sẽ chuyển từ định cỡ vị thế độc lập sang tối ưu danh mục:
1. **Tính tương quan returns:** Lấy nến 15m của 100 chu kỳ gần nhất để lập ma trận covariance.
2. **Mean-Variance Optimization (MVO):** Tối đa hóa tỷ lệ Sharpe dự kiến dựa trên covariance và expected returns từ xác suất Meta model.
3. **Risk Parity:** Tìm tỷ trọng vốn cân bằng đóng đóng góp rủi ro của mỗi tài sản trong danh mục.

### 7.2. Kiến trúc Đa tác nhân (Multi-Agent)
Mã nguồn core loop được chia tách thành các Agent độc lập điều phối bởi `AgentOrchestrator`:
- `MarketAnalystAgent`: Phân tích chỉ báo kỹ thuật và xu hướng MTF.
- `SignalGeneratorAgent`: Chấm điểm xác suất Meta model và lọc cutoff.
- `RiskManagerAgent`: Áp dụng drawdown cap và chuỗi lệnh thua.
- `PortfolioManagerAgent`: Thực thi tối ưu hóa danh mục MVO/Risk Parity.
- `RLExitAgent`: Đưa ra khuyến nghị đóng lệnh nâng cao qua Agent RL.
- `ExecutionAgent`: Giao dịch CCXT và ghi log shadow predictions.
