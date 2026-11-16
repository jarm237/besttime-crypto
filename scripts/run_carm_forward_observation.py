"""Bounded Authentic Forward Observation Runner for Workstream B CARM Shadow Observer.

Connects strictly to read-only public market data, executes authentic forward ticks,
records entries in the forward valuation ledger, and persists durable observer state.

Guarantees:
  - ZERO real trading or order submission.
  - Authentic live market data from Binance public REST.
  - Idempotent recovery across runs.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

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
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("carm_forward_runner")


def run_bounded_forward_session(
    n_ticks: int = 3,
    tick_delay_seconds: float = 2.0,
    state_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Execute a bounded authentic forward observation session."""
    assert REAL_TRADING is False, "REAL_TRADING must be disabled"
    assert LIVE_EXCHANGE_PERMISSION is False, "LIVE_EXCHANGE_PERMISSION must be disabled"
    assert PRODUCTION_CANDIDATE is False, "PRODUCTION_CANDIDATE must be False"

    state_dir = state_dir or (REPO_ROOT / "logs" / "carm_observer")
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "carm_state.json"
    ledger_file = state_dir / "valuation_ledger.jsonl"
    snapshot_file = state_dir / "first_forward_evidence_snapshot.json"

    # 1. Recover existing state or initialize fresh observer
    if state_file.exists():
        logger.info("Recovering existing observer state from %s", state_file)
        observer = CarmShadowObserver.load_state(state_file)
    else:
        logger.info("Initializing fresh CarmShadowObserver instance")
        observer = CarmShadowObserver(
            universe=CANONICAL_UNIVERSE,
            initial_capital_usd=10_000.0,
            fee_bps=12.0,
            rebalance_interval_hours=168,
            top_k=3,
            require_positive_momentum=True,
        )

    ledger = CarmValuationLedger(log_path=ledger_file)
    data_provider = CarmMarketDataProvider()

    logger.info("Beginning bounded forward observation session: %d ticks", n_ticks)
    session_start_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    tick_results = []

    for i in range(n_ticks):
        tick_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            prices, observations = data_provider.fetch_live_ticker_snapshot(CANONICAL_UNIVERSE)
        except Exception as e:
            logger.error("Market data fetch failed on tick %d: %s", i + 1, e)
            return {
                "status": "ENVIRONMENT_BLOCKED",
                "error": str(e),
                "timestamp_utc": tick_ts,
            }

        res = observer.step(
            timestamp=tick_ts,
            prices=prices,
            is_forward=True,
            observation_id=f"forward-obs-{i + 1}",
        )
        ledger.append(res)
        tick_results.append(res)

        logger.info(
            "Tick %d/%d at %s: CARM Eq=$%.2f, BTC Eq=$%.2f, Cash Eq=$%.2f [Status=%s]",
            i + 1,
            n_ticks,
            tick_ts,
            res.carm_equity,
            res.btc_bh_equity,
            res.cash_equity,
            res.data_quality_status,
        )

        if i < n_ticks - 1 and tick_delay_seconds > 0:
            time.sleep(tick_delay_seconds)

    # 2. Persist updated observer state
    state_data = observer.save_state(state_file)
    logger.info("Observer state persisted to %s", state_file)

    # 3. Calculate Comparative Scorecard
    ledger_df = ledger.to_dataframe()
    scorecard_metrics = CarmComparativeScorecard.calculate_metrics(ledger_df)
    scorecard_md = CarmComparativeScorecard.generate_markdown_scorecard(scorecard_metrics)

    evidence_snapshot = {
        "status": "FORWARD_OBSERVATION_ACTIVE",
        "session_start_utc": session_start_utc,
        "session_end_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "strategy_version": observer.carm_portfolio.portfolio_name,
        "configuration_fingerprint": observer.configuration_fingerprint,
        "canonical_universe": CANONICAL_UNIVERSE,
        "initial_capital_parity_usd": observer.initial_capital_usd,
        "counters": {
            "authentic_forward_observations": observer.authentic_forward_observations_count,
            "historical_warmup_observations": observer.historical_warmup_observations_count,
            "rejected_observations": observer.rejected_observations_count,
            "scheduled_rebalance_decisions": observer.scheduled_rebalances_count,
            "modeled_virtual_fills": observer.modeled_virtual_fills_count,
            "portfolio_valuations": observer.portfolio_valuations_count,
        },
        "latest_portfolio_equity": {
            "carm_equity_usd": observer.carm_portfolio.equity_usd,
            "btc_bh_equity_usd": observer.btc_portfolio.equity_usd,
            "cash_equity_usd": observer.cash_portfolio.equity_usd,
            "carm_net_return_pct": round(((observer.carm_portfolio.equity_usd / observer.initial_capital_usd) - 1.0) * 100.0, 4),
            "btc_bh_net_return_pct": round(((observer.btc_portfolio.equity_usd / observer.initial_capital_usd) - 1.0) * 100.0, 4),
            "cash_net_return_pct": 0.0,
        },
        "latest_prices": {sym: prices[sym] for sym in CANONICAL_UNIVERSE if sym in prices},
        "scorecard_markdown": scorecard_md,
    }

    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(evidence_snapshot, f, indent=2)
    logger.info("Evidence snapshot written to %s", snapshot_file)

    return evidence_snapshot


if __name__ == "__main__":
    snapshot = run_bounded_forward_session(n_ticks=3, tick_delay_seconds=1.5)
    print("\n" + "=" * 60)
    print("AUTHENTIC FORWARD OBSERVATION EVIDENCE SNAPSHOT")
    print("=" * 60)
    print(f"Status:                      {snapshot.get('status')}")
    print(f"Configuration Fingerprint:   {snapshot.get('configuration_fingerprint')}")
    print(f"Forward Observations:        {snapshot.get('counters', {}).get('authentic_forward_observations')}")
    print(f"Modeled Virtual Fills:       {snapshot.get('counters', {}).get('modeled_virtual_fills')}")
    print(f"Portfolio Valuations:        {snapshot.get('counters', {}).get('portfolio_valuations')}")
    print(f"CARM Equity:                 ${snapshot.get('latest_portfolio_equity', {}).get('carm_equity_usd'):,.2f}")
    print(f"BTC Buy & Hold Equity:       ${snapshot.get('latest_portfolio_equity', {}).get('btc_bh_equity_usd'):,.2f}")
    print(f"Cash Equity:                 ${snapshot.get('latest_portfolio_equity', {}).get('cash_equity_usd'):,.2f}")
    print("\nScorecard:")
    print(snapshot.get("scorecard_markdown"))
