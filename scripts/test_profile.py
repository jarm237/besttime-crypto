import sys
import os
import cProfile

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from btc_scraper.analysis import analyze_market
from backtest_april import load_candles_csv, WARMUP_CANDLES
from btc_scraper.meta_model import load_model

def run_test():
    obj = load_model()
    clf = obj.get("model") if isinstance(obj, dict) else obj
    if hasattr(clf, 'n_jobs'): clf.n_jobs = 1
    
    candles = load_candles_csv("BTC")
    window = candles[:WARMUP_CANDLES]
    
    # Run once to cache imports
    ana = analyze_market(window)
    
    def test_loop():
        for i in range(5):
            w = candles[i:i+WARMUP_CANDLES]
            a = analyze_market(w)
            
    cProfile.runctx('test_loop()', globals(), locals(), 'stats.prof')

if __name__ == "__main__":
    run_test()
