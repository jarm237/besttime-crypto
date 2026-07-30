"""
Run quick backtest split by detected regime and produce `regime_stats.json`.

This script scans a set of coins, analyzes their markets, simulates short-hold
outcomes (hold=4 candles by default) and computes win rates per signal
sub-type grouped by regime.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

from btc_scraper.analysis import analyze_all_market, calculate_tp_sl


def classify_signal(sig: str) -> tuple[str, str]:
    if not sig or "NEUTRAL" in sig:
        return None, None
    direction = None
    if "BUY" in sig:
        direction = "LONG"
    elif "SELL" in sig:
        direction = "SHORT"
    else:
        return None, None

    strength = "WEAK" if "WEAK" in sig else "STRONG"

    sub = "OTHER"
    if "Reversal" in sig:
        sub = "RSI_Reversal"
    elif "Crossover" in sig:
        sub = "EMA_Crossover"
    elif "SFP" in sig:
        sub = "SFP"
    elif "Pullback" in sig:
        sub = "SFP"
    elif "Break-SMA50" in sig or "Break-SMA50".upper() in sig.upper():
        sub = "Break_SMA50"
    elif "Counter" in sig:
        sub = "Counter_Trend"

    return f"{strength}_{direction}", sub


def simulate_outcome(
    results,
    sig_idx: int,
    direction: str,
    sl: float,
    tp1: float,
    tp2: float,
    hold: int,
    same_candle_policy: str = "CONSERVATIVE_SL_FIRST",
) -> tuple[str, float]:
    n = len(results)
    entry = results[sig_idx]["close"]
    if entry <= 0:
        return "SKIP", 0.0

    hit_price = results[min(sig_idx + hold, n - 1)]["close"]
    outcome = "TIMEOUT"

    for j in range(sig_idx + 1, min(sig_idx + hold + 1, n)):
        h = results[j].get("high", results[j]["close"])
        l = results[j].get("low", results[j]["close"])

        if direction == "LONG":
            sl_hit = sl > 0 and l <= sl
            tp2_hit = tp2 > 0 and h >= tp2
            tp1_hit = tp1 > 0 and h >= tp1
            if sl_hit and (tp1_hit or tp2_hit):
                if same_candle_policy == "AMBIGUOUS_EXCLUDE":
                    return "AMBIGUOUS", 0.0
                if same_candle_policy == "OPTIMISTIC_TP_FIRST":
                    sl_hit = False
            if sl_hit:
                outcome, hit_price = "SL", sl
                break
            if tp2_hit:
                outcome, hit_price = "TP2", tp2
                break
            if tp1_hit:
                outcome, hit_price = "TP1", tp1
                break
        else:
            sl_hit = sl > 0 and h >= sl
            tp2_hit = tp2 > 0 and l <= tp2
            tp1_hit = tp1 > 0 and l <= tp1
            if sl_hit and (tp1_hit or tp2_hit):
                if same_candle_policy == "AMBIGUOUS_EXCLUDE":
                    return "AMBIGUOUS", 0.0
                if same_candle_policy == "OPTIMISTIC_TP_FIRST":
                    sl_hit = False
            if sl_hit:
                outcome, hit_price = "SL", sl
                break
            if tp2_hit:
                outcome, hit_price = "TP2", tp2
                break
            if tp1_hit:
                outcome, hit_price = "TP1", tp1
                break

    if direction == "LONG":
        pnl = (hit_price - entry) / entry * 100
    else:
        pnl = (entry - hit_price) / entry * 100

    return outcome, pnl

COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "NEAR", "XLM", "AVAX", "DOGE"]
HOLD = 4  # number of candles to hold


def run_regime_backtest(
    out_path: str = "btc_scraper/regime/regime_stats.json",
    same_candle_policy: str = "CONSERVATIVE_SL_FIRST",
):
    stats = defaultdict(
        lambda: defaultdict(
            lambda: {"total": 0, "economic_wins": 0, "target_hit_wins": 0, "pnl_sum": 0.0}
        )
    )

    for coin in COINS:
        try:
            from btc_scraper.exchanges.binance import fetch_ohlcv_tf
        except Exception:
            print("fetch_ohlcv_tf not available; skipping live fetch for", coin)
            continue

        candles = fetch_ohlcv_tf(coin, "15m", limit=1000)
        if not candles or "error" in candles[0]:
            continue
        results = analyze_all_market(candles)
        if not results:
            continue

        # iterate through results minus HOLD to allow simulation window
        for i in range(0, len(results) - HOLD):
            r = results[i]
            sig = r.get("signal", "")
            direction_group, sub = classify_signal(sig)
            if direction_group is None or sub is None:
                continue

            sl = r.get("tp_sl", {}).get("sl", 0.0)
            tp1 = r.get("tp_sl", {}).get("tp1", 0.0)
            tp2 = r.get("tp_sl", {}).get("tp2", 0.0)
            direction = "LONG" if "BUY" in sig.upper() else "SHORT"

            outcome, pnl = simulate_outcome(
                results, i, direction, sl, tp1, tp2, HOLD, same_candle_policy=same_candle_policy
            )
            if outcome == "AMBIGUOUS":
                continue

            regime = r.get("regime") or r.get("market_regime") or "UNKNOWN"
            key = sub
            stats[key][regime]["total"] += 1
            stats[key][regime]["pnl_sum"] += float(pnl or 0.0)
            if pnl > 0:
                stats[key][regime]["economic_wins"] += 1
            if outcome in ("TP1", "TP2"):
                stats[key][regime]["target_hit_wins"] += 1

    # convert to detailed metrics and write JSON + CSV
    out = {}
    rows = []
    for strat, by_reg in stats.items():
        out[strat] = {}
        for regime, vals in by_reg.items():
            total = vals.get("total", 0)
            wins = vals.get("economic_wins", 0)
            target_hit_wins = vals.get("target_hit_wins", 0)
            losses = total - wins
            avg_pnl = round((vals.get("pnl_sum", 0.0) / total), 4) if total > 0 else None
            wr = round(wins / total, 4) if total > 0 else None
            out[strat][regime] = {
                "total": total,
                "wins": wins,
                "economic_wins": wins,
                "target_hit_wins": target_hit_wins,
                "losses": losses,
                "win_rate": wr,
                "economic_win_rate": wr,
                "target_hit_rate": round(target_hit_wins / total, 4) if total > 0 else None,
                "avg_pnl": avg_pnl,
                "same_candle_policy": same_candle_policy,
            }
            rows.append((strat, regime, total, wins, losses, wr, avg_pnl))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    # write JSON
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)

    # write CSV detailed file alongside JSON
    csv_path = os.path.splitext(out_path)[0] + "_detailed.csv"
    try:
        import csv

        with open(csv_path, "w", newline="") as cf:
            writer = csv.writer(cf)
            writer.writerow(["strategy", "regime", "total", "wins", "losses", "win_rate", "avg_pnl"])
            for r in rows:
                writer.writerow(r)
    except Exception:
        pass

    print(f"Wrote regime stats to {out_path} and {csv_path}")


if __name__ == "__main__":
    run_regime_backtest()
