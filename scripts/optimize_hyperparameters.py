import os
import sys
import json
import numpy as np
import optuna

# Add project root to path first
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Mock sentiment to speed up backtest and avoid external requests
import btc_scraper.core.sentiment
def mock_get_market_sentiment():
    return {
        "score": -0.76,
        "label": "Extreme Fear",
        "raw_value": 12,
        "timestamp": 1718000000,
        "update_time_human": "2026-06-12 00:00:00"
    }
btc_scraper.sentiment.get_market_sentiment = mock_get_market_sentiment


from btc_scraper.core.config import COINS
from btc_scraper.analysis import analyze_all_market, calculate_tp_sl
from btc_scraper.ml_engine.signal_score import compute_kelly_fraction, _estimate_b
from btc_scraper.ml_engine.meta_model import load_model
from btc_scraper.ml_engine.feature_extractor import build_meta_features, FEATURE_SCHEMA

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
PARAMS_OUT = os.path.join(LOGS_DIR, "optimized_trading_params.json")

def load_candles(coin: str, month: str) -> list[dict]:
    filename = f"{month}_{coin}_15m.csv"
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return []
    candles = []
    import csv
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append({
                "time":   row["time"],
                "open":   float(row["open"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "close":  float(row["close"]),
                "volume": float(row["volume"]),
            })
    return candles

def pre_extract_candidates():
    print("Pre-extracting candidate trades and ML predictions across March, April, and May 2026...")
    model_obj = load_model()
    if model_obj is None:
        raise RuntimeError("Meta model not found. Run python train_model_v2.py or train_april_model.py first.")
    
    clf = model_obj.get("model") if isinstance(model_obj, dict) else model_obj
    feature_names = model_obj.get("features", FEATURE_SCHEMA) if isinstance(model_obj, dict) else FEATURE_SCHEMA

    candidates = []
    candles_db = {}
    months = ["march", "april", "may"]
    
    for coin in COINS:
        for month in months:
            candles = load_candles(coin, month)
            if not candles:
                continue
            
            candles_db[(coin, month)] = candles
            all_ana = analyze_all_market(candles)
            if not all_ana:
                continue

            WARMUP = 200
            for i in range(WARMUP, len(candles)):
                ana = all_ana[i - WARMUP]
                signal = ana.get("signal", "")
                s_upper = signal.upper()
                
                is_actionable = ("BUY" in s_upper or "SELL" in s_upper) and "NEUTRAL" not in s_upper
                if not is_actionable or "WEAK" in s_upper:
                    continue

                # Run static meta-model prediction once
                try:
                    feat = build_meta_features(ana)
                    row = [float(feat.get(k, 0.0)) for k in feature_names]
                    meta_prob = float(clf.predict_proba([row])[0, 1])
                except Exception:
                    meta_prob = 0.5

                candidates.append({
                    "coin": coin,
                    "month": month,
                    "entry_index": i,
                    "entry_time": candles[i]["time"],
                    "entry_price": candles[i]["close"],
                    "signal": signal,
                    "meta_prob": meta_prob,
                    "regime": ana.get("regime"),
                    "atr": ana.get("atr"),
                    "support": ana.get("support"),
                    "resistance": ana.get("resistance"),
                    "bb_upper": ana.get("bb_upper"),
                    "bb_middle": ana.get("bb_middle"),
                    "bb_lower": ana.get("bb_lower"),
                })
                
    # Sort candidates chronologically
    candidates.sort(key=lambda x: x["entry_time"])
    print(f"Loaded {len(candidates)} total candidate signals across all coins.")
    return candidates, candles_db

def run_simulation(candidates, candles_db, trial_params, base_capital=5000.0):
    import btc_scraper.analysis as ana_mod
    import btc_scraper.ml_engine.signal_score as ss_mod
    
    # Overwrite caches so imported library calls use our proposed trial params
    ana_mod._OPTIMIZED_PARAMS_CACHE = trial_params
    ss_mod._OPTIMIZED_PARAMS_CACHE = trial_params

    signal_cutoff = trial_params.get("signal_cutoff", 0.0)
    kelly_multiplier = trial_params.get("kelly_multiplier", 1.0)

    capital = base_capital
    peak_equity = base_capital
    drawdown_pct = 0.0
    consecutive_losses = 0

    active_trades = {}
    completed_trades = []

    for cand in candidates:
        coin = cand["coin"]
        month = cand["month"]
        entry_time = cand["entry_time"]
        entry_price = cand["entry_price"]
        meta_prob = cand["meta_prob"]
        regime = cand["regime"]

        # 1. Close any active trades that have exited BEFORE or AT entry_time
        closed_coins = []
        for acoin, atrade in active_trades.items():
            if atrade["exit_time"] <= entry_time:
                pnl_pct = atrade["pnl_pct"]
                invested = atrade["invested"]
                pnl_usd = invested * (pnl_pct / 100.0)
                # Apply 0.1% transaction fee on entry and exit
                fee_usd = (invested * 0.001) + ((invested + pnl_usd) * 0.001)
                net_pnl = pnl_usd - fee_usd
                
                capital += net_pnl
                if capital > peak_equity:
                    peak_equity = capital
                
                drawdown_pct = (peak_equity - capital) / peak_equity * 100.0
                
                if pnl_pct < 0:
                    consecutive_losses += 1
                else:
                    consecutive_losses = 0
                
                atrade["net_pnl"] = net_pnl
                atrade["capital_after"] = capital
                completed_trades.append(atrade)
                closed_coins.append(acoin)
        
        for acoin in closed_coins:
            del active_trades[acoin]

        # 2. Skip trade if coin is already in a trade
        if coin in active_trades:
            continue

        # 3. Drawdown filter (10.0% max drawdown limit)
        if drawdown_pct >= 10.0:
            continue

        # 4. Check signal cutoff filter
        if meta_prob < signal_cutoff:
            continue

        # 5. Position sizing (Kelly fraction adjusted)
        strategy = cand["signal"].split("(")[0].strip() if "(" in cand["signal"] else cand["signal"]
        b_est = _estimate_b(strategy, regime or '')
        kelly_raw = compute_kelly_fraction(meta_prob, b_est)

        # Apply sequential drawdown scaling
        risk_multiplier = 0.5 if consecutive_losses >= 3 else 1.0
        pos_fraction = kelly_raw * kelly_multiplier * risk_multiplier
        pos_fraction = min(0.5, pos_fraction) # Max fraction cap
        pos_fraction = max(0.0, pos_fraction)
        
        if pos_fraction <= 0:
            continue

        invested = capital * pos_fraction
        if invested <= 0 or capital <= 0:
            continue

        # 6. Calculate Dynamic TP/SL
        tp_sl_dict = calculate_tp_sl(
            close = entry_price,
            signal = cand["signal"],
            atr = cand["atr"],
            support = cand["support"],
            resistance = cand["resistance"],
            bb_upper = cand["bb_upper"],
            bb_middle = cand["bb_middle"],
            bb_lower = cand["bb_lower"],
            regime = regime,
        )

        sl = tp_sl_dict.get("sl", 0.0)
        tp1 = tp_sl_dict.get("tp1", 0.0)
        if sl <= 0 or tp1 <= 0:
            continue

        direction = "LONG" if "BUY" in cand["signal"].upper() else "SHORT"
        
        if direction == "LONG" and (sl >= entry_price or tp1 <= entry_price):
            continue
        if direction == "SHORT" and (sl <= entry_price or tp1 >= entry_price):
            continue

        # 7. Check subsequent candles to find exit price & time
        candles = candles_db[(coin, month)]
        entry_idx = cand["entry_index"]
        
        exit_time = None
        exit_price = None
        result = None
        
        for idx in range(entry_idx + 1, len(candles)):
            c = candles[idx]
            high = c["high"]
            low = c["low"]
            
            hit_sl = False
            hit_tp = False
            if direction == "LONG":
                hit_sl = low <= sl
                hit_tp = high >= tp1
            else:
                hit_sl = high >= sl
                hit_tp = low <= tp1
                
            if hit_sl or hit_tp:
                exit_price = sl if hit_sl else tp1
                result = "LOSS" if hit_sl else "WIN"
                exit_time = c["time"]
                break
        
        if result is None:
            continue

        if direction == "LONG":
            pnl_pct = (exit_price - entry_price) / entry_price * 100.0
        else:
            pnl_pct = (entry_price - exit_price) / entry_price * 100.0

        active_trades[coin] = {
            "coin": coin,
            "month": month,
            "direction": direction,
            "entry_time": entry_time,
            "exit_time": exit_time,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "sl": sl,
            "tp1": tp1,
            "invested": invested,
            "pnl_pct": pnl_pct,
            "result": result,
        }

    return completed_trades, capital

def objective_wrapper(candidates, candles_db):
    def objective(trial):
        atr_tp_mult = trial.suggest_float("atr_tp_mult", 2.0, 6.0)
        atr_sl_mult = trial.suggest_float("atr_sl_mult", 1.0, 3.0)
        signal_cutoff = trial.suggest_float("signal_cutoff", 0.50, 0.70)
        kelly_multiplier = trial.suggest_float("kelly_multiplier", 0.10, 1.0)

        regimes = [
            "STRONG_TREND_BULL",
            "STRONG_TREND_BEAR",
            "WEAK_TREND_BULL",
            "WEAK_TREND_BEAR",
            "RANGING",
            "HIGH_VOLATILITY",
            "COMPRESSION",
            "BREAKOUT",
            "MEAN_REVERSION",
            "PANIC_SELL",
            "PUMP_RISK",
        ]

        regime_tp_scale = {}
        regime_sl_scale = {}
        for regime in regimes:
            regime_tp_scale[regime] = trial.suggest_float(f"tp_scale_{regime}", 0.5, 2.0)
            regime_sl_scale[regime] = trial.suggest_float(f"sl_scale_{regime}", 0.5, 2.0)

        trial_params = {
            "atr_tp_mult": atr_tp_mult,
            "atr_sl_mult": atr_sl_mult,
            "signal_cutoff": signal_cutoff,
            "kelly_multiplier": kelly_multiplier,
            "regime_tp_scale": regime_tp_scale,
            "regime_sl_scale": regime_sl_scale,
        }

        trades, final_cap = run_simulation(candidates, candles_db, trial_params)

        if len(trades) < 15:
            return -10000.0 + len(trades)

        net_profit = final_cap - 5000.0
        net_profit_pct = net_profit / 5000.0 * 100.0

        if net_profit_pct <= 0:
            return net_profit_pct

        returns = [t["pnl_pct"] for t in trades]
        avg_ret = np.mean(returns)
        std_ret = np.std(returns)
        sharpe = (avg_ret / std_ret) if std_ret > 0 else 0.0

        # Reward both consistency (Sharpe) and absolute return
        score = net_profit_pct * (sharpe if sharpe > 0 else 0.1)
        return score
        
    return objective

def main():
    try:
        candidates, candles_db = pre_extract_candidates()
    except Exception as e:
        print(f"Error during pre-extraction: {e}")
        return

    study = optuna.create_study(direction="maximize")
    print("Running Bayesian optimization (200 trials)...")
    study.optimize(objective_wrapper(candidates, candles_db), n_trials=200)

    print("\nOptimization Complete!")
    print(f"Best Trial Score: {study.best_value:.4f}")
    
    best_params = study.best_params
    
    # Restructure back into parameters json schema
    regimes = [
        "STRONG_TREND_BULL",
        "STRONG_TREND_BEAR",
        "WEAK_TREND_BULL",
        "WEAK_TREND_BEAR",
        "RANGING",
        "HIGH_VOLATILITY",
        "COMPRESSION",
        "BREAKOUT",
        "MEAN_REVERSION",
        "PANIC_SELL",
        "PUMP_RISK",
    ]
    
    optimized_config = {
        "atr_tp_mult": round(best_params["atr_tp_mult"], 4),
        "atr_sl_mult": round(best_params["atr_sl_mult"], 4),
        "signal_cutoff": round(best_params["signal_cutoff"], 4),
        "kelly_multiplier": round(best_params["kelly_multiplier"], 4),
        "regime_tp_scale": {},
        "regime_sl_scale": {}
    }
    
    for r in regimes:
        optimized_config["regime_tp_scale"][r] = round(best_params[f"tp_scale_{r}"], 4)
        optimized_config["regime_sl_scale"][r] = round(best_params[f"sl_scale_{r}"], 4)

    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(PARAMS_OUT, "w", encoding="utf-8") as f:
        json.dump(optimized_config, f, indent=2, ensure_ascii=False)
        
    print(f"Successfully saved optimized hyperparameters to {PARAMS_OUT}")
    print("\nOptimized Parameters Summary:")
    print(json.dumps(optimized_config, indent=2))

if __name__ == "__main__":
    main()
