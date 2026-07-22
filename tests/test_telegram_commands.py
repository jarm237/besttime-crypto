import queue

from btc_scraper.telegram_bot import commands, listener
from btc_scraper.trading import position_tracker


def _capture_replies(monkeypatch):
    replies = []

    def fake_send(text, parse_mode="HTML", reply_to_message_id=None, chat_id=None):
        replies.append({
            "text": text,
            "reply_to_message_id": reply_to_message_id,
            "chat_id": chat_id,
        })
        return len(replies)

    monkeypatch.setattr(commands, "send_telegram_message", fake_send)
    return replies


def _drain_scan_queue():
    while True:
        try:
            commands.telegram_command_queue.get_nowait()
            commands.telegram_command_queue.task_done()
        except queue.Empty:
            return


def test_group_command_suffix_is_supported(monkeypatch):
    replies = _capture_replies(monkeypatch)
    monkeypatch.setattr(commands, "format_status_message", lambda: "status-ok")

    commands.handle_telegram_command("/STATUS@BestTimeBot", chat_id=-1001, reply_to_id=42)

    assert replies == [{"text": "status-ok", "reply_to_message_id": 42, "chat_id": -1001}]


def test_buy_normalizes_pair_and_accepts_signal_basis_without_manual_price(monkeypatch):
    replies = _capture_replies(monkeypatch)
    captured = {}
    monkeypatch.setattr(commands, "get_latest_price", lambda coin: 67_100.0)

    def fake_add_position(**kwargs):
        captured.update(kwargs)
        return {"entry_time": "2026-07-22 09:00"}

    monkeypatch.setattr(position_tracker, "add_position", fake_add_position)
    monkeypatch.setattr(position_tracker, "get_open_positions", lambda: [])

    commands.handle_telegram_command("/buy BTC/USDT buy 75 signal", chat_id=123)

    assert captured["coin"] == "BTC"
    assert captured["direction"] == "LONG"
    assert captured["entry_price"] == 67_100.0
    assert captured["invested_usdt"] == 75.0
    assert captured["manual_decision_basis"] == "system_signal"
    assert replies[-1]["text"].startswith("✅")


def test_buy_rejects_duplicate_telegram_position(monkeypatch):
    replies = _capture_replies(monkeypatch)
    monkeypatch.setattr(commands, "get_latest_price", lambda coin: 100.0)
    monkeypatch.setattr(
        position_tracker,
        "get_open_positions",
        lambda: [{"coin": "BTC", "order_channel": "telegram", "status": "open"}],
    )

    commands.handle_telegram_command("/buy BTC LONG 50", chat_id=123)

    assert "Đã có vị thế Telegram đang mở" in replies[-1]["text"]


def test_buy_rejects_non_finite_or_negative_values(monkeypatch):
    replies = _capture_replies(monkeypatch)
    called = False

    def fake_add_position(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(position_tracker, "add_position", fake_add_position)

    commands.handle_telegram_command("/buy BTC LONG nan", chat_id=123)
    commands.handle_telegram_command("/buy BTC LONG -10", chat_id=123)

    assert called is False
    assert len(replies) == 2
    assert all("số dương hữu hạn" in reply["text"] for reply in replies)


def test_close_rejects_percentage_over_100(monkeypatch):
    replies = _capture_replies(monkeypatch)
    monkeypatch.setattr(commands, "get_latest_price", lambda coin: 100.0)

    commands.handle_telegram_command("/close BTC 150%", chat_id=123)

    assert len(replies) == 1
    assert "không được vượt quá 100%" in replies[0]["text"]


def test_close_partial_uses_telegram_position_filters(monkeypatch):
    replies = _capture_replies(monkeypatch)
    captured = {}

    def fake_close_partial(coin, price, percentage, **filters):
        captured.update({"coin": coin, "price": price, "percentage": percentage, **filters})
        return {
            "direction": "LONG",
            "entry_price": 100.0,
            "pnl_pct": 5.0,
            "pnl_usd_actual": 1.25,
            "invested_usdt": 25.0,
            "hold_hours": 2.0,
        }

    monkeypatch.setattr(position_tracker, "close_partial_position", fake_close_partial)

    commands.handle_telegram_command("/close btcusdt 25% 105", chat_id=123)

    assert captured == {
        "coin": "BTC",
        "price": 105.0,
        "percentage": 25.0,
        "trade_origin": "manual",
        "execution_mode": "manual",
        "order_creator": "user",
        "order_channel": "telegram",
    }
    assert replies[-1]["text"].startswith("✅")


def test_unknown_command_returns_help_hint(monkeypatch):
    replies = _capture_replies(monkeypatch)

    commands.handle_telegram_command("/does-not-exist", chat_id=123)

    assert "/help" in replies[0]["text"]


def test_scan_queue_is_bounded(monkeypatch):
    replies = _capture_replies(monkeypatch)
    _drain_scan_queue()

    commands.handle_telegram_command("/scan", chat_id=123)
    commands.handle_telegram_command("/signals", chat_id=123)

    assert commands.telegram_command_queue.qsize() == 1
    assert "đang chờ xử lý" in replies[-1]["text"]
    _drain_scan_queue()


def test_allowed_chat_ids_merge_primary_and_additional(monkeypatch):
    monkeypatch.setattr(listener, "TELEGRAM_CHAT_ID", "100")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "200, -300,200")

    assert listener._allowed_chat_ids() == {"100", "200", "-300"}


def test_register_bot_commands_updates_telegram_menu(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True, "result": True}

    def fake_post(url, json, timeout):
        captured.update({"url": url, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(listener, "TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setattr(listener.requests, "post", fake_post)

    listener._register_bot_commands()

    assert captured["url"].endswith("/bottest-token/setMyCommands")
    assert captured["json"]["commands"] == listener.BOT_COMMANDS
    assert {item["command"] for item in listener.BOT_COMMANDS} == {
        "start", "help", "status", "scan", "perf", "positions", "buy", "close"
    }
