# Meta Model Recommendations Plan

Mục tiêu: Sắp xếp và phân chia các khuyến nghị theo thứ tự ưu tiên, mỗi mục kèm các bước triển khai cụ thể.

## 1) Tăng kích thước và cải thiện calibration (Ưu tiên: Cao)
- Lý do: calibration kém ở vùng cao-confidence (0.8-1.0) làm sai lệch quyết định khi dựa trên probabilistic thresholds.
- Các bước:
  1. Thu thập thêm dữ liệu calibration gần đây (tăng set calib): tạo script `scripts/collect_calib_data.py` để lấy recent 6-12 tháng.
  2. Tăng tỷ lệ split train/calib/test: dùng 60/20/20 hoặc 70/20/10 tuỳ tập dữ liệu.
  3. Áp dụng isotonic và sigmoid, so sánh bằng mean calibration error trên holdout.
  4. Nếu bucket 0.8-1.0 vẫn thiếu mẫu, giảm kích thước bucket hoặc gộp thành 0.75-1.0 để tăng mẫu.
  5. Triển khai periodic recalibration (cron job hàng tuần) và tracking drift.

## 2) Thiết lập giám sát hiệu năng live và báo cáo (Ưu tiên: Cao)
- Lý do: theo dõi hiệu năng thực tế, phát hiện drift sớm.
- Các bước:
  1. Thêm logging prediction-level: lưu `timestamp`, `prob`, `features_hash`, `coin`, `action` vào `logs/predictions.log`.
  2. Viết job hàng ngày để tính rolling metrics (7/30/90d) và gửi báo cáo JSON/Slack.
  3. So sánh predicted_winrate vs actual_winrate trên sliding windows — cảnh báo nếu calibration_error > threshold.
  4. Dashboard nhẹ với FastAPI endpoint `/api/meta-model/metrics` (hoặc mở rộng `api/server.py`).

### Progress (Giai đoạn 2) — Hoàn tất (2026-06-19)

- Thực hiện logging prediction-level: `predict_meta_confidence()` giờ ghi các dòng JSON newline-delimited vào `logs/predictions.log`. Mỗi bản ghi gồm các trường: `timestamp`, `probability`, `features_hash`, `coin`, `action`, `model_version`.
  - File thay đổi: `btc_scraper/ml_engine/meta_model.py` — thêm tính năng ghi log trong `predict_meta_confidence()`.

- Thêm API nhẹ để truy vấn metrics và mẫu dự đoán gần đây: endpoint `/api/meta-model/metrics` trả về nội dung `meta_model.json`, thống kê tóm tắt và sample dự đoán (mặc định trả tối đa 100 bản ghi gần nhất).
  - File thay đổi: `api/server.py` — thêm `get_meta_model_metrics()`.

- Ghi chú: các bước job hàng ngày (rolling 7/30/90d) và alert (Slack/webhook) chưa được triển khai — đề xuất bước tiếp theo là tạo script `scripts/meta_model_monitor.py` chạy theo cron và đăng cảnh báo khi drift xảy ra.

Các thay đổi trên nhằm đáp ứng yêu cầu giám sát live và cung cấp dữ liệu để xây dựng báo cáo rolling metrics/alerts.

## 3) Cải thiện cân bằng lớp / cost-sensitive training (Ưu tiên: Trung bình cao)
- Lý do: cải thiện recall cho lớp WIN mà không phá vỡ precision.
- Các bước:
  1. Thử `class_weight='balanced'` (đã dùng) vs oversampling (SMOTE) vs focal loss (nếu dùng NN).
  2. Thực hiện grid-search cho `class_weight` và thresholds prediction (chọn threshold theo F1 hoặc expected PnL).
  3. Cố định evaluation metric cho chọn model (PR-AUC + Brier score).

## 4) Chạy thử nghiệm huấn luyện (A/B) với tham số/kiến trúc khác (Ưu tiên: Trung bình)
- Lý do: tìm cải thiện AUC/PR.
- Các bước:
  1. Thiết lập thử nghiệm offline (Experiment runner) sử dụng `optuna` hoặc `sklearn.model_selection` để đánh giá nhiều cấu hình.
  2. Giới hạn trials ban đầu (40-100), lưu mỗi trial như artifact (metrics + params).
  3. So sánh bằng holdout OOS recent; chọn top-K để backtest trong hệ thống giả lập.

## 5) Thêm ước lượng bất định (uncertainty) và Brier decomposition (Ưu tiên: Trung bình)
- Lý do: hiểu chất lượng độ tin cậy của xác suất dự báo.
- Các bước:
  1. Tính Brier score và decompose into reliability, resolution, uncertainty.
  2. Thêm Bayesian approximation (MC Dropout) hoặc ensemble bootstrap để ước lượng epistemic uncertainty.
  3. Expose `uncertainty` cùng `prob` trong logs để ra quyết định risk-aware.

## 6) Mở rộng backtesting OOS và stress tests (gần đây) (Ưu tiên: Trung bình)
- Lý do: đảm bảo model không overfit đến chuỗi thời gian cũ.
- Các bước:
  1. Tạo backtest presets cho các thị trường: bull, bear, high-vol, low-vol.
  2. Chạy backtest với các phiên bản model (current vs new) trên recent 3/6/12 tháng.
  3. Báo cáo PnL, max drawdown, hit-rate, avg trade return.

## 7) Tối ưu hiệu năng inference & packaging (latency/memory) (Ưu tiên: Thấp trung bình)
- Lý do: giảm latency cho môi trường real-time.
- Các bước:
  1. Kiểm tra memory & CPU profile khi load `meta_model.joblib` (psutil, memory_profiler).
  2. Nếu cần, chuyển sang ONNX / treelite cho tree models, hoặc nhóm model thành lighweight artefact.
  3. Tạo Docker image tối giản chứa model + FastAPI phục vụ prediction.

---
File này chứa các bước thực thi rõ ràng; tôi có thể bắt đầu thực hiện từng mục theo thứ tự ưu tiên.