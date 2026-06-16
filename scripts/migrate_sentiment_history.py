#!/usr/bin/env python3
"""Migrate sentiment history từ Alternative.me sang logs/sentiment_history.json.

Script này tải toàn bộ dữ liệu Fear & Greed từ API và lưu vào file history.
Dữ liệu xuất ra theo timestamp UTC ở dạng ISO.
"""

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "https://api.alternative.me/fng/?format=json&limit=2000"
HISTORY_PATH = Path("logs/sentiment_history.json")
KEEP_ENTRIES = None  # None = keep tất cả entries


def fetch_sentiment_history(limit: int = 2000) -> list[dict]:
    req = urllib.request.Request(API_URL, headers={"User-Agent": "besttime-crypto-bot/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode())

    data = []
    for item in payload.get("data", []):
        raw = int(item.get("value", 50))
        label = item.get("value_classification", "Neutral")
        ts = int(item.get("timestamp", 0))
        date = datetime.fromtimestamp(ts, tz=timezone.utc)
        score = round((raw - 50) / 50.0, 3)
        data.append({
            "timestamp": date.isoformat().replace("+00:00", "Z"),
            "raw_value": raw,
            "label": label,
            "score": score,
        })

    return sorted(data, key=lambda x: x["timestamp"])


def build_history_dict(entries: list[dict]) -> dict:
    history = {}
    for entry in entries:
        history[entry["timestamp"]] = {
            "score": entry["score"],
            "raw_value": entry["raw_value"],
            "label": entry["label"],
        }
    if KEEP_ENTRIES is not None and len(history) > KEEP_ENTRIES:
        sorted_keys = sorted(history.keys(), reverse=True)[:KEEP_ENTRIES]
        history = {k: history[k] for k in sorted_keys}
    return history


def main():
    print("Migrating sentiment history from Alternative.me...")
    entries = fetch_sentiment_history()
    print(f"Fetched {len(entries)} data points from API.")

    history = build_history_dict(entries)
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"Saved sentiment history to {HISTORY_PATH.resolve()}")
    print(f"Total entries: {len(history)}")


if __name__ == "__main__":
    main()
