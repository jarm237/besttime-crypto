"""
Display module - Hien thi du lieu OHLCV va chi bao ky thuat (RSI, EMA) cho nhieu coin
"""

from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

console = Console()


def _candle_arrow(open_: float, close: float) -> str:
    """Nen tang hay giam."""
    if close >= open_:
        return "UP"
    return "DN"


def _candle_style(open_: float, close: float) -> str:
    """Mau sac tuy theo nen tang/giam."""
    return "bright_green" if close >= open_ else "bright_red"


def make_ohlcv_table(exchange_name: str, coin: str, candles: list[dict], color: str) -> Table:
    """Tao bang Rich hien thi du lieu OHLCV va chi bao."""
    table = Table(
        title=f"[bold {color}]{exchange_name}[/] -- [bold yellow]{coin}/USDT[/] 15m (5 nến gần nhất)",
        box=box.ROUNDED,
        border_style=color,
        header_style=f"bold {color}",
        show_lines=True,
    )

    table.add_column("Time",    style="dim", width=17)
    table.add_column("Open",    justify="right", width=12)
    table.add_column("High",    justify="right", width=12)
    table.add_column("Low",     justify="right", width=12)
    table.add_column("Close",   justify="right", width=12)
    table.add_column("EMA9",    justify="right", width=12, style="cyan")
    table.add_column("EMA21",   justify="right", width=12, style="magenta")
    table.add_column("RSI14",   justify="right", width=8)
    table.add_column("+/-",     width=3)

    if not candles:
        table.add_row("[italic red]Khong co du lieu[/]", *["-"] * 7, "")
        return table

    if "error" in candles[0]:
        table.add_row(f"[red]Loi: {candles[0]['error']}[/]", *["-"] * 7, "")
        return table

    # Chi lay 5 nến cuối để hiển thị tránh đầy terminal
    display_candles = candles[-5:]

    for c in display_candles:
        style = _candle_style(c["open"], c["close"])
        arrow = _candle_arrow(c["open"], c["close"])
        
        rsi_val = c.get("rsi", 50.0)
        rsi_style = "white"
        if rsi_val < 30:
            rsi_style = "bold bright_green"
        elif rsi_val > 70:
            rsi_style = "bold bright_red"
            
        ema9 = c.get("ema9", 0.0)
        ema21 = c.get("ema21", 0.0)
        
        # Format giá trị (đặc biệt các coin nhỏ cần nhiều số thập phân hơn, ví dụ ZEC/SOL)
        val_format = ",.4f" if c['close'] < 10 else ",.2f"
        
        table.add_row(
            c["time"],
            f"{c['open']:{val_format}}",
            f"{c['high']:{val_format}}",
            f"{c['low']:{val_format}}",
            f"[{style}]{c['close']:{val_format}}[/]",
            f"{ema9:{val_format}}" if ema9 > 0 else "-",
            f"{ema21:{val_format}}" if ema21 > 0 else "-",
            f"[{rsi_style}]{rsi_val:.1f}[/]",
            f"[{style}]{arrow}[/]",
        )

    return table


