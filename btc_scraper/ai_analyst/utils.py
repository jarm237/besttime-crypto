import re
from btc_scraper.core.filters import (
    atr_shock_filter,
    atr_used_for_chandelier,
    dynamic_sl_long,
    dynamic_sl_short,
    sentiment_modify,
)

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

    from btc_scraper.ml_engine.signal_score import extract_signal_fields
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
        entry = float(tp_sl.get("entry", info.get("close", 0.0)))

        # We no longer override tp_sl["sl"] here because analysis.py already computes
        # a highly robust dynamic SL. Overriding it here caused flawed SL logic.
        
        if atr_ma > 0:
            info["atr_shock"] = atr_shock_filter(atr_current, atr_ma)
            info["atr_used"] = atr_used_for_chandelier(atr_current, atr_ma)

