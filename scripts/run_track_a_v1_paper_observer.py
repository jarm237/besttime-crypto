"""Track A v1 Forward Paper Observer (Production-Grade Manual Runner).

A causal, deterministic, idempotent, and crash-resilient manual forward observer for
Track A v1 (Donchian 20/55/90, 2-day confirmation, 20% no-trade buffer, BTC/USDT Spot,
long-only, 30 bps all-in transaction cost).

Lifecycle States:
- PENDING: Before execution window ([00:00, 01:00) UTC); decision formed, NOT finalized.
- EXECUTED: Rebalance executed during [01:00, 02:00) UTC window; terminal.
- HOLD: Evaluated during [01:00, 02:00) UTC window with deviation <= 20%; terminal.
- MISSED: Evaluation after 02:00 UTC without prior execution; window expired; terminal.
- DATA_UNAVAILABLE: Market data unavailable or fails freshness/drift checks; fail-closed.
- ALREADY_PROCESSED: Terminal decision already committed today; idempotent NO-OP.

Persistence & Recovery:
- Single source of truth: append-only CSV ledger with flush + fsync.
- State JSON checkpoint with atomic write (tmp + rename).
- Concurrency control via lockfile (PaperObserverLock).
- Fail-closed recovery: corrupt ledger raises PaperRecoveryError without capital reset.
- Strict broker isolation: SIMULATED_FILL only, broker_connected=False.

Commands:
    python scripts/run_track_a_v1_paper_observer.py --status
    python scripts/run_track_a_v1_paper_observer.py --dry-run
    python scripts/run_track_a_v1_paper_observer.py --step
    python scripts/run_track_a_v1_paper_observer.py --init-epoch [--epoch-id ID] [--force]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from btc_scraper.research.s5_economic_replay import solve_post_fee_equity
from btc_scraper.research.track_a_strategy import (
    LOOKBACK_HORIZONS,
    TRACK_A_NO_TRADE_BAND,
    DailySignalRecord,
    build_btc_daily_candles,
    compute_track_a_signals,
    load_universe_panels,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PAPER_DIR = REPO_ROOT / "research/track_a/paper"
WARMUP_CACHE_FILE = PAPER_DIR / "track_a_warmup_daily.csv"
PAPER_STATE_FILE = PAPER_DIR / "track_a_v1_paper_state.json"
PAPER_LEDGER_FILE = PAPER_DIR / "track_a_v1_paper_ledger.csv"
PAPER_LOCK_FILE = PAPER_DIR / "track_a_v1_paper.lock"

DEFAULT_FEE_BPS = 30.0
DEFAULT_INITIAL_CAPITAL = 10000.0
HTTP_TIMEOUT_SECONDS = 5.0
MAX_QUOTE_AGE_SECONDS = 60.0
MAX_CLOCK_DRIFT_MS = 10000.0
LOCK_TIMEOUT_SECONDS = 10.0


class DataUnavailableError(Exception):
    """Raised when market data cannot be obtained or fails freshness/drift checks."""


class ConcurrentExecutionError(Exception):
    """Raised when another observer instance holds the file lock."""


class PaperRecoveryError(Exception):
    """Raised when ledger or state recovery fails and manual inspection is required."""


@dataclass
class DailyKline:
    open_time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time_ms: int

    @property
    def open_dt(self) -> pd.Timestamp:
        return pd.to_datetime(self.open_time_ms, unit="ms", utc=True)

    @property
    def close_dt(self) -> pd.Timestamp:
        return pd.to_datetime(self.close_time_ms, unit="ms", utc=True)

    def is_completed(self, server_time_ms: int) -> bool:
        """A daily candle is completed only when server time has strictly passed its close time."""
        return server_time_ms >= self.close_time_ms


@dataclass
class BookTickerSnapshot:
    symbol: str
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float
    mid_price: float
    spread_bps: float
    source_timestamp_utc: pd.Timestamp
    receipt_timestamp_utc: pd.Timestamp


class MarketDataProvider:
    """Interface for bounded on-demand public market data fetching."""

    def get_server_time_ms(self) -> int:
        raise NotImplementedError

    def get_daily_klines(self, limit: int = 120) -> list[DailyKline]:
        raise NotImplementedError

    def get_book_ticker(self) -> BookTickerSnapshot:
        raise NotImplementedError


class BinancePublicRestClient(MarketDataProvider):
    """Fetches public market data directly from Binance Spot REST API (no auth, read-only)."""

    def __init__(self, base_url: str = "https://api.binance.com", timeout: float = HTTP_TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _http_get(self, endpoint: str) -> Any:
        url = f"{self.base_url}{endpoint}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "BesttimeCrypto-TrackA-PaperObserver/1.0",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
            raise DataUnavailableError(f"HTTP request to {url} failed: {e}") from e

    def get_server_time_ms(self) -> int:
        data = self._http_get("/api/v3/time")
        if not isinstance(data, dict) or "serverTime" not in data:
            raise DataUnavailableError(f"Malformed server time response: {data}")
        return int(data["serverTime"])

    def get_daily_klines(self, limit: int = 120) -> list[DailyKline]:
        data = self._http_get(f"/api/v3/klines?symbol=BTCUSDT&interval=1d&limit={limit}")
        if not isinstance(data, list):
            raise DataUnavailableError(f"Malformed klines response: {data}")

        klines: list[DailyKline] = []
        for r in data:
            klines.append(DailyKline(
                open_time_ms=int(r[0]),
                open=float(r[1]),
                high=float(r[2]),
                low=float(r[3]),
                close=float(r[4]),
                volume=float(r[5]),
                close_time_ms=int(r[6]),
            ))
        return klines

    def get_book_ticker(self) -> BookTickerSnapshot:
        receipt_dt = datetime.now(timezone.utc)
        data = self._http_get("/api/v3/ticker/bookTicker?symbol=BTCUSDT")
        if not isinstance(data, dict) or "bidPrice" not in data or "askPrice" not in data:
            raise DataUnavailableError(f"Malformed book ticker response: {data}")

        bid = float(data["bidPrice"])
        ask = float(data["askPrice"])
        bid_qty = float(data.get("bidQty", 0.0))
        ask_qty = float(data.get("askQty", 0.0))

        if bid <= 0 or ask <= 0 or ask < bid:
            raise DataUnavailableError(f"Invalid quote spread: bid={bid}, ask={ask}")

        mid = 0.5 * (bid + ask)
        spread_bps = ((ask - bid) / mid) * 10000.0

        return BookTickerSnapshot(
            symbol="BTCUSDT",
            bid_price=bid,
            bid_qty=bid_qty,
            ask_price=ask,
            ask_qty=ask_qty,
            mid_price=mid,
            spread_bps=spread_bps,
            source_timestamp_utc=receipt_dt,
            receipt_timestamp_utc=receipt_dt,
        )


class PaperObserverLock:
    """Cross-platform advisory file lock with timeout and stale-lock recovery."""

    def __init__(self, lock_file: Path = PAPER_LOCK_FILE, timeout: float = LOCK_TIMEOUT_SECONDS):
        self.lock_file = lock_file
        self.timeout = timeout
        self._acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def acquire(self) -> None:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        start_time = time.time()
        while True:
            try:
                fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(f"pid={os.getpid()}\ntime={time.time()}\n")
                self._acquired = True
                return
            except FileExistsError:
                # Check for stale lock (> 30s)
                try:
                    mtime = os.path.getmtime(self.lock_file)
                    if time.time() - mtime > 30.0:
                        try:
                            os.remove(self.lock_file)
                            continue
                        except OSError:
                            pass
                except OSError:
                    pass

                if time.time() - start_time >= self.timeout:
                    raise ConcurrentExecutionError(
                        f"Could not acquire lockfile {self.lock_file} after {self.timeout}s: another instance is running."
                    )
                time.sleep(0.1)

    def release(self) -> None:
        if self._acquired:
            try:
                if self.lock_file.exists():
                    self.lock_file.unlink()
            except OSError:
                pass
            self._acquired = False


def load_or_build_warmup_daily(repo_root: Path = REPO_ROOT) -> pd.DataFrame:
    """Load cached daily warmup candles, or build from historical archives if missing."""
    # Check repo_root / warmup file first (supports test isolation)
    local_warmup = repo_root / "track_a_warmup_daily.csv"
    if local_warmup.exists():
        return pd.read_csv(local_warmup, index_col=0, parse_dates=True)

    paper_warmup = repo_root / "research/track_a/paper/track_a_warmup_daily.csv"
    if paper_warmup.exists():
        return pd.read_csv(paper_warmup, index_col=0, parse_dates=True)

    if WARMUP_CACHE_FILE.exists():
        return pd.read_csv(WARMUP_CACHE_FILE, index_col=0, parse_dates=True)

    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    panels = load_universe_panels(repo_root)
    btc_daily = build_btc_daily_candles(panels["BTCUSDT"])
    btc_daily.to_csv(WARMUP_CACHE_FILE)
    return btc_daily


def merge_forward_daily_candles(
    warmup_df: pd.DataFrame,
    klines: Sequence[DailyKline],
    server_time_ms: int,
) -> tuple[pd.DataFrame, int, int]:
    """Merge completed klines with warmup daily series, dropping running/incomplete bars."""
    completed_rows = []
    dropped_count = 0

    for k in klines:
        if k.is_completed(server_time_ms):
            completed_rows.append({
                "open": k.open,
                "high": k.high,
                "low": k.low,
                "close": k.close,
                "volume": k.volume,
                "hour_count": 24,
                "dt": k.open_dt,
            })
        else:
            dropped_count += 1

    if not completed_rows:
        return warmup_df.copy(), 0, dropped_count

    df_new = pd.DataFrame(completed_rows).set_index("dt")
    combined = pd.concat([warmup_df, df_new])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    added_count = len(combined) - len(warmup_df)
    return combined, max(0, added_count), dropped_count


def save_paper_state_atomic(state: dict[str, Any], state_file: Path = PAPER_STATE_FILE) -> None:
    """Atomic write to prevent corruption during crash or interruption."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = state_file.with_suffix(".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, state_file)


