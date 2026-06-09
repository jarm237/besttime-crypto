#!/usr/bin/env python3
"""Generate structured RAG prompts from ML training data for Gemini AI.

This script reads `data/ml_rag_context.json` and generates:
  1. Per-coin narrative: "In the past, BTC with this signal had 75% win rate..."
  2. Risk warnings: "CAUTION: This signal type has only 40% win rate."
  3. Scenario matching: "Similar scenarios suggest..."
"""

import argparse
import json
import os
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RAG_FILE = os.path.join(ROOT_DIR, "data", "ml_rag_context.json")
DEFAULT_OUTPUT_FILE = os.path.join(ROOT_DIR, "data", "rag_prompts.md")


def load_rag_context(path: str) -> dict:
    """Load RAG context from JSON file."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading RAG context: {e}")
        return {}


def generate_coin_narrative(coin: str, stats: dict) -> str:
    """Generate narrative for a specific coin."""
    total = stats.get("total_trades", 0)
    wr = stats.get("win_rate_pct", 0)
    avg_pnl = stats.get("avg_pnl_pct", 0)
    
    if total == 0:
        return ""
    
    recent = stats.get("recent_3", [])
    recent_str = " | ".join(
        f"{t['result']}({t['pnl_pct']:+.1f}%)" for t in recent
    ) if recent else "N/A"
    
    narrative = f"""### {coin}
- **Lịch sử**: {total} lệnh đã đóng
- **Win Rate**: {wr}% ({stats.get('wins', 0)} thắng / {stats.get('losses', 0)} thua)
- **Avg P&L**: {avg_pnl:+.2f}%
- **3 lệnh gần nhất**: {recent_str}

**Lời khuyên**: Khi giao dịch {coin}, tham khảo dữ liệu trên. Nếu Win Rate thấp, hãy than trọng hơn hoặc xem xét bỏ qua tín hiệu này.
"""
    return narrative


def generate_signal_warnings(signal_stats: dict) -> str:
    """Generate warnings for low-performing signals."""
    warnings = []
    
    for signal, stats in signal_stats.items():
        wr = stats.get("win_rate_pct", 0)
        count = stats.get("count", 0)
        
        if wr < 50 and count >= 3:  # Only warn if enough sample size
            warnings.append(
                f"⚠️  **{signal}**: Chỉ {wr}% win rate trên {count} lệnh. "
                f"Hãy CẢNH BÁO hoặc HẠ CẤP tin hiệu này."
            )
        elif wr > 70 and count >= 3:
            warnings.append(
                f"✅ **{signal}**: {wr}% win rate trên {count} lệnh — đây là tín hiệu MẠNH."
            )
    
    return "\n".join(warnings) if warnings else "Không có cảnh báo đặc biệt."


def generate_directional_analysis(directional_stats: dict) -> str:
    """Generate analysis for LONG vs SHORT performance."""
    long_wr = directional_stats.get("LONG", {}).get("win_rate_pct", 0)
    short_wr = directional_stats.get("SHORT", {}).get("win_rate_pct", 0)
    
    long_count = directional_stats.get("LONG", {}).get("total", 0)
    short_count = directional_stats.get("SHORT", {}).get("total", 0)
    
    analysis = f"""## Phân tích theo Hướng Giao dịch

### LONG
- **Thống kê**: {long_count} lệnh, Win Rate = {long_wr}%
- **Avg P&L**: {directional_stats.get("LONG", {}).get("avg_pnl_pct", 0):+.2f}%

### SHORT
- **Thống kê**: {short_count} lệnh, Win Rate = {short_wr}%
- **Avg P&L**: {directional_stats.get("SHORT", {}).get("avg_pnl_pct", 0):+.2f}%

**Nhận xét**: {'Lệnh LONG hiệu quả hơn' if long_wr > short_wr else 'Lệnh SHORT hiệu quả hơn' if short_wr > long_wr else 'Cả hai hướng có hiệu quả tương đương'}
"""
    return analysis


def generate_scenario_insights(scenarios: dict) -> str:
    """Generate insights from past scenarios."""
    insights = []
    
    for scenario_key, trades in scenarios.items():
        direction, result = scenario_key.split("_")
        count = len(trades)
        
        if count < 2:
            continue
        
        avg_hold = sum(t.get("hold_hours", 0) for t in trades) / count if count > 0 else 0
        avg_pnl = sum(t.get("pnl_pct", 0) for t in trades) / count if count > 0 else 0
        
        insight = f"- {direction} {result}: {count} lệnh, avg hold={avg_hold:.1f}h, avg P&L={avg_pnl:+.2f}%"
        insights.append(insight)
    
    return "\n".join(insights) if insights else "Không có dữ liệu kịch bản."


def main():
    parser = argparse.ArgumentParser(description="Generate RAG prompts for Gemini AI from ML training data.")
    parser.add_argument("--rag-file", default=DEFAULT_RAG_FILE, help="Path to ml_rag_context.json")
    parser.add_argument("--output", default=DEFAULT_OUTPUT_FILE, help="Output markdown file path")
    args = parser.parse_args()
    
    rag = load_rag_context(args.rag_file)
    
    if not rag:
        print(f"Không tìm thấy file {args.rag_file}. Hãy chạy prepare_ml_data.py trước.")
        return
    
    # Build markdown content
    content = f"""# RAG Prompts cho Gemini AI — Dữ liệu Lịch sử Giao dịch

Sinh ra: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

## Tóm tắt Toàn cục

"""
    
    global_stats = rag.get("global_stats", {})
    content += f"""
- **Tổng lệnh đã đóng**: {global_stats.get('total_trades', 0)}
- **Win Rate**: {global_stats.get('win_rate_pct', 0)}%
- **Avg P&L**: {global_stats.get('avg_pnl_pct', 0):+.4f}%
- **Profit Factor**: {global_stats.get('profit_factor', 'N/A')}

---

## Phân tích theo Coin

"""
    
    coin_stats = rag.get("coin_stats", {})
    for coin, stats in sorted(coin_stats.items()):
        content += generate_coin_narrative(coin, stats)
    
    # Directional analysis
    content += "\n" + generate_directional_analysis(rag.get("directional_stats", {}))
    
    # Signal warnings
    content += "\n## Cảnh báo Tín hiệu\n\n"
    content += generate_signal_warnings(rag.get("signal_stats", {}))
    
    # Scenario insights
    content += "\n\n## Nhận xét Kịch bản\n\n"
    content += generate_scenario_insights(rag.get("scenarios", {}))
    
    # Write to file
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(content)
    
    print(f"✅ Đã sinh RAG prompts sang {args.output}")
    print(f"\nNội dung được sử dụng để:")
    print(f"  1. Tích hợp vào prompt Gemini AI")
    print(f"  2. Cảnh báo các tín hiệu yếu")
    print(f"  3. Điều chỉnh confidence score dựa trên lịch sử")


if __name__ == "__main__":
    main()
