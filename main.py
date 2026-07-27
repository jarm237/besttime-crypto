"""
Multi-coin OHLCV Scraper - Entry point
Cào dữ liệu nến 15m đa coin từ Binance, Bybit, OKX
Tính toán chỉ số kỹ thuật và in bảng tổng hợp tín hiệu Mua/Bán.
"""

from dotenv import load_dotenv
load_dotenv()
import sys
import argparse
import time
import schedule
from rich.console import Console
from rich.panel import Panel

import os
import queue
import threading
import asyncio
import aiohttp
import subprocess

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
from btc_scraper.core.paths import build_data_path, build_logs_path, build_scripts_path
from btc_scraper.core.runtime_ownership import RuntimeLock, audit_runtime_lock_bypass, runtime_lock_disabled
from btc_scraper.core.fear_greed import resolve_fear_greed_value
from btc_scraper.trading import position_tracker
from btc_scraper.core.candle_store import candle_store
from btc_scraper.exchanges.binance_ws import BinanceWebSocketManager
from btc_scraper.ml_engine.causal_startup import initialize_causal_system_at_startup
from btc_scraper.collectors.macro_collector import load_macro_state, fetch_and_save_macro
from btc_scraper.collectors.alternative_scheduler import AlternativeDataScheduler
from btc_scraper.collectors.alternative_quality import CollectorHealthMonitor, DataQualityDashboard
from btc_scraper.collectors.alternative_data import load_alternative_data


console = Console()


def _resolve_analysis_fear_greed(analysis: dict) -> float:
    sentiment = analysis.get("sentiment") or {}
    return resolve_fear_greed_value(
        sentiment.get("raw_value"),
        analysis.get("fear_greed"),
        default=50.0,
    )

# ─── Auto-restart config ─────────────────────────────────────────────────────
MAX_RETRIES = 5               # Số lần retry tối đa liên tiếp trước khi bỏ cuộc
BASE_BACKOFF = 10             # Thời gian chờ ban đầu (giây) khi gặp lỗi
MAX_BACKOFF = 300             # Thời gian chờ tối đa (giây) = 5 phút
SCHEDULER_RESTART_WAIT = 15  # Thời gian chờ (giây) trước khi restart scheduler
# ─────────────────────────────────────────────────────────────────────────────


# ─── Queue & Background AI Worker ─────────────────────────────────────────────
ai_queue: queue.Queue = queue.Queue()
shutdown_event = threading.Event()
shutdown_event_async = None  # Will be initialized in async_main
managed_processes: list[subprocess.Popen] = []
runtime_lock: RuntimeLock | None = None


def _track_process(proc: subprocess.Popen) -> None:
    managed_processes.append(proc)


def _cleanup_managed_processes() -> None:
    for proc in list(managed_processes):
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
    managed_processes.clear()


def ai_worker():
    """
    Background worker nhặt dữ liệu phân tích từ hàng đợi, gọi Gemini AI và 
    gửi reply nhận định lên Telegram mà không ảnh hưởng tới luồng Core.
    """
    while True:
        if shutdown_event.is_set():
            break
        try:
            item = ai_queue.get(timeout=1)
        except queue.Empty:
            continue
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
            import json, time
            from btc_scraper.core.utils import write_atomic
            output_path = build_data_path("latest_ai_analysis.json")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(str(output_path), {"timestamp": time.time(), "report": ai_report})
                
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

                    # Thực hiện lệnh đặt đóng trên exchange qua ExecutionEngine (Phase 1: không gọi CCXTClient trực tiếp)
                    note = auto_pos[0].get("note", "")
                    mode = "TESTNET" if "TESTNET" in note else ("LIVE" if "LIVE" in note else "DRY_RUN")
                    if mode in ("TESTNET", "LIVE"):
                        try:
                            direction = auto_pos[0].get("direction")
                            invested_usdt = auto_pos[0].get("invested_usdt", 0.0)
                            entry_price_pos = auto_pos[0].get("entry_price", 0.0)
                            if entry_price_pos > 0:
                                close_result = await auto_trader.close_position_on_exchange(
                                    coin=coin,
                                    direction=direction,
                                    invested_usdt=invested_usdt,
                                    entry_price=entry_price_pos,
                                    current_price=current_price,
                                )
                                if close_result.get("status") == "error":
                                    console.print(f"[bold red][AutoTrade] Loi dong lenh tren san: {close_result.get('error')}[/bold red]")
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

