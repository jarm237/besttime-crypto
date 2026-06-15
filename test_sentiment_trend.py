#!/usr/bin/env python3
"""
Test script: Kiểm tra sentiment_trend tracking & recovery signal
"""
import json
import time
from pathlib import Path
from btc_scraper.core.sentiment import (
    get_market_sentiment, 
    _save_sentiment_to_history,
    get_sentiment_trend
)

print("=" * 60)
print("TEST: Sentiment Trend Tracking & Recovery Signal")
print("=" * 60)

# 1. Lấy sentiment hiện tại
sentiment = get_market_sentiment()
print(f"\n[1] Current Sentiment:")
print(f"    Score: {sentiment['score']:+.2f} (0-100: {sentiment['raw_value']})")
print(f"    Label: {sentiment['label']}")

# 2. Lưu vào history
_save_sentiment_to_history(sentiment)
print(f"\n[2] Saved to history: logs/sentiment_history.json")

# 3. Check history file
hist_file = Path("logs/sentiment_history.json")
if hist_file.exists():
    with open(hist_file) as f:
        history = json.load(f)
    print(f"    Total entries: {len(history)}")
    if history:
        recent = list(history.items())[-3:]
        print(f"    Recent 3 entries:")
        for ts, data in recent:
            print(f"      {ts}: {data['raw_value']}/100 ({data['label']})")
else:
    print(f"    ⚠ File not found!")

# 4. Tính sentiment trend
trend = get_sentiment_trend()
print(f"\n[3] Sentiment Trend:")
print(f"    Direction: {trend['trend']} (momentum: {trend['momentum']:+.3f})")
print(f"    Recovery Signal: {trend['recovery_signal']}")
print(f"    Risk Signal: {trend['risk_signal']}")
print(f"    Hours in Extreme: {trend['hours_in_extreme']}")

# 5. Ý nghĩa
print(f"\n[4] Meaning:")
if trend['recovery_signal']:
    print(f"    ✓ Market RECOVERING from extreme fear → BOOST long signals!")
elif trend['risk_signal']:
    print(f"    ⚠ Market DECLINING from extreme greed → REDUCE long signals!")
elif trend['trend'] == 'UP':
    print(f"    ↑ Sentiment improving → More favorable for longs")
elif trend['trend'] == 'DOWN':
    print(f"    ↓ Sentiment worsening → Less favorable for longs")
else:
    print(f"    → Sentiment stable, no strong trend")

print("\n" + "=" * 60)
