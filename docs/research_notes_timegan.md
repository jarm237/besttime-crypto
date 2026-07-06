# Nghiên Cứu Kiến Trúc: Triển Khai TimeGAN Sinh Dữ Liệu Thị Trường Nhân Tạo

Tài liệu này trình bày chi tiết về kiến trúc toán học, mô hình hóa dữ liệu, sơ đồ hoạt động và lộ trình triển khai mã nguồn cho **Mô hình tạo lập thị trường nhân tạo (TimeGAN)** phục vụ hệ thống giao dịch **besttime-crypto**.

---

## 1. Tại Sao Sử Dụng TimeGAN Thay Cho GAN Truyền Thống?

GAN thông thường (như DCGAN) hoạt động tốt trên ảnh tĩnh nhưng gặp thất bại nghiêm trọng trên dữ liệu chuỗi thời gian (time-series) vì:
1. **Thiếu tính liên kết thời gian**: Không nắm bắt được mối quan hệ tự tương quan (autocorrelation) của giá qua từng bước thời gian.
2. **Price Action phi thực tế**: Các nến sinh ra bị rời rạc, gián đoạn (ví dụ: giá Open nến sau không khớp với Close nến trước).

**TimeGAN (Yoon et al., 2019)** giải quyết vấn đề này bằng cách kết hợp **Autoencoder** và **Supervised GAN Loss** trên một không gian ẩn (latent space), giúp mô hình học cả đặc trưng phân phối tĩnh và động học thời gian.

---

## 2. Kiến Trúc Hệ Thống TimeGAN (Sơ đồ Khối)

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

### Nguyên lý thiết kế cho `besttime-crypto`:
Thay vì sinh cả 18 chỉ báo kỹ thuật phức tạp (RSI, MACD, BB), ta chỉ cho TimeGAN sinh **5 đặc trưng nến cơ bản**:
$$\mathbf{X}_{1:T} = [\text{open}, \text{high}, \text{low}, \text{close}, \text{volume}]$$
Sau khi sinh ra chuỗi nến giả lập $\mathbf{X}_{\text{fake}}$, ta chạy qua hàm **`analyze_market()`** hiện tại của bot để tính toán RSI, MACD, ATR, Bollinger Bands một cách chính xác về mặt toán học. Điều này giảm số chiều của GAN từ 18 xuống 5 và loại bỏ hoàn toàn các lỗi phi lý của chỉ báo.

---

## 3. Kiến Trúc 4 Mạng Thành Phần (PyTorch)

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

---

## 4. Các Giai Đoạn Huấn Luyện (Training Strategy)

Huấn luyện TimeGAN gồm 3 bước tuần tự để đảm bảo độ hội tụ cao:

### Giai đoạn 1: Huấn luyện Autoencoder (Tối ưu Embedder & Recovery)
Chỉ huấn luyện Embedder và Recovery bằng sai số bình phương trung bình (MSE):
$$\mathcal{L}_{\text{R}} = \mathbb{E} [ || \mathbf{X}_{1:T} - \hat{\mathbf{X}}_{1:T} ||_2^2 ]$$

### Giai đoạn 2: Huấn luyện Supervisor (Nắm bắt động học thời gian)
Huấn luyện mạng Supervisor trên dữ liệu ẩn thực tế nhằm học cách dự đoán bước tiếp theo:
$$\mathcal{L}_{\text{S}} = \mathbb{E} [ || \mathbf{H}_{t+1} - s(\mathbf{H}_{1:t}) ||_2^2 ]$$

### Giai đoạn 3: Huấn luyện Đối Kháng Đồng Thời (Joint Adversarial Training)
Tối ưu cả 4 mạng cùng lúc với hàm Loss hỗn hợp:
$$\mathcal{L}_{\text{joint}} = \mathcal{L}_{\text{unsupervised}} + \alpha \mathcal{L}_{\text{supervised}} + \beta \mathcal{L}_{\text{reconstruction}}$$

---

## 5. Phác Thảo Mã Nguồn Python (TimeGAN Module)

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

---

## 6. Lộ Trình Tích Hợp Vào besttime-crypto

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
