import logging

import pytest

from app.api.deps import get_email_sender
from app.config import get_settings
from app.services.email import ConsoleEmailSender


async def test_console_email_sender_logs_content(caplog) -> None:
    sender = ConsoleEmailSender()
    with caplog.at_level(logging.INFO):
        await sender.send(to="a@b.test", subject="Bienvenue", body_text="Voici le lien : https://x")
    assert "a@b.test" in caplog.text
    assert "https://x" in caplog.text


def test_get_email_sender_local_returns_console(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "local")
    assert isinstance(get_email_sender(settings), ConsoleEmailSender)


def test_get_email_sender_non_local_raises(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(RuntimeError):
        get_email_sender(settings)
