import sys
import os
import json
import time
from datetime import datetime

os.environ['DISABLE_KELLY'] = '1'

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from btc_scraper.analysis import analyze_market, analyze_all_market
from btc_scraper.config import COINS
from backtest_april import load_candles_csv, WARMUP_CANDLES, _is_actionable, BUY_MIN_SCORE, SELL_MAX_SCORE

from btc_scraper.meta_model import load_model
from btc_scraper.feature_extractor import build_meta_features, FEATURE_SCHEMA
import btc_scraper.sentiment

# Mock sentiment to speed up backtest
def mock_get_market_sentiment():
    return {
        "score": -0.76,
        "label": "Extreme Fear",
        "raw_value": 12,
        "timestamp": 1718000000,
        "update_time_human": "2026-06-12 00:00:00"
    }
btc_scraper.sentiment.get_market_sentiment = mock_get_market_sentiment
btc_scraper.analysis.get_market_sentiment = mock_get_market_sentiment

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
SHADOW_OUT = os.path.join(LOGS_DIR, "shadow_predictions.json")

def set_n_jobs_to_1(estimator):
    if hasattr(estimator, 'n_jobs'):
        estimator.n_jobs = 1
    if hasattr(estimator, 'estimator'):
        set_n_jobs_to_1(estimator.estimator)
    if hasattr(estimator, 'base_estimator'):
        set_n_jobs_to_1(estimator.base_estimator)
    if hasattr(estimator, 'best_estimator_'):
        set_n_jobs_to_1(estimator.best_estimator_)
    if hasattr(estimator, 'steps'):
        for name, step in estimator.steps:
            set_n_jobs_to_1(step)
    if hasattr(estimator, 'calibrated_classifiers_'):
        for est in estimator.calibrated_classifiers_:
            set_n_jobs_to_1(est)

