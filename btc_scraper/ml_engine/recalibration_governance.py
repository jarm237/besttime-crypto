"""Candidate-only governance for runtime recalibration."""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from .runtime_calibration import calibration_metrics


@dataclass(frozen=True)
class RecalibrationCandidate:
    candidate_id: str
    model_name: str
    model_version: str
    calibration_method: str
    status: str = "candidate"
    auto_promote: bool = False
    artifact_sha256: str | None = None

    def validate_candidate_only(self) -> None:
        if self.status != "candidate":
            raise ValueError("recalibration artifacts must start as candidate")
        if self.auto_promote:
            raise ValueError("auto_promote must be false for recalibration candidates")

    def to_dict(self) -> dict[str, Any]:
        self.validate_candidate_only()
        return asdict(self)


@dataclass(frozen=True)
class ShadowPromotionDecision:
    status: str
    action: str
    reasons: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)


def evaluate_shadow_candidate(
    paired_samples: Iterable[Mapping[str, Any]],
    *,
    bootstrap_iterations: int = 500,
    seed: int = 17,
) -> ShadowPromotionDecision:
    rows = [dict(row) for row in paired_samples]
    if len(rows) < 30:
        return ShadowPromotionDecision("insufficient_evidence", "remain_shadow", ("paired_sample_count_lt_30",), {"paired_sample_count": len(rows)})

    labels = [int(row["label"]) for row in rows]
    production = [_prob(row, "production_probability") for row in rows]
    candidate = [_prob(row, "candidate_probability") for row in rows]
    prod_metrics = calibration_metrics(_metric_rows(production, labels, rows))
    cand_metrics = calibration_metrics(_metric_rows(candidate, labels, rows))
    brier_delta = (cand_metrics["brier"] or 0.0) - (prod_metrics["brier"] or 0.0)
    brier_ci_upper = _bootstrap_brier_delta_upper(production, candidate, labels, bootstrap_iterations, seed)

    reasons: list[str] = []
    if brier_delta >= 0:
        reasons.append("brier_delta_not_improved")
    if brier_ci_upper > 0.002:
        reasons.append("brier_ci_upper_gt_0.002")
    if cand_metrics["ece"] is None or prod_metrics["ece"] is None or cand_metrics["ece"] > prod_metrics["ece"] + 0.01:
        reasons.append("ece_regression")
    if cand_metrics["roc_auc"] is not None and prod_metrics["roc_auc"] is not None and cand_metrics["roc_auc"] < prod_metrics["roc_auc"] - 0.01:
        reasons.append("roc_auc_regression")
    reasons.extend(_tail_regression_reasons(prod_metrics, cand_metrics))

    metrics = {
        "paired_sample_count": len(rows),
        "production": prod_metrics,
        "candidate": cand_metrics,
        "brier_delta": brier_delta,
        "bootstrap_brier_delta_ci_upper": brier_ci_upper,
    }
    if reasons:
        return ShadowPromotionDecision("insufficient_evidence", "remain_shadow", tuple(reasons), metrics)
    return ShadowPromotionDecision("shadow_passed", "eligible_for_manual_production_review", (), metrics)


def block_direct_candidate_to_production(candidate_status: str, target_status: str) -> None:
    if candidate_status == "candidate" and target_status == "production":
        raise ValueError("direct candidate -> production promotion is forbidden; use candidate -> shadow -> production")


def _metric_rows(probabilities: list[float], labels: list[int], rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for prob, label, row in zip(probabilities, labels, rows):
        output.append({
            "predicted_probability": prob,
            "label": label,
            "net_pnl_pct": row.get("net_pnl_pct", 0.0),
            "symbol": row.get("symbol"),
            "side": row.get("side"),
            "regime": row.get("regime"),
        })
    return output


def _bootstrap_brier_delta_upper(
    production: list[float],
    candidate: list[float],
    labels: list[int],
    iterations: int,
    seed: int,
) -> float:
    rng = random.Random(seed)
    n = len(labels)
    deltas: list[float] = []
    for _ in range(max(1, iterations)):
        indices = [rng.randrange(n) for _ in range(n)]
        prod_brier = sum((production[i] - labels[i]) ** 2 for i in indices) / n
        cand_brier = sum((candidate[i] - labels[i]) ** 2 for i in indices) / n
        deltas.append(cand_brier - prod_brier)
    deltas.sort()
    return deltas[min(len(deltas) - 1, int(0.95 * (len(deltas) - 1)))]


def _tail_regression_reasons(prod_metrics: Mapping[str, Any], cand_metrics: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    prod_buckets = prod_metrics.get("reliability_buckets") or []
    cand_buckets = cand_metrics.get("reliability_buckets") or []
    for prod, cand in zip(prod_buckets, cand_buckets):
        if prod.get("evidence_state") != "usable" or cand.get("evidence_state") != "usable":
            continue
        in_tail = float(prod.get("lower", 0.0)) >= 0.8 or float(prod.get("upper", 1.0)) <= 0.2
        if in_tail and (cand.get("calibration_error") or 0.0) > (prod.get("calibration_error") or 0.0) + 0.03:
            reasons.append("tail_calibration_regression")
    return reasons


def _prob(row: Mapping[str, Any], field: str) -> float:
    value = row.get(field)
    if value is None:
        raise ValueError(f"missing {field}")
    prob = float(value)
    if prob < 0.0 or prob > 1.0:
        raise ValueError(f"{field} out of range")
    return prob
