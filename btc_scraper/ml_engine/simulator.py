"""CLI helpers for Phase 4.0 causal simulations."""

from __future__ import annotations

from btc_scraper.ml_engine.causal_simulator import CausalSimulator
from btc_scraper.ml_engine.scenario_interface import Intervention, InterventionType


def parse_intervention(raw: str) -> Intervention:
    """Parse CLI intervention strings such as DXY=+5% or VIX=-2."""
    raw = raw.strip()
    if "=" not in raw:
        raise ValueError("Intervention must look like NODE=value")

    node, value_part = raw.split("=", 1)
    node = node.strip()
    value_part = value_part.strip()

    if value_part.endswith("%"):
        numeric = float(value_part[:-1])
        value = numeric
    else:
        value = float(value_part)

    return Intervention(
        type=InterventionType.CUSTOM,
        target_node=node,
        value=value,
        description="Intervention from CLI",
    )


def run_cli_simulation(state, raw_intervention: str):
    simulator = CausalSimulator(graph_path="data/causal_graph.json")
    intervention = parse_intervention(raw_intervention)
    return simulator.simulate_intervention(state, intervention)
