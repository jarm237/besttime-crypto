from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class FeatureValidationConfig:
    max_missing_rate: float = 0.30
    correlation_threshold: float = 0.95
    leakage_corr_threshold: float = 0.995
    psi_threshold: float = 0.20
    psi_reject_threshold: float = 0.40
    psi_bins: int = 10

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FeatureValidator:
    """Validate candidate features before training usage."""

    LEAKAGE_NAME_TOKENS = (
        "future",
        "target",
        "label",
        "leak",
        "lookahead",
        "outcome",
        "pnl",
        "exit_",
        "result",
    )

    def __init__(self, config: FeatureValidationConfig | None = None) -> None:
        self.config = config or FeatureValidationConfig()
        self._quality_report: dict[str, Any] = {}
        self._rejection_report: dict[str, Any] = {}

    @staticmethod
    def _numeric_columns(frame: pd.DataFrame) -> list[str]:
        return [c for c in frame.columns if pd.api.types.is_numeric_dtype(frame[c])]

    @staticmethod
    def _detect_label_column(frame: pd.DataFrame) -> str | None:
        candidates = [
            "label",
            "meta_label",
            "triple_barrier_label",
            "trade_quality_score",
            "trade_quality_bucket",
            "result",
        ]
        for c in candidates:
            if c in frame.columns:
                return c
        return None

    @staticmethod
    def _connected_components(edges: list[tuple[str, str]]) -> list[list[str]]:
        graph: dict[str, set[str]] = {}
        for a, b in edges:
            graph.setdefault(a, set()).add(b)
            graph.setdefault(b, set()).add(a)

        seen: set[str] = set()
        groups: list[list[str]] = []
        for node in sorted(graph):
            if node in seen:
                continue
            stack = [node]
            component: list[str] = []
            while stack:
                cur = stack.pop()
                if cur in seen:
                    continue
                seen.add(cur)
                component.append(cur)
                stack.extend(graph.get(cur, set()) - seen)
            groups.append(sorted(component))
        return groups

    def _missing_check(self, frame: pd.DataFrame, features: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
        flagged: list[dict[str, Any]] = []
        rejected: list[str] = []
        for col in features:
            rate = float(frame[col].isna().mean())
            if rate > self.config.max_missing_rate:
                flagged.append({"feature": col, "missing_rate": rate})
                rejected.append(col)
        return flagged, sorted(set(rejected))

    def _correlation_check(self, frame: pd.DataFrame, features: list[str]) -> tuple[list[list[str]], list[str], list[dict[str, Any]]]:
        if not features:
            return [], [], []

        corr = frame[features].corr(method="pearson").abs()
        edges: list[tuple[str, str]] = []
        pairs: list[dict[str, Any]] = []
        for i, col_i in enumerate(features):
            for j in range(i + 1, len(features)):
                col_j = features[j]
                value = float(corr.loc[col_i, col_j])
                if np.isnan(value):
                    continue
                if value >= self.config.correlation_threshold:
                    edges.append((col_i, col_j))
                    pairs.append({"feature_a": col_i, "feature_b": col_j, "abs_corr": value})

        groups = self._connected_components(edges)
        rejected: list[str] = []
        for group in groups:
            keep = sorted(group)[0]
            for col in group:
                if col != keep:
                    rejected.append(col)

        return groups, sorted(set(rejected)), pairs

    def _leakage_check(self, frame: pd.DataFrame, features: list[str], label_col: str | None) -> tuple[list[dict[str, Any]], list[str]]:
        findings: list[dict[str, Any]] = []
        rejected: list[str] = []

        for col in features:
            lower = col.lower()
            if any(token in lower for token in self.LEAKAGE_NAME_TOKENS):
                findings.append({"feature": col, "reason": "name_pattern"})
                rejected.append(col)

        if label_col and label_col in frame.columns and pd.api.types.is_numeric_dtype(frame[label_col]):
            y = pd.to_numeric(frame[label_col], errors="coerce")
            for col in features:
                if col == label_col:
                    findings.append({"feature": col, "reason": "label_column"})
                    rejected.append(col)
                    continue
                x = pd.to_numeric(frame[col], errors="coerce")
                valid = x.notna() & y.notna()
                if int(valid.sum()) < 20:
                    continue
                corr = float(x[valid].corr(y[valid]))
                if not np.isnan(corr) and abs(corr) >= self.config.leakage_corr_threshold:
                    findings.append({"feature": col, "reason": "label_correlation", "abs_corr": abs(corr)})
                    rejected.append(col)

        return findings, sorted(set(rejected))

    def _psi(self, expected: pd.Series, actual: pd.Series, bins: int) -> float:
        exp = pd.to_numeric(expected, errors="coerce").dropna()
        act = pd.to_numeric(actual, errors="coerce").dropna()
        if len(exp) < 20 or len(act) < 20:
            return float("nan")

        quantiles = np.linspace(0, 1, bins + 1)
        breaks = np.unique(np.quantile(exp, quantiles))
        if len(breaks) < 3:
            return float("nan")

        exp_count, _ = np.histogram(exp, bins=breaks)
        act_count, _ = np.histogram(act, bins=breaks)

        exp_pct = np.clip(exp_count / max(exp_count.sum(), 1), 1e-6, None)
        act_pct = np.clip(act_count / max(act_count.sum(), 1), 1e-6, None)
        return float(np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct)))

    def _psi_check(
        self,
        frame: pd.DataFrame,
        features: list[str],
        *,
        time_col: str | None = None,
        reference_frame: pd.DataFrame | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        if not features:
            return [], []

        if reference_frame is not None and len(reference_frame) > 0:
            ref = reference_frame.copy()
            cur = frame.copy()
        else:
            if time_col and time_col in frame.columns:
                sorted_frame = frame.sort_values(time_col, kind="mergesort")
            else:
                sorted_frame = frame.copy()
            split = int(max(1, len(sorted_frame) * 0.7))
            ref = sorted_frame.iloc[:split]
            cur = sorted_frame.iloc[split:]

        findings: list[dict[str, Any]] = []
        rejected: list[str] = []
        for col in features:
            psi = self._psi(ref[col], cur[col], bins=self.config.psi_bins)
            if np.isnan(psi):
                continue
            if psi >= self.config.psi_threshold:
                findings.append({"feature": col, "psi": psi})
            if psi >= self.config.psi_reject_threshold:
                rejected.append(col)
        return findings, sorted(set(rejected))

    def validate(
        self,
        frame: pd.DataFrame,
        *,
        time_col: str | None = None,
        reference_frame: pd.DataFrame | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        numeric_features = self._numeric_columns(frame)
        label_col = self._detect_label_column(frame)

        missing_flagged, reject_missing = self._missing_check(frame, numeric_features)

        leakage_features = [c for c in numeric_features if c not in set(reject_missing)]
        leakage_findings, reject_leak = self._leakage_check(frame, leakage_features, label_col=label_col)

        corr_features = [c for c in numeric_features if c not in set(reject_missing + reject_leak)]
        corr_groups, reject_corr, corr_pairs = self._correlation_check(frame, corr_features)

        psi_features = [c for c in numeric_features if c not in set(reject_missing + reject_corr + reject_leak)]
        psi_findings, reject_psi = self._psi_check(
            frame,
            psi_features,
            time_col=time_col,
            reference_frame=reference_frame,
        )

        rejected = sorted(set(reject_missing + reject_corr + reject_leak + reject_psi))
        accepted = [c for c in numeric_features if c not in set(rejected)]

        self._quality_report = {
            "rows": int(len(frame)),
            "numeric_feature_count": int(len(numeric_features)),
            "accepted_feature_count": int(len(accepted)),
            "rejected_feature_count": int(len(rejected)),
            "accepted_features": accepted,
            "rejected_features": rejected,
            "missing": {
                "threshold": self.config.max_missing_rate,
                "flagged": missing_flagged,
            },
            "correlation": {
                "threshold": self.config.correlation_threshold,
                "groups": corr_groups,
                "pairs": corr_pairs,
            },
            "leakage": {
                "threshold": self.config.leakage_corr_threshold,
                "label_column": label_col,
                "findings": leakage_findings,
            },
            "psi": {
                "threshold": self.config.psi_threshold,
                "reject_threshold": self.config.psi_reject_threshold,
                "findings": psi_findings,
            },
            "config": self.config.to_dict(),
        }

        by_feature: dict[str, list[str]] = {f: [] for f in rejected}
        for f in reject_missing:
            by_feature.setdefault(f, []).append("high_missing_rate")
        for f in reject_corr:
            by_feature.setdefault(f, []).append("high_correlation")
        for f in reject_leak:
            by_feature.setdefault(f, []).append("leakage_risk")
        for f in reject_psi:
            by_feature.setdefault(f, []).append("high_psi_drift")

        self._rejection_report = {
            "rejected_feature_count": int(len(rejected)),
            "rejections": [
                {"feature": f, "reasons": by_feature.get(f, [])}
                for f in sorted(rejected)
            ],
        }
        return self._quality_report, self._rejection_report

    def get_quality_report(self) -> dict[str, Any]:
        return dict(self._quality_report)

    def get_rejection_report(self) -> dict[str, Any]:
        return dict(self._rejection_report)
