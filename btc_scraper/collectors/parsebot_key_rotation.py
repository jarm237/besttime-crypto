"""Round-robin credential-pair rotation for Parse.bot collectors."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterable


@dataclass(frozen=True)
class ParsebotCredential:
    """A Parse.bot API key and the scraper base URL issued with that key."""

    api_key: str
    base_url: str


def load_parsebot_api_keys() -> list[str]:
    """Load numbered keys first and retain the legacy single-key fallback."""
    raw_keys = [
        *(os.getenv(f"PARSEBOT_API_KEY_{index}") for index in range(1, 6)),
        os.getenv("PARSEBOT_API_KEY"),
    ]
    return list(dict.fromkeys(key.strip() for key in raw_keys if key and key.strip()))


def load_parsebot_credentials() -> list[ParsebotCredential]:
    """Load key/base-URL pairs, retaining the legacy URL as a fallback.

    Parse.bot scraper URLs are subscription-specific. Numbered credentials use
    ``PARSEBOT_API_KEY_N`` with ``PARSEBOT_BASE_URL_N``. For backward
    compatibility, a missing numbered URL falls back to
    ``PARSEBOT_BASE_URL``. The legacy key always pairs with the legacy URL.
    """
    fallback_url = (os.getenv("PARSEBOT_BASE_URL") or "").strip().rstrip("/")
    raw_pairs = [
        (
            os.getenv(f"PARSEBOT_API_KEY_{index}"),
            os.getenv(f"PARSEBOT_BASE_URL_{index}") or fallback_url,
        )
        for index in range(1, 6)
    ]
    raw_pairs.append((os.getenv("PARSEBOT_API_KEY"), fallback_url))

    credentials: list[ParsebotCredential] = []
    seen_keys: set[str] = set()
    for raw_key, raw_url in raw_pairs:
        api_key = (raw_key or "").strip()
        base_url = (raw_url or "").strip().rstrip("/")
        if not api_key or not base_url or api_key in seen_keys:
            continue
        seen_keys.add(api_key)
        credentials.append(ParsebotCredential(api_key=api_key, base_url=base_url))
    return credentials


def is_parsebot_key_exhaustion_error(exc: Exception) -> bool:
    """Recognize the quota signals handled by the Gemini-style rotation."""
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    message = str(exc).upper()
    return status_code == 429 or "429" in message or "RESOURCE_EXHAUSTED" in message


class ParsebotKeyManager:
    """Thread-safe credential-pair manager with Gemini-compatible 429 handling."""

    def __init__(
        self,
        keys: Iterable[str | ParsebotCredential],
        *,
        base_url: str = "",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        normalized: list[ParsebotCredential] = []
        seen_keys: set[str] = set()
        fallback_url = base_url.strip().rstrip("/")
        for item in keys:
            if isinstance(item, ParsebotCredential):
                credential = ParsebotCredential(
                    api_key=item.api_key.strip(),
                    base_url=item.base_url.strip().rstrip("/"),
                )
            else:
                credential = ParsebotCredential(
                    api_key=item.strip(),
                    base_url=fallback_url,
                )
            if not credential.api_key or credential.api_key in seen_keys:
                continue
            seen_keys.add(credential.api_key)
            normalized.append(credential)

        self._credentials = normalized
        self._keys = [credential.api_key for credential in normalized]
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
        credential = self.next_credential()
        return credential.api_key if credential is not None else None

    def next_credential(self) -> ParsebotCredential | None:
        with self._lock:
            self._reset_after_pause_locked()
            if not self._credentials or len(self._exhausted) >= len(self._credentials):
                return None
            for _ in range(len(self._credentials)):
                credential = self._credentials[self._index % len(self._credentials)]
                self._index = (self._index + 1) % len(self._credentials)
                if credential.api_key not in self._exhausted:
                    return credential
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
_SHARED_CREDENTIALS: tuple[ParsebotCredential, ...] = ()


def get_parsebot_key_manager(
    keys: Iterable[str | ParsebotCredential] | None = None,
    *,
    base_url: str = "",
) -> ParsebotKeyManager:
    """Return one process-wide manager, rebuilding when key/URL pairs change."""
    global _SHARED_CREDENTIALS, _SHARED_MANAGER
    if keys is None:
        resolved = tuple(load_parsebot_credentials())
    else:
        temporary = ParsebotKeyManager(keys, base_url=base_url)
        resolved = tuple(temporary._credentials)
    with _SHARED_MANAGER_LOCK:
        if _SHARED_MANAGER is None or resolved != _SHARED_CREDENTIALS:
            _SHARED_CREDENTIALS = resolved
            _SHARED_MANAGER = ParsebotKeyManager(resolved)
        return _SHARED_MANAGER
