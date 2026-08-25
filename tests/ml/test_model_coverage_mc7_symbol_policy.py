"""Tests for MC7-B — RuntimeSymbolPolicy."""
import pytest

from btc_scraper.ml_engine.runtime_symbol_policy import (
    RuntimeSymbolPolicy,
    RuntimeSymbolNotAuthorized,
    runtime_symbol_policy,
)

EXPECTED_AUTHORIZED = sorted(["BTC", "ETH", "BNB", "DOGE", "IOTA", "NEAR", "SOL", "TRX", "ZEC"])
DISABLED_SYMBOLS = [
    "AEVO", "AR", "AVAX", "ENA", "SOPH", "TAO", "TRB", "TRUMP",
    "WLD", "XAUT", "XLM", "XPL", "XRP",
]


# ── Singleton ─────────────────────────────────────────────────────────────────

def test_singleton_is_runtime_symbol_policy() -> None:
    assert isinstance(runtime_symbol_policy, RuntimeSymbolPolicy)


def test_singleton_loads_from_registry() -> None:
    """The singleton must load from the MC6 sealed registry, not a fallback."""
    enabled = runtime_symbol_policy.enabled_symbols()
    assert len(enabled) == 9
    assert sorted(enabled) == EXPECTED_AUTHORIZED


# ── enabled_symbols ───────────────────────────────────────────────────────────

def test_enabled_symbols_is_tuple_of_9() -> None:
    enabled = runtime_symbol_policy.enabled_symbols()
    assert isinstance(enabled, tuple)
    assert len(enabled) == 9


def test_enabled_symbols_sorted() -> None:
    enabled = runtime_symbol_policy.enabled_symbols()
    assert list(enabled) == sorted(enabled)


def test_enabled_symbols_exact_set() -> None:
    assert sorted(runtime_symbol_policy.enabled_symbols()) == EXPECTED_AUTHORIZED


# ── is_enabled ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sym", EXPECTED_AUTHORIZED)
def test_is_enabled_true_for_authorized(sym: str) -> None:
    assert runtime_symbol_policy.is_enabled(sym) is True


@pytest.mark.parametrize("sym", DISABLED_SYMBOLS)
def test_is_enabled_false_for_disabled(sym: str) -> None:
    assert runtime_symbol_policy.is_enabled(sym) is False


def test_is_enabled_normalizes_lowercase() -> None:
    assert runtime_symbol_policy.is_enabled("btc") is True
    assert runtime_symbol_policy.is_enabled("xrp") is False


def test_is_enabled_normalizes_usdt_suffix() -> None:
    assert runtime_symbol_policy.is_enabled("BTCUSDT") is True
    assert runtime_symbol_policy.is_enabled("xrpusdt") is False


def test_is_enabled_false_for_empty() -> None:
    assert runtime_symbol_policy.is_enabled("") is False


def test_is_enabled_false_for_whitespace() -> None:
    assert runtime_symbol_policy.is_enabled("   ") is False


def test_is_enabled_false_for_unknown() -> None:
    assert runtime_symbol_policy.is_enabled("NOTACOIN") is False


# ── assert_enabled ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sym", EXPECTED_AUTHORIZED)
def test_assert_enabled_passes_for_authorized(sym: str) -> None:
    runtime_symbol_policy.assert_enabled(sym)  # must not raise


@pytest.mark.parametrize("sym", DISABLED_SYMBOLS)
def test_assert_enabled_raises_for_disabled(sym: str) -> None:
    with pytest.raises(RuntimeSymbolNotAuthorized) as exc_info:
        runtime_symbol_policy.assert_enabled(sym)
    assert sym in str(exc_info.value)


def test_assert_enabled_raises_for_unknown() -> None:
    with pytest.raises(RuntimeSymbolNotAuthorized):
        runtime_symbol_policy.assert_enabled("FAKECOIN")


def test_assert_enabled_raises_for_empty() -> None:
    with pytest.raises(RuntimeSymbolNotAuthorized):
        runtime_symbol_policy.assert_enabled("")


def test_assert_enabled_error_contains_symbol() -> None:
    with pytest.raises(RuntimeSymbolNotAuthorized) as exc_info:
        runtime_symbol_policy.assert_enabled("XRP")
    assert "XRP" in str(exc_info.value)


def test_runtime_symbol_not_authorized_is_runtime_error() -> None:
    exc = RuntimeSymbolNotAuthorized("XRP")
    assert isinstance(exc, RuntimeError)
    assert "XRP" in str(exc)
    assert exc.symbol == "XRP"


# ── Custom instance (isolated from global singleton) ─────────────────────────

def test_custom_instance_fallback_when_no_registry(tmp_path) -> None:
    """When registry file is absent, the policy falls back to the hardcoded 9."""
    policy = RuntimeSymbolPolicy(registry_path=tmp_path / "nonexistent.json")
    enabled = policy.enabled_symbols()
    assert len(enabled) == 9
    assert "BTC" in enabled


def test_custom_instance_reads_registry(tmp_path) -> None:
    import json
    registry = {
        "routes": [
            {"symbol": "BTC", "route_type": "legacy"},
            {"symbol": "ETH", "route_type": "legacy"},
        ]
    }
    registry_file = tmp_path / "registry.json"
    registry_file.write_text(json.dumps(registry), encoding="utf-8")
    policy = RuntimeSymbolPolicy(registry_path=registry_file)
    assert sorted(policy.enabled_symbols()) == ["BTC", "ETH"]
    assert policy.is_enabled("BTC") is True
    assert policy.is_enabled("SOL") is False
