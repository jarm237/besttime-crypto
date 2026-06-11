"""
AI Analyst module - Sử dụng Gemini API (google-genai) để phân tích tình hình thị trường và khuyến nghị.
Hỗ trợ round-robin đa key và tự động tạm dừng đến hết ngày khi tất cả key đều bị 429.
"""

import re
import os
import json
import time
import datetime
from google import genai
from btc_scraper.config import GEMINI_API_KEYS
from btc_scraper.filters import (
    atr_shock_filter,
    atr_used_for_chandelier,
    dynamic_sl_long,
    dynamic_sl_short,
    sentiment_modify,
)


class _GeminiKeyManager:
    """
    Quản lý round-robin và trạng thái 429 cho danh sách Gemini API keys.
    - Mỗi lần gọi sử dụng key tiếp theo trong vòng xoay (round-robin).
    - Khi một key bị 429, bỏ qua ngay và dùng key kế tiếp.
    - Khi tất cả key đều bị 429, đánh dấu "paused" đến 00:05 hôm sau.
    """

    def __init__(self, keys: list[str]):
        self._keys = list(dict.fromkeys(keys))   # loại trùng lặp, giữ thứ tự
        self._index = 0                           # con trỏ round-robin
        self._exhausted: set[str] = set()         # keys đang bị 429
        self._paused_until: datetime.datetime | None = None

    # ------------------------------------------------------------------ #
    #  Properties                                                          #
    # ------------------------------------------------------------------ #

    @property
    def available(self) -> bool:
        """Trả về True nếu có ít nhất 1 key có thể dùng ngay bây giờ."""
        if not self._keys:
            return False
        if self._paused_until:
            if datetime.datetime.now() < self._paused_until:
                return False
            # Đã qua thời gian tạm dừng → reset
            self._paused_until = None
            self._exhausted.clear()
        return len(self._exhausted) < len(self._keys)

    @property
    def pause_info(self) -> str:
        """Thông báo thời điểm hết tạm dừng."""
        if self._paused_until:
            return self._paused_until.strftime("%H:%M ngày %d/%m/%Y")
        return ""

    # ------------------------------------------------------------------ #
    #  Methods                                                             #
    # ------------------------------------------------------------------ #

    def next_key(self) -> str | None:
        """
        Trả về key tiếp theo có thể dùng (round-robin).
        Trả về None nếu không có key nào khả dụng.
        """
        if not self.available:
            return None
        n = len(self._keys)
        for _ in range(n):
            key = self._keys[self._index % n]
            self._index = (self._index + 1) % n
            if key not in self._exhausted:
                return key
        return None

    def mark_exhausted(self, key: str) -> None:
        """
        Đánh dấu một key bị 429.
        Nếu tất cả key đều exhausted → tạm dừng đến 00:05 hôm sau.
        """
        self._exhausted.add(key)
        if len(self._exhausted) >= len(self._keys):
            tomorrow = (datetime.datetime.now() + datetime.timedelta(days=1)).replace(
                hour=0, minute=5, second=0, microsecond=0
            )
            self._paused_until = tomorrow
            print(
                f"\n  ⚠️  Tất cả {len(self._keys)} Gemini API keys đều bị 429. "
                f"Tạm dừng gọi AI đến {tomorrow.strftime('%H:%M %d/%m/%Y')}.",
                flush=True,
            )

    def reset_key(self, key: str) -> None:
        """Xóa trạng thái exhausted của một key khi gọi thành công."""
        self._exhausted.discard(key)


# Singleton manager — dùng chung trong suốt vòng đời process
_key_manager = _GeminiKeyManager(GEMINI_API_KEYS)


# ────────────────────────────────────────────────────────────────────────────
#  Helper formatters
# ────────────────────────────────────────────────────────────────────────────

def _parse_retry_delay(error_msg: str, default: int = 60) -> int:
    """Lấy số giây phải chờ từ thông báo lỗi 429 của Gemini."""
    match = re.search(r"retry in ([\d.]+)s", error_msg, re.IGNORECASE)
    if match:
        return max(int(float(match.group(1))) + 2, 1)
    return default


def _format_price(value: float) -> str:
    """Định dạng giá trị giá theo độ lớn"""
    if value == 0.0:
        return "N/A"
    return f"{value:,.2f}" if value >= 10 else f"{value:,.4f}"


