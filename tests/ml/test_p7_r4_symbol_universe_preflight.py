from __future__ import annotations

from pathlib import Path

from scripts import p7_activation_preflight as preflight


def test_symbol_universe_gate_passes_when_model_route_covers_runtime(monkeypatch):
    def fake_run(_root: Path, _code: str):
        return {
            "returncode": 0,
            "stdout": "{}",
            "stderr": "",
            "json": {
                "runtime_symbols": ["BTC", "ETH"],
                "artifact_supported_symbols": ["BTC", "ETH"],
                "model_route_supported_symbols": ["BTC", "ETH"],
                "unsupported_symbols": [],
            },
        }

    monkeypatch.setattr(preflight, "run_python_with_pinned_import", fake_run)

    result = preflight.symbol_universe_compatibility(Path("pinned"))

    assert result["status"] == "PASS"
    assert result["verdict"] == "PASS"
    assert result["unsupported_symbols"] == []


def test_symbol_universe_gate_blocks_model_route_gap(monkeypatch):
    def fake_run(_root: Path, _code: str):
        return {
            "returncode": 0,
            "stdout": "{}",
            "stderr": "",
            "json": {
                "runtime_symbols": ["BTC", "ETH", "SOL"],
                "artifact_supported_symbols": ["BTC", "ETH", "SOL"],
                "model_route_supported_symbols": ["BTC", "ETH"],
                "unsupported_symbols": ["SOL"],
            },
        }

    monkeypatch.setattr(preflight, "run_python_with_pinned_import", fake_run)

    result = preflight.symbol_universe_compatibility(Path("pinned"))

    assert result["status"] == "FAIL"
    assert result["verdict"] == "BLOCKED_INFERENCE_SYMBOL_UNSUPPORTED"
    assert result["unsupported_symbols"] == ["SOL"]
