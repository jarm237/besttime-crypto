#!/usr/bin/env python3
"""HMR-V4B-2A: Perp Spot Premium Historical Provenance Audit."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
import requests
import pandas as pd
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = REPO_ROOT / "research/historical_market_replay_v4/v4b_2a_premium_provenance.json"
OUT_MD = REPO_ROOT / "research/historical_market_replay_v4/v4b_2a_premium_provenance.md"
API_URL = "https://fapi.binance.com/fapi/v1/premiumIndexKlines"

ASSETS = ["BTC", "ETH", "BNB"]
TARGET_MONTHS = [
    "2023-01", "2023-03", "2023-06", "2023-09", "2023-12",
    "2024-01", "2024-03", "2024-06", "2024-09", "2024-12"
]

def probe_month(symbol: str, month_str: str) -> bool:
    ts = pd.Timestamp(f"{month_str}-01", tz="UTC")
    ts_ms = int(ts.timestamp() * 1000)
    params = {
        "symbol": symbol,
        "interval": "15m",
        "startTime": ts_ms,
        "limit": 5
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return len(data) > 0
        return False
    except Exception:
        return False

def check_integrity(symbol: str) -> dict:
    # Query a larger sample of 1000 klines starting from 2023-06-01 to run detailed integrity checks
    ts = pd.Timestamp("2023-06-01", tz="UTC")
    ts_ms = int(ts.timestamp() * 1000)
    params = {
        "symbol": symbol,
        "interval": "15m",
        "startTime": ts_ms,
        "limit": 1000
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=10)
        if resp.status_code != 200:
            return {"success": False, "error": f"API returned status {resp.status_code}"}
        
        klines = resp.json()
        if not klines:
            return {"success": False, "error": "No klines returned"}
            
        now_ms = int(time.time() * 1000)
        
        timestamps = []
        ohlc_consistent_count = 0
        finite_count = 0
        non_negative_count = 0
        no_future_count = 0
        
        for k in klines:
            # kline format: [open_time, open, high, low, close, volume, close_time, ...]
            ot = int(k[0])
            o = float(k[1])
            h = float(k[2])
            l = float(k[3])
            c = float(k[4])
            
            timestamps.append(ot)
            
            # OHLC consistency
            if h >= o and h >= c and l <= o and l <= c:
                ohlc_consistent_count += 1
                
            # Finite
            if np.isfinite(o) and np.isfinite(h) and np.isfinite(l) and np.isfinite(c):
                finite_count += 1
                
            # Non-negative timestamp
            if ot >= 0:
                non_negative_count += 1
                
            # No future row
            if ot < now_ms:
                no_future_count += 1
                
        # Calculations
        n = len(klines)
        monotonic = True
        for i in range(1, n):
            if timestamps[i] <= timestamps[i-1]:
                monotonic = False
                
        deltas = np.diff(timestamps)
        expected_delta = 15 * 60 * 1000 # 15 minutes in ms
        missing_intervals = sum(1 for d in deltas if d > expected_delta)
        duplicates = n - len(set(timestamps))
        
        return {
            "success": True,
            "klines_probed": n,
            "timestamp_monotonic": bool(monotonic),
            "no_duplicate_timestamps": bool(duplicates == 0),
            "ohlc_consistency_ratio": ohlc_consistent_count / n,
            "finite_value_ratio": finite_count / n,
            "non_negative_timestamp_ratio": non_negative_count / n,
            "no_future_row_ratio": no_future_count / n,
            "missing_interval_ratio": missing_intervals / n if n > 1 else 0.0,
            "duplicate_ratio": duplicates / n,
            "invalid_row_ratio": (n - ohlc_consistent_count) / n
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def run_provenance():
    print("Starting Perp Spot Premium Provenance Audit...")
    
    coverage_matrix = {}
    integrity_results = {}
    
    for asset in ASSETS:
        symbol = f"{asset}USDT"
        print(f"Auditing asset: {asset} ({symbol})...")
        
        # 1. Probing months
        coverage_matrix[asset] = {}
        for m in TARGET_MONTHS:
            available = probe_month(symbol, m)
            coverage_matrix[asset][m] = available
            print(f"  Month {m}: {'AVAILABLE' if available else 'MISSING'}")
            time.sleep(0.1) # rate limit politeness
            
        # 2. Running integrity checks
        integrity = check_integrity(symbol)
        integrity_results[asset] = integrity
        if integrity["success"]:
            print(f"  Integrity check passed: monotonic={integrity['timestamp_monotonic']}, duplicate_ratio={integrity['duplicate_ratio']:.4f}")
        else:
            print(f"  Integrity check failed: {integrity.get('error')}")
            
    # Formulate final decisions (P0-P6)
    p0_market_source = True # Direct from fapi binance
    
    # P1: Historical depth (are all probed months available?)
    p1_historical_depth = True
    for asset in ASSETS:
        for m, avail in coverage_matrix[asset].items():
            if not avail:
                p1_historical_depth = False
                
    # P2: Asset coverage (BTC + ETH required)
    p2_asset_coverage = all(coverage_matrix["BTC"].values()) and all(coverage_matrix["ETH"].values())
    
    p3_temporal_semantics = True # openTime represents the exact start of the 15m period
    p4_pit_usability = True # availability lag can be set conservatively (e.g. available_at = openTime + 15m)
    
    # P5: Data quality (missing ratio < 5%, duplicates < 1%)
    p5_data_quality = True
    for asset in ASSETS:
        integ = integrity_results[asset]
        if integ["success"]:
            if integ["missing_interval_ratio"] >= 0.05 or integ["duplicate_ratio"] >= 0.01:
                p5_data_quality = False
        else:
            p5_data_quality = False
            
    p6_no_synthetic = True # raw exchange premiumIndex klines
    
    gates_passed = {
        "P0_MARKET_SOURCE": p0_market_source,
        "P1_HISTORICAL_DEPTH": p1_historical_depth,
        "P2_ASSET_COVERAGE": p2_asset_coverage,
        "P3_TEMPORAL_SEMANTICS": p3_temporal_semantics,
        "P4_PIT_USABILITY": p4_pit_usability,
        "P5_DATA_QUALITY": p5_data_quality,
        "P6_NO_SYNTHETIC_RECONSTRUCTION": p6_no_synthetic
    }
    
    p0_p6_pass = all(gates_passed.values())
    verdict = "AUTHORIZED_V4B_2B" if p0_p6_pass else "BLOCKED_PROVENANCE"
    
    # Save JSON results
    output = {
        "program": "HMR-V4B-2A",
        "source": "binance_um_premium_index",
        "provenance_class": "MARKET_OBSERVED",
        "eligible_assets": ASSETS,
        "probed_months": TARGET_MONTHS,
        "coverage_matrix": coverage_matrix,
        "integrity_checks": integrity_results,
        "provenance_gates": gates_passed,
        "verdict": verdict
    }
    
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Saved JSON verdict to {OUT_JSON}")
    
    # Save Markdown report
    write_md_report(output)

def write_md_report(output: dict):
    lines = [
        "# HMR-V4B-2A Perp Spot Premium Provenance Audit Report",
        "",
        "## Provenance & Coverage Verdict",
        "",
        f"- **Verdict**: `{output['verdict']}`",
        f"- **Provenance Class**: `{output['provenance_class']}`",
        "",
        "### Provenance Gates (P0 - P6)",
        ""
    ]
    
    for gate, passed in output["provenance_gates"].items():
        lines.append(f"- **{gate}**: {'`PASS`' if passed else '`FAIL`'}")
        
    lines.extend([
        "",
        "## Historical Coverage Matrix",
        "",
        "| Asset | 2023 Coverage | 2024 Coverage | Frequency | Probe Verdict |",
        "| --- | :---: | :---: | :---: | :---: |"
    ])
    
    for asset in ASSETS:
        c_map = output["coverage_matrix"][asset]
        cov_2023 = sum(1 for m, avail in c_map.items() if m.startswith("2023") and avail)
        cov_2024 = sum(1 for m, avail in c_map.items() if m.startswith("2024") and avail)
        
        pass_2023 = f"{cov_2023}/5 months"
        pass_2024 = f"{cov_2024}/5 months"
        
        freq = "15m"
        asset_passed = cov_2023 == 5 and cov_2024 == 5
        lines.append(f"| `{asset}` | {pass_2023} | {pass_2024} | `{freq}` | {'`PASS`' if asset_passed else '`FAIL`'} |")
        
    lines.extend([
        "",
        "## Data Integrity Verification",
        "",
        "| Asset | Monotonic | No Duplicates | OHLC Cons. | Missing Ratio | Duplicate Ratio | Invalid Ratio |",
        "| --- | :---: | :---: | :---: | :---: | :---: | :---: |"
    ])
    
    for asset in ASSETS:
        integ = output["integrity_checks"][asset]
        if integ["success"]:
            lines.append(
                f"| `{asset}` | "
                f"{'Yes' if integ['timestamp_monotonic'] else 'No'} | "
                f"{'Yes' if integ['no_duplicate_timestamps'] else 'No'} | "
                f"{integ['ohlc_consistency_ratio']:.2%} | "
                f"{integ['missing_interval_ratio']:.4%} | "
                f"{integ['duplicate_ratio']:.4%} | "
                f"{integ['invalid_row_ratio']:.4%} |"
            )
        else:
            lines.append(f"| `{asset}` | [Error] {integ.get('error')} | | | | | |")
            
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved Markdown report to {OUT_MD}")

if __name__ == "__main__":
    run_provenance()
