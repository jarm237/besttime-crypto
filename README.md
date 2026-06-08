# besttime-crypto

Hệ thống Bot tự động cào dữ liệu tiền điện tử, phân tích tín hiệu kỹ thuật (Trading) qua thuật toán và báo cáo qua Telegram, kết hợp AI Gemini để phân tích nhận định thị trường.

## Tính năng
- Quét dữ liệu tự động cho danh sách các coin (BTC, ETH, SOL...).
- Nhận định xu hướng dựa trên EMA, SMA, Bollinger Bands, RSI.
- Tìm kiếm cơ hội vào lệnh bằng mô hình Swing Failure Pattern (SFP).
- **Quản lý vị thế thủ công (Position Tracker)**: Nhập vị thế đã giao dịch, bot sẽ liên tục giám sát và đưa ra khuyến nghị Chốt Lời / Cắt Lỗ qua Telegram theo thời gian thực.
- Gửi báo cáo phân tích tự động qua tin nhắn Telegram.

---

## Quản lý Vị thế (Position Tracker)

Công cụ `manage_positions.py` giúp bạn lưu lại các vị thế giao dịch thủ công. Sau khi lưu, ở mỗi lần quét tiếp theo, Bot sẽ tự động kiểm tra xem giá đã chạm mức Cắt Lỗ (SL), Chốt Lời (TP), hoặc có tín hiệu đảo chiều nguy hiểm hay không, và gửi cảnh báo trực tiếp qua Telegram.

### Cú pháp sử dụng CLI

Mở terminal ở thư mục dự án và chạy các lệnh sau:

#### 1. Thêm vị thế mới (Add Position)
Khi bạn vừa khớp lệnh trên sàn, hãy khai báo vào hệ thống để Bot bắt đầu theo dõi:

```bash
./scripts/manage_positions.py add <COIN> <GIÁ_ENTRY> [HƯỚNG] -n "<Ghi chú>"
```
- `<COIN>`: Tên đồng coin (VD: `BTC`, `ETH`).
- `<GIÁ_ENTRY>`: Giá mua / vào lệnh (VD: `68000`).
- `[HƯỚNG]`: (Tuỳ chọn) `LONG` hoặc `SHORT`. **Mặc định là `LONG` (Dành cho giao dịch Spot).**
- `-n`: (Tuỳ chọn) Ghi chú lý do vào lệnh.

**Ví dụ (Giao dịch Spot):**
Chỉ cần nhập Coin và Giá Mua (tự động hiểu là LONG):
```bash
./scripts/manage_positions.py add BTC 68000 -n "Mua Spot tích luỹ"
```

**Ví dụ (Đánh Futures SHORT):**
```bash
./scripts/manage_positions.py add ETH 3500 SHORT -n "Tín hiệu SFP bắt đỉnh"
```

*Lưu ý: Nếu có biến động giá chạm SL hoặc TP, hoặc bot phát hiện tín hiệu đảo chiều, bot sẽ tự động nhắn tin cảnh báo trên Telegram (Cấp độ 🚨 Khẩn cấp hoặc ⚠️ Xem xét).*

#### 2. Xem danh sách các vị thế đang mở
Liệt kê toàn bộ các lệnh hiện đang được theo dõi:
```bash
./scripts/manage_positions.py list
```

#### 3. Đóng vị thế
Khi bạn đã chốt lời hoặc cắt lỗ trên sàn, hãy ghi nhận giá đóng lệnh vào hệ thống để tính tỷ suất sinh lời (PnL) và chỉ số hiệu suất:
```bash
./scripts/manage_positions.py close <COIN> <GIÁ_BÁN>
```

**Ví dụ:**
```bash
./scripts/manage_positions.py close BTC 70000
```
*(Lệnh sẽ trả về mức % lãi/lỗ và rủi ro/lợi nhuận R-multiplier).*

#### 4. Đánh giá hiệu suất chiến lược (Performance)
Xem tổng hợp kết quả của tất cả các lệnh đã đóng để đánh giá xem chiến lược giao dịch của bạn có đang hiệu quả không:
```bash
./scripts/manage_positions.py perf
```
Các thông số bao gồm: `Win Rate`, `Profit Factor`, `Max Consecutive Losses` và `Tổng P&L`.

---

## Cài đặt và Chạy Bot
1. Cài đặt các thư viện: `pip install -r requirements.txt` (nếu có)
2. Thiết lập cấu hình Telegram & API Keys trong thư mục `config.py` hoặc `.env`
3. Khởi chạy Bot: `python main.py`
