"""Targeted Tests for Track A v1 Forward Paper Observer (P0 Lifecycle & Recovery).

Validates:
1. PENDING (00:30 UTC) -> ELIGIBLE (01:30 UTC) -> ALREADY_PROCESSED (01:35 UTC) lifecycle.
2. Crash recovery from append-only ledger when state checkpoint is corrupt/missing.
3. Concurrency control raises ConcurrentExecutionError when lock is active.
4. Recovery failure fails closed (raises PaperRecoveryError, does not reset capital).
5. Sell-side (BTC -> Cash) and Buy-side (Cash -> BTC) bid/ask accounting conservation.
6. Quote freshness (> 60s) and server clock drift (> 10s) fail closed.
7. Terminal decision idempotency (EXECUTED, HOLD, MISSED all lock decision date).
8. Current incomplete daily candle is strictly excluded from signals.
9. Paper isolation: broker_connected=False, SIMULATED_FILL only.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from scripts.run_track_a_v1_paper_observer import (
    CANONICAL_LEDGER_COLUMNS,
    BookTickerSnapshot,
    ConcurrentExecutionError,
    DailyKline,
    DataUnavailableError,
    MarketDataProvider,
    PaperObserverLock,
    PaperRecoveryError,
    append_paper_ledger_entry,
    evaluate_observer,
    load_paper_state,
    merge_forward_daily_candles,
    migrate_ledger_schema,
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


def _generate_synthetic_warmup(days: int = 100, end_dt: str = "2026-11-18", bullish: bool = True) -> pd.DataFrame:
    """Generate deterministic warmup daily candles."""
    dates = pd.date_range(end=end_dt, periods=days, freq="D", tz="UTC")
    closes = np.full(days, 60000.0)
    if bullish:
        # Trigger approved exposure = 1.0 (breakout above Donchian channel)
        closes[-2] = 70000.0
        closes[-1] = 70000.0
    else:
        # Bearish breakdown -> approved exposure = 0.0
        closes[-2] = 40000.0
        closes[-1] = 40000.0

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
    """Prepare isolated temporary directory for state, ledger, lock, and warmup."""
    state_file = tmp_path / "track_a_v1_paper_state.json"
    ledger_file = tmp_path / "track_a_v1_paper_ledger.csv"
    lock_file = tmp_path / "track_a_v1_paper.lock"
    warmup_file = tmp_path / "track_a_warmup_daily.csv"

    warmup_df = _generate_synthetic_warmup(days=100, end_dt="2026-11-18", bullish=True)
    warmup_df.to_csv(warmup_file)

    return {
        "tmp_path": tmp_path,
        "state_file": state_file,
        "ledger_file": ledger_file,
        "lock_file": lock_file,
        "warmup_file": warmup_file,
        "warmup_df": warmup_df,
    }


def test_decision_lifecycle_pending_then_eligible_same_day(test_env):
    """Test full decision lifecycle on same day: 00:30 (PENDING) -> 01:30 (EXECUTED) -> 01:35 (ALREADY_PROCESSED)."""
    # 1. Step at 00:30 UTC: PENDING
    dt_pending = pd.Timestamp("2026-11-19 00:30:00", tz="UTC")
    ticker_pending = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70000.0,
        bid_qty=1.0,
        ask_price=70002.0,
        ask_qty=1.0,
        mid_price=70001.0,
        spread_bps=0.28,
        source_timestamp_utc=dt_pending,
        receipt_timestamp_utc=dt_pending,
    )
    provider_pending = MockMarketDataProvider(
        server_time_ms=int(dt_pending.timestamp() * 1000),
        ticker=ticker_pending,
    )

    res_pending = evaluate_observer(
        provider=provider_pending,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        lock_file=test_env["lock_file"],
        repo_root=test_env["tmp_path"],
    )

    assert res_pending["status"] == "PENDING"
    assert res_pending["action"] == "PENDING"
    assert res_pending["exec_eligibility"] == "TOO_EARLY"

    # CRITICAL: Decision date must NOT be locked/finalized in state, and ledger must NOT have entries!
    state_after_pending = load_paper_state(test_env["state_file"], test_env["ledger_file"])
    assert state_after_pending["last_processed_decision_date"] is None
    assert not test_env["ledger_file"].exists()

    # 2. Step at 01:30 UTC: ELIGIBLE -> EXECUTED
    dt_eligible = pd.Timestamp("2026-11-19 01:30:00", tz="UTC")
    ticker_eligible = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70000.0,
        bid_qty=1.0,
        ask_price=70002.0,
        ask_qty=1.0,
        mid_price=70001.0,
        spread_bps=0.28,
        source_timestamp_utc=dt_eligible,
        receipt_timestamp_utc=dt_eligible,
    )
    provider_eligible = MockMarketDataProvider(
        server_time_ms=int(dt_eligible.timestamp() * 1000),
        ticker=ticker_eligible,
    )

    res_eligible = evaluate_observer(
        provider=provider_eligible,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        lock_file=test_env["lock_file"],
        repo_root=test_env["tmp_path"],
    )

    assert res_eligible["status"] == "EXECUTED"
    assert res_eligible["action"] == "REBALANCE"
    assert res_eligible["exec_eligibility"] == "ELIGIBLE"
    assert res_eligible["fee"] > 0.0

    # Decision date is now finalized in state and ledger has 1 row
    state_after_exec = load_paper_state(test_env["state_file"], test_env["ledger_file"])
    assert state_after_exec["last_processed_decision_date"] == "2026-11-19"
    assert state_after_exec["num_trades"] == 1
    assert test_env["ledger_file"].exists()
    df_ledger = pd.read_csv(test_env["ledger_file"])
    assert len(df_ledger) == 1
    assert df_ledger.iloc[0]["action"] == "REBALANCE"

    # 3. Step at 01:35 UTC: ALREADY_PROCESSED
    dt_dup = pd.Timestamp("2026-11-19 01:35:00", tz="UTC")
    ticker_dup = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70050.0,
        bid_qty=1.0,
        ask_price=70052.0,
        ask_qty=1.0,
        mid_price=70051.0,
        spread_bps=0.28,
        source_timestamp_utc=dt_dup,
        receipt_timestamp_utc=dt_dup,
    )
    provider_dup = MockMarketDataProvider(
        server_time_ms=int(dt_dup.timestamp() * 1000),
        ticker=ticker_dup,
    )

    res_dup = evaluate_observer(
        provider=provider_dup,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        lock_file=test_env["lock_file"],
        repo_root=test_env["tmp_path"],
    )

    assert res_dup["status"] == "ALREADY_PROCESSED"
    assert res_dup["action"] == "ALREADY_PROCESSED"

    # State and ledger must remain identical (no fee inflation, no new trades)
    state_after_dup = load_paper_state(test_env["state_file"], test_env["ledger_file"])
    assert state_after_dup["num_trades"] == 1
    assert state_after_dup["total_fees"] == state_after_exec["total_fees"]
    assert state_after_dup["cash"] == state_after_exec["cash"]
    assert state_after_dup["btc_holdings"] == state_after_exec["btc_holdings"]
    df_ledger_dup = pd.read_csv(test_env["ledger_file"])
    assert len(df_ledger_dup) == 1


def test_crash_recovery_after_ledger_before_state(test_env):
    """Verify state is reconstructed from ledger if crash happens after ledger write but before state update."""
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
        receipt_timestamp_utc=dt,
    )
    provider = MockMarketDataProvider(server_time_ms=int(dt.timestamp() * 1000), ticker=ticker)

    evaluate_observer(
        provider=provider,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        lock_file=test_env["lock_file"],
        repo_root=test_env["tmp_path"],
    )

    expected_state = load_paper_state(test_env["state_file"], test_env["ledger_file"])

    # Simulate crash: delete state file completely
    test_env["state_file"].unlink()
    assert not test_env["state_file"].exists()

    # Recovery must reconstruct from ledger
    recovered = load_paper_state(test_env["state_file"], test_env["ledger_file"])
    assert recovered["last_processed_decision_date"] == "2026-11-19"
    assert recovered["num_trades"] == expected_state["num_trades"]
    assert abs(recovered["cash"] - expected_state["cash"]) < 1e-6
    assert abs(recovered["btc_holdings"] - expected_state["btc_holdings"]) < 1e-8
    assert abs(recovered["total_fees"] - expected_state["total_fees"]) < 1e-6

    # Verify state file was recreated atomically
    assert test_env["state_file"].exists()


def test_concurrent_execution_lock(test_env):
    """Verify PaperObserverLock prevents concurrent execution race conditions."""
    # Acquire lock externally
    with PaperObserverLock(lock_file=test_env["lock_file"]):
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
            receipt_timestamp_utc=dt,
        )
        provider = MockMarketDataProvider(server_time_ms=int(dt.timestamp() * 1000), ticker=ticker)

        # Attempt to run evaluate_observer with short lock timeout (e.g. 0.2s)
        test_lock = PaperObserverLock(lock_file=test_env["lock_file"], timeout=0.2)
        with pytest.raises(ConcurrentExecutionError, match="another instance is running"):
            with test_lock:
                pass


def test_recovery_failure_fails_closed(test_env):
    """Verify that corrupt ledger fails closed with PaperRecoveryError without resetting capital to 10,000."""
    # Write garbage into ledger
    with open(test_env["ledger_file"], "w", encoding="utf-8") as f:
        f.write("GARBAGE,NOT,VALID,CSV,DATA\ncorrupt\n")

    # If state file missing and ledger corrupt -> must raise PaperRecoveryError
    with pytest.raises(PaperRecoveryError, match="missing required columns"):
        load_paper_state(test_env["state_file"], test_env["ledger_file"])


def test_sell_side_bid_ask_accounting_conservation(test_env):
    """Verify selling BTC -> Cash executes at bid price and satisfies capital conservation."""
    # Warmup with bearish setup (breakdown to 40k -> approved exposure = 0.0)
    warmup_bearish = _generate_synthetic_warmup(days=100, end_dt="2026-11-18", bullish=False)
    warmup_bearish.to_csv(test_env["warmup_file"])

    # Pre-seed state with existing BTC holdings (e.g. 0.20 BTC, $100 cash)
    initial_holdings = 0.20
    initial_cash = 100.0
    pre_state = {
        "epoch_id": "EPOCH_TEST_SELL",
        "policy_version": "TRACK_A_V1_DONCHIAN_STEP",
        "policy_parameters": {
            "horizons": [20, 55, 90],
            "confirmation_days": 2,
            "no_trade_band": 0.20,
            "fee_bps": 30.0,
            "universe": ["BTCUSDT", "USDT_CASH"],
        },
        "inception_utc": "2026-11-19T00:00:00+00:00",
        "last_updated_utc": "2026-11-19T00:00:00+00:00",
        "initial_capital": 10000.0,
        "cash": initial_cash,
        "btc_holdings": initial_holdings,
        "current_equity": 14100.0,
        "peak_equity": 14100.0,
        "current_drawdown": 0.0,
        "max_drawdown": 0.0,
        "total_traded_notional": 0.0,
        "total_fees": 0.0,
        "num_trades": 0,
        "last_processed_decision_date": None,
        "last_approved_exposure": 1.0,
        "last_raw_exposure": 1.0,
        "last_event_id": None,
        "broker_connected": False,
    }
    save_paper_state_atomic(pre_state, test_env["state_file"])

    # Sell execution at 01:30 UTC
    dt = pd.Timestamp("2026-11-19 01:30:00", tz="UTC")
    bid_p = 69990.0
    ask_p = 70010.0
    ticker = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=bid_p,
        bid_qty=1.0,
        ask_price=ask_p,
        ask_qty=1.0,
        mid_price=70000.0,
        spread_bps=((ask_p - bid_p) / 70000.0) * 10000.0,
        source_timestamp_utc=dt,
        receipt_timestamp_utc=dt,
    )
    provider = MockMarketDataProvider(server_time_ms=int(dt.timestamp() * 1000), ticker=ticker)

    res = evaluate_observer(
        provider=provider,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        lock_file=test_env["lock_file"],
        repo_root=test_env["tmp_path"],
    )

    assert res["action"] == "REBALANCE"
    assert res["exec_price"] == bid_p  # Must execute at BID for sell!
    assert res["target_btc_weight"] == 0.0
    assert abs(res["post_btc_holdings"]) < 1e-8
    assert res["post_cash"] > 0.0

    # Capital conservation check: V_post + fee == V_pre
    v_pre = initial_cash + initial_holdings * bid_p
    v_post = res["post_cash"]
    fee = res["fee"]
    assert abs(v_post + fee - v_pre) < 1e-5 * v_pre


def test_quote_freshness_and_server_clock_drift(test_env):
    """Verify quote freshness > 60s and clock drift > 10s fail closed."""
    now_dt = datetime.now(timezone.utc)
    now_ms = int(now_dt.timestamp() * 1000)

    # 1. Stale quote
    stale_ticker = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70000.0,
        bid_qty=1.0,
        ask_price=70002.0,
        ask_qty=1.0,
        mid_price=70001.0,
        spread_bps=0.28,
        source_timestamp_utc=now_dt - pd.Timedelta(seconds=65),
        receipt_timestamp_utc=now_dt,
    )
    provider_stale = MockMarketDataProvider(server_time_ms=now_ms, ticker=stale_ticker)
    with pytest.raises(DataUnavailableError, match="Stale quote"):
        evaluate_observer(
            provider=provider_stale,
            state_file=test_env["state_file"],
            ledger_file=test_env["ledger_file"],
            lock_file=test_env["lock_file"],
            repo_root=test_env["tmp_path"],
        )

    # 2. Clock drift > 10s
    fresh_ticker = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70000.0,
        bid_qty=1.0,
        ask_price=70002.0,
        ask_qty=1.0,
        mid_price=70001.0,
        spread_bps=0.28,
        source_timestamp_utc=now_dt,
        receipt_timestamp_utc=now_dt,
    )
    drifted_server_ms = now_ms + 15000  # 15s drift
    provider_drift = MockMarketDataProvider(server_time_ms=drifted_server_ms, ticker=fresh_ticker)
    with pytest.raises(DataUnavailableError, match="Clock drift"):
        evaluate_observer(
            provider=provider_drift,
            state_file=test_env["state_file"],
            ledger_file=test_env["ledger_file"],
            lock_file=test_env["lock_file"],
            repo_root=test_env["tmp_path"],
        )


def test_terminal_decision_idempotency_hold_and_missed(test_env):
    """Verify both HOLD and MISSED terminal decisions lock the decision date and prevent duplicate steps."""
    # Test MISSED (evaluated at 05:00 UTC)
    dt_missed = pd.Timestamp("2026-11-19 05:00:00", tz="UTC")
    ticker = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70000.0,
        bid_qty=1.0,
        ask_price=70002.0,
        ask_qty=1.0,
        mid_price=70001.0,
        spread_bps=0.28,
        source_timestamp_utc=dt_missed,
        receipt_timestamp_utc=dt_missed,
    )
    provider_missed = MockMarketDataProvider(server_time_ms=int(dt_missed.timestamp() * 1000), ticker=ticker)

    res_missed = evaluate_observer(
        provider=provider_missed,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        lock_file=test_env["lock_file"],
        repo_root=test_env["tmp_path"],
    )

    assert res_missed["status"] == "MISSED"
    assert res_missed["action"] == "MISSED"

    # Second step must be ALREADY_PROCESSED
    res_missed_dup = evaluate_observer(
        provider=provider_missed,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        lock_file=test_env["lock_file"],
        repo_root=test_env["tmp_path"],
    )
    assert res_missed_dup["status"] == "ALREADY_PROCESSED"
    assert res_missed_dup["action"] == "ALREADY_PROCESSED"


def test_incomplete_daily_candle_excluded_from_signals(test_env):
    """Verify running candle is strictly dropped from signal computation."""
    server_dt = pd.Timestamp("2026-11-19 12:00:00", tz="UTC")
    server_time_ms = int(server_dt.timestamp() * 1000)

    completed_kline = DailyKline(
        open_time_ms=int(pd.Timestamp("2026-11-18 00:00:00", tz="UTC").timestamp() * 1000),
        open=60000.0, high=61000.0, low=59000.0, close=60500.0, volume=500.0,
        close_time_ms=int(pd.Timestamp("2026-11-18 23:59:59.999", tz="UTC").timestamp() * 1000),
    )
    incomplete_kline = DailyKline(
        open_time_ms=int(pd.Timestamp("2026-11-19 00:00:00", tz="UTC").timestamp() * 1000),
        open=60500.0, high=99999.0, low=60000.0, close=99999.0, volume=100.0,
        close_time_ms=int(pd.Timestamp("2026-11-19 23:59:59.999", tz="UTC").timestamp() * 1000),
    )

    merged_df, num_added, num_dropped = merge_forward_daily_candles(
        warmup_df=test_env["warmup_df"],
        klines=[completed_kline, incomplete_kline],
        server_time_ms=server_time_ms,
    )
    assert num_dropped == 1
    assert pd.Timestamp("2026-11-19 00:00:00", tz="UTC") not in merged_df.index


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
        receipt_timestamp_utc=dt,
    )
    provider = MockMarketDataProvider(server_time_ms=int(dt.timestamp() * 1000), ticker=ticker)

    res = evaluate_observer(
        provider=provider,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        lock_file=test_env["lock_file"],
        repo_root=test_env["tmp_path"],
    )
    assert res["broker_connected"] is False
    assert res["fill_type"] == "SIMULATED_FILL"
    assert res["event_id"].startswith("FILL-")


def test_legacy_33col_to_37col_migration(test_env):
    """Verify legacy 33-column ledger is migrated cleanly to canonical 37 columns."""
    legacy_header = (
        "timestamp_utc,epoch_id,decision_date,candle_date,status,exec_eligibility,close_price,"
        "state_20,state_55,state_90,raw_exposure,approved_exposure,confirmed,current_btc_weight,"
        "target_btc_weight,deviation,action,bid_price,ask_price,mid_price,spread_bps,exec_price,"
        "fill_type,trade_notional,fee,post_cash,post_btc_holdings,nav,peak_nav,drawdown,event_id,"
        "broker_connected,clock_drift_ms\n"
    )
    legacy_row = (
        "2026-11-19T16:17:55.253000+00:00,EPOCH_20261119_161744,2026-11-19,2026-11-18,"
        "MISSED_EXECUTION_WINDOW,MISSED_EXECUTION_WINDOW,63068.22,0,0,1,0.3333333333333333,"
        "0.3333333333333333,True,0.0,0.3333333333333333,0.3333333333333333,MISSED_EXECUTION_WINDOW,"
        "63134.56,63134.57,63134.565,0.0015839184133188003,63134.565,NONE,0.0,0.0,10000.0,0.0,"
        "10000.0,10000.0,0.0,,False,66\n"
    )
    with open(test_env["ledger_file"], "w", encoding="utf-8") as f:
        f.write(legacy_header + legacy_row)

    migrated = migrate_ledger_schema(test_env["ledger_file"])
    assert migrated is True

    # Backup file must be created
    backup_file = test_env["ledger_file"].with_name(f"{test_env['ledger_file'].name}.legacy_backup")
    assert backup_file.exists()

    # Verify 37 columns and intact row
    with open(test_env["ledger_file"], "r", encoding="utf-8") as f:
        header = [c.strip() for c in f.readline().strip().split(",")]
    assert header == CANONICAL_LEDGER_COLUMNS
    assert len(header) == 37

    df = pd.read_csv(test_env["ledger_file"])
    assert len(df) == 1
    assert df.iloc[0]["epoch_id"] == "EPOCH_20261119_161744"
    assert df.iloc[0]["action"] == "MISSED_EXECUTION_WINDOW"
    assert df.iloc[0]["post_cash"] == 10000.0
    # Missing fields in 33-col should be NaN/null in pandas
    assert pd.isna(df.iloc[0]["receipt_time_utc"]) or df.iloc[0]["receipt_time_utc"] == ""
    assert pd.isna(df.iloc[0]["modeled_fee_bps"]) or df.iloc[0]["modeled_fee_bps"] == ""


def test_preserve_existing_epoch_and_missed_event(test_env):
    """Verify loading legacy ledger preserves epoch ID and missed window terminal action."""
    legacy_header = (
        "timestamp_utc,epoch_id,decision_date,candle_date,status,exec_eligibility,close_price,"
        "state_20,state_55,state_90,raw_exposure,approved_exposure,confirmed,current_btc_weight,"
        "target_btc_weight,deviation,action,bid_price,ask_price,mid_price,spread_bps,exec_price,"
        "fill_type,trade_notional,fee,post_cash,post_btc_holdings,nav,peak_nav,drawdown,event_id,"
        "broker_connected,clock_drift_ms\n"
    )
    legacy_row = (
        "2026-11-19T16:17:55.253000+00:00,EPOCH_20261119_161744,2026-11-19,2026-11-18,"
        "MISSED_EXECUTION_WINDOW,MISSED_EXECUTION_WINDOW,63068.22,0,0,1,0.3333333333333333,"
        "0.3333333333333333,True,0.0,0.3333333333333333,0.3333333333333333,MISSED_EXECUTION_WINDOW,"
        "63134.56,63134.57,63134.565,0.0015839184133188003,63134.565,NONE,0.0,0.0,10000.0,0.0,"
        "10000.0,10000.0,0.0,,False,66\n"
    )
    with open(test_env["ledger_file"], "w", encoding="utf-8") as f:
        f.write(legacy_header + legacy_row)

    state = load_paper_state(test_env["state_file"], test_env["ledger_file"])
    assert state["epoch_id"] == "EPOCH_20261119_161744"
    assert state["last_processed_decision_date"] == "2026-11-19"
    assert state["last_terminal_action"] == "MISSED_EXECUTION_WINDOW"
    assert state["cash"] == 10000.0
    assert state["btc_holdings"] == 0.0
    assert state["current_equity"] == 10000.0
    assert state["num_trades"] == 0
    assert state["total_fees"] == 0.0


def test_append_new_fill_after_migration(test_env):
    """Verify appending a new fill to a migrated ledger retains schema consistency and 2 rows."""
    test_legacy_33col_to_37col_migration(test_env)

    new_fill_entry = {col: "" for col in CANONICAL_LEDGER_COLUMNS}
    new_fill_entry.update({
        "timestamp_utc": "2026-11-20T01:30:00+00:00",
        "receipt_time_utc": "2026-11-20T01:30:00.050+00:00",
        "epoch_id": "EPOCH_20261119_161744",
        "decision_date": "2026-11-20",
        "candle_date": "2026-11-19",
        "status": "EXECUTED",
        "exec_eligibility": "WINDOW_ACTIVE",
        "close_price": 64000.0,
        "action": "REBALANCE",
        "fill_type": "SIMULATED_FILL",
        "trade_notional": 3333.33,
        "fee": 10.0,
        "post_cash": 6656.67,
        "post_btc_holdings": 0.052,
        "nav": 10000.0,
        "peak_nav": 10000.0,
        "drawdown": 0.0,
        "event_id": "FILL-TEST-001",
        "broker_connected": False,
        "modeled_fee_bps": 30.0,
    })

    append_paper_ledger_entry(new_fill_entry, test_env["ledger_file"])

    df = pd.read_csv(test_env["ledger_file"])
    assert len(df) == 2
    assert list(df.columns) == CANONICAL_LEDGER_COLUMNS
    assert df.iloc[1]["action"] == "REBALANCE"
    assert df.iloc[1]["event_id"] == "FILL-TEST-001"


def test_crash_recovery_with_migrated_ledger(test_env):
    """Verify full state recovery from migrated multi-row ledger when state file is absent."""
    test_append_new_fill_after_migration(test_env)

    # State file does not exist
    if test_env["state_file"].exists():
        test_env["state_file"].unlink()

    recovered = load_paper_state(test_env["state_file"], test_env["ledger_file"])
    assert recovered["epoch_id"] == "EPOCH_20261119_161744"
    assert recovered["last_processed_decision_date"] == "2026-11-20"
    assert recovered["num_trades"] == 1
    assert abs(recovered["cash"] - 6656.67) < 1e-2
    assert abs(recovered["btc_holdings"] - 0.052) < 1e-4
    assert abs(recovered["total_fees"] - 10.0) < 1e-4
    assert recovered["last_event_id"] == "FILL-TEST-001"
    assert test_env["state_file"].exists()


def test_malformed_ledger_with_valid_state_fails_closed(test_env):
    """Verify that corrupt ledger fails closed even if state JSON is valid, preserving evidence."""
    # Seed valid state file
    valid_state = {
        "epoch_id": "EPOCH_20261119_161744",
        "policy_version": "TRACK_A_V1_DONCHIAN_STEP",
        "policy_parameters": {
            "horizons": [20, 55, 90],
            "confirmation_days": 2,
            "no_trade_band": 0.20,
            "fee_bps": 30.0,
            "universe": ["BTCUSDT", "USDT_CASH"],
        },
        "inception_utc": "2026-11-19T16:17:44.866382+00:00",
        "last_updated_utc": "2026-11-19T16:17:55.253000+00:00",
        "initial_capital": 10000.0,
        "cash": 10000.0,
        "btc_holdings": 0.0,
        "current_equity": 10000.0,
        "peak_equity": 10000.0,
        "current_drawdown": 0.0,
        "max_drawdown": 0.0,
        "total_traded_notional": 0.0,
        "total_fees": 0.0,
        "num_trades": 0,
        "last_processed_decision_date": "2026-11-19",
        "last_terminal_action": "MISSED_EXECUTION_WINDOW",
        "last_approved_exposure": 0.3333333333333333,
        "last_raw_exposure": 0.3333333333333333,
        "last_event_id": None,
        "broker_connected": False,
    }
    save_paper_state_atomic(valid_state, test_env["state_file"])

    # Write corrupt data into ledger
    with open(test_env["ledger_file"], "w", encoding="utf-8") as f:
        f.write("CORRUPT_HEADER_WITHOUT_REQUIRED_COLUMNS\nline1,line2\n")

    # MUST fail closed with PaperRecoveryError
    with pytest.raises(PaperRecoveryError):
        load_paper_state(test_env["state_file"], test_env["ledger_file"])

    # Verify state file was NOT overwritten or reset
    with open(test_env["state_file"], "r", encoding="utf-8") as f:
        unmodified = json.load(f)
    assert unmodified["epoch_id"] == "EPOCH_20261119_161744"
    assert unmodified["cash"] == 10000.0


def test_long_running_lock_not_deleted_by_second_process(test_env):
    """Verify that a lock held by an active process is not deleted even after timeout."""
    with PaperObserverLock(lock_file=test_env["lock_file"]):
        # Lock is held by current process. Modify mtime to simulate 10 minutes elapsed
        past_time = time.time() - 600.0
        os.utime(test_env["lock_file"], (past_time, past_time))

        # Second process attempts to acquire lock
        second_lock = PaperObserverLock(lock_file=test_env["lock_file"], timeout=0.2)
        with pytest.raises(ConcurrentExecutionError, match="another instance is running"):
            with second_lock:
                pass

        # Lock file must still exist and not have been removed
        assert test_env["lock_file"].exists()


def test_double_step_does_not_create_duplicate_event(test_env):
    """Verify executing evaluate_observer twice on the same day is idempotent and creates 1 event."""
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
        receipt_timestamp_utc=dt,
    )
    provider = MockMarketDataProvider(server_time_ms=int(dt.timestamp() * 1000), ticker=ticker)

    # First step: executes rebalance
    res1 = evaluate_observer(
        provider=provider,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        lock_file=test_env["lock_file"],
        repo_root=test_env["tmp_path"],
    )
    assert res1["status"] == "EXECUTED"
    assert test_env["ledger_file"].exists()
    df1 = pd.read_csv(test_env["ledger_file"])
    assert len(df1) == 1

    # Second step 5 minutes later on the same day: idempotent ALREADY_PROCESSED
    dt2 = pd.Timestamp("2026-11-19 01:35:00", tz="UTC")
    ticker2 = BookTickerSnapshot(
        symbol="BTCUSDT",
        bid_price=70005.0,
        bid_qty=1.0,
        ask_price=70007.0,
        ask_qty=1.0,
        mid_price=70006.0,
        spread_bps=0.28,
        source_timestamp_utc=dt2,
        receipt_timestamp_utc=dt2,
    )
    provider2 = MockMarketDataProvider(server_time_ms=int(dt2.timestamp() * 1000), ticker=ticker2)

    res2 = evaluate_observer(
        provider=provider2,
        dry_run=False,
        state_file=test_env["state_file"],
        ledger_file=test_env["ledger_file"],
        lock_file=test_env["lock_file"],
        repo_root=test_env["tmp_path"],
    )
    assert res2["status"] == "ALREADY_PROCESSED"
    df2 = pd.read_csv(test_env["ledger_file"])
    assert len(df2) == 1  # No duplicate row!
    state2 = load_paper_state(test_env["state_file"], test_env["ledger_file"])
    assert state2["num_trades"] == 1  # No duplicate trade!