def append_paper_ledger_entry(entry: dict[str, Any], ledger_file: Path = PAPER_LEDGER_FILE) -> None:
    """Append terminal decision and simulated fill record to CSV ledger with flush and fsync."""
    ledger_file.parent.mkdir(parents=True, exist_ok=True)
    df_entry = pd.DataFrame([entry])
    write_header = not ledger_file.exists()
    with open(ledger_file, "a", newline="", encoding="utf-8") as f:
        df_entry.to_csv(f, header=write_header, index=False)
        f.flush()
        os.fsync(f.fileno())


def recover_state_from_ledger(
    ledger_file: Path = PAPER_LEDGER_FILE,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
) -> dict[str, Any]:
    """Deterministically reconstruct portfolio state by replaying append-only ledger events."""
    if not ledger_file.exists():
        raise PaperRecoveryError(f"Ledger file {ledger_file} does not exist.")

    try:
        df = pd.read_csv(ledger_file)
    except Exception as e:
        raise PaperRecoveryError(f"Corrupted ledger {ledger_file} could not be parsed: {e}") from e

    if df.empty or len(df.columns) < 5:
        raise PaperRecoveryError(f"Ledger {ledger_file} is empty or lacks required schema columns.")

    required_cols = {"decision_date", "action", "post_cash", "post_btc_holdings", "nav"}
    if not required_cols.issubset(df.columns):
        raise PaperRecoveryError(f"Ledger {ledger_file} missing required columns: {required_cols - set(df.columns)}")

    last_row = df.iloc[-1]
    epoch_id = str(last_row.get("epoch_id", "EPOCH_RECOVERED"))
    cash = float(last_row["post_cash"])
    holdings = float(last_row["post_btc_holdings"])
    nav = float(last_row["nav"])
    peak_nav = float(last_row.get("peak_nav", nav))
    dd = float(last_row.get("drawdown", 0.0))

    if cash < -1e-6 or holdings < -1e-8:
        raise PaperRecoveryError(f"Ledger contains negative balances: cash={cash}, holdings={holdings}")

    rebalance_rows = df[df["action"] == "REBALANCE"]
    num_trades = len(rebalance_rows)
    total_fees = float(rebalance_rows["fee"].sum()) if num_trades > 0 else 0.0
    total_traded_notional = float(rebalance_rows["trade_notional"].sum()) if num_trades > 0 else 0.0

    return {
        "epoch_id": epoch_id,
        "policy_version": "TRACK_A_V1_DONCHIAN_STEP",
        "policy_parameters": {
            "horizons": list(LOOKBACK_HORIZONS),
            "confirmation_days": 2,
            "no_trade_band": TRACK_A_NO_TRADE_BAND,
            "fee_bps": DEFAULT_FEE_BPS,
            "universe": ["BTCUSDT", "USDT_CASH"],
        },
        "inception_utc": str(df.iloc[0].get("timestamp_utc", datetime.now(timezone.utc).isoformat())),
        "last_updated_utc": str(last_row.get("timestamp_utc", datetime.now(timezone.utc).isoformat())),
        "initial_capital": float(initial_capital),
        "cash": cash,
        "btc_holdings": holdings,
        "current_equity": nav,
        "peak_equity": peak_nav,
        "current_drawdown": dd,
        "max_drawdown": float(df["drawdown"].min()) if "drawdown" in df else dd,
        "total_traded_notional": total_traded_notional,
        "total_fees": total_fees,
        "num_trades": num_trades,
        "last_processed_decision_date": str(last_row["decision_date"]),
        "last_terminal_action": str(last_row["action"]),
        "last_approved_exposure": float(last_row.get("approved_exposure", 0.0)),
        "last_raw_exposure": float(last_row.get("raw_exposure", 0.0)),
        "last_event_id": str(last_row.get("event_id")) if pd.notna(last_row.get("event_id")) else None,
        "broker_connected": False,
    }


