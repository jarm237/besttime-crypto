"""
Auto Trader — Decision engine tự động đặt lệnh Market trên Binance Testnet.

Luồng:
    analysis dict (từ analyze_market)
        ↓
    AutoTrader.evaluate_and_trade(analysis)
        ↓
    should_trade() — kiểm tra ngưỡng meta_confidence + score + filters
        ↓ YES
    compute_position_size() — 2% risk dựa trên SL distance
        ↓
    place_order() — CCXTClient.create_market_buy/sell
        ↓
    log_order() — ghi vào logs/auto_trade_log.json
        ↓
    notify_telegram() — gửi alert
        ↓
    position_tracker.add_position() — sync với hệ thống tracking

Circuit Breaker:
    - 5 lệnh thua liên tiếp → pause 24h
    - Reset tự động sau 24h hoặc khi user restart bot

Config (từ .env):
    AUTO_TRADE_DRY_RUN=true               # Bắt buộc false để live
    AUTO_TRADE_BINANCE_API_KEY=...
    AUTO_TRADE_BINANCE_API_SECRET=...
    AUTO_TRADE_BINANCE_TESTNET=true       # false = mainnet (không khuyến nghị)
    AUTO_TRADE_META_THRESHOLD=0.85
    AUTO_TRADE_SCORE_THRESHOLD=75
    AUTO_TRADE_ACCOUNT_USDT=500           # Kích thước tài khoản ước tính
    AUTO_TRADE_RISK_PCT=2.0               # % risk per trade
    AUTO_TRADE_MAX_TRADE_USDT=100         # Cap tối đa mỗi lệnh
    AUTO_TRADE_MIN_TRADE_USDT=10          # Minimum (Binance min notional)
    AUTO_TRADE_MAX_DAILY=5                # Số lệnh tối đa/ngày
    AUTO_TRADE_CIRCUIT_BREAKER_N=5        # Dừng sau N lệnh thua liên tiếp
    AUTO_TRADE_COINS=                     # Để trống = tất cả COINS
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

BASE_DIR = Path(__file__).parent.parent
AUTO_TRADE_LOG = BASE_DIR / "logs" / "auto_trade_log.json"
CIRCUIT_BREAKER_STATE = BASE_DIR / "logs" / "auto_trade_circuit.json"

# ─── Config Loader ─────────────────────────────────────────────────────────────

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except Exception:
        return default

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except Exception:
        return default

def _env_bool(key: str, default: bool) -> bool:
    v = os.getenv(key, str(default)).lower()
    return v not in ("false", "0", "no", "off")

def _env_list(key: str, default: List[str]) -> List[str]:
    v = os.getenv(key, "").strip()
    return [x.strip().upper() for x in v.split(",") if x.strip()] if v else default


# ─── Audit Log ─────────────────────────────────────────────────────────────────

def _load_log() -> List[Dict]:
    if not AUTO_TRADE_LOG.exists():
        return []
    try:
        with open(AUTO_TRADE_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_log(data: List[Dict]) -> None:
    AUTO_TRADE_LOG.parent.mkdir(exist_ok=True)
    with open(AUTO_TRADE_LOG, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _append_log(entry: Dict) -> None:
    data = _load_log()
    data.append(entry)
    _save_log(data)


# ─── Circuit Breaker State ──────────────────────────────────────────────────────

def _load_circuit() -> Dict:
    if not CIRCUIT_BREAKER_STATE.exists():
        return {"consecutive_losses": 0, "tripped_at": None, "total_trades_today": 0, "date": ""}
    try:
        with open(CIRCUIT_BREAKER_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"consecutive_losses": 0, "tripped_at": None, "total_trades_today": 0, "date": ""}

def _save_circuit(state: Dict) -> None:
    CIRCUIT_BREAKER_STATE.parent.mkdir(exist_ok=True)
    with open(CIRCUIT_BREAKER_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ─── Main AutoTrader Class ──────────────────────────────────────────────────────

class AutoTrader:
    """
    Singleton-like auto-trading engine.
    Sử dụng: auto_trader.evaluate_and_trade(analysis_dict)
    """

    def __init__(self):
        self._client = None  # Lazy init CCXTClient

    @property
    def dry_run(self) -> bool:
        return _env_bool("AUTO_TRADE_DRY_RUN", True)

    @property
    def meta_threshold(self) -> float:
        return _env_float("AUTO_TRADE_META_THRESHOLD", 0.85)

    @property
    def score_threshold(self) -> int:
        return _env_int("AUTO_TRADE_SCORE_THRESHOLD", 75)

    @property
    def account_usdt(self) -> float:
        return _env_float("AUTO_TRADE_ACCOUNT_USDT", 500.0)

    @property
    def risk_pct(self) -> float:
        """% tài khoản risk mỗi lệnh (mặc định 2%)."""
        return _env_float("AUTO_TRADE_RISK_PCT", 2.0)

    @property
    def max_trade_usdt(self) -> float:
        return _env_float("AUTO_TRADE_MAX_TRADE_USDT", 100.0)

    @property
    def min_trade_usdt(self) -> float:
        return _env_float("AUTO_TRADE_MIN_TRADE_USDT", 10.0)

    @property
    def max_daily_trades(self) -> int:
        return _env_int("AUTO_TRADE_MAX_DAILY", 5)

    @property
    def circuit_breaker_n(self) -> int:
        return _env_int("AUTO_TRADE_CIRCUIT_BREAKER_N", 5)

    @property
    def allowed_coins(self) -> List[str]:
        """List coins cho phép auto-trade. Để trống = tất cả."""
        from btc_scraper.config import COINS
        return _env_list("AUTO_TRADE_COINS", list(COINS))

    def _get_client(self):
        """Lazy-init CCXTClient."""
        if self._client is None:
            from btc_scraper.ccxt_client import CCXTClient
            self._client = CCXTClient.from_env()
        return self._client

    # ─── Circuit Breaker ────────────────────────────────────────────────────────

    def _check_circuit_breaker(self) -> tuple[bool, str]:
        """
        Kiểm tra circuit breaker.
        Returns: (is_ok, reason_if_blocked)
        """
        state = _load_circuit()
        today = datetime.now().strftime("%Y-%m-%d")

        # Reset daily counter nếu sang ngày mới
        if state.get("date") != today:
            state["total_trades_today"] = 0
            state["date"] = today
            # Không reset consecutive_losses — vẫn nhớ chuỗi thua qua ngày

        # Kiểm tra circuit breaker tripped
        if state.get("tripped_at"):
            tripped_at = state["tripped_at"]
            try:
                tripped_dt = datetime.fromisoformat(tripped_at)
                elapsed = (datetime.now() - tripped_dt).total_seconds()
                if elapsed < 86400:  # 24 giờ
                    remaining_h = (86400 - elapsed) / 3600
                    return False, f"Circuit breaker: {self.circuit_breaker_n} thua lien tiep. Reset sau {remaining_h:.1f}h"
                else:
                    # Auto-reset sau 24h
                    state["tripped_at"] = None
                    state["consecutive_losses"] = 0
                    _save_circuit(state)
            except Exception:
                state["tripped_at"] = None
                _save_circuit(state)

        # Kiểm tra daily limit
        if state.get("total_trades_today", 0) >= self.max_daily_trades:
            return False, f"Da dat gioi han {self.max_daily_trades} lenh/ngay"

        return True, ""

    def _trip_circuit_breaker(self) -> None:
        """Kích hoạt circuit breaker."""
        state = _load_circuit()
        state["tripped_at"] = datetime.now().isoformat()
        _save_circuit(state)

    def _record_trade_result(self, result: str) -> None:
        """
        Cập nhật circuit breaker state sau mỗi lệnh.
        result: 'WIN' | 'LOSS' | 'OPEN' (chưa biết)
        """
        state = _load_circuit()
        today = datetime.now().strftime("%Y-%m-%d")
        if state.get("date") != today:
            state["total_trades_today"] = 0
            state["date"] = today

        if result == "OPEN":
            state["total_trades_today"] = state.get("total_trades_today", 0) + 1
        elif result == "LOSS":
            state["consecutive_losses"] = state.get("consecutive_losses", 0) + 1
            if state["consecutive_losses"] >= self.circuit_breaker_n:
                state["tripped_at"] = datetime.now().isoformat()
        elif result == "WIN":
            state["consecutive_losses"] = 0
        # OPEN: không thay đổi consecutive_losses

        _save_circuit(state)

    # ─── Position Size ──────────────────────────────────────────────────────────

    def compute_position_size(
        self,
        entry_price: float,
        sl_price: float,
        current_balance: Optional[float] = None,
        multiplier: float = 1.0,
    ) -> float:
        """
        Tính position size dựa trên fixed fractional risk (2% mặc định) nhân với setup multiplier (Kelly/Regime).

        Formula:
            risk_usdt = account_balance * (risk_pct * multiplier) / 100
            sl_distance_pct = |entry - sl| / entry
            position_usdt = risk_usdt / sl_distance_pct

        Cap tại max_trade_usdt và min_trade_usdt.

        Args:
            entry_price: Giá vào lệnh
            sl_price: Giá stop-loss
            current_balance: Balance thực tế (nếu None, dùng AUTO_TRADE_ACCOUNT_USDT)
            multiplier: Hệ số nhân điều chỉnh rủi ro của setup (Kelly fraction, market regime)

        Returns:
            Số USDT để invest vào lệnh này
        """
        balance = current_balance if current_balance and current_balance > 0 else self.account_usdt
        
        # Scale risk_pct dynamically by the setup multiplier (Kelly sizing / market regime)
        adjusted_risk_pct = self.risk_pct * max(0.01, min(1.0, multiplier))
        risk_usdt = balance * adjusted_risk_pct / 100.0  # VD: 500 * (2% * 0.5) = 5 USDT risk

        if entry_price <= 0 or sl_price <= 0:
            # Fallback: dùng adjusted risk nếu không có SL
            return min(self.max_trade_usdt, max(self.min_trade_usdt, risk_usdt))

        sl_distance_pct = abs(entry_price - sl_price) / entry_price
        if sl_distance_pct < 0.001:
            # SL quá gần, dùng 0.5% minimum distance để tránh oversizing
            sl_distance_pct = 0.005

        # risk_usdt / sl_distance = notional cần thiết để risk đúng risk_pct
        position_usdt = risk_usdt / sl_distance_pct

        # Apply caps
        position_usdt = min(position_usdt, self.max_trade_usdt)
        position_usdt = max(position_usdt, self.min_trade_usdt)

        return round(position_usdt, 2)

    # ─── Trade Decision ─────────────────────────────────────────────────────────

    def should_trade(
        self,
        coin: str,
        signal: str,
        meta_confidence: float,
        signal_score: int,
    ) -> tuple[bool, str]:
        """
        Kiểm tra xem có nên trade không.

        Returns:
            (should_trade: bool, reason: str)
        """
        # 1. Coin có trong whitelist không?
        if coin.upper() not in [c.upper() for c in self.allowed_coins]:
            return False, f"{coin} khong trong allowed_coins"

        # 2. Phải là BUY hoặc SELL rõ ràng
        is_buy = "BUY" in signal.upper()
        is_sell = "SELL" in signal.upper()
        if not (is_buy or is_sell):
            return False, f"Signal {signal!r} khong phai BUY/SELL"

        # 3. WEAK signal → bỏ qua
        if "WEAK" in signal.upper():
            return False, f"Signal WEAK, bo qua: {signal}"

        # 4. Meta confidence threshold
        if meta_confidence < self.meta_threshold:
            return False, (
                f"Meta confidence {meta_confidence:.1%} < nguong {self.meta_threshold:.1%}"
            )

        # 5. Signal score threshold
        if signal_score < self.score_threshold:
            return False, f"Score {signal_score} < nguong {self.score_threshold}"

        return True, "OK"

    def _has_open_position(self, coin: str, direction: str) -> bool:
        """Kiểm tra đã có position cùng coin+direction chưa."""
        try:
            from btc_scraper.position_tracker import get_open_positions
            positions = get_open_positions()
            for p in positions:
                if p.get("coin", "").upper() == coin.upper() and p.get("direction", "").upper() == direction.upper():
                    return True
        except Exception:
            pass
        return False

    # ─── Core: Evaluate & Trade ─────────────────────────────────────────────────

    def evaluate_and_trade(self, analysis: Dict[str, Any]) -> List[Dict]:
        """
        Entry point chính. Gọi sau mỗi cycle fetch_and_display().

        Args:
            analysis: dict {coin:exchange → analysis_dict} từ analyze_market()

        Returns:
            List các lệnh đã được xử lý (để log/notify)
        """
        placed = []

        for key, ana in analysis.items():
            try:
                result = self._process_signal(key, ana)
                if result:
                    placed.append(result)
            except Exception as e:
                _append_log({
                    "timestamp": datetime.now().isoformat(),
                    "key": key,
                    "mode": self._get_client().mode if False else ("DRY_RUN" if self.dry_run else "LIVE"),
                    "status": "error",
                    "error": str(e),
                })

        return placed

    def _process_signal(self, key: str, ana: Dict) -> Optional[Dict]:
        """Xử lý một signal từ một coin."""
        coin = key.split(":")[0].upper()
        sig_score = ana.get("signal_score") or {}
        signal = ana.get("signal", "")
        meta_prob = sig_score.get("meta_confidence")
        score = sig_score.get("score", 0)

        # Thiếu meta confidence → bỏ qua (model chưa train)
        if meta_prob is None:
            return None

        # Kiểm tra should_trade
        ok, reason = self.should_trade(coin, signal, float(meta_prob), int(score))
        if not ok:
            return None  # Không log skip bình thường để tránh spam

        # Kiểm tra circuit breaker + daily limit
        cb_ok, cb_reason = self._check_circuit_breaker()
        if not cb_ok:
            log_entry = self._build_skip_log(coin, signal, meta_prob, score, cb_reason, ana)
            _append_log(log_entry)
            return log_entry

        # Direction
        direction = "LONG" if "BUY" in signal.upper() else "SHORT"

        # Không trade nếu đã có position cùng direction
        if self._has_open_position(coin, direction):
            return None

        # Lấy TP/SL data
        tp_sl = ana.get("tp_sl") or {}
        entry_price = tp_sl.get("entry") or ana.get("close") or 0.0
        sl_price = tp_sl.get("sl") or 0.0
        tp1_price = tp_sl.get("tp1") or 0.0

        # Tính position size
        try:
            # Thử lấy balance thực từ exchange
            client = self._get_client()
            if not self.dry_run:
                real_balance = client.get_usdt_balance()
            else:
                real_balance = self.account_usdt
        except Exception:
            real_balance = self.account_usdt

        usdt_amount = self.compute_position_size(
            entry_price=float(entry_price),
            sl_price=float(sl_price),
            current_balance=real_balance,
            multiplier=float(sig_score.get("position_size", 1.0)),
        )

        # Đặt lệnh
        symbol = f"{coin}/USDT"
        order_side = "buy" if direction == "LONG" else "sell"

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "timestamp_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "DRY_RUN" if self.dry_run else "TESTNET",
            "coin": coin,
            "symbol": symbol,
            "direction": direction,
            "signal": signal,
            "meta_confidence": round(float(meta_prob), 4),
            "meta_confidence_pct": int(round(float(meta_prob) * 100)),
            "signal_score": int(score),
            "order_type": "market",
            "entry_price": float(entry_price),
            "sl_price": float(sl_price),
            "tp1_price": float(tp1_price),
            "usdt_amount": usdt_amount,
            "account_balance_est": real_balance,
            "order_id": None,
            "status": None,
            "error": None,
        }

        try:
            if order_side == "buy":
                order = self._get_client().create_market_buy(symbol, usdt_amount)
            else:
                order = self._get_client().create_market_sell(symbol, usdt_amount)

            log_entry["order_id"] = order.get("id")
            log_entry["status"] = order.get("status", "placed")
            log_entry["filled_price"] = order.get("price") or entry_price

            # Sync với position tracker
            try:
                from btc_scraper.position_tracker import add_position
                add_position(
                    coin=coin,
                    entry_price=float(order.get("price") or entry_price),
                    direction=direction,
                    note=f"[AUTO-{log_entry['mode']}] {signal} | Meta={log_entry['meta_confidence_pct']}%",
                    invested_usdt=usdt_amount,
                    signal_score=sig_score,
                    confidence=float(meta_prob),
                )
            except Exception:
                pass

            # Record cho circuit breaker (OPEN = chưa biết WIN/LOSS)
            self._record_trade_result("OPEN")

            # Gửi Telegram
            self._notify_trade(log_entry)

        except Exception as e:
            log_entry["status"] = "error"
            log_entry["error"] = str(e)

        _append_log(log_entry)
        return log_entry

    def _build_skip_log(self, coin, signal, meta_prob, score, reason, ana) -> Dict:
        tp_sl = ana.get("tp_sl") or {}
        return {
            "timestamp": datetime.now().isoformat(),
            "timestamp_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": "DRY_RUN" if self.dry_run else "TESTNET",
            "coin": coin,
            "signal": signal,
            "meta_confidence": round(float(meta_prob), 4),
            "signal_score": int(score),
            "status": "skipped",
            "reason_skip": reason,
            "entry_price": tp_sl.get("entry") or ana.get("close"),
        }

    def _notify_trade(self, entry: Dict) -> None:
        """Gửi Telegram alert về auto-trade."""
        try:
            from btc_scraper.telegram_bot import send_telegram_message
            mode = entry.get("mode", "DRY_RUN")
            coin = entry.get("coin", "?")
            direction = entry.get("direction", "?")
            signal = entry.get("signal", "?")
            meta_pct = entry.get("meta_confidence_pct", 0)
            score = entry.get("signal_score", 0)
            usdt = entry.get("usdt_amount", 0)
            entry_price = entry.get("entry_price", 0)
            sl = entry.get("sl_price", 0)
            tp1 = entry.get("tp1_price", 0)
            order_id = entry.get("order_id", "?")
            status = entry.get("status", "?")
            err = entry.get("error")

            if err:
                msg = (
                    f"[AUTO-TRADE ERROR] {coin}\n"
                    f"Mode: {mode}\n"
                    f"Signal: {signal}\n"
                    f"Loi: {err}"
                )
            else:
                msg = (
                    f"[AUTO-TRADE] {mode}\n"
                    f"Coin: {coin} | {direction}\n"
                    f"Signal: {signal}\n"
                    f"Meta: {meta_pct}% | Score: {score}\n"
                    f"So tien: ${usdt:.2f} USDT\n"
                    f"Entry: ${entry_price:,.4f}\n"
                    f"SL: ${sl:,.4f}\n"
                    f"TP1: ${tp1:,.4f}\n"
                    f"Order ID: {order_id}\n"
                    f"Trang thai: {status}"
                )
            send_telegram_message(msg, parse_mode=None)
        except Exception:
            pass

    def status(self) -> Dict:
        """Trả về trạng thái hiện tại của AutoTrader."""
        state = _load_circuit()
        today = datetime.now().strftime("%Y-%m-%d")
        tripped = state.get("tripped_at")
        tripped_remaining_h = None
        if tripped:
            try:
                elapsed = (datetime.now() - datetime.fromisoformat(tripped)).total_seconds()
                remaining = max(0, 86400 - elapsed)
                tripped_remaining_h = round(remaining / 3600, 1)
            except Exception:
                pass

        logs = _load_log()
        today_logs = [l for l in logs if l.get("timestamp", "").startswith(today)]
        placed_today = [l for l in today_logs if l.get("status") not in ("skipped", "error")]

        return {
            "mode": "DRY_RUN" if self.dry_run else "TESTNET",
            "meta_threshold": self.meta_threshold,
            "score_threshold": self.score_threshold,
            "risk_pct": self.risk_pct,
            "max_trade_usdt": self.max_trade_usdt,
            "circuit_breaker_n": self.circuit_breaker_n,
            "circuit_tripped": bool(tripped),
            "circuit_tripped_remaining_h": tripped_remaining_h,
            "consecutive_losses": state.get("consecutive_losses", 0),
            "trades_today": state.get("total_trades_today", 0),
            "max_daily_trades": self.max_daily_trades,
            "allowed_coins": self.allowed_coins,
            "total_auto_trades": len([l for l in logs if l.get("status") not in ("skipped", "error")]),
        }


# Singleton instance — import trực tiếp từ module
auto_trader = AutoTrader()
