"""Run N1.5 COIN-M Quarterly Carry Contract & Execution Reality Check (Phases A, B, C, D, E, F)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neural_trading.n1_4.falsification import prepare_n1_4_features  # noqa: E402
from neural_trading.n1_5.coinm_simulator import (  # noqa: E402
    evaluate_n1_4_continuous_weights_under_n1_5_fees,
    run_capacity_and_margin_stress_suite,
    simulate_h1_coinm_reality_check,
)
from neural_trading.n1_5.contract_specs_and_data import (  # noqa: E402
    COINM_CONTRACT_SPECS,
    FEE_SCENARIOS,
    acquire_n1_5_mark_and_settlement_data,
)


def main() -> None:
    t0 = time.time()
    n1_4_data_dir = ROOT / "data" / "neural_n1_4"
    n1_4_manifest_path = ROOT / "research" / "neural_n1_4" / "manifests" / "n1_4_quarterly_delivery_manifest.json"
    n1_5_data_dir = ROOT / "data" / "neural_n1_5"
    out_dir = ROOT / "research" / "neural_n1_5"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[1/5] Phase D & B: Verifying unverified archive, fetching 1m Settlement Index TWAPs & 1h Mark Prices...")
    raw_panel, data_summary = acquire_n1_5_mark_and_settlement_data(
        n1_4_data_dir=n1_4_data_dir,
        n1_4_manifest_path=n1_4_manifest_path,
        n1_5_data_dir=n1_5_data_dir,
    )
    print(
        f"      Unverified archive recheck: all_verified={data_summary['unverified_archive_audit']['all_967_archives_verified_after_recheck']}; "
        f"1m settlement archives={data_summary['settlement_1m_index_archives_verified']}; "
        f"1h mark archives={data_summary['mark_price_1h_archives_verified']}"
    )

    print("[2/5] Preparing causal term-structure features on enriched COIN-M panel...")
    df = prepare_n1_4_features(raw_panel)

    print("[3/5] Phase A, B, E: Running physical COIN-M inverse contract simulator across all fee & execution scenarios...")
    modelled_runs: Dict[str, Any] = {}
    executable_runs: Dict[str, Any] = {}

    for scen_id, scen in FEE_SCENARIOS.items():
        res_mod = simulate_h1_coinm_reality_check(
            df,
            scenario=scen,
            execution_mode="MODELLED_CLOSE_T",
            initial_capital=20_000.0,
        )
        res_exec = simulate_h1_coinm_reality_check(
            df,
            scenario=scen,
            execution_mode="EXECUTABLE_TWAP_CONSTRAINED",
            initial_capital=20_000.0,
        )
        # Keep full ledgers on standard_retail_taker and verified_historical_fee_schedule, sample on others to keep JSON compact
        if scen_id not in ("standard_retail_taker", "verified_historical_fee_schedule"):
            res_mod["position_ledgers"] = res_mod["position_ledgers"][:10]
            res_exec["position_ledgers"] = res_exec["position_ledgers"][:10]
        modelled_runs[scen_id] = res_mod
        executable_runs[scen_id] = res_exec
        print(
            f"      {scen_id}: MODELLED_NET_CARRY=${res_mod['realized_net_pnl_usd']:+.2f} "
            f"({res_mod['net_return_on_committed_capital_pct']:+.2f}%), "
            f"EXECUTABLE_NET_CARRY=${res_exec['realized_net_pnl_usd']:+.2f} "
            f"({res_exec['net_return_on_committed_capital_pct']:+.2f}%)"
        )

    # Also test strict exclusion of SOLUSD_250926-1h-2025-08.zip
    res_excl_sol = simulate_h1_coinm_reality_check(
        df,
        scenario=FEE_SCENARIOS["standard_retail_taker"],
        execution_mode="EXECUTABLE_TWAP_CONSTRAINED",
        initial_capital=20_000.0,
        exclude_unverified_sol_2025_08=True,
    )
    res_excl_sol["position_ledgers"] = res_excl_sol["position_ledgers"][:5]

    print("[4/5] Evaluating N1.4 continuous daily-rebalanced weights under N1.5 fee schedules + Capacity/Margin Stress Suite...")
    n1_4_continuous_fee_audit = evaluate_n1_4_continuous_weights_under_n1_5_fees(df)
    stress_suite = run_capacity_and_margin_stress_suite(df)

    print("[5/5] Phase F: Determining final N1.5 research decision...")
    exec_retail_net = executable_runs["standard_retail_taker"]["realized_net_pnl_usd"]
    exec_stressed_net = executable_runs["stressed_execution_cost"]["realized_net_pnl_usd"]

    if exec_retail_net > 0.0 and exec_stressed_net > 0.0:
        final_disposition = "H1_EXPLORATORY_NET_CARRY_SUPPORTED"
    elif exec_retail_net <= 0.0:
        final_disposition = "H1_REJECTED_AFTER_REALISTIC_COSTS"
    else:
        final_disposition = "H1_EXPLORATORY_NET_CARRY_SUPPORTED"

    results = {
        "document_id": "NEURAL-N1-5-COINM-CARRY-REALITY-CHECK-2026-11-11",
        "elapsed_seconds": round(time.time() - t0, 2),
        "phase_a_contract_specifications": {
            sym: {
                "cm_pair": spec.cm_pair,
                "contract_size_usd": spec.contract_size_usd,
                "tier1_max_notional_usd": spec.tier1_max_notional_usd,
                "tier1_maint_margin_rate": spec.tier1_maint_margin_rate,
                "exchange_info_base_mmr": spec.exchange_info_base_mmr,
                "required_initial_margin_rate": spec.required_initial_margin_rate,
                "liquidation_fee_rate": spec.liquidation_fee_rate,
            }
            for sym, spec in COINM_CONTRACT_SPECS.items()
        },
        "phase_b_and_d_data_and_settlement_summary": data_summary,
        "phase_b_n1_4_continuous_weights_under_realistic_fees": n1_4_continuous_fee_audit,
        "phase_e_modelled_net_carry_by_fee_scenario": modelled_runs,
        "phase_e_executable_net_carry_by_fee_scenario": executable_runs,
        "phase_d_exclude_sol_250926_2025_08_sensitivity": {
            "realized_net_pnl_usd_with_sol_2025_08": executable_runs["standard_retail_taker"]["realized_net_pnl_usd"],
            "realized_net_pnl_usd_excluding_sol_2025_08": res_excl_sol["realized_net_pnl_usd"],
            "net_pnl_difference_usd": round(
                executable_runs["standard_retail_taker"]["realized_net_pnl_usd"] - res_excl_sol["realized_net_pnl_usd"], 4
            ),
        },
        "phase_c_and_d_capacity_and_margin_stress_suite": stress_suite,
        "phase_f_final_decision": {
            "final_h1_disposition": final_disposition,
            "execution_precision_status": "EXECUTION_APPROXIMATE",
            "historical_margin_replay_status": "H1_HISTORICAL_MARGIN_REPLAY = INSUFFICIENT_FOR_SUBMINUTE_WICKS_VERIFIED_ON_1H_MARK_HIGH",
            "neural_incremental_value_disposition": "NEURAL_INCREMENTAL_VALUE_NOT_SUPPORTED",
            "evaluation_2022_2025_status": "ADAPTIVE_DEVELOPMENT_NOT_INDEPENDENT_CONFIRMATION",
            "production_candidates": 0,
            "prospective_collector": "STOPPED",
            "real_trading": "DISABLED",
        },
    }

    out_path = out_dir / "n1_5_coinm_reality_check_results.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Done in {results['elapsed_seconds']}s -> {out_path}")


if __name__ == "__main__":
    main()
