from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd


@dataclass
class LabelQualityConfig:
    positive_meta_label: int = 1
    negative_meta_label: int = 0
    min_samples_warning: int = 50
    severe_imbalance_ratio: float = 4.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LabelQualityThresholds:
    min_triple_rows: int = 100
    min_meta_rows: int = 100
    min_trade_quality_rows: int = 100
    min_executable_signal_rate: float = 0.80
    min_meta_execute_rate: float = 0.40
    max_meta_class_imbalance_ratio: float = 3.0
    max_warning_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LabelQualityReporter:
    """Build label-quality report for Phase 8 monitoring and release checks."""

    def __init__(self, config: LabelQualityConfig | None = None) -> None:
        self.config = config or LabelQualityConfig()

    @staticmethod
    def _normalize_distribution_key(value: Any) -> str:
        if pd.isna(value):
            return "NA"
        if isinstance(value, str):
            try:
                numeric = float(value)
            except ValueError:
                return value
            if numeric.is_integer():
                return str(int(numeric))
            return str(numeric)
        if isinstance(value, (int, float)):
            numeric = float(value)
            if numeric.is_integer():
                return str(int(numeric))
            return str(numeric)
        return str(value)

    @staticmethod
    def _distribution(frame: pd.DataFrame, column: str) -> dict[str, int]:
        if frame.empty or column not in frame.columns:
            return {}
        normalized = frame[column].map(LabelQualityReporter._normalize_distribution_key).fillna("NA").astype(str)
        vc = normalized.value_counts(dropna=False)
        return {str(k): int(v) for k, v in vc.to_dict().items()}

    @staticmethod
    def _safe_div(n: float, d: float) -> float | None:
        if d == 0:
            return None
        return float(n / d)

    def build_report(
        self,
        *,
        triple_labels: pd.DataFrame | None = None,
        meta_labels: pd.DataFrame | None = None,
        trade_quality: pd.DataFrame | None = None,
        fallback_frame: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        triple = triple_labels.copy() if triple_labels is not None else pd.DataFrame()
        meta = meta_labels.copy() if meta_labels is not None else pd.DataFrame()
        trade = trade_quality.copy() if trade_quality is not None else pd.DataFrame()
        fallback = fallback_frame.copy() if fallback_frame is not None else pd.DataFrame()

        # Build fallback pseudo-label views when dedicated label tables are absent.
        if triple.empty and "result" in fallback.columns:
            triple = fallback[[c for c in ["coin", "entry_time", "result"] if c in fallback.columns]].copy()
            triple = triple.rename(columns={"result": "triple_barrier_label"})

        if meta.empty and "result" in fallback.columns:
            mapped = fallback[[c for c in ["coin", "entry_time", "result"] if c in fallback.columns]].copy()
            mapped["meta_label"] = mapped["result"].astype(str).str.upper().map({"WIN": 1, "LOSS": 0})
            meta = mapped[[c for c in ["coin", "entry_time", "meta_label"] if c in mapped.columns]]

        if trade.empty and "pnl_pct" in fallback.columns:
            tq = fallback[[c for c in ["coin", "entry_time", "pnl_pct"] if c in fallback.columns]].copy()
            tq["trade_quality_bucket"] = pd.cut(
                tq["pnl_pct"],
                bins=[-float("inf"), -0.5, 0.0, 0.75, float("inf")],
                labels=["D", "C", "B", "A"],
            ).astype(str)
            trade = tq

        triple_dist = self._distribution(triple, "triple_barrier_label")
        meta_dist = self._distribution(meta, "meta_label")
        trade_dist = self._distribution(trade, "trade_quality_bucket")

        meta_total = int(len(meta))
        meta_pos = int(meta_dist.get(str(self.config.positive_meta_label), 0))
        meta_neg = int(meta_dist.get(str(self.config.negative_meta_label), 0))
        meta_exec_rate = self._safe_div(meta_pos, meta_total)

        imbalance_ratio = None
        if meta_pos > 0 and meta_neg > 0:
            imbalance_ratio = float(max(meta_pos, meta_neg) / min(meta_pos, meta_neg))

        triple_total = int(len(triple))
        executable_count = int(
            sum(
                count
                for label, count in triple_dist.items()
                if str(label).upper() not in {"NA", "NAN", "NONE", "NEUTRAL"}
            )
        )
        executable_rate = self._safe_div(executable_count, triple_total)

        pnl_summary = {}
        if "pnl_pct" in fallback.columns and len(fallback) > 0:
            pnl = pd.to_numeric(fallback["pnl_pct"], errors="coerce").dropna()
            if len(pnl) > 0:
                pnl_summary = {
                    "count": int(len(pnl)),
                    "mean": float(pnl.mean()),
                    "median": float(pnl.median()),
                    "std": float(pnl.std(ddof=0)),
                    "win_rate": float((pnl > 0).mean()),
                }

        warnings: list[str] = []
        if triple_total < self.config.min_samples_warning:
            warnings.append(f"Low triple-barrier sample count: {triple_total}")
        if meta_total < self.config.min_samples_warning:
            warnings.append(f"Low meta-label sample count: {meta_total}")
        if imbalance_ratio is not None and imbalance_ratio >= self.config.severe_imbalance_ratio:
            warnings.append(f"Severe class imbalance detected: {imbalance_ratio:.2f}")
        if not triple_dist:
            warnings.append("Missing triple barrier label distribution")
        if not meta_dist:
            warnings.append("Missing meta label distribution")

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "counts": {
                "triple_barrier_rows": triple_total,
                "meta_label_rows": meta_total,
                "trade_quality_rows": int(len(trade)),
            },
            "distributions": {
                "triple_barrier_label": triple_dist,
                "meta_label": meta_dist,
                "trade_quality_bucket": trade_dist,
            },
            "quality_metrics": {
                "executable_signal_rate": executable_rate,
                "meta_execute_rate": meta_exec_rate,
                "meta_class_imbalance_ratio": imbalance_ratio,
                "pnl_summary": pnl_summary,
            },
            "warnings": warnings,
            "config": self.config.to_dict(),
        }


