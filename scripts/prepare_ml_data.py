#!/usr/bin/env python3
"""Export ML training data and RAG context from closed trade history.

This script reads `logs/closed_positions.json` and optionally `data/positions.json`,
then writes:
  1. CSV file with structured fields for model training.
  2. JSON file with RAG (Retrieval-Augmented Generation) blocks for Gemini AI.

RAG data includes: per-coin win rates, directional statistics, and similar-scenario lookups.
"""

import argparse
import csv
import json
import os
from datetime import datetime
from collections import defaultdict

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CLOSED_LOG = os.path.join(ROOT_DIR, "logs", "closed_positions.json")
DEFAULT_POSITIONS_FILE = os.path.join(ROOT_DIR, "data", "positions.json")
DEFAULT_OUTPUT_CSV = os.path.join(ROOT_DIR, "data", "ml_training_data.csv")
DEFAULT_OUTPUT_RAG = os.path.join(ROOT_DIR, "data", "ml_rag_context.json")

FIELDNAMES = [
    "coin",
    "direction",
    "is_long",
    "entry_price",
    "sell_price",
    "entry_time",
    "exit_time",
    "hold_hours",
    "pnl_pct",
    "pnl_usd_per_1000",
    "pnl_usd_actual",
    "fee_usd",
    "received_usdt",
    "r_multiplier",
    "risk_pct",
    "result",
    "is_win",
    "last_signal",
    "last_price",
    "last_checked",
    "suggested_sl",
    "suggested_tp1",
    "suggested_tp2",
    "suggested_rr1",
    "invested_usdt",
    "note",
    # Technical snapshot (extracted from suggested_sl/tp1/tp2 and entry_price)
    "entry_distance_to_sl_pct",
    "entry_distance_to_tp1_pct",
    "entry_distance_to_tp2_pct",
    "exit_distance_from_entry_pct",
]


