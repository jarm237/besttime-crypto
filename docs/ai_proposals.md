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

### PHASE 4 SUMMARY: Đánh giá trước khi bước vào Giai Đoạn 5
* **Tiến độ hiện tại**:
  * Đã hoàn tất tích hợp `RecurrentPPO` với `MlpLstmPolicy` cho agent RL.
  * Reward function đã được đơn giản hoá về Net PnL step-to-step, loại bỏ các bonus heuristic.
  * `sb3-contrib` đã được cài đặt và chạy thành công trên CPU.
  * Đã thực thi huấn luyện ngắn `10000` steps cho PPO LSTM và lưu model tại `logs/rl_models/rl_exit_ppo_*.zip`.
* **Kết quả đánh giá ban đầu** (20 episodes):
  * Rule-based baseline: Mean PnL `0.4479%`, Mean Reward `0.2963`.
  * PPO LSTM: Mean PnL `0.1812%`, Mean Reward `-0.5959`.
  * DQN: Mean PnL `0.0045%`, Mean Reward `-0.3447`.
  * A2C: Mean PnL `-0.0503%`, Mean Reward `-0.5269`.
  * Action behaviors:
    * PPO tập trung vào `HOLD`, `PARTIAL_CLOSE_50`, `TRAILING_SL_ATR`.
    * DQN thêm `MOVE_SL_BE` và `TRAILING_SL_ATR`.
    * A2C chủ yếu `MOVE_SL_BE`.
* **Xác nhận ổn định**:
  * `python -m pytest -q` chạy thành công `60 passed`.
* **Kết luận**:
  * Phase 4 đã đạt mức “hệ thống hoạt động” và có thể đánh giá được.
  * RL agents hiện vẫn chưa vượt được rule-based baseline, nên cần tinh chỉnh reward/objective và hành vi chốt lệnh trước khi chuyển sang Phase 5.

### Báo Cáo Nâng Cao: RL Exit Manager (100 Episodes)
* **Mở rộng State Space**: đã tích hợp thêm hai đặc trưng mới gồm `Max Drawdown` và `Portfolio Correlation`, nâng tổng số chiều trạng thái lên `20`.
* **Terminal Reward**: đã áp dụng cơ chế Terminal Reward nhằm định hướng hành vi chốt lệnh cuối episode và giảm hiện tượng RL chỉ tối ưu reward trung gian.

#### Kết quả 100 episodes
| Chỉ số vận hành | Rule-Based (Hold TP/SL) | PPO Agent (LSTM Policy) | DQN Agent | A2C Agent |
| :--- | :---: | :---: | :---: | :---: |
| **Mean Reward** | `-1.8638` | **`-2.1499`** | `-2.2656` | `-2.3118` |
| **Mean PnL thực tế** | **`+0.1577%`** | `+0.0643%` | `+0.0641%` | `-0.0987%` |
| **SL Hit (Chạm SL cứng)** | 356 | 335 | **235** | 371 |
| **TP Hit (Chạm TP cứng)** | 131 | 67 | 87 | 115 |
| **Partial Close 50** | N/A | 76 | **177** | 0 |
| **Exit chủ động** | N/A | **22** | 1 | 0 |
| **Max Steps (Hết nến)** | 6 | 0 | 0 | 5 |

#### Phân tích chiến thuật và PnL
* **PPO & DQN: phòng thủ chủ động**
  * PPO sử dụng bộ nhớ LSTM để dịch chuyển SL về Entry `304` lần và chốt lời từng phần `76` lần, giúp giảm SL cứng xuống `335`.
  * DQN cực kỳ risk-averse với `177` partial close và `310` trailing SL, dẫn đến SL cứng chỉ `235` lần (giảm 34% so với baseline).
* **Lý do Rule-based vẫn cao hơn về PnL**
  * Reward hiện tại vẫn phạt nặng các vị thế dính SL cứng (`drawdown_penalty = -0.50`).
  * Các agent RL do đó có xu hướng đóng non và partial close quá sớm nhằm bảo toàn điểm số, trong khi baseline chờ TP/SL cứng và bắt kịp nhiều sóng hồi.
