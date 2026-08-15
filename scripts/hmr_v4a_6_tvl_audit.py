#!/usr/bin/env python3
"""HMR-V4A-6-r1: DeFi TVL liquidity information audit."""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCAFFOLD_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4a_outcome_scaffold.parquet"
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"
RAW_TVL_DIR = REPO_ROOT / "research/alternative_history_validation/raw/defillama_tvl"

REVISION = "HMR-V4A-6-r1"
COINS = ["BTC", "ETH", "BNB"]
ELIGIBLE_ASSETS = ("BTC", "ETH", "BNB")
FEATURES = [
    "defi_tvl_level",
    "defi_tvl_change_1d",
    "defi_tvl_change_7d",
    "defi_tvl_change_30d",
    "defi_tvl_zscore_90d"
]

PERIODS = {
    "A": ("2023-01-01T00:00:00+00:00", "2024-06-30T23:59:59+00:00"),
    "B": ("2024-07-01T00:00:00+00:00", "2024-09-30T23:59:59+00:00"),
    "C": ("2024-10-01T00:00:00+00:00", "2024-12-31T23:59:59+00:00"),
}


def load_raw_tvl() -> pd.DataFrame:
    files = list(RAW_TVL_DIR.glob("*_attempt1.json"))
    if not files:
        raise FileNotFoundError(f"No raw TVL JSON files found in {RAW_TVL_DIR}")
    latest_file = sorted(files)[-1]
    print(f"Loading raw TVL data from: {latest_file.name}")
    
    with open(latest_file, "r") as f:
        payload = json.load(f)
    
    attempts = payload.get("attempts", [])
    if not attempts:
        raise ValueError("No attempts found in JSON payload")
    records = attempts[0].get("json", [])
    if not records:
        raise ValueError("No data records found in JSON payload")
        
    parsed = []
    for r in records:
        ts = int(r["date"])
        val = float(r.get("tvl", 0.0))
        source_timestamp = pd.to_datetime(ts, unit="s", utc=True)
        # Apply the frozen conservative availability lag of 12 hours
        available_at = source_timestamp + pd.Timedelta(hours=12)
        parsed.append({
            "source_date": source_timestamp.strftime("%Y-%m-%d"),
            "source_timestamp": source_timestamp,
            "available_at": available_at,
            "defi_tvl_level": val
        })
        
    df = pd.DataFrame(parsed)
    df = df.drop_duplicates(subset=["available_at"]).sort_values("available_at").reset_index(drop=True)
    
    # Compute the 5 features daily
    df["defi_tvl_change_1d"] = df["defi_tvl_level"].diff(1)
    df["defi_tvl_change_7d"] = df["defi_tvl_level"].diff(7)
    df["defi_tvl_change_30d"] = df["defi_tvl_level"].diff(30)
    
    # Rolling 90-day zscore
    r_mean = df["defi_tvl_level"].rolling(90, min_periods=30).mean()
    r_std = df["defi_tvl_level"].rolling(90, min_periods=30).std()
    df["defi_tvl_zscore_90d"] = (df["defi_tvl_level"] - r_mean) / r_std.replace(0.0, np.nan)
    
    return df.dropna(subset=["defi_tvl_zscore_90d"]).reset_index(drop=True)


def merge_tvl(scaffold: pd.DataFrame, tvl: pd.DataFrame) -> pd.DataFrame:
    merged = []
    for symbol in ELIGIBLE_ASSETS:
        left = scaffold[scaffold["symbol"] == symbol].sort_values("timestamp").copy()
        right = tvl.sort_values("available_at").copy()
        
        joined = pd.merge_asof(
            left,
            right,
            left_on="timestamp",
            right_on="available_at",
            direction="backward",
            allow_exact_matches=True,
        )
        merged.append(joined)
        
    out = pd.concat(merged, ignore_index=True)
    out["decision_time"] = out["timestamp"]
    out["tvl_age_seconds"] = (out["decision_time"] - out["available_at"]).dt.total_seconds()
    out["tvl_stale"] = out["tvl_age_seconds"] > 72 * 3600  # Stale if no update for 72 hours
    return out


def compute_future_range(g: pd.DataFrame, H: int) -> tuple[pd.Series, pd.Series]:
    # Vectorized future rolling high/low calculation
    g_rev = g.iloc[::-1]
    future_high = g_rev["high"].shift(1).rolling(window=H, min_periods=H).max().iloc[::-1]
    future_low = g_rev["low"].shift(1).rolling(window=H, min_periods=H).min().iloc[::-1]
    return future_high, future_low


