"""Canonical portfolio-equity series helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def canonicalize_equity_curve(
    values: Iterable[tuple[Any, Any]],
) -> list[tuple[Any, Any]]:
    """Keep the final portfolio value for each timestamp.

    Multi-asset backtests process one MarketEvent per symbol. That event-level
    sequence is useful for deterministic strategy execution, but it is not a
    valid performance time series because several portfolio observations share
    the same timestamp. Metrics and research evidence consume this canonical
    one-point-per-timestamp projection instead.
    """

    canonical: list[tuple[Any, Any]] = []
    previous_timestamp: Any | None = None
    for timestamp, equity in values:
        if previous_timestamp is not None and timestamp < previous_timestamp:
            raise ValueError("equity_curve_timestamp_not_monotonic")
        if canonical and timestamp == canonical[-1][0]:
            canonical[-1] = (timestamp, equity)
        else:
            canonical.append((timestamp, equity))
        previous_timestamp = timestamp
    return canonical


__all__ = ["canonicalize_equity_curve"]
