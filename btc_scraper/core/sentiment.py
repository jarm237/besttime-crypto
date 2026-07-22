"""
Sentiment Analysis module - Phân tích cảm xúc thị trường.

Nguồn dữ liệu: Alternative.me Fear & Greed Index (https://alternative.me/crypto/fear-and-greed-index/)
- Miễn phí, không cần API key.
- Cache kết quả 1 giờ để tránh spam API.

Score mapping: 0-100 → -1.0 (Cực kỳ Bearish) đến +1.0 (Cực kỳ Bullish)
"""

import time
import json
import os
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta, timezone

from btc_scraper.core.fear_greed import normalize_fear_greed, parse_fear_greed_record

# ──────────────────────────────────────────────────────────────────────────────
#  Cache đơn giản trong bộ nhớ (1 giờ)
# ──────────────────────────────────────────────────────────────────────────────
_CACHE_TTL = 3600  # seconds

_cache: dict = {
    "score": None,
    "normalized_score": None,
    "raw_value": None,
    "label": None,
    "observed_at": None,
    "observation_date": None,
    "status": "empty",
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
    Lỗi mạng/schema được chuyển cho caller để dùng stale cache hoặc unavailable.
    """
    url = "https://api.alternative.me/fng/?limit=5&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": "besttime-crypto-bot/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read().decode())

    records = data.get("data", [])
    if not records:
        raise ValueError("Alternative.me returned no Fear & Greed observations")
    current = parse_fear_greed_record(records[0])

    trend = []
    for item in records:
        observed = parse_fear_greed_record(item)
        trend.append(
            f"{observed.observed_at.strftime('%d/%m')}: "
            f"{observed.raw_value}/100 ({observed.classification})"
        )

    return {
        "score": current.normalized_score,  # backward-compatible alias
        "normalized_score": current.normalized_score,
        "label": current.classification,
        "raw_value": current.raw_value,
        "observed_at": current.observed_at.isoformat(),
        "observation_date": current.observation_date,
        "source": current.source,
        "status": "success",
        "stale": False,
        "trend": trend,
    }


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
        return {k: v for k, v in _cache.items() if k != "timestamp"}

    try:
        result = _fetch_fear_and_greed()
    except Exception as exc:
        print(f"  [Sentiment] Không thể lấy Fear & Greed Index: {exc}", flush=True)
        if _cache.get("raw_value") is not None:
            result = {
                **{k: v for k, v in _cache.items() if k != "timestamp"},
                "status": "stale",
                "stale": True,
                "error": str(exc),
            }
        else:
            result = {
                "score": None,
                "normalized_score": None,
                "label": None,
                "raw_value": None,
                "observed_at": None,
                "observation_date": None,
                "source": "alternative.me",
                "status": "unavailable",
                "stale": False,
                "error": str(exc),
                "trend": [],
            }
    _cache.update(result)
    _cache["timestamp"] = now
    if result.get("raw_value") is not None:
        print(
            f"  [Sentiment] Fear & Greed Index: {result['raw_value']}/100 "
            f"({result['label']}) -> score={result['normalized_score']:+.2f}",
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
            score = normalize_fear_greed(raw)
            ts = int(item["timestamp"])
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            mapping[date_str] = {"score": score, "label": label, "raw_value": raw}
    except Exception as e:
        print(f"  [Sentiment] Lỗi tải F&G lịch sử: {e}", flush=True)
    return mapping


# ──────────────────────────────────────────────────────────────────────────────
#  Sentiment History Tracking (hỗ trợ tính sentiment_trend)
# ──────────────────────────────────────────────────────────────────────────────

def _observation_date(value: dict, fallback: date | None = None) -> date:
    explicit = value.get("observation_date")
    if explicit:
        return date.fromisoformat(str(explicit)[:10])
    observed_at = value.get("observed_at")
    if observed_at:
        return datetime.fromisoformat(str(observed_at).replace("Z", "+00:00")).date()
    return fallback or datetime.now(timezone.utc).date()


def _normalized_score(value: dict) -> float | None:
    score = value.get("normalized_score")
    if score is None:
        score = value.get("score")
    if score is None and value.get("raw_value") is not None:
        score = normalize_fear_greed(value["raw_value"])
    return float(score) if score is not None else None


def _history_by_date(history: dict) -> dict[date, dict]:
    """Deduplicate legacy timestamp keys into one observation per UTC date."""
    daily: dict[date, tuple[str, dict]] = {}
    for key, value in history.items():
        if not isinstance(value, dict):
            continue
        try:
            observed_date = date.fromisoformat(str(key)[:10])
        except ValueError:
            continue
        if observed_date not in daily or str(key) > daily[observed_date][0]:
            daily[observed_date] = (str(key), value)
    return {observed_date: item[1] for observed_date, item in daily.items()}


def _save_sentiment_to_history(sentiment_dict: dict, history_file: str = "logs/sentiment_history.json"):
    """Upsert one canonical daily observation and retain a bounded history."""
    from pathlib import Path
    try:
        raw_value = sentiment_dict.get("raw_value")
        score = _normalized_score(sentiment_dict)
        if raw_value is None or score is None:
            return

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
        
        daily = _history_by_date(history)
        observed_date = _observation_date(sentiment_dict)
        daily[observed_date] = {
            "score": score,  # backward-compatible alias
            "normalized_score": score,
            "raw_value": raw_value,
            "label": sentiment_dict.get("label") or "Unknown",
            "observed_at": sentiment_dict.get("observed_at"),
        }

        try:
            retention_days = max(1, int(os.getenv("FEAR_GREED_HISTORY_RETENTION_DAYS", "90")))
        except ValueError:
            retention_days = 90
        retained_dates = sorted(daily, reverse=True)[:retention_days]
        history = {
            f"{observed.isoformat()}T00:00:00Z": daily[observed]
            for observed in sorted(retained_dates)
        }
        
        # Save updated history
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [Sentiment] Lỗi lưu history: {e}", flush=True)


def get_sentiment_trend(history_file: str = "logs/sentiment_history.json", current_sentiment: dict = None) -> dict:
    """Compare a daily observation with the latest observation before its date."""
    from pathlib import Path

    default_trend = {
        "trend": "UNKNOWN",
        "daily_momentum": None,
        "momentum": None,  # deprecated alias
        "recovery_signal": False,
        "risk_signal": False,
        "consecutive_extreme_days": 0,
        "hours_in_extreme": 0,  # deprecated alias; value is now days
    }

    try:
        history_path = Path(history_file)
        if history_path.exists():
            with open(history_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
        else:
            history = {}
        
        daily = _history_by_date(history)
        if current_sentiment is not None:
            current = dict(current_sentiment)
            current_date = _observation_date(current)
            previous_dates = [observed for observed in daily if observed < current_date]
            if not previous_dates or _normalized_score(current) is None:
                return default_trend
            previous_date = max(previous_dates)
            prev = daily[previous_date]
        else:
            sorted_dates = sorted(daily, reverse=True)
            if len(sorted_dates) < 2:
                return default_trend
            current_date, previous_date = sorted_dates[:2]
            current, prev = daily[current_date], daily[previous_date]

        current_score = _normalized_score(current)
        prev_score = _normalized_score(prev)
        if current_score is None or prev_score is None:
            return default_trend

        score_diff = current_score - prev_score
        momentum = round(score_diff, 3)

        if score_diff > 0.1:
            trend = "UP"
        elif score_diff < -0.1:
            trend = "DOWN"
        else:
            trend = "STABLE"
        
        current_label = current.get("label") or "Unknown"
        prev_label = prev.get("label") or "Unknown"
        recovery_signal = (
            prev_label == "Extreme Fear"
            and current_label in ["Fear", "Neutral", "Greed"]
            and score_diff > 0
        ) or (
            trend == "UP"
            and current_score < 0  # Vẫn còn bearish nhưng đang hồi phục
        )
        
        risk_signal = (
            prev_label == "Extreme Greed"
            and current_label in ["Greed", "Neutral", "Fear"]
            and score_diff < 0
        ) or (
            trend == "DOWN"
            and current_score > 0.6  # Vẫn còn bullish nhưng đang giảm
        )
        
        observations = dict(daily)
        observations[current_date] = current
        consecutive_extreme_days = 0
        expected_date = current_date
        while expected_date in observations:
            label = observations[expected_date].get("label", "")
            if label not in ("Extreme Fear", "Extreme Greed"):
                break
            consecutive_extreme_days += 1
            expected_date -= timedelta(days=1)

        return {
            "trend": trend,
            "daily_momentum": momentum,
            "momentum": momentum,
            "recovery_signal": recovery_signal,
            "risk_signal": risk_signal,
            "consecutive_extreme_days": consecutive_extreme_days,
            "hours_in_extreme": consecutive_extreme_days,
        }
    except Exception as e:
        print(f"  [Sentiment] Lỗi tính trend: {e}", flush=True)
        return default_trend