def generate_shadow_logs():
    obj = load_model()
    if obj is None:
        print("Meta model not found. Run python -m btc_scraper.meta_model --train first.")
        return
        
    clf = obj.get("model") if isinstance(obj, dict) else obj
    set_n_jobs_to_1(clf)
    
    feature_names = obj.get("features", FEATURE_SCHEMA) if isinstance(obj, dict) else FEATURE_SCHEMA

    all_shadow_records = []
    
    for coin in COINS:
        csv_path = os.path.join(DATA_DIR, f"april_{coin}_15m.csv")
        if not os.path.exists(csv_path):
            continue
            
        print(f"[{coin}] Processing...")
        candles = load_candles_csv(coin)
        n = len(candles)
        if n < WARMUP_CANDLES + 2:
            continue
            
        position = None
        
        all_ana = analyze_all_market(candles)
        
        for i in range(WARMUP_CANDLES, n):
            if i % 500 == 0:
                print(f"  Processed {i}/{n} candles")
            candle = candles[i]
            high = candle["high"]
            low = candle["low"]
            close = candle["close"]
            
            if position is not None:
                sl = position["sl"]
                tp1 = position["tp1"]
                direction = position["direction"]
                entry = position["entry"]
                
                hit_sl = False
                hit_tp1 = False
                if direction == "LONG":
                    hit_sl = low <= sl
                    hit_tp1 = high >= tp1
                else:
                    hit_sl = high >= sl
                    hit_tp1 = low <= tp1
                    
                if hit_sl or hit_tp1:
                    exit_price = sl if hit_sl else tp1
                    result = "LOSS" if hit_sl else "WIN"
                    if direction == "LONG":
                        pnl_pct = (exit_price - entry) / entry * 100
                    else:
                        pnl_pct = (entry - exit_price) / entry * 100
                    
                    # Store shadow record
                    rec = position["shadow_record"]
                    rec["actual_result"] = result
                    rec["actual_pnl_pct"] = round(pnl_pct, 4)
                    rec["closed_at"] = candle["time"]
                    all_shadow_records.append(rec)
                    
                    position = None
                    
            if position is None:
                ana = all_ana[i - WARMUP_CANDLES]
                signal = ana.get("signal", "")
                if not _is_actionable(signal):
                    continue
                    
                sig_score_info = ana.get("signal_score", {}) or {}
                score = sig_score_info.get("score", 0) or 0
                action = sig_score_info.get("action", "NEUTRAL")
                
                if "WEAK" in signal.upper(): continue
                if action == "BUY" and score < BUY_MIN_SCORE: continue
                if action == "SELL" and score > SELL_MAX_SCORE: continue
                if action == "NEUTRAL": continue
                
                tp_sl = ana.get("tp_sl", {})
                sl = tp_sl.get("sl", 0.0)
                tp1 = tp_sl.get("tp1", 0.0)
                if sl <= 0 or tp1 <= 0: continue
                
                direction = "LONG" if "BUY" in signal.upper() else "SHORT"
                if direction == "LONG" and (sl >= close or tp1 <= close): continue
                if direction == "SHORT" and (sl <= close or tp1 >= close): continue
                
                # Predict meta probability
                try:
                    feat = build_meta_features(ana)
                    row = [float(feat.get(k, 0.0)) for k in feature_names]
                    prob = float(clf.predict_proba([row])[0, 1])
                except Exception as e:
                    prob = 0.5
                    
                regime = ana.get("market_regime", "UNKNOWN")
                
                # Parse timestamp safely
                try:
                    ts = datetime.strptime(candle["time"], "%Y-%m-%d %H:%M").timestamp()
                except:
                    ts = time.time()
                


                shadow_record = {
                    "prediction_id": f"{coin}_{int(time.time()*1000)}_{i}",
                    "symbol": coin,
                    "timestamp": ts,
                    "timestamp_str": candle["time"],
                    "signal": signal,
                    "meta_prob": round(prob, 4),
                    "signal_score": score,
                    "regime": regime,
                    "htf_trend": "",
                    "position_id": f"SIM_{coin}_{i}",
                    "actual_result": None,
                    "actual_pnl_pct": None,
                    "closed_at": None
                }
                
                position = {
                    "entry": close,
                    "sl": sl,
                    "tp1": tp1,
                    "direction": direction,
                    "shadow_record": shadow_record
                }

    print(f"Generated {len(all_shadow_records)} shadow records.")
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(SHADOW_OUT, "w", encoding="utf-8") as f:
        json.dump(all_shadow_records, f, ensure_ascii=False, indent=2)
    print(f"Saved to {SHADOW_OUT}")

if __name__ == "__main__":
    generate_shadow_logs()
    
    # Run calibration report
    from scripts.shadow_log import calibration_report
    report = calibration_report()
    if report["status"] == "no_data":
        print(f"\n⏳ {report['message']}")
    else:
        print(f"\n📊 Meta Model Calibration Report (APRIL DATA)")
        print(f"   Completed: {report['total_completed']} | Pending: {report['total_pending']}")
        print(f"   Overall Win Rate: {report['overall_win_rate']}%")
        print()
        print(f"   {'Bucket':<12} {'Count':<8} {'Predicted WR':<15} {'Actual WR':<12} {'Error':<10} {'OK?'}")
        print("   " + "-" * 65)
        for bucket, data in report["buckets"].items():
            if data.get("actual_wr") is not None:
                ok = "✅" if data.get("calibrated") else "❌"
                print(f"   {bucket:<12} {data['count']:<8} {data['predicted_wr']:<15.1f} {data['actual_wr']:<12.1f} {data['calibration_error']:+.1f}%     {ok}")
            else:
                print(f"   {bucket:<12} {data['count']:<8} {'N/A':<15} {'N/A':<12} {'N/A':<10} ⏳")
        print()
        monotonic = report.get("monotonic_calibration")
        if monotonic is not None:
            print(f"   Monotonic: {'✅ Có' if monotonic else '❌ Không'}")
        print(f"\n   {report['recommendation']}")
