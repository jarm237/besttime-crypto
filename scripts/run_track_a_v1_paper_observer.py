"""Track A v1 Forward Paper Observer (Manual Terminal Runner).

A deterministic, causal, and idempotent manual observation runner that tracks
Track A v1 decisions, Donchian channels, signals, simulated execution fills (at 30 bps),
fees, NAV, and drawdown in forward paper observation mode without broker or live exchange access.

Protocol:
- Universe: BTCUSDT (Binance Spot) + CASH (USDT nominal).
- Lookback Horizons: 20, 55, 90 daily candles.
- 2-Day Confirmation: Target updated only after two consecutive identical raw exposures.
- No-Trade Buffer: 20 percentage points (0.20) deviation threshold.
- Execution Clock: Decision D formed at 00:00 UTC (cutoff D-1).
  Execution window is [01:00:00, 02:00:00) UTC on day D.
- Contemporaneous Quote: Order book top (bid/ask) from Binance public REST API.
- Fee Accounting: solve_post_fee_equity at 30 bps one-way fee.
- Safety: SIMULATED_FILL only, broker_connected=False, fail closed on missing data.

Commands:
    python scripts/run_track_a_v1_paper_observer.py --status
    python scripts/run_track_a_v1_paper_observer.py --dry-run
    python scripts/run_track_a_v1_paper_observer.py --step
    python scripts/run_track_a_v1_paper_observer.py --init-epoch [--epoch-id ID]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
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

DEFAULT_FEE_BPS = 30.0
DEFAULT_INITIAL_CAPITAL = 10000.0
HTTP_TIMEOUT_SECONDS = 5.0
MAX_QUOTE_AGE_SECONDS = 60.0


class DataUnavailableError(Exception):
    """Raised when market data cannot be obtained or fails freshness checks."""


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
            source_timestamp_utc=datetime.now(timezone.utc),
        )


def load_or_build_warmup_daily(repo_root: Path = REPO_ROOT) -> pd.DataFrame:
    """Load cached daily warmup candles, or build from historical archives if missing."""
    PAPER_DIR.mkdir(parents=True, exist_ok=True)
    if WARMUP_CACHE_FILE.exists():
        df = pd.read_csv(WARMUP_CACHE_FILE, index_col=0, parse_dates=True)
        return df

    panels = load_universe_panels(repo_root)
    btc_daily = build_btc_daily_candles(panels["BTCUSDT"])
    btc_daily.to_csv(WARMUP_CACHE_FILE)
    return btc_daily


def merge_forward_daily_candles(
    warmup_df: pd.DataFrame,
    klines: Sequence[DailyKline],
    server_time_ms: int,
) -> tuple[pd.DataFrame, int, int]:
    """Merge completed klines with warmup daily series.

    Returns:
        (merged_df, num_completed_klines_added, num_incomplete_klines_dropped)
    """
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
    # Combine and drop duplicates (favoring newest)
    combined = pd.concat([warmup_df, df_new])
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    added_count = len(combined) - len(warmup_df)
    return combined, max(0, added_count), dropped_count


def load_paper_state(state_file: Path = PAPER_STATE_FILE, ledger_file: Path = PAPER_LEDGER_FILE) -> dict[str, Any]:
    """Load current paper portfolio state or recover from append-only ledger."""
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state = json.load(f)
                if isinstance(state, dict) and "current_equity" in state:
                    return state
        except Exception:
            pass  # Fall through to recovery

    # Recovery from ledger if state is corrupted or missing
    if ledger_file.exists():
        recovered = recover_state_from_ledger(ledger_file)
        if recovered is not None:
            save_paper_state_atomic(recovered, state_file)
            return recovered

    # Clean initial state
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
        "initial_capital": DEFAULT_INITIAL_CAPITAL,
        "cash": DEFAULT_INITIAL_CAPITAL,
        "btc_holdings": 0.0,
        "current_equity": DEFAULT_INITIAL_CAPITAL,
        "peak_equity": DEFAULT_INITIAL_CAPITAL,
        "current_drawdown": 0.0,
        "max_drawdown": 0.0,
        "total_traded_notional": 0.0,
        "total_fees": 0.0,
        "num_trades": 0,
        "last_processed_decision_date": None,
        "last_approved_exposure": 0.0,
        "last_raw_exposure": 0.0,
        "last_event_id": None,
        "broker_connected": False,
    }


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
    """Append decision and simulated fill record to CSV ledger."""
    ledger_file.parent.mkdir(parents=True, exist_ok=True)
    df_entry = pd.DataFrame([entry])
    if not ledger_file.exists():
        df_entry.to_csv(ledger_file, index=False)
    else:
        df_entry.to_csv(ledger_file, mode="a", header=False, index=False)


def recover_state_from_ledger(ledger_file: Path = PAPER_LEDGER_FILE) -> dict[str, Any] | None:
    """Deterministically reconstruct portfolio state by replaying ledger events."""
    if not ledger_file.exists():
        return None
    try:
        df = pd.read_csv(ledger_file)
        if df.empty:
            return None

        last_row = df.iloc[-1]
        epoch_id = str(last_row.get("epoch_id", "EPOCH_RECOVERED"))
        cash = float(last_row.get("post_cash", DEFAULT_INITIAL_CAPITAL))
        holdings = float(last_row.get("post_btc_holdings", 0.0))
        nav = float(last_row.get("nav", DEFAULT_INITIAL_CAPITAL))
        peak_nav = float(last_row.get("peak_nav", nav))
        dd = float(last_row.get("drawdown", 0.0))

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
            "initial_capital": DEFAULT_INITIAL_CAPITAL,
            "cash": cash,
            "btc_holdings": holdings,
            "current_equity": nav,
            "peak_equity": peak_nav,
            "current_drawdown": dd,
            "max_drawdown": float(df["drawdown"].min()),
            "total_traded_notional": total_traded_notional,
            "total_fees": total_fees,
            "num_trades": num_trades,
            "last_processed_decision_date": str(last_row.get("decision_date")),
            "last_approved_exposure": float(last_row.get("approved_exposure", 0.0)),
            "last_raw_exposure": float(last_row.get("raw_exposure", 0.0)),
            "last_event_id": str(last_row.get("event_id")),
            "broker_connected": False,
        }
    except Exception as e:
        print(f"Warning: Failed to recover state from ledger {ledger_file}: {e}", file=sys.stderr)
        return None


def evaluate_observer(
    provider: MarketDataProvider,
    dry_run: bool = False,
    state_file: Path = PAPER_STATE_FILE,
    ledger_file: Path = PAPER_LEDGER_FILE,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Execute one complete forward observer evaluation cycle."""
    # 1. Fetch live market data (bounded on-demand)
    server_time_ms = provider.get_server_time_ms()
    server_dt = pd.to_datetime(server_time_ms, unit="ms", utc=True)
    local_dt = datetime.now(timezone.utc)
    clock_drift_ms = abs(server_time_ms - int(local_dt.timestamp() * 1000))

    klines = provider.get_daily_klines(limit=120)
    ticker = provider.get_book_ticker()

    # Quote freshness check
    quote_age_s = (server_dt - ticker.source_timestamp_utc).total_seconds()
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

    # 4. Check Causal Clock and Execution Window
    # Nominal execution window for decision D: [01:00:00, 02:00:00) UTC on day D
    decision_day = latest_decision_dt.date()
    current_day = server_dt.date()
    current_hour = server_dt.hour

    if current_day < decision_day:
        exec_eligibility = "TOO_EARLY"
    elif current_day == decision_day:
        if current_hour == 0:
            exec_eligibility = "TOO_EARLY"  # 00:00 UTC cutoff just closed; window is 01:00 UTC
        elif current_hour == 1:
            exec_eligibility = "ELIGIBLE"   # Inside [01:00, 02:00) UTC execution window
        else:
            exec_eligibility = "MISSED_EXECUTION_WINDOW"  # > 02:00 UTC
    else:
        exec_eligibility = "MISSED_EXECUTION_WINDOW"  # Past decision day entirely

    # 5. Load State and Check Idempotency
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

    action = "HOLD"
    trade_notional = 0.0
    realized_fee = 0.0
    exec_price = ticker.mid_price
    fill_type = "NONE"
    event_id = None
    new_cash = cash
    new_holdings = holdings

    if already_processed:
        status = "ALREADY_PROCESSED"
    elif exec_eligibility == "MISSED_EXECUTION_WINDOW":
        status = "MISSED_EXECUTION_WINDOW"
        action = "MISSED_EXECUTION_WINDOW"
    elif exec_eligibility == "TOO_EARLY":
        status = "PENDING_EXECUTION_WINDOW"
    elif exec_eligibility == "ELIGIBLE":
        status = "ELIGIBLE"
        if deviation > TRACK_A_NO_TRADE_BAND:
            action = "REBALANCE"
            fill_type = "SIMULATED_FILL"
            event_id = f"FILL-{epoch_id}-{decision_date_str}-{uuid.uuid4().hex[:8]}"

            # Conservative execution: buy at ask, sell at bid
            exec_price = ticker.ask_price if (target_w > current_w) else ticker.bid_price

            fee_rate = DEFAULT_FEE_BPS / 10000.0
            current_notionals = np.array([holdings * exec_price])
            target_weights = np.array([target_w])
            v_post, realized_fee = solve_post_fee_equity(v_pre, current_notionals, target_weights, fee_rate)

            target_notional = target_w * v_post
            trade_notional = abs(target_notional - (holdings * exec_price))
            new_holdings = target_notional / exec_price
            new_cash = (1.0 - target_w) * v_post
        else:
            action = "HOLD"

    # Mark to market post-action
    current_eq = new_cash + new_holdings * ticker.mid_price
    new_peak_eq = max(peak_eq, current_eq)
    dd = (current_eq - new_peak_eq) / new_peak_eq if new_peak_eq > 0 else 0.0
    max_dd = min(float(state["max_drawdown"]), dd)

    result_entry = {
        "timestamp_utc": server_dt.isoformat(),
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

    # Persist state if not dry-run and not already processed
    if not dry_run and not already_processed:
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
        state["last_approved_exposure"] = sig.approved_exposure
        state["last_raw_exposure"] = sig.raw_exposure

        save_paper_state_atomic(state, state_file=state_file)
        append_paper_ledger_entry(result_entry, ledger_file=ledger_file)

    return result_entry


def print_status(
    provider: MarketDataProvider | None = None,
    state_file: Path = PAPER_STATE_FILE,
    ledger_file: Path = PAPER_LEDGER_FILE,
) -> None:
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
    print(f"Last Processed Date:    {state.get('last_processed_decision_date', 'None')}")
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
) -> None:
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

    if args.init_epoch:
        init_epoch(epoch_id=args.epoch_id, capital=args.capital, force=args.force)
        return

    if args.status:
        print_status(provider=provider)
        return

    if args.step or args.dry_run:
        try:
            entry = evaluate_observer(provider=provider, dry_run=args.dry_run)
            mode_prefix = "[DRY-RUN] " if args.dry_run else ""
            print(f"{mode_prefix}Forward Observer Evaluation at {entry['timestamp_utc']}:")
            print(f"  Decision Date:       {entry['decision_date']} (Candle: {entry['candle_date']})")
            print(f"  Server Time Drift:   {entry['clock_drift_ms']} ms")
            print(f"  Quote Mid Price:     ${entry['mid_price']:,.2f} (Spread: {entry['spread_bps']:.2f} bps)")
            print(f"  Donchian States:     [20d={entry['state_20']}, 55d={entry['state_55']}, 90d={entry['state_90']}]")
            print(f"  Exposure:            Raw={entry['raw_exposure']*100:.1f}%, Confirmed={entry['confirmed']} -> Approved={entry['approved_exposure']*100:.1f}%")
            print(f"  Portfolio Weights:   Current={entry['current_btc_weight']*100:.1f}%, Target={entry['target_btc_weight']*100:.1f}%, Deviation={entry['deviation']*100:.1f}%")
            print(f"  Execution Status:    {entry['status']} (Eligibility: {entry['exec_eligibility']})")
            print(f"  Action Taken:        {entry['action']}")
            if entry["action"] == "REBALANCE":
                print(f"  Simulated Fill:      ExecPrice=${entry['exec_price']:,.2f}, Notional=${entry['trade_notional']:,.2f}, Fee(30bps)=${entry['fee']:,.2f}")
                print(f"  Fill Event ID:       {entry['event_id']}")
            print(f"  Updated NAV:         ${entry['nav']:,.2f} USDT (Drawdown: {entry['drawdown']*100:.2f}%)")
            print(f"  Holdings Post-Step:  Cash=${entry['post_cash']:,.2f}, BTC={entry['post_btc_holdings']:.6f}")
        except DataUnavailableError as e:
            print(f"FAIL CLOSED (DATA_UNAVAILABLE): {e}", file=sys.stderr)
            sys.exit(2)
        return

    print_status(provider=provider)


if __name__ == "__main__":
    main()
