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

# Buoc stdout sang UTF-8 de hien thi tieng Viet va ky tu dac biet
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from btc_scraper.exchanges import binance, bybit, okx
from btc_scraper.exchanges.binance import fetch_ohlcv_multi_tf
from btc_scraper.analysis import analyze_market
from btc_scraper.display import print_all
from btc_scraper.telegram_bot import send_signals_alert
from btc_scraper.ai_analyst import analyze_with_gemini
from btc_scraper.config import COINS, FETCH_INTERVAL_MINUTES

console = Console()

# ─── Auto-restart config ─────────────────────────────────────────────────────
MAX_RETRIES = 5               # Số lần retry tối đa liên tiếp trước khi bỏ cuộc
BASE_BACKOFF = 10             # Thời gian chờ ban đầu (giây) khi gặp lỗi
MAX_BACKOFF = 300             # Thời gian chờ tối đa (giây) = 5 phút
SCHEDULER_RESTART_WAIT = 15  # Thời gian chờ (giây) trước khi restart scheduler
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

    # 3. Phân tích nhận định bằng AI Gemini
    console.print("\n[bold yellow]🤖 Đang gửi dữ liệu phân tích lên Gemini AI...[/bold yellow]")
    ai_report = analyze_with_gemini(analysis, mtf_analysis)

    console.print(Panel(
        ai_report,
        title="[bold yellow]Gemini AI Analyst Report[/]",
        border_style="yellow",
        expand=True
    ))

    # Gửi tin nhắn thông báo kèm báo cáo AI về Telegram
    send_signals_alert(analysis, ai_report)


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
            time.sleep(10)
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
        schedule.every(FETCH_INTERVAL_MINUTES).minutes.do(fetch_and_display_with_retry)
        console.print(
            f"[dim]>> Lên lịch cập nhật mỗi {FETCH_INTERVAL_MINUTES} phút. "
            f"Nhấn Ctrl+C để dừng.[/dim]\n"
        )

    # Lấy dữ liệu ngay lập tức (cũng có retry)
    fetch_and_display_with_retry()

    if args.once:
        return

    try:
        run_scheduler()
    except KeyboardInterrupt:
        console.print("\n[bold red]Đã dừng.[/bold red]")


if __name__ == "__main__":
    main()