def load_paper_state(
    state_file: Path = PAPER_STATE_FILE,
    ledger_file: Path = PAPER_LEDGER_FILE,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
) -> dict[str, Any]:
    """Load paper state, reconciling with ledger if corrupted or missing. Fails closed on error."""
    # Case 1: State file exists
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
            if isinstance(state, dict) and "current_equity" in state and "cash" in state:
                # If ledger exists, check consistency
                if ledger_file.exists():
                    try:
                        df = pd.read_csv(ledger_file)
                        if not df.empty:
                            last_ledger_date = str(df.iloc[-1]["decision_date"])
                            state_date = state.get("last_processed_decision_date")
                            if state_date != last_ledger_date:
                                # State is lagging ledger checkpoint; recover from ledger
                                recovered = recover_state_from_ledger(ledger_file, initial_capital)
                                save_paper_state_atomic(recovered, state_file)
                                return recovered
                    except Exception:
                        pass
                return state
        except Exception:
            # Corrupted state JSON; try recovery from ledger
            if ledger_file.exists():
                recovered = recover_state_from_ledger(ledger_file, initial_capital)
                save_paper_state_atomic(recovered, state_file)
                return recovered
            raise PaperRecoveryError(f"State file {state_file} corrupted and ledger unavailable.")

    # Case 2: State file missing, but ledger exists
    if ledger_file.exists():
        recovered = recover_state_from_ledger(ledger_file, initial_capital)
        save_paper_state_atomic(recovered, state_file)
        return recovered

    # Case 3: Neither exists -> Clean initial state for a fresh epoch
    return {
        "epoch_id": f"EPOCH_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        "policy_version": "TRACK_A_V1_DONCHIAN_STEP",
        "policy_parameters": {
            "horizons": list(LOOKBACK_HORIZONS),
            "confirmation_days": 2,
            "no_trade_band": TRACK_A_NO_TRADE_BAND,
            "fee_bps": DEFAULT_FEE_BPS,
            "universe": ["BTCUSDT", "USDT_CASH"],
        },
        "inception_utc": datetime.now(timezone.utc).isoformat(),
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "initial_capital": float(initial_capital),
        "cash": float(initial_capital),
        "btc_holdings": 0.0,
        "current_equity": float(initial_capital),
        "peak_equity": float(initial_capital),
        "current_drawdown": 0.0,
        "max_drawdown": 0.0,
        "total_traded_notional": 0.0,
        "total_fees": 0.0,
        "num_trades": 0,
        "last_processed_decision_date": None,
        "last_terminal_action": None,
        "last_approved_exposure": 0.0,
        "last_raw_exposure": 0.0,
        "last_event_id": None,
        "broker_connected": False,
    }


