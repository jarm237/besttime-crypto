# Lộ Trình Phát Triển: besttime-crypto Tiến Lên AI Quant Research Platform

Bản kế hoạch này chi tiết hóa lộ trình 5 giai đoạn nhằm chuyển đổi hệ thống **besttime-crypto** từ một bot giao dịch bán tự động thành một **Nền tảng Nghiên cứu Định lượng Trí tuệ Nhân tạo (AI Quant Research Platform)** toàn diện, giải quyết các thiếu sót về bộ não trung tâm, quản lý danh mục đa tài sản, mô hình giá trị kỳ vọng (Expected Value), và RL Position Management.

---

## 1. Mục Tiêu Chiến Lược & Kiến Trúc Tổng Thể

Kiến trúc phân tầng hiện tại rất xuất sắc, đảm bảo tính mô-đun hóa cao. Bước tiếp theo là đưa vào một **Bộ Não Trung Tâm (Meta Decision Engine)** và một **Bộ Máy Danh Mục (Portfolio Intelligence Engine)** nằm ở giữa lớp chấm điểm tín hiệu và thực thi giao dịch.

```
       [ Data Layer: Candles, Volatility, Sentiment, Order Book, Macro ]
                                     │
                                     ▼
        [ Technical Analysis Indicators ]   [ Market Regime Detection ]
                                     │                   │
                                     └───────────┬───────┘
                                                 │
                                                 ▼
             [ Signal Scoring (ML) & Expected Value Predictions ]
                                                 │
                                                 ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │                 META DECISION ENGINE (Central Brain)            │
        │  ─────────────────────────────────────────────────────────────  │
        │  • Bayesian Confidence Network (Posterior Probabilities)        │
        │  • Voting Ensemble (ML Signals, Market Sentiment, Regime Filters)│
        └────────────────────────────────┬────────────────────────────────┘
                                         │
                                         ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │            PORTFOLIO INTELLIGENCE ENGINE (Portfolio Level)      │
        │  ─────────────────────────────────────────────────────────────  │
        │  • Correlation Matrix Filter                                    │
        │  • Exposure Manager & Risk Allocation (VaR / CVaR Limits)       │
        │  • Kelly Fraction & MVO Optimizer (Position Sizing)             │
        └────────────────────────────────┬────────────────────────────────┘
                                         │
                                         ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │             RL POSITION MANAGER (Reinforcement Learning)        │
        │  ─────────────────────────────────────────────────────────────  │
        │  • Actions: HOLD, INCREASE, REDUCE, MOVE_SL, HEDGE, DO_NOTHING  │
        │  • LSTM/Transformer Policy (Sequential Memory)                  │
        └────────────────────────────────┬────────────────────────────────┘
                                         │
                                         ▼
                            [ Execution & DB Persistence ]
```

---

## 2. Kế Hoạch Chi Tiết 5 Giai Đoạn

### GIAI ĐOẠN 1: Tăng Cường Độ Bền Vận Hành & Nền Tảng Ổn Định (Production Resilience)
* **Thời gian**: Tháng 1
* **Mục tiêu**: Đưa hệ thống lên mức độ tin cậy cấp doanh nghiệp (Production-Grade), giải quyết các rủi ro vận hành.

#### Các đầu việc kỹ thuật:
1. **Database Circuit Breaker**:
   * Triển khai module `core/circuit_breaker.py` để giám sát kết nối MongoDB Atlas & Redis.
   * Khi mất kết nối, tự động định tuyến các thao tác ghi dữ liệu/trạng thái vị thế vào SQLite local (`data/offline_buffer.db`).
   * Viết worker ngầm chạy `sync_offline_data()` tự động đẩy dữ liệu từ SQLite lên MongoDB khi kết nối khôi phục.
