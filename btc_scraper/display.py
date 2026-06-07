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
    
    for key, ana in analysis_results.items():
        coin, exchange = key.split(":")
        sig = ana["signal"]
        
        # Color signal
        sig_styled = f"[white]{sig}[/]"
        if "STRONG BUY" in sig or "BUY" in sig:
            sig_styled = f"[bold bright_green]{sig}[/]"
        elif "STRONG SELL" in sig or "SELL" in sig:
            sig_styled = f"[bold bright_red]{sig}[/]"
        elif "NEUTRAL" in sig:
            sig_styled = f"[bold yellow]{sig}[/]"
            
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


def make_missed_signals_table(analysis_results: dict[str, dict]) -> Table | None:
    """Tạo bảng các tín hiệu mua/bán có thể đã bị bỏ qua trong 15-30 phút qua"""
    # Gom tất cả các missed_signals của các coin lại
    all_missed = []
    for key, ana in analysis_results.items():
        coin, exchange = key.split(":")
        for ms in ana.get("missed_signals", []):
            all_missed.append((coin, exchange, ms, ana.get("close", 0.0)))
            
    if not all_missed:
        return None
        
    table = Table(
        title="[bold orange3]CAC TIN HIEU CO THE DA BI BO QUA (15 - 30 PHUT TRUOC)[/]",
        box=box.DOUBLE_EDGE,
        border_style="orange3",
        header_style="bold orange3",
        show_lines=True,
    )
    
    table.add_column("Coin", style="bold yellow")
    table.add_column("San")
    table.add_column("Thoi Gian", justify="center")
    table.add_column("Do Tre", justify="center")
    table.add_column("Tin Hieu", justify="center")
    table.add_column("Entry Cu", justify="right")
    table.add_column("Gia Hien Tai", justify="right", style="cyan")
    table.add_column("Stop Loss", justify="right", style="bright_red")
    table.add_column("TP1 / TP2 (R:R)", justify="right", style="bright_green")
    table.add_column("Trang Thai", justify="center")
    
    for coin, exchange, ms, current_close in all_missed:
        sig = ms["signal"]
        
        # Color signal
        sig_styled = f"[white]{sig}[/]"
        if "STRONG BUY" in sig or "BUY" in sig:
            sig_styled = f"[bold bright_green]{sig}[/]"
        elif "STRONG SELL" in sig or "SELL" in sig:
            sig_styled = f"[bold bright_red]{sig}[/]"
            
        val_format = ",.4f" if ms["entry"] < 10 else ",.2f"
        entry_str = f"{ms['entry']:{val_format}}"
        current_str = f"{current_close:{val_format}}" if current_close > 0 else "-"
        
        tp_sl = ms["tp_sl"]
        sl_val = tp_sl.get("sl", 0.0)
        tp1_val = tp_sl.get("tp1", 0.0)
        tp2_val = tp_sl.get("tp2", 0.0)
        rr1_val = tp_sl.get("rr1", 0.0)
        rr2_val = tp_sl.get("rr2", 0.0)
        
        sl_str = f"{sl_val:{val_format}}" if sl_val > 0 else "-"
        tp_str = f"{tp1_val:{val_format}} ({rr1_val}) / {tp2_val:{val_format}} ({rr2_val})"
        
        # Color status
        status = ms["status"]
        status_styled = f"[white]{status}[/]"
        if "Hit TP" in status:
            status_styled = f"[bold bright_green]{status}[/]"
        elif "Hit SL" in status:
            status_styled = f"[bold bright_red]{status}[/]"
        elif "Running" in status:
            status_styled = f"[bold yellow]{status}[/]"
            
        table.add_row(
            coin,
            exchange,
            ms["time"].split(" ")[1] if " " in ms["time"] else ms["time"],  # chỉ lấy giờ phút
            f"{ms['age_minutes']}p truoc",
            sig_styled,
            entry_str,
            current_str,
            sl_str,
            tp_str,
            status_styled
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

    # In bảng các tín hiệu bỏ lỡ
    missed_table = make_missed_signals_table(analysis_results)
    if missed_table:
        console.print(missed_table)
        console.print()
    else:
        console.print("[dim]>> Khong co tin hieu Mua/Ban nao bi bo lo trong 30 phut qua.[/dim]\n")
