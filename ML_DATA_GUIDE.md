# ML Data Preparation & RAG Integration Guide

Dự án đã có infrastructure để chuẩn bị dữ liệu cho ML training và RAG (Retrieval-Augmented Generation) cho Gemini AI. Tài liệu này hướng dẫn cách dùng các script mới và tích hợp RAG vào luồng chính.

---

## 📊 Script chuẩn bị dữ liệu

### 1. `scripts/prepare_ml_data.py` — Xuất dataset ML

Chuyển đổi lịch sử giao dịch đã đóng thành dataset cấu trúc cho ML training.

**Cách dùng:**
```bash
python scripts/prepare_ml_data.py
```

**Output:**
- `data/ml_training_data.csv` — Dataset 30+ cột cho model training
  - Cơ bản: `coin`, `direction`, `entry_price`, `sell_price`, `pnl_pct`, `result`
  - Kỹ thuật snapshot: `entry_distance_to_sl_pct`, `entry_distance_to_tp1_pct`, `suggested_rr1`
  - Thời gian: `hold_hours`
  - Nhãn: `is_win` (0/1 cho classification)

- `data/ml_rag_context.json` — Dữ liệu RAG cấu trúc
  - Global stats: Win rate, avg PnL, profit factor
  - Per-coin stats: Win rate, avg PnL, 3 lệnh gần nhất
  - Directional stats: LONG vs SHORT performance
  - Signal stats: Win rate per signal type
  - Scenarios: Grouping by direction + result

### 2. `scripts/generate_rag_prompts.py` — Sinh RAG narratives

Chuyển đổi RAG context thành markdown narratives cho Gemini AI.

**Cách dùng:**
```bash
python scripts/generate_rag_prompts.py
```

**Output:**
- `data/rag_prompts.md` — Markdown tóm tắt lịch sử giao dịch
  - Tóm tắt toàn cục
  - Phân tích theo coin
  - Phân tích theo hướng (LONG vs SHORT)
  - Cảnh báo tín hiệu yếu
  - Nhận xét kịch bản

---

## 🔄 Quy trình chuẩn bị dữ liệu

### Bước 1: Chạy hệ thống một thời gian

Để có dữ liệu đủ lớn (tối thiểu 20-50 lệnh đóng):
```bash
python main.py  # Chạy bot
./pos close BTC 65000  # Đóng lệnh khi ready
# ... lặp lại với các lệnh khác
```

### Bước 2: Xuất dataset

Khi đã có lịch sử giao dịch, chạy:
```bash
python scripts/prepare_ml_data.py
```

Check kết quả:
```bash
head -5 data/ml_training_data.csv
cat data/ml_rag_context.json | jq '.global_stats'
```

### Bước 3: Sinh RAG prompts

```bash
python scripts/generate_rag_prompts.py
cat data/rag_prompts.md  # Xem kết quả
```

### Bước 4: Huấn luyện lại mô hình (Continuous Learning)

Dự án hiện đã tích hợp hệ thống Continuous Learning tự động. Bạn không cần phải code thủ công như trước.

**Cách dùng:**
```bash
python scripts/continuous_learning.py
```

Script này sẽ:
1. Lấy dữ liệu OHLCV 30 ngày gần nhất + warmup.
2. Mô phỏng backtest để tự động tạo nhãn (WIN/LOSS).
3. Huấn luyện lại mô hình RandomForestClassifier.
4. Đánh giá Cross-Validation ROC-AUC.
5. So sánh Concept Drift (nếu ROC-AUC >= 0.55 thì sẽ tự động cập nhật `adaptive_model.joblib`).
6. Gửi báo cáo kết quả Retrain lên Telegram.

*Lưu ý: Luồng này cũng đã được tự động lên lịch chạy vào lúc 23:30 Chủ Nhật hàng tuần trong `main.py`.*

---

## 🤖 Tích hợp RAG vào Gemini AI

### Current RAG Implementation

Hiện `btc_scraper/ai_analyst.py` đã dùng RAG đơn giản từ `_build_rag_block()`:
- Lấy `logs/closed_positions.json`
- Tóm tắt win rate + avg PnL per coin
- Đưa vào prompt Gemini

### Enhanced RAG (Future)

