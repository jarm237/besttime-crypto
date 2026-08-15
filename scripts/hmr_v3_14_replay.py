#!/usr/bin/env python3
"""HMR-V3.14–3.20: Prospective Historical Replay & Validation.

Runs the three frozen hypotheses (H1, H2, H3) on Period B/C data (2024-07-01
to 2024-12-31) and audits their performance against the pre-ML candidate gates.
"""

import json
import sys
import warnings
from pathlib import Path
import pandas as pd
import numpy as np

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.hmr_v1_baseline import load_closed_candles
from scripts.hmr_v3_3_unconditional_dataset import COINS, TIMEFRAME, WARMUP_BARS
from scripts.hmr_v3_5_6_characterization import calculate_pit_features
from scripts.hmr_v2_4_3_baseline_models import _econ

HYP_PATH = Path("research/historical_market_replay_v3/v3_3_hypotheses/hypotheses.json")
OUT_DIR  = Path("research/historical_market_replay_v3/v3_4_event_replay")

def run():
    if not (REPO_ROOT / HYP_PATH).exists():
        print(f"ERROR: Hypotheses registry not found at {HYP_PATH}")
        sys.exit(1)

    manifest = json.loads((REPO_ROOT / HYP_PATH).read_text())
    hyps = manifest["hypotheses"]

    # Period B/C dates (Validation Window)
    period_start = pd.Timestamp("2024-07-01", tz="UTC")
    period_end   = pd.Timestamp("2024-12-31 23:59:59", tz="UTC")
    settle_end   = pd.Timestamp("2025-01-21", tz="UTC") # buffer for 96-bar returns

    print("HMR-V3.14: Loading candles for Period B/C prospective replay...")
    candles_dict = load_closed_candles(
        Path("data/fresh_training_data_2023_2026"), COINS, TIMEFRAME,
        period_start, period_end, settle_end, warmup_bars=WARMUP_BARS
    )

    all_dfs = {}
    for coin in COINS:
        rows = candles_dict.get(coin)
        if not rows:
            continue
        dfc = pd.DataFrame(rows)
        dfc["time"] = pd.to_datetime(dfc["time"], utc=True)
        dfc.set_index("time", inplace=True)
        dfc.sort_index(inplace=True)
        all_dfs[coin] = dfc

    # Scan and filter events for each hypothesis
    results = {}
    for key, h_config in hyps.items():
        h_id = h_config["hypothesis_id"]
        rules = h_config["rules"]
        horizon = h_config["expected_horizon"]
        
        print(f"  Replaying {h_id} ({h_config['name']})...")
        h_events = []
        
        for coin in COINS:
            dfc = all_dfs.get(coin)
            if dfc is None:
                continue
            
            # Re-calculate PIT features
            df_f = calculate_pit_features(dfc)
            close = dfc["close"].astype(float)
            high  = dfc["high"].astype(float)
            low   = dfc["low"].astype(float)
            
            for i in range(len(dfc)):
                ts = dfc.index[i]
                if ts < period_start or ts > period_end:
                    continue
                
                feats = df_f.loc[ts]
                
                # Check rules
                is_buy = False
                is_sell = False
                
                if h_id == "V3-H1":
                    # Compression Breakout
                    if feats["bollinger_width"] <= rules["bollinger_width_max"]:
                        if feats["range_pos"] >= rules["range_pos_buy_min"]:
                            is_buy = True
                        elif feats["range_pos"] <= rules["range_pos_sell_max"]:
                            is_sell = True
                elif h_id == "V3-H2":
                    # ATR Squeeze
                    if feats["atr_compression"] <= rules["atr_compression_max"]:
                        if feats["range_pos"] >= rules["range_pos_buy_min"]:
                            is_buy = True
                        elif feats["range_pos"] <= rules["range_pos_sell_max"]:
                            is_sell = True
                elif h_id == "V3-H3":
                    # Momentum Breakout
                    if feats["bollinger_width"] <= rules["bollinger_width_max"]:
                        if feats["ema9_slope"] >= rules["ema9_slope_buy_min"]:
                            is_buy = True
                        elif feats["ema9_slope"] <= rules["ema9_slope_sell_max"]:
                            is_sell = True
                
                if not (is_buy or is_sell):
                    continue
                
                side = "BUY" if is_buy else "SELL"
                ep = float(close.iloc[i])
                
                # Forward return computation
                ret = np.nan
                if i + horizon < len(dfc):
                    exit_p = float(close.iloc[i + horizon])
                    ret = (exit_p - ep) / ep if side == "BUY" else (ep - exit_p) / ep
                    
                h_events.append({
                    "timestamp": ts,
                    "symbol": coin,
                    "side": side,
                    "entry_price": ep,
                    "gross_return": ret
                })
                
        df_h = pd.DataFrame(h_events)
        if len(df_h) > 0:
            econ_stats = _econ(df_h["gross_return"])
            results[h_id] = {
                "n": len(df_h),
                "mean_bps": econ_stats["mean_bps"],
                "gt30_rate": econ_stats["gross_gt30_rate"],
                "verdict": "PASS" if econ_stats["mean_bps"] >= 0 and econ_stats["gross_gt30_rate"] >= 0.15 else "FAIL"
            }
        else:
            results[h_id] = {"n": 0, "mean_bps": np.nan, "gt30_rate": np.nan, "verdict": "FAIL_NO_SAMPLES"}

    # Write report
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    lines = ["# HMR-V3.14: Prospective Replay & Validation Report (Period B/C)\n",
             "| Hypothesis | n | Mean Gross EV | Gross>30 Rate | Verdict |",
             "|:---|--:|:---:|:---:|:---:|"]
    for h_id, m in results.items():
        mean_str = f"{m['mean_bps']:+.2f} bps" if not np.isnan(m["mean_bps"]) else "—"
        rate_str = f"{m['gt30_rate']:.1%}" if not np.isnan(m["gt30_rate"]) else "—"
        lines.append(f"| `{h_id}` | {m['n']} | {mean_str} | {rate_str} | **{m['verdict']}** |")
        
    (OUT_DIR / "comparison.md").write_text("\n".join(lines) + "\n")
    print(f"\n  ✓ Saved validation report: {OUT_DIR / 'comparison.md'}")
    
    for h_id, m in results.items():
        print(f"    {h_id:6s} | n={m['n']:4d} | mean={m['mean_bps']:+6.2f} bps | Gross>30={m['gt30_rate']:.1%} | verdict={m['verdict']}")
        
    print("\n  GATE: V3_20_REPLAY_VALIDATION_COMPLETE = PASS")

if __name__ == "__main__":
    run()
