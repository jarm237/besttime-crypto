"""Targeted Tests for Track A v1 Forward Paper Observer.

Validates:
1. Stale historical data fails closed (not used for forward fill).
2. Current incomplete daily candle is strictly excluded from signals.
3. Execution timestamp matches causal execution window [01:00, 02:00) UTC.
4. Double --step is strictly idempotent (no duplicate fees/trades).
5. Crash recovery restores state from append-only ledger.
6. Missing market data fails closed.
7. Cash and BTC holdings remain non-negative.
8. Mark-to-market updates NAV without creating spurious orders.
9. Paper events are isolated (broker_connected=False, SIMULATED_FILL).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from scripts.run_track_a_v1_paper_observer import (
    BookTickerSnapshot,
    DailyKline,
    DataUnavailableError,
    MarketDataProvider,
    evaluate_observer,
    load_paper_state,
    merge_forward_daily_candles,
    recover_state_from_ledger,
    save_paper_state_atomic,
)


class MockMarketDataProvider(MarketDataProvider):
    """Deterministic mock provider for offline observer testing."""

    def __init__(
        self,
        server_time_ms: int,
        klines: list[DailyKline] | None = None,
        ticker: BookTickerSnapshot | None = None,
        raise_on_time: bool = False,
        raise_on_ticker: bool = False,
    ):
        self._server_time_ms = server_time_ms
        self._klines = klines or []
        self._ticker = ticker
        self._raise_on_time = raise_on_time
        self._raise_on_ticker = raise_on_ticker

    def get_server_time_ms(self) -> int:
        if self._raise_on_time:
            raise DataUnavailableError("Simulated server time outage")
        return self._server_time_ms

    def get_daily_klines(self, limit: int = 120) -> list[DailyKline]:
        return self._klines[-limit:] if self._klines else []

    def get_book_ticker(self) -> BookTickerSnapshot:
        if self._raise_on_ticker:
            raise DataUnavailableError("Simulated ticker outage")
        if self._ticker is None:
            raise DataUnavailableError("No ticker configured")
        return self._ticker


def _generate_synthetic_warmup(days: int = 100, end_dt: str = "2026-11-18") -> pd.DataFrame:
    """Generate deterministic warmup daily candles."""
    dates = pd.date_range(end=end_dt, periods=days, freq="D", tz="UTC")
    closes = np.full(days, 60000.0)
    # Give upward breakout on last 2 days to trigger approved exposure = 1.0
    closes[-2] = 70000.0
    closes[-1] = 70000.0

    df = pd.DataFrame({
        "open": closes - 50.0,
        "high": closes + 500.0,
        "low": closes - 500.0,
        "close": closes,
        "volume": 1000.0,
        "hour_count": 24,
    }, index=dates)
    return df


@pytest.fixture
def test_env(tmp_path: Path):
    """Prepare isolated temporary directory for state, ledger, and warmup."""
    state_file = tmp_path / "track_a_v1_paper_state.json"
    ledger_file = tmp_path / "track_a_v1_paper_ledger.csv"
    warmup_file = tmp_path / "track_a_warmup_daily.csv"

    warmup_df = _generate_synthetic_warmup(days=100, end_dt="2026-11-18")
    warmup_df.to_csv(warmup_file)

    return {
        "tmp_path": tmp_path,
        "state_file": state_file,
        "ledger_file": ledger_file,
        "warmup_file": warmup_file,
        "warmup_df": warmup_df,
    }


def test_stale_quote_fails_closed(test_env):
    """Verify observer fails closed when market quote is older than MAX_QUOTE_AGE_SECONDS."""
    # Server time: 2026-11-19 01:30:00 UTC
    server_dt = pd.Timestamp("2026-11-19 01:30:00", tz="UTC")
    server_time_ms = int(server_dt.timestamp() * 1000)

    # Stale ticker quote: 5 minutes older than server time
    stale_quote_dt = server_dt - pd.Timedelta(seconds=300)
    ticker = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=65000.0,
        bid_qty=1.0,
        ask_price=65005.0,
        ask_qty=1.0,
        mid_price=65002.5,
        spread_bps=0.77,
        source_timestamp_utc=stale_quote_dt,
    )

    provider = MockMarketDataProvider(server_time_ms=server_time_ms, ticker=ticker)

    with pytest.raises(DataUnavailableError, match="Stale quote"):
        evaluate_observer(
            provider=provider,
            state_file=test_env["state_file"],
            ledger_file=test_env["ledger_file"],
            repo_root=test_env["tmp_path"],
        )

    # State file must not exist (no mutations)
    assert not test_env["state_file"].exists()
    assert not test_env["ledger_file"].exists()


def test_incomplete_daily_candle_excluded_from_signals(test_env):
    """Verify that current running daily candle is strictly dropped from signal computation."""
    server_dt = pd.Timestamp("2026-11-19 12:00:00", tz="UTC")
    server_time_ms = int(server_dt.timestamp() * 1000)

    # Create 1 completed candle (Nov 18) and 1 incomplete candle (Nov 19 running)
    completed_kline = DailyKline(
        open_time_ms=int(pd.Timestamp("2026-11-18 00:00:00", tz="UTC").timestamp() * 1000),
        open=60000.0,
        high=61000.0,
        low=59000.0,
        close=60500.0,
        volume=500.0,
        close_time_ms=int(pd.Timestamp("2026-11-18 23:59:59.999", tz="UTC").timestamp() * 1000),
    )
    incomplete_kline = DailyKline(
        open_time_ms=int(pd.Timestamp("2026-11-19 00:00:00", tz="UTC").timestamp() * 1000),
        open=60500.0,
        high=99999.0,  # Extreme spike in incomplete candle
        low=60000.0,
        close=99999.0,
        volume=100.0,
        close_time_ms=int(pd.Timestamp("2026-11-19 23:59:59.999", tz="UTC").timestamp() * 1000),
    )

    assert completed_kline.is_completed(server_time_ms) is True
    assert incomplete_kline.is_completed(server_time_ms) is False

    merged_df, num_added, num_dropped = merge_forward_daily_candles(
        warmup_df=test_env["warmup_df"],
        klines=[completed_kline, incomplete_kline],
        server_time_ms=server_time_ms,
    )

    assert num_dropped == 1
    # Check that Nov 19 spike is NOT in merged_df
    assert pd.Timestamp("2026-11-19 00:00:00", tz="UTC") not in merged_df.index
    assert merged_df["high"].max() < 90000.0


def test_causal_execution_window_matching(test_env):
    """Verify execution window rules: [01:00, 02:00) UTC is eligible, other times are rejected."""
    # Case 1: Inside window (01:15 UTC on Nov 19)
    dt_eligible = pd.Timestamp("2026-11-19 01:15:00", tz="UTC")
    ticker = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70000.0,
        bid_qty=1.0,
        ask_price=70002.0,
        ask_qty=1.0,
        mid_price=70001.0,
        spread_bps=0.28,
        source_timestamp_utc=dt_eligible,
    )

    provider_eligible = MockMarketDataProvider(
        server_time_ms=int(dt_eligible.timestamp() * 1000),
        ticker=ticker,
    )

    res_eligible = evaluate_observer(
        provider=provider_eligible,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        repo_root=test_env["tmp_path"],
    )
    assert res_eligible["exec_eligibility"] == "ELIGIBLE"
    assert res_eligible["action"] == "REBALANCE"
    assert res_eligible["post_btc_holdings"] > 0.0

    # Case 2: Too early (00:30 UTC on Nov 20) -> should be PENDING
    state_file_2 = test_env["tmp_path"] / "state_2.json"
    ledger_file_2 = test_env["tmp_path"] / "ledger_2.csv"
    dt_early = pd.Timestamp("2026-11-19 00:30:00", tz="UTC")
    ticker_early = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70000.0,
        bid_qty=1.0,
        ask_price=70002.0,
        ask_qty=1.0,
        mid_price=70001.0,
        spread_bps=0.28,
        source_timestamp_utc=dt_early,
    )
    provider_early = MockMarketDataProvider(
        server_time_ms=int(dt_early.timestamp() * 1000),
        ticker=ticker_early,
    )
    res_early = evaluate_observer(
        provider=provider_early,
        state_file=state_file_2,
        ledger_file=ledger_file_2,
        repo_root=test_env["tmp_path"],
    )
    assert res_early["exec_eligibility"] == "TOO_EARLY"
    assert res_early["action"] == "HOLD"
    assert res_early["post_btc_holdings"] == 0.0

    # Case 3: Missed window (05:00 UTC on Nov 19) -> MISSED_EXECUTION_WINDOW
    state_file_3 = test_env["tmp_path"] / "state_3.json"
    ledger_file_3 = test_env["tmp_path"] / "ledger_3.csv"
    dt_late = pd.Timestamp("2026-11-19 05:00:00", tz="UTC")
    ticker_late = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70000.0,
        bid_qty=1.0,
        ask_price=70002.0,
        ask_qty=1.0,
        mid_price=70001.0,
        spread_bps=0.28,
        source_timestamp_utc=dt_late,
    )
    provider_late = MockMarketDataProvider(
        server_time_ms=int(dt_late.timestamp() * 1000),
        ticker=ticker_late,
    )
    res_late = evaluate_observer(
        provider=provider_late,
        state_file=state_file_3,
        ledger_file=ledger_file_3,
        repo_root=test_env["tmp_path"],
    )
    assert res_late["exec_eligibility"] == "MISSED_EXECUTION_WINDOW"
    assert res_late["action"] == "MISSED_EXECUTION_WINDOW"
    assert res_late["post_btc_holdings"] == 0.0


def test_step_idempotency_double_step(test_env):
    """Verify running --step multiple times on the same decision is completely idempotent."""
    dt = pd.Timestamp("2026-11-19 01:30:00", tz="UTC")
    ticker = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70000.0,
        bid_qty=1.0,
        ask_price=70002.0,
        ask_qty=1.0,
        mid_price=70001.0,
        spread_bps=0.28,
        source_timestamp_utc=dt,
    )
    provider = MockMarketDataProvider(server_time_ms=int(dt.timestamp() * 1000), ticker=ticker)

    # First step
    res1 = evaluate_observer(
        provider=provider,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        repo_root=test_env["tmp_path"],
    )
    assert res1["action"] == "REBALANCE"
    assert res1["status"] == "ELIGIBLE"

    state_after_1 = load_paper_state(test_env["state_file"], test_env["ledger_file"])
    trades_1 = state_after_1["num_trades"]
    fees_1 = state_after_1["total_fees"]
    cash_1 = state_after_1["cash"]
    btc_1 = state_after_1["btc_holdings"]

    # Second step on same decision date
    res2 = evaluate_observer(
        provider=provider,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        repo_root=test_env["tmp_path"],
    )
    assert res2["status"] == "ALREADY_PROCESSED"
    assert res2["action"] == "HOLD"

    state_after_2 = load_paper_state(test_env["state_file"], test_env["ledger_file"])
    # Verify exact idempotency
    assert state_after_2["num_trades"] == trades_1
    assert state_after_2["total_fees"] == fees_1
    assert state_after_2["cash"] == cash_1
    assert state_after_2["btc_holdings"] == btc_1

    # Verify ledger only has 1 row
    df_ledger = pd.read_csv(test_env["ledger_file"])
    assert len(df_ledger) == 1


def test_crash_recovery_from_ledger(test_env):
    """Verify that deleting/corrupting state.json recovers seamlessly from ledger.csv."""
    dt = pd.Timestamp("2026-11-19 01:30:00", tz="UTC")
    ticker = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70000.0,
        bid_qty=1.0,
        ask_price=70002.0,
        ask_qty=1.0,
        mid_price=70001.0,
        spread_bps=0.28,
        source_timestamp_utc=dt,
    )
    provider = MockMarketDataProvider(server_time_ms=int(dt.timestamp() * 1000), ticker=ticker)

    evaluate_observer(
        provider=provider,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        repo_root=test_env["tmp_path"],
    )

    original_state = load_paper_state(test_env["state_file"], test_env["ledger_file"])

    # Simulate crash: corrupt state file with garbage
    with open(test_env["state_file"], "w") as f:
        f.write("{corrupt-json: syntax-error")

    recovered = load_paper_state(test_env["state_file"], test_env["ledger_file"])
    assert recovered is not None
    assert recovered["num_trades"] == original_state["num_trades"]
    assert abs(recovered["cash"] - original_state["cash"]) < 1e-6
    assert abs(recovered["btc_holdings"] - original_state["btc_holdings"]) < 1e-8
    assert recovered["last_processed_decision_date"] == original_state["last_processed_decision_date"]


def test_missing_market_data_fails_closed(test_env):
    """Verify observer fails closed when API raises error."""
    provider = MockMarketDataProvider(
        server_time_ms=int(pd.Timestamp("2026-11-19 01:30:00", tz="UTC").timestamp() * 1000),
        raise_on_ticker=True,
    )

    with pytest.raises(DataUnavailableError, match="ticker outage"):
        evaluate_observer(
            provider=provider,
            state_file=test_env["state_file"],
            ledger_file=test_env["ledger_file"],
            repo_root=test_env["tmp_path"],
        )


def test_non_negative_cash_and_holdings(test_env):
    """Verify cash and btc holdings are non-negative across buys and sells."""
    dt = pd.Timestamp("2026-11-19 01:30:00", tz="UTC")
    ticker = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70000.0,
        bid_qty=1.0,
        ask_price=70002.0,
        ask_qty=1.0,
        mid_price=70001.0,
        spread_bps=0.28,
        source_timestamp_utc=dt,
    )
    provider = MockMarketDataProvider(server_time_ms=int(dt.timestamp() * 1000), ticker=ticker)

    res = evaluate_observer(
        provider=provider,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        repo_root=test_env["tmp_path"],
    )
    assert res["post_cash"] >= 0.0
    assert res["post_btc_holdings"] >= 0.0


def test_mark_to_market_does_not_generate_orders(test_env):
    """Verify price changes within no-trade buffer update NAV without triggering orders."""
    # First create initial position
    dt1 = pd.Timestamp("2026-11-19 01:30:00", tz="UTC")
    ticker1 = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70000.0,
        bid_qty=1.0,
        ask_price=70002.0,
        ask_qty=1.0,
        mid_price=70001.0,
        spread_bps=0.28,
        source_timestamp_utc=dt1,
    )
    provider1 = MockMarketDataProvider(server_time_ms=int(dt1.timestamp() * 1000), ticker=ticker1)
    res1 = evaluate_observer(
        provider=provider1,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        repo_root=test_env["tmp_path"],
    )
    assert res1["action"] == "REBALANCE"

    # Advance to next day where approved exposure matches current weight (deviation < 20%)
    dt2 = pd.Timestamp("2026-11-20 01:30:00", tz="UTC")
    # Small price move (+2%)
    ticker2 = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=71400.0,
        bid_qty=1.0,
        ask_price=71402.0,
        ask_qty=1.0,
        mid_price=71401.0,
        spread_bps=0.28,
        source_timestamp_utc=dt2,
    )
    provider2 = MockMarketDataProvider(server_time_ms=int(dt2.timestamp() * 1000), ticker=ticker2)
    res2 = evaluate_observer(
        provider=provider2,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        repo_root=test_env["tmp_path"],
    )
    assert res2["action"] == "HOLD"
    assert res2["trade_notional"] == 0.0
    assert res2["fee"] == 0.0
    # NAV must reflect price increase
    assert res2["nav"] > res1["nav"]


def test_paper_isolation_no_broker_connection(test_env):
    """Verify paper events are strictly labeled as simulated fills with broker_connected=False."""
    dt = pd.Timestamp("2026-11-19 01:30:00", tz="UTC")
    ticker = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70000.0,
        bid_qty=1.0,
        ask_price=70002.0,
        ask_qty=1.0,
        mid_price=70001.0,
        spread_bps=0.28,
        source_timestamp_utc=dt,
    )
    provider = MockMarketDataProvider(server_time_ms=int(dt.timestamp() * 1000), ticker=ticker)

    res = evaluate_observer(
        provider=provider,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        repo_root=test_env["tmp_path"],
    )
    assert res["broker_connected"] is False
    assert res["fill_type"] == "SIMULATED_FILL"
    assert res["event_id"].startswith("FILL-")
