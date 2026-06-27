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
import asyncio
import aiohttp

# Buoc stdout sang UTF-8 de hien thi tieng Viet va ky tu dac biet
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from btc_scraper.exchanges import binance, bybit, okx
from btc_scraper.exchanges.binance import fetch_ohlcv_multi_tf
from btc_scraper.analysis import analyze_market
from btc_scraper.ui.display import print_all
from btc_scraper.telegram_bot import send_signals_alert, send_ai_reply, send_position_recommendations, start_telegram_listener
from btc_scraper.ai_analyst import analyze_with_gemini
from btc_scraper.core.config import COINS, FETCH_INTERVAL_MINUTES
from btc_scraper.trading import position_tracker
from btc_scraper.core.candle_store import candle_store
from btc_scraper.exchanges.binance_ws import BinanceWebSocketManager


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
        from btc_scraper.ml_engine.signal_score import extract_signal_fields
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


async def check_and_execute_auto_closes(recs: list[dict]):
    """
    Kiểm tra và tự động đóng vị thế trên Binance Testnet nếu có khuyến nghị chốt lời/cắt lỗ.
    """
    try:
        from btc_scraper.trading.auto_trader import auto_trader
        open_positions = position_tracker.get_open_positions()
        for rec in recs:
            coin = rec["coin"]
            action = rec["recommendation"]
            current_price = rec["current_price"]

            # ─── Full close triggers (SL, TP2, RL EXIT, RL TAKE_PROFIT) ───────
            # NOTE: labels changed to ASCII in _generate_recommendation to avoid
            # cp1252 crashes. This check MUST match those ASCII labels exactly.
            should_close = (
                "[!] CAT LO NGAY" in action        # SL hit (was: CẮT LỖ NGAY)
                or "[TP2] CHOT LOI TP2" in action  # TP2 hit (was: CHỐT LỜI TP2)
                or "[RL] DONG VI THE" in action     # RL action=4 EXIT
                or "[RL] CHOT LOI FULL" in action   # RL action=3 TAKE_PROFIT
            )

            # ─── Partial close triggers (RL PARTIAL_CLOSE 50%) ────────────────
            should_partial_close = "[RL] CHOT LOI 50%" in action  # RL action=1

            if should_close:
                # Tìm xem có position nào note chứa "[AUTO-"
                auto_pos = [p for p in open_positions if p["coin"].upper() == coin.upper() and "[AUTO-" in p.get("note", "")]
                if auto_pos:
                    console.print(f"[bold yellow][AutoTrade] Tu dong dong vi the {coin} do: {action}[/bold yellow]")
                    closed_data = position_tracker.close_position(coin, current_price)

                    # Cập nhật kết quả vào circuit breaker của AutoTrader
                    result_type = "LOSS" if "CAT LO NGAY" in action else "WIN"
                    auto_trader._record_trade_result(result_type)

                    # Gửi tin nhắn Telegram thông báo đóng vị thế tự động
                    msg = (
                        f"[AUTO-TRADE CLOSED] {coin}\n"
                        f"Hanh dong: {action}\n"
                        f"Gia dong: ${current_price:,.4f}\n"
                        f"PnL: {closed_data.get('pnl_pct', 0.0):+.2f}%\n"
                        f"R-multiplier: {closed_data.get('r_multiplier', 'N/A')}R\n"
                        f"Ket qua: {result_type}"
                    )
                    from btc_scraper.telegram_bot import send_telegram_message
                    send_telegram_message(msg, parse_mode=None)

                    # Thực hiện lệnh đặt đóng trên exchange nếu không phải dry_run
                    note = auto_pos[0].get("note", "")
                    mode = "TESTNET" if "TESTNET" in note else ("LIVE" if "LIVE" in note else "DRY_RUN")
                    if mode in ("TESTNET", "LIVE"):
                        try:
                            from btc_scraper.core.ccxt_client import CCXTClient
                            client = CCXTClient.from_env()
                            client.dry_run = False
                            symbol = f"{coin}/USDT"
                            direction = auto_pos[0].get("direction")
                            invested_usdt = auto_pos[0].get("invested_usdt", 0.0)
                            entry_price = auto_pos[0].get("entry_price", 0.0)
                            if entry_price > 0:
                                current_val = invested_usdt * (current_price / entry_price)
                                if direction == "LONG":
                                    await client.create_market_sell(symbol, current_val)
                                else:
                                    await client.create_market_buy(symbol, current_val)
                                await client.close()
                        except Exception as ex_err:
                            console.print(f"[bold red][AutoTrade] Loi dong lenh tren san: {ex_err}[/bold red]")

            elif should_partial_close:
                # RL recommends closing 50% of position
                auto_pos = [p for p in open_positions if p["coin"].upper() == coin.upper() and "[AUTO-" in p.get("note", "")]
                if auto_pos:
                    console.print(f"[bold cyan][AutoTrade] RL: Chot 50% vi the {coin} tai ${current_price:,.4f}[/bold cyan]")
                    try:
                        position_tracker.close_partial_position(coin, current_price, 50.0)
                        msg = (
                            f"[AUTO-TRADE PARTIAL CLOSE] {coin}\n"
                            f"RL Agent: Chot 50% vi the\n"
                            f"Gia chot: ${current_price:,.4f}\n"
                            f"PnL tai thoi diem chot: {rec.get('pnl_pct', 0.0):+.2f}%"
                        )
                        from btc_scraper.telegram_bot import send_telegram_message
                        send_telegram_message(msg, parse_mode=None)
                    except Exception as partial_err:
                        console.print(f"[bold red][AutoTrade] Loi chot 50%: {partial_err}[/bold red]")

    except Exception as e:
        console.print(f"[dim red][AutoTrade] Loi tu dong dong vi the: {e}[/dim red]")