def add_longer_horizon_targets(scaffold: pd.DataFrame) -> pd.DataFrame:
    from scripts.hmr_v1_baseline import load_closed_candles
    
    period_start = pd.Timestamp("2023-01-01", tz="UTC")
    period_end   = pd.Timestamp("2024-12-31 23:59:59", tz="UTC")
    settle_end   = pd.Timestamp("2025-01-10", tz="UTC")  # longer buffer for 672-bar (7d) exits
    
    print("Loading raw candles for high/low data...")
    candles_dict = load_closed_candles(
        Path("data/fresh_training_data_2023_2026"), COINS, "15m",
        period_start, period_end, settle_end, warmup_bars=100
    )
    
    candle_frames = []
    for coin, rows in candles_dict.items():
        dfc = pd.DataFrame(rows)
        dfc["timestamp"] = pd.to_datetime(dfc["time"], utc=True)
        dfc["symbol"] = coin
        candle_frames.append(dfc[["timestamp", "symbol", "high", "low"]])
        
    df_hl = pd.concat(candle_frames, ignore_index=True)
    scaffold = pd.merge(scaffold, df_hl, on=["timestamp", "symbol"], how="left")
    
    frames = []
    for symbol, group in scaffold.groupby("symbol"):
        g = group.sort_values("timestamp").copy()
        close = g["close"].values
        
        # Returns
        for H in (192, 288, 672):
            g[f"return_{H}"] = (g["close"].shift(-H) - g["close"]) / g["close"]
            g[f"abs_return_{H}"] = g[f"return_{H}"].abs()
            
        # Absolute Excursions & future ranges
        for H in (192, 288, 672):
            future_high_H, future_low_H = compute_future_range(g, H)
            g[f"future_range_{H}"] = (future_high_H - future_low_H) / g["close"]
            g[f"abs_move_{H}"] = np.maximum((future_high_H - g["close"]) / g["close"], (g["close"] - future_low_H) / g["close"])
            
        # Hit rates
        g["large_move_50_192"] = (g["abs_move_192"] * 10000.0 >= 50.0).astype(float)
        g["large_move_100_672"] = (g["abs_move_672"] * 10000.0 >= 100.0).astype(float)
        
        frames.append(g)
        
    return pd.concat(frames, ignore_index=True).dropna(subset=["return_672"])


