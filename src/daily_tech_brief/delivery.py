"""Delivery engine for Telegram Bot API and SMTP Email with independent retry support."""

from __future__ import annotations

import logging
import smtplib
import time
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

import requests

from daily_tech_brief.config import Settings
from daily_tech_brief.models import DeliveryResult

logger = logging.getLogger(__name__)


def mask_token(token: str) -> str:
    """Mask sensitive token for secure logging."""
    if not token or len(token) < 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"


class TelegramNotifier:
    """Delivers digests via Telegram Bot API with chunk splitting and safe fallbacks."""

    def __init__(self, bot_token: str, chat_id: str, timeout_seconds: int = 20) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout_seconds

    def _api_url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.bot_token}/{method}"

    def send_message(self, text: str, parse_mode: str = "HTML") -> Dict[str, Any]:
        """Send a single message via Telegram Bot API with retry on 429/5xx."""
        url = self._api_url("sendMessage")
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False,
        }

        retries = 2
        for attempt in range(retries + 1):
            try:
                res = requests.post(url, json=payload, timeout=self.timeout)
                
                # Check for rate limiting
                if res.status_code == 429:
                    retry_after = res.json().get("parameters", {}).get("retry_after", 3)
                    logger.warning(f"Telegram 429 rate limit. Waiting {retry_after}s...")
                    time.sleep(float(retry_after))
                    continue

                if res.status_code >= 500 and attempt < retries:
                    time.sleep(2.0 * (attempt + 1))
                    continue

                if not res.ok:
                    err_json = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
                    err_desc = err_json.get("description", res.text)

                    # If HTML parsing failed, fall back to plain text
                    if parse_mode == "HTML" and "can't parse entities" in err_desc.lower():
                        logger.warning("Telegram failed to parse HTML. Retrying with plain text.")
                        payload["parse_mode"] = None
                        fallback_res = requests.post(url, json=payload, timeout=self.timeout)
                        fallback_res.raise_for_status()
                        return fallback_res.json()

                    res.raise_for_status()

                return res.json()

            except Exception as e:
                if attempt == retries:
                    masked_url = f"https://api.telegram.org/bot{mask_token(self.bot_token)}/sendMessage"
                    logger.error(f"Telegram send failure to {masked_url}: {e}")
                    raise

        raise RuntimeError("Telegram retries exhausted")

    def deliver_digest(self, message_chunks: List[str]) -> DeliveryResult:
        """Send multi-part digest chunks sequentially."""
        last_msg_id = None
        try:
            for idx, chunk in enumerate(message_chunks):
                resp = self.send_message(chunk, parse_mode="HTML")
                msg_id = str(resp.get("result", {}).get("message_id", ""))
                if msg_id:
                    last_msg_id = msg_id
                # Polite pacing between chunks
                if idx < len(message_chunks) - 1:
                    time.sleep(0.5)

            return DeliveryResult(
                channel="telegram",
                success=True,
                status="SUCCESS",
                message_id=last_msg_id,
            )
        except Exception as e:
            return DeliveryResult(
                channel="telegram",
                success=False,
                status="FAILED",
                error_message=str(e),
            )

    def send_test_message(self) -> DeliveryResult:
        """Send a lightweight test message to verify credentials."""
        test_text = (
            "🤖 <b>Daily Tech Brief Test</b>\n\n"
            "Telegram bot integration is working properly! ✅\n"
            "Ready for scheduled 9:00 AM IST deliveries."
        )
        return self.deliver_digest([test_text])


class EmailNotifier:
    """Delivers multipart plain-text & responsive HTML emails via SMTP."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        recipient: str,
        timeout_seconds: int = 25,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender or username
        self.recipient = recipient
        self.timeout = timeout_seconds

    def send_email(self, subject: str, plain_content: str, html_content: Optional[str] = None) -> DeliveryResult:
        """Connect to SMTP server, authenticate, and deliver multipart message."""
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = self.sender
            msg["To"] = self.recipient
            msg.set_content(plain_content)

            if html_content:
                msg.add_alternative(html_content, subtype="html")

            # Determine TLS / STARTTLS based on port
            if self.port == 465:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
                server.ehlo()
                server.starttls()
                server.ehlo()

            with server:
                if self.username and self.password:
                    server.login(self.username, self.password)
                server.send_message(msg)

            logger.info(f"Email successfully delivered to {self.recipient}")
            return DeliveryResult(
                channel="email",
                success=True,
                status="SUCCESS",
            )
        except Exception as e:
            logger.error(f"SMTP delivery failed to {self.host}:{self.port}: {e}")
            return DeliveryResult(
                channel="email",
                success=False,
                status="FAILED",
                error_message=str(e),
            )

    def send_test_message(self) -> DeliveryResult:
        """Send a lightweight test email."""
        subject = "Daily Tech Brief — Test Delivery"
        plain = "This is a test message from Daily Tech Brief. SMTP delivery is configured correctly!"
        html_body = "<h3>Daily Tech Brief Test</h3><p>SMTP email delivery is working properly! &check;</p>"
        return self.send_email(subject, plain, html_body)


class DeliveryService:
    """Orchestrates independent delivery across Telegram and Email."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.telegram = (
            TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
            if settings.telegram_bot_token and settings.telegram_chat_id
            else None
        )
        self.email = (
            EmailNotifier(
                host=settings.email_host,
                port=settings.email_port,
                username=settings.email_username,
                password=settings.email_password,
                sender=settings.email_sender or settings.email_username,
                recipient=settings.email_recipient,
            )
            if settings.email_host and settings.email_username and settings.email_password and settings.email_recipient
            else None
        )

    def deliver_all(
        self,
        subject: str,
        telegram_chunks: List[str],
        plain_text: str,
        email_html: str,
        skip_channels: Optional[List[str]] = None,
    ) -> Dict[str, DeliveryResult]:
        """Deliver to all configured channels independently, skipping any already succeeded."""
        skipped = skip_channels or []
        results: Dict[str, DeliveryResult] = {}

        # 1. Telegram
        if "telegram" not in skipped:
            if self.telegram:
                results["telegram"] = self.telegram.deliver_digest(telegram_chunks)
            else:
                err = "Telegram credentials not configured."
                logger.warning(err)
                results["telegram"] = DeliveryResult("telegram", False, "FAILED", error_message=err)

        # 2. Email
        if "email" not in skipped:
            if self.email:
                results["email"] = self.email.send_email(subject, plain_text, email_html)
            else:
                err = "Email credentials not configured."
                logger.warning(err)
                results["email"] = DeliveryResult("email", False, "FAILED", error_message=err)

        return results
