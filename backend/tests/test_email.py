import logging

from app.services.email import ConsoleEmailSender


async def test_console_email_sender_logs_content(caplog) -> None:
    sender = ConsoleEmailSender()
    with caplog.at_level(logging.INFO):
        await sender.send(to="a@b.test", subject="Bienvenue", body_text="Voici le lien : https://x")
    assert "a@b.test" in caplog.text
    assert "https://x" in caplog.text
