"""
Script chạy phân tích thị trường thủ công (Manual Scan & Analysis) cho Besttime Crypto.

Tính năng:
1. Chạy 1 chu kỳ phân tích duy nhất (Synchronous / No background process).
2. Tải cấu hình từ .env và thiết lập môi trường runtime.
3. Xuất log chi tiết 100% ra màn hình Terminal đồng thời lưu file log tại logs/manual_runs/.
4. Gửi báo cáo / thông báo tín hiệu về Telegram.
5. Cập nhật latest_signals.json.
"""

import sys
import os
from pathlib import Path
from datetime import datetime

# Đảm bảo đường dẫn gốc thư mục được thêm vào sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# Đặt môi trường cho lượt chạy phân tích thủ công (Manual Scan)
os.environ["BTC_DEPLOYMENT_ID"] = "paper-canary-win-tsfix-20260901-01"
os.environ["BTC_PAPER_RUN_ID"] = "paper-canary-win-tsfix-20260901-01"
os.environ["BTC_ANALYSIS_UNIVERSE"] = "BNB,BTC,DOGE,ETH,IOTA,NEAR,SOL,TRX,ZEC"
os.environ["AUTO_TRADE_COINS"] = "BNB,BTC,DOGE,ETH,IOTA,NEAR,SOL,TRX,ZEC"
os.environ["BTC_EVIDENCE_ELIGIBLE"] = "false"
os.environ["BTC_DISABLE_RUNTIME_LOCK"] = "1"
os.environ["BTC_RUNTIME_ENVIRONMENT"] = "paper"
os.environ["LIVE_TRADING_ENABLED"] = "false"
os.environ["AUTO_TRADE_DRY_RUN"] = "true"

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


def main():
    # Đảm bảo stdout/stderr dùng UTF-8 trên Windows console
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # Tạo thư mục lưu log
    logs_dir = PROJECT_ROOT / "logs" / "manual_runs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_path = logs_dir / f"manual_scan_{timestamp_str}.log"

    print("=" * 70)
    print("      BESTTIME CRYPTO - MANUAL SCAN & ANALYSIS")
    print("=" * 70)
    print(f"[LOG] Log file: {log_file_path}")
    print(f"[ENV] Analysis Universe: {os.getenv('BTC_ANALYSIS_UNIVERSE')}")
    print(f"[ENV] Deployment ID:     {os.getenv('BTC_DEPLOYMENT_ID')}")

    # Chạy main.py ở chế độ --once (1 lần duy nhất, không daemon)
    # Gán cờ --once
    sys.argv = ["main.py", "--once"]

    print("\n[STEP 1/3] Khoi tao bo phan tich & tai du lieu nen 15m...")

    # Ghi log đồng thời ra file và console
    class TeeStream:
        def __init__(self, original_stream, log_file):
            self.original_stream = original_stream
            self.log_file = log_file

        def write(self, buf):
            try:
                self.original_stream.write(buf)
                self.original_stream.flush()
            except Exception:
                pass
            try:
                self.log_file.write(buf)
                self.log_file.flush()
            except Exception:
                pass

        def flush(self):
            try:
                self.original_stream.flush()
            except Exception:
                pass
            try:
                self.log_file.flush()
            except Exception:
                pass

    with open(log_file_path, "w", encoding="utf-8") as f_log:
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr
        sys.stdout = TeeStream(orig_stdout, f_log)
        sys.stderr = TeeStream(orig_stderr, f_log)
        try:
            from main import main as run_main
            run_main()
            print("\n[STEP 3/3] HOAN THANH CHU KY PHAN TICH THU CONG.")
            print(f"OK: Da ket thuc tien trinh sach se. File log: {log_file_path}")
            print("=" * 70)
        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr


if __name__ == "__main__":
    main()

