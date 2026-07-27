import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from btc_scraper.ml_engine.causal_startup import CausalSystemInitializer, initialize_causal_system_at_startup


def test_causal_startup_initializes_runtime_components():
    initializer = CausalSystemInitializer()
    assert initializer.initialize({"graph_path": "data/causal_graph.json", "rules_path": "data/context_rules.json"}) is True

    components = initializer.get_components()
    assert components["simulator"] is not None
    assert components["predictor"] is not None
    assert components["anomaly_detector"] is not None
    assert components["consensus_engine"] is not None


def test_top_level_initializer_returns_runtime_components():
    components = initialize_causal_system_at_startup({
        "graph_path": "data/causal_graph.json",
        "rules_path": "data/context_rules.json",
    })

    assert components["simulator"] is not None
    assert components["predictor"] is not None
    assert components["anomaly_detector"] is not None
    assert components["consensus_engine"] is not None


def test_reasoning_engine_uses_configured_graph_path(tmp_path):
    graph_path = tmp_path / "causal_graph.json"
    shutil.copy("data/causal_graph.json", graph_path)

    initializer = CausalSystemInitializer()
    assert initializer._load_reasoning_engine(str(graph_path)) is True
    assert initializer.reasoning_engine.graph.graph_path == str(graph_path)