def make_signal_table(analysis_results: dict[str, dict]) -> Table:
    """Tạo bảng tổng hợp tín hiệu Mua/Bán trên toàn bộ các coin và sàn giao dịch"""
    table = Table(
        title="[bold yellow]BANG TIN HIEU KHUYEN NGHI MUA/BAN TONG HOP[/]",
        box=box.DOUBLE_EDGE,
        border_style="yellow",
        header_style="bold yellow",
        show_lines=True,
    )
    
    table.add_column("Coin",         style="bold yellow")
    table.add_column("San")
    table.add_column("Gia Close",    justify="right")
    table.add_column("RSI",          justify="center")
    table.add_column("Tin Hieu",     justify="center")
    table.add_column("Stop Loss",    justify="right", style="bright_red")
    table.add_column("TP1 (R:R)",    justify="right", style="bright_green")
    table.add_column("TP2 (R:R)",    justify="right", style="bright_green")
    table.add_column("Ly Do Chi Tiet")
    
    from btc_scraper.ml_engine.signal_score import extract_signal_fields
    for key, ana in analysis_results.items():
        coin, exchange = key.split(":")
        sig_fields = extract_signal_fields(ana)
        sig = ana.get("signal", sig_fields.get("raw", ""))

        sig_score = ana.get("signal_score", {}) or {}
        display_label = sig_score.get("display_label")
        display_score = sig_score.get("display_score")
        confidence = sig_score.get("confidence")
        meta_pct = sig_score.get("meta_confidence_pct")

        # --- Đồng bộ với Telegram: áp dụng low_conviction (STRONG → WEAK) ---
        sig_for_display = str(sig)
        try:
            score_num = float(display_score) if display_score is not None else None
        except Exception:
            score_num = None
        low_conviction = (confidence == "LOW") or (score_num is not None and score_num < 60)
        if low_conviction:
            up = sig_for_display.upper()
            if "STRONG BUY" in up:
                sig_for_display = sig_for_display.replace("STRONG BUY", "WEAK BUY").replace("Strong Buy", "Weak Buy").replace("strong buy", "weak buy")
            elif "STRONG SELL" in up:
                sig_for_display = sig_for_display.replace("STRONG SELL", "WEAK SELL").replace("Strong Sell", "Weak Sell").replace("strong sell", "weak sell")

        # Fallback for old data without display_label
        if display_label is None:
            score_val = sig_score.get("score")
            action = sig_score.get("action", "NEUTRAL")
            if score_val is not None:
                if action == "BUY":
                    display_label = f"BUY {score_val}%"
                elif action == "SELL":
                    display_label = f"SELL {100 - score_val}%"
                else:
                    display_label = "NEUTRAL"
        if display_label and confidence and display_label != "NEUTRAL":
            score_suffix = f" [{display_label} {confidence}]"
        elif display_label == "NEUTRAL":
            score_suffix = " [→ NEUTRAL]"
        else:
            score_suffix = ""

        # --- Đồng bộ với Telegram: badge Meta confidence ---
        if meta_pct is not None:
            if meta_pct >= 70:
                meta_badge = f" [bright_green]Meta:{meta_pct}%[/bright_green]"
            elif meta_pct >= 50:
                meta_badge = f" [yellow]Meta:{meta_pct}%[/yellow]"
            else:
                meta_badge = f" [red]Meta:{meta_pct}%[/red]"
        else:
            meta_badge = ""

        # Color signal (dùng sig_for_display đã điều chỉnh low_conviction)
        sig_styled = f"[white]{sig_for_display}[/]"
        if "STRONG BUY" in sig_for_display.upper() or ("BUY" in sig_for_display.upper() and "WEAK" not in sig_for_display.upper()):
            sig_styled = f"[bold bright_green]{sig_for_display}{score_suffix}[/]{meta_badge}"
        elif "WEAK BUY" in sig_for_display.upper() or "BUY" in sig_for_display.upper():
            sig_styled = f"[bright_green]{sig_for_display}{score_suffix}[/]{meta_badge}"
        elif "STRONG SELL" in sig_for_display.upper() or ("SELL" in sig_for_display.upper() and "WEAK" not in sig_for_display.upper()):
            sig_styled = f"[bold bright_red]{sig_for_display}{score_suffix}[/]{meta_badge}"
        elif "WEAK SELL" in sig_for_display.upper() or "SELL" in sig_for_display.upper():
            sig_styled = f"[bright_red]{sig_for_display}{score_suffix}[/]{meta_badge}"
        elif "NEUTRAL" in sig_for_display.upper():
            sig_styled = f"[bold yellow]{sig_for_display}{score_suffix}[/]{meta_badge}"
            
        close_val = ana.get('close', 0.0)
        val_format = ",.4f" if close_val < 10 else ",.2f"
        close_str = f"{close_val:{val_format}}" if close_val > 0 else "-"
        
        tp_sl = ana.get("tp_sl", {})
        sl_val = tp_sl.get("sl", 0.0)
        tp1_val = tp_sl.get("tp1", 0.0)
        tp2_val = tp_sl.get("tp2", 0.0)
        rr1_val = tp_sl.get("rr1", 0.0)
        rr2_val = tp_sl.get("rr2", 0.0)
        
        sl_str = f"{sl_val:{val_format}}" if sl_val > 0 else "-"
        tp1_str = f"{tp1_val:{val_format}} ({rr1_val})" if tp1_val > 0 else "-"
        tp2_str = f"{tp2_val:{val_format}} ({rr2_val})" if tp2_val > 0 else "-"
            
        table.add_row(
            coin,
            exchange,
            close_str,
            f"{ana['rsi']:.1f}",
            sig_styled,
            sl_str,
            tp1_str,
            tp2_str,
            ana["reason"]
        )
        
    return table


