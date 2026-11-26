"""The SMTP adapter, against a fake smtplib (no network, no database)."""

import logging
import smtplib
from email.message import EmailMessage
from typing import Any, ClassVar, Self

import pytest

from app.core.config import Settings
from app.domain.errors import ServiceUnavailable
from app.services import mailer as mailer_module
from app.services.mailer import Mailer

SMTP2GO = {
    "smtp_host": "mail.smtp2go.com",
    "smtp_port": 2525,
    "smtp_username": "playmate",
    "smtp_password": "s3cret-password",
    "smtp_from_email": "PlayMate Sports <no-reply@example.com>",
}


class FakeSMTP:
    """Records what the mailer does; `fail_with` simulates a server error."""

    instances: ClassVar[list["FakeSMTP"]] = []
    fail_with: ClassVar[Exception | None] = None

    def __init__(self, host: str, port: int, **kwargs: Any) -> None:
        self.host, self.port, self.kwargs = host, port, kwargs
        self.calls: list[str] = []
        self.sent: list[EmailMessage] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.calls.append("quit")

    def starttls(self, **_: object) -> None:
        self.calls.append("starttls")

    def login(self, username: str, password: str) -> None:
        self.calls.append(f"login:{username}")
        if FakeSMTP.fail_with is not None:
            raise FakeSMTP.fail_with

    def send_message(self, message: EmailMessage) -> None:
        self.calls.append("send")
        self.sent.append(message)


class FakeSMTPSSL(FakeSMTP):
    pass


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.instances = []
    FakeSMTP.fail_with = None
    monkeypatch.setattr(mailer_module.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer_module.smtplib, "SMTP_SSL", FakeSMTPSSL)
    # The migration fixtures run Alembic's fileConfig, which disables loggers
    # that already exist; production runs migrations in a separate process.
    monkeypatch.setattr(mailer_module.logger, "disabled", False)


async def test_smtp2go_on_2525_upgrades_with_starttls_then_sends() -> None:
    await Mailer(Settings(**SMTP2GO)).send_access_code(recipient="ana@example.com", code="AB2345CD")

    [client] = FakeSMTP.instances
    assert type(client) is FakeSMTP
    assert (client.host, client.port) == ("mail.smtp2go.com", 2525)
    assert client.calls == ["starttls", "login:playmate", "send", "quit"]
    message = client.sent[0]
    assert message["To"] == "ana@example.com"
    assert message["From"] == SMTP2GO["smtp_from_email"]
    assert "AB2345CD" in message.get_content()
    assert "5 minutes" in message.get_content()


async def test_port_465_uses_implicit_tls_without_starttls() -> None:
    settings = Settings(**{**SMTP2GO, "smtp_port": 465})
    await Mailer(settings).send_access_code(recipient="ana@example.com", code="AB2345CD")

    [client] = FakeSMTP.instances
    assert type(client) is FakeSMTPSSL
    assert "context" in client.kwargs
    assert client.calls == ["login:playmate", "send", "quit"]


async def test_starttls_can_be_turned_off_for_a_local_relay() -> None:
    settings = Settings(**{**SMTP2GO, "smtp_starttls": False})
    await Mailer(settings).send_access_code(recipient="ana@example.com", code="AB2345CD")
    assert FakeSMTP.instances[0].calls == ["login:playmate", "send", "quit"]


async def test_missing_settings_refuse_without_connecting() -> None:
    settings = Settings(**{**SMTP2GO, "smtp_password": None})
    with pytest.raises(ServiceUnavailable, match="not configured"):
        await Mailer(settings).send_access_code(recipient="ana@example.com", code="X")
    assert FakeSMTP.instances == []


async def test_a_delivery_failure_is_logged_without_the_password(
    caplog: pytest.LogCaptureFixture,
) -> None:
    FakeSMTP.fail_with = smtplib.SMTPAuthenticationError(535, b"Authentication failed")
    with (
        caplog.at_level(logging.WARNING, logger="app.services.mailer"),
        pytest.raises(ServiceUnavailable, match="temporarily unavailable"),
    ):
        await Mailer(Settings(**SMTP2GO)).send_access_code(
            recipient="ana@example.com", code="AB2345CD"
        )
    [record] = caplog.records
    text = record.getMessage()
    assert "mail.smtp2go.com:2525" in text
    assert "SMTPAuthenticationError" in text and "535" in text
    assert SMTP2GO["smtp_password"] not in text
    assert "AB2345CD" not in text
