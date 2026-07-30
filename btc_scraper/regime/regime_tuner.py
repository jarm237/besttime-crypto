"""Governed walk-forward tuner for regime position multipliers.

This module deliberately defaults sparse/unknown regimes to 1.0. It emits
research evidence only; runtime containment decides whether a proposal may be
applied.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from btc_scraper.regime.config import compute_regime_config_sha256, load_regime_config


@dataclass(frozen=True)
class RegimeTunerConfig:
    min_samples_per_regime: int = 30
    train_fraction: float = 0.60
    validation_fraction: float = 0.20
    embargo_rows: int = 1
    candidates: tuple[float, ...] = (0.8, 0.9, 1.0, 1.05, 1.1)
    transaction_cost_pct: float = 0.02
    drawdown_penalty: float = 0.5
    turnover_penalty: float = 0.1
    instability_penalty: float = 0.5
    shrinkage_penalty: float = 0.1
    bootstrap_samples: int = 500
    random_seed: int = 42

    def validate(self) -> None:
        if self.min_samples_per_regime < 1:
            raise ValueError("min_samples_per_regime must be positive")
        if not 0 < self.train_fraction < 1:
            raise ValueError("train_fraction must be in (0, 1)")
        if not 0 < self.validation_fraction < 1:
            raise ValueError("validation_fraction must be in (0, 1)")
        if self.train_fraction + self.validation_fraction >= 1:
            raise ValueError("train + validation fractions must leave a holdout")
        if not self.candidates or 1.0 not in self.candidates:
            raise ValueError("candidates must include the neutral multiplier 1.0")


def _normalize_records(records: Iterable[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        try:
            pnl = float(record.get("pnl_pct"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(pnl):
            continue
        snapshot = record.get("entry_regime_snapshot") or record.get("regime_snapshot")
        regime = snapshot.get("regime_id") if isinstance(snapshot, dict) else record.get("regime")
        timestamp = pd.to_datetime(
            record.get("entry_time") or record.get("timestamp"),
            utc=True,
            errors="coerce",
        )
        rows.append(
            {
                "_order": index,
                "entry_time": timestamp,
                "regime": str(regime or "UNKNOWN").upper(),
                "pnl_pct": pnl,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    # Records without a timestamp remain deterministic but are ineligible for
    # promotion-grade evidence.
    frame["_sort_time"] = frame["entry_time"].fillna(pd.Timestamp.max.tz_localize("UTC"))
    return frame.sort_values(["_sort_time", "_order"], kind="mergesort").reset_index(drop=True)


def walk_forward_split(frame: pd.DataFrame, config: RegimeTunerConfig) -> dict[str, pd.DataFrame]:
    config.validate()
    count = len(frame)
    train_end = int(count * config.train_fraction)
    validation_start = min(count, train_end + config.embargo_rows)
    validation_end = int(count * (config.train_fraction + config.validation_fraction))
    holdout_start = min(count, validation_end + config.embargo_rows)
    return {
        "train": frame.iloc[:train_end].copy(),
        "validation": frame.iloc[validation_start:validation_end].copy(),
        "holdout": frame.iloc[holdout_start:].copy(),
    }


def _max_drawdown(values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    equity = np.cumsum(values)
    peaks = np.maximum.accumulate(np.concatenate(([0.0], equity)))[1:]
    return float(np.max(peaks - equity))


def _utility(pnl: np.ndarray, multiplier: float, config: RegimeTunerConfig) -> float:
    if pnl.size == 0:
        return float("-inf")
    scaled = pnl * multiplier - config.transaction_cost_pct * multiplier
    mean_return = float(np.mean(scaled))
    drawdown = _max_drawdown(scaled) / max(len(scaled), 1)
    turnover = abs(multiplier - 1.0) * config.transaction_cost_pct
    shrinkage = (multiplier - 1.0) ** 2
    return (
        mean_return
        - config.drawdown_penalty * drawdown
        - config.turnover_penalty * turnover
        - config.shrinkage_penalty * shrinkage
    )


def _bootstrap_mean_ci(values: np.ndarray, config: RegimeTunerConfig) -> list[float] | None:
    if values.size < 2:
        return None
    rng = np.random.default_rng(config.random_seed)
    means = [
        float(np.mean(rng.choice(values, size=len(values), replace=True)))
        for _ in range(config.bootstrap_samples)
    ]
    return [round(float(np.quantile(means, 0.025)), 6), round(float(np.quantile(means, 0.975)), 6)]


def tune_regime_multipliers(
    records: Iterable[dict[str, Any]],
    config: RegimeTunerConfig | None = None,
) -> dict[str, Any]:
    config = config or RegimeTunerConfig()
    frame = _normalize_records(records)
    splits = walk_forward_split(frame, config) if not frame.empty else {"train": frame, "validation": frame, "holdout": frame}
    regimes = sorted(set(frame["regime"])) if not frame.empty else []
    proposals: dict[str, dict[str, Any]] = {}

    for regime in regimes:
        if regime == "UNKNOWN":
            proposals[regime] = {
                "selected_multiplier": 1.0,
                "status": "INSUFFICIENT_EVIDENCE",
                "reason": "UNKNOWN_REGIME_NOT_TUNABLE",
            }
            continue
        train = splits["train"].loc[splits["train"]["regime"] == regime, "pnl_pct"].to_numpy(dtype=float)
        validation = splits["validation"].loc[
            splits["validation"]["regime"] == regime, "pnl_pct"
        ].to_numpy(dtype=float)
        holdout = splits["holdout"].loc[splits["holdout"]["regime"] == regime, "pnl_pct"].to_numpy(dtype=float)
        counts = {"train": len(train), "validation": len(validation), "holdout": len(holdout)}
        if len(train) < config.min_samples_per_regime or len(validation) < max(5, config.min_samples_per_regime // 3):
            proposals[regime] = {
                "selected_multiplier": 1.0,
                "status": "INSUFFICIENT_EVIDENCE",
                "sample_counts": counts,
            }
            continue

        candidates: list[dict[str, float]] = []
        for multiplier in config.candidates:
            train_score = _utility(train, multiplier, config)
            validation_score = _utility(validation, multiplier, config)
            stable_score = (
                min(train_score, validation_score)
                - config.instability_penalty * abs(train_score - validation_score)
            )
            candidates.append(
                {
                    "multiplier": multiplier,
                    "train_score": round(train_score, 8),
                    "validation_score": round(validation_score, 8),
                    "stable_score": round(stable_score, 8),
                }
            )
        selected = max(candidates, key=lambda item: (item["stable_score"], -abs(item["multiplier"] - 1.0)))
        multiplier = float(selected["multiplier"])
        proposals[regime] = {
            "selected_multiplier": multiplier,
            "status": "RESEARCH_ONLY",
            "sample_counts": counts,
            "candidates": candidates,
            "holdout_utility": round(_utility(holdout, multiplier, config), 8) if len(holdout) else None,
            "holdout_neutral_utility": round(_utility(holdout, 1.0, config), 8) if len(holdout) else None,
            "holdout_mean_pnl_ci95": _bootstrap_mean_ci(holdout, config),
        }

    regime_config = load_regime_config()
    data_windows = {}
    for name, split in splits.items():
        timestamps = split["entry_time"].dropna() if not split.empty and "entry_time" in split else pd.Series(dtype="datetime64[ns, UTC]")
        data_windows[name] = {
            "start": timestamps.min().isoformat() if not timestamps.empty else None,
            "end": timestamps.max().isoformat() if not timestamps.empty else None,
            "rows": len(split),
        }
    return {
        "artifact_schema_version": "regime-tuning-v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "approval_status": "RESEARCH_ONLY",
        "promotion_gate_passed": False,
        "taxonomy_version": regime_config["taxonomy_version"],
        "detector_version": regime_config["detector_version"],
        "config_sha256": compute_regime_config_sha256(regime_config),
        "tuner_config": asdict(config),
        "cost_model": {
            "transaction_cost_pct": config.transaction_cost_pct,
            "turnover_penalty": config.turnover_penalty,
        },
        "slippage_model": {
            "status": "NOT_SEPARATELY_MODELED",
            "promotion_eligible": False,
        },
        "default_fallback_multiplier": 1.0,
        "split_counts": {name: len(split) for name, split in splits.items()},
        "data_windows": data_windows,
        "timestamp_coverage_complete": bool(not frame.empty and frame["entry_time"].notna().all()),
        "proposals": proposals,
    }


def write_immutable_tuning_artifact(report: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = str(report["created_at"]).replace(":", "").replace("-", "").replace("+00:00", "Z").replace(".", "")
    path = output_dir / f"regime_tuning_{stamp}.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path
