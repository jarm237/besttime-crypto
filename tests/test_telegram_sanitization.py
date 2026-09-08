import pytest
import requests
from btc_scraper.telegram_bot.api import sanitize_telegram_error, send_telegram_message
from btc_scraper.execution.alerting import AlertManager

def test_sanitize_telegram_error_redacts_token():
    dummy_token = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    error_str = f"HTTPError: 429 Client Error for url: https://api.telegram.org/bot{dummy_token}/sendMessage"

    sanitized = sanitize_telegram_error(error_str, dummy_token)
    assert dummy_token not in sanitized
    assert "bot***REDACTED***" in sanitized

def test_sanitize_telegram_error_with_exception():
    dummy_token = "987654321:XYZabc123"
    url = f"https://api.telegram.org/bot{dummy_token}/sendMessage"
    exc = requests.exceptions.HTTPError(f"429 Client Error for url: {url}")

    sanitized = sanitize_telegram_error(exc, dummy_token)
    assert dummy_token not in sanitized
    assert "***REDACTED***" in sanitized

def test_send_telegram_message_sanitizes_token(capsys, monkeypatch):
    dummy_token = "111222333:SecretTokenValue"
    monkeypatch.setattr("btc_scraper.telegram_bot.api.TELEGRAM_BOT_TOKEN", dummy_token)
    monkeypatch.setattr("btc_scraper.telegram_bot.api.TELEGRAM_CHAT_ID", "12345")

    def mock_post(*args, **kwargs):
        url = args[0] if args else kwargs.get("url", "")
        raise requests.exceptions.HTTPError(f"429 Client Error for url: {url}")

    monkeypatch.setattr(requests, "post", mock_post)

    result = send_telegram_message("Test message")
    assert result is None

    captured = capsys.readouterr().out
    assert dummy_token not in captured
    assert "***REDACTED***" in captured

def test_alert_manager_sanitizes_token_in_logs(caplog, tmp_path):
    dummy_token = "999888777:AnotherSecretToken"
    mgr = AlertManager(
        telegram_token=dummy_token,
        telegram_chat_id="12345",
        db_path=str(tmp_path / "alerts.db"),
        log_path=str(tmp_path / "alerts.log"),
    )

    def mock_post(*args, **kwargs):
        raise requests.exceptions.HTTPError(f"429 Client Error for url: https://api.telegram.org/bot{dummy_token}/sendMessage")

    import requests
    monkeypatch_post = pytest.MonkeyPatch()
    monkeypatch_post.setattr(requests, "post", mock_post)

    try:
        success = mgr._send_telegram("Alert test")
        assert success is False
        assert dummy_token not in caplog.text
        assert "***REDACTED***" in caplog.text
    finally:
        monkeypatch_post.undo()
