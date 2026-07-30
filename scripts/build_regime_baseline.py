#!/usr/bin/env python3
"""Build reproducible before/after regime distribution evidence.

The ``before`` classifier is frozen to the v1 production semantics found at
the start of remediation. The ``after`` classifier imports the current v2
implementation and canonical config.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.core.io import smart_read_csv
from btc_scraper.regime.config import compute_regime_config_sha256, load_regime_config
from btc_scraper.regime.market_regime import (
    _classify_regime,
    calculate_adx,
    calculate_atr,
    ema,
    sma,
    stabilize_regime_sequence,
)


LEGACY_V1_CONFIG = {
    "adx_threshold": 45.94,
    "strong_adx_threshold": 35.0,
    "atr_pct_threshold": 0.844,
}


def _legacy_v1(close: float, sma200: float, ema21: float, sma50: float, adx: float, atr: float) -> tuple[str, float]:
    threshold = LEGACY_V1_CONFIG["adx_threshold"]
    if atr >= 2.0 * threshold and close < sma200 and adx >= threshold:
        return "PANIC_SELL", 0.85
    if atr >= 2.0 * threshold and close > sma200 and adx < threshold:
        return "PUMP_RISK", 0.65
    if atr <= 0.75 * threshold and adx < 20:
        return "COMPRESSION", 0.45
    if atr >= 1.5 * threshold and adx >= threshold and close > sma200 and ema21 > sma50:
        return "BREAKOUT", 0.75
    if atr >= 1.25 * threshold and adx < threshold:
        return "MEAN_REVERSION", 0.55
    if adx >= 35:
        if close > sma200 and ema21 > sma50:
            return "STRONG_TREND_BULL", 0.9
        if close < sma200 and ema21 < sma50:
            return "STRONG_TREND_BEAR", 0.9
        return "STRONG_TREND", 0.9
    if adx > threshold:
        if close > sma200 and ema21 > sma50:
            return "WEAK_TREND_BULL", 0.7
        if close < sma200 and ema21 < sma50:
            return "WEAK_TREND_BEAR", 0.7
        return "WEAK_TREND", 0.7
    if atr > threshold:
        return "HIGH_VOLATILITY", 0.6
    return "RANGING", 0.4


def _run_lengths(labels: list[str]) -> list[int]:
    if not labels:
        return []
    lengths: list[int] = []
    current = labels[0]
    length = 1
    for label in labels[1:]:
        if label == current:
            length += 1
        else:
            lengths.append(length)
            current, length = label, 1
    lengths.append(length)
    return lengths


def _summarize(labels: list[str], confidence: list[float], atr: pd.Series, adx: pd.Series, hours: float) -> dict:
    counts = Counter(labels)
    total = len(labels)
    transitions = sum(left != right for left, right in zip(labels, labels[1:]))
    runs = _run_lengths(labels)
    return {
        "rows": total,
        "counts": dict(sorted(counts.items())),
        "percentages": {key: round(value / total * 100.0, 4) for key, value in sorted(counts.items())} if total else {},
        "null_rate": 0.0,
        "unknown_rate": round(counts.get("UNKNOWN", 0) / total, 6) if total else 0.0,
        "transition_frequency": round(transitions / max(total - 1, 1), 6),
        "average_regime_duration_bars": round(float(np.mean(runs)), 4) if runs else 0.0,
        "flips_per_hour": round(transitions / max(hours, 1e-9), 6),
        "atr_percent_quantiles": {
            str(q): round(float(atr.quantile(q)), 6) for q in (0.25, 0.5, 0.75, 0.9, 0.99)
        },
        "adx_quantiles": {str(q): round(float(adx.quantile(q)), 6) for q in (0.25, 0.5, 0.75, 0.9, 0.99)},
        "confidence_quantiles": {
            str(q): round(float(pd.Series(confidence).quantile(q)), 6) for q in (0.25, 0.5, 0.75, 0.9, 0.99)
        },
    }


def analyze_file(path: Path, mode: str, config: dict) -> tuple[pd.DataFrame, dict]:
    frame = smart_read_csv(path)
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    sma200 = sma(close, 200)
    sma50 = sma(close, 50)
    ema21 = ema(close, 21)
    atr_percent = calculate_atr(frame, 14) / close * 100.0
    adx = calculate_adx(frame, 14)

    start = max(200, int(config.get("minimum_bars", 200)))
    labels: list[str] = []
    confidence: list[float] = []
    for index in range(start, len(frame)):
        values = (
            float(close.iloc[index]),
            float(sma200.iloc[index]),
            float(ema21.iloc[index]),
            float(sma50.iloc[index]),
            float(adx.iloc[index]),
            float(atr_percent.iloc[index]),
        )
        if mode == "before":
            label, conf = _legacy_v1(*values)
        else:
            classified = _classify_regime(*values, config)
            label, conf = str(classified["regime"]), float(classified["confidence"])
        labels.append(label)
        confidence.append(conf)
    if mode == "after":
        labels = stabilize_regime_sequence(labels, int(config.get("minimum_duration_bars", 3)))

    analyzed = pd.DataFrame(
        {
            "time": frame["time"].iloc[start:].reset_index(drop=True),
            "regime": labels,
            "confidence": confidence,
            "atr_percent": atr_percent.iloc[start:].reset_index(drop=True),
            "adx": adx.iloc[start:].reset_index(drop=True),
        }
    )
    timeframe = path.stem.rsplit("_", 1)[-1]
    minutes = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}.get(timeframe, 15)
    summary = _summarize(
        labels,
        confidence,
        analyzed["atr_percent"],
        analyzed["adx"],
        hours=len(analyzed) * minutes / 60.0,
    )
    summary["timeframe"] = timeframe
    return analyzed, summary


def _production_snapshot() -> dict:
    candidates = [
        REPO_ROOT / "runtime/production/local-production/data/latest_signals.json",
        REPO_ROOT / "data/latest_signals.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload.get("analysis", {}).values()
            counts = Counter(str(row.get("regime") or "UNKNOWN") for row in rows if isinstance(row, dict))
            return {"path": str(path.relative_to(REPO_ROOT)), "counts": dict(counts), "rows": sum(counts.values())}
        except Exception:
            continue
    return {"status": "not_available"}


def _source_manifest(paths: list[Path]) -> dict:
    files = []
    combined = hashlib.sha256()
    for path in paths:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        relative = str(path.relative_to(REPO_ROOT))
        sha256 = digest.hexdigest()
        size = path.stat().st_size
        files.append({"path": relative, "size_bytes": size, "sha256": sha256})
        combined.update(f"{relative}:{size}:{sha256}\n".encode())
    return {
        "file_count": len(files),
        "combined_sha256": combined.hexdigest(),
        "files": files,
    }


def build_report(mode: str, data_root: Path) -> dict:
    config = load_regime_config()
    paths = sorted(data_root.glob("*/*_*.csv"))
    by_coin: dict[str, dict] = {}
    combined: list[pd.DataFrame] = []
    for path in paths:
        coin = path.parent.name
        analyzed, summary = analyze_file(path, mode, config)
        by_coin[f"{coin}:{summary['timeframe']}"] = summary
        analyzed["coin"] = coin
        combined.append(analyzed)

    all_rows = pd.concat(combined, ignore_index=True) if combined else pd.DataFrame()
    global_summary = _summarize(
        all_rows["regime"].tolist() if not all_rows.empty else [],
        all_rows["confidence"].tolist() if not all_rows.empty else [],
        all_rows["atr_percent"] if not all_rows.empty else pd.Series(dtype=float),
        all_rows["adx"] if not all_rows.empty else pd.Series(dtype=float),
        hours=len(all_rows) * 0.25,
    )
    rolling: dict[str, dict] = {}
    if not all_rows.empty:
        latest = all_rows["time"].max()
        for days in (7, 30, 90):
            window = all_rows[all_rows["time"] >= latest - pd.Timedelta(days=days)]
            rolling[f"{days}d"] = _summarize(
                window["regime"].tolist(),
                window["confidence"].tolist(),
                window["atr_percent"],
                window["adx"],
                hours=len(window) * 0.25,
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "classifier": "legacy_v1_frozen" if mode == "before" else "canonical_v2",
        "config": LEGACY_V1_CONFIG if mode == "before" else config,
        "config_sha256": None if mode == "before" else compute_regime_config_sha256(config),
        "source_root": str(data_root.relative_to(REPO_ROOT)),
        "source_manifest": _source_manifest(paths),
        "global": global_summary,
        "by_coin_timeframe": by_coin,
        "rolling_windows": rolling,
        "production_snapshot": _production_snapshot(),
    }


def write_markdown(report: dict, path: Path) -> None:
    lines = [
        f"# Regime baseline — {report['mode']}",
        "",
        f"- Classifier: `{report['classifier']}`",
        f"- Generated at: `{report['generated_at']}`",
        f"- Rows: `{report['global']['rows']}`",
        f"- Unknown rate: `{report['global']['unknown_rate']}`",
        f"- Transition frequency: `{report['global']['transition_frequency']}`",
        f"- Average duration: `{report['global']['average_regime_duration_bars']}` bars",
        "",
        "## Distribution",
        "",
        "| Regime | Count | Percent |",
        "|---|---:|---:|",
    ]
    counts = report["global"]["counts"]
    percentages = report["global"]["percentages"]
    lines.extend(f"| {key} | {value} | {percentages[key]:.4f}% |" for key, value in counts.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["before", "after"], required=True)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=REPO_ROOT / "data/fresh_training_data_2023_2026",
    )
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "artifacts/regime")
    parser.add_argument(
        "--refresh-source-manifest",
        action="store_true",
        help="Update source hashes on an existing report without re-running classification.",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"baseline_{args.mode}_remediation"
    json_path = args.output_dir / f"{stem}.json"
    md_path = args.output_dir / f"{stem}.md"
    if args.refresh_source_manifest:
        if not json_path.exists():
            raise FileNotFoundError(f"Existing report not found: {json_path}")
        report = json.loads(json_path.read_text(encoding="utf-8"))
        report["source_manifest"] = _source_manifest(sorted(args.data_root.glob("*/*_*.csv")))
    else:
        report = build_report(args.mode, args.data_root)
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(report, md_path)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "rows": report["global"]["rows"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