def make_min_capital_table(analysis_results: dict[str, dict]) -> Table:
    """
    Tính vốn tối thiểu nên giao dịch cho mỗi coin dựa trên TP/SL % thực tế
    so sánh với phí Binance Spot (0.2% round-trip) và Futures (0.1% round-trip).
    Mục tiêu: phí giao dịch không vượt quá 20% lợi nhuận TP1.
    """
    FEE_SPOT = 0.20        # % round-trip Spot standard
    FEE_SPOT_BNB = 0.15   # % round-trip Spot có BNB
    FEE_FUTURES = 0.10    # % round-trip Futures taker
    TARGET_PROFIT_USD = 5.0  # lợi nhuận ròng mục tiêu tối thiểu ($)

    table = Table(
        title="[bold cyan]VỐN TỐI THIỂU NÊN GIAO DỊCH (theo phí Binance)[/]",
        box=box.ROUNDED,
        border_style="cyan",
        header_style="bold cyan",
        show_lines=True,
    )

    table.add_column("Coin",           style="bold yellow", justify="center")
    table.add_column("SL%",            justify="right")
    table.add_column("TP1%",           justify="right")
    table.add_column("Net TP1 (Spot)", justify="right")
    table.add_column("Min Spot ($)",   justify="right", style="bright_white")
    table.add_column("Min +BNB ($)",   justify="right", style="cyan")
    table.add_column("Min Futures ($)",justify="right", style="bright_green")
    table.add_column("Đánh giá",       justify="center")

    for key, ana in analysis_results.items():
        coin, _ = key.split(":")
        tp_sl = ana.get("tp_sl", {})
        entry = tp_sl.get("entry", 0.0)
        sl    = tp_sl.get("sl", 0.0)
        tp1   = tp_sl.get("tp1", 0.0)

        if entry <= 0 or sl <= 0 or tp1 <= 0:
            table.add_row(coin, "-", "-", "-", "-", "-", "-", "[dim]Thiếu dữ liệu[/dim]")
            continue

        sl_pct  = abs(entry - sl)  / entry * 100
        tp1_pct = abs(tp1  - entry) / entry * 100

        net_spot     = tp1_pct - FEE_SPOT
        net_spot_bnb = tp1_pct - FEE_SPOT_BNB
        net_futures  = tp1_pct - FEE_FUTURES

        def _min_usdt(net_pct: float) -> str:
            if net_pct <= 0:
                return "[red]Không hiệu quả[/red]"
            val = TARGET_PROFIT_USD / (net_pct / 100)
            return f"[bold]${val:,.0f}[/bold]"

        # Đánh giá hiệu quả phí
        fee_ratio = FEE_SPOT / tp1_pct * 100 if tp1_pct > 0 else 999
        if fee_ratio < 15:
            rating = "[bold bright_green]✅ Tốt[/]"
        elif fee_ratio < 30:
            rating = "[bold yellow]⚠️ Chấp nhận[/]"
        else:
            rating = "[bold red]❌ Phí cao[/]"

        net_str = f"{net_spot:+.3f}%" if net_spot > 0 else f"[red]{net_spot:+.3f}%[/red]"

        table.add_row(
            coin,
            f"{sl_pct:.3f}%",
            f"{tp1_pct:.3f}%",
            net_str,
            _min_usdt(net_spot),
            _min_usdt(net_spot_bnb),
            _min_usdt(net_futures),
            rating,
        )

    # Chú thích
    table.caption = (
        f"[dim]Phí Spot: 0.1%/lệnh (0.2% round-trip) | Spot+BNB: 0.075% (0.15%) | "
        f"Futures taker: 0.05% (0.1%) | Mục tiêu lãi ròng ≥ ${TARGET_PROFIT_USD:.0f}/lệnh[/dim]"
    )
    return table


def print_all(results: dict[str, dict[str, list[dict]]], analysis_results: dict[str, dict]):
    """
    In dữ liệu phân tích.
    results dạng: { "BTC": {"Binance": [...], "Bybit": [...]}, "ETH": ... }
    analysis_results dạng: { "BTC:Binance": {...}, "BTC:Bybit": {...} }
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    console.print()
    console.print(Panel(
        Text(f"THEO DOI THI TRUONG | Nen 15m & Tinh hieu Mua/Ban | Cap nhat: {now}", justify="center", style="bold white"),
        border_style="yellow",
        expand=True,
    ))

    # Hỏi người dùng xem chi tiết các nến bằng cách in mẫu nến của 1 coin tiêu biểu (tránh tràn terminal)
    # Ở đây chúng ta chỉ show bảng chi tiết nến của coin đầu tiên (BTC) để terminal gọn gàng, hoặc show tất cả
    # Để đơn giản, ta show bảng nến của BTC và ETH
    exchange_colors = {
        "Binance": "yellow",
        "Bybit":   "cyan",
        "OKX":     "magenta",
    }

    console.print("[bold white]Chi tiet cac nen cua BTC/USDT & ETH/USDT:[/bold white]")
    for coin in ["BTC", "ETH"]:
        if coin in results:
            for exchange, candles in results[coin].items():
                color = exchange_colors.get(exchange, "white")
                table = make_ohlcv_table(exchange, coin, candles, color)
                console.print(table)
                console.print()

    console.rule("[dim]Cap nhat tiep theo sau 5 phut...[/dim]")

    # In bảng khuyến nghị tổng hợp lên hàng đầu để người dùng dễ quan sát nhanh
    signal_table = make_signal_table(analysis_results)
    console.print(signal_table)
    console.print()

    # In bảng vốn tối thiểu khuyến nghị
    min_cap_table = make_min_capital_table(analysis_results)
    console.print(min_cap_table)
    console.print()
