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
./pos add <COIN> <GIÁ_ENTRY> [HƯỚNG] -n "<Ghi chú>"
```
- `<COIN>`: Tên đồng coin (VD: `BTC`, `ETH`).
- `<GIÁ_ENTRY>`: Giá mua / vào lệnh (VD: `68000`).
- `[HƯỚNG]`: (Tuỳ chọn) `LONG` hoặc `SHORT`. **Mặc định là `LONG` (Dành cho giao dịch Spot).**
- `-n`: (Tuỳ chọn) Ghi chú lý do vào lệnh.

**Ví dụ (Giao dịch Spot):**
Chỉ cần nhập Coin và Giá Mua (tự động hiểu là LONG):
```bash
./pos add BTC 68000 -n "Mua Spot tích luỹ"
```

**Ví dụ (Đánh Futures SHORT):**
```bash
./pos add ETH 3500 SHORT -n "Tín hiệu SFP bắt đỉnh"
```

*Lưu ý: Nếu có biến động giá chạm SL hoặc TP, hoặc bot phát hiện tín hiệu đảo chiều, bot sẽ tự động nhắn tin cảnh báo trên Telegram (Cấp độ 🚨 Khẩn cấp hoặc ⚠️ Xem xét).*

#### 2. Xem danh sách các vị thế đang mở
Liệt kê toàn bộ các lệnh hiện đang được theo dõi:
```bash
./pos list
```

#### 3. Đóng vị thế
Khi bạn đã chốt lời hoặc cắt lỗ trên sàn, hãy ghi nhận giá đóng lệnh vào hệ thống để tính tỷ suất sinh lời (PnL) và chỉ số hiệu suất:
```bash
./pos close <COIN> <GIÁ_BÁN>
```

**Ví dụ:**
```bash
./pos close BTC 70000
```
*(Lệnh sẽ trả về mức % lãi/lỗ và rủi ro/lợi nhuận R-multiplier).*

#### 4. Đánh giá hiệu suất chiến lược (Performance)
Xem tổng hợp kết quả của tất cả các lệnh đã đóng để đánh giá xem chiến lược giao dịch của bạn có đang hiệu quả không:
```bash
./pos perf
```
Các thông số bao gồm: `Win Rate`, `Profit Factor`, `Max Consecutive Losses` và `Tổng P&L`.

---

## Cài đặt và Khởi chạy Hệ thống

Hệ thống BestTime Crypto hiện tại bao gồm 3 thành phần chính:
1. **Tiến trình Bot cốt lõi (Core Bot):** Lấy dữ liệu, phân tích tín hiệu, và gửi cảnh báo Telegram.
2. **Backend API:** Cung cấp dữ liệu kết quả phân tích cho giao diện Web.
3. **Web Dashboard:** Giao diện trực quan để xem tín hiệu và quản lý vị thế.

### Bước 1: Cài đặt thư viện (Python & Node.js)
Cài đặt môi trường cho Bot và Backend:
```bash
# Khởi tạo và kích hoạt môi trường ảo (khuyến nghị)
python3 -m venv venv
source venv/bin/activate

# Cài đặt các thư viện Python
pip install -r requirements.txt
pip install fastapi uvicorn
```

Cài đặt môi trường cho Web Frontend:
```bash
cd web
npm install
cd ..
```

### Bước 2: Thiết lập cấu hình
Tạo file `.env` ở thư mục gốc của dự án và điền các khóa API:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
GEMINI_API_KEY=your_gemini_api_key_here
```

### Bước 3: Chạy các dịch vụ

Để hệ thống hoạt động đầy đủ tính năng, bạn cần mở **3 tab Terminal** và chạy song song 3 dịch vụ dưới đây (nhớ kích hoạt `source venv/bin/activate` ở các tab chạy Python):
## 🚀 Hướng Dẫn Chạy Toàn Bộ Hệ Thống (Mới)

Để thuận tiện nhất, bạn có thể chạy **cả 3 luồng (Bot, API, Web)** cùng một lúc trên một Terminal duy nhất bằng lệnh:

```bash
./start.sh
```
*(Nếu báo lỗi phân quyền, hãy chạy `chmod +x start.sh` một lần trước)*

Để tắt toàn bộ hệ thống, chỉ cần nhấn `Ctrl + C` tại Terminal đó.

---

### Chạy Thủ Công Từng Phần (Tuỳ chọn)

**1. Chạy Bot Cốt Lõi (Tab 1)**
Tiến trình này sẽ chạy liên tục, tự động quét thị trường mỗi 15 phút.
```bash
python main.py
```

**2. Chạy Backend API (Tab 2)**
Khởi động máy chủ FastAPI cung cấp dữ liệu cho Web (chạy ở cổng 8000).
```bash
python api/server.py
```

**3. Chạy Web Dashboard (Tab 3)**
Khởi động giao diện Web (chạy ở cổng 3000).
```bash
cd web
npm run dev -- --port 3000 --host
```

Sau khi hoàn tất, mở trình duyệt và truy cập: **[http://localhost:3000](http://localhost:3000)** để sử dụng bảng điều khiển.
