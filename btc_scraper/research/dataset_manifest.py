"""
btc_scraper/research/dataset_manifest.py
Phase M2-D: Canonical Dataset Manifest Contract.

Defines immutable, content-hashed specifications for verified historical datasets.
Tracks partition SHA-256 digests, row counts, true exchange gaps vs late listing,
and strict candle timestamp semantics (Open Time vs Close Time).
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from btc_scraper.research.experiment_contract import freeze_nested, unfreeze_nested


TIMEFRAME_SECONDS = {
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}


@dataclass(frozen=True)
class PartitionMetadata:
    """Metadata and integrity hash for an individual historical partition file."""
    partition_key: str  # e.g. "BTC/15m/BTC_15m_2023-01.csv"
    symbol: str
    timeframe: str
    file_path: str
    sha256: str
    row_count: int
    warmup_rows: int
    start_time: str  # Earliest candle open time (ISO UTC)
    end_time: str    # Latest candle open time (ISO UTC)
    known_gap_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalDatasetManifest:
    """
    Immutable canonical manifest describing a verified historical market dataset.
    Content hash is derived deterministically from sorted partition hashes.
    """
    manifest_id: str
    dataset_version: str
    raw_source_identity: str
    market_type: str
    candle_timestamp_semantics: str  # "OPEN_TIME"
    symbols: Tuple[str, ...]
    timeframes: Tuple[str, ...]
    global_start_time: str
    global_end_time: str
    
    # Provenance and listing classifications
    symbol_listing_metadata: Mapping[str, Mapping[str, Any]] = field(default_factory=lambda: freeze_nested({}))
    known_exchange_gaps: Mapping[str, Sequence[Mapping[str, Any]]] = field(default_factory=lambda: freeze_nested({}))
    partitions: Mapping[str, PartitionMetadata] = field(default_factory=lambda: freeze_nested({}))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    manifest_content_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", tuple(self.symbols))
        object.__setattr__(self, "timeframes", tuple(self.timeframes))
        object.__setattr__(self, "symbol_listing_metadata", freeze_nested(self.symbol_listing_metadata))
        object.__setattr__(self, "known_exchange_gaps", freeze_nested(self.known_exchange_gaps))
        
        # Calculate deterministic content hash
        computed_hash = self.compute_manifest_hash()
        if self.manifest_content_hash and self.manifest_content_hash != computed_hash:
            raise ValueError(
                f"manifest_content_hash mismatch: expected {computed_hash}, got {self.manifest_content_hash}"
            )
        object.__setattr__(self, "manifest_content_hash", computed_hash)

    def compute_manifest_hash(self) -> str:
        """Computes deterministic SHA-256 of all partition digests and metadata."""
        clean = {
            "manifest_id": self.manifest_id,
            "dataset_version": self.dataset_version,
            "raw_source_identity": self.raw_source_identity,
            "market_type": self.market_type,
            "candle_timestamp_semantics": self.candle_timestamp_semantics,
            "symbols": sorted(list(self.symbols)),
            "timeframes": sorted(list(self.timeframes)),
            "global_start_time": self.global_start_time,
            "global_end_time": self.global_end_time,
            "partitions": {
                k: v.to_dict() if isinstance(v, PartitionMetadata) else v
                for k, v in sorted(self.partitions.items())
            },
            "known_exchange_gaps": unfreeze_nested(self.known_exchange_gaps),
            "symbol_listing_metadata": unfreeze_nested(self.symbol_listing_metadata),
        }
        raw_json = json.dumps(clean, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "dataset_version": self.dataset_version,
            "raw_source_identity": self.raw_source_identity,
            "market_type": self.market_type,
            "candle_timestamp_semantics": self.candle_timestamp_semantics,
            "symbols": list(self.symbols),
            "timeframes": list(self.timeframes),
            "global_start_time": self.global_start_time,
            "global_end_time": self.global_end_time,
            "symbol_listing_metadata": unfreeze_nested(self.symbol_listing_metadata),
            "known_exchange_gaps": unfreeze_nested(self.known_exchange_gaps),
            "partitions": {k: v.to_dict() for k, v in self.partitions.items()},
            "created_at": self.created_at,
            "manifest_content_hash": self.manifest_content_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CanonicalDatasetManifest":
        partitions_raw = data.get("partitions", {})
        parsed_partitions = {}
        for k, p in partitions_raw.items():
            if isinstance(p, PartitionMetadata):
                parsed_partitions[k] = p
            else:
                parsed_partitions[k] = PartitionMetadata(**p)

        return cls(
            manifest_id=str(data["manifest_id"]),
            dataset_version=str(data["dataset_version"]),
            raw_source_identity=str(data["raw_source_identity"]),
            market_type=str(data["market_type"]),
            candle_timestamp_semantics=str(data.get("candle_timestamp_semantics", "OPEN_TIME")),
            symbols=tuple(data["symbols"]),
            timeframes=tuple(data["timeframes"]),
            global_start_time=str(data["global_start_time"]),
            global_end_time=str(data["global_end_time"]),
            symbol_listing_metadata=data.get("symbol_listing_metadata", {}),
            known_exchange_gaps=data.get("known_exchange_gaps", {}),
            partitions=parsed_partitions,
            created_at=str(data.get("created_at", datetime.now(timezone.utc).isoformat())),
            manifest_content_hash=str(data.get("manifest_content_hash", "")),
        )

    def save(self, filepath: Path | str) -> None:
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, sort_keys=True, ensure_ascii=False)

    @classmethod
    def load(cls, filepath: Path | str) -> "CanonicalDatasetManifest":
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
