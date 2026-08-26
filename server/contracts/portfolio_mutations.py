"""Shared errors for exact portfolio command identities."""


class PortfolioMutationConflict(ValueError):
    """Raised when a command identity or aggregate mutation conflicts."""


__all__ = ["PortfolioMutationConflict"]
