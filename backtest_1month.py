"""
Backtest 1 tháng — Đánh giá chiến lược tín hiệu hiện tại
==========================================================
Bước 1: Cào nến 15m (1 tháng) từ Binance cho tất cả COINS → lưu CSV
Bước 2: Chạy analyze_market() theo rolling window (như live)
Bước 3: Mỗi khi có tín hiệu BUY/SELL → mở lệnh ảo
Bước 4: Đóng lệnh khi giá hit SL hoặc TP1 trên nến tiếp theo
Bước 5: In báo cáo tổng hợp đánh giá model

Cách chạy:
    python backtest_1month.py

Kết quả:
    data/backtest_candles_<COIN>.csv   — dữ liệu nến thô
    data/backtest_trades_<COIN>.csv    — các lệnh ảo từng coin
    data/backtest_summary.csv          — tổng hợp tất cả coins
"""

import sys, os, time, csv, requests
from datetime import datetime, timedelta, timezone

# Đảm bảo import được btc_scraper từ thư mục gốc project
sys.path.insert(0, os.path.dirname(__file__))

from btc_scraper.analysis import analyze_market
from btc_scraper.config import COINS

# ─── Config ───────────────────────────────────────────────────────────────────
INITIAL_CAPITAL    = 300.0        # USDT ban đầu
LOOKBACK_DAYS      = 30           # Số ngày lịch sử cần cào
CANDLE_INTERVAL    = "15m"        # Khung nến
CANDLES_PER_REQ    = 1000         # Max nến mỗi request Binance
WARMUP_CANDLES     = 220          # Nến dùng để "warm up" indicator (SMA200 cần ≥200)
FEE_RATE           = 0.001        # 0.1% phí mỗi chiều (spot)
# Ngưỡng lọc tín hiệu theo từng chiều giao dịch:
BUY_MIN_SCORE  = 65    # BUY: chỉ vào lệnh khi score >= 65 (MEDIUM+, action=BUY)
SELL_MAX_SCORE = 35    # SELL: chỉ vào lệnh khi score <= 35 (action=SELL)
# WEAK signals bị loại bỏ hoàn toàn (score 36-64 = NEUTRAL zone)
DATA_DIR           = os.path.join(os.path.dirname(__file__), "data")
BINANCE_BASE       = "https://api.binance.com"
# ──────────────────────────────────────────────────────────────────────────────

os.makedirs(DATA_DIR, exist_ok=True)


# ─── 1. CÀO DỮ LIỆU ──────────────────────────────────────────────────────────

