import datetime
import logging

from btc_scraper.core.config import GEMINI_API_KEYS
from .api import call_gemini, _key_manager
from .utils import _apply_dynamic_risk_and_sentiment, _format_price
from .builders import _build_coin_block, _build_mtf_block, _build_rag_block, _load_closed_trades

_logger = logging.getLogger(__name__)


def _parse_closed_trade_time(trade: dict) -> datetime.datetime | None:
    """Resolve a closed trade timestamp across legacy/manual/paper schemas."""
    raw = (
        trade.get("closed_at")
        or trade.get("exit_time")
        or trade.get("event_time")
        or trade.get("timestamp")
    )
    if not raw:
        return None

    if isinstance(raw, datetime.datetime):
        return raw.replace(tzinfo=None)

    raw_str = str(raw).strip()
    if not raw_str:
        return None

    if "T" in raw_str:
        return datetime.datetime.fromisoformat(raw_str.replace("Z", "+00:00")).replace(tzinfo=None)

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.datetime.strptime(raw_str, fmt)
        except ValueError:
            continue

    return None

def analyze_with_gemini(
    analysis_results: dict[str, dict],
    mtf_analysis: dict[str, dict] | None = None,
    open_positions: list[dict] | None = None,
    closed_trades: list[dict] | None = None,
) -> str:
    try:
        if not GEMINI_API_KEYS:
            return "[Warning] Chua cau hinh GEMINI_API_KEY trong file .env. Bo qua phan tich AI."

        if not _key_manager.available:
            return f"[Tạm dừng] Tất cả {len(GEMINI_API_KEYS)} Gemini API keys đều đã vượt quota hôm nay. Sẽ thử lại lúc {_key_manager.pause_info}."

        first_info = next(iter(analysis_results.values()), {})
        sentiment = first_info.get("sentiment", {})
        _apply_dynamic_risk_and_sentiment(analysis_results, sentiment)

        coin_blocks = [_build_coin_block(k, v) for k, v in analysis_results.items()]
        market_data_str = "\n\n".join(coin_blocks)

        mtf_str = ""
        if mtf_analysis:
            mtf_blocks = [_build_mtf_block(coin, tf) for coin, tf in mtf_analysis.items()]
            mtf_str = "\n\n=== DU LIEU DA KHUNG THOI GIAN (1H / 4H / 1D) ===\n" + "\n\n".join(mtf_blocks)

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
            positions_str = "\n\n=== DANH SACH VI THE DANG MO (OPEN POSITIONS) ===\n" + "\n".join(pos_blocks)

        rag_str = _build_rag_block(analysis_results, closed_trades)

        sentiment_str = ""
        if sentiment and sentiment.get("raw_value") is not None:
            raw = sentiment.get("raw_value")
            label = sentiment.get("label") or "Unknown"
            score = sentiment.get("normalized_score", sentiment.get("score"))
            trend_list = sentiment.get("trend", [])
            trend_text = "\n  ".join(trend_list) if trend_list else ""
            sentiment_str = (
                f"\n\n=== CAM XUC THI TRUONG (FEAR & GREED INDEX) ===\n"
                f"  Chi so hien tai: {raw}/100 - {label} (score={score:+.2f})\n"
                f"  Xu huong nhung ngay qua:\n  {trend_text}\n"
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
            "Tam ly thi truong dang the nao? (FOMO, so hai, on dinh?) Hay danh gia ca XU HUONG cua Fear & Greed trong nhung ngay qua de xem tam ly dang tot len hay xau di.\n\n"
            "4. **Phan tich tung coin** (15m + ket hop 1h/4h/1d):\n"
            "   - EMA Crossover: EMA9 va EMA21 dang hoi tu hay phan ky? Co tin hieu giao cat sap xay ra khong?\n"
            "   - MACD Histogram: Dang tang hay giam? Momentum dang manh len hay yeu di?\n"
            "   - Bollinger Bands: Gia dang o vi tri nao? Bi ngan chan boi Upper/Lower band khong?\n"
            "   - RSI: Muc do qua mua/qua ban (ca tren 15m va 1h/4h)?\n"
            "   - Ho tro / Khang cu: Gia co dang gan cac vung quan trong khong?\n\n"
            "5. **Co hoi Mua/Ban cu extreme** (QUAN TRONG NHAT):\n"
            "   - Chi ra ROI NHAT 1-2 co hoi ro rang nhat, da duoc xac nhan boi nhieu khung thoi gian (neu co).\n"
            "   - Moi co hoi phai bao gom: Hanh dong (BUY/SELL/HOLD), Khung thoi gian chuan, Ly do cu the, "
            "Gia tham khao Entry, Target (chot loi), Stop Loss (cat lo).\n"
            "   - Co the su dung truc tiep cac muc entry, sl, tp1, tp2 da duoc tinh toan san o muc 'Khuyen nghi TP/SL' hoac tu dieu chinh neu thay can thiet dua tren phan tich da khung.\n"
            "   - Neu khong co co hoi ro rang, hay giai thich vi sao va khuyen nen dung ngoai quan sat.\n\n"
            "Luu y quan trong:\n"
            "- Viet bang tieng Viet, ngan gon va suc tich (khoang 300-400 tu).\n"
            "- Uu tien tin hieu duoc xac nhan boi nhieu khung thoi gian (multi-timeframe confluence).\n"
            "- Dung gach dau dong ro rang, uu tien cac thong tin hanh dong.\n"
            "- Khong can khai lai toan bo so lieu, chi neu nhung chi so QUAN TRONG NHAT cho quyet dinh giao dich.\n"
            "- Format phu hop de hien thi dep tren terminal va ung dung nhan tin Telegram."
        )

        return call_gemini(prompt)

    except Exception as e:
        return f"[Loi AI Analyst] Khong the thuc hien phan tich Gemini: {str(e)}"

