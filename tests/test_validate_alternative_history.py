import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "validate_alternative_history.py"
    spec = importlib.util.spec_from_file_location("validate_alternative_history", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generate_artifacts_writes_research_only_contract(tmp_path):
    module = _load_module()
    output_dir = tmp_path / "ahdv"
    anchor = datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc)

    paths = module.generate_artifacts(output_dir, anchor)

    assert set(paths) == {
        "source_inventory",
        "validation_manifest",
        "probe_results",
        "coverage_report",
        "fidelity_matrix",
        "final_report",
    }
    for path in paths.values():
        assert path.exists()

    inventory = json.loads(paths["source_inventory"].read_text(encoding="utf-8"))
    by_source = {source["source_id"]: source for source in inventory}
    assert by_source["binance_funding"]["production_features"] == ["funding_rate"]
    assert by_source["binance_open_interest"]["production_features"] == ["open_interest"]
    assert by_source["binance_orderbook"]["production_features"] == ["orderbook_imbalance"]
    assert by_source["defillama_stablecoin"]["production_features"] == [
        "stablecoin_supply",
        "stablecoin_supply_total",
    ]
    assert "NO_RUNTIME_CONTROL_ACTION" in by_source["binance_funding"]["validation_boundary"]
    assert by_source["alternative_me"]["collector"] == "AlternativeMeCollector"

    assert all(source["initial_fidelity"] == "UNCLASSIFIED" for source in inventory)
    assert all(source["initial_replay_decision"] == "PENDING_VALIDATION" for source in inventory)

    manifest = json.loads(paths["validation_manifest"].read_text(encoding="utf-8"))
    assert manifest["default_network_policy"] == "disabled"
    assert manifest["gate_sequence"][0]["gate"] == "G0"
    gate_g2 = next(g for g in manifest["gate_sequence"] if g["gate"] == "G2")
    assert gate_g2["hard_rule"] == "available_at <= replay_clock"
    assert [item["id"] for item in manifest["probe_timestamps"]] == [
        "T1_7D",
        "T2_30D",
        "T3_90D",
        "T4_180D",
        "T5_365D",
        "E1_POST_ETF_LAUNCH",
        "E2_HALVING_WINDOW",
        "E3_2024_Q4_BREAKOUT",
    ]


def test_probe_results_are_not_marked_as_evidence(tmp_path):
    module = _load_module()
    paths = module.generate_artifacts(
        tmp_path / "ahdv",
        datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc),
    )

    rows = [
        json.loads(line)
        for line in paths["probe_results"].read_text(encoding="utf-8").splitlines()
    ]
    assert rows
    assert {row["probe_status"] for row in rows} == {"NOT_PROBED"}
    assert {row["availability_gate"] for row in rows} == {"AMBIGUOUS"}
    assert all(row["temporal_correctness"]["future_information_count"] is None for row in rows)

    matrix = json.loads(paths["fidelity_matrix"].read_text(encoding="utf-8"))
    expected_fidelity_matrix = {
        "alternative_me": ("H1_HISTORICAL", "PRODUCTION_FALLBACK", "NOT_PROVEN", "VERIFIED"),
        "fred": ("UNCLASSIFIED", "PRODUCTION_FALLBACK", "UNKNOWN", "VERIFIED"),
        "binance_funding": ("H1_HISTORICAL", "PRODUCTION_FALLBACK", "NOT_PROVEN", "VERIFIED"),
        "binance_open_interest": ("UNCLASSIFIED", "PENDING_VALIDATION", "NOT_EVALUATED", "NOT_VERIFIED"),
        "binance_orderbook": ("UNCLASSIFIED", "PENDING_VALIDATION", "NOT_EVALUATED", "NOT_VERIFIED"),
        "defillama_stablecoin": ("H1_HISTORICAL", "PRODUCTION_FALLBACK", "NOT_PROVEN", "VERIFIED"),
        "defillama_tvl": ("H1_HISTORICAL", "PRODUCTION_FALLBACK", "NOT_PROVEN", "VERIFIED"),
        "deribit_dvol": (
            "H2_AS_OF_RECONSTRUCTABLE",
            "USE_RECONSTRUCTED_CLOSED_OBSERVATION",
            "RECONSTRUCTABLE_WITH_CLOSED_CANDLE_ONLY",
            "VERIFIED",
        ),
        "deribit_iv_skew": ("UNCLASSIFIED", "PENDING_VALIDATION", "NOT_EVALUATED", "NOT_VERIFIED"),
        "etf": ("UNCLASSIFIED", "PENDING_VALIDATION", "NOT_EVALUATED", "NOT_VERIFIED"),
        "google_trends": ("UNCLASSIFIED", "PENDING_VALIDATION", "NOT_EVALUATED", "NOT_VERIFIED"),
        "reddit": ("UNCLASSIFIED", "PENDING_VALIDATION", "NOT_EVALUATED", "NOT_VERIFIED"),
    }
    assert {row["source"] for row in matrix} == set(expected_fidelity_matrix)
    for row in matrix:
        sid = row["source"]
        expected = expected_fidelity_matrix[sid]
        actual = (
            row["Fidelity"],
            row["Replay decision"],
            row["PIT"],
            row["Fallback"],
        )
        assert actual == expected, f"Fidelity contract mismatch for matrix source {sid}"