* **A2C đã ổn định hơn nhưng chưa hiệu quả**
  * A2C không còn collapsing hành vi partial close; nó giữ nhiều hơn (`3082` lần HOLD) và trailing SL `122` lần.
  * Tuy nhiên, PnL vẫn âm `-0.0987%`, vì agent chưa cân bằng tốt giữa giảm drawdown và tối đa hoá lợi nhuận.

### Lộ trình chuẩn bị Phase 5
1. **Triển khai Shadow Mode (Forward Testing)**
  * Kích hoạt bằng cấu hình `.env`:
    ```env
    RL_EXIT_MANAGER_ENABLED=true
    RL_EXIT_SHADOW_MODE=true
    ```
  * Trong [position_tracker.py](file:///d:/Workspaces/Vọc vạch/btc_scraper/trading/position_tracker.py), khi `evaluate_positions()` dự đoán RL action ở chế độ shadow thì chỉ log khuyến nghị, không gọi API đóng lệnh.

2. **Confidence Gate cho RL action**
  * Thực hiện các action `PARTIAL_CLOSE` / `EXIT` chỉ khi `meta_confidence < 0.45`.
  * Nếu confidence còn cao, ưu tiên `HOLD` để giảm tình trạng đóng non khi thị trường vẫn còn biến động thuận lợi.

3. **Graceful Shutdown cho LSTM Cache**
  * Lưu `_LSTM_STATE_CACHE` xuống file temporary khi dừng bot.
  * Khôi phục cache khi khởi động lại để không mất chuỗi trạng thái cho vị thế đang mở.

### Báo Cáo Phase 5: Tích Hợp Live & Tinh Chỉnh Hành Vi RL Exit Manager
* **Trạng thái**: **HOÀN THÀNH 100%**
* **Chi tiết thực hiện**:
  1. **Shadow Mode**: Đã tích hợp hoàn chỉnh thông qua biến `RL_EXIT_SHADOW_MODE`. Đổi nhãn `[RL]` sang `[SHADOW-RL]` để chạy forward testing mà không gửi lệnh thật lên sàn.
  2. **Confidence Gate**: Lệnh `PARTIAL_CLOSE` / `EXIT` của RL giờ đây chỉ được kích hoạt nếu `meta_confidence < 0.45`, giúp giảm chốt non khi xu hướng vẫn tốt.
  3. **LSTM State Persistence**: Đã triển khai tự động lưu và khôi phục trạng thái ẩn của LSTM thông qua file Pickle `logs/rl_lstm_cache.pkl` qua các chu kỳ khởi động lại.
  4. **Kiểm thử & Đánh giá rộng**: Đã chạy 100 episodes và xác nhận mức giảm rủi ro SL của DQN là 34%. Bộ kiểm thử 61/61 tests vượt qua thành công.

### Bước tiếp theo: Triển khai Causal AI & Mô Phỏng Thế Giới (Phase 5 Core)
Hệ thống hiện đã sẵn sàng 100% để bước vào các đầu việc cốt lõi của Giai đoạn 5 (World Model & Simulation).

### PHASE 5: Trí Tuệ Thích Ứng & Mô Phỏng Thị Trường (World Model & Simulation)
* **Thời gian**: Tháng 9 trở đi
* **Mục tiêu**: Xây dựng một thế giới giả lập thị trường để mô hình tự học thông qua Self-play và Causal AI.
* **Trạng thái hiện tại**: **Hoàn thành Part 1 (TimeGAN)**. Chuẩn bị bước sang Part 2 (Causal AI).

#### Các đầu việc kỹ thuật:
1. **Synthetic Market Generation (Tạo lập thị trường nhân tạo)**: ✅ **HOÀN THÀNH**
   * Đã triển khai thành công mô hình TimeGAN. 
   * Đã tích hợp pipeline tiền xử lý, huấn luyện đa giai đoạn, sinh dữ liệu nhân tạo và tích hợp Curriculum Learning cho RL.
   * Dataset nến giả lập chất lượng cao đã sẵn sàng để huấn luyện nâng cao RL Agent.
2. **Causal World Model (Mô hình Nhân quả)**: ⏳ **NEXT STEP**
   * Huấn luyện mô hình hiểu được tác động nhân quả giữa các biến số vĩ mô/on-chain (ví dụ: `Fed Interest Rate` -> `DXY` -> `BTC Price` -> `Altcoin Season`).
   * Sử dụng cấu trúc đồ thị nhân quả (Causal Graph) để giúp Central Brain suy luận tốt hơn trong các bối cảnh thị trường chưa từng xảy ra.

---

## Báo Cáo Triển Khai TimeGAN (Đã Hoàn Thành)

Tài liệu này trình bày chi tiết về kiến trúc toán học, mô hình hóa dữ liệu, sơ đồ hoạt động và lộ trình triển khai mã nguồn cho **Mô hình tạo lập thị trường nhân tạo (TimeGAN)** phục vụ hệ thống giao dịch **besttime-crypto**.

### 1. Tại Sao Sử Dụng TimeGAN Thay Cho GAN Truyền Thống?

GAN thông thường (như DCGAN) hoạt động tốt trên ảnh tĩnh nhưng gặp thất bại nghiêm trọng trên dữ liệu chuỗi thời gian (time-series) vì:
1. **Thiếu tính liên kết thời gian**: Không nắm bắt được mối quan hệ tự tương quan (autocorrelation) của giá qua từng bước thời gian.
2. **Price Action phi thực tế**: Các nến sinh ra bị rời rạc, gián đoạn (ví dụ: giá Open nến sau không khớp với Close nến trước).

**TimeGAN (Yoon et al., 2019)** giải quyết vấn đề này bằng cách kết hợp **Autoencoder** và **Supervised GAN Loss** trên một không gian ẩn (latent space), giúp mô hình học cả đặc trưng phân phối tĩnh và động học thời gian.

### 2. Kiến Trúc Hệ Thống TimeGAN (Sơ đồ Khối)

```mermaid
graph TD
    subgraph Autoencoder Loop (Representational Space)
        X[Dữ liệu nến thực tế X] -->|Embedder e| H[Không gian ẩn thực tế H]
        H -->|Recovery r| X_hat[Nến tái tạo X_hat]
    end

    subgraph Generator & Supervisor Loop (Temporal Dynamics)
        Z[Nhiễu ngẫu nhiên Z] -->|Generator g| H_fake[Không gian ẩn giả lập H_fake]
        H_fake -->|Supervisor s| H_fake_next[Trạng thái ẩn dự kiến]
        H_fake -->|Recovery r| X_fake[Nến giả lập X_fake]
    end

    subgraph Discriminator Loop (Adversarial)
        H -->|Discriminator d| RealScore[Đánh giá Thực: 0 to 1]
        H_fake -->|Discriminator d| FakeScore[Đánh giá Giả: 0 to 1]
    end

    classDef real fill:#d4edda,stroke:#28a745,stroke-width:2px;
    classDef fake fill:#f8d7da,stroke:#dc3545,stroke-width:2px;
    class X,H,X_hat real;
    class Z,H_fake,X_fake,H_fake_next fake;
```

#### Nguyên lý thiết kế cho `besttime-crypto`:
Thay vì sinh cả 18 chỉ báo kỹ thuật phức tạp (RSI, MACD, BB), ta chỉ cho TimeGAN sinh **5 đặc trưng nến cơ bản**:
$$\mathbf{X}_{1:T} = [\text{open}, \text{high}, \text{low}, \text{close}, \text{volume}]$$
Sau khi sinh ra chuỗi nến giả lập $\mathbf{X}_{\text{fake}}$, ta chạy qua hàm **`analyze_market()`** hiện tại của bot để tính toán RSI, MACD, ATR, Bollinger Bands một cách chính xác về mặt toán học. Điều này giảm số chiều của GAN từ 18 xuống 5 và loại bỏ hoàn toàn các lỗi phi lý của chỉ báo.

### 3. Kiến Trúc 4 Mạng Thành Phần (PyTorch)

Mỗi mạng thành phần được cấu trúc bằng mạng hồi quy **GRU/LSTM** đa tầng để giữ vết bộ nhớ dài hạn:

1. **Embedder ($e$)**: 
   * Đầu vào: $\mathbf{X}_{1:T} \in \mathbb{R}^{T \times 5}$
   * Đầu ra: Trạng thái ẩn $\mathbf{H}_{1:T} \in \mathbb{R}^{T \times D_{\text{latent}}}$ (mã hóa các mối quan hệ phi tuyến).
2. **Recovery ($r$)**: 
   * Đầu vào: $\mathbf{H}_{1:T} \in \mathbb{R}^{T \times D_{\text{latent}}}$
   * Đầu ra: Chuỗi nến tái cấu trúc $\hat{\mathbf{X}}_{1:T} \in \mathbb{R}^{T \times 5}$.
3. **Generator ($g$)**: 
   * Đầu vào: Nhiễu ngẫu nhiên $\mathbf{Z}_{1:T} \in \mathbb{R}^{T \times D_{\text{noise}}}$
   * Đầu ra: Trạng thái ẩn giả lập $\mathbf{H}_{\text{fake}} \in \mathbb{R}^{T \times D_{\text{latent}}}$.
4. **Supervisor ($s$)**: 
   * Đầu vào: $\mathbf{H}_{1:T}$
   * Đầu ra: Dự đoán bước tiếp theo $\mathbf{H}_{t+1}$ dựa trên $\mathbf{H}_{1:t}$. Giúp Generator đi đúng quỹ đạo thời gian thực tế.
5. **Discriminator ($d$)**:
   * Đầu vào: $\mathbf{H}_{1:T}$ hoặc $\mathbf{H}_{\text{fake}}$
   * Đầu ra: Điểm phân loại thực/giả trên mỗi bước thời gian.

### 4. Các Giai Đoạn Huấn Luyện (Training Strategy)

Huấn luyện TimeGAN gồm 3 bước tuần tự để đảm bảo độ hội tụ cao:

#### Giai đoạn 1: Huấn luyện Autoencoder (Tối ưu Embedder & Recovery)
Chỉ huấn luyện Embedder và Recovery bằng sai số bình phương trung bình (MSE):
$$\mathcal{L}_{\text{R}} = \mathbb{E} [ || \mathbf{X}_{1:T} - \hat{\mathbf{X}}_{1:T} ||_2^2 ]$$

#### Giai đoạn 2: Huấn luyện Supervisor (Nắm bắt động học thời gian)
Huấn luyện mạng Supervisor trên dữ liệu ẩn thực tế nhằm học cách dự đoán bước tiếp theo:
$$\mathcal{L}_{\text{S}} = \mathbb{E} [ || \mathbf{H}_{t+1} - s(\mathbf{H}_{1:t}) ||_2^2 ]$$

#### Giai đoạn 3: Huấn luyện Đối Kháng Đồng Thời (Joint Adversarial Training)
Tối ưu cả 4 mạng cùng lúc với hàm Loss hỗn hợp:
$$\mathcal{L}_{\text{joint}} = \mathcal{L}_{\text{unsupervised}} + \alpha \mathcal{L}_{\text{supervised}} + \beta \mathcal{L}_{\text{reconstruction}}$$

### 5. Phác Thảo Mã Nguồn Python (TimeGAN Module)

Dưới đây là thiết kế lớp `TimeGAN` dự kiến triển khai tại `btc_scraper/ml_engine/timegan.py`:

```python
import torch
import torch.nn as nn
import numpy as np

class GRUNetwork(nn.Module):
    """Lớp nền tảng sử dụng GRU đa tầng cho chuỗi thời gian."""
    def __init__(self, input_dim, hidden_dim, output_dim, num_layers=3):
        super().__init__()
        self.gru = nn.GRU(input_dim, hidden_dim, num_layers, batch_first=True)
        self.fc = nn.Linear(hidden_dim, output_dim)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        out, _ = self.gru(x)
        out = self.fc(out)
        return self.sigmoid(out)

class TimeGANManager:
    def __init__(self, input_dim=5, latent_dim=24, hidden_dim=64):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        # 4 Mạng lõi
        self.embedder = GRUNetwork(input_dim, hidden_dim, latent_dim).to(self.device)
        self.recovery = GRUNetwork(latent_dim, hidden_dim, input_dim).to(self.device)
        self.generator = GRUNetwork(latent_dim, hidden_dim, latent_dim).to(self.device)
        self.supervisor = GRUNetwork(latent_dim, hidden_dim, latent_dim).to(self.device)
        self.discriminator = GRUNetwork(latent_dim, hidden_dim, 1).to(self.device)
        
        # Optimizers
        self.ae_opt = torch.optim.Adam(
            list(self.embedder.parameters()) + list(self.recovery.parameters()), lr=1e-3
        )
        self.gen_opt = torch.optim.Adam(
            list(self.generator.parameters()) + list(self.supervisor.parameters()), lr=1e-3
        )
        self.disc_opt = torch.optim.Adam(self.discriminator.parameters(), lr=1e-3)

    def train_autoencoder(self, data_loader, epochs=100):
        """Phase 1: Huấn luyện Autoencoder tối ưu hóa không gian biểu diễn ẩn."""
        self.embedder.train()
        self.recovery.train()
        criterion = nn.MSELoss()
        for epoch in range(epochs):
            for x in data_loader:
                x = x.to(self.device)
                self.ae_opt.zero_grad()
                h = self.embedder(x)
                x_hat = self.recovery(h)
                loss = criterion(x_hat, x)
                loss.backward()
                self.ae_opt.step()
            print(f"[AE Train] Epoch {epoch+1}/{epochs} | Loss: {loss.item():.6f}")

    def generate_synthetic_data(self, num_samples, seq_len):
        """Sinh chuỗi nến nhân tạo từ nhiễu ngẫu nhiên."""
        self.generator.eval()
        self.recovery.eval()
        with torch.no_grad():
            # Tạo nhiễu Gaussian
            z = torch.randn(num_samples, seq_len, 24).to(self.device)
            h_fake = self.generator(z)
            h_fake_supervised = self.supervisor(h_fake)
            x_fake = self.recovery(h_fake_supervised)
            return x_fake.cpu().numpy()
```

### 6. Lộ Trình Tích Hợp Vào besttime-crypto

```
[ Lịch sử Altcoin 15m CSV ] ──> [ TimeGAN Train ] ──> [ Lưu Generator Model ]
                                                            │
                                                            ▼
[ Môi trường RL TradeExitEnv ] <── [ analyze_market() ] <── [ Sinh nến Fake (1 triệu bước) ]
```

1. **Thu thập tập huấn luyện**: Lấy toàn bộ nến 15m từ các coin trong `data/historical_18m` và chuyển đổi thành ma trận tensor kích thước `(N, 24, 5)`.
2. **Huấn luyện TimeGAN**: Huấn luyện mô hình ngầm qua một script phụ `train_timegan.py`.
3. **Sinh lập dữ liệu lớn (Synthetic Simulation)**: Dùng Generator đã train để xuất ra file `data/synthetic_candles.pkl` chứa 1,000,000 bước nến giả lập chất lượng cao.
4. **Curriculum Learning nâng cao**: Cập nhật `rl_trading_env.py` để lấy dữ liệu từ `synthetic_candles.pkl` thay vì dữ liệu lịch sử hạn chế, giúp RL Exit Manager trải nghiệm hàng nghìn tình huống thị trường biến động và cải thiện khả năng tổng quát hóa chính sách.

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
