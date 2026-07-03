from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .feature_store import FeatureStoreV2


@dataclass
class DatasetBuilderV3Config:
    timeframe: str = "15m"
    lookahead_bars: int = 48
    label_type: str = "triple_barrier_meta"
    label_columns: list[str] = field(
        default_factory=lambda: [
            "triple_barrier_label",
            "meta_label",
            "trade_quality_score",
            "trade_quality_bucket",
            "result",
            "pnl_pct",
        ]
    )
    key_columns: list[str] = field(default_factory=lambda: ["coin", "entry_time"])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DatasetBuilderV3:
    """Build training dataset v3 using point-in-time-safe joins."""

    def __init__(self, config: DatasetBuilderV3Config | None = None, store: FeatureStoreV2 | None = None) -> None:
        self.config = config or DatasetBuilderV3Config()
        self.store = store or FeatureStoreV2()
        self._last_metadata: dict[str, Any] = {}

    @staticmethod
    def _resolve_time_col(frame: pd.DataFrame) -> str:
        if "entry_time" in frame.columns:
            return "entry_time"
        if "timestamp" in frame.columns:
            return "timestamp"
        raise ValueError("Expected one of time columns: entry_time, timestamp")

    @staticmethod
    def _resolve_coin_col(frame: pd.DataFrame) -> str | None:
        if "coin" in frame.columns:
            return "coin"
        if "symbol" in frame.columns:
            return "symbol"
        return None

    def _normalize_frame(self, frame: pd.DataFrame, *, keep_all: bool = True) -> tuple[pd.DataFrame, str, str | None]:
        out = frame.copy()
        time_col = self._resolve_time_col(out)
        coin_col = self._resolve_coin_col(out)

        out[time_col] = pd.to_datetime(out[time_col], utc=True, errors="coerce")
        if coin_col is not None:
            out[coin_col] = out[coin_col].astype(str)
            sort_cols = [coin_col, time_col]
        else:
            sort_cols = [time_col]

        out = out.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)
        return out, time_col, coin_col

    def _extract_labels(self, base: pd.DataFrame) -> pd.DataFrame:
        labels = [c for c in self.config.label_columns if c in base.columns]
        if not labels:
            return pd.DataFrame(index=base.index)
        return base[labels].copy()

    def _asof_join(
        self,
        left: pd.DataFrame,
        right: pd.DataFrame,
        *,
        left_time: str,
        right_time: str,
        left_coin: str | None,
        right_coin: str | None,
        feature_columns: list[str],
    ) -> pd.DataFrame:
        if not feature_columns:
            return left

        right_part = right[[c for c in [right_time, right_coin, *feature_columns] if c is not None and c in right.columns]].copy()
        if right_coin:
            right_part = right_part.sort_values([right_coin, right_time], kind="mergesort")
        else:
            right_part = right_part.sort_values([right_time], kind="mergesort")

        if left_coin and right_coin:
            left_sorted = left.sort_values([left_coin, left_time], kind="mergesort")
            joined_frames: list[pd.DataFrame] = []
            for coin_value, left_group in left_sorted.groupby(left_coin, sort=False):
                right_group = right_part[right_part[right_coin] == coin_value]
                if right_group.empty:
                    joined_frames.append(left_group)
                    continue

                joined_group = pd.merge_asof(
                    left_group,
                    right_group,
                    left_on=left_time,
                    right_on=right_time,
                    left_by=left_coin,
                    right_by=right_coin,
                    direction="backward",
                    allow_exact_matches=True,
                )
                joined_frames.append(joined_group)

            joined = pd.concat(joined_frames, ignore_index=True, sort=False) if joined_frames else left_sorted
        else:
            left_sorted = left.sort_values([left_time], kind="mergesort")
            joined = pd.merge_asof(
                left_sorted,
                right_part,
                left_on=left_time,
                right_on=right_time,
                direction="backward",
                allow_exact_matches=True,
            )

        if right_time in joined.columns and right_time != left_time:
            joined = joined.drop(columns=[right_time])
        if right_coin and left_coin and right_coin != left_coin and right_coin in joined.columns:
            joined = joined.drop(columns=[right_coin])
        return joined

    def build(
        self,
        base_frame: pd.DataFrame,
        feature_frames: dict[str, pd.DataFrame],
        *,
        labels_frame: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        base_norm, base_time, base_coin = self._normalize_frame(base_frame)
        if base_coin is None:
            base_norm["coin"] = "GLOBAL"
            base_coin = "coin"

        labels = self._extract_labels(base_norm)
        if labels_frame is not None and len(labels_frame) > 0:
            labels_ext, labels_time, labels_coin = self._normalize_frame(labels_frame)
            label_cols = [c for c in self.config.label_columns if c in labels_ext.columns]
            if label_cols:
                base_norm = self._asof_join(
                    base_norm,
                    labels_ext,
                    left_time=base_time,
                    right_time=labels_time,
                    left_coin=base_coin,
                    right_coin=labels_coin,
                    feature_columns=label_cols,
                )
                labels = base_norm[label_cols].copy()

        key_cols = [base_coin, base_time]
        dataset = base_norm[key_cols].copy()
        if not labels.empty:
            dataset = pd.concat([dataset, labels], axis=1)

        used_groups: list[str] = []
        for group_name, frame in feature_frames.items():
            if frame is None or frame.empty:
                continue
            group_norm, group_time, group_coin = self._normalize_frame(frame)

            base_cols = set(key_cols) | set(self.config.label_columns) | {"result", "pnl_pct", "signal_raw", "exit_time"}
            feature_cols = [c for c in group_norm.columns if c not in base_cols and c not in {group_time, group_coin}]
            feature_cols = [c for c in feature_cols if c not in dataset.columns]
            if not feature_cols:
                continue

            dataset = self._asof_join(
                dataset,
                group_norm,
                left_time=base_time,
                right_time=group_time,
                left_coin=base_coin,
                right_coin=group_coin,
                feature_columns=feature_cols,
            )
            used_groups.append(group_name)

        dataset = dataset.sort_values([base_coin, base_time], kind="mergesort").reset_index(drop=True)
        numeric = dataset.select_dtypes(include=["number"]).columns
        dataset[numeric] = dataset[numeric].replace([float("inf"), float("-inf")], pd.NA)

        self._last_metadata = {
            "rows": int(len(dataset)),
            "columns": int(len(dataset.columns)),
            "timeframe": self.config.timeframe,
            "label_type": self.config.label_type,
            "lookahead_bars": self.config.lookahead_bars,
            "feature_groups": used_groups,
            "label_columns_present": [c for c in self.config.label_columns if c in dataset.columns],
            "config": self.config.to_dict(),
        }
        return dataset

    def persist(self, dataset: pd.DataFrame, output_path: Path, output_format: str = "auto") -> tuple[Path, Path, dict[str, Any]]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fmt = output_format
        if fmt == "auto":
            fmt = "parquet" if output_path.suffix.lower() == ".parquet" else "csv"

        if fmt == "parquet":
            dataset.to_parquet(output_path, index=False)
        else:
            dataset.to_csv(output_path, index=False)

        version = self.store.write_dataset_version(
            dataset,
            label_type=self.config.label_type,
            lookahead_bars=self.config.lookahead_bars,
            timeframe=self.config.timeframe,
            feature_groups=self._last_metadata.get("feature_groups", []),
            version_prefix="v3",
        )

        metadata = dict(self._last_metadata)
        metadata["dataset_version"] = asdict(version)
        metadata_path = output_path.parent / "ml_dataset_v3_metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return output_path, metadata_path, metadata

    def get_metadata(self) -> dict[str, Any]:
        return dict(self._last_metadata)
