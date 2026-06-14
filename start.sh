#!/bin/bash

echo "==========================================="
echo "   Khởi động BestTime Crypto Dashboard"
echo "==========================================="

# Di chuyển đến thư mục gốc của project
cd "$(dirname "$0")"

# Kích hoạt virtual environment nếu có
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Hàm dọn dẹp khi nhấn Ctrl+C
cleanup() {
    echo ""
    echo "Đang tắt tất cả các dịch vụ..."
    kill $API_PID $WEB_PID $BOT_PID 2>/dev/null
    exit
}

# Gắn trap để bắt sự kiện Ctrl+C
trap cleanup INT

# 1. Khởi động API Server (FastAPI)
echo "[1/3] Khởi động API Server (Cổng 8000)..."
uvicorn api.server:app --host 0.0.0.0 --port 8000 > /dev/null 2>&1 &
API_PID=$!
sleep 1

# 2. Khởi động Web Dashboard (Vite/React)
echo "[2/3] Khởi động Web Dashboard (Cổng 3000)..."
cd web
# Pass the port argument so Vite runs on port 3000 to match the message above
npm run dev -- --port 3000 > /dev/null 2>&1 &
WEB_PID=$!
cd ..
sleep 1

# 3. Khởi động Trading Bot (Python Core)
echo "[3/3] Khởi động Trading Bot..."
python3 main.py &
BOT_PID=$!

echo "==========================================="
echo " Tất cả dịch vụ đã chạy thành công!"
echo " 👉 Web Dashboard: http://localhost:3000"
echo " 👉 API Server:    http://localhost:8000"
echo " Nhấn Ctrl+C để tắt hệ thống."
echo "==========================================="

# Đợi các tiến trình nền chạy (giữ terminal không bị tắt)
wait
