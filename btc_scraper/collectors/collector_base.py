"""Common utilities for alternative-data collectors."""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional


class CollectorError(RuntimeError):
    """Raised when a collector cannot produce a valid payload."""


class CollectorBase(ABC):
    """Base class for collectors that produce JSON payloads."""

    name = "collector"

    def __init__(self, output_path: Optional[str | os.PathLike[str]] = None, retries: int = 2, delay_seconds: float = 1.0) -> None:
        self.output_path = Path(output_path) if output_path is not None else None
        self.retries = max(0, retries)
        self.delay_seconds = max(0.0, delay_seconds)

    @abstractmethod
    def collect(self, force: bool = False) -> Dict[str, Any]:
        """Collect and persist data for the collector."""

    def _write_json(self, payload: Dict[str, Any], path: Optional[str | os.PathLike[str]] = None) -> Path:
        target = Path(path or self.output_path)
        if target is None:
            raise CollectorError("An output path is required for persistence")
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(_json_safe(payload), handle, indent=2, ensure_ascii=False, allow_nan=False)
        return target

    def _read_json(self, path: Optional[str | os.PathLike[str]] = None) -> Optional[Dict[str, Any]]:
        target = Path(path or self.output_path)
        if target is None or not target.exists():
            return None
        try:
            with open(target, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
        except Exception:
            return None
        return None


def _json_safe(value: Any) -> Any:
    """Make JSON persistence conform to the project missing-data standard."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


class CollectorScheduler:
    """Retry wrapper with exponential backoff, circuit breaking and cache fallback."""

    def __init__(self, retries: int = 2, delay_seconds: float = 1.0, max_delay_seconds: float = 30.0, circuit_failure_threshold: int = 3) -> None:
        self.retries = retries
        self.delay_seconds = delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.circuit_failure_threshold = max(1, circuit_failure_threshold)
        self._failures: Dict[str, int] = {}
        self._cache: Dict[str, Dict[str, Any]] = {}

    def run(self, collector: CollectorBase, force: bool = False) -> Dict[str, Any]:
        name = collector.name
        if self._failures.get(name, 0) >= self.circuit_failure_threshold and name in self._cache:
            return self._stale_cache(name, "circuit_open")
        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                payload = collector.collect(force=force)
                if not isinstance(payload, dict):
                    raise CollectorError("collector returned a non-object payload")
                if payload.get("status") == "error":
                    raise CollectorError(str(payload.get("reason", "collector reported error")))
                self._failures[name] = 0
                self._cache[name] = dict(payload)
                return payload
            except Exception as exc:  # pragma: no cover - defensive path
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(self.max_delay_seconds, self.delay_seconds * (2 ** attempt)))
                    continue
        self._failures[name] = self._failures.get(name, 0) + 1
        if name in self._cache:
            return self._stale_cache(name, repr(last_error))
        raise CollectorError(f"{collector.name} failed after {self.retries + 1} attempts: {last_error}") from last_error

    def _stale_cache(self, name: str, reason: str) -> Dict[str, Any]:
        cached = dict(self._cache[name])
        observed_at = cached.get("timestamp")
        age_seconds = None
        try:
            observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            age_seconds = max(0.0, (datetime.now(timezone.utc) - observed).total_seconds())
        except (TypeError, ValueError):
            pass
        cached.update({"status": "stale", "source": "cache", "reason": reason,
                       "is_stale": True, "age_seconds": age_seconds})
        return cached
