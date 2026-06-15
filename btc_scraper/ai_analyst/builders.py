import os
import json
from .utils import _format_price

def _build_coin_block(key: str, info: dict) -> str:
    """Xây dựng khối mô tả dữ liệu kỹ thuật đầy đủ của một coin (khung 15m)"""
    coin, exchange = key.split(":")
    close = info.get("close", 0.0)
    ema9 = info.get("ema9", 0.0)
    ema21 = info.get("ema21", 0.0)
    macd = info.get("macd", 0.0)
    macd_sig = info.get("macd_signal", 0.0)
    macd_hist = info.get("macd_hist", 0.0)
    bb_upper = info.get("bb_upper", 0.0)
    bb_middle = info.get("bb_middle", 0.0)
    bb_lower = info.get("bb_lower", 0.0)
    support = info.get("support", 0.0)
    resistance = info.get("resistance", 0.0)
    history = info.get("history", [])
    tp_sl = info.get("tp_sl", {})

    ema_spread = ema9 - ema21
    ema_trend = "EMA9 > EMA21 (xu huong tang)" if ema_spread > 0 else "EMA9 < EMA21 (xu huong giam)"
    macd_cross = "MACD > Signal (bullish momentum)" if macd > macd_sig else "MACD < Signal (bearish momentum)"

    # Vị trí giá so với Bollinger Bands
    if bb_upper > 0 and bb_lower > 0:
        bb_width = bb_upper - bb_lower
        price_pct = ((close - bb_lower) / bb_width * 100) if bb_width > 0 else 50
        if close >= bb_upper:
            bb_pos = f"Gia cham/vuot Bollinger Upper Band ({price_pct:.0f}% tren dai)"
        elif close <= bb_lower:
            bb_pos = f"Gia cham/duoi Bollinger Lower Band ({price_pct:.0f}% tren dai)"
        else:
            bb_pos = f"Gia nam trong dai Bollinger ({price_pct:.0f}% vi tri)"
    else:
        bb_pos = "N/A"

    from btc_scraper.ml_engine.signal_score import extract_signal_fields
    sig_fields = extract_signal_fields(info)
    meta_pct = sig_fields.get("meta_pct", "N/A")
    meta_str = f"{meta_pct}%" if meta_pct != "N/A" else "N/A"

    lines = [
        f"=== {coin} / USDT | {exchange} | Nến 15m ===",
        f"  Gia Close: {_format_price(close)} | RSI(14): {info['rsi']:.1f}",
        f"  EMA9: {_format_price(ema9)} | EMA21: {_format_price(ema21)} | Spread: {ema_spread:+.4f} -> {ema_trend}",
        f"  MACD: {macd:.4f} | Signal: {macd_sig:.4f} | Hist: {macd_hist:+.4f} -> {macd_cross}",
        f"  Bollinger: Upper={_format_price(bb_upper)} Mid={_format_price(bb_middle)} Lower={_format_price(bb_lower)}",
        f"  Vi tri gia: {bb_pos}",
        f"  Ho tro (50-nến): {_format_price(support)} | Khang cu (50-nến): {_format_price(resistance)}",
        f"  Tin hieu hien tai: {info.get('signal', 'N/A')} ({info.get('reason', '')})",
        f"  Confidence: {info.get('confidence', 0.5):.2f} | Meta Model Prob: {meta_str} | Position size: {info.get('position_size', 1.0):.2f} | ATR shock: {('YES' if info.get('atr_shock') else 'NO')}",
        f"  Market Regime: {info.get('market_regime', 'N/A')} | Trend Follow: {info.get('trend_following_allowed', False)}",
        f"  HTF Trend: {info.get('htf_trend', 'N/A')} | {info.get('htf_details', 'N/A')}",
    ]
    if tp_sl:
        entry_val = tp_sl.get("entry", 0.0)
        sl_val = tp_sl.get("sl", 0.0)
        tp1_val = tp_sl.get("tp1", 0.0)
        tp2_val = tp_sl.get("tp2", 0.0)
        rr1_val = tp_sl.get("rr1", 0.0)
        rr2_val = tp_sl.get("rr2", 0.0)
        method = tp_sl.get("method", "N/A")

        lines.append(
            f"  Khuyen nghi TP/SL ({method}): Entry={_format_price(entry_val)} | "
            f"SL={_format_price(sl_val)} | "
            f"TP1={_format_price(tp1_val)} (R:R={rr1_val}) | "
            f"TP2={_format_price(tp2_val)} (R:R={rr2_val})"
        )

    missed_signals = info.get("missed_signals", [])
    if missed_signals:
        lines.append("  Tin hieu mua/ban da bo qua trong 30p qua:")
        for ms in missed_signals:
            ms_tp = ms["tp_sl"]
            lines.append(
                f"    - Luc {ms['time']} ({ms['age_minutes']}p truoc): {ms['signal']} "
                f"tai Entry={_format_price(ms['entry'])} | SL={_format_price(ms_tp.get('sl', 0.0))} | "
                f"TP1={_format_price(ms_tp.get('tp1', 0.0))} (R:R={ms_tp.get('rr1', 0.0)}) -> Trang thai: {ms['status']}"
            )

    lines.append("")
    lines.append("  --- Lich su 8 nen gan nhat (moi moi nhat) ---")

    if history:
        lines.append(
            f"  {'Time':^16} | {'Close':>10} | {'EMA9':>10} | {'EMA21':>10} | {'MACD_H':>8} | {'RSI':>6} | {'Vol':>12}"
        )
        lines.append("  " + "-" * 90)
        for h in history[-8:]:
            lines.append(
                f"  {h['time']:^16} | {_format_price(h['close']):>10} | "
                f"{_format_price(h['ema9']):>10} | {_format_price(h['ema21']):>10} | "
                f"{h['macd_hist']:>+8.4f} | {h['rsi']:>6.1f} | {h['volume']:>12,.2f}"
            )
    else:
        lines.append("  (Khong co du lieu lich su)")

    return "\n".join(lines)


