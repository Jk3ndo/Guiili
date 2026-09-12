from __future__ import annotations

import logging

from app.services.email.base import EmailSender

logger = logging.getLogger(__name__)


class ConsoleEmailSender(EmailSender):
    """Dev : logue le contenu (avec le lien) au lieu d'envoyer. Jamais de vrai reseau."""

    async def send(self, *, to: str, subject: str, body_text: str) -> None:
        logger.info("EMAIL (console) to=%s subject=%s\n%s", to, subject, body_text)
