"""CLI and compatibility helpers for governed regime multiplier tuning."""
from __future__ import annotations

import json
from itertools import product

from btc_scraper.core.paths import build_logs_path, build_repo_path
from btc_scraper.regime.regime_tuner import (
    RegimeTunerConfig,
    tune_regime_multipliers,
    write_immutable_tuning_artifact,
)


LOG = build_logs_path("adaptive_signals.json")


def _load_log():
    if not LOG.exists():
        return []
    try:
        return json.loads(LOG.read_text(encoding="utf-8"))
    except Exception:
        return []


def extract_records(records):
    """Normalize legacy records while preserving timestamps and entry snapshots."""
    out = []
    for record in records:
        try:
            pnl = float(record.get("pnl_pct"))
        except (TypeError, ValueError):
            continue
        snapshot = record.get("entry_regime_snapshot") or record.get("regime_snapshot")
        regime = snapshot.get("regime_id") if isinstance(snapshot, dict) else record.get("regime")
        signal_score = record.get("signal_score") or {}
        if not regime and isinstance(signal_score, dict):
            regime = signal_score.get("regime")
        strategy = record.get("strategy")
        if not strategy and isinstance(signal_score, dict):
            strategy = signal_score.get("strategy")
        out.append(
            {
                "pnl": pnl,
                "pnl_pct": pnl,
                "regime": regime or "UNKNOWN",
                "strategy": strategy,
                "entry_time": record.get("entry_time") or record.get("timestamp"),
                "regime_snapshot": snapshot,
            }
        )
    return out


def grid_search(records, regimes, grid_vals, top_n=5, objective="expected_pnl", penalty=1.0):
    """Legacy research helper retained for reproducibility, never for promotion.

    The production-facing CLI below uses the governed walk-forward tuner.
    """
    best = []
    regimes = list(regimes)
    total = 0
    for combo in product(grid_vals, repeat=len(regimes)):
        multiplier_map = {regimes[index]: combo[index] for index in range(len(regimes))}
        total_score = 0.0
        for record in records:
            pnl = float(record["pnl"])
            multiplier = multiplier_map.get(record.get("regime") or "UNKNOWN", 1.0)
            if objective == "penalize_negative" and pnl < 0:
                pnl *= penalty
            total_score += pnl * multiplier
        best.append((total_score, multiplier_map))
        total += 1
    best.sort(key=lambda item: item[0], reverse=True)
    return best[:top_n], total


def main() -> int:
    records = extract_records(_load_log())
    report = tune_regime_multipliers(records, RegimeTunerConfig())
    output_dir = build_repo_path("artifacts", "regime", "tuning")
    path = write_immutable_tuning_artifact(report, output_dir)
    print(json.dumps({
        "artifact": str(path),
        "approval_status": report["approval_status"],
        "promotion_gate_passed": report["promotion_gate_passed"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
