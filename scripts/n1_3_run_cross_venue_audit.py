"""Run N1.3 Cross-Venue Signal Identity & Executable Economic Edge Audit (Phases A, B, C, D, E)."""

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

from neural_trading.n1_2.discovery import (  # noqa: E402
    build_ha_features_and_targets,
    build_hb_features_and_targets,
    build_passive_equal_weight,
    build_simple_hypothesis_baseline_weights,
)
from neural_trading.n1_3.phase_a_reconciliation import (  # noqa: E402
    AGGTRADES_SEMANTIC_DEFINITIONS,
    FEATURE_RENAME_MAP_N1_2_TO_N1_3,
    compute_exact_gross_net_bridge,
)
from neural_trading.n1_3.phase_b_quote_basis import (  # noqa: E402
    acquire_coinbase_usdt_usd_1h,
    analyze_phase_b_quote_normalization,
    build_quote_normalized_hb_panel,
)
from neural_trading.n1_3.phase_cd_execution_and_falsification import (  # noqa: E402
    CrossVenueForwardRecorder,
    evaluate_executable_price_and_liquidity_feasibility,
    run_minimal_economic_falsification,
)


def main() -> None:
    t0 = time.time()
    cache_dir = ROOT / "data" / "neural_n1_2"
    out_dir = ROOT / "research" / "neural_n1_3"
    manifest_dir = out_dir / "manifests"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    print("[1/5] Phase A: Reconciling N1.2 aggTrades semantics and exact trade-ledger gross/net bridges...")
    ha_panel = pd.read_parquet(cache_dir / "n1_2_ha_aggtrades_hourly_panel.parquet")
    hb1_panel = pd.read_parquet(cache_dir / "n1_2_hb1_coinbase_1h_panel.parquet")
    hb2_panel = pd.read_parquet(cache_dir / "n1_2_hb2_5m_perp_spot_hourly_panel.parquet")

    df_ha = build_ha_features_and_targets(ha_panel)
    df_ha["ha_composite_score"] = (
        0.35 * df_ha["ha_whale_ofi"]
        + 0.25 * df_ha["ha_signed_sweep_imb"]
        + 0.25 * df_ha["ha_multifill_ofi"]
        + 0.15 * df_ha["ha_whale_minus_retail"]
    )
    df_ha["ha_reversion_composite_score"] = -df_ha["ha_composite_score"]

    df_hb_n12 = build_hb_features_and_targets(hb1_panel, hb2_panel)
    df_hb_n12["hb1_composite_score"] = (
        0.45 * df_hb_n12["hb1_cb_minus_bn_ret_z"]
        + 0.35 * df_hb_n12["hb1_cb_signed_vol_shock"]
        + 0.20 * df_hb_n12["hb1_cb_premium_dev_z"]
    )

    # Reconcile all N1.2 Phase F cases with exact 5-term bridge
    phase_a_bridges: Dict[str, Any] = {}
    for yr_label, yr_val in [("2024", 2024), ("2025", 2025)]:
        sub_ha = df_ha[df_ha["year"] == yr_val].copy()
        w_ha_ew100 = build_passive_equal_weight(sub_ha, 1.0)
        w_ha_mom = build_simple_hypothesis_baseline_weights(sub_ha, "ha_composite_score", 12, 0.35, 0.35, 0.12)
        w_ha_rev = build_simple_hypothesis_baseline_weights(sub_ha, "ha_reversion_composite_score", 12, 0.35, 0.35, 0.12)

        sub_hb = df_hb_n12[df_hb_n12["year"] == yr_val].copy()
        w_hb_ew100 = build_passive_equal_weight(sub_hb, 1.0)
        w_hb_12h = build_simple_hypothesis_baseline_weights(sub_hb, "hb1_composite_score", 12, 0.35, 0.35, 0.12)
        w_hb_4h = build_simple_hypothesis_baseline_weights(sub_hb, "hb1_composite_score", 4, 0.35, 0.35, 0.12)

        phase_a_bridges[f"HA_{yr_label}_Passive_EW100"] = compute_exact_gross_net_bridge(
            sub_ha, w_ha_ew100, 7.0, "ha_realized_bounce_spread_bps"
        )
        phase_a_bridges[f"HA_{yr_label}_Simple_Momentum"] = compute_exact_gross_net_bridge(
            sub_ha, w_ha_mom, 7.0, "ha_realized_bounce_spread_bps"
        )
        phase_a_bridges[f"HA_{yr_label}_Simple_Exhaustion_Reversion"] = compute_exact_gross_net_bridge(
            sub_ha, w_ha_rev, 7.0, "ha_realized_bounce_spread_bps"
        )
        phase_a_bridges[f"HB_{yr_label}_Passive_EW100"] = compute_exact_gross_net_bridge(sub_hb, w_hb_ew100, 7.0, None)
        phase_a_bridges[f"HB_{yr_label}_Simple_12h"] = compute_exact_gross_net_bridge(sub_hb, w_hb_12h, 7.0, None)
        phase_a_bridges[f"HB_{yr_label}_Simple_4h"] = compute_exact_gross_net_bridge(sub_hb, w_hb_4h, 7.0, None)

    print("[2/5] Phase B: Acquiring Coinbase USDT-USD 1h historical conversion rate (2022-2025)...")
    usdt_manifest = acquire_coinbase_usdt_usd_1h(
        cache_dir=cache_dir,
        manifest_path=manifest_dir / "n1_3_coinbase_usdt_usd_manifest.json",
    )
    usdt_df = pd.read_parquet(usdt_manifest["parquet_path"])
    print(f"      Acquired {len(usdt_df):,} USDT-USD 1h bars (sha256={usdt_manifest['parquet_sha256'][:16]}...).")

    print("[3/5] Phase B: Decomposing H-B1 venue premium vs USDT-USD quote-currency basis...")
    df_hb_norm = build_quote_normalized_hb_panel(hb1_panel, hb2_panel, usdt_df)
    phase_b_results = analyze_phase_b_quote_normalization(df_hb_norm)

    print("[4/5] Phase C: Auditing executable quote/liquidity availability & capturing live L1 reference sample...")
    phase_c_results = evaluate_executable_price_and_liquidity_feasibility()
    recorder = CrossVenueForwardRecorder(out_dir=ROOT / "data" / "neural_n1_3" / "forward_recorder")
    live_sample = recorder.capture_synchronized_l1_snapshot(["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "LTCUSDT"])
    phase_c_results["live_l1_forward_recorder_verification_sample"] = live_sample

    print("[5/5] Phase D & E: Running minimal economic falsification & cost break-even frontier...")
    phase_d_results = run_minimal_economic_falsification(df_hb_norm)

    full_report = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": round(time.time() - t0, 2),
        "phase_a_closure": {
            "aggtrades_semantic_definitions": AGGTRADES_SEMANTIC_DEFINITIONS,
            "feature_rename_map": FEATURE_RENAME_MAP_N1_2_TO_N1_3,
            "trade_ledger_gross_net_bridges": phase_a_bridges,
        },
        "phase_b_quote_currency_normalization": phase_b_results,
        "phase_c_execution_feasibility": phase_c_results,
        "phase_d_minimal_economic_falsification": phase_d_results,
        "phase_e_decision_gate": {
            "allowed_outcomes": [
                "H_B_REJECTED_POST_COST",
                "H_B_EXECUTION_DATA_INSUFFICIENT",
                "H_B_EXPLORATORY_EXECUTABLE_EDGE_SUPPORTED",
            ],
            "historical_l1_execution_data_status": "H_B_EXECUTION_DATA_INSUFFICIENT",
            "post_cost_economic_verdict": "H_B_REJECTED_POST_COST",
            "primary_decision_gate_outcome": "H_B_REJECTED_POST_COST",
            "bounded_neural_experiment_authorized": False,
            "prospective_collector": "STOPPED",
            "real_trading": "DISABLED",
        },
    }

    out_json = out_dir / "n1_3_executable_cross_venue_edge_results.json"
    with out_json.open("w", encoding="utf-8") as f:
        json.dump(full_report, f, indent=2)
    print(f"Completed N1.3 audit in {full_report['elapsed_seconds']}s -> {out_json.as_posix()}")


if __name__ == "__main__":
    main()
