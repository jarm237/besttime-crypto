from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class CausalFeatureConfig:
    default_causal_alpha: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CausalFeatureBuilder:
    RISK_MAP = {
        "LOW": 0.2,
        "MEDIUM": 0.5,
        "HIGH": 0.75,
        "CRITICAL": 1.0,
    }

    def __init__(self, config: CausalFeatureConfig | None = None) -> None:
        self.config = config or CausalFeatureConfig()

    @staticmethod
    def _norm_text(value: Any) -> str:
        if value is None:
            return "LOW"
        text = str(value).strip().upper()
        return text if text else "LOW"

    @staticmethod
    def _to_float(series: pd.Series | Any, default: float = 0.0) -> pd.Series:
        if isinstance(series, pd.Series):
            return pd.to_numeric(series, errors="coerce").fillna(default)
        return pd.Series([default])

    def build(self, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame.copy()

        out = frame.copy()

        risk_source = out.get("causal_risk_level")
        if risk_source is None:
            risk_source = out.get("context_risk_level")
        if risk_source is None:
            risk_source = out.get("risk_level")

        if risk_source is None:
            out["causal_risk_level"] = "LOW"
        else:
            out["causal_risk_level"] = risk_source.astype(str).str.upper().replace({"": "LOW"}).fillna("LOW")

        if "causal_risk_raw" in out.columns:
            out["causal_risk_raw"] = pd.to_numeric(out["causal_risk_raw"], errors="coerce")
            out["causal_risk_raw"] = out["causal_risk_raw"].fillna(out["causal_risk_level"].map(self.RISK_MAP).fillna(0.2))
        else:
            out["causal_risk_raw"] = out["causal_risk_level"].map(self.RISK_MAP).fillna(0.2)

        alpha_source = out.get("causal_alpha")
        if alpha_source is None:
            alpha_source = out.get("CAUSAL_ALPHA")
        if alpha_source is None:
            out["causal_alpha"] = float(self.config.default_causal_alpha)
        else:
            out["causal_alpha"] = pd.to_numeric(alpha_source, errors="coerce").fillna(float(self.config.default_causal_alpha))

        context_adj_source = out.get("causal_context_adjustment")
        if context_adj_source is None:
            context_adj_source = out.get("context_adjustment")
        if context_adj_source is None:
            out["causal_context_adjustment"] = 0.0
        else:
            out["causal_context_adjustment"] = pd.to_numeric(context_adj_source, errors="coerce").fillna(0.0)

        out["causal_overridden"] = out.get("causal_overridden", False).astype(bool).astype(int)
        out["causal_context_skipped"] = out.get("context_skipped", out.get("causal_context_skipped", False)).astype(bool).astype(int)

        out["causal_primary_path_confidence"] = pd.to_numeric(
            out.get("causal_primary_path_confidence", out.get("confidence", 0.0)),
            errors="coerce",
        ).fillna(0.0)
        if out["causal_primary_path_confidence"].max(skipna=True) > 1.0:
            out["causal_primary_path_confidence"] = out["causal_primary_path_confidence"] / 100.0
        out["causal_primary_path_confidence"] = out["causal_primary_path_confidence"].clip(0.0, 1.0)

        out["causal_num_rules_fired"] = pd.to_numeric(
            out.get("causal_num_rules_fired", out.get("context_adjustments_count", 0)),
            errors="coerce",
        ).fillna(0).astype(int)

        out["causal_num_active_edges"] = pd.to_numeric(
            out.get("causal_num_active_edges", out.get("num_active_edges", 0)),
            errors="coerce",
        ).fillna(0).astype(int)

        out["cf_delta_pnl"] = pd.to_numeric(out.get("cf_delta_pnl", out.get("delta_pnl", 0.0)), errors="coerce").fillna(0.0)
        out["cf_intervention_node"] = out.get("cf_intervention_node", out.get("counterfactual_feature", ""))
        out["cf_intervention_value"] = pd.to_numeric(
            out.get("cf_intervention_value", out.get("counterfactual_value", 0.0)),
            errors="coerce",
        ).fillna(0.0)

        out["causal_risk_LOW"] = (out["causal_risk_level"] == "LOW").astype(int)
        out["causal_risk_MEDIUM"] = (out["causal_risk_level"] == "MEDIUM").astype(int)
        out["causal_risk_HIGH"] = (out["causal_risk_level"] == "HIGH").astype(int)
        out["causal_risk_CRITICAL"] = (out["causal_risk_level"] == "CRITICAL").astype(int)

        return out
