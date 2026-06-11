"""
Weekly Report Job
-----------------
Chạy vào cuối tuần để tổng hợp báo cáo giao dịch trong 7 ngày qua, 
nhờ Gemini AI nhận xét và gửi lên Telegram.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from btc_scraper.ai_analyst import generate_weekly_report
from btc_scraper.telegram_bot import send_telegram_message

def run_weekly_report():
    print("=" * 60)
    print("  ĐANG TẠO BÁO CÁO TỔNG KẾT TUẦN (WEEKLY REPORT)...")
    print("=" * 60)
    
    report = generate_weekly_report()
    
    if report:
        msg = f"📊 <b>[BÁO CÁO TỔNG KẾT TUẦN]</b> 📊\n\n{report}"
        send_telegram_message(msg, parse_mode="HTML")
        print("  ✅ Đã gửi báo cáo tuần lên Telegram.")
    else:
        print("  ⚠️ Không có báo cáo tuần.")

if __name__ == "__main__":
    run_weekly_report()
