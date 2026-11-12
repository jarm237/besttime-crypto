"""N1.6 Phase A — material closure of N1.5 (no full historical rerun).

1. Label: historical `EXECUTABLE_NET_CARRY` -> `LIQUIDITY_CONSTRAINED_SIMULATED_NET_CARRY`.
2. Leg-level partial-fill accounting audit + hedge mismatch through time (from frozen N1.5 ledgers).
3. Margin-ratio formula confirmation (wallet + uPnL, maintenance requirement, tier applicability).
4. Official Binance delivery settlement prices (public `futures/data/delivery-price`) vs the N1.5
   approximation computed from 1m `indexPriceKlines` (30m arithmetic mean of 1m closes).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import requests

from neural_trading.n1_6.config import DAPI_BASE, DATA_ROOT, PAIR_TO_SPOT, REPO_ROOT, tier1_max_notional, tier1_mmr

N1_5_RESULTS = REPO_ROOT / "research" / "neural_n1_5" / "n1_5_coinm_reality_check_results.json"
N1_5_INDEX_CACHE = REPO_ROOT / "data" / "neural_n1_5" / "index_1m_delivery"
PHASE_A_DIR = DATA_ROOT / "phase_a"

LABEL_MAP = {
    "EXECUTABLE_NET_CARRY": "LIQUIDITY_CONSTRAINED_SIMULATED_NET_CARRY",
    "EXECUTABLE_TWAP_CONSTRAINED": "LIQUIDITY_CONSTRAINED_SIMULATED_TWAP (execution_mode string kept unchanged in frozen N1.5 code)",
    "phase_e_executable_net_carry_by_fee_scenario": "phase_e_liquidity_constrained_simulated_net_carry_by_fee_scenario (alias)",
}


def fetch_official_delivery_prices() -> Dict[str, Any]:
    PHASE_A_DIR.mkdir(parents=True, exist_ok=True)
    out: Dict[str, Any] = {}
    for pair in PAIR_TO_SPOT:
        url = f"{DAPI_BASE}/futures/data/delivery-price"
        sent = int(time.time() * 1000)
        try:
            r = requests.get(url, params={"pair": pair}, timeout=15)
            recv = int(time.time() * 1000)
            payload = r.json() if r.status_code == 200 else None
            rec = {"pair": pair, "endpoint": url, "req_sent_ms": sent, "recv_ms": recv, "http_status": r.status_code,
                   "payload": payload}
        except Exception as exc:  # noqa: BLE001
            rec = {"pair": pair, "endpoint": url, "req_sent_ms": sent, "error": str(exc), "payload": None}
        (PHASE_A_DIR / f"official_delivery_price_{pair}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
        out[pair] = rec
    return out


def compare_settlement(official: Dict[str, Any]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for pair, rec in official.items():
        # Official `deliveryTime` is day-normalised (00:00 UTC of the delivery date); match on UTC date.
        off = {int(x["deliveryTime"]) // 86_400_000: float(x["deliveryPrice"]) for x in (rec.get("payload") or [])}
        for meta_p in sorted((N1_5_INDEX_CACHE / pair).glob("*.meta.json")):
            m = json.loads(meta_p.read_text(encoding="utf-8"))
            if m.get("status") != "VERIFIED_OK" or not m.get("official_twap_30m_index"):
                continue
            exp_ms = int(m["expiry_ms"])
            p_off = off.get(exp_ms // 86_400_000)
            row = {
                "pair": pair,
                "expiry_code": m["expiry_code"],
                "delivery_ms": exp_ms,
                "official_delivery_price": p_off,
                "n1_5_twap_30m_close_mean": m["official_twap_30m_index"],
                "twap_30m_ohlc4": m.get("twap_30m_ohlc4_index"),
                "twap_60m": m.get("twap_60m_index"),
                "index_close_0800": m.get("index_at_0800_utc"),
            }
            if p_off:
                for k in ("n1_5_twap_30m_close_mean", "twap_30m_ohlc4", "twap_60m", "index_close_0800"):
                    v = row[k]
                    row[f"err_{k}_bps"] = round((v / p_off - 1.0) * 1e4, 4) if v else None
            rows.append(row)
    df = pd.DataFrame(rows)
    matched = df[df["official_delivery_price"].notna()] if len(df) else df
    summary: Dict[str, Any] = {"events_in_n1_5_cache": int(len(df)), "events_matched_to_official": int(len(matched))}
    for k in ("n1_5_twap_30m_close_mean", "twap_30m_ohlc4", "twap_60m", "index_close_0800"):
        col = f"err_{k}_bps"
        if len(matched) and col in matched:
            e = matched[col].astype(float)
            summary[k] = {
                "mean_abs_err_bps": round(float(e.abs().mean()), 3),
                "median_abs_err_bps": round(float(e.abs().median()), 3),
                "p95_abs_err_bps": round(float(e.abs().quantile(0.95)), 3),
                "max_abs_err_bps": round(float(e.abs().max()), 3),
                "mean_signed_err_bps": round(float(e.mean()), 3),
                "share_within_1bp": round(float((e.abs() <= 1.0).mean()), 4),
            }
    unmatched = df[df["official_delivery_price"].isna()][["pair", "expiry_code"]].to_dict("records") if len(df) else []
    summary["unmatched_events"] = unmatched
    return {"summary": summary, "rows": rows}


def settlement_pnl_impact(results: Dict[str, Any], cmp_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Re-price N1.5 DELIVERY_SETTLEMENT exits at the official price (ledger-level, no rerun)."""
    off_by_key = {(r["pair"], r["expiry_code"]): r["official_delivery_price"] for r in cmp_rows if r.get("official_delivery_price")}
    spot_to_pair = {v: k for k, v in PAIR_TO_SPOT.items()}
    out: Dict[str, Any] = {}
    for scen, run in results["phase_e_executable_net_carry_by_fee_scenario"].items():
        delta_usd = 0.0
        n_settle = 0
        n_priced = 0
        for led in run["position_ledgers"]:
            if not str(led["exit_type"]).startswith("DELIVERY_SETTLEMENT"):
                continue
            n_settle += 1
            p_off = off_by_key.get((spot_to_pair.get(led["symbol"]), led["expiry_code"]))
            p_apx = led.get("delivery_settlement_index")
            if not p_off or not p_apx:
                continue
            n_priced += 1
            notional = led["contracts_short"] * led["contract_size_usd"]
            fee_rate = led["delivery_fee_coin"] / (notional / p_apx) if notional else 0.0
            d_coin = notional * (1.0 / p_off - 1.0 / p_apx) - (notional / p_off - notional / p_apx) * fee_rate
            # coin is sold (or rolled) near the settlement price
            delta_usd += d_coin * p_off
        out[scen] = {
            "delivery_settlement_exits": n_settle,
            "exits_repriced_with_official_price": n_priced,
            "net_pnl_delta_usd_if_official_price_used": round(delta_usd, 2),
            "reported_net_pnl_usd": run["realized_net_pnl_usd"],
        }
    return out


