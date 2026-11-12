"""Run N1.2 Phase C Fresh Data Acquisition and PIT Manifest Generation."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neural_trading.n1_2.acquisition import (  # noqa: E402
    acquire_ha_aggtrades_dataset,
    acquire_hb1_coinbase_dataset,
    acquire_hb2_5m_perp_spot_dataset,
    probe_unsuitable_sources,
)


def main() -> None:
    t0 = time.time()
    cache_dir = ROOT / "data" / "neural_n1_2"
    manifest_dir = ROOT / "research" / "neural_n1_2" / "manifests"
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    print("[1/4] Probing unsuitable sources (bookTicker / forced liquidation archives)...")
    rejected_probes = probe_unsuitable_sources()
    with (manifest_dir / "n1_2_rejected_sources_probe.json").open("w", encoding="utf-8") as f:
        json.dump(rejected_probes, f, indent=2)
    print(f"      Recorded {len(rejected_probes)} source suitability probes.")

    print("[2/4] Acquiring H-B1 Coinbase USD 1h candles (8 symbols, 2022-2025)...")
    hb1_manifest = acquire_hb1_coinbase_dataset(
        cache_dir=cache_dir,
        manifest_path=manifest_dir / "n1_2_coinbase_cross_venue_manifest.json",
    )
    print(
        f"      H-B1 complete: {hb1_manifest['total_products']} products, "
        f"{hb1_manifest['total_candles']} candles, sha256={hb1_manifest['panel_sha256'][:16]}..."
    )

    print("[3/4] Acquiring H-B2 Binance 5m Perp vs 5m Spot klines (8 symbols, 2022-2025, 768 archives)...")
    hb2_manifest = acquire_hb2_5m_perp_spot_dataset(
        cache_dir=cache_dir,
        manifest_path=manifest_dir / "n1_2_5m_perp_spot_manifest.json",
        max_workers=8,
    )
    print(
        f"      H-B2 complete: {hb2_manifest['total_verified_archives']} archives verified, "
        f"{hb2_manifest['total_matched_5m_bars']} matched 5m bars."
    )

    print("[4/4] Acquiring H-A Binance Spot monthly tick-by-tick aggTrades (5 symbols, 2022-2025, 240 archives)...")
    ha_manifest = acquire_ha_aggtrades_dataset(
        cache_dir=cache_dir,
        manifest_path=manifest_dir / "n1_2_aggtrades_manifest.json",
        max_workers=6,
    )
    print(
        f"      H-A complete: {ha_manifest['total_archives']} archives verified, "
        f"{ha_manifest['total_raw_aggtrades_processed']:,} raw tick aggTrades processed "
        f"({ha_manifest['total_compressed_bytes'] / (1024**2):.1f} MB compressed)."
    )

    summary = {
        "elapsed_seconds": round(time.time() - t0, 2),
        "rejected_probes_count": len(rejected_probes),
        "hb1_coinbase": {
            "total_products": hb1_manifest["total_products"],
            "total_candles": hb1_manifest["total_candles"],
            "panel_sha256": hb1_manifest["panel_sha256"],
        },
        "hb2_5m_perp_spot": {
            "total_verified_archives": hb2_manifest["total_verified_archives"],
            "checksum_verified_count": hb2_manifest["checksum_verified_count"],
            "total_matched_5m_bars": hb2_manifest["total_matched_5m_bars"],
            "panel_sha256": hb2_manifest["panel_sha256"],
        },
        "ha_aggtrades": {
            "total_archives": ha_manifest["total_archives"],
            "checksum_verified_count": ha_manifest["checksum_verified_count"],
            "total_raw_aggtrades_processed": ha_manifest["total_raw_aggtrades_processed"],
            "total_compressed_bytes": ha_manifest["total_compressed_bytes"],
            "panel_sha256": ha_manifest["panel_sha256"],
        },
    }
    with (manifest_dir / "n1_2_acquisition_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"Done in {summary['elapsed_seconds']}s.")


if __name__ == "__main__":
    main()
