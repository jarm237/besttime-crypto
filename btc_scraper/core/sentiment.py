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
    "raw_value": 50,
    "timestamp": 0.0,
    "trend": [],
}


# ──────────────────────────────────────────────────────────────────────────────
#  API fetcher
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_fear_and_greed() -> dict:
    """
    Gọi Alternative.me API và trả về dict:
        {"score": float (-1.0 đến 1.0), "label": str, "raw_value": int, "trend": list}
    Nếu lỗi → trả về giá trị neutral (0.0).
    """
    url = "https://api.alternative.me/fng/?limit=5&format=json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "besttime-crypto-bot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        
        current = data["data"][0]
        raw = int(current["value"])
        label = current["value_classification"]
        # Map 0-100 → -1.0 đến +1.0
        score = round((raw - 50) / 50.0, 3)
        
        trend = []
        for item in data.get("data", []):
            ts = int(item["timestamp"])
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m")
            trend.append(f"{date_str}: {item['value']}/100 ({item['value_classification']})")
            
        return {"score": score, "label": label, "raw_value": raw, "trend": trend}
    except Exception as e:
        # Không crash bot khi API lỗi
        print(f"  [Sentiment] Không thể lấy Fear & Greed Index: {e}", flush=True)
        return {"score": 0.0, "label": "Neutral", "raw_value": 50, "trend": []}


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
        return {k: _cache.get(k) for k in ("score", "label", "raw_value", "trend")}

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


# ──────────────────────────────────────────────────────────────────────────────
#  Sentiment History Tracking (hỗ trợ tính sentiment_trend)
# ──────────────────────────────────────────────────────────────────────────────

def _save_sentiment_to_history(sentiment_dict: dict, history_file: str = "logs/sentiment_history.json"):
    """
    Lưu snapshot sentiment hiện tại vào file history để theo dõi xu hướng.
    
    History format:
    {
        "2026-06-15T14:00:00Z": {"score": 0.2, "raw_value": 60, "label": "Greed"},
        "2026-06-15T13:00:00Z": {"score": -0.4, "raw_value": 30, "label": "Fear"},
        ...
    }
    """
    from pathlib import Path
    try:
        history_path = Path(history_file)
        history_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing history
        history = {}
        if history_path.exists():
            try:
                with open(history_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except Exception:
                history = {}
        
        # Add current timestamp → sentiment snapshot
        now_iso = datetime.now(timezone.utc).isoformat() + "Z"
        history[now_iso] = {
            "score": sentiment_dict.get("score", 0.0),
            "raw_value": sentiment_dict.get("raw_value", 50),
            "label": sentiment_dict.get("label", "Neutral")
        }
        
        # Keep only last 720 entries (30 days of hourly snapshots)
        if len(history) > 720:
            sorted_keys = sorted(history.keys(), reverse=True)
            history = {k: history[k] for k in sorted_keys[:720]}
        
        # Save updated history
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [Sentiment] Lỗi lưu history: {e}", flush=True)


def get_sentiment_trend(history_file: str = "logs/sentiment_history.json") -> dict:
    """
    Tính xu hướng sentiment từ history.
    
    Trả về:
    {
        "trend": "UP" / "DOWN" / "STABLE",          # Chiều xu hướng (so với 1-3 giờ trước)
        "momentum": float,                          # Tốc độ thay đổi (score/hour)
        "recovery_signal": bool,                    # True nếu đang hồi phục từ extreme_fear
        "risk_signal": bool,                        # True nếu giảm nhanh từ greed
        "hours_in_extreme": int,                    # Số giờ ở extreme (fear/greed)
    }
    """
    from pathlib import Path
    
    default_trend = {
        "trend": "STABLE",
        "momentum": 0.0,
        "recovery_signal": False,
        "risk_signal": False,
        "hours_in_extreme": 0,
    }
    
    try:
        history_path = Path(history_file)
        if not history_path.exists():
            return default_trend
        
        with open(history_path, 'r', encoding='utf-8') as f:
            history = json.load(f)
        
        if len(history) < 2:
            return default_trend
        
        # Sort timestamps descending (newest first)
        sorted_times = sorted(history.keys(), reverse=True)
        current = history[sorted_times[0]]
        
        # Tìm điểm dữ liệu cách ~1 giờ (hoặc gần nhất)
        prev_idx = 1
        if len(sorted_times) > 2:
            prev_idx = 1  # Lấy điểm liền trước
        
        prev = history[sorted_times[prev_idx]]
        
        current_score = current.get("score", 0.0)
        prev_score = prev.get("score", 0.0)
        
        # Tính momentum (thay đổi score mỗi giờ)
        score_diff = current_score - prev_score
        momentum = round(score_diff, 3)
        
        # Xác định trend
        if score_diff > 0.1:
            trend = "UP"
        elif score_diff < -0.1:
            trend = "DOWN"
        else:
            trend = "STABLE"
        
        # Detect recovery từ extreme fear
        current_label = current.get("label", "Neutral")
        prev_label = prev.get("label", "Neutral")
        recovery_signal = (
            prev_label == "Extreme Fear"
            and current_label in ["Fear", "Neutral", "Greed"]
            and score_diff > 0
        ) or (
            trend == "UP"
            and current_score < 0  # Vẫn còn bearish nhưng đang hồi phục
        )
        
        # Detect risk từ extreme greed
        risk_signal = (
            prev_label == "Extreme Greed"
            and current_label in ["Greed", "Neutral", "Fear"]
            and score_diff < 0
        ) or (
            trend == "DOWN"
            and current_score > 0.6  # Vẫn còn bullish nhưng đang giảm
        )
        
        # Count hours ở extreme
        hours_in_extreme = 0
        for i, ts in enumerate(sorted_times[:24]):  # Check last 24 hours
            label = history[ts].get("label", "")
            if label in ["Extreme Fear", "Extreme Greed"]:
                hours_in_extreme += 1
        
        return {
            "trend": trend,
            "momentum": momentum,
            "recovery_signal": recovery_signal,
            "risk_signal": risk_signal,
            "hours_in_extreme": hours_in_extreme,
        }
    except Exception as e:
        print(f"  [Sentiment] Lỗi tính trend: {e}", flush=True)
        return default_trend
