"""Round-robin API-key rotation for Parse.bot collectors."""
from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta
from typing import Callable, Iterable


def load_parsebot_api_keys() -> list[str]:
    """Load numbered keys first and retain the legacy single-key fallback."""
    raw_keys = [
        *(os.getenv(f"PARSEBOT_API_KEY_{index}") for index in range(1, 6)),
        os.getenv("PARSEBOT_API_KEY"),
    ]
    return list(dict.fromkeys(key.strip() for key in raw_keys if key and key.strip()))


def is_parsebot_key_exhaustion_error(exc: Exception) -> bool:
    """Recognize the quota signals handled by the Gemini-style rotation."""
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    message = str(exc).upper()
    return status_code == 429 or "429" in message or "RESOURCE_EXHAUSTED" in message


class ParsebotKeyManager:
    """Thread-safe round-robin manager with Gemini-compatible 429 handling."""

    def __init__(
        self,
        keys: Iterable[str],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._keys = list(dict.fromkeys(key.strip() for key in keys if key.strip()))
        self._index = 0
        self._exhausted: set[str] = set()
        self._paused_until: datetime | None = None
        self._now = now or datetime.now
        self._lock = threading.Lock()

    @property
    def key_count(self) -> int:
        return len(self._keys)

    @property
    def available(self) -> bool:
        with self._lock:
            self._reset_after_pause_locked()
            return bool(self._keys) and len(self._exhausted) < len(self._keys)

    @property
    def pause_info(self) -> str:
        with self._lock:
            return self._paused_until.isoformat() if self._paused_until else ""

    def next_key(self) -> str | None:
        with self._lock:
            self._reset_after_pause_locked()
            if not self._keys or len(self._exhausted) >= len(self._keys):
                return None
            for _ in range(len(self._keys)):
                key = self._keys[self._index % len(self._keys)]
                self._index = (self._index + 1) % len(self._keys)
                if key not in self._exhausted:
                    return key
            return None

    def mark_exhausted(self, key: str) -> None:
        with self._lock:
            if key not in self._keys:
                return
            self._exhausted.add(key)
            if len(self._exhausted) >= len(self._keys):
                self._paused_until = (self._now() + timedelta(days=1)).replace(
                    hour=0,
                    minute=5,
                    second=0,
                    microsecond=0,
                )

    def reset_key(self, key: str) -> None:
        with self._lock:
            self._exhausted.discard(key)

    def _reset_after_pause_locked(self) -> None:
        if self._paused_until and self._now() >= self._paused_until:
            self._paused_until = None
            self._exhausted.clear()


_SHARED_MANAGER_LOCK = threading.Lock()
_SHARED_MANAGER: ParsebotKeyManager | None = None
_SHARED_KEYS: tuple[str, ...] = ()


def get_parsebot_key_manager(keys: Iterable[str] | None = None) -> ParsebotKeyManager:
    """Return one process-wide manager, rebuilding it when configured keys change."""
    global _SHARED_KEYS, _SHARED_MANAGER
    resolved = tuple(keys if keys is not None else load_parsebot_api_keys())
    with _SHARED_MANAGER_LOCK:
        if _SHARED_MANAGER is None or resolved != _SHARED_KEYS:
            _SHARED_KEYS = resolved
            _SHARED_MANAGER = ParsebotKeyManager(resolved)
        return _SHARED_MANAGER
