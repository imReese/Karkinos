"""Sanitized failure vocabulary shared by reviewed external research edges."""


class ExternalResearchAuthenticationError(RuntimeError):
    pass


class ExternalResearchRateLimitedError(RuntimeError):
    pass


class ExternalResearchHttpError(RuntimeError):
    pass


class ExternalResearchTimeoutError(RuntimeError):
    pass


class ExternalResearchNetworkError(RuntimeError):
    pass


class ExternalResearchInvalidResponseError(RuntimeError):
    pass


__all__ = [
    "ExternalResearchAuthenticationError",
    "ExternalResearchHttpError",
    "ExternalResearchInvalidResponseError",
    "ExternalResearchNetworkError",
    "ExternalResearchRateLimitedError",
    "ExternalResearchTimeoutError",
]
