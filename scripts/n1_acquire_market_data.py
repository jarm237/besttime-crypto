"""
scripts/n1_acquire_market_data.py

Fresh, checksum-verified acquisition of N1 raw sources:
  H1 (cross-sectional market structure): Binance Spot 1h klines, 13 USDT pairs,
     from each pair's first archived month to 2025-12 (incl. delisted EOSUSDT).
  H2 (order-book liquidity): Binance USD-M daily bookDepth, BTCUSDT & ETHUSDT,
     2023-01-01 (archive start) to 2025-12-31.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from neural_trading.n1.acquisition import (  # noqa: E402
    spot_kline_jobs, um_bookdepth_jobs, run_jobs, write_manifest,
)

RAW = REPO / "data" / "historical" / "neural_n1" / "raw"
MAN = REPO / "research" / "neural_n1" / "manifests"

# First archived month per symbol (probed via HEAD on data.binance.vision).
SPOT_UNIVERSE = {
    "BTCUSDT": "2017-08", "ETHUSDT": "2017-08", "BNBUSDT": "2017-11",
    "LTCUSDT": "2017-12", "ADAUSDT": "2018-04", "XRPUSDT": "2018-05",
    "EOSUSDT": "2018-05", "XLMUSDT": "2018-05", "TRXUSDT": "2018-06",
    "ETCUSDT": "2018-06", "LINKUSDT": "2019-01", "DOGEUSDT": "2019-07",
    "SOLUSDT": "2020-08",
}


def main(which: str) -> None:
    if which in ("spot", "all"):
        jobs = []
        for s, fm in SPOT_UNIVERSE.items():
            # step back up to 6 months so the true first archived month is found, not assumed
            y, m = map(int, fm.split("-"))
            m -= 6
            while m <= 0:
                y, m = y - 1, m + 12
            jobs += list(spot_kline_jobs(s, f"{max(y, 2017)}-{m:02d}" if y >= 2017 else "2017-01", RAW))
        print(f"[spot] {len(jobs)} monthly files requested", flush=True)
        recs = run_jobs(jobs, workers=24)
        write_manifest(recs, MAN / "n1_spot_klines_1h_manifest.json", {
            "source_identity": "binance_vision_spot_monthly_klines",
            "official_download_location": "https://data.binance.vision/data/spot/monthly/klines/<SYMBOL>/1h/",
            "schema": ["open_time", "open", "high", "low", "close", "volume", "close_time",
                       "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"],
            "event_time": "kline open_time (UTC); bar covers [open_time, close_time]",
            "available_at": "close_time + 1 ms (bar is final only after close); archive file published after month end",
            "revision_or_correction_policy": "Binance may republish archive files; payload hash + published checksum pinned per file. A re-download with a different hash is a new dataset_version.",
            "symbol_eligibility": "Listed universe chosen ex-ante = 13 large-cap USDT pairs with Binance spot listing by 2020-08; includes delisted EOSUSDT; survivorship bias remains for pairs never considered.",
        })
    if which in ("depth", "all"):
        jobs = []
        for s in ("BTCUSDT", "ETHUSDT"):
            jobs += list(um_bookdepth_jobs(s, dt.date(2023, 1, 1), RAW))
        print(f"[depth] {len(jobs)} daily files requested", flush=True)
        recs = run_jobs(jobs, workers=24, progress_every=250)
        write_manifest(recs, MAN / "n1_um_bookdepth_manifest.json", {
            "source_identity": "binance_vision_um_daily_bookDepth",
            "official_download_location": "https://data.binance.vision/data/futures/um/daily/bookDepth/<SYMBOL>/",
            "schema": ["timestamp", "percentage", "depth", "notional"],
            "event_time": "snapshot timestamp (UTC, ~30s cadence); cumulative depth within +/-1..5% of mid on USD-M perpetual book",
            "available_at": "snapshot timestamp (observable live via exchange depth); hourly aggregates available at hour end",
            "revision_or_correction_policy": "As above; payload hash pinned.",
            "symbol_eligibility": "BTCUSDT, ETHUSDT perpetuals; archive starts 2023-01-01 (2022-12-31 returns 404).",
            "market_note": "Liquidity is observed on the USD-M perpetual book, while execution in N1 is Spot. Cross-venue liquidity is treated as information only.",
        })


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "all")