def load_json_file(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def calculate_rr1(entry_price: float, sl: float, tp1: float) -> float:
    """Calculate Risk:Reward ratio for TP1."""
    if entry_price <= 0 or sl <= 0 or tp1 <= 0:
        return 0.0
    risk = abs(entry_price - sl)
    reward = abs(tp1 - entry_price)
    if risk == 0:
        return 0.0
    return round(reward / risk, 2)


def normalize_trade(trade: dict) -> dict:
    entry_price = float(trade.get("entry_price", 0.0) or 0.0)
    sell_price = float(trade.get("sell_price", 0.0) or 0.0)
    suggested_sl = float(trade.get("suggested_sl", 0.0) or 0.0)
    suggested_tp1 = float(trade.get("suggested_tp1", 0.0) or 0.0)
    suggested_tp2 = float(trade.get("suggested_tp2", 0.0) or 0.0)
    
    risk_pct = abs(entry_price - suggested_sl) / entry_price * 100 if entry_price > 0 and suggested_sl > 0 else 0.0
    rr1 = calculate_rr1(entry_price, suggested_sl, suggested_tp1)
    
    # Calculate distances as percentages (technical snapshot features)
    entry_distance_to_sl_pct = abs(entry_price - suggested_sl) / entry_price * 100 if entry_price > 0 else 0.0
    entry_distance_to_tp1_pct = abs(suggested_tp1 - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
    entry_distance_to_tp2_pct = abs(suggested_tp2 - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
    exit_distance_from_entry_pct = abs(sell_price - entry_price) / entry_price * 100 if entry_price > 0 else 0.0

    return {
        "coin": trade.get("coin", ""),
        "direction": trade.get("direction", ""),
        "is_long": 1 if str(trade.get("direction", "")).upper() == "LONG" else 0,
        "entry_price": entry_price,
        "sell_price": sell_price,
        "entry_time": trade.get("entry_time", ""),
        "exit_time": trade.get("exit_time", ""),
        "hold_hours": float(trade.get("hold_hours", 0.0) or 0.0),
        "pnl_pct": float(trade.get("pnl_pct", 0.0) or 0.0),
        "pnl_usd_per_1000": float(trade.get("pnl_usd_per_1000", 0.0) or 0.0),
        "pnl_usd_actual": float(trade.get("pnl_usd_actual", 0.0) or 0.0),
        "fee_usd": float(trade.get("fee_usd", 0.0) or 0.0),
        "received_usdt": float(trade.get("received_usdt", 0.0) or 0.0),
        "r_multiplier": float(trade.get("r_multiplier", 0.0) or 0.0),
        "risk_pct": round(risk_pct, 4),
        "result": trade.get("result", ""),
        "is_win": 1 if str(trade.get("result", "")).upper() == "WIN" else 0,
        "last_signal": trade.get("last_signal", ""),
        "last_price": float(trade.get("last_price", 0.0) or 0.0),
        "last_checked": trade.get("last_checked", ""),
        "suggested_sl": suggested_sl,
        "suggested_tp1": suggested_tp1,
        "suggested_tp2": suggested_tp2,
        "suggested_rr1": rr1,
        "invested_usdt": float(trade.get("invested_usdt", 0.0) or 0.0),
        "note": str(trade.get("note", "")),
        # Technical snapshot features
        "entry_distance_to_sl_pct": round(entry_distance_to_sl_pct, 4),
        "entry_distance_to_tp1_pct": round(entry_distance_to_tp1_pct, 4),
        "entry_distance_to_tp2_pct": round(entry_distance_to_tp2_pct, 4),
        "exit_distance_from_entry_pct": round(exit_distance_from_entry_pct, 4),
    }


def collect_trades(closed_log_path: str, positions_path: str) -> list[dict]:
    trades = load_json_file(closed_log_path)
    if trades:
        return trades

    all_positions = load_json_file(positions_path)
    return [p for p in all_positions if str(p.get("status", "")).lower() == "closed"]


def build_rag_context(trades: list[dict]) -> dict:
    """
    Build RAG (Retrieval-Augmented Generation) context from closed trade history.
    
    Returns:
        dict with:
        - global_stats: overall win rate, avg PnL, profit factor
        - coin_stats: per-coin breakdown (win rate, avg PnL, count, recent trades)
        - directional_stats: LONG vs SHORT performance
        - signal_stats: performance by last_signal
        - scenarios: similar-scenario lookup (group by direction + result)
    """
    if not trades:
        return {}

    # Global stats
    total = len(trades)
    wins = [t for t in trades if t.get("result") == "WIN"]
    losses = [t for t in trades if t.get("result") == "LOSS"]
    
    global_win_rate = len(wins) / total * 100 if total > 0 else 0
    global_avg_pnl = sum(t.get("pnl_pct", 0.0) for t in trades) / total if total > 0 else 0
    global_profit_factor = (
        abs(sum(t.get("pnl_pct", 0.0) for t in wins)) / abs(sum(t.get("pnl_pct", 0.0) for t in losses))
        if losses and sum(t.get("pnl_pct", 0.0) for t in losses) != 0
        else None
    )

    # Per-coin stats
    coin_groups = defaultdict(list)
    for t in trades:
        coin_groups[t.get("coin", "UNKNOWN")].append(t)

    coin_stats = {}
    for coin, coin_trades in coin_groups.items():
        coin_wins = [t for t in coin_trades if t.get("result") == "WIN"]
        coin_losses = [t for t in coin_trades if t.get("result") == "LOSS"]
        coin_win_rate = len(coin_wins) / len(coin_trades) * 100 if coin_trades else 0
        coin_avg_pnl = sum(t.get("pnl_pct", 0.0) for t in coin_trades) / len(coin_trades) if coin_trades else 0
        recent_3 = sorted(coin_trades, key=lambda t: t.get("exit_time", ""), reverse=True)[:3]
        
        coin_stats[coin] = {
            "total_trades": len(coin_trades),
            "win_rate_pct": round(coin_win_rate, 2),
            "avg_pnl_pct": round(coin_avg_pnl, 4),
            "wins": len(coin_wins),
            "losses": len(coin_losses),
            "recent_3": [
                {
                    "result": t.get("result"),
                    "pnl_pct": round(t.get("pnl_pct", 0.0), 4),
                    "signal": t.get("last_signal"),
                    "hold_hours": t.get("hold_hours"),
                }
                for t in recent_3
            ],
        }

    # Directional stats
    long_trades = [t for t in trades if t.get("direction") == "LONG"]
    short_trades = [t for t in trades if t.get("direction") == "SHORT"]
    
    directional_stats = {
        "LONG": {
            "total": len(long_trades),
            "wins": len([t for t in long_trades if t.get("result") == "WIN"]),
            "win_rate_pct": round(len([t for t in long_trades if t.get("result") == "WIN"]) / len(long_trades) * 100, 2) if long_trades else 0,
            "avg_pnl_pct": round(sum(t.get("pnl_pct", 0.0) for t in long_trades) / len(long_trades), 4) if long_trades else 0,
        },
        "SHORT": {
            "total": len(short_trades),
            "wins": len([t for t in short_trades if t.get("result") == "WIN"]),
            "win_rate_pct": round(len([t for t in short_trades if t.get("result") == "WIN"]) / len(short_trades) * 100, 2) if short_trades else 0,
            "avg_pnl_pct": round(sum(t.get("pnl_pct", 0.0) for t in short_trades) / len(short_trades), 4) if short_trades else 0,
        },
    }

    # Signal stats
    signal_groups = defaultdict(list)
    for t in trades:
        signal = str(t.get("last_signal", "UNKNOWN")).upper()
        signal_groups[signal].append(t)

    signal_stats = {}
    for signal, sig_trades in signal_groups.items():
        sig_wins = [t for t in sig_trades if t.get("result") == "WIN"]
        sig_win_rate = len(sig_wins) / len(sig_trades) * 100 if sig_trades else 0
        sig_avg_pnl = sum(t.get("pnl_pct", 0.0) for t in sig_trades) / len(sig_trades) if sig_trades else 0
        
        signal_stats[signal] = {
            "count": len(sig_trades),
            "win_rate_pct": round(sig_win_rate, 2),
            "avg_pnl_pct": round(sig_avg_pnl, 4),
            "wins": len(sig_wins),
        }

    # Scenarios: group by direction and result for pattern matching
    scenarios = {}
    for t in trades:
        direction = t.get("direction", "UNKNOWN")
        result = t.get("result", "UNKNOWN")
        scenario_key = f"{direction}_{result}"
        
        if scenario_key not in scenarios:
            scenarios[scenario_key] = []
        
        scenarios[scenario_key].append({
            "coin": t.get("coin"),
            "signal": t.get("last_signal"),
            "pnl_pct": round(t.get("pnl_pct", 0.0), 4),
            "hold_hours": t.get("hold_hours"),
            "entry_distance_to_sl_pct": t.get("entry_distance_to_sl_pct", 0.0),
            "entry_distance_to_tp1_pct": t.get("entry_distance_to_tp1_pct", 0.0),
        })

    return {
        "export_timestamp": datetime.now().isoformat(),
        "global_stats": {
            "total_trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": round(global_win_rate, 2),
            "avg_pnl_pct": round(global_avg_pnl, 4),
            "profit_factor": round(global_profit_factor, 2) if global_profit_factor is not None else None,
        },
        "coin_stats": coin_stats,
        "directional_stats": directional_stats,
        "signal_stats": signal_stats,
        "scenarios": scenarios,
    }



def write_csv(rows: list[dict], output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(data: dict, output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export ML training data and RAG context from closed trade history."
    )
    parser.add_argument("--closed-log", default=DEFAULT_CLOSED_LOG, help="Path to closed_positions.json.")
    parser.add_argument("--positions", default=DEFAULT_POSITIONS_FILE, help="Path to positions.json (fallback).")
    parser.add_argument("--output-csv", default=DEFAULT_OUTPUT_CSV, help="Output CSV path.")
    parser.add_argument("--output-rag", default=DEFAULT_OUTPUT_RAG, help="Output RAG JSON path.")
    parser.add_argument("--skip-rag", action="store_true", help="Skip RAG export.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trades = collect_trades(args.closed_log, args.positions)

    if not trades:
        print("Không tìm thấy dữ liệu lệnh đã đóng. Hãy chạy ít nhất một lần close_position trước khi xuất dữ liệu.")
        return

    # Normalize trades and add technical features
    normalized_trades = [normalize_trade(t) for t in trades]
    
    # Export to CSV
    write_csv(normalized_trades, args.output_csv)
    print(f"✅ Đã xuất {len(normalized_trades)} bản ghi sang {args.output_csv}")

    # Export RAG context
    if not args.skip_rag:
        rag_context = build_rag_context(normalized_trades)
        write_json(rag_context, args.output_rag)
        print(f"✅ Đã xuất RAG context sang {args.output_rag}")
        
        # Print summary
        global_stats = rag_context.get("global_stats", {})
        print(f"\n📊 Tóm tắt:")
        print(f"  • Tổng lệnh: {global_stats.get('total_trades')}")
        print(f"  • Win Rate: {global_stats.get('win_rate_pct')}%")
        print(f"  • Avg PnL: {global_stats.get('avg_pnl_pct')}%")
        print(f"  • Profit Factor: {global_stats.get('profit_factor')}")



if __name__ == "__main__":
    main()