def fetch_candles_range(coin: str, days: int, interval: str = "15m") -> list[dict]:
    """
    Cào toàn bộ nến trong `days` ngày gần nhất bằng cách paginate nhiều request.
    Trả về list dict {time, open, high, low, close, volume}.
    """
    symbol = f"{coin}USDT"
    url = f"{BINANCE_BASE}/api/v3/klines"

    end_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=days + WARMUP_CANDLES // 96)).timestamp() * 1000)
    # +WARMUP_CANDLES//96 ngày thêm để có đủ nến warmup (96 nến/ngày với 15m)

    all_candles = []
    current_start = start_ms

    while current_start < end_ms:
        params = {
            "symbol":    symbol,
            "interval":  interval,
            "startTime": current_start,
            "endTime":   end_ms,
            "limit":     CANDLES_PER_REQ,
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            raw = resp.json()
        except Exception as e:
            print(f"  [Lỗi] {coin}: {e}")
            break

        if not raw:
            break

        for k in raw:
            all_candles.append({
                "time":   datetime.fromtimestamp(k[0] / 1000).strftime("%Y-%m-%d %H:%M"),
                "open":   float(k[1]),
                "high":   float(k[2]),
                "low":    float(k[3]),
                "close":  float(k[4]),
                "volume": float(k[5]),
            })

        last_ts = raw[-1][0]
        if last_ts >= end_ms or len(raw) < CANDLES_PER_REQ:
            break
        current_start = last_ts + 1
        time.sleep(0.12)   # Rate limit: ~8 req/s

    # Loại bỏ nến trùng lặp và sắp xếp
    seen = set()
    unique = []
    for c in all_candles:
        if c["time"] not in seen:
            seen.add(c["time"])
            unique.append(c)
    unique.sort(key=lambda x: x["time"])
    return unique


def save_candles_csv(coin: str, candles: list[dict]) -> str:
    path = os.path.join(DATA_DIR, f"backtest_candles_{coin}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(candles)
    return path


def load_candles_csv(coin: str) -> list[dict]:
    path = os.path.join(DATA_DIR, f"backtest_candles_{coin}.csv")
    if not os.path.exists(path):
        return []
    candles = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append({
                "time":   row["time"],
                "open":   float(row["open"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "close":  float(row["close"]),
                "volume": float(row["volume"]),
            })
    return candles


# ─── 2. BACKTEST ENGINE ───────────────────────────────────────────────────────

def _is_actionable(signal: str) -> bool:
    s = signal.upper()
    return ("BUY" in s or "SELL" in s) and "NEUTRAL" not in s


def backtest_coin(coin: str, candles: list[dict], initial_capital: float) -> list[dict]:
    """
    Chạy backtest theo rolling window trên toàn bộ nến của một coin.

    Logic:
    - Dùng rolling window = WARMUP_CANDLES nến để chạy analyze_market tại mỗi bước.
    - Khi có tín hiệu BUY/SELL → mở lệnh ảo tại giá close của nến tín hiệu.
    - Các nến tiếp theo: kiểm tra high/low chạm SL hay TP1.
    - Đóng lệnh: hit SL → LOSS, hit TP1 → WIN.
    - Không mở lệnh mới khi đang có lệnh.
    """
    n = len(candles)
    if n < WARMUP_CANDLES + 2:
        print(f"  [Skip] {coin}: không đủ nến ({n} < {WARMUP_CANDLES + 2})")
        return []

    trades   = []
    capital  = initial_capital
    position = None   # dict khi đang giữ lệnh

    # Chỉ backtest trên phần dữ liệu "thực" (sau warmup)
    backtest_start = WARMUP_CANDLES

    for i in range(backtest_start, n):
        candle = candles[i]
        high   = candle["high"]
        low    = candle["low"]
        close  = candle["close"]

        # ── Kiểm tra đóng lệnh đang mở ──────────────────────────────────────
        if position is not None:
            sl  = position["sl"]
            tp1 = position["tp1"]
            direction = position["direction"]
            entry = position["entry"]
            invested = position["invested"]

            hit_sl  = False
            hit_tp1 = False

            if direction == "LONG":
                hit_sl  = low  <= sl
                hit_tp1 = high >= tp1
            else:  # SHORT
                hit_sl  = high >= sl
                hit_tp1 = low  <= tp1

            # Ưu tiên SL nếu cả hai bị hit cùng nến (worst case)
            if hit_sl or hit_tp1:
                exit_price = sl if hit_sl else tp1
                result     = "LOSS" if hit_sl else "WIN"

                if direction == "LONG":
                    pnl_pct = (exit_price - entry) / entry * 100
                else:
                    pnl_pct = (entry - exit_price) / entry * 100

                pnl_usd = invested * (pnl_pct / 100)
                fee_usd = (invested * FEE_RATE) + ((invested + pnl_usd) * FEE_RATE)
                net_pnl = pnl_usd - fee_usd
                capital += net_pnl

                trades.append({
                    "coin":         coin,
                    "direction":    direction,
                    "entry_time":   position["entry_time"],
                    "exit_time":    candle["time"],
                    "entry_price":  round(entry, 6),
                    "exit_price":   round(exit_price, 6),
                    "sl":           round(sl, 6),
                    "tp1":          round(tp1, 6),
                    "rr1":          position["rr1"],
                    "signal":       position["signal"],
                    "score":        position["score"],
                    "confidence":   position["confidence"],
                    "invested_usdt": round(invested, 2),
                    "pnl_pct":      round(pnl_pct, 4),
                    "pnl_usd":      round(net_pnl, 2),
                    "capital_after": round(capital, 2),
                    "result":       result,
                })
                position = None

        # ── Tìm tín hiệu mới (chỉ khi không có lệnh) ────────────────────────
        if position is None:
            # Rolling window: lấy WARMUP_CANDLES nến gần nhất tính đến nến i
            window = candles[max(0, i - WARMUP_CANDLES + 1): i + 1]

            try:
                # analyze_market cần list dict, trả về kết quả của nến cuối window
                ana = analyze_market(window)
            except Exception as e:
                continue

            signal = ana.get("signal", "")
            if not _is_actionable(signal):
                continue

            # Lấy thông tin tín hiệu
            sig_score_info = ana.get("signal_score", {}) or {}
            score      = sig_score_info.get("score", 0) or 0
            confidence = sig_score_info.get("confidence", "LOW")
            position_size = sig_score_info.get("position_size", 0.5) or 0.5

            action = sig_score_info.get("action", "NEUTRAL")

            # Lọc tín hiệu theo chiều:
            # - BUY: cần score >= BUY_MIN_SCORE (MEDIUM+ confidence)
            # - SELL: cần score <= SELL_MAX_SCORE (signal SELL thực sự)
            # - WEAK signals bị loại hoàn toàn
            if "WEAK" in signal.upper():
                continue
            if action == "BUY" and score < BUY_MIN_SCORE:
                continue
            if action == "SELL" and score > SELL_MAX_SCORE:
                continue
            if action == "NEUTRAL":
                continue

            tp_sl = ana.get("tp_sl", {})
            sl  = tp_sl.get("sl",  0.0)
            tp1 = tp_sl.get("tp1", 0.0)
            rr1 = tp_sl.get("rr1", 0.0)

            if sl <= 0 or tp1 <= 0:
                continue

            direction = "LONG" if "BUY" in signal.upper() else "SHORT"

            # Xác thực SL/TP hợp lệ
            if direction == "LONG" and (sl >= close or tp1 <= close):
                continue
            if direction == "SHORT" and (sl <= close or tp1 >= close):
                continue

            # Vốn vào lệnh theo position_size
            invested = round(capital * position_size, 2)
            if invested <= 0 or capital <= 0:
                continue

            position = {
                "entry":       close,
                "entry_time":  candle["time"],
                "sl":          sl,
                "tp1":         tp1,
                "rr1":         rr1,
                "direction":   direction,
                "signal":      signal,
                "score":       score,
                "confidence":  confidence,
                "invested":    invested,
            }

    return trades


# ─── 3. SAVE & REPORT ─────────────────────────────────────────────────────────

def save_trades_csv(coin: str, trades: list[dict]) -> str:
    if not trades:
        return ""
    path = os.path.join(DATA_DIR, f"backtest_trades_{coin}.csv")
    fieldnames = list(trades[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(trades)
    return path


def print_coin_summary(coin: str, trades: list[dict], initial_capital: float):
    if not trades:
        print(f"  [{coin}] Không có lệnh nào được khớp.")
        return

    wins   = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] == "LOSS"]
    total  = len(trades)
    win_rate = len(wins) / total * 100 if total else 0

    final_cap  = trades[-1]["capital_after"] if trades else initial_capital
    total_pnl  = sum(t["pnl_usd"] for t in trades)
    avg_rr     = sum(t["rr1"] for t in trades) / total if total else 0
    avg_win    = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss   = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0

    print(f"\n  ┌── [{coin}] ────────────────────────────────")
    print(f"  │  Tổng lệnh   : {total:>4}  (WIN: {len(wins)}, LOSS: {len(losses)})")
    print(f"  │  Win rate    : {win_rate:>6.1f}%")
    print(f"  │  Avg W/L PnL : +{avg_win:.3f}% / {avg_loss:.3f}%")
    print(f"  │  Avg R:R     : {avg_rr:.2f}")
    print(f"  │  Net PnL     : ${total_pnl:+.2f}")
    print(f"  │  Vốn cuối   : ${final_cap:.2f}  (ban đầu: ${initial_capital:.2f})")
    print(f"  └─────────────────────────────────────────")


def save_summary_csv(all_trades: list[dict]):
    path = os.path.join(DATA_DIR, "backtest_summary.csv")
    if not all_trades:
        print("Không có lệnh nào để tổng hợp.")
        return path
    fieldnames = list(all_trades[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_trades)
    return path


def print_overall_summary(all_trades: list[dict], initial_capital: float):
    if not all_trades:
        print("\n[Tổng hợp] Không có lệnh nào.")
        return

    total  = len(all_trades)
    wins   = [t for t in all_trades if t["result"] == "WIN"]
    losses = [t for t in all_trades if t["result"] == "LOSS"]
    win_rate = len(wins) / total * 100 if total else 0
    total_pnl = sum(t["pnl_usd"] for t in all_trades)
    avg_win  = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_pct"] for t in losses) / len(losses) if losses else 0
    avg_rr   = sum(t["rr1"] for t in all_trades) / total if total else 0
    profit_factor = (
        abs(sum(t["pnl_usd"] for t in wins)) / abs(sum(t["pnl_usd"] for t in losses))
        if losses and sum(t["pnl_usd"] for t in losses) != 0 else None
    )

    # Max consecutive losses
    consec = max_consec = 0
    for t in all_trades:
        if t["result"] == "LOSS":
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0

    print("\n" + "=" * 55)
    print("  ĐÁNH GIÁ MÔ HÌNH — BACKTEST 1 THÁNG (15m)")
    print("=" * 55)
    print(f"  Tổng lệnh          : {total}")
    print(f"  Số WIN             : {len(wins)}  ({win_rate:.1f}%)")
    print(f"  Số LOSS            : {len(losses)}")
    print(f"  Win Rate           : {win_rate:.1f}%")
    print(f"  Avg Win PnL        : +{avg_win:.3f}%")
    print(f"  Avg Loss PnL       : {avg_loss:.3f}%")
    print(f"  Avg R:R (TP1)      : {avg_rr:.2f}")
    print(f"  Profit Factor      : {profit_factor:.2f}" if profit_factor else "  Profit Factor      : N/A")
    print(f"  Max Consec. Losses : {max_consec}")
    print(f"  Tổng PnL           : ${total_pnl:+.2f}")
    print(f"  Vốn ban đầu        : ${initial_capital:.2f}")
    print("=" * 55)

    # Phân tích theo signal type
    from collections import defaultdict
    by_signal: dict[str, list] = defaultdict(list)
    for t in all_trades:
        sig_key = t["signal"].split("(")[0].strip() if "(" in t["signal"] else t["signal"]
        by_signal[sig_key].append(t)

    print("\n  Phân tích theo loại tín hiệu:")
    print(f"  {'Signal':<35} {'#':>4} {'Win%':>6} {'AvgPnL':>8}")
    print("  " + "-" * 55)
    for sig, tlist in sorted(by_signal.items(), key=lambda x: -len(x[1])):
        w = sum(1 for t in tlist if t["result"] == "WIN")
        wr = w / len(tlist) * 100
        avg = sum(t["pnl_pct"] for t in tlist) / len(tlist)
        print(f"  {sig:<35} {len(tlist):>4} {wr:>5.1f}% {avg:>+8.3f}%")

    # Phân tích theo coin
    from collections import defaultdict
    by_coin: dict[str, list] = defaultdict(list)
    for t in all_trades:
        by_coin[t["coin"]].append(t)

    print("\n  Phân tích theo coin:")
    print(f"  {'Coin':<8} {'#':>4} {'Win%':>6} {'NetPnL':>9}")
    print("  " + "-" * 30)
    for coin, tlist in sorted(by_coin.items(), key=lambda x: -sum(t["pnl_usd"] for t in x[1])):
        w = sum(1 for t in tlist if t["result"] == "WIN")
        wr = w / len(tlist) * 100
        net = sum(t["pnl_usd"] for t in tlist)
        print(f"  {coin:<8} {len(tlist):>4} {wr:>5.1f}% {net:>+9.2f}$")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  BACKTEST 1 THÁNG — CHIẾN LƯỢC 15m")
    print(f"  Coins: {', '.join(COINS)}")
    print(f"  Vốn ban đầu mỗi coin: ${INITIAL_CAPITAL:.2f} USDT")
    print(f"  Lookback: {LOOKBACK_DAYS} ngày | Warmup: {WARMUP_CANDLES} nến")
    print("=" * 55)

    all_trades = []

    for coin in COINS:
        csv_path = os.path.join(DATA_DIR, f"backtest_candles_{coin}.csv")

        # Kiểm tra cache: nếu file CSV đã có và < 1 giờ tuổi thì dùng lại
        use_cache = False
        if os.path.exists(csv_path):
            age_hours = (time.time() - os.path.getmtime(csv_path)) / 3600
            if age_hours < 1:
                use_cache = True
                print(f"\n[{coin}] Dùng cache CSV ({age_hours:.1f}h trước)...")

        if use_cache:
            candles = load_candles_csv(coin)
        else:
            print(f"\n[{coin}] Đang cào {LOOKBACK_DAYS} ngày nến {CANDLE_INTERVAL}...")
            candles = fetch_candles_range(coin, LOOKBACK_DAYS, CANDLE_INTERVAL)
            if not candles:
                print(f"  [Skip] {coin}: không lấy được dữ liệu.")
                continue
            save_candles_csv(coin, candles)
            print(f"  → {len(candles)} nến | Lưu: {csv_path}")

        if not candles:
            continue

        print(f"[{coin}] Đang chạy backtest trên {len(candles)} nến...")
        trades = backtest_coin(coin, candles, INITIAL_CAPITAL)

        print_coin_summary(coin, trades, INITIAL_CAPITAL)

        if trades:
            trade_path = save_trades_csv(coin, trades)
            print(f"  → Lệnh lưu: {trade_path}")
            all_trades.extend(trades)

    # Tổng hợp
    summary_path = save_summary_csv(all_trades)
    print_overall_summary(all_trades, INITIAL_CAPITAL)
    print(f"\n[Xong] Kết quả tổng hợp: {summary_path}")


if __name__ == "__main__":
    main()
