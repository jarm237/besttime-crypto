# Đề xuất Ứng dụng AI/Machine Learning vào Besttime Crypto

Dự án hiện đã có một chuỗi xử lý tốt: **thu thập OHLCV ➔ tính chỉ báo kỹ thuật ➔ lọc tín hiệu rule-based ➔ quản lý vị thế ➔ gọi Gemini AI để phân tích**.

Tuy nhiên, mô hình AI bây giờ vẫn hoạt động ở mức “tư vấn” chứ chưa thực sự dùng lịch sử để dự đoán hay đánh giá xác suất thắng. Dưới đây là các hướng phát triển phù hợp với codebase hiện tại, đồng thời gắn vào nguồn dữ liệu thật của dự án.

---

## Mức 1: Giữ đúng hướng hiện có và làm dữ liệu tốt hơn

### 1. Củng cố RAG với dữ liệu giao dịch thật
- Hiện `btc_scraper/ai_analyst.py` đã dùng RAG đơn giản từ `logs/closed_positions.json`.
- Nên mở rộng và cấu trúc lại thành:
  - `coin + direction` tương tự,
  - `win_rate`, `avg_pnl`, `recent_trades`,
  - `kịch bản tương đồng` (ví dụ RSI/MACD/HTF khi lệnh win/lose).
- Kết quả: Gemini sẽ không còn chỉ “đọc” dữ liệu, mà sẽ nhận được bối cảnh lịch sử cụ thể để cảnh báo những tín hiệu yếu.

### 2. Chuẩn bị dữ liệu lịch sử giao dịch cho ML và RAG
- Nguồn dữ liệu chính hiện tại:
  - `logs/closed_positions.json` — append-only log của lệnh đã đóng.
  - `data/positions.json` — lưu cả vị thế mở và đóng.
- Cần thêm một bước chuẩn hóa xuất ra dataset ML như CSV hoặc JSON.
- Tôi đã bổ sung script `scripts/prepare_ml_data.py` để xuất `data/ml_training_data.csv` từ lịch sử đóng lệnh hiện có.

### 3. Tăng cường Sentiment đa nguồn
- Hiện có Fear & Greed và `sentiment_modify()` trong `btc_scraper/ai_analyst.py`.
- Bước tiếp theo nên là thêm sentiment tin tức (FinBERT/HuggingFace) hoặc news-summarization.
- Kết hợp sentiment làm filter bổ sung trong `analysis.py` thay vì chỉ dùng trong prompt AI.

---

## Mức 2: Học từ dữ liệu — Signal Scoring / Predictive Modeling

### 4. Xây mô hình đánh giá xác suất thắng của tín hiệu (Đã hoàn thành)
- Sử dụng dataset lịch sử từ `logs/closed_positions.json` và backtest simulator để huấn luyện mô hình.
- Hiện đã triển khai mô hình **RandomForestClassifier** trong `btc_scraper/meta_model.py` với **14 đặc trưng kỹ thuật** cố định (`feature_extractor.py`).
- Sử dụng phương pháp **Platt calibration** (hiệu chuẩn Sigmoid) để đưa ra xác suất thắng thực tế (`meta_confidence`) chính xác thay vì chỉ dự đoán nhị phân.
- Tích hợp vào `btc_scraper/signal_score.py` để chấm điểm tín hiệu theo thời gian thực và loại bỏ các tín hiệu yếu.

### 5. Tự động tối ưu tham số sau khi có dataset đủ lớn (Đang triển khai)
- Khi hệ thống chạy đủ vài chục đến vài trăm lệnh đóng, dùng `optuna` để tối ưu:
  - ATR multiplier cho TP/SL,
  - Các ngưỡng RSI, EMA,
  - Tỷ lệ điểm cutoff cho signal confidence.
- Đây là bước “data-driven tuning” phù hợp hơn là tinh chỉnh thủ công.

---

## Mức 3: Nghiên cứu dài hạn — Advanced AI/ML

### 6. Anomaly detection ở mức cảnh báo thị trường
- Không cần làm ngay, nhưng ý tưởng vẫn phù hợp:
  - Phát hiện chuyển động bất thường bằng `IsolationForest` hoặc mô hình chuỗi thời gian.
  - Dùng khi muốn thêm lớp bảo vệ: nếu thị trường quá dị thường, tự động kéo SL về breakeven hoặc không vào lệnh.

### 7. Reinforcement Learning cho quản lý vị thế
- Đây là mục tiêu dài hạn.
- Có thể xây môi trường Gym cho lệnh giữ lâu, học khi nào chuyển từ `hold` sang `take-profit`/`cut-loss`.

---

## Lộ trình đề xuất & Trạng thái hiện tại

1. **Bước 1 (Đã hoàn thành):** Chuẩn hóa dữ liệu lịch sử giao dịch thật. Dùng `logs/closed_positions.json` làm nguồn chính và xuất file `data/ml_training_data.csv`.
2. **Bước 2 (Đã hoàn thành):** Cải thiện RAG trong `btc_scraper/ai_analyst.py` để Gemini biết rõ Win Rate, Avg PnL và kịch bản tương đồng.
3. **Bước 3 (Đã hoàn thành):** Triển khai mô hình **RandomForest Classifier** (Meta Model) hiệu chuẩn Platt để dự đoán chính xác xác suất thắng (`meta_confidence`) và tích hợp vào hệ thống tính toán điểm số tín hiệu.
4. **Bước 4 (Đã hoàn thành):** Continuous Learning - Xây dựng pipeline tự động tải dữ liệu và retrain model định kỳ hàng tuần lúc 23:30 Chủ Nhật, kèm theo cảnh báo Concept Drift và gửi báo cáo qua Telegram.
5. **Bước 5 (Đã hoàn thành):** Tích hợp CCXT Auto-Trading trên Binance Testnet/Sandbox, quản lý vốn rủi ro cố định 2% mỗi lệnh, bảo vệ bằng Circuit Breaker ngắt 24h và tự động hóa đóng lệnh theo khuyến nghị TP/SL của bot.
6. **Bước 6 (Tương lai):** Chạy `optuna` để tối ưu tham số tự động và nghiên cứu anomaly detection / RL.
