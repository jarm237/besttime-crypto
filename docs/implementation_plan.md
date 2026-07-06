# Đánh Giá Tình Hình & Kế Hoạch Tiếp Theo (Causal World Model)

Bản kế hoạch triển khai trước đó (Mô hình TimeGAN Sinh Dữ Liệu Altcoin) đã được **hoàn thành 100%**. Hệ thống đã có khả năng sinh nến nhân tạo chất lượng cao (54/54 tests passed) và tích hợp sẵn sàng cho RL Curriculum Learning.

Dựa trên tiến độ hiện tại theo lộ trình `ai_proposals.md` (Phase 5), hệ thống hiện đã sẵn sàng bước sang cột mốc tiếp theo: **Causal World Model (Mô hình Nhân quả)** để giúp AI của besttime-crypto thực sự hiểu được nguyên nhân - kết quả của thị trường.

---

## Mục Tiêu: Causal World Model (Mô hình Nhân Quả)

- **Khái niệm**: Thay vì chỉ dùng ML để tìm "tương quan" (correlation) giữa các chỉ báo và giá, Causal AI sẽ xây dựng một biểu đồ (Causal Graph) để hiểu được yếu tố nào _gây ra_ sự thay đổi của yếu tố khác.
- **Ví dụ**: Hiểu được chuỗi tác động `Fed Interest Rate -> DXY (Chỉ số USD) -> BTC Price -> Altcoin Season`.

## User Review Required

> [!IMPORTANT]
> **Định Hướng Triển Khai Causal AI**
> Triển khai Causal AI đòi hỏi nhiều dữ liệu ngoại biên hơn. Bạn có muốn bắt đầu bằng:
>
> 1. **Dữ liệu On-chain & Macro cơ bản** (như DXY, S&P500, BTC Dominance) trước?
> 2. Hay quay lại hoàn thiện **Giai đoạn 1 (Production Resilience - Circuit Breaker)** để đảm bảo hệ thống vận hành cực kỳ ổn định trước khi tích hợp thêm các mô hình AI hạng nặng này?
>
> Vui lòng cho biết bạn muốn ưu tiên hướng nào cho Sprint tiếp theo!

## Open Questions

> [!WARNING]
> Causal AI thường dùng các thư viện như `DoWhy` (của Microsoft) hoặc `CausalML`. Tuy nhiên việc thiết lập DAG (Directed Acyclic Graph) ban đầu có thể cần sự tinh chỉnh của chuyên gia tài chính. Bạn có muốn hệ thống tự động dò tìm cấu trúc đồ thị (Causal Discovery) không?

## Proposed Changes (Dự kiến cho Causal World Model)

### Data Layer: Causal Data Fetcher

#### [NEW] [causal_data_fetcher.py](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/exchanges/causal_data_fetcher.py)

- Thu thập dữ liệu Macro (ví dụ từ Yahoo Finance cho DXY, SPX, VIX).
- Thu thập BTC Dominance và Total Market Cap.
- Căn chỉnh mốc thời gian (alignment) với nến 15m/1h của Altcoin.

---

### Core ML Engine: Causal Graph & Inference

#### [NEW] [causal_model.py](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/ml_engine/causal_model.py)

- Triển khai Causal Graph (DAG) kết nối Macro -> Crypto Market -> Altcoin.
- Sử dụng thư viện `DoWhy` hoặc thuật toán PC/FCI để đánh giá mức độ ảnh hưởng nhân quả (ATE - Average Treatment Effect) của một tín hiệu macro lên Altcoin.

#### [MODIFY] [decision_engine.py](file:///home/tran-huynh/Workspaces/Personal/besttime-crypto/btc_scraper/ml_engine/decision_engine.py)

- Tích hợp output của Causal Model làm trọng số (weight) hoặc bộ lọc (filter). Nếu tín hiệu mua xuất hiện, nhưng Causal Model xác định "VIX đang tăng mạnh -> DXY tăng -> Crypto giảm", hệ thống sẽ cản lệnh mua này (Reject).

## Verification Plan

### Automated Tests

- `pytest tests/test_causal_data.py`: Kiểm tra pipeline kéo dữ liệu Macro.
- `pytest tests/test_causal_graph.py`: Đảm bảo DAG hợp lệ và hội tụ khi huấn luyện với dữ liệu mẫu.

### Manual Verification

- Chạy `python -m btc_scraper.ml_engine.causal_model` để trực quan hoá đồ thị (plot graph) nhân quả được tìm thấy và kiểm chứng bằng logic thị trường thông thường.