def _apply_dynamic_risk_and_sentiment(
    analysis_results: dict[str, dict],
    sentiment: dict[str, object] | None,
) -> None:
    """Cập nhật confidence và dynamic SL/ATR metadata trước khi build prompt AI."""
    if sentiment is None:
        sentiment = {}

    fear_score = float(sentiment.get("score", 0.0))
    fear_extreme = fear_score <= -0.6

    from btc_scraper.signal_score import extract_signal_fields
    for info in analysis_results.values():
        sig_fields = extract_signal_fields(info)
        signal = str(info.get("signal", sig_fields.get("raw", ""))).upper()
        trend = str(info.get("trend", "NEUTRAL")).upper()
        confidence = float(info.get("confidence", 0.5))
        direction = "SHORT" if "SELL" in signal or "SHORT" in signal else "LONG"

        info["confidence"] = sentiment_modify(confidence, trend, direction, fear_extreme)
        info.setdefault("position_size", max(0.25, min(1.0, 0.5 + info["confidence"] * 0.5)))

        tp_sl = info.setdefault("tp_sl", {})
        atr_current = float(info.get("atr_current", info.get("atr", 0.0)))
        atr_ma = float(info.get("atr_ma", 0.0))
        support = info.get("support")
        resistance = info.get("resistance")

        if direction == "LONG" and support is not None:
            tp_sl["sl"] = dynamic_sl_long(float(support), atr_current, atr_ma)
            tp_sl.setdefault("method", "dynamic_atr_long")
        elif direction == "SHORT" and resistance is not None:
            tp_sl["sl"] = dynamic_sl_short(float(resistance), atr_current, atr_ma)
            tp_sl.setdefault("method", "dynamic_atr_short")

        if atr_ma > 0:
            info["atr_shock"] = atr_shock_filter(atr_current, atr_ma)
            info["atr_used"] = atr_used_for_chandelier(atr_current, atr_ma)