def leg_fill_and_mismatch_audit(results: Dict[str, Any]) -> Dict[str, Any]:
    run = results["phase_e_executable_net_carry_by_fee_scenario"]["standard_retail_taker"]
    leds = run["position_ledgers"]
    partial = [l for l in leds if l["filled_fraction"] < 0.9999]
    # Hedge mismatch through time: each position's coin mismatch (wallet - N*M/F_entry) is fixed at entry;
    # we aggregate the per-position max USD mismatch over the months it was open.
    monthly: Dict[str, float] = {}
    for l in leds:
        start = pd.Timestamp(l["entry_hour_ms"], unit="ms").to_period("M")
        end = pd.Timestamp(l["exit_hour_ms"], unit="ms").to_period("M")
        for p in pd.period_range(start, end, freq="M"):
            monthly[str(p)] = monthly.get(str(p), 0.0) + float(l["max_hedge_mismatch_usd"])
    mm = pd.Series(monthly).sort_index()
    return {
        "scenario": "standard_retail_taker / LIQUIDITY_CONSTRAINED_SIMULATED",
        "finding_leg_independence": (
            "NOT_INDEPENDENT: N1.5 applies one `filled_fraction` (derived from 4h COIN-M contract volume * 5%) to the "
            "whole package. The Spot leg is assumed to fill the same USD amount, the futures leg is then sized as "
            "floor(coin * F / (M * (1 + fee))) contracts and excess Spot purchase is trimmed. Spot-side depth/volume "
            "never constrains the fill and no leg can fill while the other does not. Hedge mismatch is therefore "
            "only the integer-contract rounding residual; legging risk is NOT represented in N1.5."
        ),
        "finding_volume_window": (
            "The 5% cap uses COIN-M volume of hours t..t+3 (the TWAP execution window). This is execution-concurrent "
            "volume, not information available at decision time t; it is a capacity approximation, not a signal leak."
        ),
        "positions": len(leds),
        "partial_fill_positions": len(partial),
        "mean_filled_fraction_partial_positions": round(float(np.mean([l["filled_fraction"] for l in partial])), 4) if partial else None,
        "positions_with_nonzero_hedge_mismatch": int(sum(1 for l in leds if l["max_hedge_mismatch_usd"] > 0)),
        "max_position_hedge_mismatch_usd": round(float(max(l["max_hedge_mismatch_usd"] for l in leds)), 2),
        "portfolio_mean_hedge_mismatch_usd_reported": run["margin_and_risk_reality"]["mean_hedge_mismatch_usd"],
        "portfolio_max_hedge_mismatch_usd_reported": run["margin_and_risk_reality"]["max_hedge_mismatch_usd"],
        "monthly_open_position_hedge_mismatch_usd_upper_bound": {k: round(v, 2) for k, v in mm.items()},
    }


