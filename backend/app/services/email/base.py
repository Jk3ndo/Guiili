from __future__ import annotations

from abc import ABC, abstractmethod


class EmailSender(ABC):
    @abstractmethod
    async def send(self, *, to: str, subject: str, body_text: str) -> None: ...
