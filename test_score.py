import sys
import os
import json
sys.path.append(os.path.abspath("."))
from btc_scraper.signal_score import evaluate_signal_score

analysis = {"signal": "BUY", "close": 60000, "rsi": 30, "macd": 100, "macd_signal": 50, "macd_hist": 50, "bb_upper": 65000, "bb_lower": 55000, "regime": "RANGING"}
res = evaluate_signal_score(analysis)
print(json.dumps(res, indent=2))