# ────────────────────────────────────────────────────────────────────────────
#  Block builders
# ────────────────────────────────────────────────────────────────────────────

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

    lines = [
        f"=== {coin} / USDT | {exchange} | Nến 15m ===",
        f"  Gia Close: {_format_price(close)} | RSI(14): {info['rsi']:.1f}",
        f"  EMA9: {_format_price(ema9)} | EMA21: {_format_price(ema21)} | Spread: {ema_spread:+.4f} -> {ema_trend}",
        f"  MACD: {macd:.4f} | Signal: {macd_sig:.4f} | Hist: {macd_hist:+.4f} -> {macd_cross}",
        f"  Bollinger: Upper={_format_price(bb_upper)} Mid={_format_price(bb_middle)} Lower={_format_price(bb_lower)}",
        f"  Vi tri gia: {bb_pos}",
        f"  Ho tro (50-nến): {_format_price(support)} | Khang cu (50-nến): {_format_price(resistance)}",
        f"  Tin hieu hien tai: {info.get('signal', 'N/A')} ({info.get('reason', '')})",
        f"  Confidence: {info.get('confidence', 0.5):.2f} | Position size: {info.get('position_size', 1.0):.2f} | ATR shock: {('YES' if info.get('atr_shock') else 'NO')}",
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


# ────────────────────────────────────────────────────────────────────────────
#  RAG: Truy xuất lịch sử lệnh để cung cấp ngữ cảnh cho Gemini
# ────────────────────────────────────────────────────────────────────────────

def _load_closed_trades(positions_path: str | None = None) -> list[dict]:
    """Đọc danh sách lệnh đã đóng từ positions.json."""
    if positions_path is None:
        # Tự động tìm file theo đường dẫn tương đối từ project root
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        positions_path = os.path.join(base, "data", "positions.json")
    try:
        with open(positions_path, encoding="utf-8") as f:
            all_trades = json.load(f)
        return [t for t in all_trades if t.get("status") == "closed"]
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

    from btc_scraper.signal_score import extract_signal_fields
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


# ────────────────────────────────────────────────────────────────────────────
#  Main analysis function
# ────────────────────────────────────────────────────────────────────────────

def analyze_with_gemini(
    analysis_results: dict[str, dict],
    mtf_analysis: dict[str, dict] | None = None,
    open_positions: list[dict] | None = None,
    closed_trades: list[dict] | None = None,
) -> str:
    """
    Gửi dữ liệu nến và chỉ số kỹ thuật lên Gemini API.
    - Round-robin qua GEMINI_API_KEY_1 … GEMINI_API_KEY_5.
    - Khi một key bị 429 → bỏ qua, dùng key tiếp theo ngay lập tức.
    - Khi tất cả key đều bị 429 → trả thông báo tạm dừng đến hết ngày.
    - RAG: Bổ sung lịch sử giao dịch để Gemini học từ quá khứ.
    """
    if not GEMINI_API_KEYS:
        return "[Warning] Chua cau hinh GEMINI_API_KEY trong file .env. Bo qua phan tich AI."

    # Kiểm tra trạng thái tạm dừng
    if not _key_manager.available:
        pause_time = _key_manager.pause_info
        return (
            f"[Tạm dừng] Tất cả {len(GEMINI_API_KEYS)} Gemini API keys đều đã vượt quota hôm nay. "
            f"Sẽ thử lại lúc {pause_time}. Bỏ qua phân tích AI lần này."
        )

    try:
        # ── Sentiment + Dynamic risk before building prompt ─────────────────
        first_info = next(iter(analysis_results.values()), {})
        sentiment = first_info.get("sentiment", {})
        _apply_dynamic_risk_and_sentiment(analysis_results, sentiment)

        # ── Xây dựng prompt ──────────────────────────────────────────────
        coin_blocks = [_build_coin_block(k, v) for k, v in analysis_results.items()]
        market_data_str = "\n\n".join(coin_blocks)

        mtf_str = ""
        if mtf_analysis:
            mtf_blocks = [_build_mtf_block(coin, tf) for coin, tf in mtf_analysis.items()]
            mtf_str = (
                "\n\n=== DU LIEU DA KHUNG THOI GIAN (1H / 4H / 1D) ===\n"
                + "\n\n".join(mtf_blocks)
            )

        positions_str = ""
        if open_positions:
            pos_blocks = []
            for p in open_positions:
                coin = p.get("coin", "N/A")
                direction = p.get("direction", "N/A")
                entry = p.get("entry_price", 0.0)
                sl = p.get("suggested_sl", "N/A")
                tp1 = p.get("suggested_tp1", "N/A")
                tp2 = p.get("suggested_tp2", "N/A")
                pnl = p.get("pnl_pct", 0.0)
                pos_blocks.append(f"- {coin} ({direction}): Entry={_format_price(entry)}, Hien tai lo/lai={pnl:+.2f}%, SL={sl}, TP1={tp1}, TP2={tp2}")
            
            positions_str = (
                "\n\n=== DANH SACH VI THE DANG MO (OPEN POSITIONS) ===\n"
                + "\n".join(pos_blocks)
            )

        # ── RAG: Lịch sử giao dịch ───────────────────────────────────────
        rag_str = _build_rag_block(analysis_results, closed_trades)

        # ── Sentiment: Fear & Greed ───────────────────────────────────────
        sentiment_str = ""
        if sentiment:
            raw = sentiment.get("raw_value", 50)
            label = sentiment.get("label", "Neutral")
            score = sentiment.get("score", 0.0)
            sentiment_str = (
                f"\n\n=== CAM XUC THI TRUONG (FEAR & GREED INDEX) ===\n"
                f"  Chi so hien tai: {raw}/100 - {label} (score={score:+.2f})\n"
                f"  {'⚠️ EXTREME FEAR: Cam xuc tieu cuc cuc do — giao dich BUY co rui ro cao!' if score < -0.6 else ('🔥 EXTREME GREED: Thi truong dang qua lac quan — giao dich SELL/SHORT co the hieu qua!' if score > 0.6 else 'Cam xuc trung binh — khong anh huong dac biet den quyet dinh giao dich.')}"
            )

        prompt = (
            "Ban la mot chuyen gia phan tich ky thuat crypto va giao dich tan tan cap cao. "
            "Ban da co kinh nghiem nhieu nam voi cac chi bao RSI, EMA, MACD va Bollinger Bands.\n\n"
            "Duoi day la du lieu ky thuat THUC TE, cap nhat nhat cua cac dong coin tren san giao dich:\n\n"
            "--- DU LIEU KHUNG 15 PHUT (ngan han, giao dich scalp/intraday) ---\n"
            f"{market_data_str}"
            f"{mtf_str}"
            f"{sentiment_str}"
            f"{rag_str}"
            f"{positions_str}\n\n"
            "Nhiem vu cua ban (phan tich bang tieng Viet):\n\n"
            "1. **Danh gia cac vi the dang mo** (NEU CO): Voi moi vi the dang mo, dua tren phan tich ky thuat hien tai (dac biet la 15m va 1h), "
            "hay dua ra loi khuyen: Nen GIU (Hold), CAT LO (Cut loss) hay CHOT LOI (Take profit). Giai thich ngan gon ly do.\n\n"
            "2. **Xu huong Da Khung** (QUAN TRONG): Ket hop tin hieu 1d -> 4h -> 1h -> 15m de xac dinh huong chinh:\n"
            "   - Neu 1d va 4h cung bullish: uu tien tim diem BUY o khung nho.\n"
            "   - Neu 1d va 4h cung bearish: uu tien tim diem SELL/SHORT o khung nho.\n"
            "   - Neu cac khung mau thuan: chua ro xu huong, nen dung ngoai quan sat.\n\n"
            "3. **Nhan dinh thi truong tong quan** (2-3 cau): Xu huong chung la Bullish hay Bearish? "
            "Tam ly thi truong dang the nao? (FOMO, so hai, on dinh?)\n\n"
            "4. **Phan tich tung coin** (15m + ket hop 1h/4h/1d):\n"
            "   - EMA Crossover: EMA9 va EMA21 dang hoi tu hay phan ky? Co tin hieu giao cat sap xay ra khong?\n"
            "   - MACD Histogram: Dang tang hay giam? Momentum dang manh len hay yeu di?\n"
            "   - Bollinger Bands: Gia dang o vi tri nao? Bi ngan chan boi Upper/Lower band khong?\n"
            "   - RSI: Muc do qua mua/qua ban (ca tren 15m va 1h/4h)?\n"
            "   - Ho tro / Khang cu: Gia co dang gan cac vung quan trong khong?\n\n"
            "5. **Co hoi Mua/Ban cu the** (QUAN TRONG NHAT):\n"
            "   - Chi ra ROI NHAT 1-2 co hoi ro rang nhat, da duoc xac nhan boi nhieu khung thoi gian (neu co).\n"
            "   - Moi co hoi phai bao gom: Hanh dong (BUY/SELL/HOLD), Khung thoi gian chuan, Ly do cu the, "
            "Gia tham khao Entry, Target (chot loi), Stop Loss (cat lo).\n"
            "   - Co the su dung truc tiep cac muc entry, sl, tp1, tp2 da duoc tinh toan san o muc 'Khuyen nghi TP/SL' hoac tu dieu chinh neu thay can thiet dua tren phan tich da khung.\n"
            "   - Dac biet xem xet cac tin hieu da bi bo qua trong 30p qua (neu co). Neu mot tin hieu van co trang thai 'Running (Van con hieu luc)' va gia hien tai van dang gan vung Entry cu, hay danh gia xem co the gia gia nhap muon (late entry) duoc khong.\n"
            "   - Neu khong co co hoi ro rang, hay giai thich vi sao va khuyen nen dung ngoai quan sat.\n\n"
            "Luu y quan trong:\n"
            "- Viet bang tieng Viet, ngan gon va suc tich (khoang 300-400 tu).\n"
            "- Uu tien tin hieu duoc xac nhan boi nhieu khung thoi gian (multi-timeframe confluence).\n"
            "- Dung gach dau dong ro rang, uu tien cac thong tin hanh dong.\n"
            "- Khong can khai lai toan bo so lieu, chi neu nhung chi so QUAN TRONG NHAT cho quyet dinh giao dich.\n"
            "- Format phu hop de hien thi dep tren terminal va ung dung nhan tin Telegram."
        )

        # ── Round-robin qua từng key ──────────────────────────────────────
        while _key_manager.available:
            api_key = _key_manager.next_key()
            if api_key is None:
                break

            key_label = f"...{api_key[-6:]}"
            try:
                print(f"  [Gemini] Dùng key [{key_label}]...", flush=True)
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                )
                _key_manager.reset_key(api_key)  # gọi thành công → bỏ đánh dấu exhausted
                return response.text if response.text else "Khong nhan duoc phan hoi tu Gemini AI."

            except Exception as api_err:
                err_str = str(api_err)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    wait_sec = _parse_retry_delay(err_str)
                    print(
                        f"  [429] Key [{key_label}] hết quota (retry ~{wait_sec}s). "
                        f"Chuyển key tiếp theo...",
                        flush=True,
                    )
                    _key_manager.mark_exhausted(api_key)
                    # Không chờ — chuyển sang key tiếp ngay
                else:
                    raise  # Lỗi không phải 429, đẩy ra ngoài

        # Tất cả key đều exhausted
        pause_time = _key_manager.pause_info
        return (
            f"[Tạm dừng] Tất cả {len(GEMINI_API_KEYS)} Gemini API keys đều đã vượt quota hôm nay. "
            f"Sẽ thử lại lúc {pause_time}."
        )

    except Exception as e:
        return f"[Loi AI Analyst] Khong the thuc hien phan tich Gemini: {str(e)}"




