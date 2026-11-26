"""Small SMTP adapter used for one-time access codes.

It deliberately uses Python's standard library so SMTP2GO, SES SMTP,
Postmark and other conventional SMTP providers work without
provider-specific code.

Connection security follows the port: 465, 8465 and 443 are implicit TLS
(SMTP over SSL); any other port, such as SMTP2GO's default 2525 or 587,
upgrades with STARTTLS unless `PLAYUP_SMTP_STARTTLS=false`.
"""

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from app.core.config import Settings
from app.domain.errors import ServiceUnavailable

logger = logging.getLogger(__name__)

#: Ports where the TLS handshake happens before any SMTP command.
IMPLICIT_TLS_PORTS = frozenset({465, 8465, 443})
TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class SmtpConfig:
    """Settings once they are known to be complete."""

    host: str
    port: int
    username: str
    password: str
    from_email: str
    starttls: bool

    @property
    def implicit_tls(self) -> bool:
        return self.port in IMPLICIT_TLS_PORTS

    @classmethod
    def from_settings(cls, settings: Settings) -> "SmtpConfig | None":
        if not (
            settings.smtp_host
            and settings.smtp_username
            and settings.smtp_password
            and settings.smtp_from_email
        ):
            return None
        return cls(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            from_email=settings.smtp_from_email,
            starttls=settings.smtp_starttls,
        )


class Mailer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send_access_code(self, *, recipient: str, code: str) -> None:
        config = SmtpConfig.from_settings(self.settings)
        if config is None:
            raise ServiceUnavailable("Email delivery is not configured")
        await asyncio.to_thread(self._send_access_code, config, recipient, code)

    def _message(self, config: SmtpConfig, recipient: str, code: str) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = "Your PlayMate Sports access code"
        message["From"] = config.from_email
        message["To"] = recipient
        message.set_content(
            "Your PlayMate Sports access code is "
            f"{code}. It expires in {self.settings.access_code_ttl_minutes} minutes."
        )
        return message

    def _send_access_code(self, config: SmtpConfig, recipient: str, code: str) -> None:
        message = self._message(config, recipient, code)
        context = ssl.create_default_context()
        try:
            client: smtplib.SMTP
            if config.implicit_tls:
                client = smtplib.SMTP_SSL(
                    config.host, config.port, timeout=TIMEOUT_SECONDS, context=context
                )
            else:
                client = smtplib.SMTP(config.host, config.port, timeout=TIMEOUT_SECONDS)
            with client:
                if not config.implicit_tls and config.starttls:
                    client.starttls(context=context)
                client.login(config.username, config.password)
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            # The reason (refused connection, 535 bad credentials, timeout)
            # goes to the log; the client only learns that delivery failed.
            # smtplib errors never include the password.
            logger.warning(
                "Access code email to %s via %s:%s failed: %s: %s",
                recipient,
                config.host,
                config.port,
                type(error).__name__,
                error,
            )
            raise ServiceUnavailable("Email delivery is temporarily unavailable") from error
