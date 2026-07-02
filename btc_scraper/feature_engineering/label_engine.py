from __future__ import annotations

import pandas as pd

from .meta_labeling import MetaLabeler, MetaLabelingConfig
from .triple_barrier import TripleBarrierConfig, TripleBarrierLabeler


class LabelEngine:
    """Phase 8 label orchestration entrypoint."""

    def __init__(
        self,
        config: TripleBarrierConfig | None = None,
        meta_config: MetaLabelingConfig | None = None,
    ) -> None:
        self.triple_barrier = TripleBarrierLabeler(config=config)
        self.meta_labeler = MetaLabeler(config=meta_config)

    def generate_triple_barrier_labels(
        self,
        signals: pd.DataFrame,
        candles: pd.DataFrame,
    ) -> pd.DataFrame:
        return self.triple_barrier.label(signals=signals, candles=candles)

    def generate_meta_labels(self, labeled_signals: pd.DataFrame) -> pd.DataFrame:
        return self.meta_labeler.label(labeled_signals)
