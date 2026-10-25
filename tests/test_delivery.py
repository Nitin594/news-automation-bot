"""Unit tests for Telegram and SMTP delivery services."""

from unittest.mock import MagicMock, patch
import pytest
import requests

from daily_tech_brief.config import Settings
from daily_tech_brief.delivery import DeliveryService, EmailNotifier, TelegramNotifier, mask_token


def test_mask_token():
    assert mask_token("12345678:ABCDEF123456789") == "1234...6789"
    assert mask_token("short") == "***"
    assert mask_token("") == "***"


def test_telegram_send_success():
    notifier = TelegramNotifier(bot_token="test_token", chat_id="12345")
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 42}}
        mock_post.return_value = mock_resp

        result = notifier.deliver_digest(["<b>Hello Telegram</b>"])
        assert result.success is True
        assert result.status == "SUCCESS"
        assert result.message_id == "42"


def test_telegram_send_failure():
    notifier = TelegramNotifier(bot_token="test_token", chat_id="12345")
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 401
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json.return_value = {"ok": False, "description": "Unauthorized"}
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("401 Unauthorized")
        mock_post.return_value = mock_resp

        result = notifier.deliver_digest(["Test"])
        assert result.success is False
        assert result.status == "FAILED"
        assert "401" in result.error_message


def test_telegram_html_parse_fallback_to_plain():
    notifier = TelegramNotifier(bot_token="test_token", chat_id="12345")
    with patch("requests.post") as mock_post:
        # First call fails with "can't parse entities"
        mock_fail = MagicMock()
        mock_fail.ok = False
        mock_fail.status_code = 400
        mock_fail.headers = {"content-type": "application/json"}
        mock_fail.json.return_value = {"description": "Bad Request: can't parse entities in message"}

        # Second call with plain text succeeds
        mock_ok = MagicMock()
        mock_ok.ok = True
        mock_ok.status_code = 200
        mock_ok.json.return_value = {"ok": True, "result": {"message_id": 99}}

        mock_post.side_effect = [mock_fail, mock_ok]

        result = notifier.deliver_digest(["Message with <b>bad tag"])
        assert result.success is True
        assert result.message_id == "99"
        assert mock_post.call_count == 2


def test_smtp_send_success():
    notifier = EmailNotifier(
        host="smtp.example.com",
        port=587,
        username="user@example.com",
        password="password",
        sender="sender@example.com",
        recipient="dest@example.com",
    )
    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server
        mock_server.__enter__.return_value = mock_server

        result = notifier.send_email("Test Subject", "Plain content", "<p>HTML content</p>")
        assert result.success is True
        assert result.status == "SUCCESS"
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user@example.com", "password")
        mock_server.send_message.assert_called_once()


def test_smtp_send_auth_failure():
    notifier = EmailNotifier(
        host="smtp.example.com",
        port=587,
        username="user@example.com",
        password="badpassword",
        sender="sender@example.com",
        recipient="dest@example.com",
    )
    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        import smtplib
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Auth failed")
        mock_smtp_cls.return_value = mock_server
        mock_server.__enter__.return_value = mock_server

        result = notifier.send_email("Test Subject", "Plain content")
        assert result.success is False
        assert result.status == "FAILED"
        assert "Auth failed" in result.error_message


def test_delivery_service_independent_channels(sample_settings: Settings):
    service = DeliveryService(sample_settings)

    # Mock telegram success and email failure
    with patch.object(service.telegram, "deliver_digest") as mock_tg, \
         patch.object(service.email, "send_email") as mock_em:

        from daily_tech_brief.models import DeliveryResult
        mock_tg.return_value = DeliveryResult("telegram", True, "SUCCESS")
        mock_em.return_value = DeliveryResult("email", False, "FAILED", error_message="Timeout")

        results = service.deliver_all(
            subject="Brief",
            telegram_chunks=["chunk1"],
            plain_text="plain",
            email_html="html",
        )

        assert results["telegram"].success is True
        assert results["email"].success is False
        mock_tg.assert_called_once()
        mock_em.assert_called_once()


def test_delivery_service_skips_successful_on_retry(sample_settings: Settings):
    service = DeliveryService(sample_settings)

    with patch.object(service.telegram, "deliver_digest") as mock_tg, \
         patch.object(service.email, "send_email") as mock_em:

        from daily_tech_brief.models import DeliveryResult
        mock_em.return_value = DeliveryResult("email", True, "SUCCESS")

        # Telegram already succeeded in previous run
        results = service.deliver_all(
            subject="Brief",
            telegram_chunks=["chunk1"],
            plain_text="plain",
            email_html="html",
            skip_channels=["telegram"],
        )

        # Telegram was skipped
        mock_tg.assert_not_called()
        # Email was attempted
        mock_em.assert_called_once()
        assert results["email"].success is True
