from typing import Dict


def _classify_mtf_signal(signal: str) -> str:
    sig = str(signal or "").upper()
    if "STRONG BUY" in sig or "BUY" in sig or "BULL" in sig:
        return "BULL"
    if "STRONG SELL" in sig or "SELL" in sig or "BEAR" in sig:
        return "BEAR"
    return "NEUTRAL"


def summarize_htf_trend(mtf_data: Dict[str, dict]) -> str:
    """Summarize HTF (1d/4h/1h) trend into one of: BULLISH, BEARISH, BULLISH-MIXED, BEARISH-MIXED, NEUTRAL.

    This implementation intentionally imports `extract_signal_fields` locally to avoid
    creating circular imports at module import time.
    """
    if not mtf_data:
        return "NEUTRAL"

    counts = {"BULL": 0, "BEAR": 0, "NEUTRAL": 0}
    for tf in ["1d", "4h", "1h"]:
        info = mtf_data.get(tf)
        if not info:
            continue
        try:
            from btc_scraper.ml_engine.signal_score import extract_signal_fields
            sig_fields = extract_signal_fields(info)
        except Exception:
            sig_fields = {}

        counts[_classify_mtf_signal(info.get("signal", sig_fields.get("raw", "")))] += 1

    if counts["BULL"] >= 2 and counts["BEAR"] == 0:
        return "BULLISH"
    if counts["BEAR"] >= 2 and counts["BULL"] == 0:
        return "BEARISH"
    if counts["BULL"] > counts["BEAR"]:
        return "BULLISH-MIXED"
    if counts["BEAR"] > counts["BULL"]:
        return "BEARISH-MIXED"
    return "NEUTRAL"


def format_htf_details(mtf_data: Dict[str, dict]) -> str:
    """Format HTF details into string (e.g. 1D=BULL | 4H=BEAR | 1H=NEUTRAL)."""
    parts = []
    for tf in ["1d", "4h", "1h"]:
        info = mtf_data.get(tf)
        if info:
            parts.append(f"{tf.upper()}={info.get('signal', 'N/A')}")
    return " | ".join(parts)

