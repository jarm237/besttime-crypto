"""Shared, fail-closed per-symbol S3 threshold contract."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


S3_THRESHOLD_CONTRACT_VERSION = "s3-per-symbol-v1"
S3_PROBABILITY_SEMANTICS = "P(win_given_proposed_trade)"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_S3_THRESHOLD_CONTRACT_PATH = ROOT / "config/s3_thresholds_v1.json"


class S3ThresholdContractError(ValueError):
    """Raised when the canonical S3 threshold contract is unavailable or invalid."""


@dataclass(frozen=True)
class S3ThresholdResult:
    symbol: str
    meta_probability: float | None
    s3_threshold: float | None
    s3_pass: bool
    threshold_contract_version: str
    threshold_contract_sha256: str | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_s3_symbol(symbol: Any) -> str:
    normalized = str(symbol or "").strip().upper()
    normalized = normalized.replace("/", "").replace("-", "").replace("_", "")
    return normalized.removesuffix("USDT")


@lru_cache(maxsize=1)
def load_s3_threshold_contract(
    path: Path = DEFAULT_S3_THRESHOLD_CONTRACT_PATH,
) -> Mapping[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S3ThresholdContractError("s3 threshold contract is unreadable") from exc

    required = {
        "schema_version",
        "threshold_contract_version",
        "probability_field",
        "probability_semantics",
        "comparison",
        "missing_policy",
        "thresholds",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise S3ThresholdContractError(
            f"s3 threshold contract missing fields:{','.join(missing)}"
        )
    if payload["threshold_contract_version"] != S3_THRESHOLD_CONTRACT_VERSION:
        raise S3ThresholdContractError("unsupported s3 threshold contract version")
    if payload["probability_semantics"] != S3_PROBABILITY_SEMANTICS:
        raise S3ThresholdContractError("unsupported s3 probability semantics")
    if payload["comparison"] != ">=" or payload["missing_policy"] != "FAIL_CLOSED":
        raise S3ThresholdContractError("s3 contract must use >= and FAIL_CLOSED")
    raw_thresholds = payload["thresholds"]
    if not isinstance(raw_thresholds, dict) or not raw_thresholds:
        raise S3ThresholdContractError("s3 threshold mapping is empty")

    thresholds: dict[str, float] = {}
    for raw_symbol, raw_threshold in raw_thresholds.items():
        symbol = normalize_s3_symbol(raw_symbol)
        try:
            threshold = float(raw_threshold)
        except (TypeError, ValueError) as exc:
            raise S3ThresholdContractError(
                f"invalid s3 threshold:{symbol or 'UNKNOWN'}"
            ) from exc
        if not symbol or not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            raise S3ThresholdContractError(
                f"invalid s3 threshold:{symbol or 'UNKNOWN'}"
            )
        thresholds[symbol] = threshold

    frozen = dict(payload)
    frozen["thresholds"] = MappingProxyType(thresholds)
    return MappingProxyType(frozen)


@lru_cache(maxsize=1)
def s3_threshold_contract_sha256(
    path: Path = DEFAULT_S3_THRESHOLD_CONTRACT_PATH,
) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evaluate_s3_threshold(symbol: Any, meta_probability: Any) -> S3ThresholdResult:
    normalized_symbol = normalize_s3_symbol(symbol)
    try:
        contract = load_s3_threshold_contract()
        contract_sha256 = s3_threshold_contract_sha256()
    except (OSError, S3ThresholdContractError) as exc:
        return S3ThresholdResult(
            symbol=normalized_symbol or "UNKNOWN",
            meta_probability=None,
            s3_threshold=None,
            s3_pass=False,
            threshold_contract_version=S3_THRESHOLD_CONTRACT_VERSION,
            threshold_contract_sha256=None,
            error=f"s3_contract_unavailable:{type(exc).__name__}",
        )

    threshold = contract["thresholds"].get(normalized_symbol)
    if threshold is None:
        return S3ThresholdResult(
            symbol=normalized_symbol or "UNKNOWN",
            meta_probability=None,
            s3_threshold=None,
            s3_pass=False,
            threshold_contract_version=str(contract["threshold_contract_version"]),
            threshold_contract_sha256=contract_sha256,
            error=f"s3_threshold_unresolved:{normalized_symbol or 'UNKNOWN'}",
        )
    try:
        probability = float(meta_probability)
    except (TypeError, ValueError):
        probability = math.nan
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        return S3ThresholdResult(
            symbol=normalized_symbol,
            meta_probability=None,
            s3_threshold=float(threshold),
            s3_pass=False,
            threshold_contract_version=str(contract["threshold_contract_version"]),
            threshold_contract_sha256=contract_sha256,
            error=f"s3_probability_invalid:{normalized_symbol}",
        )
    return S3ThresholdResult(
        symbol=normalized_symbol,
        meta_probability=probability,
        s3_threshold=float(threshold),
        s3_pass=probability >= float(threshold),
        threshold_contract_version=str(contract["threshold_contract_version"]),
        threshold_contract_sha256=contract_sha256,
    )
