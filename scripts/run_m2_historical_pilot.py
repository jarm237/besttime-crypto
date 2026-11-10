"""
scripts/run_m2_historical_pilot.py
Phase B & C Pilot: Downloads real historical data samples, verifies checksums,
normalizes with point-in-time contracts, validates data quality, and derives diagnostic features.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from btc_scraper.research.historical_sources.binance_archive import (
    download_and_verify_archive,
    parse_aggtrades_zip,
    parse_funding_rate_zip,
    parse_futures_metrics_zip,
    parse_klines_zip,
)
from btc_scraper.research.historical_sources.okx_adapter import (
    fetch_okx_candles,
    fetch_okx_funding_history,
)
from btc_scraper.research.historical_sources.treasury_macro import (
    fetch_and_parse_treasury_yields,
)
from btc_scraper.research.historical_sources.alternative_me import (
    fetch_fear_and_greed_history,
)
from btc_scraper.research.historical_sources.defi_llama import (
    fetch_historical_stablecoins,
)


def run_pilot() -> Dict[str, Any]:
    raw_dir = PROJECT_ROOT / "data" / "historical" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    report_dir = PROJECT_ROOT / "data" / "historical" / "quality_reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    pilot_report = {
        "execution_timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "datasets": {},
        "derived_feature_diagnostics": {},
        "summary": {}
    }

    print("=== Starting M2 Real-Data Backfill Pilot ===")

    # ── 1. Binance Spot 1h (June 2023 - 2023-06-01) ───────────────────────────
    print("\n[1/8] Downloading & verifying Binance Spot 1h BTCUSDT 2023-06-01...")
    url_spot_2023 = "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1h/BTCUSDT-1h-2023-06-01.zip"
    path_spot_2023, sha_spot_2023, status_spot_2023 = download_and_verify_archive(url_spot_2023, raw_dir / "binance_spot")
    records_spot_2023 = parse_klines_zip(path_spot_2023, "BTCUSDT", "BINANCE_SPOT")
    print(f"  Rows parsed: {len(records_spot_2023)}, Checksum status: {status_spot_2023}")
    pilot_report["datasets"]["binance_spot_1h_btc_2023"] = {
        "url": url_spot_2023,
        "rows": len(records_spot_2023),
        "sha256": sha_spot_2023,
        "checksum_status": status_spot_2023,
        "first_ts": records_spot_2023[0].open_time if records_spot_2023 else None,
        "last_ts": records_spot_2023[-1].open_time if records_spot_2023 else None,
        "pit_quality": records_spot_2023[0].metadata.availability_quality if records_spot_2023 else None,
        "quality_flags": list(records_spot_2023[0].metadata.quality_flags) if records_spot_2023 else [],
    }

    # ── 2. Binance Spot 1h (February 2025 - Microsecond Test) ─────────────────
    print("\n[2/8] Downloading & verifying Binance Spot 1h BTCUSDT 2025-02-01 (Microseconds)...")
    url_spot_2025 = "https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1h/BTCUSDT-1h-2025-02-01.zip"
    path_spot_2025, sha_spot_2025, status_spot_2025 = download_and_verify_archive(url_spot_2025, raw_dir / "binance_spot")
    records_spot_2025 = parse_klines_zip(path_spot_2025, "BTCUSDT", "BINANCE_SPOT")
    print(f"  Rows parsed: {len(records_spot_2025)}, Flags: {records_spot_2025[0].metadata.quality_flags}")
    pilot_report["datasets"]["binance_spot_1h_btc_2025_us"] = {
        "url": url_spot_2025,
        "rows": len(records_spot_2025),
        "sha256": sha_spot_2025,
        "checksum_status": status_spot_2025,
        "first_ts": records_spot_2025[0].open_time,
        "last_ts": records_spot_2025[-1].open_time,
        "quality_flags": list(records_spot_2025[0].metadata.quality_flags),
    }

    # ── 3. Binance Futures 1h & Funding & Metrics ──────────────────────────────
    print("\n[3/8] Downloading & verifying Binance Futures USD-M Funding & Metrics...")
    url_funding = "https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2023-06.zip"
    path_funding, sha_funding, status_funding = download_and_verify_archive(url_funding, raw_dir / "binance_futures")
    records_funding = parse_funding_rate_zip(path_funding, "BTCUSDT")
    
    url_metrics = "https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2023-06-01.zip"
    path_metrics, sha_metrics, status_metrics = download_and_verify_archive(url_metrics, raw_dir / "binance_futures")
    records_metrics = parse_futures_metrics_zip(path_metrics, "BTCUSDT")
    print(f"  Funding rows: {len(records_funding)}, Metrics 5m rows: {len(records_metrics)}")
    pilot_report["datasets"]["binance_futures_funding"] = {
        "url": url_funding,
        "rows": len(records_funding),
        "sha256": sha_funding,
        "checksum_status": status_funding,
        "sample_funding_rate": records_funding[0].funding_rate if records_funding else None,
    }
    pilot_report["datasets"]["binance_futures_metrics"] = {
        "url": url_metrics,
        "rows": len(records_metrics),
        "sha256": sha_metrics,
        "checksum_status": status_metrics,
        "first_open_interest_usd": records_metrics[0].sum_open_interest_usd if records_metrics else None,
    }

    # ── 4. Binance Spot AggTrades (1 Day Sample) ───────────────────────────────
    print("\n[4/8] Downloading & verifying Binance Spot AggTrades (1 Day Sample)...")
    url_aggtrades = "https://data.binance.vision/data/spot/daily/aggTrades/BTCUSDT/BTCUSDT-aggTrades-2023-06-01.zip"
    path_aggtrades, sha_aggtrades, status_aggtrades = download_and_verify_archive(url_aggtrades, raw_dir / "binance_spot")
    records_aggtrades = parse_aggtrades_zip(path_aggtrades, "BTCUSDT", max_rows=5000)
    print(f"  AggTrades parsed sample: {len(records_aggtrades)} rows (capped at 5000 for pilot diagnostics)")
    pilot_report["datasets"]["binance_spot_aggtrades_sample"] = {
        "url": url_aggtrades,
        "rows_sample": len(records_aggtrades),
        "sha256": sha_aggtrades,
        "checksum_status": status_aggtrades,
        "first_price": records_aggtrades[0].price if records_aggtrades else None,
        "last_price": records_aggtrades[-1].price if records_aggtrades else None,
    }

    # ── 5. OKX Historical Candles & Funding Rate ──────────────────────────────
    print("\n[5/8] Fetching OKX REST Historical Candles & Funding...")
    okx_candles = fetch_okx_candles("BTC-USDT", bar="1H", limit=100, target_cache_dir=raw_dir / "okx")
    okx_funding = fetch_okx_funding_history("BTC-USDT-SWAP", limit=50, target_cache_dir=raw_dir / "okx")
    print(f"  OKX Candles: {len(okx_candles)}, OKX Funding: {len(okx_funding)}")
    pilot_report["datasets"]["okx_candles_and_funding"] = {
        "candles_rows": len(okx_candles),
        "funding_rows": len(okx_funding),
        "oldest_candle": okx_candles[0].open_time if okx_candles else None,
        "newest_candle": okx_candles[-1].open_time if okx_candles else None,
        "pit_quality": "VERIFIED_PIT",
    }

    # ── 6. U.S. Treasury Daily Yield Curve (2023) ─────────────────────────────
    print("\n[6/8] Fetching U.S. Treasury Daily Par Yield Curve (home.treasury.gov)...")
    treasury_records = fetch_and_parse_treasury_yields(2023, target_cache_dir=raw_dir / "macro")
    print(f"  Treasury 2023 rows: {len(treasury_records)} trading days")
    pilot_report["datasets"]["us_treasury_yields_2023"] = {
        "trading_days": len(treasury_records),
        "first_date": treasury_records[0].date if treasury_records else None,
        "last_date": treasury_records[-1].date if treasury_records else None,
        "sample_10y_yield": treasury_records[-1].yield_10y if treasury_records else None,
        "pit_availability_rule": "Observation Date + 21:00:00Z (market close release)",
    }

    # ── 7. Alternative.me Crypto Fear & Greed Index ───────────────────────────
    print("\n[7/8] Fetching Alternative.me Crypto Fear & Greed Index...")
    fng_records = fetch_fear_and_greed_history(limit=100, target_cache_dir=raw_dir / "sentiment")
    print(f"  FNG entries: {len(fng_records)} days")
    pilot_report["datasets"]["alternative_me_fear_and_greed"] = {
        "entries": len(fng_records),
        "first_date": fng_records[0].timestamp[:10] if fng_records else None,
        "last_date": fng_records[-1].timestamp[:10] if fng_records else None,
        "latest_value": fng_records[-1].value if fng_records else None,
        "latest_classification": fng_records[-1].classification if fng_records else None,
    }

    # ── 8. DefiLlama Stablecoin Circulation ────────────────────────────────────
    print("\n[8/8] Fetching DefiLlama Historical Stablecoin Supply...")
    stablecoin_records = fetch_historical_stablecoins(target_cache_dir=raw_dir / "onchain")
    print(f"  Stablecoin daily snapshots: {len(stablecoin_records)}")
    pilot_report["datasets"]["defillama_stablecoins"] = {
        "snapshots_count": len(stablecoin_records),
        "first_date": stablecoin_records[0].date if stablecoin_records else None,
        "last_date": stablecoin_records[-1].date if stablecoin_records else None,
        "latest_total_circulating_usd": stablecoin_records[-1].total_circulating_usd if stablecoin_records else None,
    }

    # ── 9. Derived Feature Diagnostics ─────────────────────────────────────────
    print("\n=== Computing Derived Feature Diagnostics from Pilot Data ===")
    
    # A. Microstructure from AggTrades: Taker Imbalance & VWAP
    if records_aggtrades:
        buy_vol = sum(t.quantity for t in records_aggtrades if not t.is_buyer_maker)
        sell_vol = sum(t.quantity for t in records_aggtrades if t.is_buyer_maker)
        total_vol = buy_vol + sell_vol
        imbalance = (buy_vol - sell_vol) / total_vol if total_vol > 0 else 0.0
        vwap = sum(t.price * t.quantity for t in records_aggtrades) / total_vol if total_vol > 0 else 0.0
        pilot_report["derived_feature_diagnostics"]["aggtrade_microstructure"] = {
            "sample_trades_analyzed": len(records_aggtrades),
            "taker_buy_volume": round(buy_vol, 4),
            "taker_sell_volume": round(sell_vol, 4),
            "order_flow_imbalance": round(imbalance, 4),
            "vwap_usd": round(vwap, 2),
        }
        print(f"  Microstructure: Taker Buy={buy_vol:.2f}, Sell={sell_vol:.2f}, Imbalance={imbalance:.4f}, VWAP=${vwap:.2f}")

    # B. Derivatives: Funding Regime & OI
    if records_funding and records_metrics:
        avg_funding = sum(f.funding_rate for f in records_funding) / len(records_funding)
        latest_oi = records_metrics[-1].sum_open_interest_usd
        pilot_report["derived_feature_diagnostics"]["derivatives_regime"] = {
            "june_2023_avg_8h_funding": round(avg_funding, 8),
            "funding_annualized_pct": round(avg_funding * 3 * 365 * 100, 2),
            "latest_oi_usd": round(latest_oi, 2),
        }
        print(f"  Derivatives: June 2023 Avg Funding={avg_funding:.8f} (Annualized={avg_funding*3*365*100:.2f}%), OI=${latest_oi:,.0f}")

    # C. Macro Yield Curve Inversion (10Y - 2Y)
    if treasury_records:
        latest_tr = treasury_records[-1]
        slope_10_2 = (latest_tr.yield_10y or 0.0) - (latest_tr.yield_2y or 0.0)
        pilot_report["derived_feature_diagnostics"]["macro_yield_curve"] = {
            "observation_date": latest_tr.date,
            "yield_2y": latest_tr.yield_2y,
            "yield_10y": latest_tr.yield_10y,
            "curve_slope_10_2_bps": round(slope_10_2 * 100, 1),
            "inversion_status": "INVERTED" if slope_10_2 < 0 else "NORMAL",
        }
        print(f"  Macro: Date={latest_tr.date}, 10Y={latest_tr.yield_10y}%, 2Y={latest_tr.yield_2y}%, 10Y-2Y Slope={slope_10_2*100:.1f} bps ({'INVERTED' if slope_10_2 < 0 else 'NORMAL'})")

    report_path = report_dir / "m2_pilot_verification_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(pilot_report, f, indent=2)

    print(f"\n[DONE] Pilot execution complete. Report written to {report_path}")
    return pilot_report


if __name__ == "__main__":
    run_pilot()
