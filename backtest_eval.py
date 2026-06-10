"""
Backtest v2 - Danh gia chien luoc ky thuat chinh xac hon
- Fix bug TP1 logic (break ngay sau TP1, giu nguyen SL goc)
- Test voi nhieu hold period khac nhau: 4, 8, 16, 24 ner
- Ket qua theo tung loai tin hieu va tung sub-type (RSI, Crossover, SFP, Pullback)
- 1000 ner per coin de co du sample
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from btc_scraper.exchanges.binance import fetch_ohlcv_tf
from btc_scraper.analysis import analyze_all_market, calculate_tp_sl

COINS   = ["BTC", "ETH", "BNB", "SOL", "XRP", "NEAR", "XLM", "AVAX", "DOGE", "AVAX"]
HOLDS   = [4, 8, 16, 24]   # nến (1h, 2h, 4h, 6h)
VARIANTS = [
    {"name": "baseline", "buy_tp1_mult": 3.5, "sell_tp1_mult": 3.5, "skip_weak_buy": False},
    {"name": "buy_tp1_2.0", "buy_tp1_mult": 2.0, "sell_tp1_mult": 3.5, "skip_weak_buy": False},
    {"name": "sell_tp1_5.0", "buy_tp1_mult": 3.5, "sell_tp1_mult": 5.0, "skip_weak_buy": False},
    {"name": "no_weak_buy", "buy_tp1_mult": 3.5, "sell_tp1_mult": 3.5, "skip_weak_buy": True},
    {"name": "combo", "buy_tp1_mult": 2.0, "sell_tp1_mult": 5.0, "skip_weak_buy": True},
]

def classify_signal(sig: str) -> tuple[str, str]:
    """Trả về (direction, sub_type) hoặc (None, None) nếu là NEUTRAL."""
    if "NEUTRAL" in sig:
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
        sub = "SFP"  # treat same
    elif "Break-SMA50" in sig:
        sub = "Break_SMA50"
    elif "Counter" in sig:
        sub = "Counter_Trend"

    return f"{strength}_{direction}", sub


def simulate_outcome(results, sig_idx: int, direction: str, sl: float, tp1: float, tp2: float, hold: int) -> tuple[str, float]:
    """
    Giả lập outcome của lệnh từ sig_idx, hold tối đa 'hold' nến.
    Trả về (outcome, pnl_pct).
    FIX: Sau khi chạm TP1, BREAK ngay (không tiếp tục check SL).
    """
    n = len(results)
    entry = results[sig_idx]["close"]
    if entry <= 0:
        return "SKIP", 0.0

    hit_price = results[min(sig_idx + hold, n - 1)]["close"]
    outcome = "TIMEOUT"

    for j in range(sig_idx + 1, min(sig_idx + hold + 1, n)):
        h = results[j].get("high", results[j]["close"])
        l = results[j].get("low",  results[j]["close"])

        if direction == "LONG":
            if sl > 0 and l <= sl:
                outcome, hit_price = "SL", sl
                break
            if tp2 > 0 and h >= tp2:
                outcome, hit_price = "TP2", tp2
                break
            if tp1 > 0 and h >= tp1:   # FIX: BREAK ngay khi TP1 hit
                outcome, hit_price = "TP1", tp1
                break
        else:  # SHORT
            if sl > 0 and h >= sl:
                outcome, hit_price = "SL", sl
                break
            if tp2 > 0 and l <= tp2:
                outcome, hit_price = "TP2", tp2
                break
            if tp1 > 0 and l <= tp1:
                outcome, hit_price = "TP1", tp1
                break

    if direction == "LONG":
        pnl = (hit_price - entry) / entry * 100
    else:
        pnl = (entry - hit_price) / entry * 100

    return outcome, pnl


def _override_tp1_from_variant(r: dict, variant: dict) -> tuple[float, float]:
    from btc_scraper.signal_score import extract_signal_fields
    sig_fields = extract_signal_fields(r)
    signal = str(r.get("signal", sig_fields.get("raw", ""))).upper()
    direction = "LONG" if "BUY" in signal else "SHORT"
    if direction == "LONG":
        tp = calculate_tp_sl(
            close=r["close"],
            signal=r["signal"],
            atr=r.get("atr", 0.0),
            support=r.get("support", 0.0),
            resistance=r.get("resistance", 0.0),
            bb_upper=r.get("bb_upper", 0.0),
            bb_middle=r.get("bb_middle", 0.0),
            bb_lower=r.get("bb_lower", 0.0),
            atr_tp_mult=variant["buy_tp1_mult"],
        )
    else:
        tp = calculate_tp_sl(
            close=r["close"],
            signal=r["signal"],
            atr=r.get("atr", 0.0),
            support=r.get("support", 0.0),
            resistance=r.get("resistance", 0.0),
            bb_upper=r.get("bb_upper", 0.0),
            bb_middle=r.get("bb_middle", 0.0),
            bb_lower=r.get("bb_lower", 0.0),
            atr_tp_mult=variant["sell_tp1_mult"],
        )
    return tp["tp1"], r["tp_sl"]["tp2"]


def run_backtest():
    print("\n" + "="*72)
    print("  BACKTEST v2 — CHIEN LUOC KY THUAT (1000 ner 15m)")
    print("  Fix: TP1 break ngay | Test 4 hold period | Sub-type analysis")
    print("="*72)

    all_stats = {v["name"]: {h: {} for h in HOLDS} for v in VARIANTS}
    total_candles_processed = 0

    for coin in COINS:
        print(f"\n[{coin}] Loading 1000 ner...", end=" ")
        candles = fetch_ohlcv_tf(coin, "15m", limit=1000)
        if not candles or "error" in candles[0]:
            print("ERROR")
            continue
        results = analyze_all_market(candles)
        if not results:
            print("khong du du lieu")
            continue
        print(f"OK — {len(results)} ner phan tich")
        total_candles_processed += len(results)

        # Voi moi hold period
        for hold in HOLDS:
            eval_results = results[:len(results) - hold]

            from btc_scraper.signal_score import extract_signal_fields
            for i, r in enumerate(eval_results):
                        sig_fields = extract_signal_fields(r)
                        sig = r.get("signal", sig_fields.get("raw", ""))
                direction_group, sub = classify_signal(sig)
                if direction_group is None:
                    continue

                for variant in VARIANTS:
                    if variant["skip_weak_buy"] and "WEAK BUY" in sig.upper():
                        continue

                    sl = r["tp_sl"]["sl"]
                    tp1, tp2 = _override_tp1_from_variant(r, variant)
                    direction = "LONG" if "LONG" in direction_group else "SHORT"

                    outcome, pnl = simulate_outcome(results, i, direction, sl, tp1, tp2, hold)

                    stats = all_stats[variant["name"]][hold]
                    key = direction_group
                    if key not in stats:
                        stats[key] = {}
                    if sub not in stats[key]:
                        stats[key][sub] = {
                            "total": 0,
                            "wins": 0,
                            "pnl_list": [],
                            "outcomes": {}
                        }
                    s = stats[key][sub]
                    s["total"] += 1
                    s["pnl_list"].append(pnl)
                    s["outcomes"][outcome] = s["outcomes"].get(outcome, 0) + 1
                    if pnl > 0:
                        s["wins"] += 1

    print("\n\n" + "="*72)
    print("  KET QUA THEO HOLD PERIOD")
    print("="*72)

    for variant in VARIANTS:
        print(f"\n=== VARIANT: {variant['name']} (buy_tp1={variant['buy_tp1_mult']} sell_tp1={variant['sell_tp1_mult']} skip_weak_buy={variant['skip_weak_buy']}) ===")
        for hold in HOLDS:
            print(f"\n--- Hold = {hold} ner ({hold * 15}ph) ---")
            print(f"  {'Nhom':25s} | {'Sub':15s} | {'Total':>5} | {'WR%':>6} | {'AvgPnL':>8} | {'Outcomes'}")
            print("  " + "-"*90)

            stats_hold = all_stats[variant['name']][hold]
            group_agg = {}
            for group, subs in sorted(stats_hold.items()):
                for sub, s in subs.items():
                    if group not in group_agg:
                        group_agg[group] = {"total": 0, "wins": 0, "pnl_list": [], "outcomes": {}}
                    ga = group_agg[group]
                    ga["total"]    += s["total"]
                    ga["wins"]     += s["wins"]
                    ga["pnl_list"] += s["pnl_list"]
                    for k, v in s["outcomes"].items():
                        ga["outcomes"][k] = ga["outcomes"].get(k, 0) + v

                for sub, s in sorted(subs.items()):
                    if s["total"] == 0:
                        continue
                    wr = s["wins"] / s["total"] * 100
                    avg_pnl = sum(s["pnl_list"]) / len(s["pnl_list"])
                    outs = " ".join(f"{k}={v}" for k, v in sorted(s["outcomes"].items()))
                    print(f"  {group:25s} | {sub:15s} | {s['total']:>5} | {wr:>5.1f}% | {avg_pnl:>+7.3f}% | {outs}")

            print("  " + "-"*90)
            print("  TONG HOP:")
            for group, ga in sorted(group_agg.items()):
                wr = ga["wins"] / ga["total"] * 100 if ga["total"] > 0 else 0
                avg_pnl = sum(ga["pnl_list"]) / len(ga["pnl_list"]) if ga["pnl_list"] else 0
                wins_pnl = sum(p for p in ga["pnl_list"] if p > 0)
                loss_pnl = abs(sum(p for p in ga["pnl_list"] if p < 0))
                pf = wins_pnl / loss_pnl if loss_pnl > 0 else 999
                outs = " ".join(f"{k}={v}" for k, v in sorted(ga["outcomes"].items()))
                print(f"  {group:25s} | {'ALL':15s} | {ga['total']:>5} | {wr:>5.1f}% | {avg_pnl:>+7.3f}% | PF={pf:.2f} | {outs}")

    print(f"\n  Tong ner da phan tich: {total_candles_processed}")
    print("\n" + "="*72)

    for variant in VARIANTS:
        print(f"\n  TIM HOLD PERIOD TOI UU CHO STRONG_LONG (BUY) — {variant['name']}")
        for hold in HOLDS:
            ga = {}
            stats_hold = all_stats[variant['name']][hold]
            for group, subs in stats_hold.items():
                if group == "STRONG_LONG":
                    for sub, s in subs.items():
                        ga["total"]    = ga.get("total", 0) + s["total"]
                        ga["wins"]     = ga.get("wins", 0) + s["wins"]
                        ga["pnl_list"] = ga.get("pnl_list", []) + s["pnl_list"]
            if ga.get("total", 0) > 0:
                wr = ga["wins"] / ga["total"] * 100
                avg = sum(ga["pnl_list"]) / len(ga["pnl_list"])
                print(f"  Hold {hold:2d} ner ({hold*15:3d}ph): Total={ga['total']:3d} WR={wr:5.1f}% AvgPnL={avg:+.3f}%")


if __name__ == "__main__":
    run_backtest()
