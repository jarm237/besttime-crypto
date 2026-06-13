"""
Sentiment Analysis module - Phân tích cảm xúc thị trường.

Nguồn dữ liệu: Alternative.me Fear & Greed Index (https://alternative.me/crypto/fear-and-greed-index/)
- Miễn phí, không cần API key.
- Cache kết quả 1 giờ để tránh spam API.

Score mapping: 0-100 → -1.0 (Cực kỳ Bearish) đến +1.0 (Cực kỳ Bullish)
"""

import time
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ──────────────────────────────────────────────────────────────────────────────
#  Cache đơn giản trong bộ nhớ (1 giờ)
# ──────────────────────────────────────────────────────────────────────────────
_CACHE_TTL = 3600  # seconds

_cache: dict = {
    "score": 0.0,
    "label": "Neutral",
    "raw_value": 50,
    "timestamp": 0.0,
}


# ──────────────────────────────────────────────────────────────────────────────
#  API fetcher
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_fear_and_greed() -> dict:
    """
    Gọi Alternative.me API và trả về dict:
        {"score": float (-1.0 đến 1.0), "label": str, "raw_value": int}
    Nếu lỗi → trả về giá trị neutral (0.0).
    """
    url = "https://api.alternative.me/fng/?limit=1&format=json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "besttime-crypto-bot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        raw = int(data["data"][0]["value"])
        label = data["data"][0]["value_classification"]
        # Map 0-100 → -1.0 đến +1.0
        score = round((raw - 50) / 50.0, 3)
        return {"score": score, "label": label, "raw_value": raw}
    except Exception as e:
        # Không crash bot khi API lỗi
        print(f"  [Sentiment] Không thể lấy Fear & Greed Index: {e}", flush=True)
        return {"score": 0.0, "label": "Neutral", "raw_value": 50}


# ──────────────────────────────────────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────────────────────────────────────

def get_market_sentiment() -> dict:
    """
    Trả về dict cảm xúc thị trường (có cache 1 giờ):
        {
            "score":     float,  # -1.0 (Extreme Fear) → +1.0 (Extreme Greed)
            "label":     str,    # "Extreme Fear" / "Fear" / "Neutral" / "Greed" / "Extreme Greed"
            "raw_value": int,    # 0-100 (giá trị gốc từ API)
        }
    """
    global _cache
    now = time.time()

    if now - _cache["timestamp"] < _CACHE_TTL:
        return {k: _cache[k] for k in ("score", "label", "raw_value")}

    result = _fetch_fear_and_greed()
    _cache.update(result)
    _cache["timestamp"] = now
    print(
        f"  [Sentiment] Fear & Greed Index: {result['raw_value']}/100 "
        f"({result['label']}) -> score={result['score']:+.2f}",
        flush=True,
    )
    return result


def sentiment_label_vi(label: str) -> str:
    """Dịch nhãn sang tiếng Việt để hiển thị trên terminal/Telegram."""
    mapping = {
        "Extreme Fear": "Cực kỳ Sợ hãi",
        "Fear": "Sợ hãi",
        "Neutral": "Trung tính",
        "Greed": "Tham lam",
        "Extreme Greed": "Cực kỳ Tham lam",
    }
    return mapping.get(label, label)


def get_historical_sentiment_map(limit: int = 1000) -> dict:
    """
    Tải dữ liệu lịch sử Fear & Greed và trả về mapping:
    date_str (YYYY-MM-DD) -> sentiment_dict
    """
    url = f"https://api.alternative.me/fng/?limit={limit}&format=json"
    mapping = {}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "besttime-crypto-bot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        for item in data.get("data", []):
            raw = int(item["value"])
            label = item["value_classification"]
            score = round((raw - 50) / 50.0, 3)
            ts = int(item["timestamp"])
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            mapping[date_str] = {"score": score, "label": label, "raw_value": raw}
    except Exception as e:
        print(f"  [Sentiment] Lỗi tải F&G lịch sử: {e}", flush=True)
    return mapping