def evaluate_label_quality_thresholds(
    report: dict[str, Any],
    thresholds: LabelQualityThresholds | None = None,
) -> dict[str, Any]:
    cfg = thresholds or LabelQualityThresholds()

    counts = report.get("counts", {}) if isinstance(report, dict) else {}
    quality = report.get("quality_metrics", {}) if isinstance(report, dict) else {}
    warnings = report.get("warnings", []) if isinstance(report, dict) else []

    checks: dict[str, dict[str, Any]] = {}
    failures: dict[str, dict[str, Any]] = {}

    def record_check(key: str, ok: bool, value: Any, threshold: Any, mode: str) -> None:
        status = "pass" if ok else "fail"
        payload = {
            "status": status,
            "value": value,
            "threshold": threshold,
            "mode": mode,
        }
        checks[key] = payload
        if not ok:
            failures[key] = payload

    triple_rows = int(counts.get("triple_barrier_rows", 0) or 0)
    meta_rows = int(counts.get("meta_label_rows", 0) or 0)
    trade_rows = int(counts.get("trade_quality_rows", 0) or 0)

    executable_rate = quality.get("executable_signal_rate")
    meta_execute_rate = quality.get("meta_execute_rate")
    imbalance = quality.get("meta_class_imbalance_ratio")
    warn_count = len(warnings) if isinstance(warnings, list) else 0

    record_check(
        "counts.triple_barrier_rows",
        triple_rows >= cfg.min_triple_rows,
        triple_rows,
        cfg.min_triple_rows,
        "min",
    )
    record_check(
        "counts.meta_label_rows",
        meta_rows >= cfg.min_meta_rows,
        meta_rows,
        cfg.min_meta_rows,
        "min",
    )
    record_check(
        "counts.trade_quality_rows",
        trade_rows >= cfg.min_trade_quality_rows,
        trade_rows,
        cfg.min_trade_quality_rows,
        "min",
    )

    if executable_rate is None:
        record_check(
            "quality_metrics.executable_signal_rate",
            False,
            None,
            cfg.min_executable_signal_rate,
            "min",
        )
    else:
        record_check(
            "quality_metrics.executable_signal_rate",
            float(executable_rate) >= cfg.min_executable_signal_rate,
            float(executable_rate),
            cfg.min_executable_signal_rate,
            "min",
        )

    if meta_execute_rate is None:
        # No meta labels available: skip this metric rather than hard-failing.
        # The counts.meta_label_rows check already catches the missing-data case.
        record_check(
            "quality_metrics.meta_execute_rate",
            True,
            None,
            cfg.min_meta_execute_rate,
            "skip",
        )
    else:
        record_check(
            "quality_metrics.meta_execute_rate",
            float(meta_execute_rate) >= cfg.min_meta_execute_rate,
            float(meta_execute_rate),
            cfg.min_meta_execute_rate,
            "min",
        )

    if imbalance is None:
        record_check(
            "quality_metrics.meta_class_imbalance_ratio",
            True,
            None,
            cfg.max_meta_class_imbalance_ratio,
            "max",
        )
    else:
        record_check(
            "quality_metrics.meta_class_imbalance_ratio",
            float(imbalance) <= cfg.max_meta_class_imbalance_ratio,
            float(imbalance),
            cfg.max_meta_class_imbalance_ratio,
            "max",
        )

    record_check(
        "warnings.count",
        warn_count <= cfg.max_warning_count,
        warn_count,
        cfg.max_warning_count,
        "max",
    )

    return {
        "ok": len(failures) == 0,
        "thresholds": cfg.to_dict(),
        "checks": checks,
        "failures": failures,
        "source_generated_at": report.get("generated_at") if isinstance(report, dict) else None,
    }