1. **Dùng `ml_rag_context.json` thay vì tính runtime:**
   ```python
   # In ai_analyst.py
   import json
   with open("data/ml_rag_context.json") as f:
       rag_context = json.load(f)
   
   # Thay vì _build_rag_block(), dùng rag_context trực tiếp
   ```

2. **Đưa signal-specific warnings vào prompt:**
   ```
   Lệnh [STRONG_BUY] hiện tại. Tuy nhiên, trong quá khứ:
   - STRONG_BUY có win rate 65% (20 lệnh) — tín hiệu TỐT
   - Tuy nhiên, trên BTC, STRONG_BUY chỉ 50% win rate — CẨN THẬN
   ```

3. **Scenario-based analysis:**
   ```
   Bạn muốn vào LONG trên BTC. Tương tự lịch sử:
   - LONG WIN: 3 lệnh, avg hold 4.5h, avg PnL +1.8%
   - LONG LOSS: 2 lệnh, avg hold 2.1h, avg PnL -2.1%
   → Kỳ vọng: +0.84% nếu vào lệnh này
   ```

---

## 📈 Hướng ML tiếp theo

### Phase 1: Signal Confidence Scoring
1. Load `ml_training_data.csv`
2. Train model: `is_win ~ [technical features]`
3. Save model → Load trong `analysis.py`
4. Khi sinh tín hiệu, đánh giá confidence → hạ cấp/skip nếu thấp

### Phase 2: Dynamic Parameter Tuning
1. Chạy `optuna` backtest mỗi tuần
2. Tối ưu: ATR multiplier, EMA period, RSI threshold
3. Cập nhật vào `analysis.py` tự động

### Phase 3: Anomaly Detection
1. Train `IsolationForest` trên dữ liệu 1m candles
2. Detect flash crash patterns
3. Auto-trigger defensive SL adjustment

---

## 📁 File Structure

```
data/
├── ml_training_data.csv       ← Dataset cho model training
├── ml_rag_context.json        ← Structured RAG context
└── rag_prompts.md             ← Markdown narratives cho AI

scripts/
├── prepare_ml_data.py         ← Xuất CSV + RAG context
└── generate_rag_prompts.py    ← Sinh markdown narratives

logs/
└── closed_positions.json      ← Append-only closed trade log (source)
```

---

## ⚙️ Cách tính các cột kỹ thuật

### `entry_distance_to_sl_pct`
```
= |entry_price - suggested_sl| / entry_price * 100
```
Độ xa SL từ entry (%). Thấp = SL gần, rủi ro cao; Cao = SL xa, rủi ro thấp.

### `entry_distance_to_tp1_pct`
```
= |suggested_tp1 - entry_price| / entry_price * 100
```
Khoảng cách TP1 từ entry (%). Cao = target lợi nhuận cao.

### `suggested_rr1`
```
= |suggested_tp1 - entry_price| / |entry_price - suggested_sl|
```
Risk:Reward ratio cho TP1. Thường target > 1 là tốt.

### `exit_distance_from_entry_pct`
```
= |sell_price - entry_price| / entry_price * 100
```
Thực tế giá exit từ entry (%). Âm = lỗ, dương = lãi.

---

## 🎯 Best Practices

1. **Chạy `prepare_ml_data.py` định kỳ** — hàng tuần hoặc khi đóng 5+ lệnh mới
2. **Review `rag_prompts.md`** — kiểm tra có cảnh báo nào cần hành động
3. **Bắt đầu ML training khi có ≥50 lệnh** — sample size nhỏ dễ overfit
4. **Validate model trên test set** — không train trên toàn bộ dữ liệu
5. **A/B test mô hình mới** — chạy song song với hệ thống hiện tại trước deploy

---

## 📞 Troubleshooting

**Q: Script báo "Không tìm thấy dữ liệu lệnh đã đóng"**
A: Bạn chưa đóng bất kỳ lệnh nào. Chạy `./pos close BTC 65000` để tạo dữ liệu.

**Q: `ml_training_data.csv` bị rỗng**
A: Kiểm tra `logs/closed_positions.json` có dữ liệu không. Nếu không, tạo lệnh bằng `./pos add BTC 65000`.

**Q: Làm sao thêm cột kỹ thuật mới?**
A: Sửa hàm `normalize_trade()` trong `prepare_ml_data.py` để tính cột mới, rồi thêm vào `FIELDNAMES`.
