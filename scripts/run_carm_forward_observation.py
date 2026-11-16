"""Bounded & Continuous Authentic Forward Observation Runner for Workstream B CARM Shadow Observer.

Connects strictly to read-only public market data, executes authentic forward ticks,
records entries in the forward valuation ledger, and persists durable observer state.

Guarantees:
  - ZERO real trading or order submission (read-only prospective observer).
  - Authentic live market data from Binance public REST (ticker and closed 1h klines).
  - CLOSED 1H BARS ONLY: Hourly momentum signals use authentic closed klines, never ticker snapshots.
  - REBALANCE TYPING: Explicit separation of INCEPTION, FORCED_PROBE, and SCHEDULED_WEEKLY rebalances.
  - ATOMIC PERSISTENCE & CRASH CONSISTENCY: State saved atomically with tempfile + replace.
  - STARTUP RECONCILIATION: Valuation ledger reconciled against state timestamp on restart.
  - CONTINUOUS & BOUNDED MODES: Supports both discrete cron ticks and continuous background loops.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.research.carm_market_data import (
    CANONICAL_UNIVERSE,
    CarmMarketDataProvider,
)
from btc_scraper.research.carm_scorecard import (
    CarmComparativeScorecard,
    CarmValuationLedger,
)
from btc_scraper.research.carm_shadow_observer import (
    CarmShadowObserver,
    LIVE_EXCHANGE_PERMISSION,
    PRODUCTION_CANDIDATE,
    REAL_TRADING,
    STRATEGY_VERSION_CANONICAL,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("carm_forward_runner")


def sync_closed_hourly_klines(
    observer: CarmShadowObserver,
    data_provider: CarmMarketDataProvider,
    state_file: Path,
) -> int:
    """Sync authentic closed 1h klines into the observer's hourly buffer.

    Guarantees that observer always has the latest closed bars without
    ever writing ticker prices into the signal history.
    """
    now_utc = datetime.now(timezone.utc)
    required_history_len = observer.rebalance_interval_hours + observer.causal_delay_bars + 1
    last_closed_hour = (now_utc - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)

    needs_fetch = False
    if len(observer.hourly_price_history) < required_history_len:
        needs_fetch = True
    elif observer.hourly_price_history and observer.hourly_price_history[-1][0] < last_closed_hour:
        needs_fetch = True

    if not needs_fetch:
        return 0

    logger.info(
        "Syncing authentic closed 1h klines (current buffer: %d bars, latest: %s)...",
        len(observer.hourly_price_history),
        observer.hourly_price_history[-1][0].isoformat() if observer.hourly_price_history else "NONE",
    )
    try:
        klines = data_provider.fetch_recent_hourly_klines(CANONICAL_UNIVERSE, limit=200, now_utc=now_utc)
        added = observer.ingest_hourly_bars(klines)
        logger.info("Ingested %d authentic closed hourly bars. Total buffer: %d bars.", added, len(observer.hourly_price_history))
        observer.save_state(state_file)
        return added
    except Exception as e:
        logger.warning("Could not sync closed klines from Binance: %s. Continuing with existing buffer.", e)
        return 0


def run_forward_session(
    n_ticks: Optional[int] = 3,
    tick_delay_seconds: float = 2.0,
    probe_rebalance: bool = False,
    continuous: bool = False,
    state_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Execute authentic forward observation session with crash consistency."""
    assert REAL_TRADING is False, "REAL_TRADING must be disabled"
    assert LIVE_EXCHANGE_PERMISSION is False, "LIVE_EXCHANGE_PERMISSION must be disabled"
    assert PRODUCTION_CANDIDATE is False, "PRODUCTION_CANDIDATE must be False"

    if probe_rebalance:
        state_dir = state_dir or (REPO_ROOT / "logs" / "carm_observer" / "probe_sandbox")
        logger.warning("FORCED PROBE MODE: Using isolated sandbox at %s (canonical forward state is protected)", state_dir)
    else:
        state_dir = state_dir or (REPO_ROOT / "logs" / "carm_observer" / "canonical_epoch")
        logger.info("CANONICAL FORWARD MODE: Using clean canonical epoch directory at %s", state_dir)

    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "carm_state.json"
    ledger_file = state_dir / "valuation_ledger.jsonl"
    rejected_file = state_dir / "rejected_observations.jsonl"
    snapshot_file = state_dir / "first_forward_evidence_snapshot.json"

    data_provider = CarmMarketDataProvider()

    # 1. Recover existing state or initialize fresh observer
    if state_file.exists():
        logger.info("Recovering existing observer state from %s", state_file)
        observer = CarmShadowObserver.load_state(state_file)
    else:
        logger.info("Initializing fresh CarmShadowObserver instance (%s parity)", STRATEGY_VERSION_CANONICAL)
        observer = CarmShadowObserver(
            universe=CANONICAL_UNIVERSE,
            initial_capital_usd=10_000.0,
            fee_bps=12.0,
            rebalance_interval_hours=168,
            top_k=3,
            causal_delay_bars=2,  # shift(2) matching 0d9f6660
            require_positive_momentum=False,  # canonical research parity
            initial_allocation_mode="EQUAL_WEIGHT",  # 0d9f6660 parity
        )

    # 2. Reconcile ledger with state on startup
    ledger = CarmValuationLedger(log_path=ledger_file)
    last_accepted_ts = (
        observer.last_accepted_timestamp_utc.isoformat()
        if observer.last_accepted_timestamp_utc
        else None
    )
    dropped = ledger.reconcile_with_state(last_accepted_ts)
    if dropped > 0:
        logger.info("Reconciled valuation ledger: truncated %d uncheckpointed trailing records", dropped)

    # 3. Synchronize Closed 1h Klines from Binance Public API
    sync_closed_hourly_klines(observer, data_provider, state_file)

    session_start_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    logger.info(
        "Starting forward observation session (continuous=%s, max_ticks=%s, probe_rebalance=%s)",
        continuous,
        n_ticks if not continuous else "UNLIMITED",
        probe_rebalance,
    )

    tick_count = 0
    running = True

    def _sig_handler(signum, frame):
        nonlocal running
        logger.info("Signal received, safely terminating observation session...")
        running = False

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    prices: Dict[str, float] = {}

    while running:
        tick_count += 1
        tick_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # Periodically check if a new 1h candle has closed
        sync_closed_hourly_klines(observer, data_provider, state_file)

        try:
            prices, observations = data_provider.fetch_live_ticker_snapshot(CANONICAL_UNIVERSE)
        except Exception as e:
            logger.error("Market data fetch failed on tick %d: %s", tick_count, e)
            if not continuous:
                return {
                    "status": "ENVIRONMENT_BLOCKED",
                    "error": str(e),
                    "timestamp_utc": tick_ts,
                }
            time.sleep(tick_delay_seconds)
            continue

        # Trigger rebalance on tick 1 only if probe_rebalance was explicitly requested
        should_probe = probe_rebalance if (tick_count == 1) else False
        res = observer.step(
            timestamp=tick_ts,
            prices=prices,
            is_forward=True,
            observation_id=f"forward-obs-{tick_count}",
            force_rebalance=should_probe,
        )

        # Synchronous crash consistency: save state and ledger together for valid observations
        if res.data_quality_status == "VALID":
            ledger.append(res)
            observer.save_state(state_file)
        else:
            with open(rejected_file, "a", encoding="utf-8") as rf:
                rf.write(json.dumps({
                    "timestamp": tick_ts,
                    "status": res.data_quality_status,
                    "reason": res.rejection_reason,
                }) + "\n")

        logger.info(
            "Tick %d at %s: CARM Eq=$%.2f, BTC Eq=$%.2f, Cash Eq=$%.2f [Status=%s, Rebal=%s]",
            tick_count,
            tick_ts,
            res.carm_equity,
            res.btc_bh_equity,
            res.cash_equity,
            res.data_quality_status,
            res.rebalance_triggered,
        )

        if not continuous and n_ticks is not None and tick_count >= n_ticks:
            break

        if running and tick_delay_seconds > 0:
            time.sleep(tick_delay_seconds)

    # 4. Generate Final Comparative Scorecard & Evidence Snapshot
    ledger_df = ledger.to_dataframe()
    scorecard_metrics = CarmComparativeScorecard.calculate_metrics(ledger_df)
    scorecard_md = CarmComparativeScorecard.generate_markdown_scorecard(scorecard_metrics)

    evidence_snapshot = {
        "status": "FORWARD_OBSERVATION_ACTIVE",
        "epoch_id": observer.epoch_id,
        "session_start_utc": session_start_utc,
        "session_end_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "strategy_version": observer.strategy_version,
        "configuration_fingerprint": observer.configuration_fingerprint,
        "canonical_universe": CANONICAL_UNIVERSE,
        "initial_capital_parity_usd": observer.initial_capital_usd,
        "hourly_bars_in_buffer": len(observer.hourly_price_history),
        "counters": {
            "authentic_forward_observations": observer.authentic_forward_observations_count,
            "historical_warmup_observations": observer.historical_warmup_observations_count,
            "rejected_observations": observer.rejected_observations_count,
            "inception_rebalances": observer.inception_rebalances_count,
            "scheduled_weekly_rebalances": observer.scheduled_rebalances_count,
            "forced_probes": observer.forced_probes_count,
            "modeled_virtual_fills": observer.modeled_virtual_fills_count,
            "portfolio_valuations": observer.portfolio_valuations_count,
        },
        "latest_portfolio_equity": {
            "carm_equity_usd": round(observer.carm_portfolio.equity_usd, 2),
            "btc_bh_equity_usd": round(observer.btc_portfolio.equity_usd, 2),
            "cash_equity_usd": round(observer.cash_portfolio.equity_usd, 2),
            "carm_net_return_pct": round(((observer.carm_portfolio.equity_usd / observer.initial_capital_usd) - 1.0) * 100.0, 4),
            "btc_bh_net_return_pct": round(((observer.btc_portfolio.equity_usd / observer.initial_capital_usd) - 1.0) * 100.0, 4),
            "cash_net_return_pct": 0.0,
        },
        "latest_holdings": {
            "carm": {k: round(v, 6) for k, v in observer.carm_portfolio.holdings.items() if v > 0},
            "btc_bh": {k: round(v, 6) for k, v in observer.btc_portfolio.holdings.items() if v > 0},
        },
        "latest_prices": {sym: prices[sym] for sym in CANONICAL_UNIVERSE if sym in prices},
        "scorecard_markdown": scorecard_md,
    }

    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(evidence_snapshot, f, indent=2)
    logger.info("Evidence snapshot written to %s", snapshot_file)

    return evidence_snapshot


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CARM Read-Only Forward Runner")
    parser.add_argument("--ticks", type=int, default=3, help="Number of forward ticks for bounded run")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay between ticks in seconds")
    parser.add_argument("--continuous", action="store_true", help="Run indefinitely in continuous observation mode")
    parser.add_argument("--interval", type=float, default=60.0, help="Interval between ticks in continuous mode")
    parser.add_argument("--probe-rebalance", action="store_true", help="Execute an explicit forced probe rebalance on tick 1")
    parser.add_argument("--rebalance", action="store_true", help="Alias for --probe-rebalance")
    args = parser.parse_args()

    probe = args.probe_rebalance or args.rebalance
    delay = args.interval if args.continuous else args.delay

    snapshot = run_forward_session(
        n_ticks=None if args.continuous else args.ticks,
        tick_delay_seconds=delay,
        probe_rebalance=probe,
        continuous=args.continuous,
    )
    print("\n" + "=" * 60)
    print("AUTHENTIC FORWARD OBSERVATION EVIDENCE SNAPSHOT")
    print("=" * 60)
    print(f"Status:                      {snapshot.get('status')}")
    print(f"Epoch ID:                    {snapshot.get('epoch_id')}")
    print(f"Strategy Version:            {snapshot.get('strategy_version')}")
    print(f"Configuration Fingerprint:   {snapshot.get('configuration_fingerprint')}")
    print(f"Hourly Bars In Buffer:       {snapshot.get('hourly_bars_in_buffer')}")
    print(f"Forward Observations:        {snapshot.get('counters', {}).get('authentic_forward_observations')}")
    print(f"Inception Rebalances:        {snapshot.get('counters', {}).get('inception_rebalances')}")
    print(f"Scheduled Rebalances:        {snapshot.get('counters', {}).get('scheduled_weekly_rebalances')}")
    print(f"Forced Probes:               {snapshot.get('counters', {}).get('forced_probes')}")
    print(f"Modeled Virtual Fills:       {snapshot.get('counters', {}).get('modeled_virtual_fills')}")
    print(f"Portfolio Valuations:        {snapshot.get('counters', {}).get('portfolio_valuations')}")
    print(f"CARM Equity:                 ${snapshot.get('latest_portfolio_equity', {}).get('carm_equity_usd'):,.2f}")
    print(f"BTC Buy & Hold Equity:       ${snapshot.get('latest_portfolio_equity', {}).get('btc_bh_equity_usd'):,.2f}")
    print(f"Cash Equity:                 ${snapshot.get('latest_portfolio_equity', {}).get('cash_equity_usd'):,.2f}")
    print("\nScorecard:")
    print(snapshot.get("scorecard_markdown"))
