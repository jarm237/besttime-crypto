"""Execute N1.2 Phase D (Economic Information Discovery) and Phase E/F (Economic Feasibility Experiment)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neural_trading.n1_2.discovery import (  # noqa: E402
    build_cash_weights,
    build_ha_features_and_targets,
    build_hb_features_and_targets,
    build_passive_equal_weight,
    build_simple_hypothesis_baseline_weights,
    evaluate_feature_suite_phase_d,
    simulate_spot_long_only_portfolio,
)
from neural_trading.n1_2.experiment import (  # noqa: E402
    build_phase_f_10_metric_scorecard,
    train_and_evaluate_neural_pilot,
)


def _run_hypothesis_phase_ef(
    df: pd.DataFrame,
    hypothesis_id: str,
    feature_cols: list[str],
    composite_col: str,
    extra_half_spread_col: str | None = None,
    rebalance_every_h: int = 12,
) -> Dict[str, Any]:
    """Evaluate 4-way comparison (Cash, Passive EW, Simple Baseline, Neural Pilot) on Discovery (2022-2024) and OOS (2025)."""
    results_by_split: Dict[str, Any] = {}
    splits = [
        ("discovery_cv_2024", [2022, 2023], [2024]),
        ("oos_2025", [2022, 2023, 2024], [2025]),
    ]

    for split_name, train_yrs, eval_yrs in splits:
        df_eval = df[df["year"].isin(eval_yrs)].copy().reset_index(drop=True)

        # 1. Cash
        w_cash = build_cash_weights(df_eval)
        # 2. Passive 100% Equal-Weight
        w_ew100 = build_passive_equal_weight(df_eval, exposure=1.0)
        # 3. Simple Hypothesis-Specific Baseline
        w_simple = build_simple_hypothesis_baseline_weights(
            df_eval,
            score_col=composite_col,
            rebalance_every_h=rebalance_every_h,
            max_weight_per_asset=0.35,
            threshold_z=0.35,
            hysteresis_l1=0.12,
        )
        # 4. Bounded Neural Pilot (MicrostructureDislocationPolicy)
        w_neural, s_neural, train_meta = train_and_evaluate_neural_pilot(
            df=df,
            feature_cols=feature_cols,
            train_years=train_yrs,
            eval_years=eval_yrs,
            rebalance_every_h=rebalance_every_h,
            cost_per_leg_bps=7.0,
            extra_half_spread_col=extra_half_spread_col,
            epochs=25,
            seed=42,
        )

        # Compute exposure-matched passive benchmarks for both Simple and Neural
        mean_exp_simple = float(w_simple.sum(axis=1).mean())
        mean_exp_neural = float(w_neural.sum(axis=1).mean())
        w_ew_match_simple = build_passive_equal_weight(df_eval, exposure=max(0.01, mean_exp_simple))
        w_ew_match_neural = build_passive_equal_weight(df_eval, exposure=max(0.01, mean_exp_neural))

        sim_ew100 = simulate_spot_long_only_portfolio(
            df_eval, w_ew100, cost_per_leg_bps=7.0, extra_half_spread_col=extra_half_spread_col
        )
        sim_ew_match_simple = simulate_spot_long_only_portfolio(
            df_eval, w_ew_match_simple, cost_per_leg_bps=7.0, extra_half_spread_col=extra_half_spread_col
        )
        sim_ew_match_neural = simulate_spot_long_only_portfolio(
            df_eval, w_ew_match_neural, cost_per_leg_bps=7.0, extra_half_spread_col=extra_half_spread_col
        )

        results_by_split[split_name] = {
            "train_years": train_yrs,
            "eval_years": eval_yrs,
            "cash": build_phase_f_10_metric_scorecard(
                df_eval, w_cash, None, sim_ew100, cost_per_leg_bps=7.0, extra_half_spread_col=extra_half_spread_col
            ),
            "passive_equal_weight_100pct": build_phase_f_10_metric_scorecard(
                df_eval, w_ew100, None, sim_ew100, cost_per_leg_bps=7.0, extra_half_spread_col=extra_half_spread_col
            ),
            "passive_exposure_matched_to_simple": build_phase_f_10_metric_scorecard(
                df_eval,
                w_ew_match_simple,
                None,
                sim_ew_match_simple,
                cost_per_leg_bps=7.0,
                extra_half_spread_col=extra_half_spread_col,
            ),
            "passive_exposure_matched_to_neural": build_phase_f_10_metric_scorecard(
                df_eval,
                w_ew_match_neural,
                None,
                sim_ew_match_neural,
                cost_per_leg_bps=7.0,
                extra_half_spread_col=extra_half_spread_col,
            ),
            "simple_hypothesis_baseline": build_phase_f_10_metric_scorecard(
                df_eval,
                w_simple,
                composite_col,
                sim_ew_match_simple,
                cost_per_leg_bps=7.0,
                extra_half_spread_col=extra_half_spread_col,
            ),
            "neural_policy_pilot": build_phase_f_10_metric_scorecard(
                df_eval,
                w_neural,
                s_neural,
                sim_ew_match_neural,
                cost_per_leg_bps=7.0,
                extra_half_spread_col=extra_half_spread_col,
            ),
        }

    return {
        "hypothesis_id": hypothesis_id,
        "feature_cols": feature_cols,
        "composite_col": composite_col,
        "extra_half_spread_col": extra_half_spread_col,
        "splits": results_by_split,
    }


def main() -> None:
    t0 = time.time()
    cache_dir = ROOT / "data" / "neural_n1_2"
    out_dir = ROOT / "research" / "neural_n1_2"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("[1/4] Loading verified Phase C panels...")
    ha_panel = pd.read_parquet(cache_dir / "n1_2_ha_aggtrades_hourly_panel.parquet")
    hb1_panel = pd.read_parquet(cache_dir / "n1_2_hb1_coinbase_1h_panel.parquet")
    hb2_panel = pd.read_parquet(cache_dir / "n1_2_hb2_5m_perp_spot_hourly_panel.parquet")

    print("[2/4] Building causal features & forward targets for H-A and H-B...")
    df_ha = build_ha_features_and_targets(ha_panel)
    ha_features = [
        "ha_whale_ofi",
        "ha_whale_minus_retail",
        "ha_signed_sweep_imb",
        "ha_multifill_ofi",
        "ha_impact_asymmetry",
        "ha_sweep_intensity_z",
    ]
    # Causal composite score for H-A simple baseline
    # Note: In Phase D discovery (2022-2024), aggressive buyer sweeps (`ha_whale_ofi`, `ha_multifill_ofi`,
    # `ha_impact_asymmetry`) exhibit strong *negative* IC (-0.015 to -0.039, t = -4.2 to -7.6) due to
    # short-term liquidity exhaustion / post-sweep mean reversion. We evaluate both the naive momentum sign
    # (`ha_composite_score`) and the exhaustion-reversion sign (`ha_reversion_composite_score = -ha_composite_score`).
    df_ha["ha_composite_score"] = (
        0.35 * df_ha["ha_whale_ofi"]
        + 0.25 * df_ha["ha_signed_sweep_imb"]
        + 0.25 * df_ha["ha_multifill_ofi"]
        + 0.15 * df_ha["ha_whale_minus_retail"]
    )
    df_ha["ha_reversion_composite_score"] = -df_ha["ha_composite_score"]

    df_hb = build_hb_features_and_targets(hb1_panel, hb2_panel)
    hb_features = [
        "hb1_cb_minus_bn_ret_z",
        "hb1_cb_premium_dev_z",
        "hb1_cb_signed_vol_shock",
        "hb1_cb_vol_share_z",
        "hb2_basis_change_z",
        "hb2_last15m_perp_lead_z",
        "hb2_perp_minus_spot_imb_z",
        "hb2_last15m_imb_diff_z",
    ]
    df_hb["hb1_composite_score"] = (
        0.45 * df_hb["hb1_cb_minus_bn_ret_z"]
        + 0.35 * df_hb["hb1_cb_signed_vol_shock"]
        + 0.20 * df_hb["hb1_cb_premium_dev_z"]
    )
    df_hb["hb2_composite_score"] = (
        0.35 * df_hb["hb2_basis_change_z"]
        + 0.35 * df_hb["hb2_perp_minus_spot_imb_z"]
        + 0.30 * df_hb["hb2_last15m_perp_lead_z"]
    )
    df_hb["hb_combined_score"] = 0.50 * df_hb["hb1_composite_score"] + 0.50 * df_hb["hb2_composite_score"]

    print("[3/4] Running Phase D Economic Information Discovery...")
    phase_d_ha = evaluate_feature_suite_phase_d(
        df_ha,
        feature_cols=ha_features + ["ha_composite_score"],
        hypothesis_id="H_A_PERSISTENT_TRADE_LEVEL_ORDER_FLOW_AND_LIQUIDITY_DISLOCATION",
    )
    phase_d_hb = evaluate_feature_suite_phase_d(
        df_hb,
        feature_cols=hb_features + ["hb1_composite_score", "hb2_composite_score", "hb_combined_score"],
        hypothesis_id="H_B_CROSS_VENUE_COINBASE_AND_5M_PERP_SPOT_PRICE_DISCOVERY",
    )

    # Also summarize realized tick-level bounce spread & sweep statistics on H-A
    ha_micro_summary: Dict[str, Any] = {}
    for sym, grp in df_ha.groupby("symbol"):
        ha_micro_summary[str(sym)] = {
            "total_hours": int(len(grp)),
            "total_agg_trades": int(grp["agg_trade_count"].sum()),
            "total_underlying_orders_swept": int(grp["underlying_order_count"].sum()),
            "mean_orders_per_aggtrade": round(float(grp["underlying_order_count"].sum() / max(1.0, grp["agg_trade_count"].sum())), 4),
            "median_realized_bounce_spread_bps": round(float(grp["ha_realized_bounce_spread_bps"].median()), 3),
            "p90_realized_bounce_spread_bps": round(float(grp["ha_realized_bounce_spread_bps"].quantile(0.90)), 3),
            "whale_volume_share_pct": round(
                float((grp["whale_buy_notional"].sum() + grp["whale_sell_notional"].sum()) / max(1.0, grp["total_notional"].sum()) * 100.0),
                2,
            ),
            "retail_volume_share_pct": round(
                float((grp["retail_buy_notional"].sum() + grp["retail_sell_notional"].sum()) / max(1.0, grp["total_notional"].sum()) * 100.0),
                2,
            ),
        }

    phase_d_report = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ha_microstructure_summary": ha_micro_summary,
        "hypothesis_ha": phase_d_ha,
        "hypothesis_hb": phase_d_hb,
    }
    with (out_dir / "n1_2_phase_d_discovery_results.json").open("w", encoding="utf-8") as f:
        json.dump(phase_d_report, f, indent=2)

    print("[4/4] Running Phase E/F Post-Cost Economic Feasibility Experiments...")
    ef_ha = _run_hypothesis_phase_ef(
        df=df_ha,
        hypothesis_id="H_A_AGGTRADES_ORDER_FLOW_DISLOCATION_MOMENTUM_SIGN",
        feature_cols=ha_features,
        composite_col="ha_composite_score",
        extra_half_spread_col="ha_realized_bounce_spread_bps",
    )
    ef_ha_rev = _run_hypothesis_phase_ef(
        df=df_ha,
        hypothesis_id="H_A_AGGTRADES_EXHAUSTION_REVERSION_SIGN",
        feature_cols=ha_features,
        composite_col="ha_reversion_composite_score",
        extra_half_spread_col="ha_realized_bounce_spread_bps",
    )
    ef_hb = _run_hypothesis_phase_ef(
        df=df_hb,
        hypothesis_id="H_B_CROSS_VENUE_AND_5M_LEAD_LAG_12H",
        feature_cols=hb_features,
        composite_col="hb1_composite_score",
        extra_half_spread_col=None,
        rebalance_every_h=12,
    )
    ef_hb_4h = _run_hypothesis_phase_ef(
        df=df_hb,
        hypothesis_id="H_B_CROSS_VENUE_AND_5M_LEAD_LAG_4H",
        feature_cols=hb_features,
        composite_col="hb1_composite_score",
        extra_half_spread_col=None,
        rebalance_every_h=4,
    )

    phase_ef_report = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": round(time.time() - t0, 2),
        "ha_experiment": ef_ha,
        "ha_exhaustion_reversion_experiment": ef_ha_rev,
        "hb_experiment": ef_hb,
        "hb_4h_experiment": ef_hb_4h,
    }
    with (out_dir / "n1_2_phase_ef_economic_results.json").open("w", encoding="utf-8") as f:
        json.dump(phase_ef_report, f, indent=2)

    print(f"Completed N1.2 Phase D & E/F in {phase_ef_report['elapsed_seconds']}s.")


if __name__ == "__main__":
    main()
