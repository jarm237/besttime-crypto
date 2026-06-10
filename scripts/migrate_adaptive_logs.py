import json
import os
import sys

# Add root project dir to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from btc_scraper.adaptive_scoring import log_trade_outcome

BASE = os.path.dirname(__file__)
CLOSED_POSITIONS_LOG = os.path.join(BASE, "..", "logs", "closed_positions.json")

def migrate():
    if not os.path.exists(CLOSED_POSITIONS_LOG):
        print(f"File not found: {CLOSED_POSITIONS_LOG}")
        return

    with open(CLOSED_POSITIONS_LOG, "r", encoding="utf-8") as f:
        try:
            closed_positions = json.load(f)
        except json.JSONDecodeError:
            print("Invalid JSON format in closed_positions.json")
            return

    count = 0
    for pos in closed_positions:
        # log_trade_outcome appends to adaptive_signals.json
        log_trade_outcome(pos)
        count += 1

    print(f"Successfully migrated {count} records to adaptive_signals.json.")

if __name__ == "__main__":
    migrate()
