"""
scripts/ml2_payoff_feasibility_diagnostics.py

Executes Phase D: ML2 Payoff Feasibility Diagnostics across all 13 features on the 945-trade dataset.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import numpy as np
import pandas as pd
from scipy import stats

from btc_scraper.research.ml_trade_quality.dataset_builder import build_trade_quality_dataset
from btc_scraper.research.ml_trade_quality.feature_contract import FEATURE_NAMES
from scripts.run_m4_successor_pilot import load_development_candles_with_warmup, enrich_4h_closed_candles

# Load data & dataset
btc_raw = load_development_candles_with_warmup("BTCUSDT", "2023-01", "2025-12")
eth_raw = load_development_candles_with_warmup("ETHUSDT", "2023-01", "2025-12")
btc_enriched = enrich_4h_closed_candles(btc_raw)
eth_enriched = enrich_4h_closed_candles(eth_raw)
candles_by_symbol = {"BTCUSDT": btc_enriched, "ETHUSDT": eth_enriched}

trade_dataset, manifest = build_trade_quality_dataset(candles_by_symbol)

# Flatten dataset into DataFrame
rows = []
for t in trade_dataset:
    r = {
        "trade_id": t["trade_id"],
        "symbol": t["symbol"],
        "signal_time": t["signal_time"],
        "entry_time": t["entry_time"],
        "exit_time": t["exit_time"],
        "hold_bars": t["hold_bars"],
        "gross_pnl": t["gross_pnl"],
        "net_pnl_14bps": t["net_pnl_14bps"],
        "label": t["label"],
        "year": str(t["signal_time"])[:4],
    }
    for f_name in FEATURE_NAMES:
        r[f_name] = t["features"][f_name]
    rows.append(r)

df = pd.DataFrame(rows)

print(f"Total Trade Sample Size: {len(df)}")
print(f"BTC trades: {sum(df['symbol'] == 'BTCUSDT')}, ETH trades: {sum(df['symbol'] == 'ETHUSDT')}")
print(f"2023: {sum(df['year'] == '2023')}, 2024: {sum(df['year'] == '2024')}, 2025: {sum(df['year'] == '2025')}")

print("\n=== 1. FEATURE CORRELATIONS WITH REALIZED NET PNL ===")
corr_summary = []
for f_name in FEATURE_NAMES:
    pe_r, pe_p = stats.pearsonr(df[f_name], df["net_pnl_14bps"])
    sp_r, sp_p = stats.spearmanr(df[f_name], df["net_pnl_14bps"])
    corr_summary.append({
        "feature": f_name,
        "pearson_r": round(pe_r, 4),
        "pearson_p": round(pe_p, 4),
        "spearman_r": round(sp_r, 4),
        "spearman_p": round(sp_p, 4),
    })
df_corr = pd.DataFrame(corr_summary)
print(df_corr.to_string(index=False))

print("\n=== 2. FEATURE STABILITY ACROSS BTC VS ETH ===")
asset_stability = []
for f_name in FEATURE_NAMES:
    df_btc = df[df["symbol"] == "BTCUSDT"]
    df_eth = df[df["symbol"] == "ETHUSDT"]
    sp_btc, p_btc = stats.spearmanr(df_btc[f_name], df_btc["net_pnl_14bps"])
    sp_eth, p_eth = stats.spearmanr(df_eth[f_name], df_eth["net_pnl_14bps"])
    same_sign = (sp_btc * sp_eth > 0)
    asset_stability.append({
        "feature": f_name,
        "btc_spearman": round(sp_btc, 4),
        "eth_spearman": round(sp_eth, 4),
        "consistent_sign": same_sign,
    })
print(pd.DataFrame(asset_stability).to_string(index=False))

print("\n=== 3. FEATURE STABILITY ACROSS YEARS (2023, 2024, 2025) ===")
year_stability = []
for f_name in FEATURE_NAMES:
    sp_23, _ = stats.spearmanr(df[df["year"] == "2023"][f_name], df[df["year"] == "2023"]["net_pnl_14bps"])
    sp_24, _ = stats.spearmanr(df[df["year"] == "2024"][f_name], df[df["year"] == "2024"]["net_pnl_14bps"])
    sp_25, _ = stats.spearmanr(df[df["year"] == "2025"][f_name], df[df["year"] == "2025"]["net_pnl_14bps"])
    consistent = (sp_23 * sp_24 > 0) and (sp_24 * sp_25 > 0)
    year_stability.append({
        "feature": f_name,
        "sp_2023": round(sp_23, 4),
        "sp_2024": round(sp_24, 4),
        "sp_2025": round(sp_25, 4),
        "all_3_same_sign": consistent,
    })
print(pd.DataFrame(year_stability).to_string(index=False))

print("\n=== 4. PAYOFF TAIL CONCENTRATION & ASYMMETRY ===")
wins = df[df["net_pnl_14bps"] > 0]["net_pnl_14bps"]
losses = df[df["net_pnl_14bps"] <= 0]["net_pnl_14bps"]
print(f"Total Wins: {len(wins)} | Mean Win: ${wins.mean():.2f} | Max Win: ${wins.max():.2f}")
print(f"Total Losses: {len(losses)} | Mean Loss: ${losses.mean():.2f} | Max Loss: ${losses.min():.2f}")
print(f"Payoff Ratio (Mean Win / |Mean Loss|): {abs(wins.mean() / losses.mean()):.2f}")

top_1_pct_n = max(1, int(len(df) * 0.01))
top_5_pct_n = int(len(df) * 0.05)
sorted_pnl = df["net_pnl_14bps"].sort_values(ascending=False)
sum_total_pnl = df["net_pnl_14bps"].sum()
sum_top_1_pct = sorted_pnl.head(top_1_pct_n).sum()
sum_top_5_pct = sorted_pnl.head(top_5_pct_n).sum()
print(f"Total Net PnL across 945 trades: ${sum_total_pnl:.2f}")
print(f"Top 1% of trades ({top_1_pct_n} trades) sum to: ${sum_top_1_pct:.2f} ({sum_top_1_pct / sum_total_pnl * 100:.1f}% of total net profit!)")
print(f"Top 5% of trades ({top_5_pct_n} trades) sum to: ${sum_top_5_pct:.2f} ({sum_top_5_pct / sum_total_pnl * 100:.1f}% of total net profit!)")
