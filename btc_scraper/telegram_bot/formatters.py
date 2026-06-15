def format_status_message() -> str:
    from btc_scraper.trading.auto_trader import auto_trader
    from btc_scraper.trading.position_tracker import get_open_positions
    
    at_status = auto_trader.status()
    open_positions = get_open_positions()
    
    cb_status = "🚨 ĐÃ BỊ KÍCH HOẠT" if at_status["circuit_tripped"] else "🟢 Bình thường"
    if at_status["circuit_tripped"] and at_status["circuit_tripped_remaining_h"]:
        cb_status += f" (Mở khoá sau {at_status['circuit_tripped_remaining_h']}h)"
        
    msg = (
        "ℹ️ <b>TRẠNG THÁI HỆ THỐNG</b> ℹ️\n\n"
        f"• <b>Chế độ AutoTrader:</b> <code>{at_status['mode']}</code>\n"
        f"• <b>Lệnh hôm nay:</b> <code>{at_status['trades_today']}/{at_status['max_daily_trades']}</code>\n"
        f"• <b>Chuỗi thua liên tiếp:</b> <code>{at_status['consecutive_losses']}/{at_status['circuit_breaker_n']}</code>\n"
        f"• <b>Circuit Breaker:</b> {cb_status}\n"
        f"• <b>Số vị thế đang mở:</b> <code>{len(open_positions)}</code>\n"
        f"• <b>Ngưỡng Meta:</b> <code>{at_status['meta_threshold']:.0%}</code>\n"
        f"• <b>Ngưỡng Score:</b> <code>{at_status['score_threshold']}</code>\n"
        f"• <b>Allowed Coins:</b> <code>{', '.join(at_status['allowed_coins'][:10])}...</code>\n"
    )
    return msg


def format_positions_message() -> str:
    from btc_scraper.trading.position_tracker import get_open_positions
    positions = get_open_positions()
    if not positions:
        return "ℹ️ Hiện không có vị thế mở nào đang được theo dõi."
        
    lines = ["🛡️ <b>DANH SÁCH VỊ THẾ ĐANG MỞ</b> 🛡️\n"]
    for p in positions:
        coin = p["coin"]
        direction = p["direction"]
        entry = p["entry_price"]
        current = p.get("last_price") or entry
        pnl = 0.0
        if entry > 0:
            if direction == "LONG":
                pnl = (current - entry) / entry * 100
            else:
                pnl = (entry - current) / entry * 100
                
        pnl_text = f"lãi +{pnl:.2f}%" if pnl > 0 else f"lỗ {pnl:.2f}%"
        pnl_emoji = "🟢" if pnl >= 0 else "🔴"
        
        val_format = ",.4f" if current < 10 else ",.2f"
        
        lines.append(
            f"• {pnl_emoji} <b>{coin} ({direction})</b>\n"
            f"  👉 Vốn: <code>${p.get('invested_usdt', 0.0):.2f} USDT</code>\n"
            f"  👉 Giá vào: <code>{entry:{val_format}}</code> | Hiện tại: <code>{current:{val_format}}</code>\n"
            f"  👉 Trạng thái: <b>{pnl_text}</b>\n"
            f"  👉 Entry time: <code>{p['entry_time']}</code>\n"
        )
    return "\n".join(lines)


def format_performance_message() -> str:
    from btc_scraper.trading.position_tracker import get_performance_summary
    perf = get_performance_summary("ALL")
    if "message" in perf:
        return f"ℹ️ {perf['message']}"
        
    msg = (
        "📈 <b>BÁO CÁO HIỆU SUẤT GIAO DỊCH</b> 📈\n\n"
        f"• <b>Tổng số lệnh đã đóng:</b> <code>{perf['total_trades']}</code>\n"
        f"• <b>Số lệnh thắng:</b> <code>{perf['wins']}</code> (Win Rate: <code>{perf['win_rate_pct']}%</code>)\n"
        f"• <b>Số lệnh thua:</b> <code>{perf['losses']}</code>\n"
        f"• <b>Chuỗi thua liên tiếp tối đa:</b> <code>{perf['max_consecutive_losses']}</code>\n"
        f"• <b>Lãi/lỗ trung bình lệnh thắng:</b> <code>+{perf['avg_win_pct']}%</code>\n"
        f"• <b>Lãi/lỗ trung bình lệnh thua:</b> <code>{perf['avg_loss_pct']}%</code>\n"
        f"• <b>Profit Factor:</b> <code>{perf['profit_factor'] or 'N/A'}</code>\n"
        f"• <b>Average R-Multiplier:</b> <code>{perf['avg_r_multiplier'] or 'N/A'}R</code>\n"
        f"• <b>Tổng PnL (%):</b> <code>{perf['total_pnl_pct']:+.3f}%</code>\n"
        f"• <b>Ước tính PnL ($1000 vốn):</b> <code>{perf['pnl_per_1000_usd']:+.2f} USD</code>\n"
        f"• <b>PnL thực tế tích luỹ:</b> <code>{perf['total_pnl_usd_actual']:+.2f} USDT</code>"
    )
    return msg

