"""
Multi-coin OHLCV Scraper - Entry point
Cào dữ liệu nến 15m đa coin từ Binance, Bybit, OKX
Tính toán chỉ số kỹ thuật và in bảng tổng hợp tín hiệu Mua/Bán.
"""

import sys
import argparse
import time
import schedule
from rich.console import Console
from rich.panel import Panel

import queue
import threading

# Buoc stdout sang UTF-8 de hien thi tieng Viet va ky tu dac biet
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from btc_scraper.exchanges import binance, bybit, okx
from btc_scraper.exchanges.binance import fetch_ohlcv_multi_tf
from btc_scraper.analysis import analyze_market
from btc_scraper.display import print_all
from btc_scraper.telegram_bot import send_signals_alert, send_ai_reply, send_position_recommendations
from btc_scraper.ai_analyst import analyze_with_gemini
from btc_scraper.config import COINS, FETCH_INTERVAL_MINUTES
from btc_scraper import position_tracker

console = Console()

# ─── Auto-restart config ─────────────────────────────────────────────────────
MAX_RETRIES = 5               # Số lần retry tối đa liên tiếp trước khi bỏ cuộc
BASE_BACKOFF = 10             # Thời gian chờ ban đầu (giây) khi gặp lỗi
MAX_BACKOFF = 300             # Thời gian chờ tối đa (giây) = 5 phút
SCHEDULER_RESTART_WAIT = 15  # Thời gian chờ (giây) trước khi restart scheduler
# ─────────────────────────────────────────────────────────────────────────────


# ─── Queue & Background AI Worker ─────────────────────────────────────────────
ai_queue: queue.Queue = queue.Queue()

def ai_worker():
    """
    Background worker nhặt dữ liệu phân tích từ hàng đợi, gọi Gemini AI và 
    gửi reply nhận định lên Telegram mà không ảnh hưởng tới luồng Core.
    """
    while True:
        item = ai_queue.get()
        if item is None:
            break
        if len(item) == 4:
            analysis, mtf_analysis, open_positions, message_id = item
        else:
            analysis, mtf_analysis, message_id = item
            open_positions = []
            
        try:
            console.print("\n[bold yellow]🤖 [AI Worker] Đang gửi dữ liệu phân tích lên Gemini AI...[/bold yellow]")
            ai_report = analyze_with_gemini(analysis, mtf_analysis, open_positions)
            
            # Hiển thị ở local console
            console.print(Panel(
                ai_report,
                title="[bold yellow]Gemini AI Analyst Report[/]",
                border_style="yellow",
                expand=True
            ))
            
            # Gửi tin nhắn reply bổ trợ trên Telegram
            if message_id:
                send_ai_reply(ai_report, reply_to_message_id=message_id)
            else:
                send_ai_reply(ai_report)
                
            # Lưu AI report cho web dashboard
            import json, os, time
            data_dir = os.path.join(os.path.dirname(__file__), "data")
            os.makedirs(data_dir, exist_ok=True)
            with open(os.path.join(data_dir, "latest_ai_analysis.json"), "w", encoding="utf-8") as f:
                json.dump({"timestamp": time.time(), "report": ai_report}, f, ensure_ascii=False)
                
        except Exception as e:
            console.print(f"\n[bold red][AI Worker Error] Loi phan tich hoac gui Telegram: {e}[/bold red]")
        finally:
            ai_queue.task_done()
# ─────────────────────────────────────────────────────────────────────────────