def _build_mtf_block(coin: str, mtf_data: dict[str, dict]) -> str:
    """Xây dựng khối tóm tắt đa khung thời gian (1h, 4h, 1d) cho một coin."""
    lines = [f"--- {coin} | Phan tich Da Khung Thoi Gian ---"]
    lines.append(
        f"  {'TF':>4} | {'Close':>12} | {'RSI':>6} | {'EMA Trend':^24} | {'MACD Hist':>10} | Signal"
    )
    lines.append("  " + "-" * 85)

    for tf in ["1h", "4h", "1d"]:
        info = mtf_data.get(tf)
        if not info:
            lines.append(f"  {tf:>4} | N/A")
            continue

        close  = info.get("close", 0.0)
        rsi    = info.get("rsi", 50.0)
        ema9   = info.get("ema9", 0.0)
        ema21  = info.get("ema21", 0.0)
        hist   = info.get("macd_hist", 0.0)
        signal = info.get("signal", "N/A")

        ema_trend = "EMA9>EMA21 (tang)" if ema9 > ema21 else "EMA9<EMA21 (giam)"

        lines.append(
            f"  {tf:>4} | {_format_price(close):>12} | {rsi:>6.1f} | "
            f"{ema_trend:^24} | {hist:>+10.4f} | {signal}"
        )

    # Thêm lịch sử 5 nến mới nhất cho từng TF
    for tf in ["1h", "4h", "1d"]:
        info = mtf_data.get(tf)
        if not info:
            continue
        history = info.get("history", [])
        if not history:
            continue
        lines.append("")
        lines.append(f"  [{tf}] 5 nen gan nhat:")
        lines.append(
            f"  {'Time':^16} | {'Close':>10} | {'RSI':>6} | {'MACD_H':>8} | EMA Trend"
        )
        lines.append("  " + "-" * 70)
        for h in history[-5:]:
            h_ema_trend = "tang" if h.get("ema9", 0) > h.get("ema21", 0) else "giam"
            lines.append(
                f"  {h['time']:^16} | {_format_price(h['close']):>10} | "
                f"{h['rsi']:>6.1f} | {h['macd_hist']:>+8.4f} | {h_ema_trend}"
            )

    return "\n".join(lines)


from btc_scraper.core.db import closed_positions_col

