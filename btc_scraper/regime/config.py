"""Single source of truth for regime configuration and runtime containment."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from btc_scraper.core.paths import REPO_ROOT, build_logs_path, runtime_environment


REGIME_CONFIG_ENV = "REGIME_CONFIG_PATH"
CANONICAL_CONFIG_PATH = Path(__file__).with_name("regime_config.json")
VALID_ENFORCEMENT_MODES = {"observe", "shadow_effect", "enforce"}


class RegimeConfigError(ValueError):
    pass


def resolve_regime_config_path() -> Path:
    raw = os.getenv(REGIME_CONFIG_ENV)
    if not raw:
        return CANONICAL_CONFIG_PATH
    path = Path(raw).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


def _require_positive(config: Mapping[str, Any], key: str) -> float:
    try:
        value = float(config[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise RegimeConfigError(f"{key} must be numeric") from exc
    if value <= 0:
        raise RegimeConfigError(f"{key} must be > 0")
    return value


def validate_regime_config(config: Mapping[str, Any]) -> dict[str, Any]:
    if str(config.get("schema_version") or "") != "2.0":
        raise RegimeConfigError("schema_version must be '2.0'")
    if str(config.get("taxonomy_version") or "") != "2.0":
        raise RegimeConfigError("taxonomy_version must be '2.0'")
    if not str(config.get("detector_version") or ""):
        raise RegimeConfigError("detector_version is required")

    adx_trend = _require_positive(config, "adx_threshold")
    adx_strong = _require_positive(config, "strong_adx_threshold")
    compression = _require_positive(config, "atr_pct_compression_max")
    mean_reversion = _require_positive(config, "atr_pct_mean_reversion_min")
    breakout = _require_positive(config, "atr_pct_breakout_min")
    extreme = _require_positive(config, "atr_pct_extreme_min")
    max_atr = float(config.get("atr_pct_max_valid", 25.0))

    if adx_strong <= adx_trend:
        raise RegimeConfigError("strong_adx_threshold must be > adx_threshold")
    if mean_reversion <= compression:
        raise RegimeConfigError("atr_pct_mean_reversion_min must be > compression threshold")
    if breakout <= compression:
        raise RegimeConfigError("atr_pct_breakout_min must be > compression threshold")
    if extreme <= breakout:
        raise RegimeConfigError("atr_pct_extreme_min must be > breakout threshold")
    if extreme > max_atr or max_atr <= 0:
        raise RegimeConfigError("ATR percent thresholds exceed configured maximum")

    minimum_bars = int(config.get("minimum_bars", 200))
    if minimum_bars < 2:
        raise RegimeConfigError("minimum_bars must be >= 2")
    minimum_duration_bars = int(config.get("minimum_duration_bars", 3))
    if minimum_duration_bars < 1:
        raise RegimeConfigError("minimum_duration_bars must be >= 1")
    validated = dict(config)
    validated["minimum_bars"] = minimum_bars
    validated["minimum_duration_bars"] = minimum_duration_bars
    return validated


def load_regime_config(*, path: Path | None = None, allow_test_defaults: bool = False) -> dict[str, Any]:
    resolved = path or resolve_regime_config_path()
    if not resolved.exists():
        if allow_test_defaults and runtime_environment() == "test":
            return validate_regime_config(default_regime_config())
        raise RegimeConfigError(f"REGIME_CONFIG_MISSING: {resolved}")
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RegimeConfigError(f"REGIME_CONFIG_INVALID_JSON: {resolved}: {exc}") from exc
    return validate_regime_config(raw)


def load_runtime_regime_config() -> dict[str, Any]:
    """Fail closed in enforcement, degrade to neutral-safe defaults otherwise."""
    try:
        return load_regime_config()
    except RegimeConfigError as exc:
        if regime_enforcement_mode() == "enforce":
            raise
        fallback = validate_regime_config(default_regime_config())
        fallback["_config_health"] = "DEGRADED_CONFIG_UNAVAILABLE"
        fallback["_config_error"] = str(exc)
        fallback["_config_source"] = "SAFE_DEFAULTS_NON_EXECUTING"
        return fallback


def canonical_config_bytes(config: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(config), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_regime_config_sha256(config: Mapping[str, Any] | None = None, *, path: Path | None = None) -> str:
    loaded = config if config is not None else load_regime_config(path=path)
    return hashlib.sha256(canonical_config_bytes(loaded)).hexdigest()


def atomic_write_regime_config(config: Mapping[str, Any], *, path: Path | None = None) -> tuple[Path, str]:
    validated = validate_regime_config(config)
    target = path or resolve_regime_config_path()
    previous_hash = None
    if target.exists():
        try:
            previous_hash = compute_regime_config_sha256(path=target)
        except Exception:
            previous_hash = "INVALID_PREVIOUS_CONFIG"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(validated, indent=2, ensure_ascii=False) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
        try:
            dir_fd = os.open(target.parent, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (AttributeError, OSError):
            pass
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    new_hash = compute_regime_config_sha256(validated)
    try:
        audit_path = (
            build_logs_path("regime_config_audit.jsonl")
            if target.resolve() == resolve_regime_config_path().resolve()
            else target.parent / "regime_config_audit.jsonl"
        )
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "event": "REGIME_CONFIG_UPDATED",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "path": str(target),
                "previous_sha256": previous_hash,
                "config_sha256": new_hash,
                "schema_version": validated["schema_version"],
                "taxonomy_version": validated["taxonomy_version"],
                "detector_version": validated["detector_version"],
                "restart_required": True,
            }, sort_keys=True) + "\n")
    except Exception:
        # The config update is already durable. Audit failure is exposed by the
        # caller through the returned hash and operational log health.
        pass
    return target, new_hash


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def regime_enforcement_mode() -> str:
    mode = os.getenv("REGIME_RUNTIME_ENFORCEMENT_MODE", "observe").strip().lower()
    return mode if mode in VALID_ENFORCEMENT_MODES else "observe"


def _single_approved_effect_enabled(requested_name: str) -> bool:
    if regime_enforcement_mode() != "enforce" or not _env_flag("REGIME_PROMOTION_APPROVED"):
        return False
    requested = [
        name
        for name in (
            "REGIME_DECISION_WEIGHT_ENABLED",
            "REGIME_POSITION_SIZING_ENABLED",
            "REGIME_TP_SL_ENABLED",
        )
        if _env_flag(name)
    ]
    return requested == [requested_name]


def regime_decision_weight_enabled() -> bool:
    return _single_approved_effect_enabled("REGIME_DECISION_WEIGHT_ENABLED")


def regime_position_sizing_enabled() -> bool:
    return _single_approved_effect_enabled("REGIME_POSITION_SIZING_ENABLED")


def regime_tp_sl_enabled() -> bool:
    return _single_approved_effect_enabled("REGIME_TP_SL_ENABLED")


def regime_effect_metadata(effect_enabled: bool) -> dict[str, Any]:
    mode = regime_enforcement_mode()
    if effect_enabled:
        reason = None
    elif mode == "observe":
        reason = "REGIME_OBSERVE_ONLY"
    elif mode == "shadow_effect":
        reason = "REGIME_SHADOW_NON_EXECUTING"
    else:
        reason = "REGIME_EFFECT_FLAG_DISABLED"
    return {
        "regime_effect_mode": mode,
        "regime_effect_enabled": bool(effect_enabled),
        "regime_effect_reason": reason,
    }


def default_regime_config() -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "taxonomy_version": "2.0",
        "detector_version": "2.0.0",
        "mapping_version": "2.0",
        "adx_threshold": 25.0,
        "strong_adx_threshold": 35.0,
        "atr_pct_threshold": 0.65,
        "atr_pct_compression_max": 0.35,
        "atr_pct_mean_reversion_min": 0.55,
        "atr_pct_breakout_min": 0.65,
        "atr_pct_extreme_min": 1.2,
        "atr_pct_max_valid": 25.0,
        "minimum_bars": 200,
        "minimum_duration_bars": 3,
        "confidence": {"base": 0.35, "max": 0.98},
        "position_size_multipliers": {"default": {}, "per_strategy": {}},
        "kelly": {"max_fraction": 0.7, "decay_rate": 0.5, "min_fraction": 0.0},
        "position_sizing": {
            "method": "hybrid",
            "target_std_dev_pct": 2.0,
            "target_atr_pct": 1.0,
            "min_vol_mult": 0.25,
            "max_vol_mult": 1.5,
        },
    }