# ── Causal System singleton — khởi tạo một lần trong async_main() ─────────────
_CAUSAL_COMPONENTS: dict = {}

# ── Alternative Data Scheduler & Health Monitor ───────────────────────────────
_alt_data_scheduler: AlternativeDataScheduler | None = None
_alt_health_monitor: CollectorHealthMonitor | None = None


def _send_alt_data_telegram_alert(alert) -> None:
    """Forward critical alternative-data quality alerts to Telegram."""
    try:
        if alert.level == "critical":
            from btc_scraper.telegram_bot import send_telegram_message
            msg = f"⚠️ [ALT DATA] {alert.source}: {alert.message}"
            send_telegram_message(msg, parse_mode=None)
    except Exception:
        pass  # Never crash the monitor callback


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


async def _run_causal_runtime_pass(
    state_payload: dict | None = None,
    causal_components: dict | None = None,
) -> dict:
    """Execute the causal runtime analysis pass using pre-initialized causal components."""
    try:
        from btc_scraper.core.world_state import WorldState, get_world_state_manager, MarketRegime, LiquidityRegime
        from btc_scraper.ml_engine.world_model_predictor import WorldModelPredictor
        from btc_scraper.ml_engine.causal_anomaly_detector import CausalAnomalyDetector
        from btc_scraper.ml_engine.agents.macro_agent import MacroAgent
        from btc_scraper.ml_engine.agents.liquidity_agent import LiquidityAgent
        from btc_scraper.ml_engine.agents.sentiment_agent import SentimentAgent
        from btc_scraper.ml_engine.agents.consensus_engine import CausalConsensusEngine

        # Dùng singleton đã khởi tạo từ async_main() — không gọi lại mỗi chu kỳ
        components = causal_components or _CAUSAL_COMPONENTS

        manager = get_world_state_manager()
        state = state_payload or {}
        macro_state = load_macro_state()
        world_state = WorldState(timestamp=__import__('datetime').datetime.now(__import__('datetime').timezone.utc))
        world_state.regime = MarketRegime.RISK_ON if state.get("signal") == "bullish" else MarketRegime.RISK_OFF
        world_state.liquidity_regime = LiquidityRegime.NORMAL
        world_state.macro.DXY = float(state.get("macro", {}).get("DXY", macro_state.get("DXY", 100.0)))
        world_state.macro.RealYield = float(state.get("macro", {}).get("RealYield", 0.0))
        world_state.macro.VIX = float(state.get("macro", {}).get("VIX", macro_state.get("VIX", 20.0)))
        world_state.macro.BondYield = float(macro_state.get("BondYield", 4.5))
        world_state.liquidity.BTC_Funding = float(state.get("liquidity", {}).get("BTC_Funding", 0.0))
        world_state.liquidity.OI_Delta = float(state.get("liquidity", {}).get("OI_Delta", 0.0))
        world_state.crypto.BTC_Price = float(state.get("crypto", {}).get("BTC_Price", 0.0))
        world_state.sentiment.FearGreed = float(state.get("sentiment", {}).get("FearGreed", 50.0))
        manager.update_state(world_state)

        predictor = components.get("predictor") or WorldModelPredictor(graph_path="data/causal_graph.json")
        anomaly_detector = components.get("anomaly_detector") or CausalAnomalyDetector()
        consensus_engine = components.get("consensus_engine") or CausalConsensusEngine(graph_path="data/causal_graph.json")

        prediction = predictor.predict_next_state(world_state)
        anomaly = anomaly_detector.detect(world_state, prediction)
        reports = [
            MacroAgent().assess(world_state),
            LiquidityAgent().assess(world_state),
            SentimentAgent().assess(world_state),
        ]
        consensus = consensus_engine.decide(world_state, reports)

        return {
            "prediction": prediction,
            "anomaly": anomaly,
            "consensus": consensus,
        }
    except Exception as exc:
        console.print(f"[dim yellow]Causal runtime pass skipped: {exc}[/dim yellow]")
        return {}


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

    try:
        # Phase A fix: đọc đúng key "BTC:Binance" và lấy fear_greed từ đúng path
        btc_ana = analysis.get("BTC:Binance", {})
        fear_greed = _resolve_analysis_fear_greed(btc_ana)
        macro_state = load_macro_state()
        causal_payload = {
            "signal": btc_ana.get("signal", "neutral"),
            "macro": {
                "DXY": float(macro_state.get("DXY", 100.0)),
                "RealYield": 0.0,
                "VIX": float(macro_state.get("VIX", 20.0)),
            },
            "liquidity": {
                "BTC_Funding": float(btc_ana.get("funding_rate") or btc_ana.get("funding") or 0.0),
                "OI_Delta":    float(btc_ana.get("oi_delta") or 0.0),
            },
            "crypto": {
                "BTC_Price": float(btc_ana.get("close", 0.0)),
            },
            "sentiment": {
                "FearGreed": fear_greed,
            },
        }
        causal_result = await _run_causal_runtime_pass(causal_payload, _CAUSAL_COMPONENTS)

        # Phase B: dùng causal output để tác động vào analysis + log
        if causal_result:
            is_anomaly      = causal_result.get("anomaly", {}).get("is_anomaly", False)
            consensus_sig   = causal_result.get("consensus", {}).get("signal", "neutral")
            deviation_score = causal_result.get("anomaly", {}).get("deviation_score", 0.0)

            console.print(
                f"[dim cyan]Causal: consensus={consensus_sig} | "
                f"anomaly={is_anomaly} (score={deviation_score:.3f})[/dim cyan]"
            )

            # Đánh dấu causal_anomaly_warning vào signal_score của tất cả coin
            if is_anomaly:
                console.print("[bold red]⚠️  [Causal] Structural anomaly detected — thêm cảnh báo vào tín hiệu.[/bold red]")
                warning_tag = "⚠ CAUSAL ANOMALY"
                for _key in analysis:
                    _ana = analysis[_key]
                    _sig_score = analysis[_key].get("signal_score") or {}
                    _action = str(_sig_score.get("action") or "").upper()
                    _signal_text = str(_ana.get("signal", "") or "")
                    _signal_text_upper = _signal_text.upper()
                    _is_actionable_signal = (
                        _action in ("BUY", "SELL")
                        or (
                            "NEUTRAL" not in _signal_text_upper
                            and any(token in _signal_text_upper for token in ("BUY", "SELL", "LONG", "SHORT"))
                        )
                    )

                    if _is_actionable_signal:
                        _sig_score["causal_anomaly_warning"] = True
                        _sig_score["causal_deviation_score"] = deviation_score
                        _ana["signal_score"] = _sig_score

                        # Gắn cảnh báo trực tiếp vào signal để hiển thị rõ trên mọi kênh.
                        if warning_tag not in _signal_text:
                            _ana["signal"] = f"{_signal_text} | {warning_tag}" if _signal_text else warning_tag

            # Log warning khi consensus causal ngược chiều tín hiệu kỹ thuật
            if consensus_sig == "bearish":
                buy_coins = [k.split(":")[0] for k, v in analysis.items() if "BUY" in str(v.get("signal", ""))]
                if buy_coins:
                    console.print(f"[yellow]⚠️  [Causal] Consensus=BEARISH nhưng có BUY signal: {buy_coins}[/yellow]")
            elif consensus_sig == "bullish":
                sell_coins = [k.split(":")[0] for k, v in analysis.items() if "SELL" in str(v.get("signal", ""))]
                if sell_coins:
                    console.print(f"[yellow]⚠️  [Causal] Consensus=BULLISH nhưng có SELL signal: {sell_coins}[/yellow]")
    except Exception as causal_exc:
        console.print(f"[dim yellow]Causal runtime hook skipped: {causal_exc}[/dim yellow]")

    # ── Alternative Data quality check & summary ──────────────────────────
    try:
        if _alt_health_monitor is not None:
            alt_payload = load_alternative_data()
            _alt_health_monitor.record_collection("alternative_data", alt_payload, success=True)
            _risk_on = float(alt_payload.get("risk_on_score", 0.0))
            _macro_p = float(alt_payload.get("macro_pressure", 0.0))
            _funding_p = float(alt_payload.get("funding_pressure", 0.0))
            console.print(
                f"[dim cyan]Alt Data: risk_on={_risk_on:.2f} | "
                f"macro_pressure={_macro_p:.2f} | "
                f"funding_pressure={_funding_p:.3f}[/dim cyan]"
            )
    except Exception as alt_exc:
        console.print(f"[dim yellow]Alt Data check skipped: {alt_exc}[/dim yellow]")
    # ─────────────────────────────────────────────────────────────────────

    # Hiển thị bảng giá & chỉ báo ở Terminal
    print_all(results, analysis)

    # Lưu lại signals mới nhất để Web Dashboard đọc
    try:
        import json
        from btc_scraper.core.utils import write_atomic
        output_path = build_data_path("latest_signals.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(str(output_path), {"analysis": analysis, "mtf_analysis": mtf_analysis})
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
            ana = analyze_market(binance_candles, coin)
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
    from btc_scraper.telegram_bot.api import send_telegram_message
    telegram_scan_task = None
    while not shutdown_event_async.is_set():
        try:
            # Xử lý các lệnh từ Telegram gửi xuống
            try:
                while not telegram_command_queue.empty():
                    cmd = telegram_command_queue.get_nowait()
                    command_name = cmd.get("command") if isinstance(cmd, dict) else cmd
                    if command_name == "scan":
                        if telegram_scan_task is None or telegram_scan_task.done():
                            console.print("[bold yellow]⚡ [Telegram Bot] Trực tiếp kích hoạt quét thị trường...[/bold yellow]")
                            telegram_scan_task = asyncio.create_task(fetch_and_display_with_retry())
                        elif isinstance(cmd, dict):
                            send_telegram_message(
                                "⏳ Hệ thống đang quét thị trường. Vui lòng chờ kết quả hiện tại.",
                                chat_id=cmd.get("chat_id"),
                                reply_to_message_id=cmd.get("reply_to_id"),
                            )
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
    global shutdown_event_async
    shutdown_event_async = asyncio.Event()

    import signal
    loop = asyncio.get_running_loop()
    def _signal_handler():
        console.print("\n[bold red]Nhận tín hiệu dừng (SIGINT/SIGTERM). Bắt đầu Graceful Shutdown...[/bold red]")
        shutdown_event_async.set()
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

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
    global _ws_manager, _CAUSAL_COMPONENTS
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

    # ── Khởi tạo collector macro và Causal System (singleton) ───────────────
    try:
        fetch_and_save_macro()
        console.print("[bold cyan]  [Macro Collector] Cập nhật macro state thành công.[/bold cyan]\n")
    except Exception as macro_err:
        console.print(f"[dim yellow]  [Macro Collector] Bỏ qua cập nhật macro: {macro_err}[/dim yellow]\n")

    try:
        _CAUSAL_COMPONENTS = initialize_causal_system_at_startup({
            "graph_path": "data/causal_graph.json",
            "rules_path": "data/context_rules.json",
        })
        console.print("[bold green]  [Causal System] Khởi tạo thành công.[/bold green]\n")
    except Exception as causal_init_err:
        console.print(f"[bold yellow]  [Causal System] Lỗi khởi tạo, chạy không có causal context: {causal_init_err}[/bold yellow]\n")
        _CAUSAL_COMPONENTS = {}
    # ──────────────────────────────────────────────────────────────────────────

    # ── Khởi tạo Alternative Data Scheduler & Quality Monitor ──────────────
    global _alt_data_scheduler, _alt_health_monitor
    try:
        _alt_health_monitor = CollectorHealthMonitor(
            dashboard=DataQualityDashboard(quality_log_path=str(build_data_path("alternative_quality.json"))),
            on_alert=_send_alt_data_telegram_alert,
        )
        _alt_data_scheduler = AlternativeDataScheduler(
            interval_seconds=max(60, FETCH_INTERVAL_MINUTES * 60),
            on_success=lambda payload: _alt_health_monitor.record_collection("alternative_data", payload, success=True),
            on_failure=lambda exc: _alt_health_monitor.record_collection("alternative_data", {}, success=False),
        )
        first_payload = _alt_data_scheduler.run_once(force=True)
        n_fields = sum(1 for k, v in first_payload.items() if k != "timestamp" and v != 0.0)
        console.print(
            f"[bold cyan]  [Alternative Data] Scheduler started "
            f"(interval={FETCH_INTERVAL_MINUTES * 60}s) | "
            f"First collection: {len(first_payload)} fields ({n_fields} non-zero)[/bold cyan]\n"
        )
        if not args.once:
            _alt_data_scheduler.start(daemon=True)
    except Exception as alt_err:
        console.print(f"[dim yellow]  [Alternative Data] Khởi tạo thất bại, bỏ qua: {alt_err}[/dim yellow]\n")
        _alt_data_scheduler = None
        _alt_health_monitor = None
    # ──────────────────────────────────────────────────────────────────────────

    # Hiển thị trạng thái Meta Model khi khởi động
    try:
        import os, json as _json
        meta_metric_path = str(build_logs_path("meta_model.json"))

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
            console.print("[bold yellow]Đang chạy Weekly Report...[/bold yellow]")
            proc = subprocess.Popen([sys.executable, str(build_scripts_path("weekly_job.py"))])
            _track_process(proc)
            
        def run_continuous_learning_job():
            console.print("[bold yellow]Đang chạy Continuous Learning Pipeline...[/bold yellow]")
            proc = subprocess.Popen([sys.executable, str(build_scripts_path("continuous_learning.py"))])
            _track_process(proc)

        schedule.every().sunday.at("23:30").do(run_continuous_learning_job)
        schedule.every().sunday.at("23:45").do(run_weekly_report_job)

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
        shutdown_event.set()
        ai_queue.put(None)
        _cleanup_managed_processes()
        return

    # Khởi động listener Telegram nhận lệnh từ người dùng
    listener = threading.Thread(target=start_telegram_listener, daemon=True)
    listener.start()

    try:
        await run_scheduler()
    except KeyboardInterrupt:
        console.print("\n[bold red]Đã dừng.[/bold red]")
    finally:
        shutdown_event.set()
        ai_queue.put(None)
        if _alt_data_scheduler is not None:
            _alt_data_scheduler.stop(timeout=5.0)
        _cleanup_managed_processes()


def main():
    global runtime_lock
    try:
        if runtime_lock_disabled():
            bypass = audit_runtime_lock_bypass()
            console.print(
                "[bold red]CRITICAL: Runtime lock bypass enabled. "
                f"environment={bypass['environment']} deployment_id={bypass['deployment_id']} "
                f"runtime_id={bypass['runtime_id']} reason={bypass['reason']}[/bold red]"
            )
        else:
            runtime_lock = RuntimeLock()
            lock_info = runtime_lock.acquire()
            console.print(
                "[dim]Runtime lock acquired: "
                f"{lock_info['environment']}/{lock_info['deployment_id']} "
                f"runtime_id={lock_info['runtime_id']}[/dim]"
            )
        asyncio.run(async_main())
    except KeyboardInterrupt:
        console.print("\n[bold red]Đã dừng.[/bold red]")
    finally:
        shutdown_event.set()
        ai_queue.put(None)
        _cleanup_managed_processes()
        if runtime_lock is not None:
            runtime_lock.release()
            runtime_lock = None

if __name__ == "__main__":
    main()
