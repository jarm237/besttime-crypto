import json
from pathlib import Path
from btc_scraper.core.sentiment import get_historical_sentiment_map

print("Fetching historical sentiment data (1000 days)...")
history = get_historical_sentiment_map(limit=1000)
print(f"Fetched {len(history)} days of sentiment data.")

out_file = Path("logs/sentiment_history.json")
out_file.parent.mkdir(exist_ok=True, parents=True)

# Try to merge with existing data
try:
    with open(out_file, "r", encoding="utf-8") as f:
        existing = json.load(f)
except Exception:
    existing = {}

# We format the keys as YYYY-MM-DDT00:00:00Z to match the expected schema if needed,
# though YYYY-MM-DD is fine as well based on build_and_train.py.
# We'll just write YYYY-MM-DD for simplicity as the parser just takes k[:10].
merged = {**existing}
merged.update(history)

with open(out_file, "w", encoding="utf-8") as f:
    json.dump(merged, f, indent=2, ensure_ascii=False)

print(f"Saved {len(merged)} sentiment records to {out_file}")