def fetch_and_display():
    """Lấy dữ liệu từ tất cả sàn, phân tích chỉ báo và in ra terminal."""
    console.print("[dim]Đang lấy dữ liệu thị trường (BTC, ETH, BNB, SOL, ZEC)...[/dim]")

    results = {}
    analysis = {}
    mtf_analysis = {}   # Phân tích đa khung thời gian gửi cho AI

    for coin in COINS:
        results[coin] = {}
        # Cào từ từng sàn
        binance_candles = binance.fetch_ohlcv(coin)

        results[coin]["Binance"] = binance_candles

        # Phân tích từng sàn (khung 15m - hiển thị terminal)
        for exchange, candles in [("Binance", binance_candles)]:
            ana = analyze_market(candles)
            if candles and "error" not in candles[0]:
                ana["close"] = candles[-1]["close"]
            else:
                ana["close"] = 0.0

            # Key phân tích định dạng: "COIN:EXCHANGE"
            analysis[f"{coin}:{exchange}"] = ana

        # Lấy thêm nến 1h, 4h, 1d cho phân tích AI đa khung
        console.print(f"[dim]  ↳ [{coin}] Đang lấy nến 1h / 4h / 1d...[/dim]")
        mtf_candles = fetch_ohlcv_multi_tf(coin)
        mtf_analysis[coin] = {}
        for tf, tf_candles in mtf_candles.items():
            tf_ana = analyze_market(tf_candles)
            if tf_candles and "error" not in tf_candles[0]:
                tf_ana["close"] = tf_candles[-1]["close"]
            else:
                tf_ana["close"] = 0.0
            mtf_analysis[coin][tf] = tf_ana

    # Hiển thị bảng giá & chỉ báo ở Terminal
    print_all(results, analysis)

    # Lưu lại signals mới nhất để Web Dashboard đọc
    try:
        import os, json
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "latest_signals.json"), "w", encoding="utf-8") as f:
            json.dump(analysis, f, ensure_ascii=False, indent=2)
    except Exception as e:
        console.print(f"[dim red]Không thể lưu latest_signals.json: {e}[/dim red]")

    # Đánh giá các vị thế đang mở và gửi khuyến nghị lên Telegram
    try:
        recs = position_tracker.evaluate_positions(analysis)
        if recs:
            send_position_recommendations(recs)
    except Exception as e:
        console.print(f"[bold red]Lỗi khi đánh giá vị thế: {e}[/bold red]")

    # 3. Gửi tin nhắn thông báo tín hiệu về Telegram ngay lập tức (Luồng Core)
    message_id = send_signals_alert(analysis)

    # 4. Đẩy phân tích đa khung thời gian và vị thế mở vào Queue cho Luồng AI xử lý ngầm
    open_positions = position_tracker.get_open_positions()
    ai_queue.put((analysis, mtf_analysis, open_positions, message_id))

def fetch_and_analyze_open_positions_only():
    """Lấy dữ liệu và phân tích chỉ cho các coin đang có vị thế mở (quét khẩn cấp mỗi 5 phút). Không gọi AI."""
    open_positions = position_tracker.get_open_positions()
    if not open_positions:
        return
        
    coins_to_check = list(set([p["coin"] for p in open_positions]))
    console.print(f"[dim]Đang quét khẩn cấp các vị thế mở ({', '.join(coins_to_check)})...[/dim]")
    
    analysis = {}
    
    for coin in coins_to_check:
        binance_candles = binance.fetch_ohlcv(coin)
        ana = analyze_market(binance_candles)
        if binance_candles and "error" not in binance_candles[0]:
            ana["close"] = binance_candles[-1]["close"]
        else:
            ana["close"] = 0.0
        analysis[f"{coin}:Binance"] = ana
            
    try:
        recs = position_tracker.evaluate_positions(analysis)
        if recs:
            send_position_recommendations(recs)
    except Exception as e:
        console.print(f"[bold red]Lỗi khi đánh giá vị thế: {e}[/bold red]")

def fetch_and_analyze_open_positions_only_with_retry():
    attempt = 0
    while attempt <= MAX_RETRIES:
        try:
            fetch_and_analyze_open_positions_only()
            return
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            attempt += 1
            backoff = min(BASE_BACKOFF * (2 ** (attempt - 1)), MAX_BACKOFF)
            if attempt > MAX_RETRIES:
                return
            time.sleep(backoff)