def _load_closed_trades(positions_path: str | None = None) -> list[dict]:
    """Đọc danh sách lệnh đã đóng từ MongoDB."""
    try:
        return list(closed_positions_col.find({"status": "closed"}, {"_id": 0}))
    except Exception:
        return []


def _build_rag_block(
    analysis_results: dict[str, dict],
    closed_trades: list[dict] | None = None,
) -> str:
    """
    Xây dựng khối RAG (Retrieval-Augmented Generation) để đưa vào prompt Gemini.

    Logic truy xuất:
    1. Với mỗi coin đang phân tích, tìm các lệnh đã đóng cho coin đó.
    2. Với mỗi loại tín hiệu (signal) hiện tại, tìm các lệnh lịch sử có signal tương tự.
    3. Tính Win Rate và tóm tắt kết quả để AI tham khảo.
    """
    if not closed_trades:
        closed_trades = _load_closed_trades()
    if not closed_trades:
        return ""

    lines = ["\n\n=== DU LIEU LICH SU GIAO DICH (RAG - Hoc tu Qua khu) ==="]
    lines.append(
        "Duoi day la lich su cac lenh da dong. Hay SU DUNG du lieu nay de dieu chinh muc do tu tin "
        "cua ban khi dua ra khuyen nghi. Neu Win Rate thap, hay than trong hon."
    )

    has_content = False

    from btc_scraper.ml_engine.signal_score import extract_signal_fields
    for key, info in analysis_results.items():
        coin = key.split(":")[0]
        sig_fields = extract_signal_fields(info)
        current_signal = info.get("signal", sig_fields.get("raw", ""))

        # Tìm lệnh lịch sử cho coin này
        coin_trades = [t for t in closed_trades if t.get("coin", "").upper() == coin.upper()]

        # Tìm lệnh có loại tín hiệu tương tự (BUY / SELL)
        is_buy_signal  = "BUY"  in current_signal.upper()
        is_sell_signal = "SELL" in current_signal.upper()

        if is_buy_signal:
            similar_trades = [t for t in closed_trades if "LONG" in t.get("direction", "").upper()]
        elif is_sell_signal:
            similar_trades = [t for t in closed_trades if "SHORT" in t.get("direction", "").upper()]
        else:
            similar_trades = []

        # Tổng hợp kết quả
        sections = []

        if coin_trades:
            wins  = sum(1 for t in coin_trades if t.get("result") == "WIN")
            total = len(coin_trades)
            win_rate = wins / total * 100
            avg_pnl = sum(t.get("pnl_pct", 0.0) for t in coin_trades) / total
            recent = sorted(coin_trades, key=lambda t: t.get("entry_time", ""), reverse=True)[:3]
            recent_summary = ", ".join(
                f"{t.get('result','?')}({t.get('pnl_pct',0):+.1f}%)"
                for t in recent
            )
            sections.append(
                f"  [{coin}] Lich su {total} lenh: "
                f"Win Rate={win_rate:.0f}% | Avg PnL={avg_pnl:+.1f}% | "
                f"3 lenh gan nhat: {recent_summary}"
            )

        if similar_trades and (is_buy_signal or is_sell_signal):
            direction_label = "LONG" if is_buy_signal else "SHORT"
            wins  = sum(1 for t in similar_trades if t.get("result") == "WIN")
            total = len(similar_trades)
            win_rate = wins / total * 100
            avg_pnl = sum(t.get("pnl_pct", 0.0) for t in similar_trades) / total
            sections.append(
                f"  [Tat ca {direction_label}] Toan bo lenh {direction_label} trong lich su: "
                f"{total} lenh | Win Rate={win_rate:.0f}% | Avg PnL={avg_pnl:+.1f}%"
            )
            if win_rate < 40:
                sections.append(
                    f"  ⚠️  CANH BAO: Win Rate cua tin hieu {direction_label} chi dat {win_rate:.0f}%. "
                    "Hay THAN TRONG truoc khi vao lenh!"
                )

        if sections:
            has_content = True
            lines.append(f"\n--- {coin} | Tin hieu hien tai: {current_signal} ---")
            lines.extend(sections)

    if not has_content:
        return ""  # Không có dữ liệu hữu ích → bỏ qua

    lines.append("")
    return "\n".join(lines)

