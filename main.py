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


def _classify_mtf_signal(signal: str) -> str:
    sig = str(signal or "").upper()
    if "STRONG BUY" in sig or "BUY" in sig or "BULL" in sig:
        return "BULL"
    if "STRONG SELL" in sig or "SELL" in sig or "BEAR" in sig:
        return "BEAR"
    return "NEUTRAL"


def _summarize_htf_trend(mtf_data: dict[str, dict]) -> str:
    if not mtf_data:
        return "NEUTRAL"

    counts = {"BULL": 0, "BEAR": 0, "NEUTRAL": 0}
    for tf in ["1d", "4h", "1h"]:
        info = mtf_data.get(tf)
        if not info:
            continue
        from btc_scraper.signal_score import extract_signal_fields
        sig_fields = extract_signal_fields(info)
        counts[_classify_mtf_signal(info.get("signal", sig_fields.get("raw", "")))] += 1

    if counts["BULL"] >= 2 and counts["BEAR"] == 0:
        return "BULLISH"
    if counts["BEAR"] >= 2 and counts["BULL"] == 0:
        return "BEARISH"
    if counts["BULL"] > counts["BEAR"]:
        return "BULLISH-MIXED"
    if counts["BEAR"] > counts["BULL"]:
        return "BEARISH-MIXED"
    return "NEUTRAL"


