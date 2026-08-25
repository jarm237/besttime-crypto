"""Tests for MC7-F — Disabled Symbol Re-Enable Protection.

Verifies:
1. Each of the 13 disabled symbols, if configured via BTC_ANALYSIS_UNIVERSE, causes
   RUNTIME_UNIVERSE_NOT_AUTHORIZED:<symbol> immediately.
2. Multiple disabled symbols in one env config all raise.
3. Unknown/non-canonical symbols raise.
4. Lowercase and mixed-case disabled symbols raise.
5. predict_meta_confidence raises RuntimeSymbolNotAuthorized before model load.
6. predict_once raises RuntimeSymbolNotAuthorized before artifact resolution.
"""
import pytest

from btc_scraper.ml_engine.runtime_symbol_policy import (
    RuntimeSymbolNotAuthorized,
    runtime_symbol_policy,
)
from btc_scraper.core.config import get_analysis_universe

DISABLED_SYMBOLS = [
    "AEVO", "AR", "AVAX", "ENA", "SOPH", "TAO", "TRB", "TRUMP",
    "WLD", "XAUT", "XLM", "XPL", "XRP",
]
AUTHORIZED_SYMBOLS = ["BTC", "ETH", "BNB", "DOGE", "IOTA", "NEAR", "SOL", "TRX", "ZEC"]


# ── Single disabled symbol via env ────────────────────────────────────────────

@pytest.mark.parametrize("sym", DISABLED_SYMBOLS)
def test_single_disabled_symbol_via_env_raises(sym: str, monkeypatch) -> None:
    """Each disabled symbol, configured via env, raises RUNTIME_UNIVERSE_NOT_AUTHORIZED."""
    monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", sym)
    with pytest.raises(ValueError, match=f"RUNTIME_UNIVERSE_NOT_AUTHORIZED:{sym}"):
        get_analysis_universe()


# ── Mixed authorized + disabled via env ───────────────────────────────────────

@pytest.mark.parametrize("disabled_sym", DISABLED_SYMBOLS)
def test_authorized_plus_disabled_via_env_raises(disabled_sym: str, monkeypatch) -> None:
    """Mixing an authorized symbol with a disabled one still raises."""
    monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", f"BTC,{disabled_sym}")
    with pytest.raises(ValueError, match="RUNTIME_UNIVERSE_NOT_AUTHORIZED"):
        get_analysis_universe()


# ── Multiple disabled symbols via env ─────────────────────────────────────────

def test_multiple_disabled_symbols_via_env_raises(monkeypatch) -> None:
    monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", "XRP,WLD,AEVO")
    with pytest.raises(ValueError, match="RUNTIME_UNIVERSE_NOT_AUTHORIZED"):
        get_analysis_universe()


# ── Unknown symbol via env ────────────────────────────────────────────────────

def test_unknown_symbol_via_env_raises_unsupported(monkeypatch) -> None:
    """Unknown symbols are rejected by parse_runtime_symbols before reaching the authorized check."""
    monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", "BTC,NOTACOIN")
    with pytest.raises(ValueError, match="unsupported"):
        get_analysis_universe()


# ── RuntimeSymbolPolicy: lowercase disabled symbols ───────────────────────────

@pytest.mark.parametrize("sym", DISABLED_SYMBOLS)
def test_policy_rejects_lowercase_disabled(sym: str) -> None:
    with pytest.raises(RuntimeSymbolNotAuthorized):
        runtime_symbol_policy.assert_enabled(sym.lower())


# ── RuntimeSymbolPolicy: USDT-suffixed disabled symbols ──────────────────────

@pytest.mark.parametrize("sym", DISABLED_SYMBOLS)
def test_policy_rejects_usdt_disabled(sym: str) -> None:
    with pytest.raises(RuntimeSymbolNotAuthorized):
        runtime_symbol_policy.assert_enabled(sym + "USDT")


# ── predict_meta_confidence: disabled symbol raises before model load ─────────

@pytest.mark.parametrize("sym", ["XRP", "WLD", "AVAX"])
def test_predict_meta_confidence_raises_before_model_load(sym: str) -> None:
    """RuntimeSymbolNotAuthorized must be raised before any artifact is accessed."""
    from btc_scraper.ml_engine.meta_model import predict_meta_confidence

    model_loaded = []

    import btc_scraper.ml_engine.meta_model as mm_mod

    original = mm_mod.__dict__.get("get_meta_inference_artifact")
    try:
        def tracking_loader():
            model_loaded.append(sym)
            raise AssertionError("Model loader called — policy guard did not fire first")

        mm_mod.get_meta_inference_artifact = tracking_loader

        with pytest.raises(RuntimeSymbolNotAuthorized):
            predict_meta_confidence({}, symbol=sym)
    finally:
        if original is not None:
            mm_mod.get_meta_inference_artifact = original

    assert not model_loaded, f"Model was loaded before policy guard for {sym}"


# ── predict_once: disabled symbol raises before artifact resolution ───────────

@pytest.mark.parametrize("sym", ["XRP", "WLD"])
def test_predict_once_raises_before_artifact_resolution(sym: str, monkeypatch) -> None:
    """RuntimeSymbolNotAuthorized must be raised in predict_once before normalize_inference_symbol."""
    from btc_scraper.ml_engine.inference_coordinator import InferenceCoordinator

    normalize_called = []

    from btc_scraper.ml_engine import inference_coordinator as ic_mod

    original_normalize = ic_mod.normalize_inference_symbol
    try:
        def tracking_normalize(*args, **kwargs):
            normalize_called.append(args)
            return original_normalize(*args, **kwargs)

        ic_mod.normalize_inference_symbol = tracking_normalize

        with pytest.raises(RuntimeSymbolNotAuthorized):
            InferenceCoordinator().predict_once(
                {"observed_at": "2026-07-30T08:00:00+00:00", "signal": "BUY"},
                symbol=sym,
            )
    finally:
        ic_mod.normalize_inference_symbol = original_normalize

    assert not normalize_called, (
        f"normalize_inference_symbol was called before policy guard for {sym}. "
        "Policy guard must be the very first operation."
    )


# ── Re-enable protection: env reset must restore authorized universe ──────────

def test_resetting_env_restores_authorized_universe(monkeypatch) -> None:
    monkeypatch.setenv("BTC_ANALYSIS_UNIVERSE", "BTC,XRP")
    with pytest.raises(ValueError, match="RUNTIME_UNIVERSE_NOT_AUTHORIZED:XRP"):
        get_analysis_universe()

    monkeypatch.delenv("BTC_ANALYSIS_UNIVERSE")
    universe = get_analysis_universe()
    assert len(universe) == 9
    assert "XRP" not in universe
