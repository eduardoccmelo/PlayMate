"""Small SMTP adapter used for one-time access codes.

It deliberately uses Python's standard library so SES SMTP, Postmark, and
other conventional SMTP providers work without provider-specific code.
"""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import Settings
from app.domain.errors import ServiceUnavailable


class Mailer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send_access_code(self, *, recipient: str, code: str) -> None:
        if not self.settings.has_smtp:
            raise ServiceUnavailable("Email delivery is not configured")
        await asyncio.to_thread(self._send_access_code, recipient, code)

    def _send_access_code(self, recipient: str, code: str) -> None:
        message = EmailMessage()
        message["Subject"] = "Your PlayMate access code"
        message["From"] = self.settings.smtp_from_email
        message["To"] = recipient
        message.set_content(
            "Your PlayMate access code is "
            f"{code}. It expires in {self.settings.access_code_ttl_minutes} minutes."
        )

        try:
            with smtplib.SMTP(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=10,
            ) as client:
                if self.settings.smtp_starttls:
                    client.starttls(context=ssl.create_default_context())
                client.login(self.settings.smtp_username, self.settings.smtp_password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise ServiceUnavailable("Email delivery is temporarily unavailable") from error
