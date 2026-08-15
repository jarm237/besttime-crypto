#!/usr/bin/env python3
"""HMR-V4A-3M-r1: Deribit DVOL magnitude information audit."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import numpy as np
import pandas as pd

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


REPO_ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD_PATH = REPO_ROOT / "research/historical_market_replay_v4/v4a_outcome_scaffold.parquet"
OUT_DIR = REPO_ROOT / "research/historical_market_replay_v4"
DVOL_CACHE_PATH = OUT_DIR / "v4a_3_dvol_history.parquet"

REVISION = "HMR-V4A-3M-r1"
ELIGIBLE_ASSETS = ("BTC", "ETH")
DERIVED_CONTROL_ASSETS = ("BNB",)
FEATURES = ("dvol_level", "dvol_change_4h", "dvol_change_24h", "dvol_percentile_30d")
PRIMARY_MAGNITUDE_METRICS = (
    "abs_return_72",
    "future_range_72",
    "max_abs_excursion_72",
    "large_move_30",
    "large_move_50",
)
PERIODS = {
    "A": ("2023-01-01T00:00:00+00:00", "2024-06-30T23:59:59+00:00"),
    "B": ("2024-07-01T00:00:00+00:00", "2024-09-30T23:59:59+00:00"),
    "C": ("2024-10-01T00:00:00+00:00", "2024-12-31T23:59:59+00:00"),
}


def _fetch_deribit_dvol(currency: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if requests is None:
        raise RuntimeError("requests is not installed")
    url = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
    rows: list[list[Any]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + pd.Timedelta(days=30), end)
        params = urlencode(
            {
                "currency": currency,
                "start_timestamp": int(cursor.timestamp() * 1000),
                "end_timestamp": int(chunk_end.timestamp() * 1000),
                "resolution": 3600,
            }
        )
        response = requests.get(f"{url}?{params}", timeout=30)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("result", {}).get("data", [])
        if isinstance(data, list):
            rows.extend(data)
        cursor = chunk_end + pd.Timedelta(hours=1)
        time.sleep(0.05)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["source_timestamp_ms", "open", "high", "low", "close"])
    df["symbol"] = currency
    df["dvol_source_timestamp"] = pd.to_datetime(df["source_timestamp_ms"], unit="ms", utc=True)
    df["dvol_available_at"] = df["dvol_source_timestamp"] + pd.Timedelta(hours=1)
    df["dvol_value"] = pd.to_numeric(df["close"], errors="coerce") / 100.0
    return df[["symbol", "dvol_source_timestamp", "dvol_available_at", "dvol_value"]].dropna()


def load_or_fetch_dvol(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if DVOL_CACHE_PATH.exists():
        df = pd.read_parquet(DVOL_CACHE_PATH)
        df["dvol_source_timestamp"] = pd.to_datetime(df["dvol_source_timestamp"], utc=True)
        df["dvol_available_at"] = pd.to_datetime(df["dvol_available_at"], utc=True)
        return df
    frames = [_fetch_deribit_dvol(symbol, start, end) for symbol in ELIGIBLE_ASSETS]
    df = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True)
    if not df.empty:
        df = df.drop_duplicates(["symbol", "dvol_available_at"]).sort_values(["symbol", "dvol_available_at"])
        df.to_parquet(DVOL_CACHE_PATH, index=False)
    return df


def rolling_percentile(series: pd.Series, window: int = 24 * 30, min_periods: int = 100) -> pd.Series:
    return series.rolling(window, min_periods=min_periods).rank(pct=True)


def add_dvol_features(dvol: pd.DataFrame) -> pd.DataFrame:
    out = dvol.sort_values(["symbol", "dvol_available_at"]).copy()
    out["dvol_level"] = out["dvol_value"]
    out["dvol_change_4h"] = out.groupby("symbol")["dvol_value"].diff(4)
    out["dvol_change_24h"] = out.groupby("symbol")["dvol_value"].diff(24)
    out["dvol_percentile_30d"] = out.groupby("symbol")["dvol_value"].transform(rolling_percentile)
    return out.fillna(0.0)


def add_future_targets(df: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for _, group in df.sort_values("timestamp").groupby("symbol", sort=False):
        g = group.copy()
        close = g["close"].astype(float)
        for horizon in (8, 32, 72):
            g[f"abs_return_{horizon}"] = g[f"return_{horizon}"].abs()
        future = pd.concat([close.shift(-i) for i in range(1, 73)], axis=1)
        future_max = future.max(axis=1)
        future_min = future.min(axis=1)
        g["future_range_32"] = (
            pd.concat([close.shift(-i) for i in range(1, 33)], axis=1).max(axis=1)
            - pd.concat([close.shift(-i) for i in range(1, 33)], axis=1).min(axis=1)
        ) / close
        g["future_range_72"] = (future_max - future_min) / close
        g["mfe_72"] = (future_max - close) / close
        g["mae_72"] = (future_min - close) / close
        g["max_abs_excursion_72"] = np.maximum(g["mfe_72"].abs(), g["mae_72"].abs())
        g["large_move_30"] = (g["max_abs_excursion_72"] * 10000.0 >= 30.0).astype(float)
        g["large_move_50"] = (g["max_abs_excursion_72"] * 10000.0 >= 50.0).astype(float)
        g["signed_return_72"] = g["return_72"]
        frames.append(g)
    return pd.concat(frames, ignore_index=True).dropna(subset=["future_range_72", "max_abs_excursion_72"])


def merge_dvol(scaffold: pd.DataFrame, dvol: pd.DataFrame) -> pd.DataFrame:
    merged = []
    for symbol in ELIGIBLE_ASSETS:
        left = scaffold[scaffold["symbol"] == symbol].sort_values("timestamp").copy()
        right = dvol[dvol["symbol"] == symbol].sort_values("dvol_available_at").copy()
        joined = pd.merge_asof(
            left,
            right,
            left_on="timestamp",
            right_on="dvol_available_at",
            by="symbol",
            direction="backward",
            allow_exact_matches=True,
        )
        merged.append(joined)
    out = pd.concat(merged, ignore_index=True)
    out["decision_time"] = out["timestamp"]
    out["dvol_age_seconds"] = (out["decision_time"] - out["dvol_available_at"]).dt.total_seconds()
    out["dvol_reconstruction_class"] = "H2_ASOF_RECONSTRUCTABLE"
    out["dvol_stale"] = out["dvol_age_seconds"] > 3 * 3600
    return out


def assign_period(ts: pd.Timestamp) -> str | None:
    for name, (start, end) in PERIODS.items():
        if pd.Timestamp(start) <= ts <= pd.Timestamp(end):
            return name
    return None


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


def summarize_quantiles(df: pd.DataFrame, feature: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    q_rows: list[dict[str, Any]] = []
    feature_rows: list[dict[str, Any]] = []
    for period, period_df in df.groupby("period"):
        means_for_monotonicity = []
        for q in range(1, 6):
            g = period_df[period_df["q"] == q]
            row: dict[str, Any] = {"feature": feature, "period": period, "quantile": q, "count": int(len(g))}
            for metric in (
                "abs_return_8",
                "abs_return_32",
                "abs_return_72",
                "future_range_32",
                "future_range_72",
                "max_abs_excursion_72",
                "large_move_30",
                "large_move_50",
            ):
                row[f"mean_{metric}"] = finite_or_none(g[metric].mean()) if len(g) else None
            row["median_max_abs_excursion_72"] = finite_or_none(g["max_abs_excursion_72"].median()) if len(g) else None
            row["winsorized_mean_max_abs_excursion_72"] = (
                finite_or_none(g["max_abs_excursion_72"].clip(upper=g["max_abs_excursion_72"].quantile(0.95)).mean())
                if len(g)
                else None
            )
            means_for_monotonicity.append(row["mean_abs_return_72"])
            q_rows.append(row)
        q1 = period_df[period_df["q"] == 1]
        q5 = period_df[period_df["q"] == 5]
        feature_rows.append(
            {
                "feature": feature,
                "period": period,
                "q1_count": int(len(q1)),
                "q5_count": int(len(q5)),
                "abs_return_72_spread_bps": finite_or_none((q5["abs_return_72"].mean() - q1["abs_return_72"].mean()) * 10000.0),
                "future_range_72_spread_bps": finite_or_none((q5["future_range_72"].mean() - q1["future_range_72"].mean()) * 10000.0),
                "max_abs_excursion_72_spread_bps": finite_or_none((q5["max_abs_excursion_72"].mean() - q1["max_abs_excursion_72"].mean()) * 10000.0),
                "large_move_30_spread_pp": finite_or_none((q5["large_move_30"].mean() - q1["large_move_30"].mean()) * 100.0),
                "large_move_50_spread_pp": finite_or_none((q5["large_move_50"].mean() - q1["large_move_50"].mean()) * 100.0),
                "signed_return_72_spread_bps": finite_or_none((q5["signed_return_72"].mean() - q1["signed_return_72"].mean()) * 10000.0),
                "long_30_20_spread_pp": finite_or_none((q5["long_30_20"].mean() - q1["long_30_20"].mean()) * 100.0),
                "short_30_20_spread_pp": finite_or_none((q5["short_30_20"].mean() - q1["short_30_20"].mean()) * 100.0),
                "magnitude_monotonicity": finite_or_none(spearman_rank([1, 2, 3, 4, 5], [v or 0.0 for v in means_for_monotonicity])),
            }
        )
    return q_rows, feature_rows


def conditional_incremental(df: pd.DataFrame, feature: str) -> dict[str, Any]:
    work = df.copy()
    work["atr_bucket"] = pd.qcut(work["atr_percentile"].rank(method="first"), 3, labels=False, duplicates="drop")
    work["rv_bucket"] = pd.qcut(work["realized_volatility"].rank(method="first"), 3, labels=False, duplicates="drop")
    raw = (
        work[work["q"] == 5]["max_abs_excursion_72"].mean()
        - work[work["q"] == 1]["max_abs_excursion_72"].mean()
    ) * 10000.0
    weighted = 0.0
    total = 0
    rows = []
    for (atr_bucket, rv_bucket), g in work.groupby(["atr_bucket", "rv_bucket"], dropna=True):
        low = g[g["q"] == 1]
        high = g[g["q"] == 5]
        if low.empty or high.empty:
            continue
        spread = (high["max_abs_excursion_72"].mean() - low["max_abs_excursion_72"].mean()) * 10000.0
        weight = len(g)
        weighted += spread * weight
        total += weight
        rows.append(
            {
                "feature": feature,
                "atr_bucket": int(atr_bucket),
                "realized_vol_bucket": int(rv_bucket),
                "count": int(weight),
                "max_abs_excursion_72_spread_bps": float(spread),
            }
        )
    conditional = weighted / total if total else 0.0
    retention = abs(conditional / raw) if abs(raw) >= 1e-12 else None
    return {
        "summary": {
            "feature": feature,
            "raw_spread_bps": float(raw),
            "conditional_spread_bps": float(conditional),
            "retention": float(retention) if retention is not None else None,
            "same_sign": bool(np.sign(raw) == np.sign(conditional)) if raw and conditional else False,
        },
        "rows": rows,
    }


def add_conditioning_state(df: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for _, group in df.sort_values("timestamp").groupby("symbol", sort=False):
        g = group.copy()
        returns = g["close"].pct_change()
        g["realized_volatility"] = returns.rolling(72).std()
        g["recent_abs_return"] = g["close"].pct_change(72).abs()
        g["recent_high_low_range"] = (g["close"].rolling(72).max() - g["close"].rolling(72).min()) / g["close"]
        g["bollinger_width"] = 4 * g["close"].rolling(72).std() / g["close"].rolling(72).mean()
        g["range_compression"] = g["recent_high_low_range"].rolling(288).rank(pct=True)
        g["atr_percentile"] = g["recent_high_low_range"].rolling(288).rank(pct=True)
        frames.append(g)
    return pd.concat(frames, ignore_index=True).fillna(0.0)


def monthly_stability(df: pd.DataFrame, feature: str) -> list[dict[str, Any]]:
    rows = []
    for month, g in df.groupby(df["timestamp"].dt.strftime("%Y-%m")):
        q1 = g[g["q"] == 1]
        q5 = g[g["q"] == 5]
        if q1.empty or q5.empty:
            continue
        rows.append(
            {
                "feature": feature,
                "month": month,
                "count": int(len(g)),
                "max_abs_excursion_72_spread_bps": float((q5["max_abs_excursion_72"].mean() - q1["max_abs_excursion_72"].mean()) * 10000.0),
            }
        )
    return rows


def asset_stability(df: pd.DataFrame, feature: str) -> list[dict[str, Any]]:
    rows = []
    for (period, symbol), g in df.groupby(["period", "symbol"]):
        q1 = g[g["q"] == 1]
        q5 = g[g["q"] == 5]
        if q1.empty or q5.empty:
            continue
        rows.append(
            {
                "feature": feature,
                "period": period,
                "symbol": symbol,
                "count": int(len(g)),
                "max_abs_excursion_72_spread_bps": float((q5["max_abs_excursion_72"].mean() - q1["max_abs_excursion_72"].mean()) * 10000.0),
            }
        )
    return rows


def tail_sensitivity(df: pd.DataFrame, feature: str) -> list[dict[str, Any]]:
    rows = []
    for period, g in df.groupby("period"):
        q1 = g[g["q"] == 1]["max_abs_excursion_72"]
        q5 = g[g["q"] == 5]["max_abs_excursion_72"]
        if q1.empty or q5.empty:
            continue
        base = q5.mean() - q1.mean()
        top1 = g["max_abs_excursion_72"].quantile(0.99)
        top5 = g["max_abs_excursion_72"].quantile(0.95)
        for label, threshold in (("top_1pct", top1), ("top_5pct", top5)):
            trimmed = g[g["max_abs_excursion_72"] < threshold]
            tq1 = trimmed[trimmed["q"] == 1]["max_abs_excursion_72"]
            tq5 = trimmed[trimmed["q"] == 5]["max_abs_excursion_72"]
            trimmed_spread = tq5.mean() - tq1.mean() if not tq1.empty and not tq5.empty else 0.0
            contribution = 1.0 - (trimmed_spread / base) if abs(base) >= 1e-12 else 0.0
            rows.append(
                {
                    "feature": feature,
                    "period": period,
                    "tail_cut": label,
                    "threshold_bps": float(threshold * 10000.0),
                    "spread_without_tail_bps": float(trimmed_spread * 10000.0),
                    "tail_contribution": float(contribution),
                    "tail_event_dominated": bool(contribution > 0.70),
                }
            )
    return rows


def bootstrap_ci(df: pd.DataFrame, feature: str, period: str, iterations: int = 200) -> dict[str, Any]:
    g = df[(df["feature"] == feature) & (df["period"] == period)]
    if g.empty:
        return {"feature": feature, "period": period, "ci_low_bps": None, "ci_high_bps": None}
    values = []
    rng = np.random.default_rng(42)
    for _ in range(iterations):
        sample = g.sample(frac=1.0, replace=True, random_state=int(rng.integers(0, 1_000_000)))
        q1 = sample[sample["q"] == 1]["max_abs_excursion_72"]
        q5 = sample[sample["q"] == 5]["max_abs_excursion_72"]
        if not q1.empty and not q5.empty:
            values.append((q5.mean() - q1.mean()) * 10000.0)
    if not values:
        return {"feature": feature, "period": period, "ci_low_bps": None, "ci_high_bps": None}
    return {
        "feature": feature,
        "period": period,
        "ci_low_bps": float(np.percentile(values, 2.5)),
        "ci_high_bps": float(np.percentile(values, 97.5)),
    }


def final_verdict(feature_summaries: list[dict[str, Any]], conditional: dict[str, Any], tail_rows: list[dict[str, Any]], ci_rows: list[dict[str, Any]]) -> str:
    by_period = {row["period"]: row for row in feature_summaries}
    b = by_period.get("B", {})
    c = by_period.get("C", {})
    if not b or not c:
        return "BLOCKED_PROVENANCE"
    primary = ("max_abs_excursion_72_spread_bps", "future_range_72_spread_bps", "abs_return_72_spread_bps")
    m3 = any(abs(b.get(metric) or 0.0) >= 10.0 and abs(c.get(metric) or 0.0) >= 10.0 for metric in primary)
    m4 = (
        abs(b.get("large_move_30_spread_pp") or 0.0) >= 5.0 and abs(c.get("large_move_30_spread_pp") or 0.0) >= 5.0
    ) or (
        abs(b.get("large_move_50_spread_pp") or 0.0) >= 5.0 and abs(c.get("large_move_50_spread_pp") or 0.0) >= 5.0
    )
    m5 = np.sign(b.get("max_abs_excursion_72_spread_bps") or 0.0) == np.sign(c.get("max_abs_excursion_72_spread_bps") or 0.0)
    m6 = np.sign(b.get("magnitude_monotonicity") or 0.0) == np.sign(c.get("magnitude_monotonicity") or 0.0) and abs(b.get("magnitude_monotonicity") or 0.0) >= 0.2 and abs(c.get("magnitude_monotonicity") or 0.0) >= 0.2
    inc = conditional["summary"]
    m7 = abs(inc["raw_spread_bps"]) >= 10.0 and abs(inc["conditional_spread_bps"]) >= 5.0 and inc["same_sign"] and (inc["retention"] or 0.0) >= 0.50
    m10 = all((row["ci_low_bps"] is not None and not (row["ci_low_bps"] <= 0.0 <= row["ci_high_bps"])) for row in ci_rows if row["period"] in {"B", "C"})
    tail_dominated = any(row["tail_event_dominated"] for row in tail_rows if row["period"] in {"B", "C"} and row["tail_cut"] == "top_1pct")
    if m3 and m4 and m5 and m6 and m7 and m10:
        return "PROMOTE_TAIL_RISK_REGIME_ONLY" if tail_dominated else "PROMOTE_VOLATILITY_TIMING"
    if m3 and not m7:
        return "REJECT_AS_REALIZED_VOL_PROXY"
    if not m5 or not m6:
        return "REJECT_NON_TRANSPORTABLE"
    return "REJECT_NO_ECONOMIC_INFORMATION"


def run_audit() -> dict[str, Any]:
    print(f"{REVISION}: running DVOL magnitude audit")
    scaffold = pd.read_parquet(SCAFFOLD_PATH)
    scaffold["timestamp"] = pd.to_datetime(scaffold["timestamp"], utc=True)
    scaffold = scaffold[scaffold["symbol"].isin(ELIGIBLE_ASSETS)].copy()
    scaffold = add_conditioning_state(add_future_targets(scaffold))
    start = scaffold["timestamp"].min() - pd.Timedelta(days=35)
    end = scaffold["timestamp"].max()
    dvol = add_dvol_features(load_or_fetch_dvol(start, end))
    merged = merge_dvol(scaffold, dvol)
    merged["period"] = merged["timestamp"].apply(assign_period)
    merged = merged[merged["period"].notna()].copy()
    usable = merged[merged["dvol_value"].notna() & ~merged["dvol_stale"]].copy()
    coverage = len(usable) / len(merged) if len(merged) else 0.0

    all_quantiles: list[dict[str, Any]] = []
    all_summaries: list[dict[str, Any]] = []
    all_conditional_rows: list[dict[str, Any]] = []
    conditional_summaries: list[dict[str, Any]] = []
    all_monthly: list[dict[str, Any]] = []
    all_asset: list[dict[str, Any]] = []
    all_tail: list[dict[str, Any]] = []
    all_ci: list[dict[str, Any]] = []
    feature_verdicts = []
    quantile_assignment_frames = []

    for feature in FEATURES:
        work = usable.copy()
        edges = quantile_edges(work[work["period"] == "A"][feature])
        work["q"] = assign_quantile(work[feature], edges)
        q_rows, summaries = summarize_quantiles(work, feature)
        conditional = conditional_incremental(work, feature)
        month_rows = monthly_stability(work, feature)
        asset_rows = asset_stability(work, feature)
        tail_rows = tail_sensitivity(work, feature)
        ci_rows = [bootstrap_ci(work.assign(feature=feature), feature, period) for period in ("B", "C")]

        all_quantiles.extend(q_rows)
        all_summaries.extend(summaries)
        all_conditional_rows.extend(conditional["rows"])
        conditional_summaries.append(conditional["summary"])
        all_monthly.extend(month_rows)
        all_asset.extend(asset_rows)
        all_tail.extend(tail_rows)
        all_ci.extend(ci_rows)
        verdict = final_verdict(summaries, conditional, tail_rows, ci_rows)
        feature_verdicts.append({"feature": feature, "period_a_edges": [float(x) for x in edges], "verdict": verdict})
        quantile_assignment_frames.append(work[["decision_time", "symbol", "period", feature, "q", "dvol_value", "dvol_source_timestamp", "dvol_available_at", "dvol_age_seconds", "dvol_reconstruction_class", "dvol_stale"]].rename(columns={feature: "feature_value"}).assign(feature=feature))

    pd.concat(quantile_assignment_frames, ignore_index=True).to_parquet(OUT_DIR / "v4a_3_dvol_quantiles.parquet", index=False)
    pd.DataFrame(all_conditional_rows + conditional_summaries).to_parquet(OUT_DIR / "v4a_3_dvol_conditional.parquet", index=False)
    pd.DataFrame(all_monthly).to_parquet(OUT_DIR / "v4a_3_dvol_monthly_stability.parquet", index=False)
    pd.DataFrame(all_asset).to_parquet(OUT_DIR / "v4a_3_dvol_asset_stability.parquet", index=False)
    pd.DataFrame(all_tail).to_parquet(OUT_DIR / "v4a_3_dvol_tail_sensitivity.parquet", index=False)

    output = {
        "program": REVISION,
        "source": "deribit_dvol",
        "provenance_gate": "PROCEED_WITH_RECONSTRUCTION_CAVEAT",
        "source_authenticity": "PASS_WITH_CAVEAT",
        "source_class": "EXTERNAL_DERIBIT_OBSERVATION",
        "historical_parity": "H2_ASOF_RECONSTRUCTABLE",
        "archived_pit_parity_gate": "NOT_PROVEN",
        "production_evidence_eligible": False,
        "research_inference_eligible": True,
        "temporal_ordering_gate": "PASS" if bool((usable["dvol_available_at"] <= usable["decision_time"]).all()) else "FAIL",
        "coverage_gate": "PASS" if coverage >= 0.90 else "FAIL",
        "usable_coverage": round(float(coverage), 6),
        "eligible_assets": list(ELIGIBLE_ASSETS),
        "derived_control_assets": list(DERIVED_CONTROL_ASSETS),
        "feature_set": list(FEATURES),
        "primary_targets": [
            "abs_return_8",
            "abs_return_32",
            "abs_return_72",
            "future_range_32",
            "future_range_72",
            "max_abs_excursion_72",
            "large_move_30",
            "large_move_50",
        ],
        "secondary_directional_diagnostics": ["long_30_20", "short_30_20", "signed_return_72"],
        "feature_summaries": all_summaries,
        "conditional_summaries": conditional_summaries,
        "uncertainty": all_ci,
        "feature_verdicts": feature_verdicts,
    }
    output = json_safe(output)
    (OUT_DIR / "v4a_3_dvol_audit.json").write_text(json.dumps(output, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    write_report(output)
    print(f"saved {OUT_DIR / 'v4a_3_dvol_audit.json'}")
    return output


def write_report(output: dict[str, Any]) -> None:
    def fmt(value: Any) -> str:
        return "n/a" if value is None else f"{float(value):.2f}"

    lines = [
        "# HMR-V4A-3M-r1 Deribit DVOL Magnitude Audit",
        "",
        "## Contract",
        "",
        f"Provenance: `{output['source_authenticity']}` / `{output['historical_parity']}`. Production evidence remains blocked; research inference is allowed.",
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
    lines.extend(["", "## Primary Period Spreads", "", "| Feature | Period | Max abs excursion Q5-Q1 bps | Future range 72 Q5-Q1 bps | Large30 Q5-Q1 pp | Monotonicity |", "| --- | --- | ---: | ---: | ---: | ---: |"])
    for row in output["feature_summaries"]:
        lines.append(
            f"| `{row['feature']}` | {row['period']} | {fmt(row['max_abs_excursion_72_spread_bps'])} | "
            f"{fmt(row['future_range_72_spread_bps'])} | {fmt(row['large_move_30_spread_pp'])} | {fmt(row['magnitude_monotonicity'])} |"
        )
    (OUT_DIR / "v4a_3_dvol_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run_audit()
