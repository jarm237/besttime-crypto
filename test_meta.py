import sys
import os
sys.path.append(os.path.abspath("."))
from btc_scraper.meta_model import predict_meta_confidence
analysis = {"signal": "BUY", "close": 60000, "rsi": 30, "macd": 100, "macd_signal": 50, "macd_hist": 50, "bb_upper": 65000, "bb_lower": 55000}
print(predict_meta_confidence(analysis))
