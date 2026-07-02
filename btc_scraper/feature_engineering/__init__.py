"""Phase 8 feature engineering package."""

from .alternative_features import AlternativeFeatureBuilder, AlternativeFeatureConfig
from .causal_features import CausalFeatureBuilder, CausalFeatureConfig
from .cross_sectional_features import CrossSectionalFeatureBuilder, CrossSectionalFeatureConfig
from .dataset_builder_v3 import DatasetBuilderV3, DatasetBuilderV3Config
from .feature_store import FeatureStoreV2
from .feature_validator import FeatureValidationConfig, FeatureValidator
from .fractional_diff import FractionalDiffBuilder, FractionalDiffConfig
from .label_quality import (
    LabelQualityConfig,
    LabelQualityReporter,
    LabelQualityThresholds,
    evaluate_label_quality_thresholds,
)
from .meta_labeling import MetaLabeler, MetaLabelingConfig
from .regime_features import RegimeFeatureBuilder, RegimeFeatureConfig
from .triple_barrier import TripleBarrierConfig, TripleBarrierLabeler

__all__ = [
    "AlternativeFeatureBuilder",
    "AlternativeFeatureConfig",
    "CausalFeatureBuilder",
    "CausalFeatureConfig",
    "CrossSectionalFeatureBuilder",
    "CrossSectionalFeatureConfig",
    "DatasetBuilderV3",
    "DatasetBuilderV3Config",
    "FeatureStoreV2",
    "FeatureValidationConfig",
    "FeatureValidator",
    "FractionalDiffBuilder",
    "FractionalDiffConfig",
    "LabelQualityConfig",
    "LabelQualityReporter",
    "LabelQualityThresholds",
    "evaluate_label_quality_thresholds",
    "MetaLabeler",
    "MetaLabelingConfig",
    "RegimeFeatureBuilder",
    "RegimeFeatureConfig",
    "TripleBarrierConfig",
    "TripleBarrierLabeler",
]