def fetch_and_display_with_retry():
    """
    Wrapper quanh fetch_and_display() với cơ chế retry + exponential backoff.
    Nếu lỗi mạng hoặc exception bất kỳ, tự động thử lại tối đa MAX_RETRIES lần.
    """
    attempt = 0
    while attempt <= MAX_RETRIES:
        try:
            fetch_and_display()
            return  # Thành công → thoát
        except KeyboardInterrupt:
            raise  # Cho phép Ctrl+C thoát bình thường
        except Exception as exc:
            attempt += 1
            backoff = min(BASE_BACKOFF * (2 ** (attempt - 1)), MAX_BACKOFF)
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

            if attempt > MAX_RETRIES:
                console.print(
                    f"\n[bold red][{timestamp}] Lỗi sau {MAX_RETRIES} lần thử. "
                    f"Bỏ qua chu kỳ này và đợi lần chạy tiếp theo.[/bold red]\n"
                    f"[red]Chi tiết: {exc}[/red]\n"
                )
                return  # Không retry thêm, chờ scheduler gọi lại sau

            console.print(
                f"\n[bold yellow][{timestamp}] Lỗi lần {attempt}/{MAX_RETRIES}: {exc}[/bold yellow]\n"
                f"[dim]Thử lại sau {backoff}s...[/dim]\n"
            )
            time.sleep(backoff)


def run_scheduler():
    """
    Vòng lặp scheduler có cơ chế tự restart nếu gặp lỗi bất ngờ.
    Chỉ dừng khi nhận KeyboardInterrupt (Ctrl+C).
    """
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)  # Giảm sleep xuống 1s để kích hoạt đúng giờ chính xác hơn
        except KeyboardInterrupt:
            raise  # Truyền lên để main() xử lý
        except Exception as exc:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            console.print(
                f"\n[bold red][{timestamp}] Scheduler crash: {exc}[/bold red]\n"
                f"[dim]Restart scheduler sau {SCHEDULER_RESTART_WAIT}s...[/dim]\n"
            )
            time.sleep(SCHEDULER_RESTART_WAIT)
            # Tiếp tục vòng lặp while → tự restart


def main():
    parser = argparse.ArgumentParser(
        description="Multi-coin OHLCV Scraper & Analyzer"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Chạy một lần rồi thoát (mặc định: chạy liên tục)",
    )
    args = parser.parse_args()

    console.print(f"\n[bold yellow]*** Multi-coin Trading Signals Scraper ***[/]")
    console.print(f"[dim]Coins: {', '.join(COINS)} | Nguồn: Binance - Bybit - OKX[/dim]\n")
    console.print(
        f"[dim]Auto-restart: ON | Max retries: {MAX_RETRIES} | "
        f"Backoff: {BASE_BACKOFF}s-{MAX_BACKOFF}s[/dim]\n"
    )

    # Lên lịch chạy định kỳ (dùng wrapper có retry)
    if not args.once:
        # Dùng giờ tĩnh trên đồng hồ, cộng thêm 1 phút (ví dụ: 01, 16, 31, 46) 
        # để chắc chắn nến đã đóng cửa hoàn toàn trên sàn giao dịch.
        interval = max(1, FETCH_INTERVAL_MINUTES)
        general_minutes = [(m + 1) % 60 for m in range(0, 60, interval)]
        focused_minutes = [(m + 1) % 60 for m in range(0, 60, 5) if (m + 1) % 60 not in general_minutes]
        
        for m in general_minutes:
            schedule.every().hour.at(f"{m:02d}:00").do(fetch_and_display_with_retry)
            
        for m in focused_minutes:
            schedule.every().hour.at(f"{m:02d}:00").do(fetch_and_analyze_open_positions_only_with_retry)
            
        console.print(
            f"[dim]>> Lên lịch tổng quát vào: {general_minutes} | Quét khẩn cấp vị thế mở vào: {focused_minutes}. Nhấn Ctrl+C để dừng.[/dim]\n"
        )

    # Khởi động worker thread chạy ngầm (daemon)
    worker = threading.Thread(target=ai_worker, daemon=True)
    worker.start()

    # Lấy dữ liệu ngay lập tức (cũng có retry)
    fetch_and_display_with_retry()

    if args.once:
        # Nếu chỉ chạy 1 lần, đợi hàng đợi AI hoàn thành trước khi thoát
        if not ai_queue.empty():
            console.print("\n[dim]Đang đợi AI Worker hoàn thành phân tích...[/dim]")
            ai_queue.join()
        return

    try:
        run_scheduler()
    except KeyboardInterrupt:
        console.print("\n[bold red]Đã dừng.[/bold red]")


if __name__ == "__main__":
    main()