def margin_ratio_audit(results: Dict[str, Any]) -> Dict[str, Any]:
    spot_to_pair = {v: k for k, v in PAIR_TO_SPOT.items()}
    leds = results["phase_e_executable_net_carry_by_fee_scenario"]["standard_retail_taker"]["position_ledgers"]
    errs = []
    for l in leds:
        bal = l["margin_wallet_balance_coin"] + l["inverse_unrealized_pnl_coin"]
        if bal <= 0:
            continue
        mr = l["maintenance_margin_coin"] / bal
        errs.append(abs(mr - tier1_mmr(spot_to_pair[l["symbol"]])))
    cap = results["phase_c_and_d_capacity_and_margin_stress_suite"]["liquidity_constrained_capacity_curve"]
    tier_breaches = []
    for row in cap:
        per_asset = row["initial_capital_usd"] * 0.25 * (1.0 + max(row["net_return_on_committed_capital_pct"], 0) / 100.0)
        for pair in PAIR_TO_SPOT:
            if per_asset > tier1_max_notional(pair):
                tier_breaches.append({"initial_capital_usd": row["initial_capital_usd"], "pair": pair,
                                      "approx_max_per_asset_notional_usd": round(per_asset, 0),
                                      "tier1_max_notional_usd": tier1_max_notional(pair)})
    return {
        "formula_in_code": "margin_ratio = MM_coin / (wallet_balance_coin + inverse_uPnL_coin); MM_coin = MMR * N*M / F_mark "
                           "(evaluated at 1h mark high for the worst case). Matches Binance COIN-M definition "
                           "(maintenance margin / margin balance, margin balance = wallet balance + unrealized PnL).",
        "ledger_recomputation_positions": len(errs),
        "ledger_recomputation_max_abs_deviation_from_tier1_mmr": round(float(max(errs)), 6) if errs else None,
        "identity_note": "For a 1x coin-collateralised short, wallet ~= N*M/F_entry so margin balance = N*M/F_mark and the "
                         "ratio collapses to MMR. The reported 0.004/0.005 maxima are an identity, not an empirical "
                         "safety measurement; they only show the position was never under-collateralised in the model.",
        "tier_model": "Flat Tier-1 MMR (0.40% BTC/ETH, 0.50% alts) plus a 2.50% exchangeInfo stress value. Brackets were not "
                      "refreshed: `/dapi/v2/leverageBracket` is a SIGNED endpoint and is out of scope (public-only).",
        "tier1_exceedances_in_capacity_curve": tier_breaches,
        "tier_exceedance_verdict_impact": "None for the 1x structure (ratio = MMR at any tier, < 1.0). Higher tiers would "
                                         "matter only for leveraged/under-collateralised variants, which H-1 does not use.",
    }


def apply_label_alias(results: Dict[str, Any]) -> None:
    results["phase_e_liquidity_constrained_simulated_net_carry_by_fee_scenario"] = {
        "alias_of": "phase_e_executable_net_carry_by_fee_scenario",
        "note": "N1.6 Phase A relabel: these are liquidity-constrained SIMULATED fills (volume-share cap, sqrt impact, "
                "bar-price references), not executable quotes or real fills. Numbers are unchanged.",
    }
    results.setdefault("n1_6_phase_a_closure", {})["label_map"] = LABEL_MAP


def main() -> Dict[str, Any]:
    results = json.loads(N1_5_RESULTS.read_text(encoding="utf-8"))
    official = fetch_official_delivery_prices()
    cmp = compare_settlement(official)
    closure = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "label_map": LABEL_MAP,
        "settlement_official_vs_approximation": cmp["summary"],
        "settlement_pnl_impact": settlement_pnl_impact(results, cmp["rows"]),
        "leg_fill_and_hedge_mismatch": leg_fill_and_mismatch_audit(results),
        "margin_ratio": margin_ratio_audit(results),
    }
    s = cmp["summary"].get("n1_5_twap_30m_close_mean", {})
    closure["settlement_status"] = (
        "OFFICIAL_DELIVERY_PRICES_AVAILABLE; N1.5 used an APPROXIMATION (30m mean of 1m index closes) with "
        f"mean |error| {s.get('mean_abs_err_bps')} bps vs official"
    )
    max_delta = max(abs(v["net_pnl_delta_usd_if_official_price_used"]) for v in closure["settlement_pnl_impact"].values())
    closure["verdict_change_required"] = bool(max_delta > 250.0)
    closure["n1_5_rerun_performed"] = False

    out_dir = REPO_ROOT / "research" / "neural_n1_6"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "n1_6_phase_a_closure.json").write_text(json.dumps(closure, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(cmp["rows"]).to_csv(out_dir / "n1_6_settlement_official_vs_approx.csv", index=False)

    apply_label_alias(results)
    results["n1_6_phase_a_closure"].update({
        "settlement_status": closure["settlement_status"],
        "verdict_change_required": closure["verdict_change_required"],
        "closure_file": "research/neural_n1_6/n1_6_phase_a_closure.json",
    })
    N1_5_RESULTS.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return closure


if __name__ == "__main__":
    c = main()
    print(json.dumps({k: v for k, v in c.items() if k != "leg_fill_and_hedge_mismatch"}, indent=2, default=str)[:6000])
    print(json.dumps({k: v for k, v in c["leg_fill_and_hedge_mismatch"].items() if not k.startswith("monthly")}, indent=2))
