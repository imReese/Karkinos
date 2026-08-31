"""Shared idempotency failure contract."""


class IdempotencyConflict(ValueError):
    """Raised when one idempotency key is reused with different immutable input."""


__all__ = ["IdempotencyConflict"]
