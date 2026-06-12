import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Set paths
BASE_DIR = Path(__file__).parent.parent
CSV_FILE = BASE_DIR / "logs" / "backtest_trades.csv"
SHADOW_LOG = BASE_DIR / "logs" / "shadow_predictions.json"

def main():
    if not CSV_FILE.exists():
        print(f"❌ Không tìm thấy file {CSV_FILE}")
        return

    print(f"Reading historical backtest trades from {CSV_FILE}...")
    
    shadow_records = []
    
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            coin = row["coin"]
            trade_type = row["type"] # LONG or SHORT
            entry_time = row["entry_time"]
            exit_time = row["exit_time"]
            entry_price = float(row["entry_price"])
            exit_price = float(row["exit_price"])
            
            # Parse signal_score JSON field
            ss_str = row["signal_score"]
            try:
                ss = json.loads(ss_str)
            except Exception as e:
                print(f"Skip row due to JSON parse error: {e}")
                continue
                
            meta_prob = ss.get("meta_confidence")
            if meta_prob is None:
                continue
                
            # Compute actual pnl pct
            if trade_type == "LONG":
                pnl_pct = (exit_price - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - exit_price) / entry_price * 100
                
            actual_result = "WIN" if pnl_pct > 0 else "LOSS"
            
            # Convert timestamp
            try:
                entry_dt = datetime.strptime(entry_time, "%Y-%m-%d %H:%M")
                timestamp = time.mktime(entry_dt.timetuple())
            except Exception:
                timestamp = time.time()
                
            prediction_id = f"{coin}_{int(timestamp)}"
            
            record = {
                "prediction_id": prediction_id,
                "symbol": f"{coin}USDT",
                "timestamp": timestamp,
                "timestamp_str": entry_time,
                "signal": ss.get("raw_text") or ss.get("action") or trade_type,
                "meta_prob": round(float(meta_prob), 4),
                "signal_score": int(ss.get("score") or 50),
                "regime": "",
                "htf_trend": "",
                "position_id": coin,
                "actual_result": actual_result,
                "actual_pnl_pct": round(pnl_pct, 4),
                "closed_at": exit_time
            }
            shadow_records.append(record)
            
    print(f"Successfully parsed {len(shadow_records)} historical trades.")
    
    # Save to shadow log
    SHADOW_LOG.parent.mkdir(exist_ok=True)
    with open(SHADOW_LOG, "w", encoding="utf-8") as f:
        json.dump(shadow_records, f, ensure_ascii=False, indent=2)
        
    print(f"Saved shadow records to {SHADOW_LOG}.")
    print("\n--- Running Calibration Report ---\n")
    
    # Import and run report
    sys.path.insert(0, str(BASE_DIR))
    from scripts.calibration_report import main as run_report
    run_report()

if __name__ == "__main__":
    main()
