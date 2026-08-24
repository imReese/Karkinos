"""Notification delivery contract shared by factories and adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Notifier(ABC):
    """Abstract delivery port for user-facing notifications."""

    @abstractmethod
    def send(self, title: str, message: str) -> None:
        """Deliver one notification."""