def evaluate_observer(
    provider: MarketDataProvider,
    dry_run: bool = False,
    state_file: Path = PAPER_STATE_FILE,
    ledger_file: Path = PAPER_LEDGER_FILE,
    lock_file: Path = PAPER_LOCK_FILE,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Execute one complete forward observer evaluation cycle with locking and strict lifecycle."""
    with PaperObserverLock(lock_file=lock_file):
        # 1. Fetch live market data (bounded on-demand)
        klines = provider.get_daily_klines(limit=120)
        ticker = provider.get_book_ticker()

        receipt_time_utc = ticker.receipt_timestamp_utc if ticker.receipt_timestamp_utc is not None else datetime.now(timezone.utc)
        server_time_ms = provider.get_server_time_ms()
        server_dt = pd.to_datetime(server_time_ms, unit="ms", utc=True)
        clock_drift_ms = abs(server_time_ms - int(receipt_time_utc.timestamp() * 1000))

        if clock_drift_ms > MAX_CLOCK_DRIFT_MS:
            raise DataUnavailableError(f"Clock drift {clock_drift_ms:.0f} ms exceeds limit {MAX_CLOCK_DRIFT_MS} ms")

        # Quote freshness check
        quote_age_s = (receipt_time_utc - ticker.source_timestamp_utc).total_seconds()
        if abs(quote_age_s) > MAX_QUOTE_AGE_SECONDS:
            raise DataUnavailableError(f"Stale quote received: age={quote_age_s:.1f}s > {MAX_QUOTE_AGE_SECONDS}s")

        # 2. Load warmup and merge with completed daily klines
        warmup_df = load_or_build_warmup_daily(repo_root)
        merged_daily, num_completed_added, num_incomplete_dropped = merge_forward_daily_candles(
            warmup_df=warmup_df,
            klines=klines,
            server_time_ms=server_time_ms,
        )

        if len(merged_daily) < max(LOOKBACK_HORIZONS) + 2:
            raise DataUnavailableError(f"Insufficient daily bars: have {len(merged_daily)}, need >= 92")

        # 3. Compute causal Donchian signals
        signals = compute_track_a_signals(merged_daily)
        latest_decision_dt = max(signals.keys())
        sig: DailySignalRecord = signals[latest_decision_dt]
        decision_date_str = latest_decision_dt.strftime("%Y-%m-%d")

        # 4. Load State and Check Idempotency
        state = load_paper_state(state_file=state_file, ledger_file=ledger_file)
        epoch_id = state["epoch_id"]
        already_processed = (state.get("last_processed_decision_date") == decision_date_str)

        cash = float(state["cash"])
        holdings = float(state["btc_holdings"])
        peak_eq = float(state["peak_equity"])

        # Mark to market prior to potential rebalance
        pre_btc_notional = holdings * ticker.mid_price
        v_pre = cash + pre_btc_notional
        current_w = (pre_btc_notional / v_pre) if v_pre > 0 else 0.0
        target_w = sig.approved_exposure
        deviation = abs(target_w - current_w)

        # 5. Evaluate Decision Lifecycle & Causal Window
        decision_day = latest_decision_dt.date()
        current_day = server_dt.date()
        current_hour = server_dt.hour

        trade_notional = 0.0
        realized_fee = 0.0
        exec_price = ticker.mid_price
        fill_type = "NONE"
        event_id = None
        new_cash = cash
        new_holdings = holdings
        is_terminal = False

        if already_processed:
            status = "ALREADY_PROCESSED"
            action = "ALREADY_PROCESSED"
            exec_eligibility = "ALREADY_PROCESSED"
            is_terminal = False

        elif current_day < decision_day or (current_day == decision_day and current_hour == 0):
            # Before 01:00 UTC execution window: PENDING
            status = "PENDING"
            action = "PENDING"
            exec_eligibility = "TOO_EARLY"
            is_terminal = False  # DO NOT finalize decision date!

        elif current_day == decision_day and current_hour == 1:
            # Inside [01:00, 02:00) UTC execution window: ELIGIBLE
            exec_eligibility = "ELIGIBLE"
            is_terminal = True  # Decision will be finalized today

            if deviation > TRACK_A_NO_TRADE_BAND:
                # Rebalance triggered
                status = "EXECUTED"
                action = "REBALANCE"
                fill_type = "SIMULATED_FILL"
                event_id = f"FILL-{epoch_id}-{decision_date_str}-{uuid.uuid4().hex[:8]}"

                # Directional execution price: buy at ask, sell at bid
                if target_w > current_w:
                    exec_price = ticker.ask_price
                elif target_w < current_w:
                    exec_price = ticker.bid_price
                else:
                    exec_price = ticker.mid_price

                fee_rate = DEFAULT_FEE_BPS / 10000.0
                pre_exec_notional = holdings * exec_price
                v_pre_exec = cash + pre_exec_notional
                current_notionals = np.array([pre_exec_notional])
                target_weights = np.array([target_w])
                v_post, realized_fee = solve_post_fee_equity(v_pre_exec, current_notionals, target_weights, fee_rate)

                target_notional = target_w * v_post
                trade_notional = abs(target_notional - pre_exec_notional)
                new_holdings = target_notional / exec_price
                new_cash = (1.0 - target_w) * v_post
            else:
                status = "HOLD"
                action = "HOLD"

        else:
            # Past 02:00 UTC on decision day or later: MISSED
            status = "MISSED"
            action = "MISSED"
            exec_eligibility = "MISSED_EXECUTION_WINDOW"
            is_terminal = True  # Finalized as missed, no backdating

        # Mark to market post-action
        current_eq = new_cash + new_holdings * ticker.mid_price
        new_peak_eq = max(peak_eq, current_eq)
        dd = (current_eq - new_peak_eq) / new_peak_eq if new_peak_eq > 0 else 0.0
        max_dd = min(float(state["max_drawdown"]), dd)

        # Spread and latency metrics
        half_spread_bps = 0.5 * ticker.spread_bps
        spread_cost_bps = ((exec_price - ticker.mid_price) / ticker.mid_price) * 10000.0 if ticker.mid_price > 0 else 0.0
        effective_cost_bps = DEFAULT_FEE_BPS + abs(spread_cost_bps) if action == "REBALANCE" else 0.0

        result_entry = {
            "timestamp_utc": server_dt.isoformat(),
            "receipt_time_utc": receipt_time_utc.isoformat(),
            "epoch_id": epoch_id,
            "decision_date": decision_date_str,
            "candle_date": sig.candle_dt.strftime("%Y-%m-%d"),
            "status": status,
            "exec_eligibility": exec_eligibility,
            "close_price": sig.close_price,
            "state_20": sig.state_20,
            "state_55": sig.state_55,
            "state_90": sig.state_90,
            "raw_exposure": sig.raw_exposure,
            "approved_exposure": sig.approved_exposure,
            "confirmed": sig.confirmed,
            "current_btc_weight": current_w,
            "target_btc_weight": target_w,
            "deviation": deviation,
            "action": action,
            "bid_price": ticker.bid_price,
            "ask_price": ticker.ask_price,
            "mid_price": ticker.mid_price,
            "spread_bps": ticker.spread_bps,
            "exec_price": exec_price,
            "modeled_fee_bps": DEFAULT_FEE_BPS,
            "spread_cost_bps": spread_cost_bps,
            "effective_cost_bps": effective_cost_bps,
            "fill_type": fill_type,
            "trade_notional": trade_notional,
            "fee": realized_fee,
            "post_cash": new_cash,
            "post_btc_holdings": new_holdings,
            "nav": current_eq,
            "peak_nav": new_peak_eq,
            "drawdown": dd,
            "event_id": event_id,
            "broker_connected": False,
            "clock_drift_ms": clock_drift_ms,
        }

        # 6. Persistence: Ledger first (flush+fsync), then State Checkpoint
        # CRITICAL: Only terminal decisions (EXECUTED, HOLD, MISSED) finalize decision date and write ledger!
        if not dry_run and is_terminal and not already_processed:
            # 1. Append to append-only ledger (source of truth)
            append_paper_ledger_entry(result_entry, ledger_file=ledger_file)

            # 2. Update state checkpoint
            state["last_updated_utc"] = server_dt.isoformat()
            state["cash"] = new_cash
            state["btc_holdings"] = new_holdings
            state["current_equity"] = current_eq
            state["peak_equity"] = new_peak_eq
            state["current_drawdown"] = dd
            state["max_drawdown"] = max_dd
            state["total_traded_notional"] += trade_notional
            state["total_fees"] += realized_fee
            if action == "REBALANCE":
                state["num_trades"] += 1
                state["last_event_id"] = event_id

            state["last_processed_decision_date"] = decision_date_str
            state["last_terminal_action"] = action
            state["last_approved_exposure"] = sig.approved_exposure
            state["last_raw_exposure"] = sig.raw_exposure

            save_paper_state_atomic(state, state_file=state_file)

        return result_entry


def print_status(
    provider: MarketDataProvider | None = None,
    state_file: Path = PAPER_STATE_FILE,
    ledger_file: Path = PAPER_LEDGER_FILE,
    lock_file: Path = PAPER_LOCK_FILE,
) -> None:
    with PaperObserverLock(lock_file=lock_file):
        state = load_paper_state(state_file=state_file, ledger_file=ledger_file)
        mid_price = None
        spread_bps = None
        server_time_str = "N/A"

        if provider is not None:
            try:
                s_ms = provider.get_server_time_ms()
                server_time_str = pd.to_datetime(s_ms, unit="ms", utc=True).isoformat()
                ticker = provider.get_book_ticker()
                mid_price = ticker.mid_price
                spread_bps = ticker.spread_bps
            except Exception as e:
                server_time_str = f"Error: {e}"

        initial_cap = float(state.get("initial_capital", DEFAULT_INITIAL_CAPITAL))
        cash = float(state.get("cash", initial_cap))
        holdings = float(state.get("btc_holdings", 0.0))

        if mid_price is not None:
            current_eq = cash + holdings * mid_price
        else:
            current_eq = float(state.get("current_equity", initial_cap))

        cum_pnl = current_eq - initial_cap
        cum_ret = (cum_pnl / initial_cap) * 100.0

        print("================================================================")
        print("      TRACK A V1 FORWARD PAPER OBSERVER — STATUS SCORECARD      ")
        print("================================================================")
        print(f"Policy Version:         {state.get('policy_version', 'TRACK_A_V1_DONCHIAN_STEP')}")
        print(f"Epoch ID:               {state.get('epoch_id', 'NONE')}")
        print(f"Inception UTC:          {state.get('inception_utc', 'N/A')}")
        print(f"Server Time UTC:        {server_time_str}")
        print(f"Last Terminal Decision: {state.get('last_processed_decision_date', 'None')} ({state.get('last_terminal_action', 'None')})")
        print("----------------------------------------------------------------")
        print(f"Initial Paper Capital:  ${initial_cap:,.2f} USDT")
        print(f"Current Cash Balance:   ${cash:,.2f} USDT")
        print(f"BTC Holdings:           {holdings:.6f} BTC")
        if mid_price is not None:
            print(f"BTC Mid Price:          ${mid_price:,.2f} (Spread: {spread_bps:.2f} bps)")
            print(f"BTC Traded Value:       ${holdings * mid_price:,.2f} USDT")
        print(f"Current NAV:            ${current_eq:,.2f} USDT (Net Return: {cum_ret:+.2f}%)")
        print(f"Peak NAV:               ${float(state.get('peak_equity', current_eq)):,.2f} USDT")
        print(f"Current Drawdown:       {float(state.get('current_drawdown', 0.0))*100:.2f}% (MaxDD: {float(state.get('max_drawdown', 0.0))*100:.2f}%)")
        print(f"Total Fees Incurred:    ${float(state.get('total_fees', 0.0)):,.2f} USDT")
        print(f"Total Traded Notional:  ${float(state.get('total_traded_notional', 0.0)):,.2f} USDT")
        print(f"Rebalances Executed:    {state.get('num_trades', 0)}")
        print(f"Broker Connected:       {state.get('broker_connected', False)} (Paper Isolation Confirmed)")
        print("================================================================")


def init_epoch(
    epoch_id: str | None = None,
    capital: float = DEFAULT_INITIAL_CAPITAL,
    force: bool = False,
    state_file: Path = PAPER_STATE_FILE,
    ledger_file: Path = PAPER_LEDGER_FILE,
    lock_file: Path = PAPER_LOCK_FILE,
) -> None:
    with PaperObserverLock(lock_file=lock_file):
        if state_file.exists() and not force:
            print(f"Error: Paper state already exists at {state_file}. Use --force to overwrite.", file=sys.stderr)
            sys.exit(1)

        eid = epoch_id or f"EPOCH_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        new_state = {
            "epoch_id": eid,
            "policy_version": "TRACK_A_V1_DONCHIAN_STEP",
            "policy_parameters": {
                "horizons": list(LOOKBACK_HORIZONS),
                "confirmation_days": 2,
                "no_trade_band": TRACK_A_NO_TRADE_BAND,
                "fee_bps": DEFAULT_FEE_BPS,
                "universe": ["BTCUSDT", "USDT_CASH"],
            },
            "inception_utc": datetime.now(timezone.utc).isoformat(),
            "last_updated_utc": datetime.now(timezone.utc).isoformat(),
            "initial_capital": float(capital),
            "cash": float(capital),
            "btc_holdings": 0.0,
            "current_equity": float(capital),
            "peak_equity": float(capital),
            "current_drawdown": 0.0,
            "max_drawdown": 0.0,
            "total_traded_notional": 0.0,
            "total_fees": 0.0,
            "num_trades": 0,
            "last_processed_decision_date": None,
            "last_terminal_action": None,
            "last_approved_exposure": 0.0,
            "last_raw_exposure": 0.0,
            "last_event_id": None,
            "broker_connected": False,
        }

        save_paper_state_atomic(new_state, state_file=state_file)
        if ledger_file.exists() and force:
            ledger_file.unlink()

        print(f"Initialized new paper observation epoch '{eid}' with ${capital:,.2f} USDT at {new_state['inception_utc']}.")


def main():
    parser = argparse.ArgumentParser(description="Track A v1 Forward Paper Observer")
    parser.add_argument("--status", action="store_true", help="Display current observer state and exit")
    parser.add_argument("--step", action="store_true", help="Execute one forward observer evaluation step")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate observer step without persisting state")
    parser.add_argument("--init-epoch", action="store_true", help="Initialize a fresh forward paper observation epoch")
    parser.add_argument("--epoch-id", type=str, default=None, help="Custom epoch identifier for --init-epoch")
    parser.add_argument("--capital", type=float, default=DEFAULT_INITIAL_CAPITAL, help="Initial capital in USDT")
    parser.add_argument("--force", action="store_true", help="Force overwrite existing state during --init-epoch")
    args = parser.parse_args()

    provider = BinancePublicRestClient()

    try:
        if args.init_epoch:
            init_epoch(epoch_id=args.epoch_id, capital=args.capital, force=args.force)
            return

        if args.status:
            print_status(provider=provider)
            return

        if args.step or args.dry_run:
            entry = evaluate_observer(provider=provider, dry_run=args.dry_run)
            mode_prefix = "[DRY-RUN] " if args.dry_run else ""
            print(f"{mode_prefix}Forward Observer Evaluation at {entry['timestamp_utc']}:")
            print(f"  Decision Date:       {entry['decision_date']} (Candle: {entry['candle_date']})")
            print(f"  Lifecycle Status:    {entry['status']} (Eligibility: {entry['exec_eligibility']})")
            print(f"  Action:              {entry['action']}")
            print(f"  Server Time Drift:   {entry['clock_drift_ms']} ms")
            print(f"  Quote Mid Price:     ${entry['mid_price']:,.2f} (Spread: {entry['spread_bps']:.2f} bps)")
            print(f"  Donchian States:     [20d={entry['state_20']}, 55d={entry['state_55']}, 90d={entry['state_90']}]")
            print(f"  Exposure:            Raw={entry['raw_exposure']*100:.1f}%, Confirmed={entry['confirmed']} -> Approved={entry['approved_exposure']*100:.1f}%")
            print(f"  Portfolio Weights:   Current={entry['current_btc_weight']*100:.1f}%, Target={entry['target_btc_weight']*100:.1f}%, Deviation={entry['deviation']*100:.1f}%")
            if entry["action"] == "REBALANCE":
                print(f"  Simulated Fill:      ExecPrice=${entry['exec_price']:,.2f}, Notional=${entry['trade_notional']:,.2f}, Fee(30bps)=${entry['fee']:,.2f}")
                print(f"  Fill Event ID:       {entry['event_id']}")
                print(f"  Cost Breakdown:      ModeledFee={entry['modeled_fee_bps']:.1f}bps, SpreadCost={entry['spread_cost_bps']:+.2f}bps -> EffectiveCost={entry['effective_cost_bps']:.2f}bps")
            print(f"  Updated NAV:         ${entry['nav']:,.2f} USDT (Drawdown: {entry['drawdown']*100:.2f}%)")
            print(f"  Holdings Post-Step:  Cash=${entry['post_cash']:,.2f}, BTC={entry['post_btc_holdings']:.6f}")
            return

        print_status(provider=provider)
    except DataUnavailableError as e:
        print(f"FAIL CLOSED (DATA_UNAVAILABLE): {e}", file=sys.stderr)
        sys.exit(2)
    except ConcurrentExecutionError as e:
        print(f"CONCURRENT EXECUTION BLOCKED: {e}", file=sys.stderr)
        sys.exit(3)
    except PaperRecoveryError as e:
        print(f"CRITICAL RECOVERY FAILURE (FAIL CLOSED): {e}", file=sys.stderr)
        sys.exit(4)


if __name__ == "__main__":
    main()