def generate_weekly_report() -> str:
    if not GEMINI_API_KEYS or not _key_manager.available:
        return ""
        
    closed_trades = _load_closed_trades()
    if not closed_trades:
        return "Không có dữ liệu giao dịch nào để báo cáo."
        
    now = datetime.datetime.now()
    week_ago = now - datetime.timedelta(days=7)
    
    recent_trades = []
    _skipped_count = 0
    for t in closed_trades:
        try:
            dt = _parse_closed_trade_time(t)
            if dt is None:
                raise ValueError("missing_or_unparseable_closed_time")
            if dt >= week_ago:
                recent_trades.append(t)
        except Exception as exc:
            _skipped_count += 1
            _logger.debug(
                "Skipping invalid AI analyst record (closed_at=%r, exit_time=%r): %s",
                t.get("closed_at"),
                t.get("exit_time"),
                exc,
            )
            continue
    if _skipped_count:
        _logger.debug("[ai_analyst] Skipped %d records with unparseable exit_time", _skipped_count)
            
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
    
    sorted_trades = sorted(recent_trades, key=lambda x: x.get("pnl_pct", 0.0), reverse=True)
    best = sorted_trades[:3]
    worst = sorted_trades[-3:]
    
    best_str = "\n".join(f"- {t['coin']} ({t['direction']}): {t.get('pnl_pct', 0.0):+.2f}% ({t.get('signal_raw', t.get('signal_score',{{}}).get('raw_text',''))})" for t in best)
    worst_str = "\n".join(f"- {t['coin']} ({t['direction']}): {t.get('pnl_pct', 0.0):+.2f}% ({t.get('signal_raw', t.get('signal_score',{{}}).get('raw_text',''))})" for t in worst)
    
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
    
    res = call_gemini(prompt)
    if "Tạm dừng" in res or "Khong nhan duoc" in res:
        return "Không nhận được phản hồi báo cáo từ AI."
    return res.strip()
