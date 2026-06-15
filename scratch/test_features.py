from btc_scraper.exchanges.binance import fetch_ohlcv_tf
from btc_scraper.analysis.core import analyze_all_market
import time

def main():
    print("Fetching data from Binance...")
    try:
        # Fetch 500 candles to give enough room for SMA200 and SMC
        candles = fetch_ohlcv_tf("BTC", "15m", limit=500)
    except Exception as e:
        print(f"Error fetching data: {e}")
        return

    print(f"Fetched {len(candles)} candles. Running analyze_all_market...")
    results = analyze_all_market(candles)

    if not results:
        print("No results returned.")
        return

    print(f"Analyzed {len(results)} candles.")
    
    # Check the last 10 candles
    print("\n--- SMC & Momentum Features (Last 10 candles) ---")
    for res in results[-10:]:
        print(f"Time: {res['time']}, Close: {res['close']:.2f}, BOS(Bull/Bear): {res['bos_bull']}/{res['bos_bear']}, CHOCH(Bull/Bear): {res['choch_bull']}/{res['choch_bear']}")
        print(f"   -> ROC_14: {res['roc_14']:.2f}%, HV20: {res['hv20']:.2f}%")
        print("-" * 50)

if __name__ == "__main__":
    main()
