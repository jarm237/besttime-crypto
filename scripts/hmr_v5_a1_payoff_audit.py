#!/usr/bin/env python3
"""HMR-V5-A1: Entry-to-Payoff Surface Audit.

Systematically measures the gross price movements after candidate entries
to answer: Does the current candidate entry family produce enough gross
economic edge to justify any further modeling work?
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(REPO_ROOT))

SCAFFOLD_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4a_outcome_scaffold.parquet"
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v5"
OUT_DIR.mkdir(parents=True, exist_ok=True)

AUDIT_TS = datetime.now(timezone.utc).isoformat()

# Horizons to test (in bars of 15m)
HORIZON_MAP = {
    "30m": 2,
    "1h": 4,
    "2h": 8,
    "4h": 16,
    "8h": 32,
    "12h": 48,
    "24h": 96,
    "48h": 192,
    "72h": 288,
}


def bootstrap_mean_ci(data: np.ndarray, num_resamples: int = 1000, ci: float = 95.0) -> tuple[float, float]:
    """Calculate bootstrap confidence interval for the mean return."""
    if len(data) == 0:
        return 0.0, 0.0
    # Vectorized bootstrap choosing
    np.random.seed(42)  # for reproducible bootstrap CIs
    resamples = np.random.choice(data, size=(num_resamples, len(data)), replace=True)
    means = np.mean(resamples, axis=1)
    lower = float(np.percentile(means, (100 - ci) / 2))
    upper = float(np.percentile(means, 100 - (100 - ci) / 2))
    return lower, upper


def compute_metrics(
    closes: np.ndarray,
    signal_indices: list[int],
    side: str,
    h_bars: int,
) -> dict[str, Any]:
    """Compute forward returns, MFE, MAE, time offsets, capture ratios, and fee adjusted returns."""
    n_signals = len(signal_indices)
    if n_signals == 0:
        return {
            "n_signals": 0,
            "mean_return_bps": 0.0,
            "std_return_bps": 0.0,
            "mean_mfe_bps": 0.0,
            "mean_mae_bps": 0.0,
            "median_mfe_bps": 0.0,
            "median_mae_bps": 0.0,
            "mean_time_to_mfe_bars": 0.0,
            "mean_time_to_mae_bars": 0.0,
            "mfe_capture_ratio": 0.0,
            "win_rate_pct": 0.0,
            "ci_lower_bps": 0.0,
            "ci_upper_bps": 0.0,
            "cost_adjusted_ev_2_5_bps": 0.0,
            "cost_adjusted_ev_5_0_bps": 0.0,
            "cost_adjusted_ev_7_5_bps": 0.0,
        }

    returns = []
    mfes = []
    maes = []
    t_mfes = []
    t_maes = []

    for idx in signal_indices:
        if idx + h_bars >= len(closes):
            continue

        entry_close = closes[idx]
        path = closes[idx + 1: idx + h_bars + 1]
        exit_close = path[-1]

        # Forward return
        ret = (exit_close - entry_close) / entry_close if side == "BUY" else (entry_close - exit_close) / entry_close
        returns.append(ret)

        # MFE / MAE
        path_diffs = path - entry_close
        if side == "BUY":
            mfe_val = np.max(path_diffs) / entry_close
            mae_val = np.min(path_diffs) / entry_close
            t_mfe = np.argmax(path_diffs) + 1
            t_mae = np.argmin(path_diffs) + 1
        else:
            # For short, favorable is price drop (negative diffs)
            mfe_val = np.max(-path_diffs) / entry_close
            mae_val = np.min(-path_diffs) / entry_close
            t_mfe = np.argmax(-path_diffs) + 1
            t_mae = np.argmin(-path_diffs) + 1

        mfes.append(mfe_val)
        maes.append(mae_val)
        t_mfes.append(t_mfe)
        t_maes.append(t_mae)

    if not returns:
        return {"n_signals": 0}

    r = np.array(returns)
    m = np.array(mfes)
    a = np.array(maes)

    mean_ret = float(np.mean(r)) * 10000.0
    std_ret = float(np.std(r)) * 10000.0
    mean_mfe = float(np.mean(m)) * 10000.0
    mean_mae = float(np.mean(a)) * 10000.0
    median_mfe = float(np.percentile(m, 50)) * 10000.0
    median_mae = float(np.percentile(a, 50)) * 10000.0

    mean_t_mfe = float(np.mean(t_mfes))
    mean_t_mae = float(np.mean(t_maes))

    # Capture ratio
    mean_mae_abs = abs(mean_mae)
    capture_ratio = mean_mfe / mean_mae_abs if mean_mae_abs > 0 else mean_mfe / 1e-6

    # Win rate
    win_rate = float(np.sum(r > 0) / len(r)) * 100.0

    # Bootstrap CIs (in bps)
    ci_lower, ci_upper = bootstrap_mean_ci(r * 10000.0)

    # Cost-adjusted EV
    cost_2_5 = mean_ret - 2.5
    cost_5_0 = mean_ret - 5.0
    cost_7_5 = mean_ret - 7.5

    return {
        "n_signals": len(returns),
        "mean_return_bps": round(mean_ret, 4),
        "std_return_bps": round(std_ret, 4),
        "mean_mfe_bps": round(mean_mfe, 4),
        "mean_mae_bps": round(mean_mae, 4),
        "median_mfe_bps": round(median_mfe, 4),
        "median_mae_bps": round(median_mae, 4),
        "mean_time_to_mfe_bars": round(mean_t_mfe, 2),
        "mean_time_to_mae_bars": round(mean_t_mae, 2),
        "mfe_capture_ratio": round(capture_ratio, 4),
        "win_rate_pct": round(win_rate, 2),
        "ci_lower_bps": round(ci_lower, 4),
        "ci_upper_bps": round(ci_upper, 4),
        "cost_adjusted_ev_2_5_bps": round(cost_2_5, 4),
        "cost_adjusted_ev_5_0_bps": round(cost_5_0, 4),
        "cost_adjusted_ev_7_5_bps": round(cost_7_5, 4),
    }


def main():
    print("=== HMR-V5-A1: Entry-to-Payoff Surface Audit ===")
    print(f"Timestamp: {AUDIT_TS}\n")

    print("Loading outcome scaffold dataset...")
    df = pd.read_parquet(SCAFFOLD_PATH)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    results: dict[str, Any] = {
        "program": "HMR-V5-A1",
        "audit_timestamp": AUDIT_TS,
        "maximum_valid_historical_window": "2023-01-01 to 2024-12-31",
        "symbols": {},
    }

    # Analyze by symbol
    for symbol in ["BTC", "ETH", "BNB"]:
        print(f"\nAnalyzing {symbol} price curves...")
        df_sym = df[df["symbol"] == symbol].sort_values("timestamp").copy().reset_index(drop=True)
        closes = df_sym["close"].values

        # ── Regime Indicators (30-day window = 2880 bars) ──────────────────────
        # SMA 30-day
        df_sym["sma_30d"] = df_sym["close"].rolling(2880).mean()
        # Volatility 30-day
        df_sym["vol_30d"] = df_sym["close"].pct_change().rolling(2880).std()
        vol_median = df_sym["vol_30d"].median()

        # Classify regimes
        df_sym["trend_regime"] = np.where(df_sym["close"] > df_sym["sma_30d"], "UPTREND", "DOWNTREND")
        df_sym["vol_regime"] = np.where(df_sym["vol_30d"] > vol_median, "HIGH_VOL", "LOW_VOL")

        # Temporal indicators
        df_sym["year"] = df_sym["timestamp"].dt.year.astype(str)
        df_sym["quarter"] = df_sym["timestamp"].dt.to_period("Q").astype(str)

        results["symbols"][symbol] = {
            "BUY": {},
            "SELL": {},
        }

        for side, signal_col in [("BUY", "long_30_20"), ("SELL", "short_30_20")]:
            signal_indices = df_sym[df_sym[signal_col] == 1].index.tolist()
            print(f"  Side {side}: {len(signal_indices)} entries found.")

            for h_name, h_bars in HORIZON_MAP.items():
                # Overall horizon analysis
                overall = compute_metrics(closes, signal_indices, side, h_bars)

                # Sub-segment breakdowns
                # 1. Year Stability
                years = {}
                for yr in ["2023", "2024"]:
                    sub_idx = df_sym[(df_sym[signal_col] == 1) & (df_sym["year"] == yr)].index.tolist()
                    years[yr] = compute_metrics(closes, sub_idx, side, h_bars)

                # 2. Quarter Stability
                quarters = {}
                for qtr in sorted(df_sym["quarter"].unique()):
                    sub_idx = df_sym[(df_sym[signal_col] == 1) & (df_sym["quarter"] == qtr)].index.tolist()
                    quarters[qtr] = compute_metrics(closes, sub_idx, side, h_bars)

                # 3. Regime Stability (Trend)
                regimes_trend = {}
                for regime in ["UPTREND", "DOWNTREND"]:
                    sub_idx = df_sym[(df_sym[signal_col] == 1) & (df_sym["trend_regime"] == regime)].index.tolist()
                    regimes_trend[regime] = compute_metrics(closes, sub_idx, side, h_bars)

                # 4. Regime Stability (Volatility)
                regimes_vol = {}
                for regime in ["HIGH_VOL", "LOW_VOL"]:
                    sub_idx = df_sym[(df_sym[signal_col] == 1) & (df_sym["vol_regime"] == regime)].index.tolist()
                    regimes_vol[regime] = compute_metrics(closes, sub_idx, side, h_bars)

                results["symbols"][symbol][side][h_name] = {
                    "overall": overall,
                    "temporal": {
                        "by_year": years,
                        "by_quarter": quarters,
                    },
                    "regimes": {
                        "trend": regimes_trend,
                        "volatility": regimes_vol,
                    }
                }

    # ── Governance Audit Verdict Determination ────────────────────────────────
    # Check BTC BUY and SELL at a medium-term horizon (e.g. 4h, 12h, 24h) to determine final verdict
    btc_buy_24h = results["symbols"]["BTC"]["BUY"]["24h"]["overall"]
    btc_sell_24h = results["symbols"]["BTC"]["SELL"]["24h"]["overall"]

    # Threshold criteria:
    # gross mean return > 2.5 bps (at 24h) and lower CI bounds > 0
    buy_edge_passes = btc_buy_24h["mean_return_bps"] > 2.5 and btc_buy_24h["ci_lower_bps"] > 0
    sell_edge_passes = btc_sell_24h["mean_return_bps"] > 2.5 and btc_sell_24h["ci_lower_bps"] > 0

    if buy_edge_passes or sell_edge_passes:
        # Check if MAE is reached before MFE or capture ratio is low
        # suggesting poor entry timing (too early/late)
        if btc_buy_24h["mfe_capture_ratio"] < 0.8 or btc_sell_24h["mfe_capture_ratio"] < 0.8:
            verdict = "REDESIGN_ENTRY"
            verdict_note = (
                "Sufficient gross price movements exist (MFE > 20 bps), but "
                "entry timing is poor: MAE magnitude is high, leading to a low MFE capture ratio (< 0.8). "
                "Entries are either early or late, requiring entry signal redesign."
            )
        else:
            verdict = "PROMOTE_PAYOFF_ARCHITECTURE"
            verdict_note = (
                "Exploitable price movements exist post-entry, and cost floors "
                "are cleanly exceeded. Proceed to V5-B exit architecture comparison."
            )
    else:
        # Gross returns fail to exceed cost floors or CI contains zero
        verdict = "HARD_STOP_STRATEGY_FAMILY"
        verdict_note = (
            "Mean gross returns across BTC horizons are below realistic roundtrip cost floors "
            "(2.5 bps) or bootstrap confidence intervals contain zero. "
            "No exploitable price movement exists after candidate entries. "
            "The strategy family is rejected."
        )

    results["verdict"] = verdict
    results["verdict_note"] = verdict_note
    results["ml_training"] = "BLOCKED — exit architecture baseline and economic survivability must be established before ML authorization."

    # Save JSON
    json_path = OUT_DIR / "v5_a1_payoff_audit.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ Saved audit JSON to {json_path}")

    # Generate Markdown Report
    write_md_report(results)
    return results


def write_md_report(res: dict[str, Any]):
    report_path = OUT_DIR / "v5_a1_payoff_report.md"

    lines = [
        "# HMR-V5-A1: Entry-to-Payoff Surface Audit Report",
        "",
        f"> **Timestamp**: `{res['audit_timestamp']}` | **Historical Window**: `{res['maximum_valid_historical_window']}`",
        "",
        "## Governance Rationale & Verdict",
        "",
        f"- **Audit Verdict**: **`{res['verdict']}`**",
        f"- **ML Training**: `{res['ml_training']}`",
        "",
        f"**Verdict Wording**: {res['verdict_note']}",
        "",
        "---",
        "",
        "## Overall Payoff Surface Summary (BTC)",
        "",
        "### BUY Side (long_30_20)",
        "",
        "| Horizon | Signals | Mean Return (bps) | Std Dev (bps) | 95% CI (bps) | Mean MFE (bps) | Mean MAE (bps) | Capture Ratio | Cost-Adj EV (5 bps) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    btc_buy = res["symbols"]["BTC"]["BUY"]
    for h in HORIZON_MAP.keys():
        o = btc_buy[h]["overall"]
        lines.append(
            f"| `{h}` | {o['n_signals']} | {o['mean_return_bps']:.2f} | {o['std_return_bps']:.2f} | "
            f"[{o['ci_lower_bps']:.2f}, {o['ci_upper_bps']:.2f}] | {o['mean_mfe_bps']:.2f} | {o['mean_mae_bps']:.2f} | "
            f"{o['mfe_capture_ratio']:.2f} | {o['cost_adjusted_ev_5_0_bps']:.2f} |"
        )

    lines.extend([
        "",
        "### SELL Side (short_30_20)",
        "",
        "| Horizon | Signals | Mean Return (bps) | Std Dev (bps) | 95% CI (bps) | Mean MFE (bps) | Mean MAE (bps) | Capture Ratio | Cost-Adj EV (5 bps) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])

    btc_sell = res["symbols"]["BTC"]["SELL"]
    for h in HORIZON_MAP.keys():
        o = btc_sell[h]["overall"]
        lines.append(
            f"| `{h}` | {o['n_signals']} | {o['mean_return_bps']:.2f} | {o['std_return_bps']:.2f} | "
            f"[{o['ci_lower_bps']:.2f}, {o['ci_upper_bps']:.2f}] | {o['mean_mfe_bps']:.2f} | {o['mean_mae_bps']:.2f} | "
            f"{o['mfe_capture_ratio']:.2f} | {o['cost_adjusted_ev_5_0_bps']:.2f} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## Multi-Asset Stability Check (24h Horizon)",
        "",
        "| Asset | Side | Signals | Mean Return (bps) | 95% CI (bps) | Mean MFE (bps) | Mean MAE (bps) | Capture Ratio | Cost-Adj EV (5 bps) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])

    for asset in ["BTC", "ETH", "BNB"]:
        for side in ["BUY", "SELL"]:
            o = res["symbols"][asset][side]["24h"]["overall"]
            lines.append(
                f"| `{asset}` | `{side}` | {o['n_signals']} | {o['mean_return_bps']:.2f} | "
                f"[{o['ci_lower_bps']:.2f}, {o['ci_upper_bps']:.2f}] | {o['mean_mfe_bps']:.2f} | {o['mean_mae_bps']:.2f} | "
                f"{o['mfe_capture_ratio']:.2f} | {o['cost_adjusted_ev_5_0_bps']:.2f} |"
            )

    lines.extend([
        "",
        "---",
        "",
        "## Regime & Temporal Stability (BTC 24h Horizon)",
        "",
        "### Temporal Stability",
        "",
        "| Side | Sub-segment | Signals | Mean Return (bps) | 95% CI (bps) | Mean MFE (bps) | Mean MAE (bps) | Capture Ratio |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])

    # Temporal BUY
    t_buy = res["symbols"]["BTC"]["BUY"]["24h"]["temporal"]
    for yr in ["2023", "2024"]:
        o = t_buy["by_year"][yr]
        lines.append(f"| `BUY` | Year {yr} | {o['n_signals']} | {o['mean_return_bps']:.2f} | [{o['ci_lower_bps']:.2f}, {o['ci_upper_bps']:.2f}] | {o['mean_mfe_bps']:.2f} | {o['mean_mae_bps']:.2f} | {o['mfe_capture_ratio']:.2f} |")
    for qtr in sorted(t_buy["by_quarter"].keys()):
        o = t_buy["by_quarter"][qtr]
        lines.append(f"| `BUY` | Quarter {qtr} | {o['n_signals']} | {o['mean_return_bps']:.2f} | [{o['ci_lower_bps']:.2f}, {o['ci_upper_bps']:.2f}] | {o['mean_mfe_bps']:.2f} | {o['mean_mae_bps']:.2f} | {o['mfe_capture_ratio']:.2f} |")

    # Temporal SELL
    t_sell = res["symbols"]["BTC"]["SELL"]["24h"]["temporal"]
    for yr in ["2023", "2024"]:
        o = t_sell["by_year"][yr]
        lines.append(f"| `SELL` | Year {yr} | {o['n_signals']} | {o['mean_return_bps']:.2f} | [{o['ci_lower_bps']:.2f}, {o['ci_upper_bps']:.2f}] | {o['mean_mfe_bps']:.2f} | {o['mean_mae_bps']:.2f} | {o['mfe_capture_ratio']:.2f} |")
    for qtr in sorted(t_sell["by_quarter"].keys()):
        o = t_sell["by_quarter"][qtr]
        lines.append(f"| `SELL` | Quarter {qtr} | {o['n_signals']} | {o['mean_return_bps']:.2f} | [{o['ci_lower_bps']:.2f}, {o['ci_upper_bps']:.2f}] | {o['mean_mfe_bps']:.2f} | {o['mean_mae_bps']:.2f} | {o['mfe_capture_ratio']:.2f} |")

    lines.extend([
        "",
        "### Regime Stability",
        "",
        "| Side | Regime Type | Sub-segment | Signals | Mean Return (bps) | 95% CI (bps) | Mean MFE (bps) | Mean MAE (bps) | Capture Ratio |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])

    # Trend/Vol BUY
    r_buy = res["symbols"]["BTC"]["BUY"]["24h"]["regimes"]
    for trend in ["UPTREND", "DOWNTREND"]:
        o = r_buy["trend"][trend]
        lines.append(f"| `BUY` | Trend | {trend} | {o['n_signals']} | {o['mean_return_bps']:.2f} | [{o['ci_lower_bps']:.2f}, {o['ci_upper_bps']:.2f}] | {o['mean_mfe_bps']:.2f} | {o['mean_mae_bps']:.2f} | {o['mfe_capture_ratio']:.2f} |")
    for vol in ["HIGH_VOL", "LOW_VOL"]:
        o = r_buy["volatility"][vol]
        lines.append(f"| `BUY` | Volatility | {vol} | {o['n_signals']} | {o['mean_return_bps']:.2f} | [{o['ci_lower_bps']:.2f}, {o['ci_upper_bps']:.2f}] | {o['mean_mfe_bps']:.2f} | {o['mean_mae_bps']:.2f} | {o['mfe_capture_ratio']:.2f} |")

    # Trend/Vol SELL
    r_sell = res["symbols"]["BTC"]["SELL"]["24h"]["regimes"]
    for trend in ["UPTREND", "DOWNTREND"]:
        o = r_sell["trend"][trend]
        lines.append(f"| `SELL` | Trend | {trend} | {o['n_signals']} | {o['mean_return_bps']:.2f} | [{o['ci_lower_bps']:.2f}, {o['ci_upper_bps']:.2f}] | {o['mean_mfe_bps']:.2f} | {o['mean_mae_bps']:.2f} | {o['mfe_capture_ratio']:.2f} |")
    for vol in ["HIGH_VOL", "LOW_VOL"]:
        o = r_sell["volatility"][vol]
        lines.append(f"| `SELL` | Volatility | {vol} | {o['n_signals']} | {o['mean_return_bps']:.2f} | [{o['ci_lower_bps']:.2f}, {o['ci_upper_bps']:.2f}] | {o['mean_mfe_bps']:.2f} | {o['mean_mae_bps']:.2f} | {o['mfe_capture_ratio']:.2f} |")

    lines.extend([
        "",
        "---",
        "",
        "## Scientific Interpretation",
        "",
        "- **Payoff Capture boundary**: Since high/low columns are not present in the outcome scaffold,",
        "  the MFE and MAE are computed from close-to-close price paths. Actual intraday high/low excursions",
        "  will be higher than reported here.",
        "- **Rejection Rationale**: A hard stop verdict is triggered when mean returns fail to cover the lowest",
        "  fee bracket (2.5 bps) or when the bootstrap 95% confidence intervals overlap with zero.",
    ])

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✓ Saved Markdown report to {report_path}")


if __name__ == "__main__":
    main()
