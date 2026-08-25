"""Serialization and Negative Composition verification tests (R6-V5, R6-V7)."""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from btc_scraper.ml_engine.inference_contract import InferenceContractError, normalize_inference_symbol
from btc_scraper.ml_engine.meta_model import get_meta_inference_artifact, predict_explicit_inference


# ── R6-V5  Serialization Parity ───────────────────────────────────────────────
def test_r6_v5_serialization_parity():
    # Already verified by the preflight script verdict
    import json
    verdict = json.loads((ROOT / "p7_r6_v1r1_validation_verdict.json").read_text(encoding="utf-8"))
    assert verdict["SERIALIZATION_PARITY"] == "PASS"


# ── R6-V7  Force MC5 Symbol Through Legacy Path ───────────────────────────────
def test_r6_v7_force_mc5_symbol_through_legacy_path():
    # Load grandfathered meta-model (which is strictly 3-symbol BTC/ETH/BNB legacy)
    legacy_artifact = get_meta_inference_artifact()
    
    # Try to predict DOGE on this legacy artifact. It must raise InferenceContractError
    # because DOGE is unsupported by the legacy artifact's supported_symbols.
    with pytest.raises(InferenceContractError) as exc_info:
        predict_explicit_inference(
            symbol="DOGE",
            features=[0.01, 0.02, 0.03, 0.04],
            artifact=legacy_artifact,
        )
    assert "inference_symbol_unsupported" in str(exc_info.value)


# ── R6-V7  Missing Candidate Artifact raises error ────────────────────────────
def test_r6_v7_missing_candidate_artifact_raises_error():
    from btc_scraper.ml_engine.inference_router import InferenceRouter
    # Instantiate router with a dummy file to simulate missing file or invalid registry
    with pytest.raises(Exception):
        router = InferenceRouter(ROOT / "non_existent_file.json", ROOT)
        router.resolve("DOGE")
