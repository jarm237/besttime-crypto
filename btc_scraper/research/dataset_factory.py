"""
btc_scraper/research/dataset_factory.py
Phase M3-D: Research Dataset Factory.

Assembles HistoricalDatasetProvider, FeatureFactory, and TripleBarrierLabelFactory into
strictly aligned, leakage-free datasets (X, y, metadata, purge_intervals) for research
and walk-forward cross-validation.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import numpy as np

from btc_scraper.research.dataset_provider import HistoricalDatasetProvider
from btc_scraper.research.feature_contract import FeatureSetSpec
from btc_scraper.research.feature_factory import FeatureFactory
from btc_scraper.research.label_factory import (
    TripleBarrierLabel,
    TripleBarrierLabelFactory,
    TripleBarrierSpec,
)


@dataclass(frozen=True)
class RowFunnelAccounting:
    """
    Transparent accounting of every candle row from ingestion to final aligned dataset.
    raw_eligible_decisions -> feature_warmup -> valid_features -> label_candidates -> resolved_labels -> final_research_samples
    """
    raw_eligible_decisions: int    # total base candles loaded
    feature_warmup_dropped: int    # initial bars reserved for feature warmup
    terminal_horizon_dropped: int  # trailing bars reserved for labeling horizon
    invalid_feature_rows: int      # rows containing NaN or Inf in features
    unresolved_labels_dropped: int # candidate rows where label resolution was None
    final_research_samples: int    # final clean, leakage-free aligned rows

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


@dataclass
class AlignedDataset:
    """
    Leakage-free aligned research dataset.
    Each sample i has features X[i] available at decision_time, entry at Next-Bar-Open,
    label y[i] evaluated via triple barrier, and purge_interval for walk-forward CV.
    """
    feature_spec: FeatureSetSpec
    label_spec: TripleBarrierSpec
    symbol: str
    feature_names: Tuple[str, ...]
    features: List[Dict[str, float]]
    labels: List[TripleBarrierLabel]
    decision_times: List[str]
    purge_intervals: List[Tuple[str, str]]
    funnel: Optional[RowFunnelAccounting] = None

    def __len__(self) -> int:
        return len(self.features)

    def to_numpy(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Converts aligned dataset to numpy matrices.
        Returns:
            X: 2D float array (N x D)
            y: 1D int array (N,) of label classes {-1, 0, 1}
            net_returns: 1D float array (N,) of net economic returns
        """
        n = len(self.features)
        d = len(self.feature_names)

        X = np.zeros((n, d), dtype=np.float64)
        for i, row in enumerate(self.features):
            for j, feat_name in enumerate(self.feature_names):
                X[i, j] = row.get(feat_name, 0.0)

        y = np.array([lbl.label_class for lbl in self.labels], dtype=np.int32)
        net_returns = np.array([lbl.net_return for lbl in self.labels], dtype=np.float64)

        return X, y, net_returns


class ResearchDatasetFactory:
    """
    Factory that orchestrates data ingestion, feature generation, and label construction.
    """

    @classmethod
    def build_aligned_dataset(
        cls,
        provider: HistoricalDatasetProvider,
        feature_spec: FeatureSetSpec,
        label_spec: TripleBarrierSpec,
        symbol: str,
        start_time: str,
        end_time: str,
        side: str = "LONG",
        min_warmup_bars: int = 50,
    ) -> AlignedDataset:
        """
        Builds an aligned dataset for the given symbol and timeframe range.
        Discards warmup prefix and incomplete terminal suffix to ensure complete alignment.
        """
        # 1. Ingest base candles
        base_tf = feature_spec.base_timeframe
        base_candles = provider.load_candles(
            symbol=symbol,
            timeframe=base_tf,
            start_time=start_time,
            end_time=end_time,
            include_warmup=True,
        )

        if len(base_candles) < min_warmup_bars + label_spec.max_holding_bars + 2:
            raise ValueError(
                f"Insufficient candles loaded ({len(base_candles)}) for symbol={symbol} "
                f"to satisfy warmup ({min_warmup_bars}) and labeling horizon ({label_spec.max_holding_bars})"
            )

        # 2. Ingest higher timeframe context candles
        mtf_candles: Dict[str, List[Dict[str, Any]]] = {}
        for htf in feature_spec.higher_timeframes:
            try:
                htf_data = provider.load_candles(
                    symbol=symbol,
                    timeframe=htf,
                    start_time=start_time,
                    end_time=end_time,
                    include_warmup=True,
                )
                mtf_candles[htf] = htf_data
            except Exception:
                # If HTF is not available, proceed without it
                pass

        # 3. Compute Point-in-Time Features
        feature_factory = FeatureFactory(feature_spec)
        raw_features = feature_factory.compute_batch_features(base_candles, mtf_candles)

        # 4. Compute Triple Barrier Labels
        label_factory = TripleBarrierLabelFactory(label_spec)
        raw_labels = label_factory.compute_labels(base_candles, side=side)

        # 5. Align valid samples: trim warmup prefix and incomplete suffix
        aligned_features: List[Dict[str, float]] = []
        aligned_labels: List[TripleBarrierLabel] = []
        decision_times: List[str] = []
        purge_intervals: List[Tuple[str, str]] = []

        total_bars = len(base_candles)
        warmup_dropped = min_warmup_bars
        terminal_dropped = label_spec.max_holding_bars + 1
        terminal_cutoff = total_bars - terminal_dropped

        invalid_feature_count = 0
        unresolved_label_count = 0

        for i in range(min_warmup_bars, terminal_cutoff):
            lbl = raw_labels[i]
            if lbl is None:
                unresolved_label_count += 1
                continue

            feat = raw_features[i]
            
            # Check for invalid values (NaN, Inf) in feature vector
            has_invalid = False
            for v in feat.values():
                if math.isnan(v) or math.isinf(v):
                    has_invalid = True
                    break

            if has_invalid:
                invalid_feature_count += 1
                continue

            d_time = str(base_candles[i].get("close_time", base_candles[i].get("time", "")))

            aligned_features.append(feat)
            aligned_labels.append(lbl)
            decision_times.append(d_time)
            purge_intervals.append((lbl.label_start_time, lbl.label_end_time))

        funnel = RowFunnelAccounting(
            raw_eligible_decisions=total_bars,
            feature_warmup_dropped=warmup_dropped,
            terminal_horizon_dropped=terminal_dropped,
            invalid_feature_rows=invalid_feature_count,
            unresolved_labels_dropped=unresolved_label_count,
            final_research_samples=len(aligned_features),
        )

        return AlignedDataset(
            feature_spec=feature_spec,
            label_spec=label_spec,
            symbol=symbol,
            feature_names=feature_spec.feature_names,
            features=aligned_features,
            labels=aligned_labels,
            decision_times=decision_times,
            purge_intervals=purge_intervals,
            funnel=funnel,
        )
