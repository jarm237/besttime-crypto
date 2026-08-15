#!/usr/bin/env python3
"""HMR-V4A-4-r1: Alternative.me Fear & Greed sentiment information audit."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4a_outcome_scaffold.parquet"
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"
RAW_SENTIMENT_DIR = REPO_ROOT / "research/alternative_history_validation/raw/alternative_me"

REVISION = "HMR-V4A-4-r1"
ELIGIBLE_ASSETS = ("BTC", "ETH")
DERIVED_CONTROL_ASSETS = ("BNB",)
FEATURES = ("fear_greed_level", "fear_greed_delta_1d", "fear_greed_delta_7d", "fear_greed_percentile_90d")

PERIODS = {
    "A": ("2023-01-01T00:00:00+00:00", "2024-06-30T23:59:59+00:00"),
    "B": ("2024-07-01T00:00:00+00:00", "2024-09-30T23:59:59+00:00"),
    "C": ("2024-10-01T00:00:00+00:00", "2024-12-31T23:59:59+00:00"),
}


def load_raw_sentiment() -> pd.DataFrame:
    # Find attempt1 JSON files in the raw directory
    files = list(RAW_SENTIMENT_DIR.glob("*_attempt1.json"))
    if not files:
        raise FileNotFoundError(f"No raw alternative_me JSON files found in {RAW_SENTIMENT_DIR}")
    # Choose the latest file by name/mtime
    latest_file = sorted(files)[-1]
    print(f"Loading raw Alternative.me data from: {latest_file.name}")
    
    with open(latest_file, "r") as f:
        payload = json.load(f)
    
    records = payload.get("json", {}).get("data", [])
    if not records:
        raise ValueError("No data records found in JSON payload")
        
    parsed = []
    for r in records:
        ts = int(r["timestamp"])
        val = float(r["value"])
        label = r["value_classification"]
        source_timestamp = pd.to_datetime(ts, unit="s", utc=True)
        # Apply the frozen conservative availability lag of 6 hours
        available_at = source_timestamp + pd.Timedelta(hours=6)
        parsed.append({
            "source_date": source_timestamp.strftime("%Y-%m-%d"),
            "source_timestamp": source_timestamp,
            "available_at": available_at,
            "fear_greed_level": val,
            "fear_greed_label": label
        })
        
    df = pd.DataFrame(parsed)
    df = df.drop_duplicates(subset=["available_at"]).sort_values("available_at").reset_index(drop=True)
    
    # Compute the 4 frozen features daily
    df["fear_greed_delta_1d"] = df["fear_greed_level"].diff(1)
    df["fear_greed_delta_7d"] = df["fear_greed_level"].diff(7)
    df["fear_greed_percentile_90d"] = df["fear_greed_level"].rolling(90, min_periods=30).rank(pct=True)
    return df.dropna(subset=["fear_greed_percentile_90d"]).reset_index(drop=True)


def merge_sentiment(scaffold: pd.DataFrame, sentiment: pd.DataFrame) -> pd.DataFrame:
    merged = []
    # Merge for each symbol individually
    for symbol in ELIGIBLE_ASSETS + DERIVED_CONTROL_ASSETS:
        left = scaffold[scaffold["symbol"] == symbol].sort_values("timestamp").copy()
        right = sentiment.sort_values("available_at").copy()
        
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
    out["sentiment_age_seconds"] = (out["decision_time"] - out["available_at"]).dt.total_seconds()
    out["sentiment_stale"] = out["sentiment_age_seconds"] > 48 * 3600  # Stale if no update for 48 hours
    return out


def add_conditioning_state(df: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for _, group in df.sort_values("timestamp").groupby("symbol", sort=False):
        g = group.copy()
        returns = g["close"].pct_change()
        g["realized_volatility"] = returns.rolling(72).std()
        g["recent_high_low_range"] = (g["close"].rolling(72).max() - g["close"].rolling(72).min()) / g["close"]
        g["atr_percentile"] = g["recent_high_low_range"].rolling(288).rank(pct=True)
        frames.append(g)
    return pd.concat(frames, ignore_index=True).fillna(0.0)


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
            for target in ("return_32", "return_72", "long_30_20", "short_30_20", "large_move_30"):
                row[f"mean_{target}"] = finite_or_none(g[target].mean()) if len(g) else None
            means_for_monotonicity.append(row["mean_return_72"])
            q_rows.append(row)
            
        q1 = period_df[period_df["q"] == 1]
        q5 = period_df[period_df["q"] == 5]
        
        feature_rows.append(
            {
                "feature": feature,
                "period": period,
                "q1_count": int(len(q1)),
                "q5_count": int(len(q5)),
                "return_32_spread_bps": finite_or_none((q5["return_32"].mean() - q1["return_32"].mean()) * 10000.0) if len(q1) and len(q5) else None,
                "return_72_spread_bps": finite_or_none((q5["return_72"].mean() - q1["return_72"].mean()) * 10000.0) if len(q1) and len(q5) else None,
                "long_30_20_spread_pp": finite_or_none((q5["long_30_20"].mean() - q1["long_30_20"].mean()) * 100.0) if len(q1) and len(q5) else None,
                "short_30_20_spread_pp": finite_or_none((q5["short_30_20"].mean() - q1["short_30_20"].mean()) * 100.0) if len(q1) and len(q5) else None,
                "large_move_30_spread_pp": finite_or_none((q5["large_move_30"].mean() - q1["large_move_30"].mean()) * 100.0) if len(q1) and len(q5) else None,
                "magnitude_monotonicity": finite_or_none(spearman_rank([1, 2, 3, 4, 5], [v or 0.0 for v in means_for_monotonicity])),
            }
        )
    return q_rows, feature_rows


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


def evaluate_feature_verdict(
    summaries: list[dict[str, Any]],
    conditional_dict: dict[str, dict[str, Any]],
    asset_rows: list[dict[str, Any]],
    ci_rows: list[dict[str, Any]],
) -> str:
    by_period = {row["period"]: row for row in summaries}
    b = by_period.get("B", {})
    c = by_period.get("C", {})
    a = by_period.get("A", {})
    
    if not b or not c:
        return "BLOCKED_PROVENANCE"
        
    # Gates evaluation variables
    # S3: Same sign B & C for return spreads or directional probabilities
    ret32_b, ret32_c = b.get("return_32_spread_bps") or 0.0, c.get("return_32_spread_bps") or 0.0
    ret72_b, ret72_c = b.get("return_72_spread_bps") or 0.0, c.get("return_72_spread_bps") or 0.0
    long_b, long_c = b.get("long_30_20_spread_pp") or 0.0, c.get("long_30_20_spread_pp") or 0.0
    short_b, short_c = b.get("short_30_20_spread_pp") or 0.0, c.get("short_30_20_spread_pp") or 0.0
    
    s3_ret32 = np.sign(ret32_b) == np.sign(ret32_c) and abs(ret32_b) >= 1.0
    s3_ret72 = np.sign(ret72_b) == np.sign(ret72_c) and abs(ret72_b) >= 1.0
    s3_long = np.sign(long_b) == np.sign(long_c) and abs(long_b) >= 0.1
    s3_short = np.sign(short_b) == np.sign(short_c) and abs(short_b) >= 0.1
    
    s3_directional = s3_ret32 or s3_ret72 or s3_long or s3_short
    
    # S4: Return spread >= 10 bps in B & C
    s4_ret32 = abs(ret32_b) >= 10.0 and abs(ret32_c) >= 10.0 and np.sign(ret32_b) == np.sign(ret32_c)
    s4_ret72 = abs(ret72_b) >= 10.0 and abs(ret72_c) >= 10.0 and np.sign(ret72_b) == np.sign(ret72_c)
    s4 = s4_ret32 or s4_ret72
    
    # S5: Outcome discrimination >= 5 percentage-points for long_30_20 or short_30_20 in B and C
    s5_long = abs(long_b) >= 5.0 and abs(long_c) >= 5.0 and np.sign(long_b) == np.sign(long_c)
    s5_short = abs(short_b) >= 5.0 and abs(short_c) >= 5.0 and np.sign(short_b) == np.sign(short_c)
    s5 = s5_long or s5_short
    
    # S8: Cross-asset same sign
    # Get spreads by asset for Period B and C
    btc_signs = {}
    eth_signs = {}
    for row in asset_rows:
        if row["period"] in ("B", "C"):
            k = (row["period"], row["target"])
            if row["symbol"] == "BTC":
                btc_signs[k] = np.sign(row["spread"])
            elif row["symbol"] == "ETH":
                eth_signs[k] = np.sign(row["spread"])
                
    s8 = False
    for k in btc_signs:
        if k in eth_signs and btc_signs[k] == eth_signs[k]:
            s8 = True
            break
            
    # S9: Bootstrap CI excludes 0 in B & C
    # Find if there is any target that has CI excluding 0 in both B and C
    s9_targets = set()
    for row in ci_rows:
        if row["period"] in ("B", "C"):
            low = row["ci_low"]
            high = row["ci_high"]
            if low is not None and high is not None:
                if not (low <= 0.0 <= high):
                    s9_targets.add((row["period"], row["target"]))
                    
    s9 = False
    for target in ("return_72", "long_30_20", "short_30_20"):
        if ("B", target) in s9_targets and ("C", target) in s9_targets:
            s9 = True
            break
            
    # S10: Transportability (no A -> B/C inversion)
    # Signs in A, B, and C are the same
    ret32_a = a.get("return_32_spread_bps") or 0.0
    ret72_a = a.get("return_72_spread_bps") or 0.0
    long_a = a.get("long_30_20_spread_pp") or 0.0
    short_a = a.get("short_30_20_spread_pp") or 0.0
    
    s10_ret32 = np.sign(ret32_a) == np.sign(ret32_b) == np.sign(ret32_c) if ret32_a and ret32_b else True
    s10_ret72 = np.sign(ret72_a) == np.sign(ret72_b) == np.sign(ret72_c) if ret72_a and ret72_b else True
    s10_long = np.sign(long_a) == np.sign(long_b) == np.sign(long_c) if long_a and long_b else True
    s10_short = np.sign(short_a) == np.sign(short_b) == np.sign(short_c) if short_a and short_b else True
    
    s10 = s10_ret32 and s10_ret72 and s10_long and s10_short
    
    # Conditional checks for regime-only promotion
    # Let's inspect conditional spreads for long_30_20, short_30_20 and large_move_30
    regime_stable = False
    for target in ("long_30_20", "short_30_20", "large_move_30"):
        cond_data = conditional_dict.get(target, {}).get("summary", {})
        cond_spread = cond_data.get("conditional_spread") or 0.0
        raw_spread = cond_data.get("raw_spread") or 0.0
        retention = cond_data.get("retention") or 0.0
        same_sign = cond_data.get("same_sign") or False
        # If conditional spread is significant and same sign as raw
        if abs(cond_spread) >= 2.0 and same_sign and retention >= 0.40:
            regime_stable = True
            
    # Final verdict taxonomy logic
    if s3_directional and s4 and s5 and s8 and s9 and s10:
        return "PROMOTE_DIRECTIONAL_AND_REGIME" if regime_stable else "PROMOTE_DIRECTIONAL_INFORMATION"
        
    if regime_stable and s10:
        return "PROMOTE_REGIME_INFORMATION_ONLY"
        
    # Check if failed due to inversion/transportability
    if not s10 or (s3_directional and np.sign(ret72_b) != np.sign(ret72_c)):
        return "REJECT_NON_TRANSPORTABLE"
        
    return "REJECT_NO_ECONOMIC_INFORMATION"


def run_audit() -> dict[str, Any]:
    print(f"{REVISION}: starting Alternative.me sentiment audit")
    
    # Load candles scaffold
    scaffold = pd.read_parquet(SCAFFOLD_PATH)
    scaffold["timestamp"] = pd.to_datetime(scaffold["timestamp"], utc=True)
    scaffold = scaffold[scaffold["symbol"].isin(ELIGIBLE_ASSETS + DERIVED_CONTROL_ASSETS)].copy()
    
    # Add large_move_30 target
    scaffold["large_move_30"] = (scaffold["abs_move_72"] * 10000.0 >= 30.0).astype(float)
    
    # Add conditioning state fields (ATR, realized volatility)
    scaffold = add_conditioning_state(scaffold)
    
    # Load sentiment and merge
    sentiment_df = load_raw_sentiment()
    merged = merge_sentiment(scaffold, sentiment_df)
    
    merged["period"] = merged["timestamp"].apply(assign_period)
    merged = merged[merged["period"].notna()].copy()
    
    # Filter usable
    usable = merged[merged["fear_greed_level"].notna() & ~merged["sentiment_stale"]].copy()
    coverage = len(usable) / len(merged) if len(merged) else 0.0
    print(f"Coverage: {coverage:.2%} ({len(usable)} usable / {len(merged)} total)")
    
    all_quantiles = []
    all_summaries = []
    all_conditional_rows = []
    all_conditional_summaries = []
    all_monthly = []
    all_asset = []
    all_ci = []
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
        
        # 2. Conditioning state (ATR, RV)
        conditional_dict = {}
        for target, scale in (
            ("return_32", 10000.0),
            ("return_72", 10000.0),
            ("long_30_20", 100.0),
            ("short_30_20", 100.0),
            ("large_move_30", 100.0)
        ):
            cond = conditional_incremental(work, feature, target, scale)
            all_conditional_rows.extend(cond["rows"])
            all_conditional_summaries.append(cond["summary"])
            conditional_dict[target] = cond
            
        # 3. Monthly stability
        for target, scale in (("return_72", 10000.0), ("long_30_20", 100.0), ("short_30_20", 100.0)):
            all_monthly.extend(monthly_stability(work, feature, target, scale))
            
        # 4. Asset stability (cross-asset)
        for target, scale in (("return_72", 10000.0), ("long_30_20", 100.0), ("short_30_20", 100.0)):
            all_asset.extend(asset_stability(work, feature, target, scale))
            
        # 5. Bootstrap CI
        ci_rows = []
        for period in ("B", "C"):
            for target, scale in (("return_72", 10000.0), ("long_30_20", 100.0), ("short_30_20", 100.0)):
                ci = bootstrap_ci(work, feature, period, target, scale)
                ci_rows.append(ci)
                all_ci.append(ci)
                
        # 6. Evaluate feature verdict
        verdict = evaluate_feature_verdict(summaries, conditional_dict, all_asset, ci_rows)
        feature_verdicts.append({
            "feature": feature,
            "period_a_edges": [float(x) for x in edges],
            "verdict": verdict
        })
        print(f"Feature {feature} verdict: {verdict}")
        
        # Save assignment
        cols = [
            "decision_time", "symbol", "period", "q", 
            "fear_greed_level", "source_timestamp", "available_at", 
            "sentiment_age_seconds", "sentiment_stale"
        ]
        frame = work[cols].copy()
        frame["feature_value"] = work[feature]
        frame["feature"] = feature
        quantile_assignment_frames.append(frame)

        
    # Write Parquet outputs
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pd.concat(quantile_assignment_frames, ignore_index=True).to_parquet(OUT_DIR / "v4a_4_sentiment_quantiles.parquet", index=False)
    pd.DataFrame(all_conditional_rows).to_parquet(OUT_DIR / "v4a_4_sentiment_conditional.parquet", index=False)
    pd.DataFrame(all_monthly).to_parquet(OUT_DIR / "v4a_4_sentiment_monthly_stability.parquet", index=False)
    pd.DataFrame(all_asset).to_parquet(OUT_DIR / "v4a_4_sentiment_asset_stability.parquet", index=False)
    
    # Build verdict output dictionary
    output = {
        "program": REVISION,
        "source": "alternative_me",
        "provenance_gate": "PROCEED_WITH_LAG_CAVEAT",
        "source_authenticity": "PASS",
        "source_class": "EXTERNAL_PUBLISHED_OBSERVATION",
        "historical_parity": "H2_DATE_LEVEL_ASOF",
        "archived_pit_parity_gate": "NOT_PROVEN",
        "production_evidence_eligible": False,
        "research_inference_eligible": True,
        "temporal_ordering_gate": "PASS" if (usable["available_at"] <= usable["decision_time"]).all() else "FAIL",
        "coverage_gate": "PASS" if coverage >= 0.90 else "FAIL",
        "usable_coverage": round(float(coverage), 6),
        "eligible_assets": list(ELIGIBLE_ASSETS),
        "derived_control_assets": list(DERIVED_CONTROL_ASSETS),
        "feature_set": list(FEATURES),
        "primary_targets": ["return_32", "return_72", "long_30_20", "short_30_20", "large_move_30"],
        "feature_summaries": all_summaries,
        "conditional_summaries": all_conditional_summaries,
        "uncertainty": all_ci,
        "feature_verdicts": feature_verdicts,
    }
    
    output = json_safe(output)
    (OUT_DIR / "v4a_4_sentiment_audit.json").write_text(json.dumps(output, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Saved JSON audit verdict to {OUT_DIR / 'v4a_4_sentiment_audit.json'}")
    
    write_report(output)
    return output


def write_report(output: dict[str, Any]) -> None:
    def fmt(value: Any) -> str:
        return "n/a" if value is None else f"{float(value):.2f}"

    lines = [
        f"# {output['program']} Alternative.me Fear & Greed Sentiment Audit",
        "",
        "## Contract & Provenance",
        "",
        f"- **Source authenticity**: `{output['source_authenticity']}`",
        f"- **Historical parity**: `{output['historical_parity']}`",
        f"- **Temporal validity gate**: `{output['temporal_ordering_gate']}` (6-hour conservative lag enforced)",
        f"- **Usable coverage**: `{output['usable_coverage']:.2%}` (`{output['coverage_gate']}`)",
        f"- **Production evidence eligibility**: `ELIGIBLE_FOR_PRODUCTION = {output['production_evidence_eligible']}`",
        "",
        f"Eligible assets: `{', '.join(output['eligible_assets'])}`. Control-only assets: `{', '.join(output['derived_control_assets'])}`.",
        "",
        "## Feature Verdicts",
        "",
        "| Feature | Verdict |",
        "| --- | --- |",
    ]
    for row in output["feature_verdicts"]:
        lines.append(f"| `{row['feature']}` | `{row['verdict']}` |")
        
    lines.extend([
        "",
        "## Primary Period Spreads (Q5 - Q1)",
        "",
        "| Feature | Period | Return 32 Spread (bps) | Return 72 Spread (bps) | Long 30/20 Spread (pp) | Short 30/20 Spread (pp) | Large Move 30 (pp) | Monotonicity |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"
    ])
    
    for row in output["feature_summaries"]:
        lines.append(
            f"| `{row['feature']}` | {row['period']} | "
            f"{fmt(row['return_32_spread_bps'])} | "
            f"{fmt(row['return_72_spread_bps'])} | "
            f"{fmt(row['long_30_20_spread_pp'])} | "
            f"{fmt(row['short_30_20_spread_pp'])} | "
            f"{fmt(row['large_move_30_spread_pp'])} | "
            f"{fmt(row['magnitude_monotonicity'])} |"
        )
        
    # Add Section on sign vectors and patterns
    lines.extend([
        "",
        "## Period Effect Vectors and Sign Patterns",
        "",
        "| Feature | Target | Period Spreads [A, B, C] | Sign Pattern | Transport Verdict |",
        "| --- | --- | :---: | :---: | :---: |"
    ])
    
    # Group summaries by feature and target to output effect vectors
    feat_target_map = {}
    for row in output["feature_summaries"]:
        feat = row["feature"]
        period = row["period"]
        for target, scale_unit in (
            ("return_72_spread_bps", "bps"),
            ("long_30_20_spread_pp", "pp"),
            ("short_30_20_spread_pp", "pp")
        ):
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
            
        lines.append(
            f"| `{feat}` | `{target.replace('_spread_bps','').replace('_spread_pp','')}` | "
            f"[{val_a:+.1f}, {val_b:+.1f}, {val_c:+.1f}] | `{pattern}` | `{verdict}` |"
        )
        
    # Write out the markdown report
    (OUT_DIR / "v4a_4_sentiment_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved Markdown report to {OUT_DIR / 'v4a_4_sentiment_report.md'}")


if __name__ == "__main__":
    run_audit()
