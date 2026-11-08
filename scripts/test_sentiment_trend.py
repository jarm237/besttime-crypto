#!/usr/bin/env python3
"""Manual diagnostic for sentiment trend tracking and recovery signals."""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from btc_scraper.core.paths import build_logs_path
from btc_scraper.core.sentiment import (
    _save_sentiment_to_history,
    get_market_sentiment,
    get_sentiment_trend,
)


def main() -> int:
    """Run the diagnostic without performing network or file I/O on import."""
    print("=" * 60)
    print("TEST: Sentiment Trend Tracking & Recovery Signal")
    print("=" * 60)

    sentiment = get_market_sentiment()
    score = sentiment.get("score")
    score_display = f"{score:+.2f}" if score is not None else "N/A"
    raw_value = sentiment.get("raw_value")
    raw_display = str(raw_value) if raw_value is not None else "N/A"
    print("\n[1] Current Sentiment:")
    print(f"    Score: {score_display} (0-100: {raw_display})")
    print(f"    Label: {sentiment.get('label', 'Unknown')}")

    _save_sentiment_to_history(sentiment)
    hist_file = build_logs_path("sentiment_history.json")
    print(f"\n[2] Saved to history: {hist_file}")

    if hist_file.exists():
        with open(hist_file, encoding="utf-8") as history_stream:
            history = json.load(history_stream)
        print(f"    Total entries: {len(history)}")
        if history:
            recent = list(history.items())[-3:]
            print("    Recent 3 entries:")
            for timestamp, data in recent:
                print(
                    f"      {timestamp}: {data.get('raw_value', 'N/A')}/100 "
                    f"({data.get('label', 'Unknown')})"
                )
    else:
        print("    Warning: File not found!")

    trend = get_sentiment_trend()
    momentum = trend["momentum"]
    momentum_display = f"{momentum:+.3f}" if momentum is not None else "N/A"
    print("\n[3] Sentiment Trend:")
    print(f"    Direction: {trend['trend']} (momentum: {momentum_display})")
    print(f"    Recovery Signal: {trend['recovery_signal']}")
    print(f"    Risk Signal: {trend['risk_signal']}")
    print(f"    Hours in Extreme: {trend['hours_in_extreme']}")

    print("\n[4] Meaning:")
    if trend["recovery_signal"]:
        print("    Market RECOVERING from extreme fear: BOOST long signals!")
    elif trend["risk_signal"]:
        print("    Market DECLINING from extreme greed: REDUCE long signals!")
    elif trend["trend"] == "UP":
        print("    Sentiment improving: More favorable for longs")
    elif trend["trend"] == "DOWN":
        print("    Sentiment worsening: Less favorable for longs")
    else:
        print("    Sentiment stable, no strong trend")

    print("\n" + "=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
