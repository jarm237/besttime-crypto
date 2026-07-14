"""Register the canonical model artifacts once without overwriting artifacts."""
from __future__ import annotations

from btc_scraper.ml_engine.artifact_resolver import ROOT, get_artifact_resolver
from btc_scraper.ml_engine.model_registry import ModelRegistry


def main() -> None:
    resolver, registry = get_artifact_resolver(), ModelRegistry()
    records = [
        ("adaptive_rf", "2026.07.07.1", "production"),
        ("meta_model", "v3.1", "production"),
        ("rl_exit", "2026.06.28.215012", "shadow"),
        ("meta_model_v3", "v3-candidate", "candidate"),
        ("slippage_model_v2", "unavailable", "disabled"),
    ]
    for name, version, status in records:
        if registry.active(name, ("candidate", "shadow", "production", "disabled", "archive", "rejected")):
            continue
        if name in {"meta_model_v3", "slippage_model_v2"}:
            registry.register({"model_name": name, "version": version, "status": status,
                               "reason": "candidate_blocked_pending_leakage_audit" if name == "meta_model_v3" else "disabled_missing_artifact"})
            continue
        artifact = resolver.resolve(name, require_metadata=(name == "rl_exit"))
        if not artifact.healthy:
            raise RuntimeError(f"cannot register unhealthy {name}: {artifact.reason}")
        registry.register({"model_name": name, "version": version, "status": status,
                           "artifact_path": str(artifact.path.relative_to(ROOT)),
                           "sha256": artifact.sha256, "schema_version": artifact.schema_version,
                           "metrics": artifact.metadata or {}})


if __name__ == "__main__":
    main()
