# Kế Hoạch Triển Khai: Hiện Thực Mô Hình TimeGAN Sinh Dữ Liệu Altcoin

Bản kế hoạch này chia nhỏ quy trình thiết lập, huấn luyện và tích hợp mô hình **TimeGAN** vào hệ thống giao dịch **besttime-crypto** thành 5 giai đoạn kỹ thuật rõ ràng.

---

## GIAI ĐOẠN 1: Đường Ống Chuẩn Bị & Tiền Xử Lý Dữ Liệu (Preprocessing Pipeline)
* **Mục tiêu**: Chuẩn bị dữ liệu lịch sử nến 15m dưới dạng Tensor chuỗi thời gian chất lượng cao để nạp vào PyTorch.
* **Các bước thực hiện**:
  1. **Trích xuất chuỗi (Sequence Chunking)**:
     * Quét các file nến 15m từ `data/historical_18m/`.
     * Tách dữ liệu thành các chuỗi thời gian có độ dài cố định $T$ (mặc định: `seq_len = 24`, tương đương 6 tiếng giao dịch).
     * Định dạng dữ liệu đầu ra: Tensor kích thước `(N, seq_len, 5)` đại diện cho `[open, high, low, close, volume]`.
  2. **Chuẩn hóa giá động (MinMax Scaling)**:
     * Viết bộ chuẩn hóa `OHLCV_Scaler` để co giãn dữ liệu về đoạn `[0, 1]`.
     * Đảm bảo tính nhất quán: Tỷ lệ tương quan giữa `High` (phải là max) và `Low` (phải là min) không bị bóp méo sau chuẩn hóa.
  3. **PyTorch DataLoader**:
     * Xây dựng lớp `AltcoinSequenceDataset(Dataset)` và khởi tạo `DataLoader` hỗ trợ chia batch, xáo trộn dữ liệu (shuffle).

---

## GIAI ĐOẠN 2: Lập Trình Kiến Trúc Mạng TimeGAN (Core Architecture)
* **Mục tiêu**: Xây dựng 4 mạng thần kinh chính sử dụng cấu trúc mạng hồi quy GRU.
* **Các cấu phần mã nguồn**:
  1. Tạo tệp tin `btc_scraper/ml_engine/timegan.py` định nghĩa các lớp:
     * **`Embedder`**: Ánh xạ dữ liệu 5 chiều $X_{1:T}$ sang không gian ẩn $D_{\text{latent}}$ chiều.
     * **`Recovery`**: Giải mã vector ẩn về không gian giá gốc 5 chiều.
     * **`Generator`**: Ánh xạ nhiễu ngẫu nhiên $Z_{1:T}$ sang không gian ẩn.
     * **`Supervisor`**: Học quy luật chuyển trạng thái ẩn một bước ($H_{t} \to H_{t+1}$).
     * **`Discriminator`**: Phân loại chuỗi ẩn thực/giả trên từng bước thời gian.
  2. **Unit Test thành phần**:
     * Viết các test smoke xác nhận kích thước tensor đầu ra của từng mạng khớp nối hoàn hảo.

---

## GIAI ĐOẠN 3: Thiết Lập Vòng Lặp Huấn Luyện Đa Giai Đoạn (Multi-Stage Training Loop)
* **Mục tiêu**: Triển khai quy trình huấn luyện 3 bước tuần tự giúp TimeGAN hội tụ ổn định, tránh sụp đổ chế độ (mode collapse).
* **Quy trình huấn luyện**:
  1. **Giai đoạn 3.1 (Autoencoder Pre-training)**:
     * Chỉ tối ưu `Embedder` và `Recovery` dựa trên Reconstruction Loss (MSE) trong 100-200 epochs.
  2. **Giai đoạn 3.2 (Supervised Pre-training)**:
     * Đóng băng các mạng khác, chỉ tối ưu `Supervisor` dựa trên Supervised Loss (MSE dự báo bước tiếp theo trên không gian ẩn) trong 100 epochs.
  3. **Giai đoạn 3.3 (Joint Adversarial Training)**:
     * Huấn luyện đồng thời cả 4 mạng với tổng hàm Loss phối hợp (Adversarial Loss + Supervised Loss + Reconstruction Loss) trong 200 epochs.
  4. **Lưu trữ checkpoint**:
     * Tự động lưu checkpoint tốt nhất của mô hình Generator tại `logs/timegan_models/generator.pt`.

---

## GIAI ĐOẠN 4: Sinh Dữ Liệu Nhân Tạo & Tái Cấu Trúc Chỉ Báo (Indicator Reconstruction)
* **Mục tiêu**: Sinh chuỗi nến nhân tạo thô và tái lập các chỉ báo kỹ thuật một cách chính xác nhất.
* **Các bước thực hiện**:
  1. **Tạo dữ liệu thô**: Sử dụng `generator.pt` để sinh ra chuỗi nến giả lập $\mathbf{X}_{\text{fake}} = [O, H, L, C, V]$.
  2. **Giải chuẩn hóa (Inverse Transform)**: Đưa giá trị nến giả lập về khoảng giá trị thực tế của USD.
  3. **Ràng buộc logic nến**: Kiểm tra và điều chỉnh các lỗi nhỏ (ví dụ: đảm bảo $High \ge Open$, $High \ge Close$, $Low \le Open$, $Low \le Close$).
  4. **Tái lập chỉ báo kỹ thuật**:
     * Đưa dữ liệu nến thô giả lập vào hàm **`analyze_market()`** để tự động tính toán các cột RSI, MACD, ATR, BB_width, v.v.
     * Lưu trữ dataset hoàn chỉnh gồm 20 đặc trưng đã qua xử lý vào tệp `data/rl_synthetic_candles.pkl`.

---

## GIAI ĐOẠN 5: Tích Hợp RL Environment & Học Tăng Cường Thích Ứng (Curriculum Integration)
* **Mục tiêu**: Nạp dữ liệu giả lập vào môi trường học tăng cường để cải thiện năng lực của Agent.
* **Các bước thực hiện**:
  1. **Cập nhật `rl_trading_env.py`**:
     * Cho phép môi trường nhận dữ liệu giả lập từ `data/rl_synthetic_candles.pkl` làm tập huấn luyện bổ sung hoặc làm Curriculum phase ban đầu (easy/simulated phase).
  2. **Huấn luyện RL thích ứng**:
     * Huấn luyện RecurrentPPO / DQN trước trên 1,000,000 bước dữ liệu giả lập TimeGAN để Agent học cách quản trị rủi ro cơ bản.
     * Sau đó, chuyển sang huấn luyện tinh chỉnh (fine-tune) trên dữ liệu nến thực tế.
  3. **Đánh giá kiểm chứng**:
     * Chạy đánh giá PnL và Sharpe ratio của Agent được huấn luyện chéo so với Agent chỉ huấn luyện trên dữ liệu lịch sử hạn chế.