2. **Graceful Shutdown & Process Supervision**:
   * Sửa đổi [main.py](file:///d:/Workspaces/Vọc vạch/main.py) để quản lý tín hiệu hệ thống (`SIGINT`, `SIGTERM`).
   * Gửi sentinel `None` vào queue của `ai_worker` và đóng các luồng WebSocket Binance một cách chủ động.
   * Quản lý tiến trình con (như `continuous_learning.py`) thông qua việc lưu file PID và chấm dứt tiến trình khi dừng ứng dụng.
3. **Atomic File Writes**:
   * Viết helper `atomic_write(file_path, data)` sử dụng cơ chế ghi tạm `.tmp` sau đó `os.replace` để tránh hỏng file khi mất nguồn.
4. **Health Check Endpoint & Monitoring Metrics**:
   * Tích hợp một luồng HTTP daemon siêu nhẹ (FastAPI/Flask) hoặc Prometheus Client trong `main.py` để xuất các chỉ số:
     * `ws_latency_ms`: Độ trễ WebSocket của Binance.
     * `db_connection_status`: Trạng thái kết nối DB (0 hoặc 1).
     * `queue_size`: Kích thước hàng đợi của AI Analyst.
5. **Mở rộng Test Coverage cho ML/RL**:
   * Tạo [test_rl_env.py](file:///d:/Workspaces/Vọc vạch/tests/test_rl_env.py) để chạy thử nghiệm huấn luyện mô hình PPO với 100 timesteps trên dữ liệu giả lập.
   * Bổ sung unit test cho `meta_model` và `adaptive_scoring`.

---

### GIAI ĐOẠN 2: Bộ Quản Trị Danh Mục Thông Minh (Portfolio Intelligence & Risk Allocation)
* **Thời gian**: Tháng 2 - Tháng 3
* **Mục tiêu**: Loại bỏ việc mở vị thế mù quáng cho các tài sản có tương quan cao, tối ưu hóa phân bổ vốn ở cấp danh mục.

#### Các đầu việc kỹ thuật:
1. **Correlation Engine**:
   * Xây dựng module `analysis/correlation.py` để tính toán ma trận tương quan lăn (rolling correlation matrix) 30 ngày của giá Altcoin dựa trên dữ liệu nến 1h.
   * Thiết lập bộ lọc: Nếu một tín hiệu BUY xuất hiện trên đồng Altcoin B, nhưng danh mục đang giữ đồng Altcoin A có độ tương quan $R_{A,B} > 0.75$, hệ thống sẽ:
     * Hoặc gộp chung giới hạn rủi ro.
     * Hoặc từ chối mở lệnh mới trên B nếu tổng rủi ro của nhóm vượt ngưỡng.
2. **Exposure Manager**:
   * Tính toán rủi ro danh mục theo Sector (ví dụ: L1, L2, DeFi, Meme, AI) để tránh tập trung vốn vào một nhóm coin khi có sự kiện thị trường.
   * Giới hạn tỷ lệ USDT/Stablecoin trong tài khoản để luôn duy trì đệm thanh khoản.
3. **Dynamic Position Sizing bằng Kelly Fraction & VaR (Value at Risk)**:
   * Chuyển đổi định lượng vốn từ mức cố định (ví dụ $100) sang tính toán động:
     $$\text{Size} = \text{Total Capital} \times f^* \times \text{Risk Multiplier}$$
     Trong đó Kelly Fraction $f^* = p - \frac{q}{b}$ ($p$: tỷ lệ thắng, $b$: tỷ lệ win/loss).
   * Triển khai mô hình tính toán **VaR (Value at Risk - Độ lệch rủi ro tối đa)** và **CVaR (Conditional VaR - Kỳ vọng tổn thất vượt mức VaR)** cho toàn bộ danh mục để tự động cắt giảm quy mô các lệnh khi biên độ biến động chung tăng đột biến.

---

### GIAI ĐOẠN 3: Bộ Não Quyết Định & Mô Hình Giá Tri Kỳ Vọng (Decision & Expected Value Intelligence)
* **Thời gian**: Tháng 4 - Tháng 5
* **Mục tiêu**: Chuyển đổi mô hình phân loại nhị phân (Meta Model) thành mô hình giá trị kỳ vọng (Expected Value) và tích hợp bộ não trung tâm.

#### Các đầu việc kỹ thuật:
1. **Expected Value (EV) Model**:
   * Nâng cấp mô hình [meta_model.py](file:///d:/Workspaces/Vọc vạch/btc_scraper/ml_engine/meta_model.py) để chuyển từ dự báo xác suất thắng/thua đơn thuần sang dự đoán đa biến số:
     * $\text{Expected Return}$ (Lợi nhuận kỳ vọng - tỷ lệ phần trăm).
     * $\text{Expected Drawdown}$ (Mức sụt giảm tài sản kỳ vọng tối đa).
     * $\text{Expected Hold Time}$ (Số lượng nến dự kiến giữ vị thế).
     * Xác suất đạt $\text{TP1}$, $\text{TP2}$, và $\text{SL}$.
   * Kết hợp các dự đoán này để tính toán giá trị kỳ vọng:
     $$E(PnL) = (P_{TP1} \times TP1_{pct}) + (P_{TP2} \times TP2_{pct}) - (P_{SL} \times SL_{pct})$$
2. **Central Meta Decision Engine**:
   * Xây dựng lớp quyết định trung tâm `MetaDecisionEngine` tại `btc_scraper/ml_engine/decision_engine.py`.
   * **Bayesian Network Integration**: Kết hợp các nguồn thông tin không đồng nhất (Tín hiệu chỉ báo, ML score, Sentiment, Market Regime, Volatility, Macro) làm các biến đầu vào để tính toán xác suất hậu nghiệm (Posterior Probability) cho hướng đi của giá.
   * Cấu hình logic biểu quyết (Voting Ensemble): Cho phép các mô hình thành phần biểu quyết. Quyết định đầu ra sẽ linh hoạt hơn:
     * `BUY` / `SELL`: Mở vị thế đầy đủ.
     * `INCREASE` / `REDUCE`: Gia tăng/giảm tỷ trọng lệnh hiện có.
     * `HOLD`: Tiếp tục giữ nguyên trạng thái.
     * `IGNORE`: Bỏ qua tín hiệu (tắt nhiễu).

---

### GIAI ĐOẠN 4: Quản Trị Vị Thế Bằng Học Tăng Cường (RL Position Manager)
* **Thời gian**: Tháng 6 - Tháng 7 - Tháng 8
* **Mục tiêu**: Thay thế RL Exit Manager đơn thuần bằng một Agent quản trị vị thế động toàn diện, tích hợp bộ nhớ chuỗi.

#### Các đầu việc kỹ thuật:
1. **Tái thiết kế Environment (`TradeManagementEnv`)**:
   * Cập nhật không gian trạng thái (State Space) bao gồm cả trạng thái ma trận tương quan danh mục, mức tiếp xúc rủi ro hiện tại và dự đoán EV.
   * **Mở rộng Action Space**:
     * `0: HOLD` (Giữ nguyên).
     * `1: INCREASE` (Mua/Bán thêm - DCA thông minh).
     * `2: REDUCE` (Bán bớt - chốt 25%/50% vị thế).
     * `3: MOVE_SL` (Dịch stop loss).
     * `4: HEDGE` (Mở vị thế đối ứng để bảo vệ tài khoản).
     * `5: DO_NOTHING`.
2. **LSTM / Transformer Policy**:
   * Thay thế MLP bằng mạng Recurrent Neural Network (LSTM/GRU) hoặc kiến trúc Transformer mini để lưu vết các bước chuyển trạng thái giá của các nến trước đó.
   * Giúp Agent nhận diện được mẫu hình chuyển động (Price Action) thay vì các chỉ số tĩnh.
3. **Tái định hình Reward Shaping**:
   * Xóa bỏ hoàn toàn các phần thưởng heuristic khuyến khích Agent dịch SL hoặc an toàn giả tạo.
   * Thiết lập hàm thưởng tập trung thẳng vào **Net PnL** (đã trừ phí giao dịch & trượt giá) kết hợp với phạt biến động (Sharpe/Sortino ratio của episode).

---

### GIAI ĐOẠN 5: Trí Tuệ Thích Ứng & Mô Phỏng Thị Trường (World Model & Simulation)
* **Thời gian**: Tháng 9 trở đi
* **Mục tiêu**: Xây dựng một thế giới giả lập thị trường để mô hình tự học thông qua Self-play và Causal AI.

#### Các đầu việc kỹ thuật:
1. **Synthetic Market Generation (Tạo lập thị trường nhân tạo)**:
   * Sử dụng mạng sinh như GANs hoặc TimeGAN để tạo ra hàng triệu kịch bản biến động giá Altcoin giả lập (bao gồm cả các đợt flash crash, bull run giả, sideway kéo dài) để huấn luyện RL Agent mà không sợ bị Overfitting dữ liệu lịch sử.
2. **Causal World Model (Mô hình Nhân quả)**:
   * Huấn luyện mô hình hiểu được tác động nhân quả giữa các biến số vĩ mô/on-chain (ví dụ: `Fed Interest Rate` -> `DXY` -> `BTC Price` -> `Altcoin Season`).
   * Sử dụng cấu trúc đồ thị nhân quả (Causal Graph) để giúp Central Brain suy luận tốt hơn trong các bối cảnh thị trường chưa từng xảy ra.

---

## 3. Các File Đề Xuất Thay Đổi & Tạo Mới (Giai đoạn 1)

Dưới đây là các tệp tin trong hệ thống sẽ được sửa đổi hoặc tạo mới ngay trong **Giai đoạn 1 (Production Resilience)**:

### `[MODIFY]` [main.py](file:///d:/Workspaces/Vọc vạch/main.py)
* **Nội dung thay đổi**: Tích hợp cờ tín hiệu Graceful Shutdown, kết nối Prometheus metrics exporter, và cấu hình bắt lỗi mất kết nối DB toàn cục để gọi Circuit Breaker.

### `[NEW]` [core/circuit_breaker.py](file:///d:/Workspaces/Vọc vạch/btc_scraper/core/circuit_breaker.py)
* **Nội dung tạo mới**: Lớp điều phối Circuit Breaker. Theo dõi MongoDB Atlas. Nếu phát hiện lỗi mạng kéo dài, chuyển hướng ghi dữ liệu vào SQLite local.

### `[MODIFY]` [position_tracker.py](file:///d:/Workspaces/Vọc vạch/btc_scraper/trading/position_tracker.py)
* **Nội dung thay đổi**: Sửa đổi cơ chế ghi log/cập nhật vị thế. Tích hợp ghi file atomic cho các log predictions local.

### `[NEW]` [tests/test_rl_env.py](file:///d:/Workspaces/Vọc vạch/tests/test_rl_env.py)
* **Nội dung tạo mới**: File kiểm thử liên tục (Smoke Test) cho RL Environment và Meta Model. Chạy tự động trong CI pipeline để phát hiện regression.

---

## 4. Kế Hoạch Xác Minh (Verification Plan)

### Kiểm thử Tự động (Automated Testing)
1. **Smoke Test cho RL**:
   ```bash
   pytest tests/test_rl_env.py -v
   ```
2. **Kiểm thử Circuit Breaker**:
   * Viết mock test ngắt kết nối mạng với MongoDB Atlas và xác minh dữ liệu vị thế được lưu chính xác vào SQLite local. Khôi phục kết nối và kiểm tra đồng bộ dữ liệu.

### Xác minh Thủ công (Manual Verification)
1. **Mô phỏng Graceful Shutdown**:
   * Chạy `python main.py` và gửi tín hiệu `Ctrl+C` (SIGINT). Xác minh trên log xem AI Analyst thread và WebSocket stream có thoát tuần tự mà không có Exception ngắt quãng nào.
2. **Kiểm tra Health Check API**:
   * Truy cập `http://localhost:8000/health` và xác nhận định dạng JSON xuất ra đúng các trường thông tin hiệu năng hệ thống.

---

## 5. Câu Hỏi Cần Alignment

> [!IMPORTANT]
> Vui lòng phản hồi các điểm dưới đây để tối ưu hóa bản kế hoạch:
> 1. **Khung thời gian huấn luyện**: Bạn có yêu cầu giới hạn về hạ tầng tính toán (ví dụ: chỉ chạy trên CPU thông thường hay có hỗ trợ GPU) cho phần huấn luyện RL Position Manager ở Giai đoạn 4 không? Việc này sẽ ảnh hưởng đến quyết định chọn LSTM hay các cấu trúc Transformer phức tạp hơn.
> 2. **Cơ sở dữ liệu Local Buffer**: Cho Giai đoạn 1, SQLite là lựa chọn mặc định của tôi vì nó không cần cài đặt thêm service nào trên máy chủ. Bạn có muốn sử dụng Redis local hoặc một giải pháp lưu trữ khác để làm Local Buffer không?
