from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from btc_scraper.core.paths import build_data_path

FEATURE_LAYERS = {
    "raw",
    "clean",
    "normalized",
    "labels",
    "derived",
    "causal",
    "regime",
    "training",
}


@dataclass
class DatasetVersion:
    dataset_version: str
    created_at: str
    row_count: int
    feature_count: int
    label_type: str
    lookahead_bars: int
    timeframe: str
    source_hash: str
    feature_groups: list[str]


class FeatureStoreV2:
    """Simple file-based feature store for Phase 8 pipelines."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else build_data_path("feature_store")
        self.root.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.root / "feature_metadata.json"
        self.dataset_version_index = self.root / "dataset_versions.json"

    def ensure_structure(self) -> None:
        for layer in sorted(FEATURE_LAYERS):
            (self.root / layer).mkdir(parents=True, exist_ok=True)

    def _resolve_layer(self, layer: str) -> Path:
        layer_norm = layer.strip().lower()
        if layer_norm not in FEATURE_LAYERS:
            valid = ", ".join(sorted(FEATURE_LAYERS))
            raise ValueError(f"Unsupported layer '{layer}'. Expected one of: {valid}")
        path = self.root / layer_norm
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_table(self, frame: pd.DataFrame, layer: str, name: str, fmt: str = "parquet") -> Path:
        """Persist a feature table in the requested layer."""
        layer_path = self._resolve_layer(layer)
        fmt_norm = fmt.lower().strip()

        if fmt_norm == "parquet":
            out_path = layer_path / f"{name}.parquet"
            frame.to_parquet(out_path, index=False)
            return out_path

        if fmt_norm == "csv":
            out_path = layer_path / f"{name}.csv"
            frame.to_csv(out_path, index=False)
            return out_path

        raise ValueError("fmt must be one of: parquet, csv")

    def load_table(self, layer: str, name: str) -> pd.DataFrame:
        """Load a table by checking parquet first, then csv fallback."""
        layer_path = self._resolve_layer(layer)
        parquet_path = layer_path / f"{name}.parquet"
        csv_path = layer_path / f"{name}.csv"

        if parquet_path.exists():
            return pd.read_parquet(parquet_path)
        if csv_path.exists():
            return pd.read_csv(csv_path)

        raise FileNotFoundError(f"No table found for {name} in layer {layer}")

    def register_feature_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Upsert feature metadata keyed by feature_name."""
        feature_name = str(metadata.get("feature_name", "")).strip()
        if not feature_name:
            raise ValueError("metadata.feature_name is required")

        existing = self.load_feature_metadata()
        now = datetime.now(timezone.utc).isoformat()
        payload = dict(metadata)
        payload["updated_at"] = now
        if feature_name not in existing:
            payload["created_at"] = now
        else:
            payload.setdefault("created_at", existing[feature_name].get("created_at", now))

        existing[feature_name] = payload
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    def load_feature_metadata(self) -> dict[str, dict[str, Any]]:
        if not self.metadata_path.exists():
            return {}
        raw = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}

    @staticmethod
    def _compute_source_hash(frame: pd.DataFrame) -> str:
        """Stable fingerprint to track reproducibility of generated datasets."""
        payload = frame.copy()
        payload = payload.sort_index(axis=1)
        hashed = pd.util.hash_pandas_object(payload, index=True).values.tobytes()
        return hashlib.sha256(hashed).hexdigest()

    def write_dataset_version(
        self,
        frame: pd.DataFrame,
        *,
        label_type: str,
        lookahead_bars: int,
        timeframe: str,
        feature_groups: list[str],
        version_prefix: str = "v3",
    ) -> DatasetVersion:
        created_at = datetime.now(timezone.utc)
        version_suffix = created_at.strftime("%Y_%m_%d")
        dataset_version = f"{version_prefix}_{version_suffix}"
        version = DatasetVersion(
            dataset_version=dataset_version,
            created_at=created_at.isoformat(),
            row_count=int(len(frame)),
            feature_count=int(len(frame.columns)),
            label_type=label_type,
            lookahead_bars=int(lookahead_bars),
            timeframe=str(timeframe),
            source_hash=self._compute_source_hash(frame),
            feature_groups=list(feature_groups),
        )

        training_dir = self._resolve_layer("training")
        version_path = training_dir / f"ml_dataset_{dataset_version}.metadata.json"
        version_path.write_text(json.dumps(asdict(version), indent=2), encoding="utf-8")

        index = []
        if self.dataset_version_index.exists():
            try:
                loaded = json.loads(self.dataset_version_index.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    index = loaded
            except Exception:
                index = []
        index.append(asdict(version))
        self.dataset_version_index.write_text(json.dumps(index, indent=2), encoding="utf-8")
        return version
