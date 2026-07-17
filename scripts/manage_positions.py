#!/usr/bin/env python3
"""
CLI tool để quản lý các vị thế thủ công.
Dùng để thêm lệnh, đóng lệnh và xem hiệu suất của chiến lược giao dịch.
"""

import sys
import os
import argparse
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Thêm đường dẫn project vào sys.path để import được btc_scraper
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from btc_scraper.trading import position_tracker

console = Console()

def cmd_add(args):
    try:
        pos = position_tracker.add_position(
            coin=args.coin,
            entry_price=args.entry_price,
            direction=args.direction,
            note=args.note,
            trade_origin="manual",
            execution_mode="manual",
            created_by="manage_positions_cli",
            order_creator="user",
            order_channel="cli",
            manual_decision_basis=args.manual_decision_basis,
        )
        console.print(f"\n[bold green]✅ Đã thêm vị thế MỚI:[/bold green]")
        console.print(pos)
    except ValueError as e:
        console.print(f"\n[bold red]❌ Lỗi: {e}[/bold red]")

def cmd_close(args):
    try:
        pos = position_tracker.close_position(
            coin=args.coin,
            sell_price=args.sell_price
        )
        console.print(f"\n[bold green]✅ Đã ĐÓNG vị thế:[/bold green]")
        
        # In kết quả đẹp
        pnl = pos['pnl_pct']
        color = "green" if pnl > 0 else "red"
        console.print(f"Coin: {pos['coin']} | Hướng: {pos['direction']}")
        console.print(f"Entry: {pos['entry_price']} -> Exit: {pos['sell_price']}")
        console.print(f"P&L: [{color}]{pnl:+.2f}% (R-mult: {pos.get('r_multiplier')})[/{color}]")
        console.print(f"Kết quả: {pos['result']} (Giữ: {pos['hold_hours']}h)")
    except ValueError as e:
        console.print(f"\n[bold red]❌ Lỗi: {e}[/bold red]")

def cmd_list(args):
    positions = position_tracker.get_open_positions()
    if not positions:
        console.print("\n[yellow]Không có vị thế nào đang mở.[/yellow]")
        return
        
    table = Table(title="Các Vị Thế Đang Mở")
    table.add_column("Coin", style="cyan")
    table.add_column("Hướng", style="magenta")
    table.add_column("Entry", justify="right")
    table.add_column("Nguồn", style="blue")
    table.add_column("Tín hiệu Gần Nhất", style="yellow")
    table.add_column("Giá Hiện Tại", justify="right")
    table.add_column("Ghi chú")
    
    for p in positions:
        table.add_row(
            p['coin'],
            p['direction'],
            str(p['entry_price']),
            position_tracker.format_order_provenance(p),
            str(p.get('last_signal', 'N/A')),
            str(p.get('last_price', 'N/A')),
            p.get('note', '')
        )
        
    console.print()
    console.print(table)

def cmd_perf(args):
    trade_type = args.type.upper() if hasattr(args, 'type') else "ALL"
    perf = position_tracker.get_performance_summary(trade_type)
    if "message" in perf:
        console.print(f"\n[yellow]{perf['message']}[/yellow]")
        return
        
    table = Table(title=f"Thống Kê Hiệu Suất Chiến Lược ({trade_type})")
    table.add_column("Chỉ Số", style="cyan")
    table.add_column("Giá Trị", style="bold")
    
    table.add_row("Tổng số lệnh", str(perf['total_trades']))
    table.add_row("Số lệnh Thắng/Thua", f"{perf['wins']} / {perf['losses']}")
    table.add_row("Win Rate", f"{perf['win_rate_pct']}%")
    table.add_row("Lãi trung bình (Win)", f"{perf['avg_win_pct']}%", style="green")
    table.add_row("Lỗ trung bình (Loss)", f"{perf['avg_loss_pct']}%", style="red")
    table.add_row("Profit Factor", str(perf['profit_factor']))
    
    avg_r = perf['avg_r_multiplier']
    table.add_row("Kỳ vọng (Avg R)", str(avg_r) if avg_r is not None else "N/A")
    table.add_row("Max Chuỗi Thua", str(perf['max_consecutive_losses']))
    
    total_pnl = perf['total_pnl_pct']
    color = "green" if total_pnl > 0 else "red"
    table.add_row("Tổng P&L (%)", f"[{color}]{total_pnl:+.2f}%[/{color}]")
    
    usd_pnl = perf['pnl_per_1000_usd']
    table.add_row("Lợi nhuận (Vốn $1000)", f"[{color}]${usd_pnl:+.2f}[/{color}]")
    
    console.print()
    console.print(table)


def main():
    parser = argparse.ArgumentParser(description="Quản lý vị thế giao dịch")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Command: add
    parser_add = subparsers.add_parser("add", help="Thêm vị thế đang mở mới")
    parser_add.add_argument("coin", help="Tên coin (vd: BTC)")
    parser_add.add_argument("entry_price", type=float, help="Giá vào lệnh")
    parser_add.add_argument("direction", nargs="?", choices=["LONG", "SHORT"], default="LONG", help="Hướng vị thế (mặc định: LONG cho Spot)")
    parser_add.add_argument("--note", "-n", default="", help="Ghi chú thêm")
    
    parser_add.add_argument(
        "--manual-decision-basis",
        choices=["system_signal", "personal_discretion"],
        default="personal_discretion",
        help="Whether the entry follows a system signal or personal discretion",
    )

    # Command: close
    parser_close = subparsers.add_parser("close", help="Đóng vị thế")
    parser_close.add_argument("coin", help="Tên coin (vd: BTC)")
    parser_close.add_argument("sell_price", type=float, help="Giá bán/đóng lệnh")
    
    # Command: list
    parser_list = subparsers.add_parser("list", help="Xem các vị thế đang mở")
    
    # Command: perf
    parser_perf = subparsers.add_parser("perf", help="Xem hiệu suất chiến lược (đã đóng)")
    parser_perf.add_argument("--type", "-t", choices=["ALL", "AUTO", "MANUAL"], default="ALL", help="Loại lệnh để xem thống kê (ALL, AUTO, MANUAL)")
    
    args = parser.parse_args()
    
    if args.command == "add":
        cmd_add(args)
    elif args.command == "close":
        cmd_close(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "perf":
        cmd_perf(args)

if __name__ == "__main__":
    main()
