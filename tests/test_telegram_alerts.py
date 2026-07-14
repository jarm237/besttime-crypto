from btc_scraper.telegram_bot import alerts


def test_send_signals_alert_includes_kelly_fraction(monkeypatch):
    sent = []

    def fake_send(message, parse_mode=None):
        sent.append(message)
        return len(sent)

    monkeypatch.setattr(alerts, "TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setattr(alerts, "TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(alerts, "send_telegram_message", fake_send)

    msg_id = alerts.send_signals_alert({
        "BTC:Binance": {
            "signal": "BUY (Crossover)",
            "reason": "test reason",
            "close": 100.0,
            "rsi": 55.0,
            "signal_score": {
                "action": "BUY",
                "score": 72,
                "display_label": "BUY 72%",
                "display_score": 72,
                "confidence": "MEDIUM",
                "meta_confidence_pct": 68,
                "kelly_fraction": 0.1234,
            },
            "tp_sl": {
                "entry": 100.0,
                "sl": 98.0,
                "tp1": 104.0,
                "tp2": 108.0,
                "rr1": 2.0,
                "rr2": 4.0,
            },
        }
    })

    assert msg_id == 1
    assert sent
    assert "Kelly: 12.3%" in sent[0]
