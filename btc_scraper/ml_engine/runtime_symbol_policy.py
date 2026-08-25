"""MC7-B — Runtime Symbol Policy.

Single source of truth for which symbols are authorized for inference dispatch.
Truth is read from the MC6 sealed inference registry (model_coverage_mc6_inference_registry.json).
No manual symbol list duplication.
"""
from __future__ import annotations

import json
from pathlib import Path


class RuntimeSymbolNotAuthorized(RuntimeError):
    """Raised when a symbol that is not in the authorized runtime universe
    is presented to any inference entry point.

    This must be raised *before* any model is loaded or inference dispatched.
    """

    def __init__(self, symbol: str) -> None:
        super().__init__(f"RuntimeSymbolNotAuthorized:{symbol}")
        self.symbol = symbol


_FALLBACK_AUTHORIZED = frozenset(
    {"BTC", "ETH", "BNB", "DOGE", "IOTA", "NEAR", "SOL", "TRX", "ZEC"}
)


def _load_authorized_from_registry(registry_path: Path) -> frozenset[str]:
    """Load authorized symbols from the MC6 sealed inference registry."""
    if not registry_path.exists():
        return _FALLBACK_AUTHORIZED
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        symbols = frozenset(str(r["symbol"]).strip().upper() for r in data.get("routes", []))
        return symbols if symbols else _FALLBACK_AUTHORIZED
    except Exception:
        return _FALLBACK_AUTHORIZED


class RuntimeSymbolPolicy:
    """Authoritative policy for which symbols may enter inference dispatch.

    Loaded lazily from the MC6 sealed inference registry.  All callers must
    use the module-level singleton ``runtime_symbol_policy`` rather than
    constructing their own instance.
    """

    def __init__(
        self,
        registry_path: Path | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self._repo_root = repo_root or Path(__file__).resolve().parents[2]
        self._registry_path = (
            registry_path
            or self._repo_root / "model_coverage_mc6_inference_registry.json"
        )
        self._authorized: frozenset[str] = _load_authorized_from_registry(
            self._registry_path
        )

    # ── public API ───────────────────────────────────────────────────────────

    def enabled_symbols(self) -> tuple[str, ...]:
        """Return the ordered tuple of authorized inference symbols."""
        return tuple(sorted(self._authorized))

    def is_enabled(self, symbol: str) -> bool:
        """Return True iff *symbol* is in the authorized runtime universe."""
        return self._normalize(symbol) in self._authorized

    def assert_enabled(self, symbol: str) -> None:
        """Raise :exc:`RuntimeSymbolNotAuthorized` if *symbol* is not authorized.

        This must be called as the **first** operation in any inference entry
        point, before model loading, artifact resolution, or feature extraction.
        """
        norm = self._normalize(symbol)
        if norm not in self._authorized:
            raise RuntimeSymbolNotAuthorized(symbol)

    # ── internal ─────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(symbol: str) -> str:
        return (
            str(symbol).strip().upper().replace("/", "").replace("-", "").removesuffix("USDT")
        )


# Module-level singleton — import and use this directly.
runtime_symbol_policy: RuntimeSymbolPolicy = RuntimeSymbolPolicy()
