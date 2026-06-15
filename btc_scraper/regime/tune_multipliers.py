"""
Tune position size multipliers per regime (and optionally per-strategy)
using historical logged trades in `logs/adaptive_signals.json`.

Approach:
 - Load logged trades with fields: pnl_pct, regime, strategy (if present)
 - Grid search multipliers per regime over candidate values and score by
   total expected PnL = sum(pnl_pct * multiplier)
 - Save top-N suggestions to logs/multiplier_tuning.json

Run: .venv/bin/python -m btc_scraper.tune_multipliers
"""
import json
import os
from itertools import product
from math import isfinite

BASE = os.path.dirname(__file__)
LOG = os.path.join(BASE, "..", "logs", "adaptive_signals.json")
OUT = os.path.join(BASE, "..", "logs", "multiplier_tuning.json")
CSV_BACKTEST = os.path.join(BASE, "regime_stats_detailed.csv")


def _load_log():
    if not os.path.exists(LOG):
        return []
    try:
        with open(LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def extract_records(records):
    out = []
    for r in records:
        pnl = r.get("pnl_pct")
        if pnl is None:
            continue
        try:
            pnl = float(pnl)
        except Exception:
            continue
        regime = r.get("regime") or None
        # try nested signal_score
        ss = r.get("signal_score") or {}
        if not regime and isinstance(ss, dict):
            regime = ss.get("regime")
        strategy = r.get("strategy") or None
        if not strategy and isinstance(ss, dict):
            strategy = ss.get("strategy")
        out.append({"pnl": pnl, "regime": regime, "strategy": strategy})
    return out


def grid_search(records, regimes, grid_vals, top_n=5, objective="expected_pnl", penalty=1.0):
    """
    objective: one of 'expected_pnl', 'winrate_times_avgpnl', 'penalize_negative'
    penalty: multiplier for penalize_negative (higher penalizes negatives more)
    """
    best = []
    combos = product(grid_vals, repeat=len(regimes))
    regimes = list(regimes)
    total = 0
    for idx, combo in enumerate(combos):
        mult_map = {regimes[i]: combo[i] for i in range(len(regimes))}

        if objective == "expected_pnl":
            total_score = 0.0
            for r in records:
                reg = r.get("regime") or "UNKNOWN"
                m = mult_map.get(reg, 1.0)
                total_score += r["pnl"] * m

        elif objective == "winrate_times_avgpnl":
            # compute per-regime win_rate and avg_pnl then sum(win_rate * avg_pnl * count * m)
            by_reg = {}
            for r in records:
                reg = r.get("regime") or "UNKNOWN"
                by_reg.setdefault(reg, {"pnl_sum": 0.0, "wins": 0, "count": 0})
                by_reg[reg]["pnl_sum"] += r["pnl"]
                by_reg[reg]["wins"] += 1 if r.get("pnl", 0) > 0 else 0
                by_reg[reg]["count"] += 1
            total_score = 0.0
            for reg, vals in by_reg.items():
                if vals["count"] == 0:
                    continue
                win_rate = vals["wins"] / vals["count"]
                avg_pnl = vals["pnl_sum"] / vals["count"]
                m = mult_map.get(reg, 1.0)
                total_score += win_rate * avg_pnl * vals["count"] * m

        elif objective == "penalize_negative":
            total_score = 0.0
            for r in records:
                reg = r.get("regime") or "UNKNOWN"
                m = mult_map.get(reg, 1.0)
                pnl = r["pnl"]
                if pnl < 0:
                    total_score += pnl * m * penalty
                else:
                    total_score += pnl * m

        else:
            # default fallback
            total_score = 0.0
            for r in records:
                reg = r.get("regime") or "UNKNOWN"
                m = mult_map.get(reg, 1.0)
                total_score += r["pnl"] * m

        best.append((total_score, mult_map))
        total += 1

    best.sort(key=lambda x: x[0], reverse=True)
    return best[:top_n], total


def main():
    records_raw = _load_log()
    records = extract_records(records_raw)
    if not records:
        print("No usable records found in", LOG)
    else:
        # If detailed backtest CSV exists, prefer using it for per-strategy suggestions
        if os.path.exists(CSV_BACKTEST):
            import csv
            sugg = {"default": {}, "per_strategy": {}}
            rows = []
            with open(CSV_BACKTEST, "r", encoding="utf-8") as cf:
                reader = csv.DictReader(cf)
                for r in reader:
                    # fields: strategy, regime, total, wins, losses, win_rate, avg_pnl
                    try:
                        strategy = r.get("strategy")
                        regime = r.get("regime")
                        total_trades = int(r.get("total", 0))
                        avg_pnl = float(r.get("avg_pnl") or 0.0)
                    except Exception:
                        continue
                    rows.append((strategy, regime, total_trades, avg_pnl))

            # grid values
            grid_vals = [round(0.25 + i * 0.05, 2) for i in range(16)]

            # For each (strategy, regime) pick multiplier maximizing total expected pnl
            for strategy, regime, total_trades, avg_pnl in rows:
                best_m = None
                best_score = None
                for m in grid_vals:
                    score = avg_pnl * total_trades * m
                    if best_score is None or score > best_score:
                        best_score = score
                        best_m = m
                # assign
                if strategy not in sugg["per_strategy"]:
                    sugg["per_strategy"][strategy] = {}
                sugg["per_strategy"][strategy][regime] = best_m

            # derive defaults by aggregating across strategies: for each regime pick multiplier maximizing sum of scores
            regimes = sorted(set([r for (_, r, _, _) in rows]))
            for reg in regimes:
                best_m = None
                best_score = None
                for m in grid_vals:
                    total_score = sum(avg_pnl * total_trades * m for (_, rreg, total_trades, avg_pnl) in rows if rreg == reg)
                    if best_score is None or total_score > best_score:
                        best_score = total_score
                        best_m = m
                sugg["default"][reg] = best_m

            out = {"method": "backtest_csv", "csv": CSV_BACKTEST, "suggested": sugg}
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2)
            print("Wrote tuning results (from CSV) to", OUT)

        else:
            regimes = sorted(set((r.get("regime") or "UNKNOWN") for r in records))
            print("Detected regimes:", regimes)

            # candidate grid values
            grid_vals = [round(0.25 + i * 0.05, 2) for i in range(16)]  # 0.25..1.0

            print("Grid size per regime:", len(grid_vals), "total combos:", len(grid_vals) ** len(regimes))

            top, total = grid_search(records, regimes, grid_vals, top_n=10)

            out = {"regimes": regimes, "grid_values": grid_vals, "total_combinations": total, "top": []}
            for score, mm in top:
                out["top"].append({"expected_pnl": round(score, 4), "multipliers": mm})

            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2)

            print("Wrote tuning results to", OUT)


if __name__ == "__main__":
    main()
