"""
AI Analyst module - Sử dụng Gemini API (google-genai) để phân tích tình hình thị trường và khuyến nghị.
Hỗ trợ round-robin đa key và tự động tạm dừng đến hết ngày khi tất cả key đều bị 429.
"""

import re
import time
import datetime
from google import genai
from btc_scraper.config import GEMINI_API_KEYS


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
#  Main analysis function
# ────────────────────────────────────────────────────────────────────────────

def analyze_with_gemini(
    analysis_results: dict[str, dict],
    mtf_analysis: dict[str, dict] | None = None,
    open_positions: list[dict] | None = None,
) -> str:
    """
    Gửi dữ liệu nến và chỉ số kỹ thuật lên Gemini API.
    - Round-robin qua GEMINI_API_KEY_1 … GEMINI_API_KEY_5.
    - Khi một key bị 429 → bỏ qua, dùng key tiếp theo ngay lập tức.
    - Khi tất cả key đều bị 429 → trả thông báo tạm dừng đến hết ngày.
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

        prompt = (
            "Ban la mot chuyen gia phan tich ky thuat crypto va giao dich tan tan cap cao. "
            "Ban da co kinh nghiem nhieu nam voi cac chi bao RSI, EMA, MACD va Bollinger Bands.\n\n"
            "Duoi day la du lieu ky thuat THUC TE, cap nhat nhat cua cac dong coin tren san giao dich:\n\n"
            "--- DU LIEU KHUNG 15 PHUT (ngan han, giao dich scalp/intraday) ---\n"
            f"{market_data_str}"
            f"{mtf_str}"
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
