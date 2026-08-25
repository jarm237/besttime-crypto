"""Fail-closed inference router backed by the MC6 immutable registry.

Resolves a symbol to its exact qualified inference artifacts.  Raises
``InferenceSymbolUnsupported`` for any symbol not present in the registry
— there is **no** silent fallback, no default model, no ``models.get(sym, btc)``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class InferenceSymbolUnsupported(RuntimeError):
    """Raised when a symbol has no routable inference route."""

    def __init__(self, symbol: str, reason: str = "unknown") -> None:
        self.symbol = symbol
        self.reason = reason
        super().__init__(f"inference_symbol_unsupported:{symbol}:{reason}")


class InferenceRouteIntegrityError(RuntimeError):
    """Raised when a route's on-disk artifacts fail integrity checks."""

    def __init__(self, symbol: str, detail: str) -> None:
        self.symbol = symbol
        self.detail = detail
        super().__init__(f"inference_route_integrity_error:{symbol}:{detail}")


@dataclass(frozen=True)
class InferenceRoute:
    """Resolved inference route for a single symbol."""

    symbol: str
    route_type: str  # LEGACY | MC5_QUALIFIED
    route_version: str
    model_artifact_path: Path | None
    model_sha256: str | None
    calibrator_artifact_path: Path | None
    calibrator_sha256: str | None
    feature_schema: list[str]
    feature_schema_version: str
    qualification_verdict: str


class InferenceRouter:
    """Registry-backed fail-closed inference router.

    Parameters
    ----------
    registry_path : Path
        Absolute path to ``model_coverage_mc6_inference_registry.json``.
    repo_root : Path
        Repository root used to resolve relative artifact paths.
    """

    def __init__(self, registry_path: Path, repo_root: Path) -> None:
        self._repo_root = repo_root
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        self._routes: dict[str, dict[str, Any]] = {}
        for entry in data.get("routes", []):
            self._routes[entry["symbol"]] = entry

    # ── public API ───────────────────────────────────────────────────────

    def resolve(self, symbol: str) -> InferenceRoute:
        """Return the *exact* route for *symbol*, or raise."""
        entry = self._routes.get(symbol)
        if entry is None:
            raise InferenceSymbolUnsupported(symbol, reason="no_registry_entry")

        model_path: Path | None = None
        cal_path: Path | None = None

        if entry.get("model_artifact_path"):
            model_path = self._repo_root / entry["model_artifact_path"]
        if entry.get("calibrator_artifact_path"):
            cal_path = self._repo_root / entry["calibrator_artifact_path"]

        return InferenceRoute(
            symbol=entry["symbol"],
            route_type=entry["route_type"],
            route_version=entry["route_version"],
            model_artifact_path=model_path,
            model_sha256=entry.get("model_sha256"),
            calibrator_artifact_path=cal_path,
            calibrator_sha256=entry.get("calibrator_sha256"),
            feature_schema=entry["feature_schema"],
            feature_schema_version=entry["feature_schema_version"],
            qualification_verdict=entry["qualification_verdict"],
        )

    def validate_route(self, route: InferenceRoute) -> None:
        """Verify that the resolved route's on-disk artifacts are intact.

        Raises ``InferenceRouteIntegrityError`` on any failure.
        """
        if route.route_type == "LEGACY":
            # Legacy routes do not have per-symbol artifacts managed by MC6
            return

        if route.model_artifact_path is None:
            raise InferenceRouteIntegrityError(route.symbol, "model_path_is_none")
        if not route.model_artifact_path.exists():
            raise InferenceRouteIntegrityError(
                route.symbol,
                f"model_artifact_missing:{route.model_artifact_path}",
            )
        if route.model_sha256:
            actual = hashlib.sha256(route.model_artifact_path.read_bytes()).hexdigest()
            if actual != route.model_sha256:
                raise InferenceRouteIntegrityError(
                    route.symbol,
                    f"model_sha_mismatch:expected={route.model_sha256},actual={actual}",
                )

        if route.calibrator_artifact_path is None:
            raise InferenceRouteIntegrityError(route.symbol, "calibrator_path_is_none")
        if not route.calibrator_artifact_path.exists():
            raise InferenceRouteIntegrityError(
                route.symbol,
                f"calibrator_missing:{route.calibrator_artifact_path}",
            )
        if route.calibrator_sha256:
            actual = hashlib.sha256(route.calibrator_artifact_path.read_bytes()).hexdigest()
            if actual != route.calibrator_sha256:
                raise InferenceRouteIntegrityError(
                    route.symbol,
                    f"calibrator_sha_mismatch:expected={route.calibrator_sha256},actual={actual}",
                )

    def validate_schema(self, route: InferenceRoute, expected_features: list[str] | None = None) -> None:
        """Verify the route's feature schema matches expectations."""
        expected = expected_features or ["return_8", "return_32", "return_72", "abs_move_72"]
        if route.feature_schema != expected:
            raise InferenceRouteIntegrityError(
                route.symbol,
                f"schema_mismatch:expected={expected},actual={route.feature_schema}",
            )

    @property
    def routable_symbols(self) -> list[str]:
        return sorted(self._routes.keys())

    def __contains__(self, symbol: str) -> bool:
        return symbol in self._routes
