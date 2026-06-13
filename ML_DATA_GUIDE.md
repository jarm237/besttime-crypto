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

Hiện `btc_scraper/ai_analyst.py` đã dùng RAG từ `logs/closed_positions.json` và dataset lịch sử để bổ sung prompt Gemini AI với:
- Win rate & average PnL theo coin
- Hiệu suất tín hiệu theo hướng LONG/SHORT
- Các cảnh báo chiến lược và kịch bản lịch sử

### Improved RAG Pipeline

1. **Dùng `data/ml_rag_context.json` thay vì tính runtime:**
   ```python
   from pathlib import Path
   import json

   path = Path("data/ml_rag_context.json")
   with path.open("r", encoding="utf-8") as f:
       rag_context = json.load(f)
   ```

2. **Xây prompt trực tiếp từ context:**
   - Tổng quan thị trường
   - Hiệu suất từng coin
   - So sánh tín hiệu hiện tại với lịch sử

3. **Scenario-based analysis:**
   ```
   Hiện tại lệnh STRONG_BUY trên BTC. Trong lịch sử:
   - LONG WIN: 3 lệnh, avg hold 4.5h, avg PnL +1.8%
   - LONG LOSS: 2 lệnh, avg hold 2.1h, avg PnL -2.1%
   → Kỳ vọng: +0.84% nếu vào lệnh này
   ```

4. **RAG prompt generation:**
   - Source: `data/rag_prompts.md`
   - Build once, reuse cho Gemini
   - Giảm overhead tính toán runtime

---

## 📈 Hướng ML tiếp theo (Lộ trình Roadmap)

### Phase 1: Signal Confidence Scoring & Feature Engineering (Đã hoàn thành)
1. **Thu thập dữ liệu lịch sử:** Sử dụng `fetch_historical_range.py` để cào dữ liệu lịch sử chất lượng cao từ Binance qua nhiều tháng liên tục (đã tích hợp đầy đủ **18 tháng**, từ Tháng 1/2025 đến Tháng 6/2026, với **18,908 mẫu giao dịch**).
2. **Huấn luyện mô hình Adaptive:** Chạy `train_april_model.py` để load toàn bộ dữ liệu 18 tháng, chạy giả lập sinh tín hiệu, trích xuất đặc trưng kỹ thuật (`FEATURE_SCHEMA`), huấn luyện mô hình **Random Forest Classifier** và lưu tại `logs/adaptive_model.joblib`.
3. **Hiệu chuẩn xác suất (Calibration):** Chia kết quả hiệu chuẩn thành 5 nhóm xác suất (0.0-0.4, 0.4-0.6, 0.6-0.7, 0.7-0.8, 0.8-1.0) và lưu vào `logs/meta_model.json`.

### Phase 2: Ensemble Machine Learning (Đã hoàn thành)
1. **Mô hình Ensemble:** Xây dựng `EnsembleMetaModel` kết hợp RandomForest, LightGBM, CatBoost để tăng độ chính xác dự báo xác suất thắng.
2. **Probability Calibration:** Áp dụng Isotonic Regression để hiệu chuẩn xác suất dự báo, tối ưu hóa sai số MACE xuống dưới 20%.

### Phase 3: Dynamic Parameter Tuning & Risk Management (Đã hoàn thành)
1. **Bayesian Optimization (Optuna):** Chạy tối ưu hóa Optuna (`scripts/optimize_hyperparameters.py`) hàng tuần để tự động tìm tham số ATR multipliers, signal cutoff, kelly multiplier, và regime scaling.
2. **Dynamic TP/SL & Position Sizing:** Tích hợp TP/SL co giãn động theo regime và quản lý vốn Kelly điều chỉnh theo mô hình ML.
3. **Risk Management:** Triển khai `RiskManager` kiểm soát drawdown (<10%) và chuỗi lệnh thua liên tiếp.

### Phase 4: Reinforcement Learning Exit Manager (Đã hoàn thành)
1. **Trading Environment:** Định nghĩa môi trường Gymnasium (`btc_scraper/rl_trading_env.py`) mô phỏng các trade episodes.
2. **RL Agent Training:** Huấn luyện các Agent PPO, DQN, A2C (`train_rl_exit_manager.py`) trên dữ liệu tín hiệu lịch sử, lưu checkpoint tại `logs/rl_models/`.
3. **Evaluation:** Đánh giá hiệu năng và so sánh giữa RL exit strategy và baseline rule-based exit (`evaluate_rl_phase4.py`).

### Phase 5: Portfolio Optimization & Multi-Agent AI (Đã hoàn thành)
1. **Tối ưu hóa danh mục:** Phân bổ vốn hiệu quả qua Mean-Variance (MVO), Risk Parity, Sharpe/Sortino ratio sử dụng module `portfolio_manager.py`.
2. **Hệ thống Multi-Agent:** Tái cấu trúc hệ thống thành đa tác nhân (`multi_agent.py`) bao gồm: MarketAnalystAgent, SignalGeneratorAgent, RiskManagerAgent, PortfolioManagerAgent, RLExitAgent và ExecutionAgent được điều phối tự động bởi `AgentOrchestrator`.

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
├── closed_positions.json      ← Append-only closed trade log (source)
├── auto_trade_log.json        ← Lịch sử đặt/đóng lệnh tự động CCXT (Audit Log)
└── auto_trade_circuit.json    ← Lưu trạng thái ngắt mạch (Circuit Breaker)
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
