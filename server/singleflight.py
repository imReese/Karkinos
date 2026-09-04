"""Small thread-safe completion primitive for read-side single-flight work."""

from __future__ import annotations

from concurrent.futures import Future
from typing import Generic, TypeVar

T = TypeVar("T")


class SingleFlightCompletion(Generic[T]):
    """Expose completion semantics without leaking a mutable ``Future``.

    The owner of a flight completes it once, while concurrent readers only wait
    for the immutable result.  Keeping this synchronization detail outside the
    projection layer prevents concurrency state transitions from looking like
    persistence mutations in read-model code.
    """

    def __init__(self) -> None:
        self._future: Future[T] = Future()

    def wait(self) -> T:
        """Wait for and return the owner's result, or re-raise its failure."""

        return self._future.result()

    def succeed(self, value: T) -> None:
        """Complete the flight successfully."""

        self._future.set_result(value)

    def fail(self, error: BaseException) -> None:
        """Complete the flight with the owner's original failure."""

        self._future.set_exception(error)


__all__ = ["SingleFlightCompletion"]
