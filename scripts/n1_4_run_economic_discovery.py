r"""Run N1.4 Greenfield Economic-First Alpha Discovery (Phases D, E, F, G)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neural_trading.n1_4.acquisition import acquire_n1_4_datasets_and_build_panel  # noqa: E402
from neural_trading.n1_4.falsification import (  # noqa: E402
    prepare_n1_4_features,
    run_phase_e_economic_falsification,
)
from neural_trading.n1_4.neural_pilot import run_phase_f_bounded_neural_evaluation  # noqa: E402


def main() -> None:
    t0 = time.time()
    data_dir = ROOT / "data" / "neural_n1_4"
    n1_2_cache_dir = ROOT / "data" / "neural_n1_2"
    out_dir = ROOT / "research" / "neural_n1_4"
    manifest_dir = out_dir / "manifests"
    data_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    print("[1/4] Phase D: Acquiring & verifying COIN-M and USD-M Quarterly Delivery Futures (2022-2025)...")
    manifest = acquire_n1_4_datasets_and_build_panel(
        data_dir=data_dir,
        n1_2_cache_dir=n1_2_cache_dir,
        manifest_dir=manifest_dir,
    )
    print(
        f"      Verified {manifest['verified_delivery_archives_count']} delivery archives "
        f"({manifest['checksum_verified_delivery_archives_count']} checksum-verified), "
        f"{manifest['total_delivery_hourly_bars']} hourly delivery bars."
    )

    panel_path = Path(manifest["panel_parquet_path"])
    raw_panel = pd.read_parquet(panel_path)

    print("[2/4] Phase E: Preparing causal features and running economic falsification for H-1 and H-2...")
    df = prepare_n1_4_features(raw_panel)
    phase_e = run_phase_e_economic_falsification(df)

    h1_disc_net = phase_e["h1_quarterly_delivery_carry"]["discovery_2022_2023"]["simple_carry_by_latency"]["close_t"]["net_pnl_usd"]
    h1_val_net = phase_e["h1_quarterly_delivery_carry"]["validation_2024"]["simple_carry_by_latency"]["close_t"]["net_pnl_usd"]
    h1_dev_net = phase_e["h1_quarterly_delivery_carry"]["adaptive_dev_2025"]["simple_carry_by_latency"]["close_t"]["net_pnl_usd"]
    h2_disc_net = phase_e["h2_multiday_deleveraging_liquidity"]["discovery_2022_2023"]["simple_multiday_liquidity_baseline"]["net_pnl_usd"]
    h2_dev_net = phase_e["h2_multiday_deleveraging_liquidity"]["adaptive_dev_2025"]["simple_multiday_liquidity_baseline"]["net_pnl_usd"]

    print(
        f"      H-1 Simple Carry Net PnL: 2022-2023=${h1_disc_net:+.2f}, 2024=${h1_val_net:+.2f}, Dev 2025=${h1_dev_net:+.2f}"
    )
    print(f"      H-2 Multi-Day Spot Liquidity Net PnL: 2022-2023=${h2_disc_net:+.2f}, Dev 2025=${h2_dev_net:+.2f}")

    h1_economically_feasible = bool(h1_disc_net > 0.0 and h1_val_net > 0.0)
    h2_economically_feasible = bool(h2_disc_net > 0.0 and h2_dev_net > 0.0)

    phase_f = None
    if h1_economically_feasible:
        print("[3/4] Phase F: H-1 passed Phase E economic falsification -> Running single bounded TermStructureCarryPolicy pilot...")
        phase_f = run_phase_f_bounded_neural_evaluation(df)
    else:
        print("[3/4] Phase F: Skipped (no hypothesis passed Phase E economic falsification).")

    print("[4/4] Phase G: Determining final research decision state...")
    nn_inc_24 = (
        phase_f["validation_2024_train_2022_2023"]["neural_term_structure_policy"]["net_excess_vs_simple_carry_baseline_usd"]
        if phase_f
        else 0.0
    )
    nn_inc_25 = (
        phase_f["adaptive_dev_2025_train_2022_2024"]["neural_term_structure_policy"]["net_excess_vs_simple_carry_baseline_usd"]
        if phase_f
        else 0.0
    )

    if h1_economically_feasible and h1_dev_net > 0.0:
        primary_state = "EXPLORATORY_NET_EDGE_SUPPORTED"
        neural_state = (
            "NEURAL_INCREMENTAL_VALUE_EXPLORATORY"
            if (nn_inc_24 > 0.0 and nn_inc_25 > 0.0)
            else "NEURAL_INCREMENTAL_VALUE_NOT_SUPPORTED"
        )
    elif h1_economically_feasible:
        primary_state = "EXECUTABLE_GROSS_EDGE_SUPPORTED"
        neural_state = "NEURAL_INCREMENTAL_VALUE_NOT_SUPPORTED"
    else:
        primary_state = "NO_FEASIBLE_ALPHA_MECHANISM_IDENTIFIED"
        neural_state = "NEURAL_INCREMENTAL_VALUE_NOT_SUPPORTED"

    results: Dict[str, Any] = {
        "document_id": "NEURAL-N1-4-ECONOMIC-DISCOVERY-RESULTS-2026-11-11",
        "elapsed_seconds": round(time.time() - t0, 2),
        "phase_a_n1_3_closure": {
            "H_B_POST_COST_DISPOSITION": "REJECTED",
            "H_B_HISTORICAL_L1_EVIDENCE": "INSUFFICIENT",
            "H_B_NEURAL_TRAINING": "NOT_JUSTIFIED",
            "N1_N1_3_PRODUCTION_CANDIDATES": 0,
            "PROSPECTIVE_COLLECTOR": "STOPPED",
            "REAL_TRADING": "DISABLED",
        },
        "phase_d_data_summary": {
            k: v for k, v in manifest.items() if k != "delivery_archive_records"
        },
        "phase_e_economic_falsification": {
            "h1_economically_feasible_for_phase_f": h1_economically_feasible,
            "h2_economically_feasible_for_phase_f": h2_economically_feasible,
            "results": phase_e,
        },
        "phase_f_bounded_neural_pilot": phase_f,
        "phase_g_research_decision": {
            "h1_quarterly_delivery_carry_disposition": primary_state,
            "h2_multiday_spot_liquidity_disposition": (
                "EXPLORATORY_NET_EDGE_SUPPORTED" if h2_economically_feasible else "REJECTED_AT_PHASE_E_FALSIFICATION"
            ),
            "neural_incremental_value_disposition": neural_state,
            "neural_net_excess_vs_simple_2024_usd": nn_inc_24,
            "neural_net_excess_vs_simple_2025_usd": nn_inc_25,
            "evaluation_2025_status": "ADAPTIVE_DEVELOPMENT_NOT_INDEPENDENT_CONFIRMATION",
            "prospective_collector": "STOPPED",
            "real_trading": "DISABLED",
        },
    }

    res_path = out_dir / "n1_4_economic_discovery_results.json"
    res_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Done in {results['elapsed_seconds']}s -> {res_path}")


if __name__ == "__main__":
    main()