def add_conditioning_state(df: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for _, group in df.sort_values("timestamp").groupby("symbol", sort=False):
        g = group.copy()
        returns = g["close"].pct_change()
        g["realized_volatility"] = returns.rolling(72).std()
        g["recent_high_low_range"] = (g["close"].rolling(72).max() - g["close"].rolling(72).min()) / g["close"]
        g["atr_percentile"] = g["recent_high_low_range"].rolling(288).rank(pct=True)
        # Compute recent 7d return of BTC for price trend conditioning
        frames.append(g)
    out = pd.concat(frames, ignore_index=True).fillna(0.0)
    
    # Compute global BTC recent 7d return to map to all rows
    btc = out[out["symbol"] == "BTC"].sort_values("timestamp").copy()
    btc["btc_recent_7d_return"] = btc["close"].pct_change(672)
    mapping = btc.set_index("timestamp")["btc_recent_7d_return"]
    out["btc_recent_7d_return"] = out["timestamp"].map(mapping).fillna(0.0)
    return out


def quantile_edges(period_a: pd.Series) -> np.ndarray:
    return np.nanpercentile(period_a, [20, 40, 60, 80])


def assign_quantile(values: pd.Series, edges: np.ndarray) -> pd.Series:
    return values.apply(lambda value: int(np.searchsorted(edges, value) + 1))


def spearman_rank(x: list[float], y: list[float]) -> float:
    if len(x) < 2 or len(set(y)) <= 1:
        return 0.0
    return float(pd.Series(x).corr(pd.Series(y), method="spearman"))


def finite_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return finite_or_none(value)
    return value


def assign_period(ts: pd.Timestamp) -> str | None:
    for name, (start, end) in PERIODS.items():
        if pd.Timestamp(start) <= ts <= pd.Timestamp(end):
            return name
    return None


def summarize_quantiles(df: pd.DataFrame, feature: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    q_rows: list[dict[str, Any]] = []
    feature_rows: list[dict[str, Any]] = []
    
    for period in ("A", "B", "C"):
        period_df = df[df["period"] == period]
        means_for_monotonicity = []
        for q in range(1, 6):
            g = period_df[period_df["q"] == q]
            row: dict[str, Any] = {"feature": feature, "period": period, "quantile": q, "count": int(len(g))}
            for target in (
                "return_8", "return_32", "return_72", "return_192", "return_288", "return_672",
                "abs_return_192", "abs_return_288", "future_range_192", "future_range_288",
                "large_move_50_192", "large_move_100_672", "long_30_20", "short_30_20"
            ):
                row[f"mean_{target}"] = finite_or_none(g[target].mean()) if len(g) else None
            means_for_monotonicity.append(row["mean_return_288"])
            q_rows.append(row)
            
        q1 = period_df[period_df["q"] == 1]
        q5 = period_df[period_df["q"] == 5]
        
        feature_rows.append(
            {
                "feature": feature,
                "period": period,
                "q1_count": int(len(q1)),
                "q5_count": int(len(q5)),
                "return_192_spread_bps": finite_or_none((q5["return_192"].mean() - q1["return_192"].mean()) * 10000.0) if len(q1) and len(q5) else None,
                "return_288_spread_bps": finite_or_none((q5["return_288"].mean() - q1["return_288"].mean()) * 10000.0) if len(q1) and len(q5) else None,
                "return_672_spread_bps": finite_or_none((q5["return_672"].mean() - q1["return_672"].mean()) * 10000.0) if len(q1) and len(q5) else None,
                "large_move_50_192_spread_pp": finite_or_none((q5["large_move_50_192"].mean() - q1["large_move_50_192"].mean()) * 100.0) if len(q1) and len(q5) else None,
                "large_move_100_672_spread_pp": finite_or_none((q5["large_move_100_672"].mean() - q1["large_move_100_672"].mean()) * 100.0) if len(q1) and len(q5) else None,
                "long_30_20_spread_pp": finite_or_none((q5["long_30_20"].mean() - q1["long_30_20"].mean()) * 100.0) if len(q1) and len(q5) else None,
                "short_30_20_spread_pp": finite_or_none((q5["short_30_20"].mean() - q1["short_30_20"].mean()) * 100.0) if len(q1) and len(q5) else None,
                "magnitude_monotonicity": finite_or_none(spearman_rank([1, 2, 3, 4, 5], [v or 0.0 for v in means_for_monotonicity])),
            }
        )
    return q_rows, feature_rows


def check_calendar_confounding(df: pd.DataFrame, feature: str) -> float:
    time_numeric = df["timestamp"].astype(np.int64)
    corr = float(df[feature].corr(time_numeric, method="spearman"))
    return corr


def check_distribution_shift(df: pd.DataFrame) -> dict[str, float]:
    result = {}
    for period in ("B", "C"):
        p_df = df[df["period"] == period]
        if p_df.empty:
            result[period] = 0.0
            continue
        max_frac = p_df["q"].value_counts(normalize=True).max()
        result[period] = float(max_frac)
    return result


def check_price_confounding_conditioning(df: pd.DataFrame, feature: str, target: str, scale: float = 1.0) -> dict[str, Any]:
    work = df.copy()
    # Condition on recent 7d BTC return buckets
    work["price_trend_bucket"] = pd.qcut(work["btc_recent_7d_return"].rank(method="first"), 3, labels=False, duplicates="drop")
    
    q1_all = work[work["q"] == 1]
    q5_all = work[work["q"] == 5]
    if q1_all.empty or q5_all.empty:
        raw = 0.0
    else:
        raw = (q5_all[target].mean() - q1_all[target].mean()) * scale
        
    weighted = 0.0
    total = 0
    for _, g in work.groupby("price_trend_bucket", dropna=True):
        low = g[g["q"] == 1]
        high = g[g["q"] == 5]
        if low.empty or high.empty:
            continue
        spread = (high[target].mean() - low[target].mean()) * scale
        weight = len(g)
        weighted += spread * weight
        total += weight
        
    conditional = weighted / total if total else 0.0
    retention = abs(conditional / raw) if abs(raw) >= 1e-12 else None
    return {
        "raw_spread": raw,
        "conditional_spread": conditional,
        "retention": retention,
        "same_sign": bool(np.sign(raw) == np.sign(conditional)) if raw and conditional else False,
    }


def conditional_incremental(df: pd.DataFrame, feature: str, target: str, scale: float = 1.0) -> dict[str, Any]:
    work = df.copy()
    work["atr_bucket"] = pd.qcut(work["atr_percentile"].rank(method="first"), 3, labels=False, duplicates="drop")
    work["rv_bucket"] = pd.qcut(work["realized_volatility"].rank(method="first"), 3, labels=False, duplicates="drop")
    
    q1_all = work[work["q"] == 1]
    q5_all = work[work["q"] == 5]
    if q1_all.empty or q5_all.empty:
        raw = 0.0
    else:
        raw = (q5_all[target].mean() - q1_all[target].mean()) * scale
        
    weighted = 0.0
    total = 0
    rows = []
    
    for (atr_bucket, rv_bucket), g in work.groupby(["atr_bucket", "rv_bucket"], dropna=True):
        low = g[g["q"] == 1]
        high = g[g["q"] == 5]
        if low.empty or high.empty:
            continue
        spread = (high[target].mean() - low[target].mean()) * scale
        weight = len(g)
        weighted += spread * weight
        total += weight
        rows.append(
            {
                "feature": feature,
                "target": target,
                "atr_bucket": int(atr_bucket),
                "realized_vol_bucket": int(rv_bucket),
                "count": int(weight),
                "spread": float(spread),
            }
        )
    conditional = weighted / total if total else 0.0
    retention = abs(conditional / raw) if abs(raw) >= 1e-12 else None
    return {
        "summary": {
            "feature": feature,
            "target": target,
            "raw_spread": float(raw),
            "conditional_spread": float(conditional),
            "retention": float(retention) if retention is not None else None,
            "same_sign": bool(np.sign(raw) == np.sign(conditional)) if raw and conditional else False,
        },
        "rows": rows,
    }


def monthly_stability(df: pd.DataFrame, feature: str, target: str, scale: float = 1.0) -> list[dict[str, Any]]:
    rows = []
    for month, g in df.groupby(df["timestamp"].dt.strftime("%Y-%m")):
        q1 = g[g["q"] == 1]
        q5 = g[g["q"] == 5]
        if q1.empty or q5.empty:
            continue
        rows.append(
            {
                "feature": feature,
                "target": target,
                "month": month,
                "count": int(len(g)),
                "spread": float((q5[target].mean() - q1[target].mean()) * scale),
            }
        )
    return rows


def asset_stability(df: pd.DataFrame, feature: str, target: str, scale: float = 1.0) -> list[dict[str, Any]]:
    rows = []
    for (period, symbol), g in df.groupby(["period", "symbol"]):
        q1 = g[g["q"] == 1]
        q5 = g[g["q"] == 5]
        if q1.empty or q5.empty:
            continue
        rows.append(
            {
                "feature": feature,
                "target": target,
                "period": period,
                "symbol": symbol,
                "count": int(len(g)),
                "spread": float((q5[target].mean() - q1[target].mean()) * scale),
            }
        )
    return rows


def bootstrap_ci(df: pd.DataFrame, feature: str, period: str, target: str, scale: float = 1.0, iterations: int = 100) -> dict[str, Any]:
    g = df[(df["period"] == period)]
    if g.empty:
        return {"feature": feature, "period": period, "target": target, "ci_low": None, "ci_high": None}
    values = []
    rng = np.random.default_rng(42)
    for _ in range(iterations):
        sample = g.sample(frac=1.0, replace=True, random_state=int(rng.integers(0, 1_000_000)))
        q1 = sample[sample["q"] == 1][target]
        q5 = sample[sample["q"] == 5][target]
        if not q1.empty and not q5.empty:
            values.append((q5.mean() - q1.mean()) * scale)
    if not values:
        return {"feature": feature, "period": period, "target": target, "ci_low": None, "ci_high": None}
    return {
        "feature": feature,
        "period": period,
        "target": target,
        "ci_low": float(np.percentile(values, 2.5)),
        "ci_high": float(np.percentile(values, 97.5)),
    }


def evaluate_tvl_verdict(
    feature: str,
    summaries: list[dict[str, Any]],
    conditional_dict: dict[str, dict[str, Any]],
    asset_rows: list[dict[str, Any]],
    ci_rows: list[dict[str, Any]],
    time_corr: float,
    drift_report: dict[str, float],
    price_corr: float,
    price_cond: dict[str, Any]
) -> str:
    by_period = {row["period"]: row for row in summaries}
    b = by_period.get("B", {})
    c = by_period.get("C", {})
    a = by_period.get("A", {})
    
    if not b or not c:
        return "BLOCKED_PROVENANCE"
        
    # T3 Calendar Confounding Gate
    if abs(time_corr) >= 0.80:
        return "REJECT_TIME_TREND_CONFOUNDED"
        
    # T4 Crypto-price Mechanical Confounding Gate
    # High correlation with recent market returns or if conditional spread shrinks heavily
    if abs(price_corr) >= 0.70 or (price_cond.get("retention") is not None and price_cond.get("retention") < 0.40):
        return "REJECT_MARK_TO_MARKET_PRICE_PROXY"
        
    # T11 Distribution Shift / Support Collapse Gate
    if drift_report.get("B", 0.0) >= 0.80 or drift_report.get("C", 0.0) >= 0.80:
        return "REJECT_SUPPORT_COLLAPSE"
        
    # Economic spread floors (T5)
    # 48h >= 10 bps, 72h >= 15 bps, 7d >= 25 bps
    spread_48_b, spread_48_c = b.get("return_192_spread_bps") or 0.0, c.get("return_192_spread_bps") or 0.0
    spread_72_b, spread_72_c = b.get("return_288_spread_bps") or 0.0, c.get("return_288_spread_bps") or 0.0
    spread_7d_b, spread_7d_c = b.get("return_672_spread_bps") or 0.0, c.get("return_672_spread_bps") or 0.0
    
    pass_48 = abs(spread_48_b) >= 10.0 and abs(spread_48_c) >= 10.0 and np.sign(spread_48_b) == np.sign(spread_48_c)
    pass_72 = abs(spread_72_b) >= 15.0 and abs(spread_72_c) >= 15.0 and np.sign(spread_72_b) == np.sign(spread_72_c)
    pass_7d = abs(spread_7d_b) >= 25.0 and abs(spread_7d_c) >= 25.0 and np.sign(spread_7d_b) == np.sign(spread_7d_c)
    
    t5_directional = pass_48 or pass_72 or pass_7d
    
    # T9 Cross asset same sign
    btc_signs = {}
    eth_signs = {}
    bnb_signs = {}
    for row in asset_rows:
        if row["period"] in ("B", "C"):
            k = (row["period"], row["target"])
            if row["symbol"] == "BTC":
                btc_signs[k] = np.sign(row["spread"])
            elif row["symbol"] == "ETH":
                eth_signs[k] = np.sign(row["spread"])
            elif row["symbol"] == "BNB":
                bnb_signs[k] = np.sign(row["spread"])
                
    t9_cross_asset = False
    for k in btc_signs:
        if k in eth_signs and k in bnb_signs:
            signs = [btc_signs[k], eth_signs[k], bnb_signs[k]]
            same_sign_count = max(signs.count(1), signs.count(-1))
            if same_sign_count >= 2:
                sp_btc = abs(next((r["spread"] for r in asset_rows if r["period"] == k[0] and r["target"] == k[1] and r["symbol"] == "BTC"), 0.0))
                sp_eth = abs(next((r["spread"] for r in asset_rows if r["period"] == k[0] and r["target"] == k[1] and r["symbol"] == "ETH"), 0.0))
                sp_bnb = abs(next((r["spread"] for r in asset_rows if r["period"] == k[0] and r["target"] == k[1] and r["symbol"] == "BNB"), 0.0))
                total_sp = sp_btc + sp_eth + sp_bnb
                if total_sp > 0:
                    dominant_pct = max(sp_btc, sp_eth, sp_bnb) / total_sp
                    if dominant_pct <= 0.70:
                        t9_cross_asset = True
                        break
                        
    # T10 Bootstrap excludes zero
    t10_targets = set()
    for row in ci_rows:
        if row["period"] in ("B", "C"):
            low = row["ci_low"]
            high = row["ci_high"]
            if low is not None and high is not None:
                if not (low <= 0.0 <= high):
                    t10_targets.add((row["period"], row["target"]))
    t10 = False
    for target in ("return_672", "return_288", "return_192"):
        if ("B", target) in t10_targets and ("C", target) in t10_targets:
            t10 = True
            break
            
    # T6 Inversion check (A -> B/C inversion)
    spr48_a = a.get("return_192_spread_bps") or 0.0
    spr72_a = a.get("return_288_spread_bps") or 0.0
    spr7d_a = a.get("return_672_spread_bps") or 0.0
    
    inversion_48 = np.sign(spr48_a) != np.sign(spread_48_b) if spr48_a and spread_48_b else False
    inversion_72 = np.sign(spr72_a) != np.sign(spread_72_b) if spr72_a and spread_72_b else False
    inversion_7d = np.sign(spr7d_a) != np.sign(spread_7d_b) if spr7d_a and spread_7d_b else False
    
    t6_directional = not (inversion_48 or inversion_72 or inversion_7d)
    
    # Conditional checks for regime-only promotion
    regime_stable = False
    for target in ("large_move_50_192", "large_move_100_672", "long_30_20", "short_30_20"):
        cond_data = conditional_dict.get(target, {}).get("summary", {})
        cond_spread = cond_data.get("conditional_spread") or 0.0
        raw_spread = cond_data.get("raw_spread") or 0.0
        retention = cond_data.get("retention") or 0.0
        same_sign = cond_data.get("same_sign") or False
        if abs(cond_spread) >= 3.0 and same_sign and retention >= 0.40:
            regime_stable = True
            
    # Verdict taxonomy emission
    if t5_directional and t6_directional and t9_cross_asset and t10:
        if pass_7d:
            return "PROMOTE_MEDIUM_HORIZON_DIRECTIONAL"
        return "PROMOTE_DIRECTIONAL_AND_REGIME"
        
    if regime_stable and t6_directional:
        return "PROMOTE_CAPITAL_REGIME_INFORMATION"
        
    if not t6_directional or (np.sign(spread_72_b) != np.sign(spread_72_c) if spread_72_b and spread_72_c else False):
        return "REJECT_NON_TRANSPORTABLE"
        
    return "REJECT_NO_ECONOMIC_INFORMATION"


def run_audit() -> dict[str, Any]:
    print(f"{REVISION}: starting DeFi TVL liquidity audit")
    
    # Load candles outcome scaffold
    scaffold = pd.read_parquet(SCAFFOLD_PATH)
    scaffold["timestamp"] = pd.to_datetime(scaffold["timestamp"], utc=True)
    scaffold = scaffold[scaffold["symbol"].isin(ELIGIBLE_ASSETS)].copy()
    
    # Add new targets
    scaffold = add_longer_horizon_targets(scaffold)
    
    # Add conditioning states (including global BTC recent return)
    scaffold = add_conditioning_state(scaffold)
    
    # Load TVL and merge
    tvl_df = load_raw_tvl()
    merged = merge_tvl(scaffold, tvl_df)
    
    merged["period"] = merged["timestamp"].apply(assign_period)
    merged = merged[merged["period"].notna()].copy()
    
    # Usable coverage
    usable = merged[merged["defi_tvl_level"].notna() & ~merged["tvl_stale"]].copy()
    coverage = len(usable) / len(merged) if len(merged) else 0.0
    print(f"Coverage: {coverage:.2%} ({len(usable)} usable / {len(merged)} total)")
    
    all_quantiles = []
    all_summaries = []
    all_conditional_rows = []
    all_conditional_summaries = []
    all_monthly = []
    all_asset = []
    all_ci = []
    all_distribution_shifts = []
    feature_verdicts = []
    quantile_assignment_frames = []
    
    for feature in FEATURES:
        print(f"Auditing feature: {feature}")
        work = usable.copy()
        
        # Fit quantiles on Period A
        period_a_vals = work[work["period"] == "A"][feature]
        edges = quantile_edges(period_a_vals)
        work["q"] = assign_quantile(work[feature], edges)
        
        # 1. Summaries & quantiles
        q_rows, summaries = summarize_quantiles(work, feature)
        all_quantiles.extend(q_rows)
        all_summaries.extend(summaries)
        
        # 2. Check calendar confounding (T3)
        time_corr = check_calendar_confounding(work, feature)
        print(f"Feature {feature} correlation with calendar time: {time_corr:.4f}")
        
        # 3. Check price mechanical coupling (T4)
        price_corr = float(work[feature].corr(work["btc_recent_7d_return"], method="spearman"))
        price_cond = check_price_confounding_conditioning(work, feature, "return_288", 10000.0)
        print(f"Feature {feature} correlation with BTC price: {price_corr:.4f}, retention: {price_cond.get('retention')}")
        
        # 4. Check distribution shifts (T11)
        drift_report = check_distribution_shift(work)
        for p, max_frac in drift_report.items():
            all_distribution_shifts.append({
                "feature": feature,
                "period": p,
                "max_quantile_fraction": max_frac,
                "collapse_risk": bool(max_frac >= 0.80)
            })
        print(f"Feature {feature} drift fractions: B={drift_report.get('B', 0.0):.2f}, C={drift_report.get('C', 0.0):.2f}")
        
        # 5. Conditioning state (ATR, RV)
        conditional_dict = {}
        for target, scale in (
            ("return_192", 10000.0),
            ("return_288", 10000.0),
            ("return_672", 10000.0),
            ("large_move_50_192", 100.0),
            ("large_move_100_672", 100.0),
            ("long_30_20", 100.0),
            ("short_30_20", 100.0)
        ):
            cond = conditional_incremental(work, feature, target, scale)
            all_conditional_rows.extend(cond["rows"])
            all_conditional_summaries.append(cond["summary"])
            conditional_dict[target] = cond
            
        # 6. Monthly stability
        for target, scale in (("return_288", 10000.0), ("long_30_20", 100.0), ("short_30_20", 100.0)):
            all_monthly.extend(monthly_stability(work, feature, target, scale))
            
        # 7. Asset stability (cross-asset)
        for target, scale in (("return_288", 10000.0), ("long_30_20", 100.0), ("short_30_20", 100.0)):
            all_asset.extend(asset_stability(work, feature, target, scale))
            
        # 8. Bootstrap CI
        ci_rows = []
        for period in ("B", "C"):
            for target, scale in (("return_192", 10000.0), ("return_288", 10000.0), ("return_672", 10000.0)):
                ci = bootstrap_ci(work, feature, period, target, scale)
                ci_rows.append(ci)
                all_ci.append(ci)
                
        # 9. Evaluate TVL verdict
        verdict = evaluate_tvl_verdict(
            feature, summaries, conditional_dict, all_asset, ci_rows, time_corr, drift_report, price_corr, price_cond
        )
        feature_verdicts.append({
            "feature": feature,
            "period_a_edges": [float(x) for x in edges],
            "verdict": verdict,
            "calendar_time_correlation": time_corr,
            "price_mechanical_correlation": price_corr,
            "price_conditioning_retention": price_cond.get("retention"),
            "distribution_drift": drift_report
        })
        print(f"Feature {feature} verdict: {verdict}")
        
        # Save assignment
        cols = [
            "decision_time", "symbol", "period", "q", 
            "defi_tvl_level", "source_timestamp", "available_at", 
            "tvl_age_seconds", "tvl_stale"
        ]
        frame = work[cols].copy()
        frame["feature_value"] = work[feature]
        frame["feature"] = feature
        quantile_assignment_frames.append(frame)
        
    # Write Parquet outputs
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.concat(quantile_assignment_frames, ignore_index=True).to_parquet(OUT_DIR / "v4a_6_tvl_quantiles.parquet", index=False)
    pd.DataFrame(all_conditional_rows).to_parquet(OUT_DIR / "v4a_6_tvl_conditional.parquet", index=False)
    pd.DataFrame(all_monthly).to_parquet(OUT_DIR / "v4a_6_tvl_monthly_stability.parquet", index=False)
    pd.DataFrame(all_asset).to_parquet(OUT_DIR / "v4a_6_tvl_asset_stability.parquet", index=False)
    pd.DataFrame(all_distribution_shifts).to_parquet(OUT_DIR / "v4a_6_tvl_distribution_shift.parquet", index=False)
    
    # Build verdict output JSON
    output = {
        "program": REVISION,
        "source": "defillama_tvl",
        "information_class": ["LIQUIDITY_REGIME", "MEDIUM_HORIZON_DIRECTIONAL"],
        "primary_horizons": ["48h", "72h", "7d"],
        "short_horizon_directional_use": "DIAGNOSTIC_ONLY",
        "provenance_gate": "PROCEED_WITH_LAG_CAVEAT",
        "source_authenticity": "PASS_WITH_CONSERVATIVE_LAG",
        "source_class": "EXTERNAL_RECONSTRUCTED_HISTORY",
        "historical_parity": "H2_ASOF_RECONSTRUCTABLE",
        "archived_publication_parity": "NOT_PROVEN",
        "availability_policy": "CONSERVATIVE_ASSUMPTION_12UTC",
        "production_evidence_eligible": False,
        "research_inference_eligible": True,
        "temporal_ordering_gate": "PASS" if (usable["available_at"] <= usable["decision_time"]).all() else "FAIL",
        "coverage_gate": "PASS" if coverage >= 0.90 else "FAIL",
        "usable_coverage": round(float(coverage), 6),
        "eligible_assets": list(ELIGIBLE_ASSETS),
        "feature_set": list(FEATURES),
        "primary_targets": ["return_192", "return_288", "return_672", "large_move_50_192", "large_move_100_672"],
        "feature_summaries": all_summaries,
        "conditional_summaries": all_conditional_summaries,
        "uncertainty": all_ci,
        "distribution_shifts": all_distribution_shifts,
        "feature_verdicts": feature_verdicts,
    }
    
    output = json_safe(output)
    (OUT_DIR / "v4a_6_tvl_audit.json").write_text(json.dumps(output, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Saved JSON audit verdict to {OUT_DIR / 'v4a_6_tvl_audit.json'}")
    
    write_report(output)
    return output


def write_report(output: dict[str, Any]) -> None:
    def fmt(value: Any) -> str:
        return "n/a" if value is None else f"{float(value):.2f}"

    lines = [
        f"# {output['program']} DeFi TVL liquidity Audit Report",
        "",
        "## Contract & Provenance",
        "",
        f"- **Source authenticity**: `{output['source_authenticity']}`",
        f"- **Historical parity**: `{output['historical_parity']}`",
        f"- **Temporal validity gate**: `{output['temporal_ordering_gate']}` (12-hour conservative lag enforced)",
        f"- **Usable coverage**: `{output['usable_coverage']:.2%}` (`{output['coverage_gate']}`)",
        f"- **Production evidence eligibility**: `ELIGIBLE_FOR_PRODUCTION = {output['production_evidence_eligible']}`",
        f"- **Availability policy**: `{output['availability_policy']}`",
        f"- **Archived publication parity**: `{output['archived_publication_parity']}`",
        "",
        f"Eligible assets: `{', '.join(output['eligible_assets'])}`.",
        "",
        "## Feature Verdicts",
        "",
        "| Feature | Calendar Correlation | Price Correlation | Price conditioning retention | Verdict |",
        "| --- | :---: | :---: | :---: | --- |",
    ]
    for row in output["feature_verdicts"]:
        lines.append(
            f"| `{row['feature']}` | {fmt(row['calendar_time_correlation'])} | "
            f"{fmt(row['price_mechanical_correlation'])} | {fmt(row['price_conditioning_retention'])} | `{row['verdict']}` |"
        )
        
    lines.extend([
        "",
        "## Primary Medium-Horizon Spreads (Q5 - Q1)",
        "",
        "| Feature | Period | Return 48h (bps) | Return 72h (bps) | Return 7d (bps) | Large 50_192 (pp) | Large 100_672 (pp) | Monotonicity |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"
    ])
    
    for row in output["feature_summaries"]:
        lines.append(
            f"| `{row['feature']}` | {row['period']} | "
            f"{fmt(row['return_192_spread_bps'])} | "
            f"{fmt(row['return_288_spread_bps'])} | "
            f"{fmt(row['return_672_spread_bps'])} | "
            f"{fmt(row['large_move_50_192_spread_pp'])} | "
            f"{fmt(row['large_move_100_672_spread_pp'])} | "
            f"{fmt(row['magnitude_monotonicity'])} |"
        )
        
    lines.extend([
        "",
        "## Period Effect Vectors and Sign Patterns",
        "",
        "| Feature | Target | Period Spreads [A, B, C] | Sign Pattern | Transport Verdict |",
        "| --- | --- | :---: | :---: | :---: |"
    ])
    
    feat_target_map = {}
    for row in output["feature_summaries"]:
        feat = row["feature"]
        period = row["period"]
        for target in ("return_192_spread_bps", "return_288_spread_bps", "return_672_spread_bps"):
            val = row[target]
            feat_target_map.setdefault((feat, target), {})[period] = val
            
    for (feat, target), p_map in sorted(feat_target_map.items()):
        val_a, val_b, val_c = p_map.get("A"), p_map.get("B"), p_map.get("C")
        if val_a is None or val_b is None or val_c is None:
            continue
        sa = "+" if val_a >= 0 else "-"
        sb = "+" if val_b >= 0 else "-"
        sc = "+" if val_c >= 0 else "-"
        pattern = f"{sa}{sb}{sc}"
        
        # transport verdict
        if sb != sc:
            verdict = "NON_TRANSPORTABLE"
        elif sa != sb:
            verdict = "A->B/C INVERSION"
        else:
            verdict = "TRANSPORTABLE"
            
        name = target.replace('_spread_bps','').replace('return_192','return_48h').replace('return_288','return_72h').replace('return_672','return_7d')
        lines.append(
            f"| `{feat}` | `{name}` | "
            f"[{val_a:+.1f}, {val_b:+.1f}, {val_c:+.1f}] | `{pattern}` | `{verdict}` |"
        )
        
    (OUT_DIR / "v4a_6_tvl_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved Markdown report to {OUT_DIR / 'v4a_6_tvl_report.md'}")


if __name__ == "__main__":
    run_audit()
