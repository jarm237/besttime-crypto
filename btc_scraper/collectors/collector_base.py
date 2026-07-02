"""Common utilities for alternative-data collectors."""

from __future__ import annotations

import json
import os
import time
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
            json.dump(payload, handle, indent=2, ensure_ascii=False)
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


class CollectorScheduler:
    """Simple retry wrapper for collectors."""

    def __init__(self, retries: int = 2, delay_seconds: float = 1.0) -> None:
        self.retries = retries
        self.delay_seconds = delay_seconds

    def run(self, collector: CollectorBase, force: bool = False) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                return collector.collect(force=force)
            except Exception as exc:  # pragma: no cover - defensive path
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.delay_seconds)
                    continue
        raise CollectorError(f"{collector.name} failed after {self.retries + 1} attempts: {last_error}") from last_error