# ────────────────────────────────────────────────────────────────────────────
#  Weekly Report Generator
# ────────────────────────────────────────────────────────────────────────────

def generate_weekly_report() -> str:
    """
    Sinh báo cáo tổng kết tuần dựa trên dữ liệu giao dịch đã đóng.
    """
    if not GEMINI_API_KEYS or not _key_manager.available:
        return ""
        
    closed_trades = _load_closed_trades()
    if not closed_trades:
        return "Không có dữ liệu giao dịch nào để báo cáo."
        
    # Filter for last 7 days
    now = datetime.datetime.now()
    week_ago = now - datetime.timedelta(days=7)
    
    recent_trades = []
    for t in closed_trades:
        try:
            exit_time_str = t.get("exit_time", "")
            # Example format: 2026-06-11 02:43:00 or similar
            if "T" in exit_time_str:
                dt = datetime.datetime.fromisoformat(exit_time_str.replace("Z", "+00:00")).replace(tzinfo=None)
            else:
                dt = datetime.datetime.strptime(exit_time_str, "%Y-%m-%d %H:%M:%S")
            if dt >= week_ago:
                recent_trades.append(t)
        except:
            pass
            
    if not recent_trades:
        return "Không có lệnh nào đóng trong 7 ngày qua."
        
    wins = [t for t in recent_trades if t.get("result") == "WIN"]
    losses = [t for t in recent_trades if t.get("result") == "LOSS"]
    win_rate = len(wins) / len(recent_trades) * 100
    
    total_pnl = sum(t.get("pnl_pct", 0.0) for t in recent_trades)
    
    stats = (
        f"Tổng lệnh: {len(recent_trades)}\n"
        f"WIN: {len(wins)} | LOSS: {len(losses)}\n"
        f"Win Rate: {win_rate:.1f}%\n"
        f"Tổng PnL: {total_pnl:+.2f}%\n"
    )
    
    # top 3 best and worst
    sorted_trades = sorted(recent_trades, key=lambda x: x.get("pnl_pct", 0.0), reverse=True)
    best = sorted_trades[:3]
    worst = sorted_trades[-3:]
    
    best_str = "\n".join(f"- {t['coin']} ({t['direction']}): {t.get('pnl_pct', 0.0):+.2f}% ({t.get('signal_raw', t.get('signal_score',{}).get('raw_text',''))})" for t in best)
    worst_str = "\n".join(f"- {t['coin']} ({t['direction']}): {t.get('pnl_pct', 0.0):+.2f}% ({t.get('signal_raw', t.get('signal_score',{}).get('raw_text',''))})" for t in worst)
    
    prompt = (
        "Bạn là một chuyên gia đánh giá hiệu suất hệ thống giao dịch thuật toán (Crypto).\n"
        "Hãy viết một báo cáo tổng kết tuần ngắn gọn, chuyên nghiệp và có chiều sâu dựa trên số liệu sau:\n\n"
        f"--- THỐNG KÊ 7 NGÀY QUA ---\n{stats}\n\n"
        f"--- TOP 3 LỆNH THẮNG ĐẬM NHẤT ---\n{best_str}\n\n"
        f"--- TOP 3 LỆNH THUA LỖ NẶNG NHẤT ---\n{worst_str}\n\n"
        "Yêu cầu báo cáo gồm 3 phần:\n"
        "1. Tóm tắt hiệu suất: Nhận xét tổng quan về Win Rate và PnL.\n"
        "2. Phân tích: Đặc điểm chung của các lệnh thắng/thua là gì? (Ví dụ: xu hướng, loại tín hiệu).\n"
        "3. Đề xuất cải thiện: Cần chỉnh sửa R:R, vị thế (position size) hay thay đổi ngưỡng tín hiệu nào không?\n"
        "Chỉ viết tiếng Việt, sử dụng icon phù hợp. Giữ báo cáo súc tích dưới 400 từ."
    )
    
    while _key_manager.available:
        api_key = _key_manager.next_key()
        if not api_key: break
        try:
            client = genai.Client(api_key=api_key)
            resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            _key_manager.reset_key(api_key)
            return resp.text.strip()
        except Exception as api_err:
            if "429" in str(api_err) or "RESOURCE_EXHAUSTED" in str(api_err):
                _key_manager.mark_exhausted(api_key)
            else:
                break
    return "Không nhận được phản hồi báo cáo từ AI."
