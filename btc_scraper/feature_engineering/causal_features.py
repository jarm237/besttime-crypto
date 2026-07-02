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

        if "causal_overridden" in out.columns:
            out["causal_overridden"] = out["causal_overridden"].astype(bool).astype(int)
        else:
            out["causal_overridden"] = 0

        if "context_skipped" in out.columns:
            out["causal_context_skipped"] = out["context_skipped"].astype(bool).astype(int)
        elif "causal_context_skipped" in out.columns:
            out["causal_context_skipped"] = out["causal_context_skipped"].astype(bool).astype(int)
        else:
            out["causal_context_skipped"] = 0

        if "causal_primary_path_confidence" in out.columns:
            confidence = pd.to_numeric(out["causal_primary_path_confidence"], errors="coerce").fillna(0.0)
        elif "confidence" in out.columns:
            confidence = pd.to_numeric(out["confidence"], errors="coerce").fillna(0.0)
        else:
            confidence = pd.Series(0.0, index=out.index)
        
        if confidence.max(skipna=True) > 1.0:
            confidence = confidence / 100.0
        out["causal_primary_path_confidence"] = confidence.clip(0.0, 1.0)

        if "causal_num_rules_fired" in out.columns:
            out["causal_num_rules_fired"] = pd.to_numeric(out["causal_num_rules_fired"], errors="coerce").fillna(0).astype(int)
        elif "context_adjustments_count" in out.columns:
            out["causal_num_rules_fired"] = pd.to_numeric(out["context_adjustments_count"], errors="coerce").fillna(0).astype(int)
        else:
            out["causal_num_rules_fired"] = 0

        if "causal_num_active_edges" in out.columns:
            out["causal_num_active_edges"] = pd.to_numeric(out["causal_num_active_edges"], errors="coerce").fillna(0).astype(int)
        elif "num_active_edges" in out.columns:
            out["causal_num_active_edges"] = pd.to_numeric(out["num_active_edges"], errors="coerce").fillna(0).astype(int)
        else:
            out["causal_num_active_edges"] = 0

        if "cf_delta_pnl" in out.columns:
            out["cf_delta_pnl"] = pd.to_numeric(out["cf_delta_pnl"], errors="coerce").fillna(0.0)
        elif "delta_pnl" in out.columns:
            out["cf_delta_pnl"] = pd.to_numeric(out["delta_pnl"], errors="coerce").fillna(0.0)
        else:
            out["cf_delta_pnl"] = 0.0

        if "cf_intervention_node" in out.columns:
            pass
        elif "counterfactual_feature" in out.columns:
            out["cf_intervention_node"] = out["counterfactual_feature"]
        else:
            out["cf_intervention_node"] = ""

        if "cf_intervention_value" in out.columns:
            out["cf_intervention_value"] = pd.to_numeric(out["cf_intervention_value"], errors="coerce").fillna(0.0)
        elif "counterfactual_value" in out.columns:
            out["cf_intervention_value"] = pd.to_numeric(out["counterfactual_value"], errors="coerce").fillna(0.0)
        else:
            out["cf_intervention_value"] = 0.0

        out["causal_risk_LOW"] = (out["causal_risk_level"] == "LOW").astype(int)
        out["causal_risk_MEDIUM"] = (out["causal_risk_level"] == "MEDIUM").astype(int)
        out["causal_risk_HIGH"] = (out["causal_risk_level"] == "HIGH").astype(int)
        out["causal_risk_CRITICAL"] = (out["causal_risk_level"] == "CRITICAL").astype(int)

        return out
