# CHIẾN LƯỢC GIAO DỊCH & CÔNG THỨC TOÁN HỌC ĐANG SỬ DỤNG

Tài liệu này tổng hợp toàn bộ các chỉ báo kỹ thuật, công thức tính toán, quy tắc xác định tín hiệu (6 lớp lọc) và logic quản lý vị thế hiện tại trong hệ thống bot giao dịch Crypto.

> **Cập nhật lần cuối**: 09/06/2026 — Sau backtest v2 (8.000 điểm dữ liệu, 10 coin, 1000 nến 15m)

---

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

### Lớp 7 — Machine Learning / Adaptive Scoring (Mới)
* **Mục đích**: Thay vì chỉ dùng Rule-based cứng nhắc, tín hiệu sau cùng sẽ được đưa qua mô hình Machine Learning (Random Forest / Logistic) để tính Xác Suất Thắng (Win Probability).
* **Ngưỡng hành động (Threshold)**: Điểm > 51% (BUY), < 49% (SELL). Vùng 49-51% là NEUTRAL.
* **Đầu ra**: 
  - `score` (0-100%): Xác suất lệnh sẽ thắng. Điểm quanh 50% là trung lập.
  - `confidence`: HIGH (điểm cách xa 50%), MEDIUM, LOW.
  - `position_size`: Tự động nội suy từ 0.25 (nhỏ) đến 1.0 (Full volume) dựa trên khoảng cách của score so với mức 50 (Kelly Criterion rút gọn).
* **Cơ chế tự học (Continuous Learning)**:
  - Lệnh đóng được lưu vào `logs/closed_positions.json`.
  - Hàng tuần (23:30 Chủ Nhật), script `scripts/continuous_learning.py` tự động chạy để tải dữ liệu, tự sinh nhãn, train lại mô hình và kiểm tra Concept Drift (phát hiện nếu mô hình bị out-of-date). Nếu an toàn (ROC-AUC > 0.55), mô hình mới sẽ được lưu đè lên `adaptive_model.joblib`.

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

## 5. Kết quả Backtest v2 (Tham khảo)

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
