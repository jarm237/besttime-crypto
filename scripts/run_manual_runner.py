"""
Script chạy Runner liên tục ở chế độ Thủ công (Foreground Manual Runner).

Tính năng:
1. Chạy liên tục (Runner lặp định kỳ 15 phút, lắng nghe lệnh Telegram, quản lý vị thế).
2. Hiển thị TOÀN BỘ LOG trực tiếp trên màn hình Terminal trước mắt bạn.
3. Tự động ghi đồng thời vào file log tại logs/manual_runs/manual_runner_<timestamp>.log.
4. Gửi thông báo Telegram liên tục theo từng khung nến 15 phút.
5. Bạn có thể nhấn Ctrl+C bất kỳ lúc nào để dừng.
"""

import sys
import os
import signal
from pathlib import Path
from datetime import datetime

# Đảm bảo đường dẫn gốc thư mục được thêm vào sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# Đặt môi trường cho Runner liên tục (Continuous Manual Runner)
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
    log_file_path = logs_dir / f"manual_runner_{timestamp_str}.log"

    print("=" * 75)
    print("   BESTTIME CRYPTO - CONTINUOUS FOREGROUND RUNNER (MANUAL MODE)")
    print("=" * 75)
    print(f"[LOG] File log lưu tại: {log_file_path}")
    print(f"[ENV] Analysis Universe: {os.getenv('BTC_ANALYSIS_UNIVERSE')}")
    print(f"[ENV] Deployment ID:     {os.getenv('BTC_DEPLOYMENT_ID')}")
    print("[NOTE] Bot dang chay LIEN TUC tren Terminal (dinh ky 15m + Telegram bot listener).")
    print("[NOTE] Nhan Ctrl+C de dung runner bat ky luc nao.")
    print("=" * 75 + "\n")

    # Đảm bảo sys.argv không chứa --once để chạy liên tục
    sys.argv = ["main.py"]

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
        except KeyboardInterrupt:
            print("\n\n[STOP] Da dung Runner theo yeu cau nguoi dung (Ctrl+C).")
            print(f"[LOG] File log da duoc luu tai: {log_file_path}")
            print("=" * 75)
        finally:
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr


if __name__ == "__main__":
    main()