def _format_htf_details(mtf_data: dict[str, dict]) -> str:
    parts = []
    for tf in ["1d", "4h", "1h"]:
        info = mtf_data.get(tf)
        if info:
            parts.append(f"{tf.upper()}={info.get('signal', 'N/A')}")
    return " | ".join(parts)

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

        # Gắn HTF trend summary vào analysis 15m
        htf_trend = _summarize_htf_trend(mtf_analysis[coin])
        htf_details = _format_htf_details(mtf_analysis[coin])
        analysis[f"{coin}:Binance"]["htf_trend"] = htf_trend
        analysis[f"{coin}:Binance"]["htf_details"] = htf_details

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

    # [Shadow Mode] Ghi log Meta Model predictions cho tất cả BUY/SELL signals
    try:
        from scripts.shadow_log import log_signal_prediction
        for key, ana in analysis.items():
            sig_score = ana.get("signal_score") or {}
            meta_prob = sig_score.get("meta_confidence")
            sig = ana.get("signal", "")
            if meta_prob is not None and ("BUY" in sig or "SELL" in sig):
                coin = key.split(":")[0]
                log_signal_prediction(
                    symbol=f"{coin}USDT",
                    signal=sig,
                    meta_prob=meta_prob,
                    signal_score=sig_score.get("score", 50),
                    regime=ana.get("regime") or (sig_score.get("regime") or ""),
                    htf_trend=ana.get("htf_trend", ""),
                )
    except Exception as e:
        console.print(f"[dim red][Shadow] Lỗi ghi shadow log: {e}[/dim red]")

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

    # Hiển thị trạng thái Shadow Mode & Meta Model khi khởi động
    try:
        import os, time as _time, json as _json
        shadow_log_path = os.path.join(os.path.dirname(__file__), "logs", "shadow_predictions.json")
        meta_metric_path = os.path.join(os.path.dirname(__file__), "logs", "meta_model.json")

        # Meta Model status
        if os.path.exists(meta_metric_path):
            with open(meta_metric_path, "r", encoding="utf-8") as _f:
                _m = _json.load(_f)
            _auc = _m.get("cv_auc_mean")
            _n = _m.get("n_samples", 0)
            _auc_str = f"{_auc:.3f}" if _auc else "N/A"
            console.print(
                f"[bold cyan]  [Meta Model] Loaded | Samples: {_n} | CV AUC: {_auc_str} | "
                f"Calibrated: {'Yes' if _m.get('calibrated') else 'No'}[/bold cyan]"
            )
        else:
            console.print("[dim yellow]  [Meta Model] Chua train. Chay: python -m btc_scraper.meta_model --train[/dim yellow]")

        # Shadow Mode status
        if os.path.exists(shadow_log_path):
            _age_days = (_time.time() - os.path.getctime(shadow_log_path)) / 86400
            if _age_days < 7:
                _days_left = 7 - _age_days
                console.print(
                    f"[bold magenta]  [Shadow Mode] Sprint 2 dang chay: "
                    f"{_age_days:.1f}/7 ngay | Con {_days_left:.1f} ngay -> Reminder luc 09:00 hang ngay[/bold magenta]\n"
                )
            else:
                console.print(
                    f"[bold green]  [Shadow Mode] Da du 7 ngay! "
                    f"Chay: python scripts/shadow_log.py de xem calibration report.[/bold green]\n"
                )
        else:
            console.print("[dim]  [Shadow Mode] Chua bat dau (se tu dong ghi log khi co BUY/SELL signal).[/dim]\n")
    except Exception:
        pass


    # Lên lịch chạy định kỳ (dùng wrapper có retry)
    if not args.once:
        # Dùng giờ tĩnh trên đồng hồ, cộng thêm 1 phút (ví dụ: 01, 16, 31, 46) 
        # để chắc chắn nến đã đóng cửa hoàn toàn trên sàn giao dịch.
        interval = max(1, FETCH_INTERVAL_MINUTES)
        general_minutes = [(m + 1) % 60 for m in range(0, 60, interval)]
        focused_minutes = [(m + 1) % 60 for m in range(0, 60, 5) if (m + 1) % 60 not in general_minutes]
        
        for m in general_minutes:
            schedule.every().hour.at(f":{m:02d}").do(fetch_and_display_with_retry)
            
        for m in focused_minutes:
            schedule.every().hour.at(f":{m:02d}").do(fetch_and_analyze_open_positions_only_with_retry)

        def run_weekly_report_job():
            import subprocess, os
            console.print("[bold yellow]Đang chạy Weekly Report...[/bold yellow]")
            subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "scripts", "weekly_job.py")])
            
        def run_continuous_learning_job():
            import subprocess, os
            console.print("[bold yellow]Đang chạy Continuous Learning Pipeline...[/bold yellow]")
            subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "scripts", "continuous_learning.py")])

        schedule.every().sunday.at("23:30").do(run_continuous_learning_job)
        schedule.every().sunday.at("23:45").do(run_weekly_report_job)

        # ── Shadow Mode Reminder ──────────────────────────────────────────
        def check_shadow_mode_reminder():
            """
            Kiểm tra hàng ngày xem Shadow Mode đã chạy đủ 7 ngày chưa.
            Nếu đủ 7 ngày: gửi Telegram alert với calibration report và hướng dẫn chuyển Sprint 3.
            Sau khi gửi xong, tự hủy job này khỏi schedule.
            """
            import os, time as _time
            shadow_log_path = os.path.join(os.path.dirname(__file__), "logs", "shadow_predictions.json")

            if not os.path.exists(shadow_log_path):
                return  # chưa có dữ liệu shadow mode, bỏ qua

            # Kiểm tra thời gian tạo file (lần đầu tiên ghi shadow log)
            file_age_days = (_time.time() - os.path.getctime(shadow_log_path)) / 86400

            if file_age_days < 7:
                days_left = max(0, 7 - file_age_days)
                console.print(f"[dim][Shadow] {file_age_days:.1f} ngày / 7 ngày. Còn {days_left:.1f} ngày nữa.[/dim]")
                return

            # Đã đủ 7 ngày → generate calibration report và gửi Telegram
            console.print("[bold yellow][Shadow] Đã 7 ngày! Đang tạo calibration report...[/bold yellow]")
            try:
                from scripts.shadow_log import calibration_report
                report = calibration_report(min_samples=3)

                lines = [
                    "[SHADOW MODE - SPRINT 2 COMPLETE]",
                    "Meta Model da chay duoc 7 ngay.",
                    "",
                ]

                if report["status"] == "no_data":
                    lines += [
                        "Chua co du lieu calibration.",
                        "Ly do: khong co position nao duoc dong trong 7 ngay.",
                        "Tiep tuc Shadow Mode them 1 tuan.",
                    ]
                else:
                    lines += [
                        f"Tong completed: {report['total_completed']} | Pending: {report['total_pending']}",
                        f"Overall Win Rate thuc te: {report.get('overall_win_rate', 'N/A')}%",
                        "",
                        "=== CALIBRATION BUCKETS ===",
                    ]
                    for bucket, data in report.get("buckets", {}).items():
                        if data.get("actual_wr") is not None:
                            ok = "[OK]" if data.get("calibrated") else "[LECH]"
                            lines.append(
                                f"{bucket}: du doan={data['predicted_wr']}% | thuc te={data['actual_wr']}% "
                                f"(n={data['count']}) {ok}"
                            )
                        else:
                            lines.append(f"{bucket}: chua du sample (n={data['count']})<3)")

                    lines += [
                        "",
                        f"Monotonic: {'Co' if report.get('monotonic_calibration') else 'Khong'}",
                        "",
                        report.get("recommendation", ""),
                        "",
                    ]

                    # Hướng dẫn Sprint 3 nếu model tốt
                    if report.get("monotonic_calibration"):
                        lines += [
                            "=== NEXT STEPS: SPRINT 3 ===",
                            "1. Xem calibration report day du:",
                            "   python scripts/shadow_log.py",
                            "",
                            "2. Bat Signal Filter trong signal_score.py:",
                            "   Uncomment dong: META_REJECT_THRESHOLD = 0.45",
                            "   (hoac set env: META_REJECT_THRESHOLD=0.45)",
                            "",
                            "3. Restart bot de ap dung:",
                            "   Ctrl+C roi chay lai python main.py",
                        ]
                    else:
                        lines += [
                            "=== NEXT STEPS ===",
                            "Model chua calibrated hoan toan.",
                            "Tiep tuc Shadow Mode them 1 tuan.",
                            "Chay: python scripts/shadow_log.py de xem chi tiet.",
                        ]

                message = "\n".join(lines)
                from btc_scraper.telegram_bot import send_telegram_message
                send_telegram_message(message, parse_mode=None)
                console.print("[bold green][Shadow] Da gui Telegram reminder Sprint 2 complete![/bold green]")

                # Huỷ job này khỏi schedule (dùng sentinel)
                return schedule.CancelJob

            except Exception as e:
                console.print(f"[red][Shadow] Loi tao calibration report: {e}[/red]")

        # Chạy kiểm tra mỗi ngày lúc 09:00 sáng
        schedule.every().day.at("09:00").do(check_shadow_mode_reminder)
        # ──────────────────────────────────────────────────────────────────
            
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