# ── Global WS Manager (khởi tạo trong main()) ────────────────────────────────
_ws_manager: BinanceWebSocketManager | None = None


async def _get_candles_for_coin(coin: str, interval: str = "15m", session=None) -> list[dict]:
    """
    Đọc nến từ CandleStore (WS) nếu có, ngược lại fallback về REST.
    Đây là điểm duy nhất trong code đọc dữ liệu Binance.
    """
    global _ws_manager
    if _ws_manager is not None and candle_store.has_data(coin, interval):
        candles = candle_store.get(coin, interval)
        if candles:
            return candles

    # REST fallback (WS chưa sẵn sàng hoặc chưa có dữ liệu)
    from btc_scraper.exchanges.binance import fetch_ohlcv, fetch_ohlcv_tf, MTF_INTERVALS
    if interval == "15m":
        return await fetch_ohlcv(coin, session)
    limit = MTF_INTERVALS.get(interval, 50)
    return await fetch_ohlcv_tf(coin, interval, limit, session)


async def fetch_and_display():
    """Lấy dữ liệu từ CandleStore (WS) hoặc REST (fallback), phân tích và in ra terminal."""
    global _ws_manager
    using_ws = _ws_manager is not None and _ws_manager.is_healthy()
    src_label = "WebSocket" if using_ws else "REST fallback (parallel)"
    console.print(f"[dim]Đang lấy dữ liệu thị trường ({src_label})...[/dim]")

    results = {}
    raw_candles_dict = {}
    mtf_candles_dict = {}

    async with aiohttp.ClientSession() as session:
        tasks_15m = []
        for coin in COINS:
            tasks_15m.append(_get_candles_for_coin(coin, "15m", session))
            
        res_15m = await asyncio.gather(*tasks_15m)
        
        for i, coin in enumerate(COINS):
            binance_candles = res_15m[i]
            results[coin] = {"Binance": binance_candles}
            raw_candles_dict[coin] = binance_candles
            mtf_candles_dict[coin] = {}

        if not using_ws:
            console.print(f"[dim]  ↳ Đang lấy nến 1h / 4h / 1d (REST parallel)...[/dim]")
            tasks_mtf = []
            for coin in COINS:
                for tf in ["1h", "4h", "1d"]:
                    tasks_mtf.append(_get_candles_for_coin(coin, tf, session))
            res_mtf = await asyncio.gather(*tasks_mtf)
            
            idx = 0
            for coin in COINS:
                for tf in ["1h", "4h", "1d"]:
                    mtf_candles_dict[coin][tf] = res_mtf[idx]
                    idx += 1
        else:
            for coin in COINS:
                for tf in ["1h", "4h", "1d"]:
                    mtf_candles_dict[coin][tf] = await _get_candles_for_coin(coin, tf, session)

    # Chạy hệ thống đa tác nhân điều phối (AgentOrchestrator)
    from btc_scraper.ml_engine.multi_agent import AgentOrchestrator
    orchestrator = AgentOrchestrator()
    context = await orchestrator.run_cycle(raw_candles_dict, mtf_candles_dict)

    analysis = context["analysis"]
    mtf_analysis = context["mtf_analysis"]

    # Hiển thị bảng giá & chỉ báo ở Terminal
    print_all(results, analysis)

    # Lưu lại signals mới nhất để Web Dashboard đọc
    try:
        import os, json
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "latest_signals.json"), "w", encoding="utf-8") as f:
            json.dump({"analysis": analysis, "mtf_analysis": mtf_analysis}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        console.print(f"[dim red]Không thể lưu latest_signals.json: {e}[/dim red]")

    # Đánh giá các vị thế đang mở và gửi khuyến nghị lên Telegram
    try:
        recs = position_tracker.evaluate_positions(analysis)
        if recs:
            send_position_recommendations(recs)
            await check_and_execute_auto_closes(recs)
    except Exception as e:
        console.print(f"[bold red]Lỗi khi đánh giá vị thế: {e}[/bold red]")

    # 3. Gửi tin nhắn thông báo tín hiệu về Telegram ngay lập tức (Luồng Core)
    message_id = send_signals_alert(analysis, mtf_analysis)

    # 4. Đẩy phân tích đa khung thời gian và vị thế mở vào Queue cho Luồng AI xử lý ngầm
    open_positions = position_tracker.get_open_positions()
    ai_queue.put((analysis, mtf_analysis, open_positions, message_id))

async def fetch_and_analyze_open_positions_only():
    """Lấy dữ liệu và phân tích chỉ cho các coin đang có vị thế mở (quét khẩn cấp mỗi 5 phút). Không gọi AI."""
    open_positions = position_tracker.get_open_positions()
    if not open_positions:
        return
        
    coins_to_check = list(set([p["coin"] for p in open_positions]))
    console.print(f"[dim]Đang quét khẩn cấp các vị thế mở ({', '.join(coins_to_check)})...[/dim]")
    
    analysis = {}
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for coin in coins_to_check:
            tasks.append(_get_candles_for_coin(coin, "15m", session))
        res_15m = await asyncio.gather(*tasks)
        
        for i, coin in enumerate(coins_to_check):
            binance_candles = res_15m[i]
            ana = analyze_market(binance_candles)
            ana["close"] = binance_candles[-1]["close"] if (binance_candles and "error" not in binance_candles[0]) else 0.0
            analysis[f"{coin}:Binance"] = ana
            
    try:
        recs = position_tracker.evaluate_positions(analysis)
        if recs:
            send_position_recommendations(recs)
            await check_and_execute_auto_closes(recs)
    except Exception as e:
        console.print(f"[bold red]Lỗi khi đánh giá vị thế: {e}[/bold red]")

async def fetch_and_analyze_open_positions_only_with_retry():
    attempt = 0
    while attempt <= MAX_RETRIES:
        try:
            await fetch_and_analyze_open_positions_only()
            return
        except asyncio.CancelledError:
            raise
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            attempt += 1
            backoff = min(BASE_BACKOFF * (2 ** (attempt - 1)), MAX_BACKOFF)
            if attempt > MAX_RETRIES:
                return
            await asyncio.sleep(backoff)


async def fetch_and_display_with_retry():
    """
    Wrapper quanh fetch_and_display() với cơ chế retry + exponential backoff.
    Nếu lỗi mạng hoặc exception bất kỳ, tự động thử lại tối đa MAX_RETRIES lần.
    """
    attempt = 0
    while attempt <= MAX_RETRIES:
        try:
            await fetch_and_display()
            return  # Thành công → thoát
        except asyncio.CancelledError:
            raise
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
            await asyncio.sleep(backoff)


async def run_scheduler():
    """
    Vòng lặp scheduler có cơ chế tự restart nếu gặp lỗi bất ngờ.
    Chỉ dừng khi nhận KeyboardInterrupt (Ctrl+C) hoặc CancelledError.
    """
    from btc_scraper.telegram_bot import telegram_command_queue
    while True:
        try:
            # Xử lý các lệnh từ Telegram gửi xuống
            try:
                while not telegram_command_queue.empty():
                    cmd = telegram_command_queue.get_nowait()
                    if cmd == "scan":
                        console.print("[bold yellow]⚡ [Telegram Bot] Trực tiếp kích hoạt quét thị trường...[/bold yellow]")
                        asyncio.create_task(fetch_and_display_with_retry())
                    telegram_command_queue.task_done()
            except queue.Empty:
                pass

            schedule.run_pending()
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except KeyboardInterrupt:
            raise  # Truyền lên để main() xử lý
        except Exception as exc:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            console.print(
                f"\n[bold red][{timestamp}] Scheduler crash: {exc}[/bold red]\n"
                f"[dim]Restart scheduler sau {SCHEDULER_RESTART_WAIT}s...[/dim]\n"
            )
            await asyncio.sleep(SCHEDULER_RESTART_WAIT)
            # Tiếp tục vòng lặp while → tự restart


async def async_main():
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
    console.print(f"[dim]Coins: {', '.join(COINS)} | Nguồn: Binance (WebSocket) + Bybit + OKX[/dim]\n")
    console.print(
        f"[dim]Auto-restart: ON | Max retries: {MAX_RETRIES} | "
        f"Backoff: {BASE_BACKOFF}s-{MAX_BACKOFF}s[/dim]\n"
    )

    # ── Khởi tạo WebSocket Manager ────────────────────────────────────────────
    global _ws_manager
    try:
        _ws_manager = BinanceWebSocketManager(
            coins=COINS,
            on_candle_close=None,  # event-driven callback tùy chọn (hiện không bắt buộc)
        )
        await _ws_manager.bootstrap_rest()   # Load 210 nến lịch sử qua REST
        if not args.once:
            _ws_manager.connect()      # Bắt đầu WS thread nền
            console.print("[bold cyan]  [WebSocket] Binance Combined Stream đã kết nối.[/bold cyan]\n")
        else:
            console.print("[dim]  [WebSocket] Chế độ --once: bỏ qua WS, dùng REST data.[/dim]\n")
    except Exception as ws_err:
        console.print(f"[bold red]  [WebSocket] Lỗi khởi động WS, sẽ dùng REST fallback: {ws_err}[/bold red]\n")
        _ws_manager = None
    # ──────────────────────────────────────────────────────────────────────────

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
            schedule.every().hour.at(f":{m:02d}").do(lambda: asyncio.create_task(fetch_and_display_with_retry()))
            
        for m in focused_minutes:
            schedule.every().hour.at(f":{m:02d}").do(lambda: asyncio.create_task(fetch_and_analyze_open_positions_only_with_retry()))

        # ── WebSocket Watchdog (fallback guard) ───────────────────────────────
        def ws_watchdog():
            """Kiểm tra WS health mỗi 20 phút. Nếu unhealthy → chạy REST fallback ngay."""
            if _ws_manager is not None and not _ws_manager.check_health():
                console.print("[bold yellow]  [WS Watchdog] WS không healthy → chạy REST fallback ngay.[/bold yellow]")
                asyncio.create_task(fetch_and_display_with_retry())

        schedule.every(20).minutes.do(ws_watchdog)
        # ─────────────────────────────────────────────────────────────────────

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
    await fetch_and_display_with_retry()

    if args.once:
        # Nếu chỉ chạy 1 lần, đợi hàng đợi AI hoàn thành trước khi thoát
        if not ai_queue.empty():
            console.print("\n[dim]Đang đợi AI Worker hoàn thành phân tích...[/dim]")
            ai_queue.join()
        return

    # Khởi động listener Telegram nhận lệnh từ người dùng
    listener = threading.Thread(target=start_telegram_listener, daemon=True)
    listener.start()

    try:
        await run_scheduler()
    except KeyboardInterrupt:
        console.print("\n[bold red]Đã dừng.[/bold red]")


def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        console.print("\n[bold red]Đã dừng.[/bold red]")

if __name__ == "__main__":
    main()
